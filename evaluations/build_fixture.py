"""Rebuild the fixed MCP evaluation fixture (plan section 25).

Generates three deterministic synthetic songs, analyzes them with the
declared configurations into a committed cache, and writes the evaluation
XML plus the manifest that pins the project ids and rhythm hashes.

The committed fixture must stay deterministic: analysis timestamps are
pinned, and project.json audio paths are rewritten to a stable relative
placeholder so regenerating on another machine produces identical bytes.

Usage: python evaluations/build_fixture.py
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import sys
import xml.etree.ElementTree as ET
from pathlib import Path
from xml.dom import minidom

EVAL_DIR = Path(__file__).resolve().parent
REPO_ROOT = EVAL_DIR.parent
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(REPO_ROOT / "tests"))

from fixtures.generate_audio import generate_all  # noqa: E402

FIXED_CREATED_AT = "2026-08-29T00:00:00Z"
AUDIO_PLACEHOLDER = "evaluations/fixtures/mcp-eval-cache/source.audio"

PROJECT_SPECS = [
    {"name": "fixed-120", "subdivision": 16},
    {"name": "offgrid", "subdivision": 32},
    {"name": "tempo-change", "subdivision": 16},
]


def _write_text_lf(path: Path, text: str) -> None:
    """Write deterministic UTF-8 bytes without platform newline translation."""
    path.write_bytes(text.replace("\r\n", "\n").encode("utf-8"))


def _normalize_json_tree(root: Path) -> None:
    for path in root.rglob("*.json"):
        _write_text_lf(path, path.read_text(encoding="utf-8"))


def main() -> int:
    import tempfile

    import answers
    from beatscope.models import AnalysisConfig
    from beatscope.pipeline import analyze_track
    from beatscope.project import ProjectManager, compute_cache_key, content_hash
    from beatscope.schema import ANALYZER_VERSION, SCHEMA_VERSION

    cache_root = EVAL_DIR / "fixtures" / "mcp-eval-cache"
    manager = ProjectManager(cache_root)
    entries = []
    with tempfile.TemporaryDirectory(prefix="beatscope-eval-") as work:
        audio = generate_all(work)
        for spec in PROJECT_SPECS:
            wav = Path(audio[spec["name"]]["audio"])
            cfg = AnalysisConfig(backend="lightweight", subdivision=spec["subdivision"], separation="auto")
            rhythm = analyze_track(wav, cfg, display_name=wav.name)
            rhythm["analysis"]["created_at"] = FIXED_CREATED_AT
            project_dir = manager.save_project(
                rhythm["project_id"], wav, rhythm, cfg.to_dict(),
                cache_key=compute_cache_key(content_hash(wav), cfg.to_dict()),
            )
            # Stable, machine-independent meta: the committed fixture is
            # read-only and never serves audio, so the path is a placeholder.
            meta_file = project_dir / "project.json"
            meta = json.loads(meta_file.read_text(encoding="utf-8"))
            meta["audio_path"] = AUDIO_PLACEHOLDER
            meta["created_at"] = FIXED_CREATED_AT
            _write_text_lf(meta_file, json.dumps(meta, indent=2, ensure_ascii=False))
            _normalize_json_tree(project_dir)
            entries.append({
                "name": spec["name"],
                "project_id": rhythm["project_id"],
                "display_name": wav.name,
                "backend": "lightweight",
                "subdivision": spec["subdivision"],
                "created_at": FIXED_CREATED_AT,
                "rhythm_sha256": hashlib.sha256(
                    (project_dir / "rhythm.json").read_bytes()
                ).hexdigest(),
            })

    manifest = {
        "schema_version": SCHEMA_VERSION,
        "analyzer_version": ANALYZER_VERSION,
        "created_at": FIXED_CREATED_AT,
        "fixture_cache": "fixtures/mcp-eval-cache",
        "projects": entries,
        "questions_file": "beatscope_mcp.xml",
    }
    _write_text_lf(
        EVAL_DIR / "fixtures-manifest.json",
        json.dumps(manifest, indent=2, ensure_ascii=False) + "\n",
    )

    async def build_xml() -> ET.Element:
        service, bridge = await answers.build_service()
        try:
            root = ET.Element("evaluation")
            for question in answers.questions():
                pair = ET.SubElement(root, "qa_pair", {"id": question["id"]})
                ET.SubElement(pair, "question").text = question["question"]
                ET.SubElement(pair, "answer").text = await question["compute"](service, bridge)
            return root
        finally:
            await bridge.close()

    root = asyncio.run(build_xml())

    xml_text = minidom.parseString(ET.tostring(root, encoding="unicode")).toprettyxml(indent="  ")
    lines = [line for line in xml_text.splitlines() if line.strip()]
    _write_text_lf(EVAL_DIR / "beatscope_mcp.xml", "\n".join(lines) + "\n")

    for entry in entries:
        print(f"{entry['name']}: {entry['project_id']} (rhythm sha256 {entry['rhythm_sha256'][:12]}...)")
    print(f"Wrote {EVAL_DIR / 'beatscope_mcp.xml'} and fixtures-manifest.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
