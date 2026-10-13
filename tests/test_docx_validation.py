import zipfile
from pathlib import Path

from paper_qa.schemas import Status
from paper_qa.services.docx_validation import inspect_docx

DOCUMENT_XML = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"
 xmlns:m="http://schemas.openxmlformats.org/officeDocument/2006/math">
 <w:body><w:p><w:bookmarkStart w:id="1" w:name="qa-eq0001"/>
 <m:oMathPara><m:oMath><m:r><m:t>x+y</m:t></m:r></m:oMath></m:oMathPara>
 <w:bookmarkEnd w:id="1"/></w:p></w:body>
</w:document>"""


def make_docx(path: Path, document_xml: str = DOCUMENT_XML) -> None:
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr(
            "[Content_Types].xml",
            '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"/>',
        )
        archive.writestr("word/document.xml", document_xml)


def test_detects_omml_and_equation_bookmark(tmp_path: Path) -> None:
    path = tmp_path / "math.docx"
    make_docx(path)
    status, counts, issues, inventory = inspect_docx(path, [{"id": "eq0001"}])
    assert status == Status.PASS
    assert counts["omath"] == 1
    assert inventory["matched_equation_ids"] == ["eq0001"]
    assert not issues


def test_rejects_broken_docx(tmp_path: Path) -> None:
    path = tmp_path / "broken.docx"
    path.write_bytes(b"not a zip")
    status, _, issues, _ = inspect_docx(path, [{"id": "eq0001"}])
    assert status == Status.FAIL
    assert issues[0].code == "DOCX_ARCHIVE_INVALID"
