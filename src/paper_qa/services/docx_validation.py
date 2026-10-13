from __future__ import annotations

import zipfile
from pathlib import Path
from typing import Any

from lxml import etree

from ..schemas import Issue, Severity, Status

MATH_NS = "http://schemas.openxmlformats.org/officeDocument/2006/math"
WORD_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
DRAWING_NS = "http://schemas.openxmlformats.org/drawingml/2006/main"
PARTS = (
    "word/document.xml",
    "word/footnotes.xml",
    "word/endnotes.xml",
    "word/header1.xml",
    "word/footer1.xml",
)


def inspect_docx(
    path: Path, expected_equations: list[dict[str, Any]]
) -> tuple[Status, dict[str, int], list[Issue], dict[str, Any]]:
    issues: list[Issue] = []
    omath = 0
    omath_para = 0
    drawings = 0
    bookmarks: set[str] = set()
    inspected: list[str] = []
    try:
        with zipfile.ZipFile(path) as archive:
            bad = archive.testzip()
            if bad:
                raise zipfile.BadZipFile(f"CRC failure in {bad}")
            for name in archive.namelist():
                if (
                    name == "word/document.xml"
                    or name in PARTS
                    or (name.startswith("word/header") and name.endswith(".xml"))
                    or (name.startswith("word/footer") and name.endswith(".xml"))
                ):
                    try:
                        root = etree.fromstring(
                            archive.read(name),
                            parser=etree.XMLParser(
                                resolve_entities=False, no_network=True, huge_tree=False
                            ),
                        )
                    except etree.XMLSyntaxError as exc:
                        issues.append(
                            Issue(
                                severity=Severity.ERROR,
                                code="DOCX_XML_INVALID",
                                path=name,
                                message=f"OOXML part is not valid XML: {exc}",
                            )
                        )
                        continue
                    inspected.append(name)
                    omath += len(root.xpath(".//m:oMath", namespaces={"m": MATH_NS}))
                    omath_para += len(root.xpath(".//m:oMathPara", namespaces={"m": MATH_NS}))
                    drawings += len(root.xpath(".//a:blip", namespaces={"a": DRAWING_NS}))
                    for node in root.xpath(".//w:bookmarkStart", namespaces={"w": WORD_NS}):
                        value = node.get(f"{{{WORD_NS}}}name")
                        if value:
                            bookmarks.add(value)
    except (zipfile.BadZipFile, OSError) as exc:
        issues.append(
            Issue(
                severity=Severity.ERROR,
                code="DOCX_ARCHIVE_INVALID",
                message=f"DOCX is not a valid ZIP archive: {exc}",
            )
        )
        return (
            Status.FAIL,
            {"expected_math": len(expected_equations), "omath": 0, "bookmarks": 0},
            issues,
            {},
        )

    expected_ids = [str(item["id"]) for item in expected_equations]
    matched_bookmarks = [
        element_id
        for element_id in expected_ids
        if f"qa-{element_id}" in bookmarks or f"qa_{element_id}" in bookmarks
    ]
    if expected_ids and omath == 0:
        issues.append(
            Issue(
                severity=Severity.ERROR,
                code="OMML_MISSING",
                message="Equations are expected but no Office Math objects were found",
            )
        )
    elif expected_ids and omath < len(expected_ids):
        issues.append(
            Issue(
                severity=Severity.WARNING,
                code="OMML_COUNT_LOW",
                message=(
                    "There are fewer OMML objects than expected equations; "
                    "splitting/merging prevents a definitive failure"
                ),
                details={"expected": len(expected_ids), "omath": omath},
            )
        )
    if expected_ids and not matched_bookmarks:
        issues.append(
            Issue(
                severity=Severity.WARNING,
                code="EQUATION_BOOKMARKS_NOT_PRESERVED",
                message=(
                    "Pandoc did not preserve qa-equation bookmarks; validation "
                    "fell back to aggregate OMML evidence"
                ),
            )
        )
    elif len(matched_bookmarks) < len(expected_ids):
        missing = sorted(set(expected_ids) - set(matched_bookmarks))
        issues.append(
            Issue(
                severity=Severity.WARNING,
                code="EQUATION_BOOKMARK_MAPPING_PARTIAL",
                message="Only some equation bookmarks were found in the DOCX",
                details={"missing_element_ids": missing[:100]},
            )
        )
    if expected_ids and drawings and omath == 0:
        issues.append(
            Issue(
                severity=Severity.WARNING,
                code="POSSIBLE_EQUATION_IMAGES",
                message=(
                    "The document contains drawings but no OMML; equations may "
                    "have been converted to images"
                ),
                details={"drawings": drawings},
            )
        )
    status = (
        Status.FAIL
        if any(item.severity == Severity.ERROR for item in issues)
        else (Status.WARN if issues else Status.PASS)
    )
    counts = {
        "expected_math": len(expected_ids),
        "omath": omath,
        "omath_para": omath_para,
        "drawings": drawings,
        "bookmarks": len(bookmarks),
        "matched_equation_bookmarks": len(matched_bookmarks),
    }
    inventory = {
        "parts": inspected,
        "bookmark_names": sorted(bookmarks),
        "matched_equation_ids": matched_bookmarks,
        "counts": counts,
    }
    return status, counts, issues, inventory
