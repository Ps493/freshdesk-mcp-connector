# Freshdesk → Agent Studio Connector (read-only, MCP)

A private connector that lets an Agent Studio agent **read tickets** from Freshdesk through five MCP tools.
Python 3.10+, **zero third-party dependencies**, 21 offline tests against a local mock.

## Architecture

```
Agent Studio agent ──MCP (JSON-RPC/stdio)──▶ mcp_server.py ──▶ tools.py ──▶ client.py ──HTTPS GET──▶ Freshdesk /api/v2
                                              (protocol)     (validation,    (auth, token bucket,
                                                              shaping,        Retry-After, backoff,
                                                              redaction)      no-redirect, typed errors)
```
| Layer | Responsibility |
|---|---|
| `client.py` | Basic-auth API key (`key:X`), GET-only, token-bucket limiter, 429 → honours `Retry-After` (cap 60s), 5xx/network → jittered exp. backoff, redirects disabled so the key can't be forwarded, domain regex blocks SSRF, key never logged |
| `tools.py` | JSON-schema'd tools, strict arg validation, structured search → safe query builder, response slimming (token cost), PII masking, 1.2k-char text truncation |
| `mcp_server.py` | initialize / tools/list / tools/call / ping; failures return `isError` tool results so the model can self-correct |

## Tools
`check_connection` · `list_tickets` · `get_ticket` · `list_ticket_conversations` · `search_tickets` — full schemas in `docs/tools.mcp.json` (all annotated `readOnlyHint: true`).

## Setup & run
```bash
cp .env.example .env && export $(grep -v '^#' .env | sed 's/ *#.*//' | xargs)   # set real values
python -m fd_connector verify      # auth flow: confirms key + domain, prints rate-limit headroom
python -m fd_connector serve       # MCP stdio server (register this command in Agent Studio)
python -m fd_connector spec        # dump tool spec
```
Agent Studio / any MCP client config:
```json
{"command": "python", "args": ["-m", "fd_connector"], "env": {"FRESHDESK_DOMAIN": "acme", "FRESHDESK_API_KEY": "<secret-store ref>"}}
```
Tests (no network, no credentials): `python -m unittest discover -s tests -t . -v`
Try it locally without Freshdesk: `python -m tests.mock_freshdesk` then `FRESHDESK_BASE_URL=<printed url> FRESHDESK_API_KEY=test-key-not-real python -m fd_connector verify`.

## Guardrails (and why)
- **Read-only by construction** – the client has no write methods; a test asserts it. Use a least-privilege Freshdesk agent anyway.
- **Prompt-injection posture** – ticket text is attacker-controlled. Every response carries an `untrusted_content` notice; the mock includes an "IGNORE PREVIOUS INSTRUCTIONS" ticket.
- **Private notes excluded** by default; **PII masked** (email/phone) by default.
- **No raw query passthrough** – search uses typed filters; `advanced_query` is character-whitelisted (no quotes/backslashes), so the agent can't break out of Freshdesk's quoted-query syntax.
- **Bounded outputs** – `per_page ≤ 50`, search page ≤ 10, text truncated – protects context window and quota.

## Assumptions
- Freshdesk API v2, API-key auth (Freshdesk has no OAuth for personal API keys; OAuth is only for Marketplace apps).
- Plan limit is unknown at runtime, so the default is a conservative 50 calls/min; tune `FRESHDESK_CALLS_PER_MINUTE`.
- Validated against a local mock **and** a live Freshdesk trial tenant seeded with fictional data. See `docs/live_validation.md` for results and findings.

## Limitations & long-term fix → see `docs/CAPABILITIES.md`

## Docs
- `docs/CAPABILITIES.md` – what the agent can/cannot do, cost model, limitations and long-term fixes
- `docs/MERCHANT_SCENARIO.md` – the merchant problem framing, rollout and success metrics
- `docs/EVALUATION.md` – oracle-based evaluation method (`python scripts/run_eval.py`)
- `docs/live_validation.md` – results from a live Freshdesk trial tenant (fictional data)
- Live scripts (run from repo root, env vars set): `scripts/seed_demo_tickets.py`, `scripts/live_smoke.py`, `scripts/rate_limit_demo.py`, `scripts/run_eval.py`
