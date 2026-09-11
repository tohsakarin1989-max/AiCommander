from datetime import datetime, timedelta, timezone

import pytest

from app.models.deployment_advisor import TechDefenseSource, TechDefenseEventAggregate
from app.services.situation_change_service import closed_window
from app.services.tech_defense_change_service import tech_changes, tech_recommendations
from tests.test_case_search_page import search_db  # noqa: F401


def fixture(db):
    source = TechDefenseSource(source_key='test', name='合成设备摘要', operational_area_id=1, status='active')
    db.add(source)
    db.flush()
    window = closed_window(datetime(2026, 9, 11, 3, tzinfo=timezone.utc), 'daily')
    rows = []
    for start, offline in [(window.previous_start, 1), (window.current_start, 3)]:
        for index in range(2):
            left = start + timedelta(hours=12 * index)
            row = TechDefenseEventAggregate(source_id=source.id, operational_area_id=1,
                period_start=left, period_end=left + timedelta(hours=12), device_type='camera',
                online_count=10 - offline, offline_count=offline, alert_count=2,
                redacted_vehicle_event_count=0)
            db.add(row)
            rows.append(row)
    db.commit()
    db.info['authorized_area_ids'] = (1,)
    return window, rows


def test_stocks_are_not_summed_and_advice_has_no_spatial_claim(search_db):
    window, rows = fixture(search_db)
    result = tech_changes(search_db, 1, window)
    item = result['items'][0]
    assert item['state'] == 'comparable'
    assert item['current']['reported_online'] == 7
    assert item['current']['alert_count'] == 4
    assert item['offline_change'] == 2
    advice = tech_recommendations(result, '一区')
    assert len(advice) == 1 and len(advice[0]['evidence_refs']) == 4
    assert '不证明具体空间盲区' in advice[0]['expected_effect']


@pytest.mark.parametrize('failure', ['gap', 'overlap', 'population', 'negative'])
def test_incompatible_series_does_not_invent_change(search_db, failure):
    window, rows = fixture(search_db)
    if failure == 'gap':
        rows[-1].period_start += timedelta(hours=1)
    elif failure == 'overlap':
        rows[-1].period_start -= timedelta(hours=1)
    elif failure == 'population':
        rows[-1].online_count += 1
    else:
        rows[-1].alert_count = -1
    search_db.commit()
    result = tech_changes(search_db, 1, window)
    assert result['items'][0]['state'] == 'incomparable'
    assert 'offline_change' not in result['items'][0]
    assert tech_recommendations(result, '一区') == []


def test_unauthorized_and_missing_sources(search_db):
    window, rows = fixture(search_db)
    with pytest.raises(PermissionError):
        tech_changes(search_db, 2, window)
    search_db.query(TechDefenseEventAggregate).delete()
    search_db.commit()
    assert tech_changes(search_db, 1, window)['information_gaps']
