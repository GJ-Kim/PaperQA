# 배포

Paper QA MCP는 LibreChat과 동일한 Compose 프로젝트의 내부 네트워크에서만 노출합니다. `paper-qa-mcp:8010`을 `mcpSettings.allowedAddresses`에 추가하고 `http://paper-qa-mcp:8010/mcp`를 `streamable-http` 서버로 등록합니다.

공유 볼륨은 기존 Docling·Pandoc·Filesystem 서비스와 같은 호스트 디렉터리 `/home/sup3rgj/ai-data`를 컨테이너 `/data`로 마운트합니다. Paper QA 루트는 `/data/papers`입니다.

이미지는 FastMCP 4.1.0, Pandoc 3.12.1, uv 0.12.24 및 Python 3.13.7 베이스로 고정됩니다. 실제 운영에서는 베이스 이미지 태그뿐 아니라 이미지 digest도 배포 승인 시 기록하는 것을 권장합니다.

