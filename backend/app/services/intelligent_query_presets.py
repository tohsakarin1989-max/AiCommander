"""Explicit user-selected business requests, not a pretend language model."""
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


PRESETS = {'case_count': 'count_cases', 'case_process': 'read_case_process',
           'case_result': 'explain_case_result', 'facility_dossier': 'read_facility_dossier',
           'facility_history': 'read_facility_at', 'coverage_scenario': 'compare_coverage_scenario'}


class QueryPreset(BaseModel):
    model_config = ConfigDict(extra='forbid')
    name: Literal['case_count', 'case_process', 'case_result', 'facility_dossier', 'facility_history', 'coverage_scenario']
    arguments: dict = Field(default_factory=dict)

    @model_validator(mode='after')
    def validate_arguments(self):
        from app.services.intelligent_query_tools import TOOLS
        self.arguments = TOOLS[PRESETS[self.name]].model_validate(self.arguments).model_dump(mode='json', exclude_unset=True)
        return self


async def run_preset(db, question, preset, *, context=None, cancelled=lambda: False, envelope=None):
    from app.services.intelligent_query_loop import run_query
    # A fixed call is an intentional business preset, explicitly labelled as
    # such; it is not an emulated model response or model acceptance evidence.
    request = QueryPreset.model_validate(preset)
    from app.services.question_contract import make_question_spec
    return await run_query(db, question, None, context=context, cancelled=cancelled,
                           preset_call=(PRESETS[request.name], request.arguments), envelope=envelope,
                           question_spec=make_question_spec(question, context=context,
                               preset=request.model_dump(mode='json')))
