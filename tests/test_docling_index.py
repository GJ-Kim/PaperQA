import json
from pathlib import Path

from paper_qa.services.docling_index import create_index


def test_docling_reference_order_and_types(tmp_path: Path) -> None:
    payload = {
        "body": {"children": [{"$ref": "#/texts/0"}, {"$ref": "#/texts/1"}]},
        "texts": [
            {
                "self_ref": "#/texts/0",
                "label": "section_header",
                "text": "Introduction",
                "prov": [{"page_no": 1}],
            },
            {
                "self_ref": "#/texts/1",
                "label": "formula",
                "text": "x^2+y^2",
                "prov": [{"page_no": 2}],
            },
        ],
    }
    source = tmp_path / "docling.json"
    source.write_text(json.dumps(payload), encoding="utf-8")
    index = create_index("paper-12345678", source)
    assert [item["id"] for item in index["elements"]] == ["h0001", "eq0001"]
    assert index["elements"][1]["page"] == 2
    assert index["elements"][1]["latex"] == "x^2+y^2"
