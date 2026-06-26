#!/usr/bin/env python3
"""
MCP server for obsidian-vault-sync.

Exposes sync_vault as a tool you can call from inside Claude chat
without leaving the terminal or waiting for cron.

Setup (add to ~/.claude/claude_desktop_config.json):
    {
      "mcpServers": {
        "obsidian-vault-sync": {
          "command": "python3",
          "args": ["/path/to/obsidian-vault-sync/mcp_server.py"]
        }
      }
    }

Then in Claude: "sync my vault" or just call the sync_vault tool.
"""
import json
import sys
import subprocess
from pathlib import Path

SYNC_SCRIPT = Path(__file__).parent / "sync.py"

TOOLS = [
    {
        "name": "sync_vault",
        "description": (
            "Sync Claude (and optionally Copilot) conversations to the Obsidian vault. "
            "Runs incrementally — only new or changed sessions are processed."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "force": {
                    "type": "boolean",
                    "description": "Force a full rebuild of all notes (slow). Defaults to false."
                }
            },
            "required": []
        }
    }
]


def handle(req):
    method = req.get("method", "")
    rid    = req.get("id")

    if method == "initialize":
        return {
            "jsonrpc": "2.0", "id": rid,
            "result": {
                "protocolVersion": "2024-11-05",
                "capabilities": {"tools": {}},
                "serverInfo": {"name": "obsidian-vault-sync", "version": "1.1.0"}
            }
        }

    if method == "tools/list":
        return {"jsonrpc": "2.0", "id": rid, "result": {"tools": TOOLS}}

    if method == "tools/call":
        name   = req.get("params", {}).get("name", "")
        inputs = req.get("params", {}).get("arguments", {})

        if name == "sync_vault":
            cmd = [sys.executable, str(SYNC_SCRIPT)]

            # force rebuild: bump FORMAT env var trick — simplest way without
            # modifying sync.py at runtime is to just tell the user after
            force = inputs.get("force", False)
            if force:
                note = "(force flag noted — to rebuild all notes, bump FORMAT in sync.py)\n"
            else:
                note = ""

            result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
            output = (result.stdout or "") + (result.stderr or "")
            text   = note + (output.strip() or "Sync complete.")
            ok     = result.returncode == 0

            return {
                "jsonrpc": "2.0", "id": rid,
                "result": {
                    "content": [{"type": "text", "text": text}],
                    "isError": not ok
                }
            }

        return {
            "jsonrpc": "2.0", "id": rid,
            "error": {"code": -32601, "message": f"Unknown tool: {name}"}
        }

    # notifications (no id) and unknown methods — no response needed
    if rid is None:
        return None

    return {"jsonrpc": "2.0", "id": rid, "result": {}}


def main():
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            req  = json.loads(line)
            resp = handle(req)
            if resp is not None:
                print(json.dumps(resp), flush=True)
        except Exception as e:
            err = {"jsonrpc": "2.0", "id": None,
                   "error": {"code": -32700, "message": str(e)}}
            print(json.dumps(err), flush=True)


if __name__ == "__main__":
    main()
