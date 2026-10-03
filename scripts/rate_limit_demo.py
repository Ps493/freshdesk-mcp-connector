import sys, os, time
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from fd_connector.__main__ import build

ts = build()
start = time.time()
for i in range(1, 71):
    r = ts.call("list_tickets", {"per_page": 1})
    rl = r["meta"]["rate_limit"]
    print(f"call {i:2d} | t={time.time()-start:5.1f}s | remaining={rl.get('remaining')}", flush=True)
print("done: 70 calls on a 50/min plan, no crash")
