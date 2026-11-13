# End-to-End Closure Snapshot

Qualified RTL scenarios: 8/8. Canonical closure denominators are unchanged.

| Scenario | Result | Cycles | Accepted jobs | Consumed completions | Checked record reads |
|---|---|---:|---:|---:|---:|
| stateful_lifetime_campaign | PASS | 385899 | 385 | 385 | 5762 |
| stateful_cross_stage_retry | PASS | 7277 | 5 | 5 | 22 |
| stateful_handler_cached_arithmetic | PASS | 38488 | 1 | 1 | 2 |
| stateful_fault_both_pending | PASS | 8347 | 1 | 1 | 2 |
| stateful_reset_multiple_owners | PASS | 12741 | 6 | 4 | 10 |
| stateful_queued_invalidation | PASS | 12765 | 6 | 6 | 17 |
| stateful_read_permission_downgrade | PASS | 4721 | 5 | 5 | 14 |
| stateful_contended_sleep_drain | PASS | 34255 | 1 | 1 | 2 |

Reset-aborted jobs need not produce completions. Record-read replay matches publication and consumption within reset boundaries, including reused tags after reboot.

Trace IDs and SHA-256 bindings: [CSV](compute_end_to_end_closure.csv). This is supplemental scenario evidence, not a new Cartesian cross-coverage percentage.
