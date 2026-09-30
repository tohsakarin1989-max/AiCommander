"""Whole-scope counts, deduplication and unavailable-not-zero contracts."""
from datetime import datetime

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest
from sqlalchemy.exc import SQLAlchemyError

from app.api import events, reports
from app.database import get_db
from app.models.case import Case
from app.models.event import Event
from app.models.map_foundation import OperationalArea
from app.models.meeting import Meeting
from app.models.report import Report
from test_case_results import db_session  # noqa: F401


@pytest.fixture
def statistics_client(db_session):
    db_session.add_all([OperationalArea(id=i, code=f"STAT-{i}", name=f"合成{i}") for i in (1, 2)])
    db_session.flush()
    db_session.add_all([Case(id=i, case_number=f"STAT-{i}", occurred_time=datetime(2020, 1, 1),
                            description="合成统计样本", operational_area_id=i) for i in (1, 2)])
    db_session.flush()
    db_session.add_all([Meeting(meeting_id="m1", operational_area_id=1, case_ids=[1, 1], status="completed"),
                       Meeting(meeting_id="m2", operational_area_id=2, case_ids=[2], status="completed"),
                       Meeting(meeting_id="m-restricted-source", operational_area_id=1,
                               case_ids=[1, 2], status="completed")])
    db_session.flush()
    for index in range(105):
        db_session.add(Report(meeting_id="m1", report_type="summary", content={}, created_at=datetime(2020, 1, 1)))
        db_session.add(Event(event_number=f"S{index}", operational_area_id=1, event_type="oil_trace",
                             occurred_time=datetime(2020, 1, 1, 8), title="合成事件", related_case_id=1))
    db_session.add(Report(meeting_id="m2", report_type="summary", content={}))
    db_session.add(Report(meeting_id="m-restricted-source", report_type="summary", content={}))
    db_session.add(Event(event_number="outside-area", operational_area_id=2, event_type="oil_trace",
                        occurred_time=datetime(2020, 1, 1, 8), title="受限事件", related_case_id=2))
    db_session.add(Event(event_number="at-end", operational_area_id=1, event_type="tool_trace",
                        occurred_time=datetime(2020, 1, 2), title="截止边界事件"))
    db_session.commit()
    db_session.info["authorized_area_ids"] = (1,)
    app = FastAPI()
    app.include_router(reports.router, prefix="/api/reports")
    app.include_router(events.router, prefix="/api/events")
    app.dependency_overrides[get_db] = lambda: db_session
    with TestClient(app) as client:
        yield client


def test_report_counts_are_not_list_length_and_cases_are_distinct(statistics_client):
    client = statistics_client
    first = client.get("/api/reports/", params={"limit": 3}).json()
    assert len(first) == 3
    assert {item['meeting_id'] for item in first} == {'m1'}
    final = client.get('/api/reports/', params={'skip': 103, 'limit': 3}).json()
    assert len(final) == 2 and {item['meeting_id'] for item in final} == {'m1'}
    assert not {item['id'] for item in first} & {item['id'] for item in final}
    assert client.get('/api/reports/', params={'skip': 105, 'limit': 3}).json() == []
    response = client.get("/api/reports/statistics")
    assert response.status_code == 200, response.text
    data = response.json()
    assert data["total_reports"] == 105
    assert data["covered_cases"] == 1
    assert data["report_meetings"] == 1
    assert data["complete"] is True and data["cutoff"]


def test_event_list_and_statistics_share_half_open_authorized_scope(statistics_client):
    params = {"operational_area_id": 1, "start_date": "2020-01-01T00:00:00Z", "end_date": "2020-01-02T00:00:00Z"}
    first = statistics_client.get("/api/events/", params={**params, "limit": 1}).json()
    assert len(first) == 1
    response = statistics_client.get("/api/events/statistics", params={**params, "all_history": True})
    assert response.status_code == 200, response.text
    data = response.json()
    assert data["filtered_events"] == 105
    assert data["linked_case_count"] == 1
    assert data["by_type"] == {"oil_trace": 105}
    assert data["scope"]["end_exclusive"] is True
    assert statistics_client.get("/api/events/statistics", params={"operational_area_id": 2, "all_history": True}).status_code == 404
    assert statistics_client.get("/api/events/", params={"operational_area_id": 2}).status_code == 404


@pytest.mark.parametrize("url", ["/api/events/statistics", "/api/reports/statistics"])
def test_database_failure_is_not_a_successful_zero(statistics_client, db_session, monkeypatch, url):
    def broken(*args, **kwargs):
        raise SQLAlchemyError("sensitive-query-marker")
    monkeypatch.setattr(db_session, "query", broken)
    response = statistics_client.get(url)
    assert response.status_code == 503
    assert "sensitive-query-marker" not in response.text


def test_invalid_time_window_is_not_silently_widened(statistics_client):
    params = {"start_date": "2020-01-02", "end_date": "2020-01-01"}
    assert statistics_client.get("/api/events/statistics", params=params).status_code == 422
    assert statistics_client.get("/api/events/", params=params).status_code == 422
