"""Start the MCP HTTP transport and verify a real protocol round trip."""

from __future__ import annotations

import asyncio
import socket
import sys

from fastmcp import Client


HOST = "127.0.0.1"
PORT = 8001
ENDPOINT = f"http://{HOST}:{PORT}/mcp"


async def wait_until_listening(process: asyncio.subprocess.Process, attempts: int = 150) -> None:
    for _ in range(attempts):
        if process.returncode is not None:
            raise RuntimeError(f"MCP server exited early with code {process.returncode}")
        try:
            with socket.create_connection((HOST, PORT), timeout=0.1):
                return
        except OSError:
            await asyncio.sleep(0.1)
    raise RuntimeError(f"MCP server did not start at {ENDPOINT}")


async def main() -> None:
    process = await asyncio.create_subprocess_exec(
        sys.executable,
        "-m",
        "hire_agent.mcp_server",
        "--transport",
        "http",
        "--host",
        HOST,
        "--port",
        str(PORT),
        stdout=asyncio.subprocess.DEVNULL,
        stderr=asyncio.subprocess.DEVNULL,
    )
    try:
        await wait_until_listening(process)
        async with Client(ENDPOINT) as client:
            catalog = await client.list_tools()
            created = await client.call_tool(
                "upsert_candidate",
                {
                    "candidate_id": "http-smoke-c1",
                    "display_name": "HTTP Smoke",
                    "skills": ["Python", "MCP"],
                    "years_experience": 3,
                    "location": "Shanghai",
                },
            )
            fetched = await client.call_tool(
                "get_candidate", {"candidate_id": "http-smoke-c1"}
            )
        assert len(catalog) == 13
        assert not created.is_error
        assert not fetched.is_error
        assert fetched.data["display_name"] == "HTTP Smoke"
        print(
            {
                "transport": "streamable-http",
                "endpoint": ENDPOINT,
                "tool_count": len(catalog),
                "round_trip": "ok",
            }
        )
    finally:
        process.terminate()
        await process.wait()


if __name__ == "__main__":
    asyncio.run(main())
