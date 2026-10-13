from __future__ import annotations

from pathlib import Path
from typing import Any

from ..schemas import Issue, Severity, Status
from .latex_validation import _walk, extract_math


def markdown_inventory(path: Path, pandoc_binary: str) -> dict[str, Any]:
    import json
    import subprocess

    process = subprocess.run(
        [pandoc_binary, "--from=markdown+tex_math_dollars+fenced_divs", "--to=json", str(path)],
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=120,
    )
    if process.returncode:
        raise RuntimeError(process.stderr.strip() or "Pandoc failed")
    ast = json.loads(process.stdout)
    headings: list[dict[str, Any]] = []
    images: list[str] = []
    links: list[str] = []
    tables = 0
    for node in _walk(ast):
        node_type = node.get("t")
        content = node.get("c")
        if node_type == "Header" and isinstance(content, list) and len(content) >= 3:
            text = "".join(
                part.get("c", "") for part in _walk(content[2]) if part.get("t") in {"Str", "Code"}
            )
            headings.append({"level": content[0], "text": text})
        elif node_type == "Table":
            tables += 1
        elif node_type in {"Image", "Link"} and isinstance(content, list) and content:
            target = content[-1]
            if isinstance(target, list) and target and isinstance(target[0], str):
                (images if node_type == "Image" else links).append(target[0])
    return {
        "headings": headings,
        "tables": tables,
        "images": images,
        "links": links,
        "math": extract_math(path, pandoc_binary),
    }


def validate_structure(
    job_root: Path,
    source_index: dict[str, Any],
    target_path: Path,
    pandoc_binary: str,
) -> tuple[Status, dict[str, int], list[Issue], dict[str, Any]]:
    inventory = markdown_inventory(target_path, pandoc_binary)
    expected = source_index.get("elements", [])
    expected_counts = {
        "headings": sum(item.get("type") == "heading" for item in expected),
        "tables": sum(item.get("type") == "table" for item in expected),
        "figures": sum(item.get("type") == "figure" for item in expected),
        "captions": sum(item.get("type") == "caption" for item in expected),
        "references": sum(item.get("type") == "reference" for item in expected),
    }
    issues: list[Issue] = []
    if len(inventory["headings"]) < expected_counts["headings"]:
        issues.append(
            Issue(
                severity=Severity.ERROR,
                code="HEADING_MISSING",
                message="Target has fewer headings than the source index",
                details={
                    "expected": expected_counts["headings"],
                    "actual": len(inventory["headings"]),
                },
            )
        )
    if inventory["tables"] < expected_counts["tables"]:
        issues.append(
            Issue(
                severity=Severity.ERROR,
                code="TABLE_MISSING",
                message="Target has fewer tables than the source index",
                details={"expected": expected_counts["tables"], "actual": inventory["tables"]},
            )
        )
    if len(inventory["images"]) < expected_counts["figures"]:
        issues.append(
            Issue(
                severity=Severity.WARNING,
                code="FIGURE_COUNT_LOW",
                message=(
                    "Target has fewer Markdown images than source figures; embedded "
                    "Docling representations may require manual review"
                ),
                details={
                    "expected": expected_counts["figures"],
                    "actual": len(inventory["images"]),
                },
            )
        )
    for link in inventory["images"]:
        if "://" in link or link.startswith("data:"):
            continue
        resolved = (target_path.parent / link).resolve(strict=False)
        try:
            resolved.relative_to(job_root.resolve())
        except ValueError:
            issues.append(
                Issue(
                    severity=Severity.ERROR,
                    code="IMAGE_PATH_ESCAPE",
                    path=link,
                    message="Image path escapes the job workspace",
                )
            )
            continue
        if not resolved.is_file():
            issues.append(
                Issue(
                    severity=Severity.ERROR,
                    code="IMAGE_FILE_MISSING",
                    path=link,
                    message="Referenced image file does not exist",
                )
            )
    status = (
        Status.FAIL
        if any(item.severity == Severity.ERROR for item in issues)
        else (Status.WARN if issues else Status.PASS)
    )
    counts = {
        **{f"source_{k}": v for k, v in expected_counts.items()},
        "target_headings": len(inventory["headings"]),
        "target_tables": inventory["tables"],
        "target_images": len(inventory["images"]),
    }
    return status, counts, issues, inventory
