"""Explicit installed algorithms only; IDs never resolve file paths or URLs."""
import hashlib
from pathlib import Path

from app.services.scorers import dual_domain_v34

SCORERS = {dual_domain_v34.VERSION: (dual_domain_v34.DualDomainV34, dual_domain_v34)}


def resolve_scorer(version):
    if version not in SCORERS:
        raise ValueError('frozen_algorithm_unavailable')
    implementation, module = SCORERS[version]
    fingerprint = hashlib.sha256(Path(module.__file__).read_bytes()).hexdigest()
    return implementation, fingerprint
