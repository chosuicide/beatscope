"""Pydantic input models for MCP tools (plan sections 12-17).

Inputs are untrusted: ``extra="forbid"`` keeps the tool surface explicit and
validators encode the parameter relationships the plan fixes.
"""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

BACKENDS = Literal["lightweight", "beat-this", "demucs"]
PROJECT_ID_PATTERN = r"^[0-9a-f]{12}$"
CUE_TYPES = Literal["accent", "impact", "scale", "flow", "flash", "bloom"]


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class AnalyzeAudioInput(StrictModel):
    audio_path: str = Field(min_length=1, max_length=4096)
    backend: BACKENDS = "lightweight"
    subdivision: Literal[16, 32] = 16
    beat_file: str | None = Field(default=None, max_length=4096)
    drums_path: str | None = Field(default=None, max_length=4096)
    force: bool = False

    @model_validator(mode="after")
    def _beat_this_requires_beat_file(self) -> "AnalyzeAudioInput":
        if self.backend == "beat-this" and not self.beat_file:
            raise ValueError(
                "backend 'beat-this' requires beat_file: a .beats file produced by "
                "the Beat This command (beatscope CLI or high-quality workflow)."
            )
        if self.backend != "beat-this" and self.beat_file:
            raise ValueError("beat_file is only valid with backend 'beat-this'.")
        return self


class ListProjectsInput(StrictModel):
    query: str | None = Field(default=None, max_length=200)
    backend: BACKENDS | None = None
    limit: int = Field(default=20, ge=1, le=100)
    offset: int = Field(default=0, ge=0)


class GetProjectInput(StrictModel):
    project_id: str = Field(pattern=PROJECT_ID_PATTERN)
    detail: Literal["summary", "timing", "full"] = "summary"


class VisualStateInput(StrictModel):
    project_id: str = Field(pattern=PROJECT_ID_PATTERN)
    time: float = Field(ge=0)


class EventsInput(StrictModel):
    project_id: str = Field(pattern=PROJECT_ID_PATTERN)
    start: float = Field(ge=0)
    end: float = Field(gt=0)
    include: set[Literal["beats", "onsets", "cues", "patterns"]] = Field(
        default_factory=lambda: {"beats", "onsets", "cues"}
    )
    cue_types: set[CUE_TYPES] = Field(
        default_factory=lambda: {"accent", "impact", "scale", "flow", "flash", "bloom"}
    )
    limit: int = Field(default=100, ge=1, le=500)
    offset: int = Field(default=0, ge=0)

    @model_validator(mode="after")
    def _window_checks(self) -> "EventsInput":
        if self.end <= self.start:
            raise ValueError(
                f"end ({self.end}) must be greater than start ({self.start}). "
                "Query each segment separately."
            )
        if self.end - self.start > 600:
            raise ValueError(
                f"Time window spans {self.end - self.start:.0f} s; the limit is 600 s. "
                "Split the range into smaller queries."
            )
        return self


class ExportInput(StrictModel):
    project_id: str = Field(pattern=PROJECT_ID_PATTERN)
    destination: str = Field(min_length=1, max_length=4096)
    overwrite: bool = False


class ProjectSummary(BaseModel):
    model_config = ConfigDict(extra="forbid")

    project_id: str
    display_name: str
    bpm: float | None = None
    bars: int = 0
    duration: float | None = None
    backend: str | None = None
    pipeline_version: str | None = None
    beats: int = 0
    onsets: int = 0
    cues: int = 0
    warnings: list[str] = Field(default_factory=list)
    provenance: dict[str, str] = Field(default_factory=dict)


class ListProjectsResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    ok: bool = True
    summary: str
    total: int
    count: int
    offset: int
    has_more: bool
    next_offset: int | None = None
    projects: list[ProjectSummary]


class GetProjectResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    ok: bool = True
    project_id: str
    summary: str
    detail: Literal["summary", "timing", "full"]
    data: dict | None = None
    truncated: bool = False
    resource: str | None = None
    note: str | None = None
