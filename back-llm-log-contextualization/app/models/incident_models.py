from typing import List, Optional

from pydantic import BaseModel, Field


class IncidentReport(BaseModel):
    """Structured representation of a detected incident in the grid."""

    incident_id: str = Field(..., description="Unique identifier for the incident.")
    severity: str = Field(
        ...,
        description="Severity level of the incident (e.g., info, warning, critical).",
    )
    description: str = Field(..., description="Human-readable description of the incident.")
    recommended_actions: List[str] = Field(
        default_factory=list,
        description="Suggested remediation steps for operators.",
    )
    related_signals: Optional[List[str]] = Field(
        default=None,
        description="Optional list of related signals, assets, or log identifiers.",
    )

