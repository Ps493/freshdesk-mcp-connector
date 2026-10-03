| Case | Check | Result | Detail |
|---|---|---|---|
| E01 | check_connection succeeds | PASS |  |
| E02 | list_tickets honours per_page and reports has_more | PASS |  |
| E03 | get_ticket agrees with oracle and flags untrusted content | PASS |  |
| E04-refund | search by tag 'refund' matches oracle | PASS | 4 tickets agree |
| E04-shipping | search by tag 'shipping' matches oracle | PASS | 4 tickets agree |
| E05 | search status=open + priority=urgent matches oracle | PASS | 4 tickets agree |
| E06 | future date filter returns nothing | PASS |  |
| E07 | unknown ticket id -> typed not_found | PASS |  |
| E08 | invalid/injection arguments rejected before any network call | PASS | 8 bad calls blocked, 0 network calls |
| E09 | no email/phone patterns in free-text fields of list + get output | PASS | 0 leaking field(s) |
| E10 | tool surface is read-only | PASS |  |
| E11 | responses expose rate-limit metadata | PASS |  |

12 passed, 0 failed, 0 skipped
