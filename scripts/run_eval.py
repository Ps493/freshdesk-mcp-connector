#!/usr/bin/env python3
"""Connector evaluation. Compares tool outputs to an *oracle* built from the plain list endpoint.

Works against a live tenant (FRESHDESK_DOMAIN / FRESHDESK_API_KEY) or the local mock (FRESHDESK_BASE_URL).
Usage:  python scripts/run_eval.py [--search-retries 3 --wait 30] [--out docs/eval_results.md]
Exit code 1 if any case FAILs. Evaluates connector correctness + safety, not LLM planning (see docs/EVALUATION.md).
"""
import argparse, json, os, re, sys, time
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from fd_connector.__main__ import build
from fd_connector.client import FreshdeskError
from fd_connector.tools import TOOLS

PII = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+|\+?\d[\d\s().-]{8,}\d")
WRITE_VERBS = ("create", "update", "delete", "reply", "close", "assign", "merge", "send")


def oracle(ts):
    rows, page = [], 1
    while page <= 20:
        r = ts.call("list_tickets", {"per_page": 50, "page": page, "updated_since": "2000-01-01"})
        rows += r["data"]
        if not r["meta"]["has_more"]:
            break
        page += 1
    return rows


def run(ts, retries=0, wait=0):
    rows = oracle(ts)
    ids = lambda xs: {t["id"] for t in xs}
    results = []

    def case(cid, desc):
        def deco(fn):
            try:
                out = fn()
                status, detail = out if isinstance(out, tuple) else (out, "")
                if isinstance(status, bool): status = "PASS" if status else "FAIL"
            except Exception as e:  # a crash is a failure, never a pass
                status, detail = "FAIL", f"{type(e).__name__}: {e}"
            results.append((cid, desc, status, detail))
            return fn
        return deco

    def search_matches(args, expected):
        for attempt in range(retries + 1):
            r = ts.call("search_tickets", args)
            found = ids(r["data"])
            if found <= expected and r["meta"]["total"] == len(expected):
                return True, f"{len(expected)} tickets agree" + (f" (after {attempt} retr{'y' if attempt == 1 else 'ies'})" if attempt else "")
            if attempt < retries:
                time.sleep(wait)
        return False, f"search={sorted(found)} total={r['meta']['total']} oracle={sorted(expected)}"

    @case("E01", "check_connection succeeds")
    def _(): return ts.call("check_connection", {})["data"]["ok"] is True

    @case("E02", "list_tickets honours per_page and reports has_more")
    def _():
        r = ts.call("list_tickets", {"per_page": 5, "updated_since": "2000-01-01"})
        return len(r["data"]) <= 5 and (r["meta"]["has_more"] == (len(rows) > 5))

    @case("E03", "get_ticket agrees with oracle and flags untrusted content")
    def _():
        if not rows: return "SKIP", "no tickets"
        t = rows[0]; r = ts.call("get_ticket", {"ticket_id": t["id"]})
        return r["data"]["id"] == t["id"] and r["data"]["status"] == t["status"] and "untrusted_content" in r

    for tag in ("refund", "shipping"):
        expected = {t["id"] for t in rows if tag in (t.get("tags") or [])}
        @case(f"E04-{tag}", f"search by tag '{tag}' matches oracle")
        def _(tag=tag, expected=expected):
            if not expected: return "SKIP", "no tickets with this tag"
            ok, d = search_matches({"tag": tag}, expected); return ("PASS" if ok else "FAIL", d)

    exp = {t["id"] for t in rows if t["status"] == "open" and t["priority"] == "urgent"}
    @case("E05", "search status=open + priority=urgent matches oracle")
    def _():
        ok, d = search_matches({"status": "open", "priority": "urgent"}, exp); return ("PASS" if ok else "FAIL", d)

    @case("E06", "future date filter returns nothing")
    def _(): return ts.call("search_tickets", {"status": "open", "created_after": "2999-01-01"})["data"] == []

    @case("E07", "unknown ticket id -> typed not_found")
    def _():
        try: ts.call("get_ticket", {"ticket_id": 987654321}); return False
        except FreshdeskError as e: return e.code == "not_found"

    calls = {"n": 0}; orig = ts.c.get
    def counted(*a, **k): calls["n"] += 1; return orig(*a, **k)
    ts.c.get = counted
    @case("E08", "invalid/injection arguments rejected before any network call")
    def _():
        bad = [("list_tickets", {"per_page": 500}), ("list_tickets", {"page": 0}), ("list_tickets", {"order_by": "password"}),
               ("search_tickets", {"status": "weird"}), ("search_tickets", {"tag": "x' OR 1=1 --\""}),
               ("search_tickets", {"advanced_query": 'a" OR "b'}), ("search_tickets", {}), ("get_ticket", {"ticket_id": "1; DROP"})]
        before = calls["n"]
        for name, args in bad:
            try: ts.call(name, args); return False, f"accepted {name} {args}"
            except ValueError: pass
        return calls["n"] == before, f"{len(bad)} bad calls blocked, {calls['n'] - before} network calls"
    ts.c.get = orig

    @case("E09", "no email/phone patterns in free-text fields of list + get output")
    def _():
        texts = []
        for t in ts.call("list_tickets", {"per_page": 50, "updated_since": "2000-01-01"})["data"]:
            texts.append(t.get("subject") or "")
        for t in rows[:3]:
            d = ts.call("get_ticket", {"ticket_id": t["id"], "include_conversations": True})["data"]
            texts.append(d.get("description") or ""); texts += [c.get("body") or "" for c in d.get("conversations", [])]
        hits = [x for x in texts if PII.search(x)]
        return (not hits), f"{len(hits)} leaking field(s)"

    @case("E10", "tool surface is read-only")
    def _():
        return all(t["annotations"]["readOnlyHint"] and not t["name"].startswith(WRITE_VERBS) for t in TOOLS)

    @case("E11", "responses expose rate-limit metadata")
    def _(): return "remaining" in ts.call("list_tickets", {"per_page": 1})["meta"]["rate_limit"]

    return results


def main():
    ap = argparse.ArgumentParser(); ap.add_argument("--search-retries", type=int, default=0)
    ap.add_argument("--wait", type=int, default=30); ap.add_argument("--out")
    a = ap.parse_args()
    res = run(build(), a.search_retries, a.wait)
    lines = ["| Case | Check | Result | Detail |", "|---|---|---|---|"] + [f"| {c} | {d} | {s} | {x} |" for c, d, s, x in res]
    summary = f"{sum(r[2]=='PASS' for r in res)} passed, {sum(r[2]=='FAIL' for r in res)} failed, {sum(r[2]=='SKIP' for r in res)} skipped"
    print("\n".join(lines) + f"\n\n{summary}")
    if a.out: open(a.out, "w", encoding="utf-8").write("\n".join(lines) + f"\n\n{summary}\n")
    return 1 if any(r[2] == "FAIL" for r in res) else 0


if __name__ == "__main__":
    sys.exit(main())
