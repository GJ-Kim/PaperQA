from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Settings:
    root: Path
    host: str = "0.0.0.0"
    port: int = 8010
    transport: str = "http"
    max_issues: int = 50
    pandoc_binary: str = "pandoc"

    @classmethod
    def from_env(cls) -> Settings:
        return cls(
            root=Path(os.getenv("PAPER_QA_ROOT", "/workspace/papers")),
            host=os.getenv("PAPER_QA_HOST", "0.0.0.0"),
            port=int(os.getenv("PAPER_QA_PORT", "8010")),
            transport=os.getenv("PAPER_QA_TRANSPORT", "http"),
            max_issues=int(os.getenv("PAPER_QA_MAX_ISSUES", "50")),
            pandoc_binary=os.getenv("PAPER_QA_PANDOC", "pandoc"),
        )
