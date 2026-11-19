"""Intake taxonomy and validated provider/form contracts."""

import uuid
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

Category = Literal[
    "plumbing",
    "electrical",
    "hvac",
    "carpentry",
    "civil_structural",
    "appliance_equipment",
    "it_network",
    "pest_control",
    "cleaning_sanitation",
    "other",
]
SafetyFlag = Literal[
    "electrical_hazard",
    "water_near_electrical",
    "gas_leak",
    "fire_risk",
    "structural_risk",
    "slip_hazard",
    "none",
]
PriorityValue = Literal["low", "medium", "high", "urgent"]
CATEGORY_IDS = {
    "plumbing": "plumbing",
    "electrical": "electrical",
    "hvac": "air-conditioning-ventilation",
    "carpentry": "carpentry",
    "civil_structural": "civil-structural",
    "appliance_equipment": "equipment-repair",
    "it_network": "it-network",
    "pest_control": "pest-control",
    "cleaning_sanitation": "cleaning-sanitation",
    "other": "other",
}
Short = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=500)]


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)


class QuestionAnswer(StrictModel):
    question: Short
    answer: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=2000)]


class FollowUpRound(StrictModel):
    answers: Annotated[list[QuestionAnswer], Field(min_length=1, max_length=3)]


class TriageInput(StrictModel):
    description: Annotated[str, Field(min_length=1, max_length=10000)]
    branch_id: uuid.UUID | None = None
    location_detail: Annotated[str, Field(max_length=255)] = ""
    conversation: Annotated[list[FollowUpRound], Field(max_length=2)] = Field(default_factory=list)

    @model_validator(mode="after")
    def nonblank(self):
        if not self.description.strip():
            raise ValueError("Describe the issue")
        return self


class PhotoAnalysis(StrictModel):
    provided: bool
    visible_issue: Short | None
    severity_estimate: Literal["minor", "moderate", "severe", "unknown"]
    suggested_tools_or_parts: Annotated[list[Short], Field(max_length=12)]
    matches_description: bool | None


class TriageResult(StrictModel):
    language_detected: Literal["en", "tl", "taglish", "other"]
    normalized_description: Annotated[
        str, StringConstraints(strip_whitespace=True, min_length=1, max_length=10000)
    ]
    original_description: Annotated[str, Field(max_length=10000)]
    category: Category
    subcategory: Annotated[
        str, StringConstraints(strip_whitespace=True, min_length=1, max_length=180)
    ]
    priority: PriorityValue
    priority_reason: Short
    safety_flags: Annotated[list[SafetyFlag], Field(max_length=7)]
    confidence: float = Field(ge=0, le=1)
    needs_more_info: bool
    follow_up_questions: Annotated[list[Short], Field(max_length=3)]
    photo_analysis: PhotoAnalysis


class TriageResponse(StrictModel):
    result: TriageResult | None
    triage_id: uuid.UUID | None
    incomplete_info: bool = False
    manual_fallback: bool = False
    message: str | None = None
    safety_flags: list[SafetyFlag] = Field(default_factory=list)


class ConfirmationInput(StrictModel):
    category: Category
    priority: PriorityValue
