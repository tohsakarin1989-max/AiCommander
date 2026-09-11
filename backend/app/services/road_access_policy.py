"""Internal-road eligibility before graph compilation, independent of data visibility.

All route operations must use the same compiled eligible graph. This module
does not itself construct a graph or claim that an eligible road is connected.
"""
from dataclasses import dataclass
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class VehicleAssumption(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True, frozen=True)
    kind: Literal['auto', 'truck']
    height_m: float | None = Field(default=None, gt=0, allow_inf_nan=False)
    weight_t: float | None = Field(default=None, gt=0, allow_inf_nan=False)
    source: Literal['case_record', 'explicit_reference_assumption']


class InternalRoadConditions(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True, frozen=True)
    direction: Literal['forward', 'reverse', 'both', 'unknown'] = 'unknown'
    gate: Literal['open', 'closed', 'unknown'] = 'unknown'
    access: Literal['permitted', 'prohibited', 'unknown'] = 'unknown'
    max_height_m: float | None = Field(default=None, gt=0, allow_inf_nan=False)
    max_weight_t: float | None = Field(default=None, gt=0, allow_inf_nan=False)
    valid_from: datetime | None = None
    valid_until: datetime | None = None

    @model_validator(mode='after')
    def check_interval(self):
        for value in (self.valid_from, self.valid_until):
            if value is not None and (value.tzinfo is None or value.utcoffset() is None):
                raise ValueError('road_condition_timezone_required')
        if self.valid_from and self.valid_until and self.valid_until <= self.valid_from:
            raise ValueError('road_condition_interval_invalid')
        return self


@dataclass(frozen=True)
class RoadEligibility:
    include: bool
    reason: str
    direction: str | None = None


def internal_road_eligibility(*, conditions: InternalRoadConditions, vehicle: VehicleAssumption,
                              verified: bool, traversal_permitted: bool, at: datetime) -> RoadEligibility:
    """Fail closed; callers must resolve permission from road grants, not area visibility.

    `at` is the requested historical/current condition time, not the worker's
    clock. The caller must separately select a graph covering that time.
    """
    if type(verified) is not bool or type(traversal_permitted) is not bool:
        raise ValueError('explicit_boolean_road_authority_required')
    if at.tzinfo is None or at.utcoffset() is None:
        raise ValueError('analysis_timezone_required')
    if not traversal_permitted:
        return RoadEligibility(False, 'traversal_permission_denied')
    if not verified:
        return RoadEligibility(False, 'source_unverified')
    if conditions.gate == 'closed' or conditions.access == 'prohibited':
        return RoadEligibility(False, 'explicitly_closed')
    if conditions.valid_from and at < conditions.valid_from:
        return RoadEligibility(False, 'conditions_not_yet_valid')
    if conditions.valid_until and at >= conditions.valid_until:
        return RoadEligibility(False, 'conditions_expired')
    if conditions.gate == 'unknown' or conditions.access == 'unknown' or conditions.direction == 'unknown':
        return RoadEligibility(False, 'conditions_unknown')
    for limit, actual in ((conditions.max_height_m, vehicle.height_m), (conditions.max_weight_t, vehicle.weight_t)):
        if limit is not None:
            if actual is None:
                return RoadEligibility(False, 'vehicle_dimensions_missing')
            if actual > limit:
                return RoadEligibility(False, 'vehicle_limit_exceeded')
    return RoadEligibility(True, 'eligible_not_connectivity_confirmation', conditions.direction)
