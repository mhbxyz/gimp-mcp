# Security model

## Threats considered

| Threat | Mitigation |
|---|---|
| Remote access over the network | The bridge only listens on a Unix domain socket; nothing binds TCP/UDP. |
| Another local user connecting | Socket `0600` in a `0700` directory owned by the user; the bridge checks the peer uid with `SO_PEERCRED` and closes foreign connections before reading. |
| A process of the same user without the token (e.g. sandboxed app with access to the runtime dir but not the token) | Mandatory `hello` with a 256-bit token from a `0600` file regenerated at each GIMP start; no operation runs before it. |
| Arbitrary code execution through the bridge | The bridge dispatches a fixed table of operations; there is no eval, no Script-Fu passthrough. |
| Confused responses / replay | Request ids are checked; a mismatch drops the connection. Requests pinned to a session id are refused after a GIMP restart. |
| Resource exhaustion by a client | Requests > 8 MiB are refused; responses are sent with a 10 s send timeout. |
| Secrets/data in logs | Logs never include the token or image data. |

## Not protected against

* Malicious code already running as the same user with access to the token
  file: it can drive GIMP like the MCP server can (same trust level as the user).
* Paths given to file tools are interpreted with the user's permissions (see
  the file tools documentation for overwrite rules).

## Reliability guarantees

| Situation | Behaviour | Test |
|---|---|---|
| GIMP not running / plug-in missing | `GIMP_NOT_RUNNING` in < 2 s | `test_missing_bridge_fails_fast_with_actionable_error` |
| GIMP frozen (socket accepts, never answers) | `BRIDGE_UNAVAILABLE` after the 3 s connect/handshake timeout | `test_frozen_gimp_does_not_block_forever` |
| Request slower than the timeout | `TIMEOUT`; for a mutation `outcome: "unknown"`; the connection is dropped so the late answer can never be read as another request's answer | `test_timed_out_mutation_reports_unknown_outcome_and_next_call_gets_its_own_answer` |
| MCP request cancelled by the client | The bridge connection is dropped; GIMP may still finish the operation (it is **not** cancelled inside GIMP) | `test_cancelled_request_never_leaks_its_late_answer_into_the_next_one` |
| GIMP crashes during a request | `DISCONNECTED`, `outcome: "unknown"` | `test_bridge_dying_mid_request_reports_disconnected_with_unknown_outcome` |
| GIMP restarted | The next call reconnects transparently; the new `session_id` invalidates old ids (`SESSION_CHANGED`) | `test_client_reconnects_after_the_bridge_restarts`, `tests/e2e/test_restart.py` |
| Concurrent tool calls | Serialized in issue order on one connection; GIMP runs requests one at a time across all connections | `test_concurrent_mutations_run_in_issue_order_and_answers_are_not_mixed`, `test_two_clients_are_served_one_request_at_a_time` |
| Server shutdown (client closes stdin) | The server exits; in-flight requests are abandoned (their GIMP-side effect, if any, is kept) | `test_stdout_carries_only_json_rpc_and_logs_go_to_stderr` |

Retries: only **reads** are retried automatically, once, when the connection
turned out to be dead. Mutations are never retried automatically.

Logs: the token is never logged (`test_logs_never_contain_the_token`), nor are
image bytes; GIMP-side tracebacks stay in GIMP's console.
