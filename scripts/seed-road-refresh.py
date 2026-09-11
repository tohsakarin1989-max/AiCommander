"""Publish a NEW CATALOG VERSION of the same graph in an owned synthetic stack.

This exercises refresh and native recomputation, not a topology-change benchmark
or the separate candidate-file installation path.
"""
from datetime import datetime, timezone
import json
import os
import sys
from uuid import uuid4

sys.path.insert(0, '/app')

from sqlalchemy import select
from sqlalchemy.engine import make_url

from app.config import settings
from app.database import SessionLocal
from app.models.case_pipeline import OutboxEvent
from app.models.road_network import RoadNetworkVersion
from app.services.road_refresh_jobs import enqueue_publication


def main():
    project = os.environ.get('AIC_DISPOSABLE_STACK_PROJECT', '')
    url = make_url(settings.DATABASE_URL)
    assert project.startswith('aic-road-stack-') and url.database == project.replace('-', '_')
    assert url.host == 'postgres' and url.get_backend_name() == 'postgresql'
    with SessionLocal() as db:
        old = db.scalars(select(RoadNetworkVersion)).all()
        assert len(old) == 1 and old[0].status == 'ready'
        assert db.scalar(select(OutboxEvent.id).where(
            OutboxEvent.event_type == 'case.roads.compare', OutboxEvent.status == 'completed'))
        values = {column.name: getattr(old[0], column.name) for column in old[0].__table__.columns}
        identifier = str(uuid4())
        values.update(id=identifier, valid_from=datetime.now(timezone.utc),
                      created_at=datetime.now(timezone.utc),
                      # Deliberately distinct fixture build identity: the catalog
                      # correctly rejects duplicate input/build versions. This
                      # is not a claim that the graph was rebuilt by production.
                      builder_version=values['builder_version'] + '-refresh-fixture')
        db.add(RoadNetworkVersion(**values))
        db.flush()
        event_id = enqueue_publication(db, identifier, valid_from=values['valid_from'])
        assert event_id and enqueue_publication(db, identifier) is None
        db.commit()
        print(json.dumps({'network_id': identifier, 'refresh_event_id': event_id,
                          'graph_sha256': values['graph_sha256'],
                          'fixture_builder_identity': values['builder_version'],
                          'same_graph_new_catalog_version': True}), flush=True)


if __name__ == '__main__':
    main()
