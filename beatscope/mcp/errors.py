"""Public, actionable MCP errors (plan section 10.4).

Tool handlers translate these into ``ToolError`` so the model receives the
message text instead of an opaque "tool crashed" wrapper.
"""
from __future__ import annotations


class BeatScopeMCPError(Exception):
    """Base class for expected, actionable BeatScope MCP failures."""


class ProjectNotFound(BeatScopeMCPError):
    pass


class PathNotAllowed(BeatScopeMCPError):
    pass


class RuntimeUnavailable(BeatScopeMCPError):
    pass


class InvalidTimeRange(BeatScopeMCPError):
    pass


class AnalysisFailed(BeatScopeMCPError):
    """The pipeline could not produce a valid project for this input."""


class AnalysisCancelledError(BeatScopeMCPError):
    """A running analysis was cancelled; nothing was written."""


class ExportTargetExists(BeatScopeMCPError):
    """The destination ZIP already exists and overwrite was not requested."""
