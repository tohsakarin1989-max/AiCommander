"""Lightweight catalog contracts, using isolated synthetic material sources."""
from contextlib import contextmanager
from copy import deepcopy
from datetime import datetime, timedelta

import pytest
from sqlalchemy import event

from app.models.conclusion import Conclusion
from app.models.deployment_advisor import SituationBrief
from app.models.knowledge_asset import KnowledgeAsset
from app.models.meeting import Meeting
from app.models.report import Report
from app.services import analysis_topic_service as topics
from app.services import intelligent_query_tasks as queries
from app.services import result_catalog
from app.services.facility_material_service import freeze_facility
from tests.test_intelligent_query_tasks import query_db, search_db  # noqa: F401
from tests.test_query_followup import FINISH, call, model_for
from tests.test_result_materials_v65 import (  # noqa: F401
    client,
    facility,
    material_db,
    saved_case,
)


@contextmanager
def no_sql_writes(db):
    """Observe actual statements, including writes not tracked by the ORM."""
    writes = []

    def observe(conn, cursor, statement, parameters, context, many):
        if statement.lstrip().lower().startswith(("insert", "update", "delete")):
            writes.append(statement)

    event.listen(db.bind, "before_cursor_execute", observe)
    try:
        yield
    finally:
        event.remove(db.bind, "before_cursor_execute", observe)
    assert writes == []
    assert not db.new and not db.dirty and not db.deleted


def forbid_document_builds(monkeypatch):
    def forbidden(*args, **kwargs):
        pytest.fail("catalog must not construct a document or map")

    for module, name in (
        ("app.services.case_result_document", "build_case_result_document"),
        ("app.services.topic_document", "build_topic_document"),
        ("app.services.intelligent_query_document", "build_query_document"),
        ("app.services.typed_material_document", "build"),
        ("app.services.result_map_service", "attach_map"),
    ):
        monkeypatch.setattr(f"{module}.{name}", forbidden)


async def seed_all_kinds(db):
    case, result = saved_case(db, "目录合成案件")
    asset = facility(db)
    frozen, _ = freeze_facility(db, asset.id, idempotency_key="catalog-all-kinds")
    meeting = Meeting(
        meeting_id="catalog-meeting", operational_area_id=1, case_ids=[case.id]
    )
    db.add(meeting)
    db.flush()
    report = Report(
        meeting_id=meeting.meeting_id,
        report_type="comprehensive",
        content={"summary": "会议正文标记-ABC"},
    )
    conclusion = Conclusion(
        case_id=case.id,
        meeting_id=meeting.meeting_id,
        summary="历史结论正文标记-ABC",
        evidence={},
        status="published",
    )
    experience = KnowledgeAsset(
        asset_type="case_report",
        source_case_id=case.id,
        version=1,
        title="历史案件报告",
        content={"markdown": "旧报告正文标记-ABC"},
        evidence_refs=[],
        source_signature="a" * 64,
        source_data_version="b" * 64,
        status="archived",
    )
    brief = SituationBrief(
        id="catalog-situation",
        operational_area_id=1,
        period_type="daily",
        period_start=datetime(2026, 9, 1),
        period_end=datetime(2026, 9, 2),
        input_fingerprint="c" * 64,
        status="completed",
        summary="态势正文标记-ABC",
        comparison_snapshot={
            "current": {"case_ids": [case.id], "case_count": 1},
            "previous": {"case_ids": []},
        },
        evidence_refs=[f"case:{case.id}"],
        information_gaps=[],
    )
    db.add_all([report, conclusion, experience, brief])
    db.commit()
    topic = topics.create_topic(db, "目录专题", {})
    assert topics.refresh_topic(db, topic["id"])["status"] == "updated"
    snapshot = topics.read_topic(db, topic["id"])["snapshot"]
    query = queries.create_query(db, "统计案件数")
    await queries.execute_query(
        db, query["id"], model=model_for(call("count_cases", {}), FINISH)
    )
    return {
        "case": result["id"],
        "topic": snapshot["id"],
        "facility": frozen.id,
        "situation": brief.id,
        "meeting": str(report.id),
        "query": query["id"],
        "experience": str(experience.id),
        "conclusion": str(conclusion.id),
    }


@pytest.mark.asyncio
async def test_all_eight_kinds_list_without_document_or_map_builds(
    material_db, monkeypatch
):
    identifiers = await seed_all_kinds(material_db)
    before = {
        kind: result_catalog.read_result(material_db, kind, identifier)
        for kind, identifier in identifiers.items()
    }
    forbid_document_builds(monkeypatch)
    with no_sql_writes(material_db):
        listing = result_catalog.catalog(material_db, limit=100)
    assert {item["kind"]: item["id"] for item in listing["items"]} == identifiers
    assert listing["has_more"] is False
    for item in listing["items"]:
        assert item["content_sha256"] == before[item["kind"]]["content_sha256"]
        assert item["title"] == before[item["kind"]]["title"]
        assert "document" not in item and "body" not in item
        assert item["catalog_projection"]["state"] == "legacy_fallback"
        assert "schema_version" in item["catalog_projection"]


@pytest.mark.asyncio
async def test_body_search_semantics_remain_for_every_material_kind(
    material_db, monkeypatch
):
    identifiers = await seed_all_kinds(material_db)
    needles = {
        "case": "合成井场",
        "topic": "frozen_topic_snapshot",
        "facility": "原油",
        "situation": "态势正文标记-abc",
        "meeting": "会议正文标记-abc",
        "query": "COUNT_CASES",
        "experience": "旧报告正文标记-abc",
        "conclusion": "历史结论正文标记-abc",
    }
    for kind, needle in needles.items():
        reader = result_catalog.read_result(material_db, kind, identifiers[kind])
        assert needle.casefold() not in reader["title"].casefold()
    forbid_document_builds(monkeypatch)
    with no_sql_writes(material_db):
        for kind, needle in needles.items():
            listing = result_catalog.catalog(material_db, kind=kind, query=f" {needle} ")
            assert [item["id"] for item in listing["items"]] == [identifiers[kind]], kind
            assert listing["has_more"] is False
        assert result_catalog.catalog(material_db, query="不存在的正文唯一标记")["items"] == []


def test_catalog_get_keeps_unindexed_history_without_writes(material_db, monkeypatch):
    _, result = saved_case(material_db)
    stored_content = deepcopy(result["content"])
    stored_digest = result["content_sha256"]
    forbid_document_builds(monkeypatch)
    with no_sql_writes(material_db), client(material_db) as http:
        response = http.get("/api/results", params={"kind": "case", "q": "合成井场"})
        assert response.status_code == 200
        assert response.headers["cache-control"] == "no-store"
        item = response.json()["items"][0]
        assert item["id"] == result["id"]
        assert item["content_sha256"] == stored_digest
        assert item["catalog_projection"]["state"] == "legacy_fallback"
    from app.services.case_result_service import CaseResultService

    saved = CaseResultService.read(material_db, result["id"])
    assert saved["content"] == stored_content
    assert saved["content_sha256"] == stored_digest


def test_source_revocation_precedes_pagination_and_has_more(material_db):
    asset = facility(material_db)
    unaffected, _ = freeze_facility(
        material_db, asset.id, idempotency_key="catalog-before-source"
    )
    material_db.commit()
    case, _ = saved_case(material_db, "将转移的共同来源")
    first, _ = freeze_facility(
        material_db, asset.id, idempotency_key="catalog-common-source-first"
    )
    second, _ = freeze_facility(
        material_db, asset.id, idempotency_key="catalog-common-source-second"
    )
    instant = datetime(2026, 9, 5)
    unaffected.created_at = instant
    first.created_at = instant + timedelta(minutes=1)
    second.created_at = instant + timedelta(minutes=2)
    first.title = "受限目录标记一"
    second.title = "受限目录标记二"
    material_db.commit()
    initial = result_catalog.catalog(material_db, kind="facility", limit=1)
    assert initial["items"][0]["id"] == second.id
    assert initial["has_more"] is True

    case.operational_area_id = 2
    material_db.commit()
    with no_sql_writes(material_db):
        visible = result_catalog.catalog(material_db, kind="facility", limit=1)
        assert [item["id"] for item in visible["items"]] == [unaffected.id]
        assert visible["has_more"] is False
        later = result_catalog.catalog(material_db, kind="facility", limit=1, offset=1)
        assert later["items"] == [] and later["has_more"] is False
        denied = result_catalog.catalog(material_db, kind="facility", query="受限目录标记")
        assert denied["items"] == [] and denied["has_more"] is False


def test_read_contract_and_saved_digest_are_unchanged_after_listing(material_db):
    _, result = saved_case(material_db)
    before, document = result_catalog._read(
        material_db, "case", result["id"], topic_document_preview=True
    )
    with no_sql_writes(material_db):
        listing = result_catalog.catalog(material_db, kind="case")
        after, repeated = result_catalog._read(
            material_db, "case", result["id"], topic_document_preview=False
        )
    assert before == after
    assert document == repeated
    assert listing["items"][0]["content_sha256"] == result["content_sha256"]
    assert document.content_sha256 == result["content_sha256"]


@pytest.mark.asyncio
@pytest.mark.parametrize('tool', ['find_business_results', 'read_business_result'])
async def test_query_source_validation_does_not_render_nested_materials(material_db, monkeypatch, tool):
    _, result = saved_case(material_db)
    args = {'kind': 'case'}
    if tool == 'read_business_result':
        args['identifier'] = result['id']
    task = queries.create_query(material_db, '已有成果来源')
    await queries.execute_query(material_db, task['id'], model=model_for(call(tool, args), FINISH))
    assert queries.read_query(material_db, task['id'])['result']['cards'][0]['state'] == 'ready'
    forbid_document_builds(monkeypatch)
    with no_sql_writes(material_db):
        items = result_catalog.catalog(material_db, kind='query')['items']
    assert [item['id'] for item in items] == [task['id']]
