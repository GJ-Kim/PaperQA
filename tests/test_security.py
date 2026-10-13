from pathlib import Path

import pytest

from paper_qa.schemas import ArtifactType
from paper_qa.security import PathSecurityError, validate_relative_path
from paper_qa.storage import Workspace


@pytest.mark.parametrize("value", ["../secret", "/etc/passwd", "C:/secret", "a/../../b", "a\\b"])
def test_rejects_unsafe_relative_paths(value: str) -> None:
    with pytest.raises(PathSecurityError):
        validate_relative_path(value)


def test_workspace_creates_isolated_job(tmp_path: Path) -> None:
    workspace = Workspace(tmp_path)
    job = workspace.create_job("fixture")
    assert job["job_id"].startswith("paper-")
    assert workspace.path(job["job_id"], "incoming").is_dir()
    assert workspace.path(job["job_id"], "metadata/job.json").is_file()


def test_register_only_accepts_incoming(tmp_path: Path) -> None:
    workspace = Workspace(tmp_path)
    job_id = workspace.create_job()["job_id"]
    workspace.write_text(job_id, "extracted/not-incoming.md", "x")
    with pytest.raises(PathSecurityError):
        workspace.register_artifact(
            job_id, "extracted/not-incoming.md", ArtifactType.SOURCE_MARKDOWN
        )


def test_register_cannot_overwrite_metadata(tmp_path: Path) -> None:
    workspace = Workspace(tmp_path)
    job_id = workspace.create_job()["job_id"]
    workspace.write_text(job_id, "incoming/source.md", "x")
    with pytest.raises(PathSecurityError):
        workspace.register_artifact(
            job_id,
            "incoming/source.md",
            ArtifactType.SOURCE_MARKDOWN,
            "metadata/job.json",
        )
