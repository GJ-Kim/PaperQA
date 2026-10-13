from __future__ import annotations

import hashlib
import json
import os
import shutil
import tempfile
import threading
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .schemas import ArtifactType, Issue, Status, ToolSummary, ValidationResult
from .security import (
    PathSecurityError,
    ensure_within,
    reject_symlink_path,
    secure_permissions,
    validate_job_id,
    validate_relative_path,
)

JOB_DIRECTORIES = (
    "input",
    "incoming",
    "extracted/images",
    "metadata",
    "chunks/source",
    "chunks/translated",
    "output",
    "qa/runs",
)

DEFAULT_ARTIFACT_PATHS = {
    ArtifactType.ORIGINAL_PDF: "input/original.pdf",
    ArtifactType.DOCLING_JSON: "extracted/original.docling.json",
    ArtifactType.SOURCE_MARKDOWN: "extracted/original.md",
    ArtifactType.TRANSLATED_MARKDOWN: "output/paper_translated_ko.md",
    ArtifactType.DOCX: "output/paper_translated_ko.docx",
}


def utc_now() -> str:
    return datetime.now(UTC).isoformat()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


class Workspace:
    def __init__(self, root: Path):
        self.root = root.resolve(strict=False)
        self._result_lock = threading.RLock()
        self.root.mkdir(parents=True, exist_ok=True)
        secure_permissions(self.root)

    def job_dir(self, job_id: str, *, must_exist: bool = True) -> Path:
        validate_job_id(job_id)
        lexical_path = self.root / job_id
        reject_symlink_path(self.root, lexical_path)
        path = ensure_within(self.root, lexical_path)
        if must_exist and not path.is_dir():
            raise FileNotFoundError(f"Unknown job_id: {job_id}")
        return path

    def path(self, job_id: str, relative_path: str, *, must_exist: bool = True) -> Path:
        base = self.job_dir(job_id)
        rel = validate_relative_path(relative_path)
        lexical_candidate = base.joinpath(*rel.parts)
        reject_symlink_path(base, lexical_candidate)
        candidate = ensure_within(base, lexical_candidate)
        if must_exist and not candidate.exists():
            raise FileNotFoundError(f"Artifact does not exist: {relative_path}")
        return candidate

    def create_job(self, label: str | None = None) -> dict[str, Any]:
        job_id = f"paper-{uuid.uuid4().hex[:16]}"
        base = self.job_dir(job_id, must_exist=False)
        base.mkdir(mode=0o750)
        for relative in JOB_DIRECTORIES:
            (base / relative).mkdir(parents=True, exist_ok=True)
        metadata = {
            "job_id": job_id,
            "label": label,
            "created_at": utc_now(),
            "schema_version": "1.0",
        }
        self.write_json(job_id, "metadata/job.json", metadata)
        return {**metadata, "incoming_path": f"{job_id}/incoming"}

    def register_artifact(
        self,
        job_id: str,
        source_path: str,
        artifact_type: ArtifactType,
        destination_path: str | None = None,
    ) -> dict[str, Any]:
        source = self.path(job_id, source_path)
        if not source.is_file():
            raise ValueError("Artifact source must be a regular file")
        if not source_path.startswith("incoming/"):
            raise PathSecurityError(
                "New artifacts may only be registered from the job's incoming/ directory"
            )
        destination_rel = destination_path or DEFAULT_ARTIFACT_PATHS.get(artifact_type)
        if destination_rel is None:
            destination_rel = f"extracted/{source.name}"
        destination_parts = validate_relative_path(destination_rel).parts
        if destination_parts[0] not in {"input", "extracted", "output"}:
            raise PathSecurityError(
                "Registered artifact destinations must be under input/, extracted/, or output/"
            )
        destination = self.path(job_id, destination_rel, must_exist=False)
        destination.parent.mkdir(parents=True, exist_ok=True)
        self._atomic_copy(source, destination)
        record = {
            "artifact_type": artifact_type.value,
            "source_path": source_path,
            "path": destination_rel,
            "size": destination.stat().st_size,
            "sha256": sha256_file(destination),
            "registered_at": utc_now(),
        }
        registry_path = "metadata/artifacts.json"
        registry = self.read_json(job_id, registry_path, default={"artifacts": []})
        registry["artifacts"] = [r for r in registry["artifacts"] if r["path"] != destination_rel]
        registry["artifacts"].append(record)
        self.write_json(job_id, registry_path, registry)
        return {"job_id": job_id, **record}

    def read_json(self, job_id: str, relative_path: str, default: Any = None) -> Any:
        try:
            path = self.path(job_id, relative_path)
        except FileNotFoundError:
            if default is not None:
                return default
            raise
        with path.open("r", encoding="utf-8") as stream:
            return json.load(stream)

    def write_json(self, job_id: str, relative_path: str, value: Any) -> Path:
        return self.write_text(
            job_id,
            relative_path,
            json.dumps(value, ensure_ascii=False, indent=2) + "\n",
        )

    def write_text(self, job_id: str, relative_path: str, value: str) -> Path:
        path = self.path(job_id, relative_path, must_exist=False)
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, temp_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
        try:
            with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as stream:
                stream.write(value)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temp_name, path)
            secure_permissions(path)
        finally:
            if os.path.exists(temp_name):
                os.unlink(temp_name)
        return path

    def save_result(
        self,
        job_id: str,
        check: str,
        status: Status,
        counts: dict[str, int],
        issues: list[Issue],
        metadata: dict[str, Any] | None = None,
        max_issues: int = 50,
    ) -> ToolSummary:
        with self._result_lock:
            return self._save_result_locked(
                job_id, check, status, counts, issues, metadata, max_issues
            )

    def _save_result_locked(
        self,
        job_id: str,
        check: str,
        status: Status,
        counts: dict[str, int],
        issues: list[Issue],
        metadata: dict[str, Any] | None,
        max_issues: int,
    ) -> ToolSummary:
        run_id = f"{datetime.now(UTC).strftime('%Y%m%dT%H%M%S%fZ')}-{uuid.uuid4().hex[:6]}"
        result_path = f"qa/runs/{run_id}-{check}.json"
        result = ValidationResult(
            job_id=job_id,
            run_id=run_id,
            check=check,
            status=status,
            counts=counts,
            issues=issues,
            report_path=result_path,
            created_at=utc_now(),
            metadata=metadata or {},
        )
        payload = result.model_dump(mode="json")
        self.write_json(job_id, result_path, payload)
        latest = self.read_json(job_id, "qa/results.json", default={"job_id": job_id, "checks": {}})
        latest["checks"][check] = payload
        latest["updated_at"] = utc_now()
        self.write_json(job_id, "qa/results.json", latest)
        history = self.path(job_id, "qa/run_history.jsonl", must_exist=False)
        history.parent.mkdir(parents=True, exist_ok=True)
        with history.open("a", encoding="utf-8", newline="\n") as stream:
            stream.write(
                json.dumps(
                    {
                        k: payload[k]
                        for k in ("run_id", "check", "status", "created_at", "report_path")
                    }
                )
                + "\n"
            )
        return ToolSummary(
            job_id=job_id,
            check=check,
            status=status,
            counts=counts,
            issues=issues[:max_issues],
            total_issues=len(issues),
            report_path=result_path,
        )

    @staticmethod
    def _atomic_copy(source: Path, destination: Path) -> None:
        fd, temp_name = tempfile.mkstemp(prefix=f".{destination.name}.", dir=destination.parent)
        os.close(fd)
        try:
            shutil.copyfile(source, temp_name)
            os.replace(temp_name, destination)
            secure_permissions(destination)
        finally:
            if os.path.exists(temp_name):
                os.unlink(temp_name)
