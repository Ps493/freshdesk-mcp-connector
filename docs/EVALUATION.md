# Evaluation

`python scripts/run_eval.py` (live tenant) or the same runner inside `python -m unittest` (mock, runs in CI).

## Method: oracle comparison
The runner builds a ground-truth **oracle** by paging the plain list endpoint (`updated_since=2000-01-01`, because Freshdesk's list endpoint otherwise returns only recent tickets). Tool outputs are then compared with the oracle, so the checks do not depend on hand-written expected IDs and work on any tenant.

| Case | What it checks |
|---|---|
| E01 | credentials work (`check_connection`) |
| E02 | `per_page` honoured; `has_more` correct |
| E03 | `get_ticket` agrees with the list view; response carries the `untrusted_content` notice |
| E04 (refund, shipping) | tag search returns exactly the oracle set (retries allowed for Freshdesk's search-index lag) |
| E05 | `status=open + priority=urgent` search equals the oracle |
| E06 | future date filter returns nothing |
| E07 | unknown id gives a typed `not_found`, not a crash |
| E08 | 8 malformed / injection-style arguments are rejected **before any network call** |
| E09 | no email or phone pattern in free-text fields (subjects, descriptions, replies) |
| E10 | every tool is read-only; none has a write verb in its name |
| E11 | every response exposes rate-limit metadata for the agent |

## Live run
Run `python scripts/run_eval.py --search-retries 3 --wait 30 --out docs/eval_results.md` against your tenant and commit `docs/eval_results.md` (it contains ticket IDs and fictional subjects only).

## What this does not measure (be upfront about it)
- **LLM behaviour.** The runner tests the connector's contract, not whether a model picks the right tool or phrases a good answer. The next step is a prompt set (e.g. "which urgent tickets mention refunds?") with the expected tool call per prompt, scored on tool choice, arguments, and answer faithfulness against the oracle.
- **Scale.** The tenant has ~13 tickets; pagination at hundreds of tickets and the 300-result search cap are covered by unit tests and documentation, not by live data.
- **Private notes and conversations.** The trial tickets have no replies or private notes; those paths are covered by the mock only.
