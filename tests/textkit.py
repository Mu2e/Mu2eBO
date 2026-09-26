#!/usr/bin/env python3
"""textkit: a toy MCP server whose tools are registered the two ways
prodtools' servers register theirs, so its replies carry no structured
content, only JSON as text. tests/test_kits.py drives it through the real
KitClient over stdio.

- run_status is declared `-> dict` with `@server.tool(description=...)`,
  like the read server's tools (prodtools_mcp/server.py). A bare `dict`
  gets no output schema, so under mcp 2.x the reply is text only.
- submit_once and echo_text are registered like the write server's tools
  (prodtools_mcp_write/server.py): `server.tool(name=name)` over a
  functools.wraps wrapper of a function with no return annotation.
  echo_text returns its argument verbatim, so a test can send any text.
- structured returns both structured content and a text that is not JSON.

No `from __future__ import annotations` here (see tests/toykit.py).
"""
import functools
from typing import Optional

CREATED_UTC = "2026-09-26T00:00:00+00:00"


def submit_once(json: str, desc: str, dsconf: str, run_as: str):
    return {"name": f"cnf.tester.{desc}.{dsconf}.0", "state": "submitted",
            "json": json, "run_as": run_as}


def echo_text(text: str):
    return text


TOOL_FUNCTIONS = {"submit_once": submit_once, "echo_text": echo_text}


def _forwarding(fn, ToolError):
    """prodtools_mcp_write/server.py's wrapper: any exception becomes a
    ToolError carrying the same text."""
    @functools.wraps(fn)
    def wrapper(*args, **kwargs):
        try:
            return fn(*args, **kwargs)
        except ToolError:
            raise
        except Exception as e:
            raise ToolError(str(e)) from e
    return wrapper


def make_server():
    from mcp.server.mcpserver import MCPServer
    from mcp.server.mcpserver.exceptions import ToolError
    from mcp.types import CallToolResult, TextContent

    server = MCPServer("textkit")

    @server.tool(description="How a run went; declared -> dict, like "
                             "prodtools' read server.")
    def run_status(name: str, mine: bool = False,
                   user: Optional[str] = None) -> dict:
        return {"name": name, "state": "done", "created_utc": CREATED_UTC,
                "user": user}

    for name, fn in TOOL_FUNCTIONS.items():
        server.tool(name=name)(_forwarding(fn, ToolError))

    @server.tool()
    def structured() -> CallToolResult:
        return CallToolResult(
            content=[TextContent(type="text", text="not JSON")],
            structured_content={"from": "structured"})

    return server


def main() -> int:
    make_server().run("stdio")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
