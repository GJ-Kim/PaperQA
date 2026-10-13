from __future__ import annotations

from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, Field


class Status(StrEnum):
    PASS = "PASS"
    WARN = "WARN"
    FAIL = "FAIL"
    NOT_CHECKED = "NOT_CHECKED"


class Severity(StrEnum):
    ERROR = "error"
    WARNING = "warning"
    INFO = "info"


class ArtifactType(StrEnum):
    ORIGINAL_PDF = "original_pdf"
    DOCLING_JSON = "docling_json"
    SOURCE_MARKDOWN = "source_markdown"
    TRANSLATED_MARKDOWN = "translated_markdown"
    DOCX = "docx"
    IMAGE = "image"
    OTHER = "other"


class DoclingArtifactType(StrEnum):
    DOCLING_JSON = "docling_json"
    SOURCE_MARKDOWN = "source_markdown"


class Issue(BaseModel):
    severity: Severity
    code: str
    message: str
    element_id: str | None = None
    chunk_id: str | None = None
    page: int | None = None
    path: str | None = None
    details: dict[str, Any] = Field(default_factory=dict)


class ValidationResult(BaseModel):
    job_id: str
    run_id: str
    check: str
    status: Status
    counts: dict[str, int] = Field(default_factory=dict)
    issues: list[Issue] = Field(default_factory=list)
    report_path: str
    created_at: str
    metadata: dict[str, Any] = Field(default_factory=dict)


class ToolSummary(BaseModel):
    job_id: str
    check: str
    status: Status
    counts: dict[str, int] = Field(default_factory=dict)
    issues: list[Issue] = Field(default_factory=list)
    total_issues: int = 0
    report_path: str


LatexMode = Literal["strict", "normalized"]
