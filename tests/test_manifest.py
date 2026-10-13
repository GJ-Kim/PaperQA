from pathlib import Path

from paper_qa.schemas import Status
from paper_qa.services.manifest import create_chunks, validate_completeness
from paper_qa.storage import Workspace


def _index(job_id: str) -> dict:
    return {
        "job_id": job_id,
        "elements": [
            {"id": "p0001", "type": "paragraph", "text": "A long source paragraph.", "order": 1},
            {"id": "eq0001", "type": "equation", "text": "x+y", "latex": "x+y", "order": 2},
        ],
    }


def test_chunks_include_equation_bookmark_markup(tmp_path: Path) -> None:
    workspace = Workspace(tmp_path)
    job_id = workspace.create_job()["job_id"]
    manifest = create_chunks(workspace, job_id, _index(job_id), 1000)
    content = workspace.path(job_id, manifest["chunks"][0]["source_path"]).read_text(
        encoding="utf-8"
    )
    assert "<!-- QA:ELEMENT:eq0001 -->" in content
    assert "{#qa-eq0001}" in content


def test_completeness_detects_missing_marker(tmp_path: Path) -> None:
    workspace = Workspace(tmp_path)
    job_id = workspace.create_job()["job_id"]
    manifest = create_chunks(workspace, job_id, _index(job_id), 1000)
    target = manifest["chunks"][0]["translated_path"]
    workspace.write_text(job_id, target, "<!-- QA:ELEMENT:p0001 -->\n번역")
    status, _, issues = validate_completeness(workspace, job_id, manifest)
    assert status == Status.FAIL
    assert "TRANSLATED_ELEMENT_MISSING" in {issue.code for issue in issues}
