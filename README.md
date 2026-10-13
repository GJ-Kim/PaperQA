# Paper QA MCP

영문 학술논문의 Docling 추출물, 한국어 번역 Markdown, Pandoc DOCX를 파일 기반으로 검사하는 독립 MCP 서버입니다. 번역 자체나 PDF OCR은 수행하지 않습니다.

## 제공 도구

- `create_job`, `register_artifact`: 격리된 작업 생성과 안전한 파일 등록
- `create_source_index`: Docling JSON 요소와 수식/구조 인벤토리 생성
- `create_translation_chunks`, `create_chunk_manifest`: 요소 마커가 포함된 청크 및 Manifest 생성/검증
- `validate_translation_completeness`: 청크·요소 누락, 중복, 빈 번역, 의심 축약 검사
- `merge_translated_chunks`: Manifest 순서대로 번역 Markdown 병합
- `validate_latex_equations`: Pandoc AST 기반 strict/normalized 수식 비교
- `validate_document_structure`: 제목·표·그림 및 이미지 경로 검사
- `validate_docx_omml`: DOCX 무결성, OMML, 그림, 수식 북마크 검사
- `generate_qa_report`, `get_validation_summary`: 누적 보고서 및 작은 응답

## 로컬 개발

Python 3.11~3.14와 `uv`가 필요합니다. 수식/구조 통합 검사에는 Pandoc 3.12.1이 필요하지만 나머지 단위 시험은 Pandoc 없이 실행됩니다.

```powershell
uv sync
uv run pytest
$env:PAPER_QA_ROOT = "$PWD/paper-workspace"
uv run paper-qa-mcp
```

Streamable HTTP 엔드포인트는 기본적으로 `http://localhost:8010/mcp`입니다.

## Docker 및 LibreChat 연결

운영 서버의 LibreChat Compose 디렉터리에서 이 저장소를 `mcp/paper-qa-mcp`로 배치한다고 가정합니다.

```bash
docker compose -f docker-compose.yml -f docker-compose.override.yml \
  -f mcp/paper-qa-mcp/compose.paper-qa.yml up -d --build paper-qa-mcp api
```

기존 `librechat.yaml`에는 [deploy/librechat.paper-qa.snippet.yaml](deploy/librechat.paper-qa.snippet.yaml)의 주소와 서버 항목을 병합합니다. 첨부 구성과 동일하게 호스트 `/home/sup3rgj/ai-data`가 컨테이너의 `/data`에 마운트되며, QA 작업은 `/data/papers/<job_id>` 아래에 생성됩니다. 외부 포트는 공개하지 않습니다.

## 안전한 파일 반입 흐름

1. `create_job`을 호출해 서버 생성 `job_id`를 받습니다.
2. 외부 오케스트레이터가 공유 볼륨의 `<job_id>/incoming/`에 파일을 복사합니다.
3. `register_artifact(job_id, "incoming/file.pdf", "original_pdf")`처럼 등록합니다.
4. 등록 도구가 파일을 표준 위치에 원자적으로 복사하고 SHA-256을 기록합니다.

모든 MCP 경로는 작업 디렉터리 기준 POSIX 상대경로만 허용합니다. `..`, 절대경로, Windows 드라이브 경로, 심볼릭 링크 경로는 거부합니다.

## 권장 실행 순서

1. `create_job`
2. 입력 파일 배치 및 `register_artifact`
3. `create_source_index`
4. `create_translation_chunks`
5. Agent가 `chunks/source`를 번역하여 대응하는 `chunks/translated/*_ko.md` 작성
6. `validate_translation_completeness`
7. `merge_translated_chunks`
8. `validate_latex_equations`, `validate_document_structure`
9. Pandoc MCP로 DOCX 생성
10. `register_artifact(..., "docx")`, `validate_docx_omml`
11. `generate_qa_report`

수식 청크는 `qa-eq####` 식별자가 있는 fenced div로 생성됩니다. Pandoc이 이를 DOCX 북마크로 보존하면 수식별 추적에 사용하고, 보존하지 않으면 OMML 개수 및 순서 기반 검사로 후퇴하여 `WARN`을 기록합니다.

## 알려진 한계

- Docling JSON 구조가 fixture와 다르면 일부 요소가 일반 문단으로 분류될 수 있습니다.
- OMML 존재는 수학적 내용의 동치를 증명하지 않습니다.
- Markdown 문자 길이 비율은 요약 의심 경고일 뿐 합격/실패의 단독 근거가 아닙니다.
- 참고문헌, 복잡한 병합 표, 이미지 내부 텍스트 및 번역 의미 정확성은 수동 확인이 필요합니다.

