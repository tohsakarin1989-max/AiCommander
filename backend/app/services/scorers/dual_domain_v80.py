"""8.0 live source candidates require an explicit suitable incident endpoint.

Frozen older scorers remain available for historical evaluation. This adapter
does not turn a discovery point into an incident site or draw presumed routes.
"""
from types import SimpleNamespace

from app.repositories.spatial_repository import SpatialRepository
from app.services.case_analysis_applicability import allows
from app.services.scorers.dual_domain_v60 import DualDomainV60

VERSION = "dual-domain-8.0.0-1"


class DualDomainV80:
    @staticmethod
    def _build_candidates(db, case, profile, snapshot, repository=SpatialRepository):
        if not allows(getattr(profile, "payload", {}), "source_inference"):
            return []
        applicability = profile.payload["analysis_applicability"]
        point = applicability.get("incident_point")
        if not point:
            return []
        frozen_case = SimpleNamespace(
            latitude=point["latitude"], longitude=point["longitude"],
            operational_area_id=case.operational_area_id,
            oil_type=profile.payload.get("standard", {}).get("oil_type"),
        )
        candidates = DualDomainV60._source_candidates(db, frozen_case, profile, snapshot, repository)
        for item in candidates:
            item["supporting_evidence"].extend(
                f"原文线索：{basis['value']}（不代表已核实来源）"
                for basis in applicability.get("source_basis", []))
            item["counter_evidence"].append("原文手法或来源线索不证明该设施实际涉案。")
        return candidates[:3]

    _source_candidates = _build_candidates
