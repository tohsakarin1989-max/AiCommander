"""Isolated compatibility acceptance: no raw analysis during report layout."""
from datetime import datetime
import json
from types import SimpleNamespace

import pytest

from app.models.case import Case
from app.models.knowledge_asset import KnowledgeAsset, KnowledgeReuseRecord
from app.models.map_foundation import OperationalArea
from app.services.case_history_compat import build_legacy_similar_cases
from app.services.case_history_retrieval import CaseHistoryRetrieval, HistoryUnavailable
from app.services.case_intelligence_service import CaseIntelligenceService
from app.services.case_knowledge_service import CaseKnowledgeService
from app.services.case_result_service import CaseResultService
from app.services.knowledge_asset_service import KnowledgeAssetService, KnowledgeAssetError
from app.services.history_rank_fusion import HistoryRankFusion
from test_case_history_retrieval import db_session, corpus  # noqa: F401
from test_knowledge_asset_lifecycle import _session, _seed_case, _freeze_result
from tests.history_index_helpers import build_history_index


def _confirmed(db, case):
    asset = KnowledgeAsset(asset_type="experience_card", source_case_id=case.id, version=1,
                           title="合成已确认经验", content={"summary": "夜间打孔使用软管。"},
                           evidence_refs=[{"id": f"case:{case.id}"}], source_signature="a" * 64,
                           source_data_version="b" * 64, status="confirmed")
    db.add(asset)
    db.commit()
    build_history_index(db, [case])
    return asset


def test_legacy_recall_passes_500_and_retains_versions_scope_and_partial(db_session, corpus, monkeypatch):
    target = Case(case_number="TARGET", occurred_time=datetime(2026, 9, 1), location="未知",
                  description="夜间打孔盗油并使用软管。", operational_area_id=1)
    db_session.add(target)
    db_session.commit()
    result = build_legacy_similar_cases(db_session, target.id, days=0, limit=200)
    assert result["items"][0]["case"]["case_number"] == "OLD-MATCH"
    assert result["items"][0]["versions"]["source_text_hash"]
    assert result["items"][0]["components"] == {}
    assert result["coverage"]["authorized_cases"] == 621
    assert result["coverage"]["indexed_cases"] == 621
    assert result["coverage"]["scanned_cases"] == 1
    assert result["coverage"]["recency_limit"] is None
    assert "HIDDEN" not in json.dumps(result, default=str)
    with pytest.raises(ValueError, match="invalid_history_query"):
        CaseHistoryRetrieval.search(db_session, source_case_id=target.id, limit=21)
    monkeypatch.setattr("app.services.case_history_retrieval.SCAN_SECONDS", -1)
    partial = build_legacy_similar_cases(db_session, target.id, days=0)
    assert partial["state"] == "partial" and not partial["coverage"]["complete"]
    db_session.info["authorized_area_ids"] = ()
    with pytest.raises(HistoryUnavailable):
        build_legacy_similar_cases(db_session, target.id, days=0)


def test_cases_only_internal_200_does_not_mix_cards(db_session, monkeypatch):
    db_session.info["authorized_area_ids"] = (1,)
    cases = [Case(case_number=f"MATCH-{i}", location="未知", description="打孔盗油使用软管。",
                  occurred_time=datetime(2026, 1, 1), operational_area_id=1) for i in range(220)]
    db_session.add_all(cases)
    db_session.commit()
    build_history_index(db_session)
    _confirmed(db_session, cases[1])
    # This checks the internal result limit and source-type filter, not latency.
    # Keep the production five-second budget; elapsed-budget partial results are
    # tested separately and must not make this contract depend on runner speed.
    with monkeypatch.context() as retrieval:
        retrieval.setattr("app.services.case_history_fragment_search.time",
                          SimpleNamespace(monotonic=lambda: 100.0))
        result = CaseHistoryRetrieval.search_cases(db_session, source_case_id=cases[0].id, limit=200)
    assert result["coverage"]["scan_complete"] is True
    assert result["coverage"]["budget_seconds"] == 5.0
    assert len(result["items"]) == 200
    assert {item["source_type"] for item in result["items"]} == {"case"}


def test_legacy_experience_search_retrieves_older_cards_and_preserves_negation(db_session, corpus):
    asset = _confirmed(db_session, corpus)
    result = CaseKnowledgeService.search_experience_cards(db_session, "打孔 软管")
    assert result["items"][0]["asset_id"] == asset.id
    assert result["coverage"]["authorized_cases"] == 621
    assert result["coverage"]["indexed_cases"] == 621
    asset.content = {"summary": "未转运。"}
    db_session.commit()
    build_history_index(db_session, [corpus])
    assert not CaseKnowledgeService.search_experience_cards(db_session, "转运")["items"]
    negated = CaseKnowledgeService.search_experience_cards(db_session, "未转运")
    assert negated["items"][0]["shared_conditions"] == [["action", "转运", "negated"]]
    asset.content = {"summary": "疑似转运。"}
    db_session.commit()
    build_history_index(db_session, [corpus])
    uncertain = CaseKnowledgeService.search_experience_cards(db_session, "疑似转运")
    assert uncertain["items"][0]["shared_conditions"] == [["action", "转运", "uncertain"]]
    db_session.info["authorized_area_ids"] = ()
    assert not CaseKnowledgeService.search_experience_cards(db_session, "疑似转运")["items"]


def test_frozen_report_refuses_missing_and_stale_without_implicit_generation(monkeypatch):
    db = _session()
    case = Case(case_number="FROZEN-MISSING", occurred_time=datetime(2026, 9, 1),
                location="合成井场", description="夜间发现软管及油桶。", status="closed")
    db.add(case)
    db.commit()
    def forbidden(*args, **kwargs):
        pytest.fail("report layout must not analyze or refresh raw facts")
    monkeypatch.setattr(CaseIntelligenceService, "build_report", forbidden)
    monkeypatch.setattr(KnowledgeAssetService, "_ensure_case_quality", forbidden)
    with pytest.raises(KnowledgeAssetError, match="frozen_result_unavailable"):
        KnowledgeAssetService.generate_report_snapshot(db, case.id, experience_asset_ids=[])
    assert db.query(KnowledgeAsset).count() == 0
    _freeze_result(db, case)
    case.description += "后续资料补充。"
    db.commit()
    with pytest.raises(KnowledgeAssetError, match="frozen_result_stale"):
        KnowledgeAssetService.generate_report_snapshot(db, case.id, experience_asset_ids=[])
    assert db.query(KnowledgeAsset).count() == 0


def test_frozen_report_only_formats_selected_experience_and_old_versions_remain_readable(monkeypatch):
    db = _session()
    target, source = _seed_case(db, number="FROZEN-TARGET"), _seed_case(db, number="FROZEN-SOURCE")
    source_asset = _confirmed(db, source)
    _freeze_result(db, target)
    frozen = CaseResultService.latest(db, target.id)
    def forbidden(*args, **kwargs):
        pytest.fail("must reuse frozen input")
    monkeypatch.setattr(CaseIntelligenceService, "build_report", forbidden)
    monkeypatch.setattr(KnowledgeAssetService, "_ensure_case_quality", forbidden)
    first = KnowledgeAssetService.generate_report_snapshot(db, target.id, experience_asset_ids=[source_asset.id])
    again = KnowledgeAssetService.generate_report_snapshot(db, target.id, experience_asset_ids=[source_asset.id], days=30, limit=1)
    assert first.id == again.id and db.query(KnowledgeReuseRecord).count() == 1
    assert first.content["frozen_result"]["id"] == frozen["id"]
    assert first.content["report"]["generation_mode"] == "frozen_result_layout"
    original = json.dumps(first.content, sort_keys=True)
    target.description += "原文更新。"
    db.commit()
    assert json.dumps(KnowledgeAssetService.asset_payload(db, first)["content"], sort_keys=True) == original
    with pytest.raises(KnowledgeAssetError, match="source_changed_since_generation"):
        KnowledgeAssetService.review_asset(db, first.id, status="confirmed")


def test_report_and_experience_are_not_delivered_after_reference_scope_revoked():
    db = _session()
    db.add_all([OperationalArea(id=1, code="A", name="合成甲"), OperationalArea(id=2, code="B", name="合成乙")])
    db.commit()
    target, source = _seed_case(db, number="SCOPE-TARGET"), _seed_case(db, number="SCOPE-SOURCE")
    target.operational_area_id, source.operational_area_id = 1, 2
    db.commit()
    source_asset = _confirmed(db, source)
    _freeze_result(db, target)
    accessible = KnowledgeAssetService.generate_report_snapshot(db, target.id, experience_asset_ids=[])
    report = KnowledgeAssetService.generate_report_snapshot(db, target.id, experience_asset_ids=[source_asset.id])
    db.info["authorized_area_ids"] = (1,)
    with pytest.raises(KnowledgeAssetError, match="knowledge_asset_not_found"):
        KnowledgeAssetService.asset_payload(db, report)
    listing = KnowledgeAssetService.list_assets(db, case_id=target.id)
    assert [item["id"] for item in listing["items"]] == [accessible.id]
    assert listing["total"] == 1 and listing["total_kind"] == "returned_accessible"
    assert source.case_number not in json.dumps(listing)
    history = KnowledgeAssetService.list_reuse_records(db, target_case_id=target.id)
    assert history["items"] == [] and history["total"] == 0
    assert not KnowledgeAssetService.reuse_recommendations(db, target.id)["items"]


def test_extended_rank_fusion_does_not_truncate_internal_200():
    fusion = HistoryRankFusion(candidate_capacity=460)
    for i in range(600):
        fusion.add({"score": 1.0 - i / 1000, "shared_conditions": [], "different_conditions": [],
                    "versions": {}, "id": i}, 1.0 - i / 1000)
    assert len(fusion.finish(200)) == 200


@pytest.mark.parametrize("status,label", [("draft", "草稿"), ("archived", "已归档")])
def test_legacy_experience_status_is_never_mislabeled_confirmed(db_session, status, label):
    db_session.info["authorized_area_ids"] = (1,)
    db_session.add(Case(case_number="LEGACY-STATUS", location="合成地点",
                        occurred_time=datetime(2026, 1, 1), operational_area_id=1,
                        features={"intelligence": {"experience_card": {
                            "summary": "打孔使用软管。", "manual_review_status": status}}}))
    db_session.commit()
    build_history_index(db_session)
    # Unconfirmed material remains readable in its own listing, but the shared
    # reference index must not promote it into the confirmed-experience corpus.
    listing = CaseKnowledgeService.list_experience_cards(db_session, status=status)
    assert listing["items"][0]["manual_review_status"] == status
    assert "不作为已确认经验" in listing["items"][0]["applicability_reason"]
    result = CaseKnowledgeService.search_experience_cards(db_session, "软管", status=status)
    assert result["items"] == []
    assert result["state"] == 'partial' and not result["coverage"]["complete"]
    assert result['query_context']['experience_status'] == status


def test_optional_legacy_profile_history_failure_is_explicit_not_no_match(monkeypatch):
    from sqlalchemy.exc import OperationalError
    from app.services.case_profile_service import CaseProfileService

    def unavailable(*args, **kwargs):
        raise HistoryUnavailable("history_unavailable")
    monkeypatch.setattr(CaseIntelligenceService, "find_similar_cases", unavailable)
    result = CaseProfileService._safe_similar_cases(_session(), 1)
    assert result["state"] == "unavailable"
    assert result["coverage"]["complete"] is False
    assert "不能据此判断" in result["boundary"]

    def database_failed(*args, **kwargs):
        raise OperationalError("synthetic statement", {}, RuntimeError("synthetic failure"))
    monkeypatch.setattr(CaseIntelligenceService, "find_similar_cases", database_failed)
    with pytest.raises(OperationalError):
        CaseProfileService._safe_similar_cases(_session(), 1)
