"""The committed evaluation fixture must match independent recomputation.

Plan section 25: the evaluation XML pins ten read-only question/answer
pairs for an agent that knows nothing about BeatScope internals. These
tests keep the fixture honest: the committed rhythm.json hashes match the
manifest, and every answer still recomputes from the fixture cache through
the same service layer the MCP server exposes.
"""
from __future__ import annotations

import hashlib
import shutil
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

EVAL_DIR = Path(__file__).resolve().parents[2] / "evaluations"
sys.path.insert(0, str(EVAL_DIR))

import answers  # noqa: E402

pytestmark = [
    pytest.mark.anyio,
    pytest.mark.skipif(shutil.which("node") is None, reason="node is not available"),
]


def _load_xml() -> dict[str, ET.Element]:
    root = ET.parse(EVAL_DIR / "beatscope_mcp.xml").getroot()
    return {pair.get("id"): pair for pair in root.findall("qa_pair")}


def test_manifest_hashes_match_committed_cache():
    for entry in answers.load_manifest()["projects"]:
        rhythm_file = (
            answers.fixture_cache_root() / "projects" / entry["project_id"] / "rhythm.json"
        )
        assert rhythm_file.is_file(), f"missing fixture project: {entry['name']}"
        digest = hashlib.sha256(rhythm_file.read_bytes()).hexdigest()
        assert digest == entry["rhythm_sha256"], entry["name"]
        assert b"\r\n" not in rhythm_file.read_bytes(), entry["name"]


def test_manifest_covers_the_three_fixture_projects():
    names = {entry["name"] for entry in answers.load_manifest()["projects"]}
    assert {"fixed-120", "offgrid", "tempo-change"} <= names


def test_xml_has_exactly_the_ten_pinned_questions():
    pairs = _load_xml()
    expected = {question["id"] for question in answers.questions()}
    assert set(pairs) == expected
    assert len(pairs) == 10


async def test_evaluation_answers_recompute_to_xml_values():
    pairs = _load_xml()
    service, bridge = await answers.build_service()
    try:
        for question in answers.questions():
            pair = pairs[question["id"]]
            recomputed = (await question["compute"](service, bridge)).strip()
            pinned = (pair.findtext("answer") or "").strip()
            assert pinned == recomputed, f"answer drift on {question['id']}"
            pinned_question = (pair.findtext("question") or "").strip()
            assert pinned_question == question["question"].strip(), question["id"]
    finally:
        await bridge.close()
