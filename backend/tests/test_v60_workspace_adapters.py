"""v6 read chain reuses persisted outputs and version-specific review state."""
from copy import deepcopy

import pytest
from sqlalchemy import select

from app.api.suggestions import get_suggestions
from app.config import settings
from app.models.case import Case
from app.models.knowledge_asset import KnowledgeAsset
from app.services.case_automation_service import CaseAutomationService
from app.services.case_intelligence_service import CaseIntelligenceService
from app.services.case_knowledge_service import CaseKnowledgeService
from app.services.case_processing_card_service import CaseProcessingCardService
from app.services.case_profile_service import CaseProfileService
from app.services.case_quality_service import CaseQualityService
from app.services.case_result_service import CaseResultService
from app.services.case_workspace_service import CaseWorkspaceService
from app.services.experience_state_service import read_experience_state
from test_case_results import db_session  # noqa: F401
from test_case_result_access import result_data  # noqa: F401
from test_conclusion_result_reuse import current_profile  # noqa: F401


@pytest.fixture
def case(db_session, current_profile, monkeypatch):
    monkeypatch.setattr(settings, "ENABLE_BONUS_ACCOUNTING", False)
    case = db_session.scalar(select(Case).where(Case.id == 1))
    case.quality_issues = {"score": 100, "missing_required": []}
    case.features = {"summary": "旧预处理摘要，不是本次画像",
                     "intelligence": {"experience_card": {"summary": "旧卡不同内容", "manual_review_status": "draft"}}}
    db_session.commit()
    return case


def asset(db, case, *, version=1, status="confirmed", refs=None):
    saved = KnowledgeAsset(asset_type="experience_card", source_case_id=case.id, version=version,
                           title=f"测试经验v{version}", content={"summary": f"版本{version}内容"},
                           evidence_refs=refs or [{"id": f"case:{case.id}"}],
                           source_signature=str(version) * 64, source_data_version="s" * 64,
                           status=status, reviewer_label="合成审核人")
    db.add(saved)
    db.commit()
    return saved


def test_daily_and_compat_reads_do_not_extract_search_or_generate(db_session, case, monkeypatch):
    frozen, _ = CaseResultService.create_current(db_session, case.id)
    db_session.commit()
    before = deepcopy(case.features)

    def forbidden(*args, **kwargs):
        raise AssertionError("GET must reuse saved data, not generate or commit")

    for name in ("build_workbench", "build_llm_context_pack", "build_case_tags", "build_experience_card", "find_similar_cases"):
        monkeypatch.setattr(CaseIntelligenceService, name, forbidden)
    monkeypatch.setattr(CaseQualityService, "evaluate_case", forbidden)
    monkeypatch.setattr(db_session, "commit", forbidden)
    workspace = CaseWorkspaceService.read(db_session, case.id)
    assert workspace["schema_version"] == "case-workspace-6.0-1"
    assert workspace["automation_workbench"]["data"]["result_id"] == frozen["id"]
    assert all(isinstance(item, str) for item in workspace["automation_workbench"]["data"]["conclusion_layering"]["facts"])
    if workspace["result"]["data"].get("composition_status") == "road_not_ready":
        assert workspace["automation_workbench"]["data"]["conclusion_layering"]["inferences"] == []
    assert workspace["detail_profile"]["data"]["standard_profile"] == workspace["profile"]
    assert workspace["detail_profile"]["data"]["ai_summary"]["summary"] == case.description
    assert workspace["detail_profile"]["data"]["ai_summary"]["legacy_summary"]["state"] == "historical_unversioned"
    assert workspace["detail_profile"]["data"]["quality"]["state"] == "stale"
    assert workspace["detail_profile"]["data"]["quality"]["historical_result"] == case.quality_issues
    CaseProfileService.build_case_profile(db_session, case.id)
    CaseProcessingCardService.build_processing_card(db_session, case.id)
    CaseAutomationService.build_automation_workbench(db_session, case, include_bonus=False)
    CaseKnowledgeService.build_case_diagram(db_session, case.id)
    assert case.features == before


def test_confirmed_asset_resolves_old_draft_in_all_consumers(db_session, case):
    saved = asset(db_session, case)
    profile = CaseProfileService.build_case_profile(db_session, case.id)
    assert profile["experience_card"]["asset_id"] == saved.id
    assert profile["experience_card"]["manual_review_status"] == "confirmed"
    assert profile["availability"]["has_confirmed_experience"] is True
    assert not any(group["key"] == "experience" for group in
                   CaseProcessingCardService.build_processing_card(db_session, case.id)["gap_groups"])
    response = get_suggestions(db=db_session, limit=50, offset=0, workflow="all")
    assert not any(item["workflow"] == "experience" for item in response["suggestions"])
    assert case.features["intelligence"]["experience_card"]["manual_review_status"] == "draft"


def test_new_different_asset_does_not_inherit_old_confirmation(db_session, case):
    old = asset(db_session, case)
    new = asset(db_session, case, version=2, status="draft")
    state = read_experience_state(db_session, case)
    assert state["asset_id"] == new.id and state["needs_review"] is True
    assert state["confirmed"] is False
    with pytest.raises(ValueError, match="experience_asset_version_required"):
        CaseKnowledgeService.update_experience_card_status(db_session, case.id, status="confirmed")
    assert old.status == "confirmed" and new.status == "draft"


def test_restricted_latest_asset_does_not_leak_or_fall_back(db_session, case):
    asset(db_session, case, refs=[{"id": "case:2"}])
    db_session.info["authorized_area_ids"] = (1,)
    state = read_experience_state(db_session, case)
    assert state == {"state": "unavailable", "source": "knowledge_asset", "card": None,
                     "needs_review": False, "confirmed": False}


def test_missing_saved_outputs_stay_missing_without_extracting(db_session, case, monkeypatch):
    from app.models.case_pipeline import CaseAnalysisProfile
    db_session.query(CaseAnalysisProfile).update({"is_current": False})
    case.quality_issues = None
    db_session.commit()
    monkeypatch.setattr(CaseQualityService, "evaluate_case", lambda *args: pytest.fail("unexpected extraction"))
    profile = CaseProfileService.build_case_profile(db_session, case.id)
    assert profile["standard_profile"]["status"] == "unavailable"
    assert profile["quality"]["state"] == "not_generated"
    assert profile["availability"]["has_ai_features"] is False
