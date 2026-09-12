"""日常处理卡只提示真实待办，旧画像不能绕过冻结成果证据鉴权。"""
import asyncio
import json
from copy import deepcopy

import pytest
from sqlalchemy import event, select

from app.config import settings
from app.models.case import Case
from app.models.conclusion import Conclusion
from app.services.case_processing_card_service import CaseProcessingCardService
from app.services.case_profile_service import CaseProfileService
from app.services.case_result_service import CaseResultService
from app.services.conclusion_factory_service import ConclusionFactoryService
from test_conclusion_result_reuse import current_profile, result_data  # noqa: F401


@pytest.fixture
def daily_case(db_session, current_profile, monkeypatch):
    monkeypatch.setattr(settings, "ENABLE_BONUS_ACCOUNTING", False)
    case = db_session.scalar(select(Case).where(Case.id == 1))
    case.quality_issues = {"score": 100, "missing_required": []}
    db_session.commit()
    return case


@pytest.mark.parametrize("experience", [None, {}, {"summary": "已有经验", "manual_review_status": "archived"}])
def test_missing_or_archived_optional_artifacts_do_not_create_work(
    db_session, daily_case, experience,
):
    daily_case.features = {"intelligence": {"experience_card": experience}} if experience is not None else None
    db_session.commit()
    profile = CaseProfileService.build_case_profile(db_session, daily_case.id, include_similar=False)
    processing = CaseProcessingCardService.build_processing_card(db_session, daily_case.id)
    assert profile["availability"]["needs_human_review"] is False
    assert processing["manual_review_required"] is False
    assert processing["status"] == "ready"
    assert processing["gap_groups"] == []
    assert processing["suggested_actions"] == []
    assert profile["knowledge_refs"]["reports"] == []


@pytest.mark.parametrize("status", [None, "draft", "pending", "needs_review", "flagged"])
def test_existing_experience_draft_keeps_its_review_entry(db_session, daily_case, status):
    daily_case.features = {"intelligence": {"experience_card": {
        "summary": "已有待复核经验，不是每案自动要求", "manual_review_status": status,
    }}}
    db_session.commit()
    profile = CaseProfileService.build_case_profile(db_session, daily_case.id, include_similar=False)
    processing = CaseProcessingCardService.build_processing_card(db_session, daily_case.id)
    assert profile["availability"]["needs_human_review"] is True
    assert {item["key"] for item in processing["gap_groups"]} == {"experience"}


@pytest.mark.parametrize("status", ["confirmed", "approved"])
def test_confirmed_experience_is_available_without_repeated_review(db_session, daily_case, status):
    daily_case.features = {"intelligence": {"experience_card": {
        "summary": "已确认经验", "manual_review_status": status,
    }}}
    db_session.commit()
    profile = CaseProfileService.build_case_profile(db_session, daily_case.id, include_similar=False)
    assert profile["availability"]["has_confirmed_experience"] is True
    assert profile["availability"]["needs_human_review"] is False


def test_actual_quality_gap_and_existing_conclusion_still_need_judgment(db_session, daily_case):
    daily_case.quality_issues = {"score": 60, "missing_required": [{"field": "oil_type", "label": "缺少油品"}]}
    db_session.add(Conclusion(case_id=daily_case.id, status="needs_review", summary="已有历史草稿", evidence={}))
    db_session.commit()
    profile = CaseProfileService.build_case_profile(db_session, daily_case.id, include_similar=False)
    processing = CaseProcessingCardService.build_processing_card(db_session, daily_case.id)
    assert profile["availability"]["needs_human_review"] is True
    assert {item["key"] for item in processing["gap_groups"]} == {"quality", "report"}
    assert profile["knowledge_refs"]["conclusions"][0]["summary"] == "已有历史草稿"


def test_existing_conclusion_alone_still_marks_review_needed(db_session, daily_case):
    db_session.add(Conclusion(case_id=daily_case.id, status="draft", summary="已有草稿", evidence={}))
    db_session.commit()
    profile = CaseProfileService.build_case_profile(db_session, daily_case.id, include_similar=False)
    assert profile["availability"]["needs_human_review"] is True
    assert CaseProcessingCardService.build_processing_card(db_session, daily_case.id)["manual_review_required"] is True


def test_revoked_source_hides_reused_conclusion_and_all_derived_counts(
    db_session, daily_case, result_data,
):
    result_data[2].evidence_refs = ["case:2"]
    result_data[2].claim = "仅另一辖区可见的候选内容"
    db_session.commit()
    CaseResultService.create_current(db_session, 1)
    db_session.commit()
    draft = asyncio.run(ConclusionFactoryService.generate_conclusion(db_session, 1))
    first = CaseProfileService.build_case_profile(db_session, 1, include_similar=False)
    assert first["knowledge_refs"]["conclusions"][0]["id"] == draft.id
    assert first["knowledge_refs"]["conclusions"][0]["confidence"] is None
    assert first["availability"]["needs_human_review"] is True

    db_session.info["authorized_area_ids"] = (1,)
    revoked = CaseProfileService.build_case_profile(db_session, 1, include_similar=False)
    processing = CaseProcessingCardService.build_processing_card(db_session, 1)
    assert revoked["knowledge_refs"]["conclusions"] == []
    assert revoked["source_map"]["conclusions"] == []
    assert revoked["availability"]["needs_human_review"] is False
    assert processing["manual_review_required"] is False
    assert processing["gap_groups"] == []
    assert "仅另一辖区可见的候选内容" not in json.dumps([revoked, processing], ensure_ascii=False)


def test_missing_saved_result_is_not_exposed_by_legacy_profile(db_session, daily_case):
    db_session.add(Conclusion(case_id=1, status="needs_review", summary="不应暴露", evidence={
        "source_result": {"result_id": "nonexistent-result", "content_sha256": "missing"},
    }))
    db_session.commit()
    profile = CaseProfileService.build_case_profile(db_session, 1, include_similar=False)
    assert profile["knowledge_refs"]["conclusions"] == []
    assert profile["availability"]["needs_human_review"] is False
    assert "不应暴露" not in json.dumps(profile, ensure_ascii=False)


def test_profile_and_processing_card_read_never_mutate_original_case(db_session, daily_case):
    daily_case.features = {"intelligence": {"experience_card": {"summary": "保留草稿", "manual_review_status": "draft"}}}
    db_session.commit()
    before = db_session.execute(Case.__table__.select()).mappings().all()
    original_features = deepcopy(daily_case.features)
    mutations = []

    def observe(conn, cursor, statement, parameters, context, executemany):
        if statement.lstrip().lower().startswith(("update ", "insert ", "delete ")):
            mutations.append(statement)

    event.listen(db_session.bind, "before_cursor_execute", observe)
    try:
        CaseProfileService.build_case_profile(db_session, 1, include_similar=False)
        CaseProcessingCardService.build_processing_card(db_session, 1)
    finally:
        event.remove(db_session.bind, "before_cursor_execute", observe)
    assert mutations == []
    assert daily_case.features == original_features
    assert db_session.execute(Case.__table__.select()).mappings().all() == before
