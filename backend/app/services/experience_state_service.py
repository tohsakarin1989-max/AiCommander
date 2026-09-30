"""Read one review target; never transfer a decision between different contents."""
from copy import deepcopy

from sqlalchemy.orm import Session

from app.models.case import Case
from app.models.knowledge_asset import KnowledgeAsset
from app.services.case_history_retrieval import _asset_access


def read_experience_state(db: Session, case: Case) -> dict:
    asset = (db.query(KnowledgeAsset)
             .filter(KnowledgeAsset.source_case_id == case.id,
                     KnowledgeAsset.asset_type == "experience_card")
             .order_by(KnowledgeAsset.version.desc(), KnowledgeAsset.id.desc()).first())
    if asset is not None:
        if not _asset_access(db, asset):
            # Do not reveal the restricted title/id/count or fall back to a
            # differently reviewed legacy card as if it were the current asset.
            return {"state": "unavailable", "source": "knowledge_asset", "card": None,
                    "needs_review": False, "confirmed": False}
        card = deepcopy(asset.content or {})
        card.update({"asset_id": asset.id, "asset_version": asset.version,
                     "manual_review_status": asset.status,
                     "reviewer": asset.reviewer_label, "review_note": asset.review_note,
                     "reviewed_at": asset.reviewed_at.isoformat() if asset.reviewed_at else None,
                     "review_source": "knowledge_asset"})
        return {"state": "ready", "source": "knowledge_asset", "card": card,
                "asset_id": asset.id, "asset_version": asset.version,
                "needs_review": asset.status == "draft", "confirmed": asset.status == "confirmed"}
    features = case.features if isinstance(case.features, dict) else {}
    intelligence = features.get("intelligence") or {}
    legacy = intelligence.get("experience_card") if isinstance(intelligence, dict) else None
    if not isinstance(legacy, dict) or not legacy:
        return {"state": "not_generated", "source": None, "card": None,
                "needs_review": False, "confirmed": False}
    card = deepcopy(legacy)
    card.update({"review_source": "legacy_json", "historical": True,
                 "compatibility_boundary": "旧卡原内容与原审核记录，仅供历史兼容；不确认任何新生成内容。"})
    status = card.get("manual_review_status")
    return {"state": "legacy", "source": "legacy_json", "card": card,
            "needs_review": status in {None, "draft", "pending", "needs_review", "flagged"},
            "confirmed": status in {"confirmed", "approved"}}
