"""The pattern router: what a route may match, and what it must not."""
from beatscope.routing import match_route

ROUTES = [
    ("GET", ("api", "projects",), "list_projects"),
    ("GET", ("api", "projects", ":id"), "get_project"),
    ("GET", ("api", "projects", ":id", "assets", ":asset_id"), "get_asset"),
    ("DELETE", ("api", "jobs", ":id"), "cancel_job"),
]


def test_a_literal_pattern_matches_only_itself():
    assert match_route(ROUTES, "GET", ["api", "projects"]) == ("list_projects", {})


def test_a_colon_segment_is_captured_by_name():
    handler, params = match_route(ROUTES, "GET", ["api", "projects", "0a1b2c3d4e5f"])
    assert handler == "get_project"
    assert params == {"id": "0a1b2c3d4e5f"}


def test_every_captured_segment_is_reported():
    handler, params = match_route(ROUTES, "GET", ["api", "projects", "0a1b2c3d4e5f", "assets", "cd" * 32])
    assert handler == "get_asset"
    assert params == {"id": "0a1b2c3d4e5f", "asset_id": "cd" * 32}


def test_the_segment_count_must_match_exactly():
    """A shorter route must not answer for a longer path."""
    assert match_route(ROUTES, "GET", ["api", "projects", "0a1b2c3d4e5f", "audio"]) == (None, {})
    assert match_route(ROUTES, "GET", ["api"]) == (None, {})


def test_the_method_is_part_of_the_match():
    assert match_route(ROUTES, "POST", ["api", "projects"]) == (None, {})
    assert match_route(ROUTES, "DELETE", ["api", "jobs", "abc"]) == ("cancel_job", {"id": "abc"})


def test_a_literal_segment_that_differs_does_not_match():
    assert match_route(ROUTES, "GET", ["api", "albums"]) == (None, {})


def test_an_empty_path_matches_nothing():
    assert match_route(ROUTES, "GET", []) == (None, {})
