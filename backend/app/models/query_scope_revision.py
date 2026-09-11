"""Database-enforced scope relocation revision; ordinary inserts do not invalidate queries."""
from sqlalchemy import BigInteger, CheckConstraint, Column, Integer, event

from app.database import Base


class QueryScopeRevision(Base):
    __tablename__ = 'query_scope_revision'
    __table_args__ = (CheckConstraint('id = 1', name='ck_query_scope_singleton'),)
    id = Column(Integer, primary_key=True)
    revision = Column(BigInteger, nullable=False, default=0)


def install_scope_revision_v1(connection):
    """Shared with migration 93e6a20fd53b; keep this contract immutable.

    Triggers cover ORM, bulk updates and direct SQL, inside the same transaction.
    Global invalidation on relocation/deletion is conservative; no row IDs or
    sensitive attributes are added to this table.
    """
    dialect = connection.dialect.name
    if dialect not in {'sqlite', 'postgresql'}:
        raise RuntimeError('query_scope_revision_database_unsupported')
    connection.exec_driver_sql('INSERT INTO query_scope_revision (id, revision) VALUES (1, 0) ON CONFLICT (id) DO NOTHING')
    if dialect == 'postgresql':
        connection.exec_driver_sql('''CREATE OR REPLACE FUNCTION aic_query_scope_changed_v1()
            RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN
            UPDATE query_scope_revision SET revision = revision + 1 WHERE id = 1;
            RETURN NULL; END $$''')
    for table in ('cases', 'jurisdiction_assets', 'map_snapshots'):
        for operation in ('update', 'delete'):
            name = f'aic_query_scope_{table}_{operation}_v1'
            if dialect == 'sqlite':
                condition = ' WHEN OLD.operational_area_id IS NOT NEW.operational_area_id' if operation == 'update' else ''
                connection.exec_driver_sql(f'''CREATE TRIGGER IF NOT EXISTS {name}
                    AFTER {operation.upper()} ON {table}{condition} BEGIN
                    UPDATE query_scope_revision SET revision = revision + 1 WHERE id = 1; END''')
            else:
                condition = ' WHEN (OLD.operational_area_id IS DISTINCT FROM NEW.operational_area_id)' if operation == 'update' else ''
                connection.exec_driver_sql(f'DROP TRIGGER IF EXISTS {name} ON {table}')
                connection.exec_driver_sql(f'''CREATE TRIGGER {name} AFTER {operation.upper()} ON {table}
                    FOR EACH ROW{condition} EXECUTE FUNCTION aic_query_scope_changed_v1()''')


@event.listens_for(Base.metadata, 'after_create')
def _install_for_created_metadata(metadata, connection, **kwargs):
    # create_all is the test/development fallback. Production uses Alembic.
    required = {'query_scope_revision', 'cases', 'jurisdiction_assets', 'map_snapshots'}
    tables = {table.name for table in kwargs.get('tables', metadata.tables.values())}
    if required.issubset(tables):
        install_scope_revision_v1(connection)
