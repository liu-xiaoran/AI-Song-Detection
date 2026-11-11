"""Public API result contracts."""

from typing import Literal

from pydantic import BaseModel, Field


class ModelInfo(BaseModel):
    name: str
    version: str
    sha256: str
    upstream_commit: str


class DecisionPolicy(BaseModel):
    id: str
    version: int
    human_below: float
    ai_above: float
    uncertain_inclusive: tuple[float, float]
    validated: bool


class DetectionResult(BaseModel):
    filename: str
    assessment: Literal["likely_ai_generated", "likely_human_created", "uncertain"]
    ai_score: float = Field(
        ge=0, le=1, description="Uncalibrated AI model score; not a verified probability"
    )
    threshold: float = Field(
        ge=0,
        le=1,
        description="Deprecated upstream binary reference; use decision_policy for app assessments",
        deprecated=True,
    )
    upstream_binary_threshold: float = Field(ge=0, le=1)
    decision_policy: DecisionPolicy
    report_id: str
    input_sha256: str
    input_size_bytes: int = Field(ge=0)
    application_version: str
    analyzed_at: str
    analyzed_start_seconds: float = Field(ge=0)
    analyzed_end_seconds: float = Field(ge=0)
    requested_duration_seconds: float = Field(ge=10, le=300)
    audio_duration_seconds: float = Field(ge=0)
    analyzed_duration_seconds: float = Field(ge=0, le=300)
    truncated: bool
    processing_time_ms: float = Field(ge=0)
    model: ModelInfo
    warnings: list[str]


class JobError(BaseModel):
    code: str
    message: str


class DetectionJob(BaseModel):
    id: str
    status: Literal["queued", "running", "cancelling", "completed", "failed", "cancelled"]
    stage: Literal["queued", "hashing", "decoding", "preprocessing", "inference", "complete"]
    created_at: str
    updated_at: str
    result: DetectionResult | None = None
    error: JobError | None = None
