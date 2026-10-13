from __future__ import annotations

import os
import re
from pathlib import Path, PurePosixPath

JOB_ID_RE = re.compile(r"^[a-z0-9][a-z0-9-]{7,63}$")


class PathSecurityError(ValueError):
    pass


def validate_job_id(job_id: str) -> str:
    if not JOB_ID_RE.fullmatch(job_id):
        raise PathSecurityError("Invalid job_id format")
    return job_id


def validate_relative_path(value: str) -> PurePosixPath:
    if not value or "\\" in value or "\x00" in value:
        raise PathSecurityError("Path must be a non-empty POSIX-style relative path")
    path = PurePosixPath(value)
    if path.is_absolute() or any(part in {"", ".", ".."} for part in path.parts):
        raise PathSecurityError("Absolute paths and traversal segments are forbidden")
    if path.parts[0].endswith(":"):
        raise PathSecurityError("Drive-qualified paths are forbidden")
    return path


def ensure_within(root: Path, candidate: Path) -> Path:
    root_real = root.resolve(strict=False)
    candidate_real = candidate.resolve(strict=False)
    try:
        candidate_real.relative_to(root_real)
    except ValueError as exc:
        raise PathSecurityError("Path escapes the configured workspace") from exc
    return candidate_real


def reject_symlink_path(root: Path, candidate: Path) -> None:
    current = root.resolve(strict=False)
    relative = candidate.relative_to(current)
    for part in relative.parts:
        current = current / part
        if current.exists() and current.is_symlink():
            raise PathSecurityError("Symbolic links are forbidden in artifact paths")


def secure_permissions(path: Path) -> None:
    if os.name != "nt":
        path.chmod(0o750 if path.is_dir() else 0o640)
