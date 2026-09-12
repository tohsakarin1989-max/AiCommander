"""单案结论只排版已冻结成果；与会议生成路径保持独立。"""
import asyncio
from copy import deepcopy

import pytest
from sqlalchemy import event, select

from app.database import AreaWriteAccessError
from app.models.case import Case
from app.models.conclusion import Conclusion
from app.models.conclusion_review import ConclusionReview
from app.models.case_result import CaseResultSnapshot
from app.models.map_foundation import MapSnapshot
from app.services.case_intelligence_service import CaseIntelligenceService
from app.services.case_pipeline_service import (
    CASE_DICTIONARY_VERSION,
    CASE_PROFILE_SCHEMA_VERSION,
    CasePipelineService,
)
from app.services.case_result_access import CaseResultAccessError
from app.services.case_result_service import CaseResultService
from app.services.conclusion_factory_service import (
    ConclusionFactoryService,
    ConclusionResultPendingError,
)
from test_case_result_access import result_data  # noqa: F401


@pytest.fixture
def current_profile(db_session, result_data):
    profile, _, candidate = result_data
    db_session.info.update(authorized_area_ids=(1, 2), area_access_levels={1: "write"})
    case = db_session.scalar(select(Case).where(Case.id == 1))
    case.location = "合成地点"
    db_session.flush()
    source_hash = CasePipelineService.source_hash(db_session, case)
    profile.source_hash = source_hash
    profile.schema_version = CASE_PROFILE_SCHEMA_VERSION
    profile.dictionary_version = CASE_DICTIONARY_VERSION
    profile.payload = {
        **profile.payload, "source_hash": source_hash,
        "critical_gaps": [{"field": "oil_type", "label": "缺少油品类型"}],
    }
    candidate.counter_evidence = ["现有资料未证明与该设施有实际联系"]
    db_session.execute(MapSnapshot.__table__.update().values(status="current"))
    db_session.commit()
    return profile


@pytest.fixture
def frozen_result(db_session, current_profile):
    result, _ = CaseResultService.create_current(db_session, 1)
    db_session.commit()
    assert CaseResultService.latest(db_session, 1)["freshness"] == "current"
    return result


@pytest.fixture
def forbid_analysis(monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("结论草稿不得重跑模型、原文分析或相似检索")

    for name in ("_get_llm", "_build_evidence"):
        monkeypatch.setattr(ConclusionFactoryService, name, forbidden)
    for name in ("build_report", "build_experience_card", "find_similar_cases", "build_prevention_suggestions"):
        monkeypatch.setattr(CaseIntelligenceService, name, forbidden)


def generate(db):
    return asyncio.run(ConclusionFactoryService.generate_conclusion(db, 1))


def test_reuses_frozen_facts_candidates_gaps_without_analysis_or_case_writes(
    db_session, frozen_result, forbid_analysis,
):
    before = db_session.execute(Case.__table__.select()).mappings().all()
    snapshot_count = len(list(db_session.scalars(select(CaseResultSnapshot.id))))
    mutations = []

    def observe(conn, cursor, statement, parameters, context, executemany):
        sql = statement.lower().lstrip()
        if sql.startswith(("update cases", "insert into cases", "delete from cases")):
            mutations.append(statement)

    event.listen(db_session.bind, "before_cursor_execute", observe)
    try:
        draft = generate(db_session)
    finally:
        event.remove(db_session.bind, "before_cursor_execute", observe)

    assert draft.status == "needs_review"
    assert draft.risk_level == "unknown"
    evidence = draft.evidence
    assert evidence["source_result"] == {
        "result_id": frozen_result["id"],
        "content_sha256": frozen_result["content_sha256"],
        "schema_version": frozen_result["content"]["schema_version"],
        "versions": frozen_result["content"]["versions"],
    }
    assert evidence["raw"]["case_result"] == frozen_result["content"]
    assert "case_intelligence" not in evidence["raw"]
    output = evidence["ai_output"]
    assert output["model_status"] == "reused_case_result"
    assert output["review_status"] == "pending_review"
    assert output["confidence_available"] is False
    assert "地点：合成地点" in output["facts"]
    assert "缺少油品类型" in output["information_gaps"]
    inference = output["inferences"][0]
    original = frozen_result["content"]["candidates"][0]
    assert inference["claim"] == original["claim"]
    assert inference["basis"] == original["supporting_evidence"]
    assert inference["counter_evidence"] == original["counter_evidence"]
    assert inference["evidence_refs"] == original["evidence_refs"]
    assert inference["score_kind"] == "rule_support_not_probability"
    assert inference["is_official_fact"] is False
    assert output["recommendations"] == []
    assert not mutations
    assert db_session.execute(Case.__table__.select()).mappings().all() == before
    assert len(list(db_session.scalars(select(CaseResultSnapshot.id)))) == snapshot_count


def test_repeated_request_returns_same_draft(db_session, frozen_result, forbid_analysis):
    first = generate(db_session)
    frozen_draft = deepcopy(first.evidence)
    again = generate(db_session)
    assert again.id == first.id
    assert again.evidence == frozen_draft
    assert len(list(db_session.scalars(select(Conclusion.id)))) == 1


@pytest.mark.parametrize("status,action", [("published", "approve"), ("rejected", "reject"), ("flagged", "flag")])
def test_repeated_request_does_not_reset_human_decision(
    db_session, frozen_result, forbid_analysis, status, action,
):
    first = generate(db_session)
    first.status = status
    first.summary = "人工保留的表述，不应被重新生成覆盖"
    review = ConclusionReview(conclusion_id=first.id, action=action, note="合成审核意见")
    db_session.add(review)
    db_session.commit()
    again = generate(db_session)
    assert again.id == first.id
    assert again.status == status
    assert again.summary == "人工保留的表述，不应被重新生成覆盖"
    assert db_session.scalar(select(ConclusionReview.id)) == review.id
    assert len(list(db_session.scalars(select(Conclusion.id)))) == 1


def test_new_source_result_creates_separate_draft_and_keeps_published_history(
    db_session, frozen_result, result_data, forbid_analysis,
):
    previous = generate(db_session)
    previous.status = "published"
    old_evidence = deepcopy(previous.evidence)
    result_data[2].claim = "后来形成的另一条待判断候选"
    db_session.commit()
    changed, created = CaseResultService.create_current(db_session, 1)
    db_session.commit()
    assert created
    current = generate(db_session)
    assert current.id != previous.id
    assert current.status == "needs_review"
    assert current.evidence["source_result"]["result_id"] == changed["id"]
    db_session.refresh(previous)
    assert previous.status == "published" and previous.evidence == old_evidence


def test_missing_result_waits_instead_of_generating(db_session, current_profile, forbid_analysis):
    with pytest.raises(ConclusionResultPendingError, match="等待后台"):
        generate(db_session)
    assert list(db_session.scalars(select(Conclusion.id))) == []


def test_changed_case_waits_instead_of_reusing_stale_result(db_session, frozen_result, forbid_analysis):
    db_session.execute(Case.__table__.update().where(Case.id == 1).values(description="原案情后来修改"))
    db_session.commit()
    with pytest.raises(ConclusionResultPendingError, match="等待后台"):
        generate(db_session)
    assert list(db_session.scalars(select(Conclusion.id))) == []


def test_result_without_candidates_never_invents_them(db_session, current_profile, forbid_analysis):
    CaseResultService.freeze_completed_inputs(db_session, current_profile)
    db_session.commit()
    draft = generate(db_session)
    assert draft.evidence["ai_output"]["inferences"] == []
    assert draft.evidence["ai_output"]["recommendations"] == []
    assert "当前成果未提供候选，不补造推断" in draft.summary
    assert draft.evidence["raw"]["case_result"]["analysis_status"] == "not_generated"


def test_scope_shrink_rechecks_every_source_even_when_draft_exists(
    db_session, current_profile, result_data, forbid_analysis,
):
    result_data[2].evidence_refs = ["case:2"]
    db_session.commit()
    CaseResultService.create_current(db_session, 1)
    db_session.commit()
    draft = generate(db_session)
    db_session.info["authorized_area_ids"] = (1,)
    with pytest.raises(CaseResultAccessError):
        generate(db_session)
    with pytest.raises(CaseResultAccessError):
        ConclusionFactoryService.require_conclusion_result_access(db_session, draft)
    assert len(list(db_session.scalars(select(Conclusion.id)))) == 1


def test_saved_result_reference_cannot_be_tampered(db_session, frozen_result, forbid_analysis):
    draft = generate(db_session)
    corrupt = deepcopy(draft.evidence)
    corrupt["source_result"]["content_sha256"] = "tampered"
    draft.evidence = corrupt
    db_session.commit()
    with pytest.raises(CaseResultAccessError):
        generate(db_session)


def test_read_only_area_cannot_generate_draft(db_session, frozen_result, forbid_analysis):
    db_session.info["area_access_levels"] = {1: "read"}
    with pytest.raises(AreaWriteAccessError):
        generate(db_session)
    assert list(db_session.scalars(select(Conclusion.id))) == []


def test_unbound_session_cannot_use_frozen_case_result(db_session, frozen_result, forbid_analysis):
    db_session.info.pop("authorized_area_ids")
    with pytest.raises(CaseResultAccessError):
        generate(db_session)
    assert list(db_session.scalars(select(Conclusion.id))) == []


def test_legacy_meeting_conclusion_reference_contract_is_unchanged(db_session):
    legacy = Conclusion(case_id=1, meeting_id="historical-meeting", evidence={"raw": {"meeting": {}}})
    ConclusionFactoryService.require_conclusion_result_access(db_session, legacy)
