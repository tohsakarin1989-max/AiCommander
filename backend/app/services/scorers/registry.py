"""Explicit installed algorithms only; IDs never resolve file paths or URLs."""
import hashlib
from pathlib import Path

from app.services import case_analysis_applicability
from app.services.scorers import dual_domain_v34, dual_domain_v60, dual_domain_v80, facility_roads_v52, facility_roads_v63

SCORERS = {dual_domain_v34.VERSION: (dual_domain_v34.DualDomainV34, dual_domain_v34),
           dual_domain_v60.VERSION: (dual_domain_v60.DualDomainV60, dual_domain_v60),
           dual_domain_v80.VERSION: (dual_domain_v80.DualDomainV80, dual_domain_v80)}
FACILITY_SCORERS = {facility_roads_v52.VERSION: (facility_roads_v52.rank_facilities, facility_roads_v52),
                    facility_roads_v63.VERSION: (facility_roads_v63.rank_facilities, facility_roads_v63)}


def resolve_scorer(version):
    if version not in SCORERS:
        raise ValueError('frozen_algorithm_unavailable')
    implementation, module = SCORERS[version]
    source = Path(module.__file__).read_bytes()
    if module is dual_domain_v80:
        # Include the gate and inherited scoring implementation. Keep historical
        # fingerprints intact so already-frozen 3.x/6.x runs remain replayable.
        for dependency in (case_analysis_applicability, dual_domain_v60, dual_domain_v34):
            source += Path(dependency.__file__).read_bytes()
    fingerprint = hashlib.sha256(source).hexdigest()
    return implementation, fingerprint


def resolve_facility_scorer(version):
    if version not in FACILITY_SCORERS:
        raise ValueError('frozen_facility_algorithm_unavailable')
    implementation, module = FACILITY_SCORERS[version]
    source = Path(module.__file__).read_bytes()
    if module is facility_roads_v63:
        source += Path(facility_roads_v52.__file__).read_bytes()
    return implementation, hashlib.sha256(source).hexdigest()
