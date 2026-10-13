from __future__ import annotations

from typing import Any

from fastmcp import FastMCP

from ..config import Settings
from ..schemas import ArtifactType, Issue, Severity, Status
from ..services.docling_index import create_index
from ..services.docx_validation import inspect_docx
from ..services.latex_validation import compare_math, extract_math
from ..services.manifest import (
    MARKER_RE,
    create_chunks,
    validate_completeness,
    validate_manifest,
)
from ..services.manifest import (
    merge_translated_chunks as merge_chunks,
)
from ..services.report import generate_report as build_report
from ..services.structure_validation import validate_structure
from ..storage import Workspace, sha256_file


def install_tools(mcp: FastMCP, settings: Settings, workspace: Workspace) -> None:
    def summary(value: Any) -> dict[str, Any]:
        return value.model_dump(mode="json") if hasattr(value, "model_dump") else value

    @mcp.tool
    def health() -> dict[str, Any]:
        """Return server readiness and dependency configuration without reading paper contents."""
        return {
            "status": "ok",
            "root": str(settings.root),
            "pandoc": settings.pandoc_binary,
            "schema_version": "1.0",
        }

    @mcp.tool
    def create_job(label: str | None = None) -> dict[str, Any]:
        """Create an isolated paper QA job and return its server-generated ID."""
        return workspace.create_job(label)

    @mcp.tool
    def register_artifact(
        job_id: str,
        source_path: str,
        artifact_type: ArtifactType,
        destination_path: str | None = None,
    ) -> dict[str, Any]:
        """Copy and register a file already placed in this job's incoming directory."""
        return workspace.register_artifact(job_id, source_path, artifact_type, destination_path)

    @mcp.tool
    def create_source_index(
        job_id: str, docling_json_path: str = "extracted/original.docling.json"
    ) -> dict[str, Any]:
        """Create normalized element, equation, and structure indexes from Docling JSON."""
        source_path = workspace.path(job_id, docling_json_path)
        index = create_index(job_id, source_path)
        index_path = "metadata/source_index.json"
        workspace.write_json(job_id, index_path, index)
        equations = {
            "job_id": job_id,
            "source_sha256": index["source_sha256"],
            "equations": [
                {k: item.get(k) for k in ("id", "page", "order", "latex", "latex_sha256")}
                for item in index["elements"]
                if item["type"] == "equation"
            ],
        }
        structures = {
            "job_id": job_id,
            "elements": [
                {k: item.get(k) for k in ("id", "type", "page", "order", "section")}
                for item in index["elements"]
                if item["type"] != "paragraph"
            ],
        }
        workspace.write_json(job_id, "metadata/equation_inventory.json", equations)
        workspace.write_json(job_id, "metadata/structure_inventory.json", structures)
        return {
            "job_id": job_id,
            "status": "PASS",
            "counts": index["counts"],
            "elements": len(index["elements"]),
            "source_index_path": index_path,
            "equation_inventory_path": "metadata/equation_inventory.json",
            "structure_inventory_path": "metadata/structure_inventory.json",
        }

    @mcp.tool
    def create_translation_chunks(
        job_id: str,
        source_index_path: str = "metadata/source_index.json",
        max_chars: int = 12000,
    ) -> dict[str, Any]:
        """Create marker-preserving source chunks and their manifest from the normalized index."""
        index = workspace.read_json(job_id, source_index_path)
        manifest = create_chunks(workspace, job_id, index, max_chars)
        manifest_path = "metadata/manifest.json"
        workspace.write_json(job_id, manifest_path, manifest)
        return {
            "job_id": job_id,
            "status": "PASS",
            "chunks": len(manifest["chunks"]),
            "elements": sum(len(item["element_ids"]) for item in manifest["chunks"]),
            "manifest_path": manifest_path,
            "source_chunk_dir": "chunks/source",
        }

    @mcp.tool
    def create_chunk_manifest(
        job_id: str,
        source_chunk_dir: str = "chunks/source",
        source_index_path: str = "metadata/source_index.json",
    ) -> dict[str, Any]:
        """Build and validate a manifest for existing marker-bearing source chunk files."""
        directory = workspace.path(job_id, source_chunk_dir)
        if not directory.is_dir():
            raise ValueError("source_chunk_dir must be a directory")
        chunks = []
        for path in sorted(directory.glob("*.md")):
            relative = path.relative_to(workspace.job_dir(job_id)).as_posix()
            chunk_id = path.stem
            content = path.read_text(encoding="utf-8")
            chunks.append(
                {
                    "chunk_id": chunk_id,
                    "element_ids": MARKER_RE.findall(content),
                    "source_path": relative,
                    "translated_path": f"chunks/translated/{chunk_id}_ko.md",
                    "status": "pending",
                    "source_sha256": sha256_file(path),
                    "translated_sha256": None,
                }
            )
        manifest = {"job_id": job_id, "schema_version": "1.0", "chunks": chunks}
        issues = validate_manifest(workspace.read_json(job_id, source_index_path), manifest)
        workspace.write_json(job_id, "metadata/manifest.json", manifest)
        status = Status.FAIL if issues else Status.PASS
        result = workspace.save_result(
            job_id,
            "chunk_manifest",
            status,
            {"chunks": len(chunks), "elements": sum(len(item["element_ids"]) for item in chunks)},
            issues,
            max_issues=settings.max_issues,
        )
        return summary(result)

    @mcp.tool
    def validate_translation_completeness(
        job_id: str,
        manifest_path: str = "metadata/manifest.json",
        suspicious_ratio: float = 0.35,
    ) -> dict[str, Any]:
        """Detect missing, empty, duplicate, unknown, or suspiciously short translated elements."""
        if suspicious_ratio < 0 or suspicious_ratio > 1:
            raise ValueError("suspicious_ratio must be between 0 and 1")
        manifest = workspace.read_json(job_id, manifest_path)
        status, counts, issues = validate_completeness(
            workspace, job_id, manifest, suspicious_ratio
        )
        return summary(
            workspace.save_result(
                job_id,
                "translation_completeness",
                status,
                counts,
                issues,
                {"suspicious_ratio": suspicious_ratio},
                settings.max_issues,
            )
        )

    @mcp.tool
    def merge_translated_chunks(
        job_id: str, manifest_path: str = "metadata/manifest.json"
    ) -> dict[str, Any]:
        """Merge validated translated chunks in manifest order into the output Markdown file."""
        manifest = workspace.read_json(job_id, manifest_path)
        return merge_chunks(workspace, job_id, manifest)

    @mcp.tool
    def validate_latex_equations(
        job_id: str,
        source_md_path: str = "extracted/original.md",
        target_md_path: str = "output/paper_translated_ko.md",
        mode: str = "strict",
    ) -> dict[str, Any]:
        """Compare Pandoc Math AST nodes using strict or whitespace-normalized LaTeX text."""
        if mode not in {"strict", "normalized"}:
            raise ValueError("mode must be strict or normalized")
        source_path = workspace.path(job_id, source_md_path)
        target_path = workspace.path(job_id, target_md_path)
        try:
            source = extract_math(source_path, settings.pandoc_binary)
            target = extract_math(target_path, settings.pandoc_binary)
            status, counts, issues = compare_math(source, target, mode)
            metadata = {
                "mode": mode,
                "normalization": "none" if mode == "strict" else "collapse Unicode whitespace",
                "source_sha256": sha256_file(source_path),
                "target_sha256": sha256_file(target_path),
            }
        except (FileNotFoundError, RuntimeError, TimeoutError) as exc:
            status, counts = Status.NOT_CHECKED, {"source": 0, "target": 0, "matched": 0}
            issues = [
                Issue(
                    severity=Severity.WARNING, code="PANDOC_UNAVAILABLE_OR_FAILED", message=str(exc)
                )
            ]
            metadata = {"mode": mode}
        return summary(
            workspace.save_result(
                job_id, "latex_equations", status, counts, issues, metadata, settings.max_issues
            )
        )

    @mcp.tool
    def validate_document_structure(
        job_id: str,
        source_index_path: str = "metadata/source_index.json",
        target_md_path: str = "output/paper_translated_ko.md",
    ) -> dict[str, Any]:
        """Validate headings, tables, figures, and local image paths using Pandoc AST."""
        target = workspace.path(job_id, target_md_path)
        try:
            status, counts, issues, inventory = validate_structure(
                workspace.job_dir(job_id),
                workspace.read_json(job_id, source_index_path),
                target,
                settings.pandoc_binary,
            )
            workspace.write_json(job_id, "qa/structure_inventory.json", inventory)
        except (FileNotFoundError, RuntimeError, TimeoutError) as exc:
            status, counts = Status.NOT_CHECKED, {}
            issues = [
                Issue(
                    severity=Severity.WARNING, code="STRUCTURE_CHECK_UNAVAILABLE", message=str(exc)
                )
            ]
        return summary(
            workspace.save_result(
                job_id, "document_structure", status, counts, issues, {}, settings.max_issues
            )
        )

    @mcp.tool
    def validate_docx_omml(
        job_id: str,
        docx_path: str = "output/paper_translated_ko.docx",
        expected_math_inventory_path: str = "metadata/equation_inventory.json",
    ) -> dict[str, Any]:
        """Check DOCX ZIP/XML integrity, Office Math, drawings, and qa-equation bookmarks."""
        inventory = workspace.read_json(job_id, expected_math_inventory_path)
        status, counts, issues, docx_inventory = inspect_docx(
            workspace.path(job_id, docx_path), inventory.get("equations", [])
        )
        workspace.write_json(job_id, "qa/docx_inventory.json", docx_inventory)
        return summary(
            workspace.save_result(
                job_id,
                "docx_omml",
                status,
                counts,
                issues,
                {"docx_sha256": sha256_file(workspace.path(job_id, docx_path))},
                settings.max_issues,
            )
        )

    @mcp.tool
    def generate_qa_report(job_id: str, format: str = "markdown") -> dict[str, Any]:
        """Generate the cumulative QA report. JSON state is always kept in qa/results.json."""
        if format not in {"markdown", "json", "both"}:
            raise ValueError("format must be markdown, json, or both")
        result = build_report(workspace, job_id)
        if format == "json":
            result["path"] = "qa/results.json"
        elif format == "both":
            result["json_path"] = "qa/results.json"
        return result

    @mcp.tool
    def get_validation_summary(job_id: str, max_issues: int = 20) -> dict[str, Any]:
        """Return compact latest statuses and a bounded issue list for an existing job."""
        if max_issues < 0 or max_issues > 200:
            raise ValueError("max_issues must be between 0 and 200")
        results = workspace.read_json(job_id, "qa/results.json", default={"checks": {}})
        checks = results.get("checks", {})
        issues = []
        for name, check in checks.items():
            for issue in check.get("issues", []):
                issues.append({"check": name, **issue})
        statuses = {name: value.get("status") for name, value in checks.items()}
        overall = (
            "FAIL"
            if "FAIL" in statuses.values()
            else (
                "WARN"
                if "WARN" in statuses.values()
                else (
                    "NOT_CHECKED" if not statuses or "NOT_CHECKED" in statuses.values() else "PASS"
                )
            )
        )
        return {
            "job_id": job_id,
            "status": overall,
            "checks": statuses,
            "total_issues": len(issues),
            "issues": issues[:max_issues],
            "results_path": "qa/results.json",
        }
