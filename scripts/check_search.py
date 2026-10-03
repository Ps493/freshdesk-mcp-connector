import sys, os
sys.path.insert(0, os.getcwd())
from fd_connector.__main__ import build
ts = build()
rows = []
for p in (1, 2):
    rows += ts.call("list_tickets", {"per_page": 50, "page": p})["data"]
for tag in ("refund", "shipping"):
    listed = sorted(t["id"] for t in rows if tag in t["tags"])
    found = sorted(t["id"] for t in ts.call("search_tickets", {"tag": tag})["data"])
    print(tag, "| from list:", listed, "| from search:", found)
