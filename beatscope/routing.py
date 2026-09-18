"""A pattern router small enough to read in one sitting.

A pattern segment starting with ``:`` matches and captures one path segment;
every other segment must be equal. Matching requires the method to agree and the
segment count to match exactly, so a short route can never swallow a longer one
and the table's order carries no hidden meaning.
"""
from __future__ import annotations

# (method, pattern, handler method name). The handler is named rather than bound
# because the tables are module level while the handlers are methods.
Route = tuple[str, tuple[str, ...], str]


def match_route(routes: list[Route], method: str, parts: list[str]) -> tuple[str | None, dict[str, str]]:
    """The handler name for this method and path, plus its captured parameters."""
    for route_method, pattern, handler in routes:
        if route_method != method or len(pattern) != len(parts):
            continue
        params: dict[str, str] = {}
        for expected, segment in zip(pattern, parts, strict=True):
            if expected.startswith(":"):
                params[expected[1:]] = segment
            elif expected != segment:
                break
        else:
            return handler, params
    return None, {}
