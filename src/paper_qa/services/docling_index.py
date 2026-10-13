from __future__ import annotations

import hashlib
import json
from collections import defaultdict
from collections.abc import Iterable
from pathlib import Path
from typing import Any

from ..storage import sha256_file

PREFIXES = {
    "paragraph": "p",
    "heading": "h",
    "equation": "eq",
    "table": "tbl",
    "figure": "fig",
    "caption": "cap",
    "footnote": "fn",
    "reference": "ref",
}


def _resolve_pointer(document: dict[str, Any], pointer: str) -> Any:
    if not pointer.startswith("#/"):
        return None
    value: Any = document
    for token in pointer[2:].split("/"):
        token = token.replace("~1", "/").replace("~0", "~")
        if isinstance(value, list):
            value = value[int(token)]
        elif isinstance(value, dict):
            value = value.get(token)
        else:
            return None
        if value is None:
            return None
    return value


def _walk_refs(document: dict[str, Any], node: Any, seen: set[str]) -> Iterable[dict[str, Any]]:
    if isinstance(node, dict) and "$ref" in node:
        pointer = str(node["$ref"])
        if pointer in seen:
            return
        seen.add(pointer)
        resolved = _resolve_pointer(document, pointer)
        if isinstance(resolved, dict):
            yield resolved
            for child in resolved.get("children", []):
                yield from _walk_refs(document, child, seen)
        return
    if isinstance(node, dict):
        yield node
        for child in node.get("children", []):
            yield from _walk_refs(document, child, seen)


def _fallback_nodes(document: dict[str, Any]) -> Iterable[dict[str, Any]]:
    for key in ("texts", "tables", "pictures", "key_value_items", "form_items"):
        value = document.get(key, [])
        if isinstance(value, list):
            yield from (item for item in value if isinstance(item, dict))


def _page(node: dict[str, Any]) -> int | None:
    provenance = node.get("prov") or node.get("provenance") or []
    if isinstance(provenance, dict):
        provenance = [provenance]
    for item in provenance:
        if isinstance(item, dict):
            value = item.get("page_no", item.get("page"))
            if isinstance(value, int):
                return value
    return None


def _classify(node: dict[str, Any]) -> str:
    label = str(node.get("label") or node.get("type") or "").lower()
    if label in {"formula", "equation", "math", "display_formula"}:
        return "equation"
    if label in {"section_header", "title", "subtitle", "heading"}:
        return "heading"
    if "caption" in label:
        return "caption"
    if "footnote" in label:
        return "footnote"
    if label in {"reference", "bibliography", "bibliographic_reference"}:
        return "reference"
    if "table" in label:
        return "table"
    if label in {"picture", "figure", "image"}:
        return "figure"
    return "paragraph"


def _node_text(node: dict[str, Any], kind: str) -> str:
    for key in (
        ("latex", "text", "orig") if kind == "equation" else ("text", "orig", "content", "latex")
    ):
        value = node.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    if kind == "table":
        data = node.get("data")
        if isinstance(data, dict):
            cells = data.get("table_cells", data.get("cells", []))
            lines = []
            for cell in cells if isinstance(cells, list) else []:
                if isinstance(cell, dict):
                    value = cell.get("text") or cell.get("content")
                    if isinstance(value, str):
                        lines.append(value)
            return " | ".join(lines)
    return ""


def create_index(job_id: str, source_path: Path) -> dict[str, Any]:
    with source_path.open("r", encoding="utf-8") as stream:
        document = json.load(stream)
    body = document.get("body") if isinstance(document, dict) else None
    nodes = list(_walk_refs(document, body, set())) if body else []
    if not nodes:
        nodes = list(_fallback_nodes(document))
        nodes.sort(key=lambda node: (_page(node) is None, _page(node) or 0))

    counters: defaultdict[str, int] = defaultdict(int)
    elements: list[dict[str, Any]] = []
    current_section: str | None = None
    for order, node in enumerate(nodes, start=1):
        kind = _classify(node)
        text = _node_text(node, kind)
        if not text and kind not in {"figure"}:
            continue
        counters[kind] += 1
        prefix = PREFIXES[kind]
        element_id = f"{prefix}{counters[kind]:04d}"
        if kind == "heading":
            current_section = text
        digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
        item = {
            "id": element_id,
            "type": kind,
            "page": _page(node),
            "section": current_section,
            "order": order,
            "source_text_sha256": digest,
            "text": text,
            "translatable": kind != "equation",
            "docling_ref": node.get("self_ref") or node.get("$ref"),
        }
        if kind == "equation":
            item["latex"] = text
            item["latex_sha256"] = digest
        elements.append(item)
    return {
        "job_id": job_id,
        "schema_version": "1.0",
        "source_sha256": sha256_file(source_path),
        "elements": elements,
        "counts": dict(counters),
    }
