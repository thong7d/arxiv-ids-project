"""Persistent client of Google's official Colab MCP, controlled by a local queue.

No secret values or browser connection tokens are printed. Queue files are local
artifacts. The server opens Google's connection UI for user sign-in/consent.
"""

import argparse
import asyncio
import json
import sys
from pathlib import Path

from fastmcp import Client
from fastmcp.client.transports import StdioTransport


async def main(directory: Path):
    directory.mkdir(parents=True, exist_ok=True)
    logdir = directory.resolve() / "logs"
    logdir.mkdir(exist_ok=True)
    transport = StdioTransport(
        command=sys.executable,
        args=[str(Path(__file__).with_name("colab_server.py").resolve()), "--log", str(logdir)],
    )
    async with Client(transport, timeout=180) as client:
        while True:
            for request in sorted(directory.glob("request-*.json")):
                result_path = request.with_name(request.name.replace("request-", "result-"))
                if result_path.exists():
                    continue
                try:
                    task = json.loads(request.read_text(encoding="utf-8-sig"))
                    if task["operation"] == "list":
                        result = [
                            tool.model_dump(mode="json") for tool in await client.list_tools()
                        ]
                    else:
                        response = await client.call_tool(task["name"], task.get("arguments", {}))
                        result = {
                            "is_error": response.is_error,
                            "content": [item.model_dump(mode="json") for item in response.content],
                            "structured_content": response.structured_content,
                        }
                    result_path.write_text(
                        json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
                    )
                    print(f"Completed {request.name}", flush=True)
                except Exception as error:
                    result_path.write_text(
                        json.dumps({"error": type(error).__name__, "detail": str(error)}),
                        encoding="utf-8",
                    )
                    print(f"Failed {request.name}: {type(error).__name__}", flush=True)
            await asyncio.sleep(1)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--queue", type=Path, default=Path("artifacts/colab"))
    asyncio.run(main(parser.parse_args().queue))
