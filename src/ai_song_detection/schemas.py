"""Public API result contracts."""

from typing import Literal

from pydantic import BaseModel, Field


class ModelInfo(BaseModel):
    name: str
    version: str
    sha256: str
    upstream_commit: str


class DetectionResult(BaseModel):
    filename: str
    assessment: Literal["likely_ai_generated", "likely_human_created", "uncertain"]
    ai_score: float = Field(
        ge=0, le=1, description="Uncalibrated AI model score; not a verified probability"
    )
    threshold: float = Field(
        ge=0,
        le=1,
        description="Upstream binary threshold; this app also uses a 0.4-0.6 uncertainty band",
    )
    audio_duration_seconds: float = Field(ge=0)
    analyzed_duration_seconds: float = Field(ge=0, le=300)
    truncated: bool
    processing_time_ms: float = Field(ge=0)
    model: ModelInfo
    warnings: list[str]
