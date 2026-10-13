import json
from pathlib import Path

import anyio
from fastmcp import Client, FastMCP

from paper_qa.config import Settings
from paper_qa.storage import Workspace
from paper_qa.tools.qa_tools import install_tools


def test_in_memory_mcp_exposes_and_calls_tools(tmp_path: Path) -> None:
    async def exercise() -> None:
        mcp = FastMCP("test-paper-qa")
        workspace = Workspace(tmp_path)
        install_tools(mcp, Settings(root=tmp_path), workspace)
        async with Client(mcp) as client:
            tools = await client.list_tools()
            names = {tool.name for tool in tools}
            assert {
                "create_job",
                "register_artifact",
                "create_source_index",
                "create_translation_chunks",
                "validate_latex_equations",
                "validate_docx_omml",
                "generate_qa_report",
            } <= names
            result = await client.call_tool("create_job", {"label": "integration"})
            job_id = result.data["job_id"]
            assert job_id.startswith("paper-")

            docling = {
                "body": {
                    "children": [
                        {"$ref": "#/texts/0"},
                        {"$ref": "#/texts/1"},
                    ]
                },
                "texts": [
                    {
                        "self_ref": "#/texts/0",
                        "label": "text",
                        "text": "Source paragraph",
                        "prov": [{"page_no": 1}],
                    },
                    {
                        "self_ref": "#/texts/1",
                        "label": "formula",
                        "text": "x+y",
                        "prov": [{"page_no": 1}],
                    },
                ],
            }
            workspace.write_text(job_id, "incoming/docling.json", json.dumps(docling))
            registered = await client.call_tool(
                "register_artifact",
                {
                    "job_id": job_id,
                    "source_path": "incoming/docling.json",
                    "artifact_type": "docling_json",
                },
            )
            assert registered.data["path"] == "extracted/original.docling.json"

            indexed = await client.call_tool("create_source_index", {"job_id": job_id})
            assert indexed.data["elements"] == 2
            chunked = await client.call_tool(
                "create_translation_chunks", {"job_id": job_id, "max_chars": 1000}
            )
            assert chunked.data["chunks"] == 1

            manifest = workspace.read_json(job_id, "metadata/manifest.json")
            source = workspace.path(job_id, manifest["chunks"][0]["source_path"])
            workspace.write_text(
                job_id,
                manifest["chunks"][0]["translated_path"],
                source.read_text(encoding="utf-8"),
            )
            checked = await client.call_tool(
                "validate_translation_completeness", {"job_id": job_id}
            )
            assert checked.data["status"] == "PASS"
            report = await client.call_tool("generate_qa_report", {"job_id": job_id})
            assert report.data["status"] == "PASS"
            assert workspace.path(job_id, report.data["path"]).is_file()

    anyio.run(exercise)
