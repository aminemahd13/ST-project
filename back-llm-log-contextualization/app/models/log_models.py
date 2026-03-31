from datetime import datetime
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class LogInput(BaseModel):
    """Input model representing a batch or single grid log entry."""

    source: str = Field(..., description="Origin of the log data (e.g., substation, SCADA).")
    timestamp: datetime = Field(..., description="Timestamp associated with the log data.")
    message: str = Field(..., description="Raw log message or content.")
    metadata: Optional[Dict[str, Any]] = Field(
        default=None,
        description="Optional metadata associated with the log entry.",
    )


class AnalysisOutput(BaseModel):
    """High-level analysis results produced by the analysis agent."""

    summary: str = Field(..., description="Short natural language description of the log context.")
    detected_anomalies: List[str] = Field(
        default_factory=list,
        description="List of identifiers or descriptions of detected anomalies.",
    )
    confidence: float = Field(
        default=0.0,
        ge=0.0,
        le=1.0,
        description="Overall confidence score for the analysis.",
    )

