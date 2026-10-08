"""Source-revision CAS for the daily editor; legacy writes remain compatible."""
from sqlalchemy import func, select

from app.database import require_area_write_access
from app.models.case import Case, CasePerson, CaseVehicle
from app.models.case_source import CaseLocation, CaseRevision, OilMeasurement
from app.services.case_intake_contract import normalize_intake
from app.services.case_number_service import ensure_number_transaction
from app.services.case_service import CaseService
from app.services.case_source_service import field_value


NULLABLE_CASE_UPDATE_FIELDS = {
    "occurred_time", "occurred_from", "occurred_to", "time_expression", "discovered_at",
    "location", "case_type", "description", "latitude", "longitude", "involved_persons",
    "involved_items", "loss_amount", "oil_type", "oil_volume", "oil_value", "facility_type",
    "facility_owner", "security_level", "modus_operandi", "suspect_roles", "vehicle_info",
    "upstream_source", "downstream_destination", "report_time", "report_unit", "source_type",
    "source_detail", "police_reported", "case_filed", "police_officer", "police_phone",
    "security_officers", "oil_nature", "water_cut", "vehicle_handling", "person_handling",
    "oil_handling", "operation_role", "current_stage",
}


class CaseEditUnavailable(LookupError):
    pass


class CaseEditConflict(ValueError):
    def __init__(self, current_revision):
        super().__init__("案件原始资料已更新，请保留本地输入并比较最新内容")
        self.current_revision = current_revision


def lock_case(db, case_id, *, write):
    connection = db.connection()
    if write:
        ensure_number_transaction(db)
    elif connection.dialect.name == "sqlite" and not connection.connection.driver_connection.in_transaction:
        # SQLite's legacy driver mode otherwise gives each SELECT a new snapshot.
        connection.exec_driver_sql("BEGIN")
    statement = select(Case).where(Case.id == case_id).with_for_update(read=not write)
    with db.no_autoflush:
        case = db.scalar(statement.execution_options(populate_existing=True))
    if case is None:
        raise CaseEditUnavailable("案件不存在或当前无权访问")
    if write:
        require_area_write_access(db, case.operational_area_id)
    return case


def source_revision(db, case_id):
    return db.scalar(select(func.max(CaseRevision.revision)).where(CaseRevision.case_id == case_id)) or 0


def edit_snapshot(db, case_id):
    with db.no_autoflush:
        case = lock_case(db, case_id, write=False)
        result = {"case": case, "source_revision": source_revision(db, case_id)}
        for key, model in (("initial_vehicles", CaseVehicle), ("initial_persons", CasePerson),
                           ("initial_locations", CaseLocation), ("initial_measurements", OilMeasurement)):
            rows = db.query(model).populate_existing().filter(model.case_id == case_id).order_by(model.id).all()
            result[key] = [{column.name: field_value(row, column) for column in model.__table__.columns}
                           for row in rows]
        return result


def update_case_checked(db, case_id, values, *, expected_revision=None, commit=True):
    try:
        case = lock_case(db, case_id, write=True)
        if expected_revision is not None:
            current = source_revision(db, case_id)
            if current != expected_revision:
                raise CaseEditConflict(current)
        values = normalize_intake(dict(values), case)
        vehicles, persons = values.pop("initial_vehicles", None), values.pop("initial_persons", None)
        for field, value in values.items():
            if value is None and field not in NULLABLE_CASE_UPDATE_FIELDS:
                raise ValueError(f"{field} 不能为空")
        case = CaseService.update_case(db, case_id, initial_vehicles=vehicles, initial_persons=persons,
            replace_vehicles=vehicles is not None, replace_persons=persons is not None,
            commit=False, **values)
        if commit:
            db.commit()
            db.refresh(case)
        return case
    except Exception:
        db.rollback()
        raise
