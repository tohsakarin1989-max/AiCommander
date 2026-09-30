"""Shared bounded execution vocabulary, without sharing runtime permissions.

The DB guard applies to a dedicated read task transaction. A timed-out SQL
statement is rolled back before a caller can persist a terminal task state.
"""
from contextlib import contextmanager
from dataclasses import asdict, dataclass, field
import threading
import time
from typing import Callable

from sqlalchemy import event
from sqlalchemy.exc import DBAPIError


class ExecutionCancelled(Exception):
    pass


@dataclass(frozen=True)
class ToolDeclaration:
    name: str
    version: str
    parameters: dict
    runtime: str
    effect: str = "read_only"
    data_classification: str = "intranet_raw"
    max_output_bytes: int = 196_608

    def public(self):
        return asdict(self)


@dataclass(frozen=True)
class TaskEnvelope:
    task_id: str | None
    mode: str
    principal_user_id: int | None
    scope_version: str | None
    max_steps: int = 8
    timeout_seconds: float = 120
    source_bindings: dict = field(default_factory=dict)
    schema_version: str = "execution-envelope-6.4-1"

    def public(self):
        return asdict(self)


def evidence_contract(output: dict) -> dict:
    """References are supplied by business tools, never minted by a model."""
    evidence = output.get('evidence') or {}
    references = output.get('evidence_refs') or evidence.get('refs') or []
    return {'schema_version': 'execution-evidence-6.4-1',
            'evidence_refs': sorted({value for value in references if isinstance(value, str)}),
            'query_basis': evidence,
            'boundary': '工具来源引用不等于已核实事实；交付时仍重新核验当前访问范围。'}


@dataclass
class ExecutionBudget:
    deadline: float
    cancelled: Callable[[], bool] = lambda: False
    max_steps: int = 8
    steps: int = 0
    clock: Callable[[], float] = time.monotonic
    cancellation_signal: threading.Event = field(default_factory=threading.Event)

    def check(self, *, poll=True):
        if self.cancellation_signal.is_set() or (poll and self.cancelled()):
            self.cancellation_signal.set()
            raise ExecutionCancelled("execution_cancelled")
        if self.clock() >= self.deadline:
            raise TimeoutError("execution_timeout")

    def take_step(self):
        self.check()
        if self.steps >= self.max_steps:
            raise ValueError("query_step_limit")
        self.steps += 1


@dataclass
class ExecutionUsage:
    started: float = field(default_factory=time.monotonic)
    model_requests: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    missing_usage: bool = False
    tool_calls: int = 0

    def record_response(self, response):
        usage = getattr(response, "usage_metadata", None)
        if not isinstance(usage, dict):
            usage = (getattr(response, "response_metadata", None) or {}).get("token_usage")
        if not isinstance(usage, dict):
            self.missing_usage = True
            return
        incoming = usage.get("input_tokens", usage.get("prompt_tokens"))
        outgoing = usage.get("output_tokens", usage.get("completion_tokens"))
        if any(type(value) is not int or value < 0 for value in (incoming, outgoing)):
            self.missing_usage = True
            return
        self.input_tokens += incoming
        self.output_tokens += outgoing

    def public(self):
        state = "not_used" if not self.model_requests else "unavailable" if self.missing_usage else "known"
        return {"model_requests": self.model_requests, "tool_calls": self.tool_calls,
                "input_tokens": None if self.missing_usage else self.input_tokens,
                "output_tokens": None if self.missing_usage else self.output_tokens,
                "token_state": state, "duration_ms": round((time.monotonic() - self.started) * 1000)}


@contextmanager
def sql_budget(db, budget: ExecutionBudget):
    """Limit actual statements, not just post-hoc result publication.

Cancellation polling must use a separate session when supplied as
``execution_cancel_probe``. SQLite's progress callback never queries the same
connection recursively. Only this task's DBAPI connection can be interrupted.
"""
    budget.check()
    connection = db.connection()
    driver = connection.connection.driver_connection
    dialect = connection.dialect.name
    stopped = threading.Event()
    cancellation_lock = threading.Lock()
    worker = None
    probe = db.info.get("execution_cancel_probe")
    previous_timeout = None
    if dialect == "postgresql":
        previous_timeout = connection.exec_driver_sql("SHOW statement_timeout").scalar()

    def before_statement(conn, cursor, statement, parameters, context, many):
        budget.check(poll=False)
        if dialect == "postgresql":
            remaining_ms = max(1, int((budget.deadline - budget.clock()) * 1000))
            cursor.execute("SELECT set_config('statement_timeout', %s, true)", (str(remaining_ms),))

    event.listen(connection, "before_cursor_execute", before_statement)
    if dialect == "sqlite":
        driver.set_progress_handler(lambda: int(
            budget.cancellation_signal.is_set() or budget.clock() >= budget.deadline), 1000)

    def watch():
        while not stopped.wait(0.1):
            try:
                is_cancelled = bool(probe()) if probe is not None else False
            except Exception:
                is_cancelled = True  # A failed permission/cancellation probe cannot grant execution.
            if is_cancelled:
                budget.cancellation_signal.set()
            if is_cancelled or budget.clock() >= budget.deadline:
                with cancellation_lock:
                    if stopped.is_set():
                        return
                    try:
                        if dialect == "sqlite":
                            driver.interrupt()
                        elif dialect == "postgresql":
                            driver.cancel()
                    except Exception:
                        pass  # Statement deadline and final publication checks remain active.
                return

    if probe is not None:
        worker = threading.Thread(target=watch, name="query-db-cancellation", daemon=True)
        worker.start()
    try:
        yield
        budget.check(poll=False)
    except DBAPIError as error:
        if budget.cancellation_signal.is_set():
            raise ExecutionCancelled("execution_cancelled") from None
        if budget.clock() >= budget.deadline or (dialect == 'postgresql' and
                getattr(error.orig, 'sqlstate', getattr(error.orig, 'pgcode', None)) == '57014'):
            raise TimeoutError("execution_timeout") from None
        raise
    finally:
        with cancellation_lock:
            stopped.set()
        if worker is not None:
            worker.join(timeout=2)
        event.remove(connection, "before_cursor_execute", before_statement)
        if dialect == "sqlite":
            driver.set_progress_handler(None, 0)
        if dialect == "postgresql" and previous_timeout is not None:
            # If a statement aborted the transaction, caller must roll it back;
            # SET LOCAL then resets automatically. Never mask the original error.
            try:
                connection.exec_driver_sql("SELECT set_config('statement_timeout', %s, true)",
                                           (str(previous_timeout),))
            except DBAPIError:
                pass
