"""One version signature for automatic facility comparison and upgrades."""

SCORING_INPUT_VERSION = 'facility-scoring-inputs-5.2-1'


def current_versions() -> dict[str, str]:
    # Lazy imports avoid bringing retrieval/model dependencies into startup.
    from app.services.case_history_retrieval import RETRIEVAL_VERSION
    from app.services.facility_candidate_pool import RECALL_VERSION
    from app.services.facility_history_conditions import VERSION as HISTORY_VERSION
    from app.services.facility_production_conditions import VERSION as PRODUCTION_VERSION
    from app.services.scorers.facility_roads_v52 import VERSION as SCORER_VERSION

    return {
        "recall": RECALL_VERSION,
        "history": HISTORY_VERSION,
        "retrieval": RETRIEVAL_VERSION,
        "production": PRODUCTION_VERSION,
        "scorer": SCORER_VERSION,
        "scoring_inputs": SCORING_INPUT_VERSION,
    }
