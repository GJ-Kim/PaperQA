from __future__ import annotations

from typing import Any

from ..storage import Workspace, sha256_file, utc_now

STATUS_ORDER = {"FAIL": 3, "WARN": 2, "NOT_CHECKED": 1, "PASS": 0}


def generate_report(workspace: Workspace, job_id: str) -> dict[str, Any]:
    results = workspace.read_json(job_id, "qa/results.json", default={"checks": {}})
    checks = results.get("checks", {})
    overall = max(
        (item.get("status", "NOT_CHECKED") for item in checks.values()),
        key=lambda value: STATUS_ORDER.get(value, 1),
        default="NOT_CHECKED",
    )
    workspace.read_json(job_id, "metadata/job.json")
    artifacts = workspace.read_json(job_id, "metadata/artifacts.json", default={"artifacts": []})
    lines = [
        "# Paper QA 보고서",
        "",
        f"- 작업 ID: `{job_id}`",
        f"- 생성 시각(UTC): `{utc_now()}`",
        f"- 종합 상태: **{overall}**",
        "- 한계: 자동 검사는 번역의 의미 정확성을 완전히 증명하지 않습니다.",
        "",
        "## 입력 및 산출물",
        "",
        "| 유형 | 경로 | SHA-256 |",
        "|---|---|---|",
    ]
    for artifact in artifacts.get("artifacts", []):
        lines.append(
            f"| {artifact['artifact_type']} | `{artifact['path']}` | `{artifact['sha256']}` |"
        )
    lines.extend(
        ["", "## 검사 결과", "", "| 검사 | 상태 | 이슈 수 | 결과 파일 |", "|---|---:|---:|---|"]
    )
    for name, check in sorted(checks.items()):
        issue_count = len(check.get("issues", []))
        report_path = check["report_path"]
        lines.append(f"| {name} | **{check['status']}** | {issue_count} | `{report_path}` |")
    lines.extend(["", "## 주요 이슈", ""])
    any_issue = False
    for name, check in sorted(checks.items()):
        for issue in check.get("issues", []):
            any_issue = True
            location = issue.get("element_id") or issue.get("chunk_id") or issue.get("path") or "-"
            heading = f"{issue['severity'].upper()} / {issue['code']}"
            lines.append(f"- **{heading}** ({name}, `{location}`): {issue['message']}")
    if not any_issue:
        lines.append("- 보고된 이슈 없음")
    lines.extend(
        [
            "",
            "## 수동 확인 권고",
            "",
            "- 의미 보존, 전문용어 선택, 원본 PDF의 추출 오류는 사람이 최종 확인해야 합니다.",
            "- 수식 북마크가 보존되지 않은 경우 OMML 개수는 수학적 내용 동치를 뜻하지 않습니다.",
            "",
        ]
    )
    relative = "output/translation_qa_report.md"
    path = workspace.write_text(job_id, relative, "\n".join(lines))
    return {
        "job_id": job_id,
        "status": overall,
        "path": relative,
        "sha256": sha256_file(path),
        "checks": len(checks),
    }
