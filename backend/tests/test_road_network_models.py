from datetime import datetime, timezone

import pytest
from sqlalchemy.exc import IntegrityError

from app.models.road_network import RoadAccessGroup, RoadAccessMembership, RoadNetworkVersion
from test_case_results import db_session, result_data  # noqa: F401


def network(**changes):
    return RoadNetworkVersion(**{'id': 'graph-1', 'group_id': 1, 'policy_revision': 1,
        'public_bundle_id': 1, 'input_sha256': 'a' * 64, 'conditions_sha256': 'b' * 64,
        'source_manifest': {}, 'engine_version': 'valhalla-test', 'builder_version': 'test',
        'status': 'building', 'valid_from': datetime(2026, 9, 11, tzinfo=timezone.utc), **changes})


def test_groups_not_automatically_inherited_from_data_visibility(db_session, result_data):
    assert db_session.query(RoadAccessMembership).count() == 0
    db_session.add(RoadAccessGroup(id=1, name='合成通行组'))
    db_session.commit()
    db_session.add(network())
    db_session.commit()
    assert db_session.query(RoadAccessMembership).count() == 0


@pytest.mark.parametrize('changes', [
    {'status': 'ready'}, {'status': 'unknown'}, {'policy_revision': 0},
    {'valid_until': datetime(2026, 9, 10, tzinfo=timezone.utc)},
])
def test_invalid_graph_state_rejected_by_database(db_session, result_data, changes):
    db_session.add(RoadAccessGroup(id=1, name='合成通行组'))
    db_session.commit()
    db_session.add(network(**changes))
    with pytest.raises(IntegrityError):
        db_session.commit()
    db_session.rollback()


def test_duplicate_graph_inputs_do_not_create_two_versions(db_session, result_data):
    db_session.add(RoadAccessGroup(id=1, name='合成通行组'))
    db_session.commit()
    db_session.add(network())
    db_session.commit()
    db_session.add(network(id='graph-2'))
    with pytest.raises(IntegrityError):
        db_session.commit()
    db_session.rollback()
