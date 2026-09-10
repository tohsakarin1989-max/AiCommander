"""v4.0 全库检索：分页、筛选和分类统计必须使用相同授权范围。"""
from datetime import datetime

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import app.models  # noqa: F401
from app.api import cases
from app.database import Base, get_db
from app.models.case import Case
from app.models.map_foundation import OperationalArea


@pytest.fixture
def search_db():
    engine = create_engine("sqlite://", poolclass=StaticPool,
                           connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    with sessionmaker(bind=engine)() as db:
        db.add_all([OperationalArea(id=1, code="one", name="一区"),
                    OperationalArea(id=2, code="two", name="二区")])
        db.commit()
        yield db
    engine.dispose()


def client_for(db):
    app = FastAPI()
    app.include_router(cases.router, prefix="/api/cases")

    def override():
        yield db

    app.dependency_overrides[get_db] = override
    return TestClient(app)


def add_case(db, number, **values):
    values = {"operational_area_id": 1, "occurred_time": datetime(2026, 9, 9, 12),
              "status": "pending", "case_type": "盗油", "oil_type": "原油", **values}
    item = Case(case_number=number, **values)
    db.add(item)
    db.flush()
    return item


def test_paging_searches_beyond_first_hundred_with_stable_order(search_db):
    for i in range(125):
        add_case(search_db, f"CASE-{i:03d}")
    search_db.commit()
    client = client_for(search_db)
    first = client.get("/api/cases/page", params={"page_size": 100})
    assert first.status_code == 200
    second = client.get("/api/cases/page", params={"page": 2, "page_size": 100}).json()
    assert first.json()["total"] == second["total"] == 125
    assert len(first.json()["items"]) == 100
    assert len(second["items"]) == 25
    assert first.json()["items"][0]["case_number"] == "CASE-124"
    assert not ({x["id"] for x in first.json()["items"]} & {x["id"] for x in second["items"]})
    found = client.get("/api/cases/page", params={"keyword": "CASE-000"}).json()
    assert found["total"] == 1
    assert found["items"][0]["case_number"] == "CASE-000"


def test_filters_and_facets_include_full_authorized_data_only(search_db):
    add_case(search_db, "A", status="pending")
    add_case(search_db, "B", status="resolved", oil_type="柴油")
    add_case(search_db, "SECRET", operational_area_id=2, case_type="隐藏类型")
    search_db.commit()
    search_db.info["authorized_area_ids"] = (1,)
    client = client_for(search_db)
    result = client.get("/api/cases/page", params=[("statuses", "resolved")]).json()
    assert result["total"] == 1
    assert result["items"][0]["case_number"] == "B"
    assert result["facets"]["statuses"] == {"pending": 1, "resolved": 1}
    assert result["facets"]["case_types"] == {"盗油": 2}
    denied = client.get("/api/cases/page", params={"operational_area_id": 2}).json()
    assert denied["total"] == 0
    assert denied["facets"]["case_types"] == {}
    assert client.get("/api/cases/page", params={"keyword": "SECRET"}).json()["total"] == 0
    search_db.info["authorized_area_ids"] = ()
    assert client.get("/api/cases/page").json()["total"] == 0


def test_multi_select_and_missing_geo_exclude_null_categories(search_db):
    add_case(search_db, "A", status="pending", latitude=46, longitude=125)
    add_case(search_db, "B", status="resolved")
    add_case(search_db, "C", status="failed", case_type=None)
    search_db.commit()
    response = client_for(search_db).get("/api/cases/page", params=[
        ("statuses", "resolved"), ("statuses", "failed"),
        ("case_types", "盗油"), ("has_geo", "false"),
    ])
    assert response.status_code == 200
    assert [x["case_number"] for x in response.json()["items"]] == ["B"]
    assert client_for(search_db).get("/api/cases/page", params={"has_geo": True}).json()["total"] == 1


@pytest.mark.parametrize("keyword", ["%", "_", "\\", "' OR 1=1 --"])
def test_search_treats_wildcards_and_sql_as_literal_text(search_db, keyword):
    add_case(search_db, "ordinary", description="正常描述")
    add_case(search_db, "match", description=f"样本{keyword}文字")
    search_db.commit()
    result = client_for(search_db).get("/api/cases/page", params={"keyword": keyword})
    assert result.status_code == 200
    assert result.json()["total"] == 1
    assert result.json()["items"][0]["case_number"] == "match"


def test_date_interval_is_half_open_and_normalizes_timezone(search_db):
    add_case(search_db, "before", occurred_time=datetime(2026, 9, 8, 15, 59))
    add_case(search_db, "first", occurred_time=datetime(2026, 9, 8, 16))
    add_case(search_db, "last", occurred_time=datetime(2026, 9, 9, 15, 59, 59))
    add_case(search_db, "next", occurred_time=datetime(2026, 9, 9, 16))
    search_db.commit()
    result = client_for(search_db).get("/api/cases/page", params={
        "start_date": "2026-09-09T00:00:00+08:00",
        "end_date": "2026-09-10T00:00:00+08:00",
    }).json()
    assert {x["case_number"] for x in result["items"]} == {"first", "last"}


@pytest.mark.parametrize("params", [
    {"page": 0}, {"page_size": 0}, {"page_size": 201}, {"keyword": "字" * 201},
    {"start_date": "2026-09-10T00:00:00", "end_date": "2026-09-09T00:00:00"},
])
def test_invalid_queries_are_rejected(search_db, params):
    assert client_for(search_db).get("/api/cases/page", params=params).status_code == 422


def test_empty_page_and_legacy_list_contract_remain_read_only(search_db):
    item = add_case(search_db, "only", quality_score=35)
    search_db.commit()
    client = client_for(search_db)
    result = client.get("/api/cases/page", params={"page": 5}).json()
    assert result["items"] == []
    assert result["total"] == 1
    assert isinstance(client.get("/api/cases/").json(), list)
    assert client.get(f"/api/cases/{item.id}").json()["case_number"] == "only"
    assert search_db.query(Case).one().quality_score == 35


def test_real_create_update_and_import_preserve_timezone_in_search(search_db, monkeypatch):
    from app.config import settings
    from app.services.case_service import CaseService

    monkeypatch.setattr(settings, "ENABLE_VECTOR_DB", False)
    monkeypatch.setattr(CaseService, "_refresh_chain_links", lambda *args: None)
    client = client_for(search_db)
    created = client.post("/api/cases/", json={
        "occurred_time": "2026-09-09T20:00:00+08:00",
        "report_time": "2026-09-09T21:00:00+08:00",
        "description": "时区回归样本", "operational_area_id": 1,
    })
    assert created.status_code == 200, created.text
    case_id = created.json()["id"]
    params = {"start_date": "2026-09-09T00:00:00+08:00",
              "end_date": "2026-09-10T00:00:00+08:00"}
    assert client.get("/api/cases/page", params=params).json()["total"] == 1
    assert len(client.get("/api/cases/", params=params).json()) == 1
    assert datetime.fromisoformat(created.json()["occurred_time"]).utcoffset().total_seconds() == 0
    assert search_db.get(Case, case_id).report_time == datetime(2026, 9, 9, 13)
    updated = client.put(f"/api/cases/{case_id}", json={
        "occurred_time": "2026-09-10T01:00:00+08:00",
    })
    assert updated.status_code == 200, updated.text
    assert client.get("/api/cases/page", params=params).json()["total"] == 0
    imported = client.post("/api/cases/import?operational_area_id=1", files={
        "file": ("timezone.csv", "occurred_time,description\n2026-09-09T23:30:00+08:00,导入时区样本\n".encode(), "text/csv"),
    })
    assert imported.status_code == 200, imported.text
    assert imported.json()["created"] == 1, imported.text
    assert client.get("/api/cases/page", params=params).json()["total"] == 1
    assert len(client.get("/api/cases/", params=params).json()) == 1


def test_pipeline_hash_is_stable_for_equivalent_timezone_representations(search_db, monkeypatch):
    from app.config import settings
    from app.models.case_pipeline import OutboxEvent
    from app.services.case_pipeline_service import CasePipelineService
    from app.services.case_service import CaseService

    monkeypatch.setattr(settings, "ENABLE_VECTOR_DB", False)
    monkeypatch.setattr(CaseService, "_refresh_chain_links", lambda *args: None)
    item = CaseService.create_case(search_db, "TIME-HASH", datetime.fromisoformat("2026-09-09T20:00:00+08:00"),
                                   operational_area_id=1, description="合成时间哈希样本")
    event = search_db.query(OutboxEvent).filter(OutboxEvent.aggregate_id == str(item.id)).one()
    assert event.payload["source_hash"] == CasePipelineService.source_hash(search_db, item)
    original_hash = event.payload["source_hash"]
    updated = CaseService.update_case(search_db, item.id,
        occurred_time=datetime.fromisoformat("2026-09-09T12:00:00+00:00"))
    assert CasePipelineService.source_hash(search_db, updated) == original_hash
    assert search_db.query(OutboxEvent).count() == 1
