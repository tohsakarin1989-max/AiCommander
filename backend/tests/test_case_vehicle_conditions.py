import pytest
from pydantic import ValidationError

from app.api.cases import CaseVehicleCreate, CaseVehicleDraft, create_case_vehicle, list_case_vehicles
from app.services.case_pipeline_service import CasePipelineService
from app.services.case_road_vehicle import frozen_road_vehicle
from app.services.case_service import CaseService
from test_case_pipeline import db_session, _create_case  # noqa: F401


@pytest.mark.parametrize('schema', [CaseVehicleCreate, CaseVehicleDraft])
@pytest.mark.parametrize('field,value', [('height_m', 0), ('height_m', True), ('height_m', '3米'),
    ('height_m', float('nan')), ('gross_weight_t', -1), ('gross_weight_t', float('inf')),
    ('road_vehicle_kind', 'ignore_restrictions')])
def test_vehicle_conditions_validate_without_guessing_units(schema, field, value):
    with pytest.raises(ValidationError):
        schema.model_validate({field: value})


def test_recorded_conditions_save_read_freeze_and_clear_through_existing_services(db_session):
    case = _create_case(db_session)
    vehicle = create_case_vehicle(case.id, CaseVehicleCreate(vehicle_type='重型挂车',
        road_vehicle_kind='truck', height_m=3.2, gross_weight_t=12.5, oil_volume=2.), db_session)
    assert list_case_vehicles(case.id, db_session)[0].gross_weight_t == 12.5
    saved = CasePipelineService.build_profile_payload(db_session, case)
    frozen = frozen_road_vehicle(saved)
    assert frozen.model_dump() == {'kind': 'truck', 'height_m': 3.2, 'weight_t': 12.5, 'source': 'case_record'}
    before = CasePipelineService.source_hash(db_session, case)
    draft = CaseVehicleDraft(id=vehicle.id, gross_weight_t=None)
    CaseService.update_case(db_session, case.id, initial_vehicles=[draft.model_dump(exclude_unset=True)])
    db_session.refresh(vehicle)
    assert vehicle.gross_weight_t is None and vehicle.height_m == 3.2 and vehicle.oil_volume == 2.
    assert CasePipelineService.source_hash(db_session, case) != before
    assert frozen_road_vehicle(CasePipelineService.build_profile_payload(db_session, case)) is None
    assert frozen_road_vehicle(saved).weight_t == 12.5


def test_legacy_record_does_not_require_or_fabricate_road_fields():
    assert CaseVehicleCreate(vehicle_type='重型挂车').gross_weight_t is None
    assert CaseVehicleDraft().road_vehicle_kind is None
