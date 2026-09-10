"""Shared cooperative deadline for nested document rendering stages."""
from contextvars import ContextVar
from functools import wraps
from time import monotonic


_deadline = ContextVar('document_render_deadline', default=None)
TOTAL_SECONDS = 120


class DocumentBudgetExceeded(TimeoutError):
    pass


def remaining_seconds(stage_limit: float) -> float:
    deadline = _deadline.get()
    if deadline is None:
        return stage_limit
    remaining = deadline - monotonic()
    if remaining <= 0:
        raise DocumentBudgetExceeded('document_render_timeout')
    return min(stage_limit, remaining)


def document_budget(function):
    @wraps(function)
    def wrapped(*args, **kwargs):
        token = None
        if _deadline.get() is None:
            token = _deadline.set(monotonic() + TOTAL_SECONDS)
        try:
            remaining_seconds(TOTAL_SECONDS)
            result = function(*args, **kwargs)
            remaining_seconds(TOTAL_SECONDS)
            return result
        except DocumentBudgetExceeded:
            # Lazy import avoids a cycle with the export module.
            from app.services.case_result_export import CaseResultExportError
            raise CaseResultExportError('renderer_timeout') from None
        finally:
            if token is not None:
                _deadline.reset(token)
    return wrapped
