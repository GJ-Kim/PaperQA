# MCP API 요약

파일을 받는 모든 도구는 `job_id`와 작업 내부 상대경로만 받습니다. 응답에는 본문 대신 상태, 개수, 상위 이슈, 결과 파일 경로가 들어갑니다.

검증 상태는 `PASS`, `WARN`, `FAIL`, `NOT_CHECKED`입니다. 각 실행은 `qa/runs/<run_id>-<check>.json`에 보존되고, `qa/results.json`에는 검사별 최신 결과가 저장됩니다.

`register_artifact`의 `source_path`는 반드시 `incoming/`으로 시작해야 합니다. 표준 목적지는 아티팩트 유형에 따라 자동 결정되며 필요한 경우에만 `destination_path`를 지정합니다.

