# 배포

Paper QA MCP는 LibreChat과 동일한 Compose 프로젝트의 내부 네트워크에서만 노출합니다. `paper-qa-mcp:8010`을 `mcpSettings.allowedAddresses`에 추가하고 `http://paper-qa-mcp:8010/mcp`를 `streamable-http` 서버로 등록합니다.

Paper QA에는 필요한 경로만 분리해서 마운트합니다.

```yaml
volumes:
  - /home/sup3rgj/ai-data/papers:/data/papers
  - /home/sup3rgj/ai-data/docling-mcp/cache:/data/docling-mcp/cache:ro
environment:
  PAPER_QA_ROOT: /data/papers
  DOCLING_CACHE_ROOT: /data/docling-mcp/cache
  PAPER_QA_IMPORT_MAX_BYTES: "104857600"
```

Docling의 실제 캐시 호스트 경로가 다르면 source만 조정하되, 컨테이너 내부
경로와 `DOCLING_CACHE_ROOT`는 일치시켜야 합니다. 캐시 마운트는 읽기 전용으로
유지합니다. Paper QA 컨테이너의 UID `10001`이 캐시 디렉터리와 파일을 읽을 수
있도록 호스트 권한 또는 ACL을 설정해야 합니다.

이미지는 FastMCP 4.1.0, Pandoc 3.12.1, uv 0.12.24 및 Python 3.13.7 베이스로 고정됩니다. 실제 운영에서는 베이스 이미지 태그뿐 아니라 이미지 digest도 배포 승인 시 기록하는 것을 권장합니다.

