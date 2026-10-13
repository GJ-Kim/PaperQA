from __future__ import annotations

import hashlib
import json
import logging
import os
import stat
import threading
import uuid
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path, PureWindowsPath
from typing import Any, BinaryIO

from ..schemas import ArtifactType, DoclingArtifactType
from ..security import PathSecurityError
from ..storage import DEFAULT_ARTIFACT_PATHS, Workspace, sha256_file

logger = logging.getLogger(__name__)


class ImportErrorCode(StrEnum):
    INVALID_JOB_ID = "INVALID_JOB_ID"
    ACCESS_DENIED = "ACCESS_DENIED"
    INVALID_FILENAME = "INVALID_FILENAME"
    UNSUPPORTED_ARTIFACT_TYPE = "UNSUPPORTED_ARTIFACT_TYPE"
    SOURCE_NOT_FOUND = "SOURCE_NOT_FOUND"
    SOURCE_OUTSIDE_CACHE = "SOURCE_OUTSIDE_CACHE"
    FILE_TOO_LARGE = "FILE_TOO_LARGE"
    INVALID_ARTIFACT_CONTENT = "INVALID_ARTIFACT_CONTENT"
    ARTIFACT_CONFLICT = "ARTIFACT_CONFLICT"
    IMPORT_IO_ERROR = "IMPORT_IO_ERROR"
    REGISTRATION_FAILED = "REGISTRATION_FAILED"


class ArtifactImportError(RuntimeError):
    def __init__(self, code: ImportErrorCode, message: str):
        self.code = code
        self.public_message = message
        super().__init__(f"{code.value}: {message}")


@dataclass(frozen=True)
class ImportConfig:
    extension: str
    incoming_path: str
    artifact_type: ArtifactType


IMPORT_CONFIG = {
    DoclingArtifactType.DOCLING_JSON: ImportConfig(
        extension=".json",
        incoming_path="incoming/original.docling.json",
        artifact_type=ArtifactType.DOCLING_JSON,
    ),
    DoclingArtifactType.SOURCE_MARKDOWN: ImportConfig(
        extension=".md",
        incoming_path="incoming/original.md",
        artifact_type=ArtifactType.SOURCE_MARKDOWN,
    ),
}


def validate_cache_filename(filename: str) -> str:
    if (
        not filename
        or filename in {".", ".."}
        or "\x00" in filename
        or "/" in filename
        or "\\" in filename
        or Path(filename).is_absolute()
        or bool(PureWindowsPath(filename).drive)
        or Path(filename).name != filename
    ):
        raise ArtifactImportError(
            ImportErrorCode.INVALID_FILENAME,
            "filename must be a single cache basename without path separators",
        )
    return filename


class DoclingArtifactImporter:
    def __init__(self, workspace: Workspace, cache_root: Path, max_bytes: int):
        if max_bytes <= 0:
            raise ValueError("import max_bytes must be positive")
        self.workspace = workspace
        self.cache_root = cache_root
        self.max_bytes = max_bytes
        self._locks_guard = threading.Lock()
        self._locks: dict[tuple[str, str], threading.Lock] = {}

    def import_artifact(
        self,
        job_id: str,
        filename: str,
        artifact_type: DoclingArtifactType,
    ) -> dict[str, object]:
        try:
            self.workspace.job_dir(job_id)
        except (PathSecurityError, FileNotFoundError):
            raise ArtifactImportError(
                ImportErrorCode.INVALID_JOB_ID,
                "job_id is invalid or does not identify an existing job",
            ) from None

        filename = validate_cache_filename(filename)
        try:
            config = IMPORT_CONFIG[artifact_type]
        except KeyError:
            raise ArtifactImportError(
                ImportErrorCode.UNSUPPORTED_ARTIFACT_TYPE,
                "artifact_type must be docling_json or source_markdown",
            ) from None
        if not filename.lower().endswith(config.extension):
            raise ArtifactImportError(
                ImportErrorCode.INVALID_FILENAME,
                f"filename must have the {config.extension} extension",
            )

        source = self._resolve_source(filename)
        lock = self._lock_for(job_id, artifact_type.value)
        with lock:
            return self._import_locked(job_id, filename, artifact_type, config, source)

    def _lock_for(self, job_id: str, artifact_type: str) -> threading.Lock:
        key = (job_id, artifact_type)
        with self._locks_guard:
            return self._locks.setdefault(key, threading.Lock())

    def _resolve_source(self, filename: str) -> Path:
        try:
            if self.cache_root.is_symlink():
                raise ArtifactImportError(
                    ImportErrorCode.SOURCE_OUTSIDE_CACHE,
                    "configured Docling cache root must not be a symbolic link",
                )
            root = self.cache_root.resolve(strict=True)
        except FileNotFoundError:
            raise ArtifactImportError(
                ImportErrorCode.SOURCE_NOT_FOUND,
                "configured Docling cache is unavailable",
            ) from None

        candidate = self.cache_root / filename
        try:
            if candidate.is_symlink():
                raise ArtifactImportError(
                    ImportErrorCode.SOURCE_OUTSIDE_CACHE,
                    "symbolic links are not accepted as Docling artifacts",
                )
            resolved = candidate.resolve(strict=True)
            resolved.relative_to(root)
        except ArtifactImportError:
            raise
        except FileNotFoundError:
            raise ArtifactImportError(
                ImportErrorCode.SOURCE_NOT_FOUND,
                "Docling cache artifact does not exist",
            ) from None
        except (OSError, ValueError):
            raise ArtifactImportError(
                ImportErrorCode.SOURCE_OUTSIDE_CACHE,
                "Docling cache artifact resolves outside the approved cache",
            ) from None
        if not resolved.is_file():
            raise ArtifactImportError(
                ImportErrorCode.SOURCE_NOT_FOUND,
                "Docling cache artifact is not a regular file",
            )
        return candidate

    def _import_locked(
        self,
        job_id: str,
        filename: str,
        artifact_type: DoclingArtifactType,
        config: ImportConfig,
        source: Path,
    ) -> dict[str, object]:
        incoming = self.workspace.path(job_id, config.incoming_path, must_exist=False)
        canonical_rel = DEFAULT_ARTIFACT_PATHS[config.artifact_type]
        canonical = self.workspace.path(job_id, canonical_rel, must_exist=False)
        temp = incoming.parent / f".docling-import-{uuid.uuid4().hex}.tmp"
        created_incoming = False
        canonical_existed = canonical.exists()
        try:
            size, digest = self._bounded_copy(source, temp)
            self._validate_content(temp, artifact_type)

            if canonical.exists():
                if sha256_file(canonical) != digest:
                    raise ArtifactImportError(
                        ImportErrorCode.ARTIFACT_CONFLICT,
                        "canonical artifact already exists with different content",
                    )
                if self._is_registered(job_id, canonical_rel, digest):
                    return self._success(
                        job_id, artifact_type, canonical_rel, filename, size, digest, True
                    )

            if incoming.exists():
                if not incoming.is_file() or incoming.is_symlink():
                    raise ArtifactImportError(
                        ImportErrorCode.ARTIFACT_CONFLICT,
                        "incoming artifact target is not a safe regular file",
                    )
                if sha256_file(incoming) != digest:
                    raise ArtifactImportError(
                        ImportErrorCode.ARTIFACT_CONFLICT,
                        "incoming artifact already exists with different content",
                    )
            else:
                os.replace(temp, incoming)
                created_incoming = True

            try:
                registered = self.workspace.register_artifact(
                    job_id,
                    config.incoming_path,
                    config.artifact_type,
                )
            except Exception as exc:
                if not canonical_existed and canonical.exists():
                    canonical.unlink()
                if created_incoming and incoming.exists():
                    incoming.unlink()
                raise ArtifactImportError(
                    ImportErrorCode.REGISTRATION_FAILED,
                    "artifact registration failed and newly created files were rolled back",
                ) from exc

            result = self._success(
                job_id,
                artifact_type,
                str(registered["path"]),
                filename,
                int(registered["size"]),
                str(registered["sha256"]),
                False,
            )
            logger.info(
                "Docling artifact registered job_id=%s type=%s digest=%s",
                job_id,
                artifact_type.value,
                digest[:12],
            )
            return result
        except ArtifactImportError:
            raise
        except OSError as exc:
            raise ArtifactImportError(
                ImportErrorCode.IMPORT_IO_ERROR,
                "Docling artifact could not be imported due to a storage I/O error",
            ) from exc
        finally:
            if temp.exists():
                temp.unlink()

    def _bounded_copy(self, source: Path, destination: Path) -> tuple[int, str]:
        flags = os.O_RDONLY | getattr(os, "O_BINARY", 0)
        if hasattr(os, "O_NOFOLLOW"):
            flags |= os.O_NOFOLLOW
        try:
            descriptor = os.open(source, flags)
        except FileNotFoundError:
            raise ArtifactImportError(
                ImportErrorCode.SOURCE_NOT_FOUND,
                "Docling cache artifact disappeared before it could be imported",
            ) from None
        except OSError as exc:
            raise ArtifactImportError(
                ImportErrorCode.SOURCE_OUTSIDE_CACHE,
                "Docling cache artifact could not be opened safely",
            ) from exc

        digest = hashlib.sha256()
        size = 0
        try:
            source_stat = os.fstat(descriptor)
            if not stat.S_ISREG(source_stat.st_mode):
                raise ArtifactImportError(
                    ImportErrorCode.SOURCE_OUTSIDE_CACHE,
                    "Docling cache artifact is not a regular file",
                )
            if source_stat.st_size > self.max_bytes:
                raise ArtifactImportError(
                    ImportErrorCode.FILE_TOO_LARGE,
                    "Docling artifact exceeds the configured import size limit",
                )
            with os.fdopen(descriptor, "rb", closefd=True) as source_stream:
                descriptor = -1
                with destination.open("xb") as target_stream:
                    size = self._copy_stream(source_stream, target_stream, digest)
                    target_stream.flush()
                    os.fsync(target_stream.fileno())
        finally:
            if descriptor >= 0:
                os.close(descriptor)
        return size, digest.hexdigest()

    def _copy_stream(
        self,
        source: BinaryIO,
        target: BinaryIO,
        digest: Any,
    ) -> int:
        size = 0
        while block := source.read(1024 * 1024):
            size += len(block)
            if size > self.max_bytes:
                raise ArtifactImportError(
                    ImportErrorCode.FILE_TOO_LARGE,
                    "Docling artifact exceeds the configured import size limit",
                )
            target.write(block)
            digest.update(block)
        return size

    @staticmethod
    def _validate_content(path: Path, artifact_type: DoclingArtifactType) -> None:
        if artifact_type == DoclingArtifactType.DOCLING_JSON:
            try:
                with path.open("r", encoding="utf-8") as stream:
                    value = json.load(stream)
            except (UnicodeDecodeError, json.JSONDecodeError):
                raise ArtifactImportError(
                    ImportErrorCode.INVALID_ARTIFACT_CONTENT,
                    "Docling JSON must be valid UTF-8 JSON",
                ) from None
            if not isinstance(value, dict):
                raise ArtifactImportError(
                    ImportErrorCode.INVALID_ARTIFACT_CONTENT,
                    "Docling JSON root must be an object",
                )
            return

        try:
            has_content = False
            with path.open("r", encoding="utf-8") as stream:
                while chunk := stream.read(64 * 1024):
                    has_content = has_content or bool(chunk.strip())
        except UnicodeDecodeError:
            raise ArtifactImportError(
                ImportErrorCode.INVALID_ARTIFACT_CONTENT,
                "source Markdown must be valid UTF-8 text",
            ) from None
        if not has_content:
            raise ArtifactImportError(
                ImportErrorCode.INVALID_ARTIFACT_CONTENT,
                "source Markdown must not be empty",
            )

    def _is_registered(self, job_id: str, path: str, digest: str) -> bool:
        registry = self.workspace.read_json(
            job_id, "metadata/artifacts.json", default={"artifacts": []}
        )
        return any(
            item.get("path") == path and item.get("sha256") == digest
            for item in registry.get("artifacts", [])
        )

    @staticmethod
    def _success(
        job_id: str,
        artifact_type: DoclingArtifactType,
        artifact_path: str,
        source_filename: str,
        size: int,
        digest: str,
        already_registered: bool,
    ) -> dict[str, object]:
        return {
            "status": "registered",
            "job_id": job_id,
            "artifact_type": artifact_type.value,
            "artifact_path": artifact_path,
            "source_filename": source_filename,
            "size_bytes": size,
            "sha256": digest,
            "already_registered": already_registered,
        }
