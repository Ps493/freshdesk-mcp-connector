"""Minimal MCP (JSON-RPC 2.0 over stdio, newline-delimited) server. No SDK dependency."""
from __future__ import annotations
import json, sys
from .tools import TOOLS, Toolset
from .client import FreshdeskError
from . import __version__


def _text(obj, is_error=False):
    return {"content": [{"type": "text", "text": json.dumps(obj, ensure_ascii=False)}], "isError": is_error}


def handle(ts: Toolset, msg: dict) -> dict | None:
    mid, method, params = msg.get("id"), msg.get("method"), msg.get("params") or {}
    if mid is None:  # notification
        return None
    ok = lambda r: {"jsonrpc": "2.0", "id": mid, "result": r}
    if method == "initialize":
        return ok({"protocolVersion": params.get("protocolVersion", "2024-11-05"), "capabilities": {"tools": {}},
                   "serverInfo": {"name": "freshdesk-readonly-connector", "version": __version__}})
    if method == "ping": return ok({})
    if method == "tools/list": return ok({"tools": TOOLS})
    if method == "tools/call":
        try:
            return ok(_text(ts.call(params.get("name", ""), params.get("arguments") or {})))
        except FreshdeskError as e:  # returned to the model so it can self-correct / back off
            return ok(_text({"error": e.to_dict()}, True))
        except ValueError as e:
            return ok(_text({"error": {"code": "invalid_arguments", "message": str(e)}}, True))
    return {"jsonrpc": "2.0", "id": mid, "error": {"code": -32601, "message": f"Method not found: {method}"}}


def serve(ts: Toolset) -> None:
    for line in sys.stdin:
        if not line.strip(): continue
        try:
            msg = json.loads(line)
        except json.JSONDecodeError:
            print(json.dumps({"jsonrpc": "2.0", "id": None, "error": {"code": -32700, "message": "Parse error"}}), flush=True)
            continue
        resp = handle(ts, msg)
        if resp is not None:
            print(json.dumps(resp), flush=True)
