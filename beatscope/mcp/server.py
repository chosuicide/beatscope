"""BeatScope MCP server: agents query Rhythm IR without reading source.

``main()`` only configures stderr logging, builds the server, and runs
stdio (plan section 8). Tool/resource handlers adapt the protocol to
``BeatScopeService``; all workflow logic lives in the service layer.
"""
from __future__ import annotations

import json
import logging
import sys
from contextlib import asynccontextmanager
from importlib import resources

from mcp.server import MCPServer
from mcp.server.mcpserver import Context
from mcp.server.mcpserver.exceptions import ResourceError, ToolError
from mcp.types import ToolAnnotations
from pydantic import ValidationError

from ..project import ProjectManager
from .errors import BeatScopeMCPError, RuntimeUnavailable
from .models import (
    AnalyzeAudioInput,
    EventsInput,
    ExportInput,
    GetProjectInput,
    ListProjectsInput,
    VisualStateInput,
)
from .paths import MCPSettings, PathPolicy
from .runtime_bridge import RuntimeBridge
from .service import BeatScopeService

SERVER_NAME = "beatscope_mcp"

INSTRUCTIONS = (
    "Use BeatScope timing facts for audio-reactive work. "
    "Do not infer kick, snare, or 808 identity from onsets."
)


def _read_only(title: str) -> ToolAnnotations:
    return ToolAnnotations(
        title=title,
        read_only_hint=True,
        destructive_hint=False,
        idempotent_hint=True,
        open_world_hint=False,
    )


def _schema_json() -> str:
    return (resources.files("beatscope.mcp") / "data" / "schema_v4.json").read_text(encoding="utf-8")


def _service(ctx: Context) -> BeatScopeService:
    state = ctx.request_context.lifespan_context
    service = state.get("service") if isinstance(state, dict) else None
    if service is None:
        raise ToolError("BeatScope service is not initialised.")
    return service


def _call(action) -> dict:
    """Run a service action and map expected failures to actionable ToolErrors.

    ``action`` is a zero-argument callable so that pydantic input validation
    happens *inside* the guarded region; models built at the call site would
    escape as unexpected exceptions and lose their messages.
    """
    try:
        return action()
    except (BeatScopeMCPError, ValidationError) as exc:
        raise ToolError(str(exc)) from None


async def _acall(action) -> dict:
    """Async sibling of _call for service methods that await the runtime."""
    try:
        return await action()
    except (BeatScopeMCPError, ValidationError) as exc:
        raise ToolError(str(exc)) from None


def create_server(settings: MCPSettings | None = None) -> MCPServer:
    server_settings = settings or MCPSettings.from_env()

    @asynccontextmanager
    async def lifespan(server: MCPServer):
        projects = ProjectManager(server_settings.cache_root)
        paths = PathPolicy(server_settings.allowed_roots)
        runtime = RuntimeBridge(node_command=server_settings.node_command)
        try:
            await runtime.start()
        except RuntimeUnavailable as exc:
            # Read-only tools stay usable without Node; runtime-backed tools
            # raise the same actionable error on call.
            print(f"beatscope-mcp: runtime bridge unavailable: {exc}", file=sys.stderr)
        service = BeatScopeService(
            projects,
            paths,
            runtime=runtime,
            max_response_chars=server_settings.max_response_chars,
        )
        try:
            yield {"service": service, "settings": server_settings}
        finally:
            await runtime.close()

    mcp = MCPServer(
        SERVER_NAME,
        instructions=INSTRUCTIONS,
        lifespan=lifespan,
        log_level=server_settings.log_level,
    )

    # ----------------------------------------------------------- resources

    @mcp.resource(
        "beatscope://schema/v4",
        name="beatscope_schema_v4",
        description="BeatScope Rhythm Project schema v4, machine-readable field reference.",
        mime_type="application/json",
    )
    def schema_v4() -> str:
        return _schema_json()

    @mcp.resource(
        "beatscope://projects/{project_id}/manifest",
        name="beatscope_project_manifest",
        description="Project summary without energy arrays or private paths.",
        mime_type="application/json",
    )
    def project_manifest(project_id: str, ctx: Context = None) -> str:
        try:
            result = _service(ctx).get_project(GetProjectInput(project_id=project_id, detail="summary"))
        except (BeatScopeMCPError, ValidationError) as exc:
            raise ResourceError(str(exc)) from None
        return json.dumps(result["data"], ensure_ascii=False)

    @mcp.resource(
        "beatscope://projects/{project_id}/rhythm",
        name="beatscope_project_rhythm",
        description="Complete schema v4 rhythm project JSON.",
        mime_type="application/json",
    )
    def project_rhythm(project_id: str, ctx: Context = None) -> str:
        try:
            rhythm = _service(ctx).load_validated_rhythm(project_id)
        except BeatScopeMCPError as exc:
            raise ResourceError(str(exc)) from None
        return json.dumps(rhythm, ensure_ascii=False, allow_nan=False)

    # --------------------------------------------------------------- tools

    @mcp.tool(
        name="beatscope_list_projects",
        description=(
            "List cached BeatScope rhythm projects with identity, BPM, bars, duration, "
            "backend, and provenance. Supports a display-name/id query, backend filter, "
            "and offset pagination."
        ),
        annotations=_read_only("List BeatScope projects"),
    )
    async def beatscope_list_projects(
        ctx: Context = None,
        query: str | None = None,
        backend: str | None = None,
        limit: int = 20,
        offset: int = 0,
    ) -> dict:
        return _call(
            lambda: _service(ctx).list_projects(
                ListProjectsInput(query=query, backend=backend, limit=limit, offset=offset)
            )
        )

    @mcp.tool(
        name="beatscope_get_project",
        description=(
            "Read one BeatScope project. detail='summary' returns identity and counts; "
            "'timing' adds beats, tempo segments, patterns, and cues (no energy arrays); "
            "'full' returns the complete schema v4 JSON unless it exceeds the response "
            "budget, in which case it points at the beatscope://projects/{id}/rhythm resource."
        ),
        annotations=_read_only("Read a BeatScope project"),
    )
    async def beatscope_get_project(
        ctx: Context = None,
        project_id: str = "",
        detail: str = "summary",
    ) -> dict:
        return _call(
            lambda: _service(ctx).get_project(
                GetProjectInput(project_id=project_id, detail=detail)
            )
        )

    @mcp.tool(
        name="beatscope_get_visual_state",
        description=(
            "Visual state at one audio instant, computed by the shared JavaScript "
            "runtime: bar, beat, beatIndex, beat/bar phases, low/mid/high/all "
            "energy, onset impulse, accent, section. Mirrors the web player's "
            "track.at(time) exactly; null onset age or accent means no previous "
            "onset exists."
        ),
        annotations=_read_only("Read BeatScope visual state"),
    )
    async def beatscope_get_visual_state(
        ctx: Context = None,
        project_id: str = "",
        time: float = 0.0,
    ) -> dict:
        return await _acall(
            lambda: _service(ctx).get_visual_state(
                VisualStateInput(project_id=project_id, time=time)
            )
        )

    @mcp.tool(
        name="beatscope_get_events",
        description=(
            "List BeatScope events in a time window (start, end]: beats, onsets "
            "(runtime boundary semantics), cues by type, and pattern bars. "
            "Windows are capped at 600 s - split longer ranges into separate "
            "queries. Results are sorted by time and kind, then paginated."
        ),
        annotations=_read_only("Read BeatScope events"),
    )
    async def beatscope_get_events(
        ctx: Context = None,
        project_id: str = "",
        start: float = 0.0,
        end: float = 0.0,
        include: list[str] | None = None,
        cue_types: list[str] | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> dict:
        kwargs: dict = {
            "project_id": project_id,
            "start": start,
            "end": end,
            "limit": limit,
            "offset": offset,
        }
        if include is not None:
            kwargs["include"] = set(include)
        if cue_types is not None:
            kwargs["cue_types"] = set(cue_types)
        return await _acall(lambda: _service(ctx).get_events(EventsInput(**kwargs)))

    @mcp.tool(
        name="beatscope_analyze_audio",
        description=(
            "Analyze an audio file into a cached BeatScope rhythm project (beats, "
            "bars, onsets, energy bands, cues) and return its project id with a "
            "tempo/grid summary. Paths must live under the server's allowed roots. "
            "Results are cached per audio content and configuration; pass "
            "force=true to re-analyze anyway. backend='beat-this' requires a .beats "
            "beat_file. Reports progress and honours cancellation - a cancelled "
            "analysis writes nothing."
        ),
        annotations=ToolAnnotations(
            title="Analyze audio with BeatScope",
            read_only_hint=False,
            destructive_hint=False,
            idempotent_hint=True,
            open_world_hint=False,
        ),
    )
    async def beatscope_analyze_audio(
        ctx: Context = None,
        audio_path: str = "",
        backend: str = "lightweight",
        subdivision: int = 16,
        beat_file: str | None = None,
        drums_path: str | None = None,
        force: bool = False,
    ) -> dict:
        service = _service(ctx)

        async def report(value: float, message: str | None = None) -> None:
            try:
                await ctx.report_progress(value, 1.0, message)
            except Exception:
                pass  # progress is best-effort; the outcome must not depend on it

        return await _acall(
            lambda: service.analyze_audio(
                AnalyzeAudioInput(
                    audio_path=audio_path,
                    backend=backend,
                    subdivision=subdivision,
                    beat_file=beat_file,
                    drums_path=drums_path,
                    force=force,
                ),
                progress=report,
            )
        )

    @mcp.tool(
        name="beatscope_export_package",
        description=(
            "Export a BeatScope project as the portable agent handoff ZIP "
            "(rhythm-map.json, shared runtime, visual-state.js, BEATSCOPE.md, "
            "SKILL.md, schema reference) and return its path, size, SHA-256, "
            "and ZIP manifest - not the binary. WRITES a local file: the "
            "destination must end in .zip and live under the server's allowed "
            "roots. An existing destination is kept unless overwrite=true."
        ),
        annotations=ToolAnnotations(
            title="Export BeatScope agent package",
            read_only_hint=False,
            destructive_hint=False,
            idempotent_hint=True,
            open_world_hint=False,
        ),
    )
    async def beatscope_export_package(
        ctx: Context = None,
        project_id: str = "",
        destination: str = "",
        overwrite: bool = False,
    ) -> dict:
        return _call(
            lambda: _service(ctx).export_package(
                ExportInput(project_id=project_id, destination=destination, overwrite=overwrite)
            )
        )

    return mcp


def configure_stderr_logging(level: str = "WARNING") -> None:
    """stdout belongs to the MCP protocol, so logs may only go to stderr."""
    logging.basicConfig(level=getattr(logging, level, logging.WARNING), stream=sys.stderr)


def main() -> None:
    settings = MCPSettings.from_env()
    configure_stderr_logging(settings.log_level)
    server = create_server(settings)
    server.run(transport="stdio")


if __name__ == "__main__":
    main()
