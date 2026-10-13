# Agent v2.1 — Docling 캐시 반입 추가 지시

기존 `PAPER QA JOB AND PATH CONTRACT`의 incoming 규칙 뒤에 다음 내용을 추가합니다.

```text
### Preferred Docling artifact import workflow

When Paper QA MCP provides `import_docling_artifact`:
1. Call Docling `save_docling_document`.
2. Read the returned `md_file` and `json_file` paths.
3. Confirm that the files are located under the configured shared Docling cache.
4. Extract ONLY the basename of each returned path.
5. Call `import_docling_artifact(job_id, filename, artifact_type)` for each file.
6. Use `docling_json` for JSON and `source_markdown` for Markdown.
7. Verify `status=registered` and the returned canonical artifact paths.
8. Do not additionally call Filesystem `copy_file` or Paper QA
   `register_artifact` after a successful import.
9. Do not pass an absolute path or the document content to
   `import_docling_artifact`.
10. After successful JSON registration, call `create_source_index`.
11. If the import tool is unavailable, fall back to the verified Filesystem
    copy plus job-relative `register_artifact` workflow.
12. If import fails, report its error code. Never fabricate Docling JSON or
    attempt arbitrary cache access.
```

예를 들어 Docling이 다음 경로를 반환했다면:

```text
/data/docling-mcp/cache/a6220a6b74b3267d26a2a56440492412.json
```

Paper QA에는 다음 값만 전달합니다.

```text
filename: a6220a6b74b3267d26a2a56440492412.json
artifact_type: docling_json
```
