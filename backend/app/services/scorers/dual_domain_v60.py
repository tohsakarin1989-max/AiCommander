"""v6.0 compatibility spatial baseline; proximity alone creates no storage claim.

The frozen v3.4 implementation remains available for historical evaluations.
Validated storage/lineage inference is not implemented by this baseline; do not
replace missing supporting evidence with a nearby village, settlement or depot.
"""
from app.repositories.spatial_repository import SpatialRepository
from app.services.scorers.dual_domain_v34 import DualDomainV34

VERSION = "dual-domain-6.0.0-1"


class DualDomainV60(DualDomainV34):
    @staticmethod
    def _storage_candidates(db, case, profile, snapshot, repository=SpatialRepository):
        return []

    @staticmethod
    def _build_candidates(db, case, profile, snapshot, repository=SpatialRepository):
        candidates = DualDomainV60._source_candidates(db, case, profile, snapshot, repository)
        activity = DualDomainV60._activity_candidate(db, case, profile, snapshot, repository)
        if activity:
            candidates.append(activity)
        candidates.extend(DualDomainV60._route_candidates(db, case, profile, snapshot, repository))
        candidates.sort(key=lambda item: (-item["score"], item["hypothesis_type"], item["title"]))
        return candidates[:3]
