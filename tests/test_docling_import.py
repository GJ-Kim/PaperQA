import json
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

from paper_qa.schemas import DoclingArtifactType
from paper_qa.services.docling_import import (
    ArtifactImportError,
    DoclingArtifactImporter,
    ImportErrorCode,
)
from paper_qa.services.docling_index import create_index
from paper_qa.storage import Workspace


@pytest.fixture
def import_env(tmp_path: Path) -> tuple[Workspace, str, Path, DoclingArtifactImporter]:
    workspace = Workspace(tmp_path / "papers")
    job_id = workspace.create_job()["job_id"]
    cache = tmp_path / "docling-cache"
    cache.mkdir()
    importer = DoclingArtifactImporter(workspace, cache, 1024 * 1024)
    return workspace, job_id, cache, importer


def test_import_json_registers_canonical_artifact_and_is_idempotent(
    import_env: tuple[Workspace, str, Path, DoclingArtifactImporter],
) -> None:
    workspace, job_id, cache, importer = import_env
    source = cache / "opaque.json"
    source.write_text('{"body": {"children": []}}', encoding="utf-8")

    result = importer.import_artifact(job_id, source.name, DoclingArtifactType.DOCLING_JSON)
    assert result["status"] == "registered"
    assert result["artifact_path"] == "extracted/original.docling.json"
    assert result["already_registered"] is False
    assert len(str(result["sha256"])) == 64
    assert workspace.path(job_id, "extracted/original.docling.json").is_file()

    repeated = importer.import_artifact(job_id, source.name, DoclingArtifactType.DOCLING_JSON)
    assert repeated["already_registered"] is True
    assert repeated["sha256"] == result["sha256"]


def test_import_markdown_registers_canonical_artifact(
    import_env: tuple[Workspace, str, Path, DoclingArtifactImporter],
) -> None:
    workspace, job_id, cache, importer = import_env
    source = cache / "opaque.md"
    source.write_text("# Paper\n\nContent", encoding="utf-8")

    result = importer.import_artifact(job_id, source.name, DoclingArtifactType.SOURCE_MARKDOWN)
    assert result["artifact_path"] == "extracted/original.md"
    assert workspace.path(job_id, "extracted/original.md").read_text(
        encoding="utf-8"
    ) == source.read_text(encoding="utf-8")


@pytest.mark.parametrize(
    "filename",
    ["", ".", "..", "../opaque.json", "a/b.json", "a\\b.json", "/etc/passwd", "C:\\x.json"],
)
def test_rejects_non_basename_cache_names(
    import_env: tuple[Workspace, str, Path, DoclingArtifactImporter], filename: str
) -> None:
    _, job_id, _, importer = import_env
    with pytest.raises(ArtifactImportError) as raised:
        importer.import_artifact(job_id, filename, DoclingArtifactType.DOCLING_JSON)
    assert raised.value.code == ImportErrorCode.INVALID_FILENAME


def test_rejects_wrong_extension(
    import_env: tuple[Workspace, str, Path, DoclingArtifactImporter],
) -> None:
    _, job_id, cache, importer = import_env
    (cache / "opaque.md").write_text("content", encoding="utf-8")
    with pytest.raises(ArtifactImportError) as raised:
        importer.import_artifact(job_id, "opaque.md", DoclingArtifactType.DOCLING_JSON)
    assert raised.value.code == ImportErrorCode.INVALID_FILENAME


@pytest.mark.parametrize(
    ("artifact_type", "filename", "content"),
    [
        (DoclingArtifactType.DOCLING_JSON, "broken.json", "not json"),
        (DoclingArtifactType.DOCLING_JSON, "array.json", "[]"),
        (DoclingArtifactType.SOURCE_MARKDOWN, "empty.md", " \n\t"),
    ],
)
def test_rejects_invalid_content(
    import_env: tuple[Workspace, str, Path, DoclingArtifactImporter],
    artifact_type: DoclingArtifactType,
    filename: str,
    content: str,
) -> None:
    _, job_id, cache, importer = import_env
    (cache / filename).write_text(content, encoding="utf-8")
    with pytest.raises(ArtifactImportError) as raised:
        importer.import_artifact(job_id, filename, artifact_type)
    assert raised.value.code == ImportErrorCode.INVALID_ARTIFACT_CONTENT


def test_rejects_file_larger_than_limit(tmp_path: Path) -> None:
    workspace = Workspace(tmp_path / "papers")
    job_id = workspace.create_job()["job_id"]
    cache = tmp_path / "cache"
    cache.mkdir()
    (cache / "large.md").write_text("0123456789", encoding="utf-8")
    importer = DoclingArtifactImporter(workspace, cache, 5)
    with pytest.raises(ArtifactImportError) as raised:
        importer.import_artifact(job_id, "large.md", DoclingArtifactType.SOURCE_MARKDOWN)
    assert raised.value.code == ImportErrorCode.FILE_TOO_LARGE


def test_different_content_does_not_overwrite_existing_artifact(
    import_env: tuple[Workspace, str, Path, DoclingArtifactImporter],
) -> None:
    workspace, job_id, cache, importer = import_env
    source = cache / "opaque.json"
    source.write_text('{"version": 1}', encoding="utf-8")
    importer.import_artifact(job_id, source.name, DoclingArtifactType.DOCLING_JSON)
    canonical = workspace.path(job_id, "extracted/original.docling.json")
    original = canonical.read_bytes()

    source.write_text('{"version": 2}', encoding="utf-8")
    with pytest.raises(ArtifactImportError) as raised:
        importer.import_artifact(job_id, source.name, DoclingArtifactType.DOCLING_JSON)
    assert raised.value.code == ImportErrorCode.ARTIFACT_CONFLICT
    assert canonical.read_bytes() == original


def test_rejects_cache_symlink(
    import_env: tuple[Workspace, str, Path, DoclingArtifactImporter], tmp_path: Path
) -> None:
    _, job_id, cache, importer = import_env
    outside = tmp_path / "outside.json"
    outside.write_text("{}", encoding="utf-8")
    link = cache / "link.json"
    try:
        link.symlink_to(outside)
    except OSError:
        pytest.skip("symbolic links are unavailable in this test environment")
    with pytest.raises(ArtifactImportError) as raised:
        importer.import_artifact(job_id, link.name, DoclingArtifactType.DOCLING_JSON)
    assert raised.value.code == ImportErrorCode.SOURCE_OUTSIDE_CACHE


def test_registration_failure_rolls_back_new_files(
    import_env: tuple[Workspace, str, Path, DoclingArtifactImporter],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace, job_id, cache, importer = import_env
    (cache / "opaque.json").write_text("{}", encoding="utf-8")

    def fail_registration(*args: object, **kwargs: object) -> dict[str, object]:
        raise OSError("simulated failure")

    monkeypatch.setattr(workspace, "register_artifact", fail_registration)
    with pytest.raises(ArtifactImportError) as raised:
        importer.import_artifact(job_id, "opaque.json", DoclingArtifactType.DOCLING_JSON)
    assert raised.value.code == ImportErrorCode.REGISTRATION_FAILED
    assert not workspace.path(job_id, "incoming/original.docling.json", must_exist=False).exists()
    assert not workspace.path(job_id, "extracted/original.docling.json", must_exist=False).exists()


def test_concurrent_same_import_is_safe_and_idempotent(
    import_env: tuple[Workspace, str, Path, DoclingArtifactImporter],
) -> None:
    _, job_id, cache, importer = import_env
    (cache / "opaque.json").write_text("{}", encoding="utf-8")

    def run_import() -> dict[str, object]:
        return importer.import_artifact(job_id, "opaque.json", DoclingArtifactType.DOCLING_JSON)

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(lambda _: run_import(), range(2)))
    assert sorted(bool(item["already_registered"]) for item in results) == [False, True]


def test_imported_realistic_json_can_create_source_index(
    import_env: tuple[Workspace, str, Path, DoclingArtifactImporter],
) -> None:
    workspace, job_id, cache, importer = import_env
    payload = {
        "body": {"children": [{"$ref": "#/texts/0"}]},
        "texts": [
            {
                "self_ref": "#/texts/0",
                "label": "text",
                "text": "Imported source paragraph",
                "prov": [{"page_no": 1}],
            }
        ],
    }
    (cache / "real.json").write_text(json.dumps(payload), encoding="utf-8")
    importer.import_artifact(job_id, "real.json", DoclingArtifactType.DOCLING_JSON)
    index = create_index(job_id, workspace.path(job_id, "extracted/original.docling.json"))
    assert len(index["elements"]) == 1
    assert index["elements"][0]["text"] == "Imported source paragraph"


def test_invalid_or_missing_job_is_reported(
    import_env: tuple[Workspace, str, Path, DoclingArtifactImporter],
) -> None:
    _, _, cache, importer = import_env
    (cache / "opaque.json").write_text("{}", encoding="utf-8")
    with pytest.raises(ArtifactImportError) as raised:
        importer.import_artifact(
            "paper-0000000000000000",
            "opaque.json",
            DoclingArtifactType.DOCLING_JSON,
        )
    assert raised.value.code == ImportErrorCode.INVALID_JOB_ID
