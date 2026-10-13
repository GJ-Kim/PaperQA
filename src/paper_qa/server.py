from __future__ import annotations

from fastmcp import FastMCP

from .config import Settings
from .storage import Workspace
from .tools.qa_tools import install_tools

settings = Settings.from_env()
workspace = Workspace(settings.root)
mcp = FastMCP("Paper QA MCP")
install_tools(mcp, settings, workspace)


def main() -> None:
    mcp.run(transport=settings.transport, host=settings.host, port=settings.port)


if __name__ == "__main__":
    main()
