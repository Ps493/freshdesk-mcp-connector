import json, os, sys
from .client import FreshdeskClient, FreshdeskError
from .tools import TOOLS, Toolset
from .mcp_server import serve


def build() -> Toolset:
    c = FreshdeskClient(os.environ.get("FRESHDESK_DOMAIN", ""), os.environ.get("FRESHDESK_API_KEY", ""),
                        base_url=os.environ.get("FRESHDESK_BASE_URL"),
                        calls_per_minute=int(os.environ.get("FRESHDESK_CALLS_PER_MINUTE", "40")),
                        burst=int(os.environ.get("FRESHDESK_BURST", "10")))
    return Toolset(c, redact=os.environ.get("FRESHDESK_REDACT_PII", "1") != "0")


def main() -> int:
    cmd = sys.argv[1] if len(sys.argv) > 1 else "serve"
    if cmd == "spec":
        print(json.dumps({"tools": TOOLS}, indent=2)); return 0
    try:
        ts = build()
        if cmd == "verify":
            print(json.dumps(ts.call("check_connection", {}), indent=2)); return 0
        serve(ts); return 0
    except (ValueError, FreshdeskError) as e:
        print(f"error: {e}", file=sys.stderr); return 2


if __name__ == "__main__":
    sys.exit(main())
