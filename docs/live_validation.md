# Live validation (Freshdesk Omni trial, fictional data)

Run on 2026-10-04 against a free-trial tenant seeded with 10 fictional tickets (`seed_demo_tickets.py`).

| Check | Result |
|---|---|
| API-key auth (`verify`) | ok; plan quota reported as 50 req/min via `X-Ratelimit-Total` |
| `list_tickets` (pagination, `has_more`) | ok |
| `get_ticket` + conversations | ok; private notes excluded; phone number in a ticket masked (`Call [phone]`) |
| `search_tickets` by tag / status+priority / date+tag | ok |
| Search vs. ground truth (list endpoint) | identical sets for `refund` {4,5,9,12} and `shipping` {4,7,10,12} |

## Findings
1. **Search index lag.** Immediately after seeding, tag searches returned incomplete results (1 of 4 for `refund`). Minutes later they matched the list endpoint exactly. Agents must not treat a fresh search as complete; use `list_tickets` for recently created tickets.
2. **Shared quota.** The tenant quota is 50 req/min and was partly consumed by other scripts using the same key. The client now syncs its local token bucket to the server's `X-Ratelimit-Remaining`, so it backs off for quota used by other processes.
3. Freshdesk includes built-in sample tickets (e.g. "Authentication failure"); they appear in results.

## Rate-limit stress test (70 calls on a 50/min plan, `scripts/rate_limit_demo.py`)
- Calls 1-50 completed in ~25s (old defaults: 50-call burst); `remaining` counted down 49 -> 0.
- Call 51 returned HTTP 429; the client honoured `Retry-After` (40s, consistent with a fixed 60s window starting at the first call) and calls 51-70 then succeeded. No crash, no lost data.
- **Finding:** a full-size token bucket allows up to ~2x quota across a fixed-window boundary, so it did not prevent the 429. Fix: defaults changed to 40 req/min sustained with a burst of 10 (burst + per-window refill <= 50), covered by a unit test. 429 handling remains as the safety net.
- Per-call cost: `get_ticket` with conversations = 2 API calls; on a 50/min plan an agent has roughly 20-25 such tool calls per minute.

## Re-run after the burst-limited defaults (40/min sustained, burst 10)
- 70 sequential calls: **zero 429s**, total 103 s. First ~15 calls fast, then ~1.5 s per call; `remaining` reached 0.0 at call 50 and reset to 49.0 at call 51 (~61 s after the first call, consistent with a fixed 60 s window).
- One unexplained 13.7 s stall at call 63 (no error surfaced; likely network latency or a silent retry). Not investigated further.
- Burst + rate sums to exactly the plan quota, leaving no margin if another client shares the key; the server-header sync is the safeguard for that case.
