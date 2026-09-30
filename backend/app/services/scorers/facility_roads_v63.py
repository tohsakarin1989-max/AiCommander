"""Retain the audited road weights while freezing every compared facility.

The 5.2 scorer stays installed and unchanged for captured-input replay. This
version retains its top-three contract and additionally preserves all ranks.
"""
from copy import deepcopy

from app.services.scorers.facility_roads_v52 import FacilityEvidence, rank_facilities as rank_v52

VERSION = "facility-roads-6.3.0-1"


def rank_facilities(evidence: list[FacilityEvidence], *, recall_complete: bool) -> dict:
    result = rank_v52(evidence, recall_complete=recall_complete)
    nearest = {item.asset_id: rank for rank, item in enumerate(
        sorted(evidence, key=lambda row: (row.straight_distance_m, row.asset_id)), 1)}
    rows = []
    for item in evidence:
        ranked = rank_v52([item], recall_complete=True)["candidates"]
        if ranked:
            row = ranked[0]
            row["distance_only_rank"] = nearest[item.asset_id]
            rows.append(row)
    rows.sort(key=lambda row: (-row["score"], row["road_distance_m"], row["asset_id"]))
    for rank, row in enumerate(rows, 1):
        row["rank"] = rank
        row["rank_change_from_distance"] = row["distance_only_rank"] - rank
    return {**result, "algorithm_version": VERSION, "all_candidates": rows,
            "candidates": deepcopy(rows[:3])}
