from __future__ import annotations

import re
from collections import Counter
from typing import Any

from ..schemas import Issue, Severity, Status
from ..storage import Workspace, sha256_file, sha256_text

MARKER_RE = re.compile(r"<!--\s*QA:ELEMENT:([A-Za-z0-9_-]+)\s*-->")


def _render_element(element: dict[str, Any]) -> str:
    marker = f"<!-- QA:ELEMENT:{element['id']} -->"
    text = element.get("latex") or element.get("text") or ""
    kind = element.get("type")
    if kind == "heading":
        return f"{marker}\n## {text}"
    if kind == "equation":
        return f"{marker}\n::: {{#qa-{element['id']}}}\n$$\n{text}\n$$\n:::"
    if kind == "figure":
        return f"{marker}\n<!-- FIGURE {element['id']} -->"
    return f"{marker}\n{text}"


def create_chunks(
    workspace: Workspace,
    job_id: str,
    source_index: dict[str, Any],
    max_chars: int = 12000,
) -> dict[str, Any]:
    if max_chars < 1000 or max_chars > 100_000:
        raise ValueError("max_chars must be between 1000 and 100000")
    groups: list[list[dict[str, Any]]] = []
    current: list[dict[str, Any]] = []
    size = 0
    for element in source_index["elements"]:
        rendered = _render_element(element)
        if current and size + len(rendered) > max_chars:
            groups.append(current)
            current, size = [], 0
        current.append(element)
        size += len(rendered) + 2
    if current:
        groups.append(current)

    chunks = []
    for number, group in enumerate(groups, start=1):
        chunk_id = f"chunk_{number:04d}"
        relative = f"chunks/source/{chunk_id}.md"
        content = "\n\n".join(_render_element(item) for item in group) + "\n"
        workspace.write_text(job_id, relative, content)
        chunks.append(
            {
                "chunk_id": chunk_id,
                "element_ids": [item["id"] for item in group],
                "source_path": relative,
                "translated_path": f"chunks/translated/{chunk_id}_ko.md",
                "status": "pending",
                "source_sha256": sha256_text(content),
                "translated_sha256": None,
            }
        )
    return {"job_id": job_id, "schema_version": "1.0", "chunks": chunks}


def validate_manifest(index: dict[str, Any], manifest: dict[str, Any]) -> list[Issue]:
    expected = [element["id"] for element in index["elements"]]
    actual = [
        element_id
        for chunk in manifest.get("chunks", [])
        for element_id in chunk.get("element_ids", [])
    ]
    counts = Counter(actual)
    issues = [
        Issue(
            severity=Severity.ERROR,
            code="ELEMENT_MISSING_FROM_MANIFEST",
            element_id=value,
            message="Source element is not assigned to any chunk",
        )
        for value in expected
        if counts[value] == 0
    ]
    issues.extend(
        Issue(
            severity=Severity.ERROR,
            code="ELEMENT_DUPLICATED_IN_MANIFEST",
            element_id=value,
            message="Source element is assigned to multiple chunks",
        )
        for value, count in counts.items()
        if count > 1
    )
    unknown = set(actual) - set(expected)
    issues.extend(
        Issue(
            severity=Severity.ERROR,
            code="UNKNOWN_ELEMENT_IN_MANIFEST",
            element_id=value,
            message="Manifest refers to an unknown source element",
        )
        for value in sorted(unknown)
    )
    return issues


def validate_completeness(
    workspace: Workspace,
    job_id: str,
    manifest: dict[str, Any],
    suspicious_ratio: float = 0.35,
) -> tuple[Status, dict[str, int], list[Issue]]:
    issues: list[Issue] = []
    expected_ids: list[str] = []
    found_ids: list[str] = []
    translated_chunks = 0
    for chunk in manifest.get("chunks", []):
        chunk_id = chunk["chunk_id"]
        expected_ids.extend(chunk.get("element_ids", []))
        target_rel = chunk["translated_path"]
        try:
            target = workspace.path(job_id, target_rel)
        except FileNotFoundError:
            issues.append(
                Issue(
                    severity=Severity.ERROR,
                    code="TRANSLATED_CHUNK_MISSING",
                    chunk_id=chunk_id,
                    path=target_rel,
                    message="Translated chunk file is missing",
                )
            )
            continue
        content = target.read_text(encoding="utf-8")
        if not content.strip():
            issues.append(
                Issue(
                    severity=Severity.ERROR,
                    code="TRANSLATED_CHUNK_EMPTY",
                    chunk_id=chunk_id,
                    path=target_rel,
                    message="Translated chunk file is empty",
                )
            )
            continue
        translated_chunks += 1
        markers = MARKER_RE.findall(content)
        found_ids.extend(markers)
        source = workspace.path(job_id, chunk["source_path"])
        source_size = max(1, len(MARKER_RE.sub("", source.read_text(encoding="utf-8")).strip()))
        target_size = len(MARKER_RE.sub("", content).strip())
        if target_size / source_size < suspicious_ratio:
            issues.append(
                Issue(
                    severity=Severity.WARNING,
                    code="SUSPICIOUSLY_SHORT_TRANSLATION",
                    chunk_id=chunk_id,
                    path=target_rel,
                    message="Translation is unusually short; semantic review is recommended",
                    details={"character_ratio": round(target_size / source_size, 3)},
                )
            )
    marker_counts = Counter(found_ids)
    chunk_for = {
        element_id: chunk["chunk_id"]
        for chunk in manifest.get("chunks", [])
        for element_id in chunk.get("element_ids", [])
    }
    for element_id in expected_ids:
        if marker_counts[element_id] == 0:
            issues.append(
                Issue(
                    severity=Severity.ERROR,
                    code="TRANSLATED_ELEMENT_MISSING",
                    element_id=element_id,
                    chunk_id=chunk_for[element_id],
                    message="Expected element marker is missing from translated chunks",
                )
            )
        elif marker_counts[element_id] > 1:
            issues.append(
                Issue(
                    severity=Severity.ERROR,
                    code="TRANSLATED_ELEMENT_DUPLICATED",
                    element_id=element_id,
                    chunk_id=chunk_for[element_id],
                    message="Element marker appears more than once in translated chunks",
                )
            )
    for element_id in sorted(set(found_ids) - set(expected_ids)):
        issues.append(
            Issue(
                severity=Severity.ERROR,
                code="UNKNOWN_TRANSLATED_ELEMENT",
                element_id=element_id,
                message="Translated content contains an unknown element marker",
            )
        )
    status = (
        Status.FAIL
        if any(issue.severity == Severity.ERROR for issue in issues)
        else (Status.WARN if issues else Status.PASS)
    )
    return (
        status,
        {
            "expected_chunks": len(manifest.get("chunks", [])),
            "translated_chunks": translated_chunks,
            "expected_elements": len(expected_ids),
            "found_markers": len(found_ids),
        },
        issues,
    )


def merge_translated_chunks(
    workspace: Workspace, job_id: str, manifest: dict[str, Any]
) -> dict[str, Any]:
    parts: list[str] = []
    hashes: dict[str, str] = {}
    for chunk in manifest.get("chunks", []):
        relative = chunk["translated_path"]
        path = workspace.path(job_id, relative)
        text = path.read_text(encoding="utf-8").strip()
        if not text:
            raise ValueError(f"Translated chunk is empty: {relative}")
        parts.append(text)
        hashes[chunk["chunk_id"]] = sha256_file(path)
    output = "\n\n".join(parts) + "\n"
    relative = "output/paper_translated_ko.md"
    path = workspace.write_text(job_id, relative, output)
    return {"job_id": job_id, "path": relative, "sha256": sha256_file(path), "chunk_sha256": hashes}
