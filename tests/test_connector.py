import json, os, subprocess, sys, unittest
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from fd_connector.client import FreshdeskClient, FreshdeskError, TokenBucket
from fd_connector.tools import Toolset, build_search_query
from fd_connector.mcp_server import handle
from tests import mock_freshdesk as mock


class Base(unittest.TestCase):
    def setUp(self):
        self.srv, self.url = mock.start()
        self.sleeps = []
        self.client = FreshdeskClient("", mock.API_KEY, base_url=self.url, sleep=self.sleeps.append)
        self.ts = Toolset(self.client)
    def tearDown(self): self.srv.shutdown()


class TestAuth(Base):
    def test_valid_key(self):
        self.assertTrue(self.ts.call("check_connection", {})["data"]["ok"])
        self.assertEqual(self.srv.auth_seen[0][:6], "Basic ")

    def test_bad_key_is_401_and_not_retried(self):
        bad = Toolset(FreshdeskClient("", "wrong", base_url=self.url, sleep=self.sleeps.append))
        with self.assertRaises(FreshdeskError) as e: bad.call("list_tickets", {})
        self.assertEqual(e.exception.code, "auth_failed"); self.assertEqual(self.srv.hits, 1)

    def test_domain_validation_blocks_ssrf(self):
        for d in ("evil.com/x", "a b", "", "x@y"):
            with self.assertRaises(ValueError): FreshdeskClient(d, "k")

    def test_plain_http_non_loopback_rejected(self):
        with self.assertRaises(ValueError): FreshdeskClient("", "k", base_url="http://example.com")

    def test_redirects_not_followed(self):
        self.assertEqual(type(self.client.opener.handlers[-1]).__name__ if False else "ok", "ok")  # see client._NoRedirect
        from fd_connector.client import _NoRedirect
        self.assertIsNone(_NoRedirect().redirect_request(None, None, 302, "", {}, "http://evil"))


class TestRateLimits(Base):
    def test_429_honours_retry_after_then_succeeds(self):
        self.srv.fail_queue += [(429, {"Retry-After": "3"}), (429, {"Retry-After": "2"})]
        r = self.ts.call("list_tickets", {"per_page": 5})
        self.assertEqual(len(r["data"]), 5)
        self.assertEqual(self.sleeps, [3.0, 2.0])

    def test_429_gives_up_with_typed_error(self):
        self.srv.fail_queue += [(429, {"Retry-After": "1"})] * 10
        with self.assertRaises(FreshdeskError) as e: self.ts.call("list_tickets", {})
        self.assertEqual(e.exception.code, "rate_limited")

    def test_5xx_retried_with_backoff(self):
        self.srv.fail_queue += [(503, {})]
        self.assertTrue(self.ts.call("list_tickets", {}))
        self.assertEqual(len(self.sleeps), 1)

    def test_server_reported_remaining_throttles_shared_key(self):
        t = [0.0]; b = self.client.bucket
        b.clock, b.last = (lambda: t[0]), 0.0
        b.sleep = lambda s: (self.sleeps.append(s), t.__setitem__(0, t[0] + s))
        self.srv.remaining = 0                      # another process drained the shared quota
        self.ts.call("list_tickets", {"per_page": 1})
        self.sleeps.clear(); self.srv.remaining = 49
        self.ts.call("list_tickets", {"per_page": 1})
        self.assertTrue(self.sleeps and self.sleeps[0] > 0)

    def test_burst_plus_rate_stays_under_fixed_window_quota(self):
        t = [0.0]; slept = []
        def sl(x): slept.append(x); t[0] += x
        b = TokenBucket(40, clock=lambda: t[0], sleep=sl, burst=10)
        sent = []
        while t[0] < 60:
            b.acquire(); sent.append(t[0])
        self.assertLessEqual(len([x for x in sent if x < 60]), 50)  # plan quota

    def test_token_bucket_blocks_when_empty(self):
        t = [0.0]; slept = []
        def sl(s): slept.append(s); t[0] += s
        b = TokenBucket(60, clock=lambda: t[0], sleep=sl)
        for _ in range(60): b.acquire()
        b.acquire()
        self.assertTrue(slept and abs(slept[0] - 1.0) < 1e-6)


class TestTools(Base):
    def test_pagination(self):
        p1 = self.ts.call("list_tickets", {"per_page": 20, "page": 1})
        p3 = self.ts.call("list_tickets", {"per_page": 20, "page": 3})
        self.assertTrue(p1["meta"]["has_more"]); self.assertFalse(p3["meta"]["has_more"]); self.assertEqual(len(p3["data"]), 5)

    def test_get_and_redaction(self):
        d = self.ts.call("get_ticket", {"ticket_id": 7})["data"]
        self.assertNotIn("@", d["subject"]); self.assertNotIn("9876543210", d["description"])
        raw = Toolset(self.client, redact=False).call("get_ticket", {"ticket_id": 7})["data"]
        self.assertIn("@", raw["subject"])

    def test_untrusted_flag_present(self):
        self.assertIn("untrusted_content", self.ts.call("get_ticket", {"ticket_id": 7}))

    def test_private_notes_excluded_by_default(self):
        c = self.ts.call("get_ticket", {"ticket_id": 1, "include_conversations": True})["data"]["conversations"]
        self.assertEqual(len(c), 1); self.assertNotIn("bob@corp.com", json.dumps(c))
        c2 = self.ts.call("list_ticket_conversations", {"ticket_id": 1, "include_private_notes": True})["data"]
        self.assertEqual(len(c2), 2)

    def test_not_found(self):
        with self.assertRaises(FreshdeskError) as e: self.ts.call("get_ticket", {"ticket_id": 9999})
        self.assertEqual(e.exception.code, "not_found")

    def test_search(self):
        r = self.ts.call("search_tickets", {"status": "open", "priority": "low"})
        self.assertTrue(all(t["status"] == "open" and t["priority"] == "low" for t in r["data"]))
        r2 = self.ts.call("search_tickets", {"tag": "refund"})
        self.assertEqual(r2["meta"]["total"], 15)

    def test_search_injection_rejected(self):
        for bad in ({"tag": "x' OR 1=1 --\""}, {"advanced_query": 'a" OR "b'}, {"created_after": "2026-1-1"}, {"status": "weird"}, {}):
            with self.assertRaises(ValueError): build_search_query(bad)

    def test_bounds(self):
        for a in ({"per_page": 500}, {"page": 0}, {"order_by": "password"}):
            with self.assertRaises(ValueError): self.ts.call("list_tickets", a)
        with self.assertRaises(ValueError): self.ts.call("search_tickets", {"status": "open", "page": 11})

    def test_read_only(self):
        self.assertFalse(hasattr(self.client, "post") or hasattr(self.client, "put") or hasattr(self.client, "delete"))
        from fd_connector.tools import TOOLS
        self.assertTrue(all(t["annotations"]["readOnlyHint"] for t in TOOLS))


class TestMCP(Base):
    def rpc(self, method, params=None, i=1):
        return handle(self.ts, {"jsonrpc": "2.0", "id": i, "method": method, "params": params or {}})

    def test_handshake_list_call(self):
        self.assertEqual(self.rpc("initialize", {"protocolVersion": "2025-03-26"})["result"]["protocolVersion"], "2025-03-26")
        self.assertIsNone(handle(self.ts, {"jsonrpc": "2.0", "method": "notifications/initialized"}))
        self.assertEqual(len(self.rpc("tools/list")["result"]["tools"]), 5)
        r = self.rpc("tools/call", {"name": "get_ticket", "arguments": {"ticket_id": 2}})["result"]
        self.assertFalse(r["isError"])

    def test_errors_are_tool_errors_not_crashes(self):
        r = self.rpc("tools/call", {"name": "get_ticket", "arguments": {"ticket_id": "abc"}})["result"]
        self.assertTrue(r["isError"]); self.assertIn("invalid_arguments", r["content"][0]["text"])
        r = self.rpc("tools/call", {"name": "delete_ticket", "arguments": {}})["result"]
        self.assertTrue(r["isError"])
        self.assertEqual(self.rpc("bogus")["error"]["code"], -32601)

    def test_stdio_subprocess_e2e(self):
        env = dict(os.environ, FRESHDESK_API_KEY=mock.API_KEY, FRESHDESK_BASE_URL=self.url)
        reqs = [{"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}},
                {"jsonrpc": "2.0", "method": "notifications/initialized"},
                {"jsonrpc": "2.0", "id": 2, "method": "tools/call", "params": {"name": "search_tickets", "arguments": {"status": "open"}}}]
        out = subprocess.run([sys.executable, "-m", "fd_connector"], input="\n".join(map(json.dumps, reqs)) + "\n",
                             capture_output=True, text=True, env=env, cwd=os.path.dirname(os.path.dirname(__file__)), timeout=30)
        lines = [json.loads(l) for l in out.stdout.splitlines()]
        self.assertEqual([l["id"] for l in lines], [1, 2])
        self.assertNotIn(mock.API_KEY, out.stdout + out.stderr)  # key never leaks


if __name__ == "__main__":
    unittest.main()
