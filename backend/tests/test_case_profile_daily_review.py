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
from app.services.case_quality_service import QUALITY_RULE_VERSION
from app.services.case_result_service import CaseResultService
from test_conclusion_result_reuse import saved_legacy
from app.api.cases import get_case_profile
from test_conclusion_result_reuse import current_profile, result_data  # noqa: F401


@pytest.fixture
def daily_case(db_session, current_profile, monkeypatch):
    monkeypatch.setattr(settings, "ENABLE_BONUS_ACCOUNTING", False)
    case = db_session.scalar(select(Case).where(Case.id == 1))
    case.quality_issues = {"rule_version": QUALITY_RULE_VERSION, "score": 100, "missing_required": []}
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
    daily_case.quality_issues = {"rule_version": QUALITY_RULE_VERSION, "score": 60,
                               "missing_required": [{"field": "source_type", "label": "线索来源待补充"}]}
    db_session.add(Conclusion(case_id=daily_case.id, status="needs_review", summary="已有历史草稿", evidence={}))
    db_session.commit()
    profile = CaseProfileService.build_case_profile(db_session, daily_case.id, include_similar=False)
    processing = CaseProcessingCardService.build_processing_card(db_session, daily_case.id)
    assert profile["availability"]["needs_human_review"] is True
    assert {item["key"] for item in processing["gap_groups"]} == {"quality"}
    assert profile["knowledge_refs"]["conclusions"][0]["summary"] == "已有历史草稿"


def test_legacy_investigation_gaps_remain_history_without_new_review(db_session, daily_case, monkeypatch):
    from app.services.case_quality_service import CaseQualityService

    original = {"rule_version": "case-quality-6.1", "score": 68, "missing_required": [
        {"field": "police_reported", "label": "是否报案"},
        {"field": "case_filed", "label": "是否立案"},
    ]}
    daily_case.quality_issues = deepcopy(original)
    db_session.commit()
    monkeypatch.setattr(CaseQualityService, "evaluate_case", lambda *args: pytest.fail("GET must not evaluate"))
    profile = CaseProfileService.build_case_profile(db_session, daily_case.id)
    assert profile["quality"]["state"] == "stale"
    assert profile["quality"]["historical_result"] == original
    assert profile["quality_gaps"] == []
    assert profile["availability"]["needs_human_review"] is False
    processing = CaseProcessingCardService.build_processing_card(db_session, daily_case.id)
    assert processing["gap_groups"] == []
    assert processing["status"] == "stale"
    assert processing["profile_snapshot"]["quality_state"] == "stale"
    assert daily_case.quality_issues == original


def test_old_factory_draft_does_not_require_another_review(db_session, daily_case):
    db_session.add(Conclusion(case_id=daily_case.id, status="draft", summary="已有草稿", evidence={}))
    db_session.commit()
    profile = CaseProfileService.build_case_profile(db_session, daily_case.id, include_similar=False)
    assert profile["availability"]["needs_human_review"] is False
    assert CaseProcessingCardService.build_processing_card(db_session, daily_case.id)["manual_review_required"] is False


def test_revoked_source_hides_reused_conclusion_and_all_derived_counts(
    db_session, daily_case, result_data,
):
    result_data[2].evidence_refs = ["case:2"]
    result_data[2].claim = "仅另一辖区可见的候选内容"
    db_session.commit()
    CaseResultService.create_current(db_session, 1)
    db_session.commit()
    draft = saved_legacy(db_session, CaseResultService.latest(db_session, 1), status="flagged")
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


@pytest.mark.parametrize("rule_version", [QUALITY_RULE_VERSION, "case-quality-6.1", None])
def test_profile_and_processing_card_read_never_mutate_original_case(db_session, daily_case, rule_version):
    daily_case.quality_issues = {**daily_case.quality_issues, "rule_version": rule_version}
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


def test_daily_profile_skips_duplicate_legacy_similarity(db_session, daily_case, monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("日常资料聚合不应重复检索历史案件")

    monkeypatch.setattr(CaseProfileService, "_safe_similar_cases", forbidden)
    profile = get_case_profile(daily_case.id, db=db_session, include_similar=False)
    assert profile["similar_cases"]["state"] == "not_requested"
    assert profile["similar_cases"]["items"] == []
    assert profile["case"]["id"] == daily_case.id
    assert "evidence" in profile["related"]
    assert "reports" in profile["knowledge_refs"]


def test_profile_legacy_default_no_longer_repeats_history_search(db_session, daily_case, monkeypatch):
    def forbidden(*args):
        raise AssertionError("兼容GET不应重新搜索")
    monkeypatch.setattr(CaseProfileService, "_safe_similar_cases", forbidden)
    result = get_case_profile(daily_case.id, db=db_session)["similar_cases"]
    assert result["state"] == "not_requested"
    assert result["items"] == []


def test_lightweight_profile_missing_case_remains_not_found(db_session):
    from fastapi import HTTPException

    with pytest.raises(HTTPException) as error:
        get_case_profile(99999, db=db_session, include_similar=False)
    assert error.value.status_code == 404


def test_profile_database_failure_is_explicit_and_sanitized(db_session, monkeypatch):
    from fastapi import HTTPException
    from sqlalchemy.exc import SQLAlchemyError

    def unavailable(*args, **kwargs):
        raise SQLAlchemyError("internal-sensitive-query")

    monkeypatch.setattr(CaseProfileService, "build_case_profile", unavailable)
    with pytest.raises(HTTPException) as error:
        get_case_profile(1, db=db_session)
    assert error.value.status_code == 503
    assert "不能据此判断" in error.value.detail
    assert "internal-sensitive-query" not in error.value.detail
