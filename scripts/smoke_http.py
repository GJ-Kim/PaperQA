from __future__ import annotations

import argparse

import anyio
from fastmcp import Client


async def inspect_server(url: str) -> None:
    async with Client(url) as client:
        tools = await client.list_tools()
        print(f"Connected to {url}; {len(tools)} tools")
        print("\n".join(sorted(tool.name for tool in tools)))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("url", nargs="?", default="http://127.0.0.1:8010/mcp")
    args = parser.parse_args()
    anyio.run(inspect_server, args.url)


if __name__ == "__main__":
    main()
