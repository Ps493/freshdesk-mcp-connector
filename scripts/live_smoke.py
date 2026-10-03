import json, sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))  # repo root
from fd_connector.__main__ import build

ts = build()

def show(name, args):
    print(f"\n=== {name} {args}")
    try:
        r = ts.call(name, args)
        d = r["data"]
        if isinstance(d, list):
            for t in d:
                print(" ", t.get("id"), t.get("status"), t.get("priority"), t.get("subject") or t.get("body"))
        else:
            print(json.dumps(d, indent=2)[:900])
        print("meta:", {k: v for k, v in r["meta"].items() if k != "query_sent"})
    except Exception as e:
        print("FAILED:", type(e).__name__, e)

show("check_connection", {})
show("list_tickets", {"per_page": 5})
first = ts.call("list_tickets", {"per_page": 1})["data"][0]["id"]
show("get_ticket", {"ticket_id": first, "include_conversations": True})
show("search_tickets", {"tag": "refund"})
show("search_tickets", {"status": "open", "priority": "urgent"})
show("search_tickets", {"created_after": "2026-01-01", "tag": "shipping"})
