"""Explicit background preparation for isolated synthetic history fixtures."""
from sqlalchemy import select
from app.models.case import Case
from app.services.case_history_index_service import CaseHistoryIndexService


def build_history_index(db, cases=None):
    marker = object()
    scope = db.info.pop('authorized_area_ids', marker)
    try:
        for case in list(cases) if cases is not None else list(db.scalars(select(Case))):
            CaseHistoryIndexService.rebuild_case(db, case)
        db.commit()
    finally:
        if scope is not marker:
            db.info['authorized_area_ids'] = scope
