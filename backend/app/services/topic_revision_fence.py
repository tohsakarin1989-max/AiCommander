"""Database-backed input generation prevents mixed-source publication.

This deliberately conservative fence covers new members as well as references
already present in a snapshot. It is not claimed to be precise incremental work.
"""
from sqlalchemy import event, inspect, select, text

from app.database import Base
from app.models.analysis_topic import TopicDataRevision


SOURCE_TABLES = (
    'cases', 'case_revisions', 'case_analysis_profiles', 'events',
    'jurisdiction_assets', 'jurisdiction_asset_versions', 'map_snapshots',
    'map_feature_claims', 'map_sources', 'facility_source_identities',
    'case_result_snapshots', 'case_road_artifacts', 'road_network_versions',
    'internal_road_feature_versions', 'internal_road_reviews', 'road_access_grants',
    'road_access_memberships', 'road_access_groups', 'case_facility_associations',
    'case_locations', 'oil_measurements', 'case_vehicles', 'case_persons',
    'case_evidence', 'source_references', 'evidence_objects', 'oil_recovery_records',
    'situation_briefs', 'knowledge_assets', 'case_history_indexes',
)
PG_LOCK_NAMESPACE = 20260930
PG_LOCK_KEY = 6401
PG_SEQUENCE = 'aic_topic_revision_seq_v64'


def install(connection):
    names = set(inspect(connection).get_table_names())
    if 'topic_data_revision' not in names:
        return
    dialect = connection.dialect.name
    connection.exec_driver_sql('INSERT INTO topic_data_revision (id, revision) VALUES (1, 0) ON CONFLICT (id) DO NOTHING')
    if dialect == 'postgresql':
        connection.exec_driver_sql(f'CREATE SEQUENCE IF NOT EXISTS {PG_SEQUENCE}')
        connection.exec_driver_sql(f"SELECT setval('{PG_SEQUENCE}', GREATEST(1, (SELECT revision FROM topic_data_revision WHERE id=1), (SELECT last_value FROM {PG_SEQUENCE})), true)")
        connection.exec_driver_sql(f'''CREATE OR REPLACE FUNCTION aic_topic_revision_v64()
            RETURNS TRIGGER AS $$ BEGIN
            PERFORM pg_advisory_xact_lock_shared({PG_LOCK_NAMESPACE}, {PG_LOCK_KEY});
            PERFORM nextval('{PG_SEQUENCE}');
            RETURN NULL; END; $$ LANGUAGE plpgsql''')
    for table in SOURCE_TABLES:
        if table not in names:
            continue
        if dialect == 'sqlite':
            for action in ('INSERT', 'UPDATE', 'DELETE'):
                name = f'aic_topic_{table}_{action.lower()}_v64'
                connection.exec_driver_sql(f'''CREATE TRIGGER IF NOT EXISTS {name}
                    AFTER {action} ON {table} BEGIN
                    UPDATE topic_data_revision SET revision=revision+1 WHERE id=1; END''')
        elif dialect == 'postgresql':
            name = f'aic_topic_{table}_v64'
            connection.exec_driver_sql(f'DROP TRIGGER IF EXISTS {name} ON {table}')
            connection.exec_driver_sql(f'''CREATE TRIGGER {name}
                BEFORE INSERT OR UPDATE OR DELETE ON {table}
                FOR EACH STATEMENT EXECUTE FUNCTION aic_topic_revision_v64()''')
        else:
            raise ValueError('topic_database_unsupported')


@event.listens_for(Base.metadata, 'after_create')
def _install_after_create(target, connection, **kwargs):
    install(connection)


def current_revision(db, *, lock=False):
    if db.get_bind().dialect.name == 'postgresql':
        if lock:
            db.execute(text('SELECT pg_advisory_xact_lock(:namespace, :key)'),
                       {'namespace': PG_LOCK_NAMESPACE, 'key': PG_LOCK_KEY})
        return db.scalar(text(f'SELECT last_value FROM {PG_SEQUENCE}'))
    # This is one global concurrency generation, not an authorized business row.
    # Read it on the same transaction's Connection so the Session does not attach
    # every case/asset scope predicate and rebuild their cache keys per flush.
    table = TopicDataRevision.__table__
    statement = select(table.c.revision).where(table.c.id == 1)
    value = db.connection().scalar(statement)
    if value is None:
        raise ValueError('topic_revision_fence_missing')
    return value
