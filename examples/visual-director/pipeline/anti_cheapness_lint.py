"""Configurable AST + regex anti-cheapness static gate.

Inspects pipeline / scene Python source files before rendering so banned APIs
cannot quietly creep back in. Profiles keep BeatScope's core style-neutral:
strict rules apply only when selected by the project spec.
"""
from __future__ import annotations

import argparse
import ast
import json
import re
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Iterable

PROFILES: dict[str, dict[str, object]] = {
    "universal-baseline": {
        "description": "Style-neutral baseline: allows any creative aesthetic while blocking unseeded randomness and cliche fake-glitch text.",
        "forbidden_calls": [
            "random.random",
            "random.randint",
            "random.uniform",
            "random.choice",
            "np.random.rand",
            "np.random.randn",
            "np.random.randint",
        ],
        "forbidden_attrs": [],
        "forbidden_regex": [
            r"['\"](?:ERR\s*\d+[-_]\d+|NO\s+SIGNAL|SYSTEM\s+ERROR)['\"]",
        ],
    },
    "strict-darkroom": {
        "description": "Zero text/UI, zero bloom/glare/blur glow, zero smooth alpha fades.",
        "forbidden_calls": [
            "cv2.putText",
            "putText",
            "ImageDraw.text",
            "bpy.ops.object.text_add",
            "cv2.GaussianBlur",
            "GaussianBlur",
            "cv2.blur",
            "cv2.medianBlur",
            "cv2.addWeighted",
        ],
        "forbidden_attrs": [
            "use_bloom",
            "use_motion_blur",
        ],
        "forbidden_regex": [
            r"\bCompositorNodeGlare\b",
            r"['\"]BLOOM['\"]",
            r"['\"]GLARE['\"]",
            r"['\"]FONT['\"]",
        ],
    },
    "editorial-kinetic": {
        "description": "Allows intentional typography while blocking bloom/glare/blur glow stickers.",
        "forbidden_calls": [
            "cv2.GaussianBlur",
            "GaussianBlur",
            "cv2.blur",
        ],
        "forbidden_attrs": [
            "use_bloom",
            "use_motion_blur",
        ],
        "forbidden_regex": [
            r"\bCompositorNodeGlare\b",
            r"['\"]BLOOM['\"]",
            r"['\"]GLARE['\"]",
        ],
    },
    "off": {
        "description": "Disable style-specific bans (still checks Python syntax).",
        "forbidden_calls": [],
        "forbidden_attrs": [],
        "forbidden_regex": [],
    },
}


@dataclass(frozen=True)
class LintViolation:
    file: str
    line: int
    rule: str
    detail: str


class AntiCheapnessViolation(RuntimeError):
    def __init__(self, violations: list[LintViolation]) -> None:
        self.violations = violations
        summary = "\n".join(
            f"  - {v.file}:{v.line} [{v.rule}] {v.detail}" for v in violations
        )
        super().__init__(f"Anti-cheapness lint blocked render ({len(violations)} violations):\n{summary}")


def _dotted_name(node: ast.AST) -> str:
    parts: list[str] = []
    current: ast.AST | None = node
    while isinstance(current, ast.Attribute):
        parts.append(current.attr)
        current = current.value
    if isinstance(current, ast.Name):
        parts.append(current.id)
    return ".".join(reversed(parts))


def load_rules(profile: str = "strict-darkroom", custom_rules_path: Path | None = None) -> dict[str, list[str]]:
    if custom_rules_path is not None:
        raw = json.loads(custom_rules_path.read_text(encoding="utf-8"))
        return {
            "forbidden_calls": list(raw.get("forbidden_calls", [])),
            "forbidden_attrs": list(raw.get("forbidden_attrs", [])),
            "forbidden_regex": list(raw.get("forbidden_regex", [])),
        }
    if profile not in PROFILES:
        raise ValueError(f"Unknown lint profile {profile!r}; choose from {sorted(PROFILES)}")
    selected = PROFILES[profile]
    return {
        "forbidden_calls": list(selected["forbidden_calls"]),  # type: ignore[arg-type]
        "forbidden_attrs": list(selected["forbidden_attrs"]),  # type: ignore[arg-type]
        "forbidden_regex": list(selected["forbidden_regex"]),  # type: ignore[arg-type]
    }


def scan_file(path: Path, rules: dict[str, list[str]]) -> list[LintViolation]:
    text = path.read_text(encoding="utf-8")
    lines = text.splitlines()
    violations: list[LintViolation] = []

    def allowed_on(lineno: int) -> bool:
        if 1 <= lineno <= len(lines):
            return "# lint-allow:" in lines[lineno - 1]
        return False

    try:
        tree = ast.parse(text, filename=str(path))
    except SyntaxError as exc:
        return [LintViolation(str(path), exc.lineno or 1, "syntax", str(exc))]

    forbidden_calls = set(rules["forbidden_calls"])
    forbidden_attrs = set(rules["forbidden_attrs"])

    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            dotted = _dotted_name(node.func)
            short = dotted.rsplit(".", 1)[-1] if dotted else ""
            if (dotted in forbidden_calls or short in forbidden_calls) and not allowed_on(node.lineno):
                violations.append(
                    LintViolation(str(path), node.lineno, "forbidden-call", f"banned call '{dotted or short}'")
                )
        elif isinstance(node, ast.Assign):
            is_explicit_false = isinstance(node.value, ast.Constant) and node.value.value is False
            if is_explicit_false:
                continue
            for target in node.targets:
                if isinstance(target, ast.Attribute) and target.attr in forbidden_attrs and not allowed_on(node.lineno):
                    violations.append(
                        LintViolation(str(path), node.lineno, "forbidden-attr", f"banned attribute assignment '.{target.attr}'")
                    )

    compiled_patterns = [re.compile(pat) for pat in rules["forbidden_regex"]]
    for lineno, line in enumerate(lines, start=1):
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or allowed_on(lineno):
            continue
        code_part = line.split("#", 1)[0]
        for pattern in compiled_patterns:
            match = pattern.search(code_part)
            if match:
                violations.append(
                    LintViolation(str(path), lineno, "forbidden-regex", f"matched '{match.group(0)}'")
                )

    return violations


def scan_paths(
    paths: Iterable[Path],
    profile: str = "strict-darkroom",
    custom_rules_path: Path | None = None,
    *,
    exclude_names: set[str] | None = None,
) -> list[LintViolation]:
    rules = load_rules(profile, custom_rules_path)
    excluded = exclude_names if exclude_names is not None else {"anti_cheapness_lint.py"}
    violations: list[LintViolation] = []
    for target in paths:
        if target.is_dir():
            for py in sorted(target.rglob("*.py")):
                if py.name in excluded or "__pycache__" in py.parts:
                    continue
                violations.extend(scan_file(py, rules))
        elif target.is_file() and target.suffix == ".py" and target.name not in excluded:
            violations.extend(scan_file(target, rules))
    return violations


def enforce_lint(
    paths: Iterable[Path],
    profile: str = "strict-darkroom",
    custom_rules_path: Path | None = None,
) -> list[LintViolation]:
    violations = scan_paths(paths, profile=profile, custom_rules_path=custom_rules_path)
    if violations:
        raise AntiCheapnessViolation(violations)
    return []


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Anti-cheapness static code linter.")
    parser.add_argument("targets", nargs="+", type=Path, help="Python files or directories to scan")
    parser.add_argument("--profile", default="strict-darkroom", choices=sorted(PROFILES))
    parser.add_argument("--rules", type=Path, default=None, help="Custom JSON rule file")
    parser.add_argument("--json", action="store_true", help="Emit JSON report")
    args = parser.parse_args(argv)

    violations = scan_paths(args.targets, profile=args.profile, custom_rules_path=args.rules)
    if args.json:
        print(json.dumps({
            "profile": args.profile,
            "ok": not violations,
            "violations": [asdict(v) for v in violations],
        }, ensure_ascii=False, indent=2))
    elif violations:
        for v in violations:
            print(f"[BLOCK] {v.file}:{v.line} ({v.rule}): {v.detail}", file=sys.stderr)
    else:
        print(f"[PASS] Anti-cheapness lint ({args.profile}): 0 violations")
    return 1 if violations else 0


if __name__ == "__main__":
    raise SystemExit(main())
