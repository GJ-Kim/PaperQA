from __future__ import annotations

import json
import re
import subprocess
from collections import defaultdict, deque
from pathlib import Path
from typing import Any

from ..schemas import Issue, Severity, Status


def _walk(value: Any):
    if isinstance(value, dict):
        yield value
        for child in value.values():
            yield from _walk(child)
    elif isinstance(value, list):
        for child in value:
            yield from _walk(child)


def extract_math(path: Path, pandoc_binary: str) -> list[dict[str, Any]]:
    process = subprocess.run(
        [pandoc_binary, "--from=markdown+tex_math_dollars+raw_tex", "--to=json", str(path)],
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=120,
    )
    if process.returncode:
        raise RuntimeError(process.stderr.strip() or "Pandoc failed")
    ast = json.loads(process.stdout)
    math = []
    for node in _walk(ast):
        if node.get("t") != "Math":
            continue
        content = node.get("c", [])
        if len(content) != 2:
            continue
        style = content[0].get("t", "Unknown") if isinstance(content[0], dict) else "Unknown"
        math.append(
            {"type": "display" if style == "DisplayMath" else "inline", "latex": content[1]}
        )
    return math


def _normalize(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip()


def compare_math(
    source: list[dict[str, Any]], target: list[dict[str, Any]], mode: str
) -> tuple[Status, dict[str, int], list[Issue]]:
    key = (lambda value: value) if mode == "strict" else _normalize
    available: defaultdict[str, deque[int]] = defaultdict(deque)
    for index, item in enumerate(target):
        available[key(item["latex"])].append(index)
    matched_targets: set[int] = set()
    issues: list[Issue] = []
    for source_index, item in enumerate(source):
        candidates = available[key(item["latex"])]
        if not candidates:
            issues.append(
                Issue(
                    severity=Severity.ERROR,
                    code="EQUATION_MISSING_OR_CHANGED",
                    message="Source equation was not found unchanged in the target",
                    details={
                        "source_index": source_index + 1,
                        "math_type": item["type"],
                        "latex": item["latex"][:500],
                    },
                )
            )
            continue
        target_index = candidates.popleft()
        matched_targets.add(target_index)
        if item["type"] != target[target_index]["type"]:
            issues.append(
                Issue(
                    severity=Severity.WARNING,
                    code="EQUATION_TYPE_CHANGED",
                    message="Equation changed between inline and display form",
                    details={"source_index": source_index + 1, "target_index": target_index + 1},
                )
            )
        if target_index < source_index and len(source) == len(target):
            issues.append(
                Issue(
                    severity=Severity.WARNING,
                    code="EQUATION_ORDER_CHANGED",
                    message="Equation order may have changed",
                    details={"source_index": source_index + 1, "target_index": target_index + 1},
                )
            )
    for index, item in enumerate(target):
        if index not in matched_targets:
            issues.append(
                Issue(
                    severity=Severity.ERROR,
                    code="EQUATION_ADDED",
                    message="Target contains an equation not found in the source",
                    details={"target_index": index + 1, "latex": item["latex"][:500]},
                )
            )
    status = (
        Status.FAIL
        if any(issue.severity == Severity.ERROR for issue in issues)
        else (Status.WARN if issues else Status.PASS)
    )
    return (
        status,
        {"source": len(source), "target": len(target), "matched": len(matched_targets)},
        issues,
    )
