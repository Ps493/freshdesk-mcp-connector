# What the agent can and cannot do

## Can
- Browse/triage: list tickets by updated/created/due/status, filter (`new_and_my_open`, `watching`, `spam`, `deleted`), paginate.
- Look up any ticket by id, with description and the first 10 customer/agent replies.
- Search by status, priority, tag, requester/agent/group id, created/updated date ranges (AND-combined).
- Self-diagnose: `check_connection` returns auth state and remaining rate-limit budget; errors are typed (`auth_failed`, `forbidden`, `not_found`, `rate_limited`, `invalid_arguments`, `network_error`).
- Survive throttling: proactive token bucket + `Retry-After` backoff, transparent to the agent.

## Cannot (by design)
- Create, reply to, assign, close, merge, or delete tickets. No writes of any kind.
- See private notes unless `include_private_notes=true` is passed explicitly.
- See raw emails/phone numbers unless the operator sets `FRESHDESK_REDACT_PII=0`.
- Full-text search of ticket bodies: Freshdesk's search API is field-based. The `advanced_query` fragment can use custom fields, but not free text.
- Return more than 300 search results, or attachments/inline images.
- Read contacts, companies, SLA or satisfaction data (easy extension; deliberately out of scope).

## Cost model
`get_ticket(include_conversations=true)` costs 2 Freshdesk API calls; other tools cost 1. On a 50 req/min plan (as on the trial tested) expect roughly 20-40 tool calls per minute. Freshdesk's search index can lag a few minutes behind new tickets (observed live); use `list_tickets` for just-created tickets.

## Freshdesk behaviours to know
- The plain list endpoint returns only recently created tickets by default; pass `updated_since` (the tool accepts it) to reach older ones. The eval oracle does this.
- Search is eventually consistent: new tickets can take minutes to appear (observed live).

## Known limitations
| Limitation | Impact | Long-term fix |
|---|---|---|
| Per-process, in-memory rate limiter | Multiple connector replicas can jointly exceed the account quota | Shared limiter (Redis) or one gateway per tenant |
| Single static API key per process | No per-merchant isolation; key rotation = restart | Multi-tenant credential broker (vault ref per merchant) + OAuth/Marketplace app where available |
| Polling, not push | Agent sees stale data between calls | Freshdesk automation webhooks → event queue → cached read model |
| stdio transport | One client per process | Streamable-HTTP MCP behind Agent Studio's gateway with authN/Z, audit log |
| No response cache | Repeat reads burn quota | Short-TTL cache keyed on (tenant, path, params) with `updated_since` invalidation |
| Not verified against a live tenant | Field drift possible on custom plans | Contract tests against a sandbox Freshdesk in CI |
| Redaction is regex-based | Misses names, addresses, order-specific PII | Presidio/NER pass, or field-level allow-listing |
