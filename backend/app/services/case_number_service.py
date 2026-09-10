"""Internal global namespace metadata; never exposes another area's case data."""
import sqlite3

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models.case import Case


def occupied_numbers(db: Session, prefix: str) -> list[str]:
    # The uniqueness namespace is global. Core selects ONLY reserved identifiers,
    # not ORM cases or business fields; this function has no public/tool endpoint.
    column = Case.__table__.c.case_number
    return list(db.scalars(select(column).where(column.startswith(prefix, autoescape=True))))


def is_number_collision(exc: IntegrityError) -> bool:
    original = exc.orig
    if isinstance(original, sqlite3.IntegrityError):
        return str(original) == "UNIQUE constraint failed: cases.case_number"
    diagnostic = getattr(original, "diag", None)
    return (getattr(original, "pgcode", None) == "23505"
            and getattr(diagnostic, "constraint_name", None) in {"ix_cases_case_number", "cases_case_number_key", "uq_cases_case_number"})


def ensure_number_transaction(db: Session) -> None:
    """sqlite3 legacy mode must have a real outer transaction before SAVEPOINT."""
    connection = db.connection()
    if connection.dialect.name == "sqlite" and not connection.connection.driver_connection.in_transaction:
        # Reserve the SQLite writer before reading the namespace, avoiding a
        # read-to-write lock upgrade race. PostgreSQL uses unique-index arbitration.
        connection.exec_driver_sql("BEGIN IMMEDIATE")
