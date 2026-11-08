# Security model

## Threats considered

| Threat | Mitigation |
|---|---|
| Remote access over the network | The bridge listens on a Unix domain socket (Linux, macOS) or a named pipe that rejects remote clients (Windows); gimp-mcp binds no TCP/UDP socket. Checked on each OS by `tests/e2e/test_no_network.py` over GIMP's whole process tree; the only listener found is GIMP for Windows' own D-Bus session bus (`gdbus.exe`), on loopback only. |
| Another local user connecting | Socket `0600` in a `0700` directory owned by the user; the bridge checks the peer uid with `SO_PEERCRED` and closes foreign connections before reading. |
| A process of the same user without the token (e.g. sandboxed app with access to the runtime dir but not the token) | Mandatory `hello` with a 256-bit token from a `0600` file regenerated at each GIMP start; no operation runs before it. |
| Arbitrary code execution through the bridge | The bridge dispatches a fixed table of operations; there is no eval, no Script-Fu passthrough. Generic PDB access goes through an allowlist that denies evaluation, consoles, servers, files, UI and external-effect plug-ins (`gmb_policy.py`, see `docs/tools.md#generic-procedure-access`). |
| Confused responses / replay | Request ids are checked; a mismatch drops the connection. Requests pinned to a session id are refused after a GIMP restart. |
| Resource exhaustion by a client | Requests > 8 MiB are refused; responses are sent with a 10 s send timeout. |
| Secrets/data in logs | Logs never include the token or image data. |

## Not protected against

* Malicious code already running as the same user with access to the token
  file: it can drive GIMP like the MCP server can (same trust level as the user).
* Paths given to file tools are interpreted with the user's permissions (see
  the file tools documentation for overwrite rules).

## File paths

Decision (#102): file tools accept **local absolute paths only**.

* On Windows, UNC paths (`\\server\share\…`, including `\\localhost\C$\…`) and the device
  namespaces (`\\?\…`, `\\.\…`) are refused before GIMP is asked anything. Opening a UNC path makes
  Windows connect to that machine and offer the user's credentials (NTLM), so a path suggested by
  a document or a web page an agent read could leak them or pull a file from an attacker's server.
  Reserved device names (`CON`, `NUL`, `COM1`…) are refused too: they are not files.
* Mapped drives (`Z:\…`) and network file systems mounted on Linux or macOS are accepted: the user
  chose to mount them, and the OS presents them as local paths.
* Batch globs stay inside their directory: patterns cannot have a drive, a root or `..`, and
  every match is kept only if its resolved location is inside the directory, compared by file
  identity (device and inode), so symlinks, junctions, case and Unicode spellings cannot escape.
* "Never an input" and "same file listed twice" compare file identities; outputs that do not exist
  yet are compared as the OS names them (case-insensitive on macOS and Windows, Unicode form
  ignored on macOS, the safe side on case-sensitive volumes).

Tests: `tests/unit/test_os_paths.py` (rules for every OS on every runner, and the behaviour of the
runner's own file system) and `tests/e2e/test_os_paths.py` (real GIMP on Linux, macOS and Windows).

## Reliability guarantees

| Situation | Behaviour | Test |
|---|---|---|
| GIMP not running / plug-in missing | `GIMP_NOT_RUNNING` in < 2 s | `test_missing_bridge_fails_fast_with_actionable_error` |
| GIMP frozen (socket accepts, never answers) | `BRIDGE_UNAVAILABLE` after the 3 s connect/handshake timeout | `test_frozen_gimp_does_not_block_forever` |
| Request slower than the timeout | `TIMEOUT`; for a mutation `outcome: "unknown"`; the connection is dropped so the late answer can never be read as another request's answer | `test_timed_out_mutation_reports_unknown_outcome_and_next_call_gets_its_own_answer` |
| MCP request cancelled by the client | The bridge connection is dropped; GIMP may still finish the operation (it is **not** cancelled inside GIMP). The next call waits for GIMP to finish it (up to the request timeout) instead of failing | `test_cancelled_request_never_leaks_its_late_answer_into_the_next_one`, `test_after_a_cancelled_request_the_next_call_waits_for_gimp_to_finish_it`, `tests/e2e/test_protocol.py` |
| Batch cancelled by the client | No further step or file; the images the batch opened are closed without saving once GIMP is free | `test_cancelling_a_batch_stops_it_and_closes_its_images` |
| GIMP crashes during a request | `DISCONNECTED`, `outcome: "unknown"` | `test_bridge_dying_mid_request_reports_disconnected_with_unknown_outcome` |
| GIMP restarted | The next call reconnects transparently; the new `session_id` invalidates old ids (`SESSION_CHANGED`) | `test_client_reconnects_after_the_bridge_restarts`, `tests/e2e/test_restart.py` |
| Concurrent tool calls | Serialized in issue order on one connection; GIMP runs requests one at a time across all connections | `test_concurrent_mutations_run_in_issue_order_and_answers_are_not_mixed`, `test_two_clients_are_served_one_request_at_a_time` |
| Server shutdown (client closes stdin) | The server exits; in-flight requests are abandoned (their GIMP-side effect, if any, is kept) | `test_stdout_carries_only_json_rpc_and_logs_go_to_stderr` |

Retries: only **reads** are retried automatically, once, when the connection
turned out to be dead. Mutations are never retried automatically.

Logs: the token is never logged (`test_logs_never_contain_the_token`), nor are
image bytes; GIMP-side tracebacks stay in GIMP's console.
