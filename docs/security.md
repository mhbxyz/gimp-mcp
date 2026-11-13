# Security model

gimp-mcp lets an AI agent drive the user's GIMP. This page says who could abuse that, what stops them on
Linux, macOS and Windows, which test proves each mitigation, and which risks are accepted. It was
reviewed as a whole before 1.0 (#122); a change to the transport, the file tools or the PDB access
updates it.

## Who is considered

| | Actor | Example |
|---|---|---|
| **R** | A remote host on the network | Another machine on the same Wi-Fi |
| **U** | Another local user | A shared Linux host, a terminal server |
| **S** | A process of the same user without the token | A sandboxed app that sees the runtime directory |
| **A** | The agent itself, misled by what it reads | Instructions hidden in an image's metadata, a document or a web page, carried out through tool calls the user approved |
| **C** | The supply chain | A compromised GitHub Action or downloaded tool in the release pipeline |

Code already running as the user with access to the token is out of scope: it can drive GIMP the way the
MCP server does, at the user's own trust level.

Tests are named `file::function`; unit tests live in `tests/unit/`, end-to-end tests (a real GIMP) in
`tests/e2e/`. Unit tests run on Linux, macOS and Windows (`ci.yml`, jobs `fast` and `unit-os`); tests for
one OS skip elsewhere.

## Transport and peer check

| Threat | Platforms | Mitigation | Test |
|---|---|---|---|
| R connects | Linux, macOS | Unix domain socket only: gimp-mcp binds no TCP or UDP socket | `test_bridge_reliability.py::test_bridge_listens_on_a_private_unix_socket_only`, `e2e/test_no_network.py::test_gimp_and_the_bridge_own_no_network_socket` (GIMP's whole process tree; the only listener is GIMP for Windows' own D-Bus bus, on loopback) |
| R connects | Windows | Named pipe created with `PIPE_REJECT_REMOTE_CLIENTS` | `test_windows_pipe.py::test_the_pipe_refuses_remote_clients`, `e2e/test_no_network.py::test_gimp_and_the_bridge_own_no_network_socket` |
| U connects | Linux, macOS, Flatpak | Socket `0600` in a `0700` directory; the plug-in reads the peer uid (`SO_PEERCRED`, `LOCAL_PEERCRED`) and closes a foreign or unknown peer before reading | `test_bridge_reliability.py::test_bridge_listens_on_a_private_unix_socket_only`, `::test_connection_from_another_uid_is_closed_before_any_request`, `::test_a_peer_whose_uid_cannot_be_read_is_refused` |
| U connects | Windows | Protected DACL naming only the user; the client's process owner is checked before registration | `test_windows_pipe.py::test_the_pipe_dacl_names_only_the_current_user`, `::test_a_client_of_another_user_is_refused_before_any_request` |
| U creates the socket directory first (`/tmp/gimp-mcp-<uid>` fallback) | Linux, macOS | The plug-in refuses a directory it does not own and makes its own `0700`; the socket is bound under umask `0177`, never briefly open to others | `test_bridge_mitigations.py::test_the_plugin_refuses_a_socket_directory_of_another_user`, `::test_the_plugin_makes_its_socket_directory_private_and_binds_with_a_private_umask` |
| U or S takes the address before GIMP | all | A live bridge is never replaced; a pipe name already served is refused (`FILE_FLAG_FIRST_PIPE_INSTANCE`) | `test_bridge_reliability.py::test_second_bridge_on_the_same_socket_refuses_to_start`, `test_windows_pipe.py::test_a_second_bridge_cannot_take_the_pipe_name` |
| U plays a fake bridge to the MCP server | Linux, macOS | The client checks the peer uid of the socket before sending anything, the token included (#122) | `test_bridge_client.py::test_a_bridge_served_by_another_user_is_refused_before_the_token_is_sent` |
| U plays a fake bridge to the MCP server | Windows | The client checks the owner of the process serving the pipe before writing, so a squatting server has nothing to impersonate the client with | `test_windows_pipe.py::test_a_pipe_served_by_another_user_is_refused_before_anything_is_written` |
| An answer meant for another request | all | Request ids are checked and a mismatch drops the connection (`outcome: "unknown"`); requests pinned to a session are refused after a GIMP restart | `test_bridge_mitigations.py::test_an_answer_to_another_request_drops_the_connection`, `test_bridge_client.py::test_request_pinned_to_another_session_is_refused_by_the_bridge` |
| Oversized messages | all | Requests over 8 MiB are refused; answers over 64 MiB drop the connection, and the next call reconnects | `test_bridge_reliability.py::test_oversized_request_is_refused`, `test_bridge_mitigations.py::test_an_oversized_answer_drops_the_connection_and_the_server_keeps_working` |
| A client that stops reading blocks GIMP | Linux, macOS | Answers are sent with a 10 s timeout, then abandoned | `test_bridge_mitigations.py::test_a_client_that_never_reads_cannot_block_the_bridge` |
| An older plug-in lacks the refusals made inside GIMP (below) | all | The operations that gained one have a new revision; with an older plug-in they fail with `PLUGIN_VERSION_MISMATCH` and the `gimp-mcp install-plugin` hint instead of running unprotected | `test_plugin_security_revisions.py::test_calls_that_rely_on_a_plugin_side_refusal_need_the_new_plugin`, `e2e/test_versions.py::test_the_previous_release_plugin_serves_this_server` |

## Token

| Threat | Platforms | Mitigation | Test |
|---|---|---|---|
| S drives GIMP | all | A `hello` with a 256-bit token comes first; nothing runs before it, a wrong token closes the connection; compared in constant time | `test_bridge_protocol_core.py::test_wrong_token_closes_the_connection_before_any_operation`, `test_bridge_reliability.py::test_request_before_hello_is_refused_and_connection_closed`, `test_bridge_client.py::test_wrong_token_is_rejected_before_any_operation_runs` |
| U reads the token | Linux, macOS | Token file `0600` in the `0700` directory | `test_bridge_reliability.py::test_bridge_listens_on_a_private_unix_socket_only` |
| U reads the token | Windows | Token in `%LOCALAPPDATA%\gimp-mcp\`, whose ACL admits only the user, SYSTEM and Administrators | `test_windows_pipe.py::test_the_token_file_is_readable_only_by_the_user_and_administrators` |
| A token read once is reused | all | A new token at every GIMP start; the file is removed when the bridge closes | `e2e/test_security.py::test_each_gimp_session_has_a_new_token`, `test_bridge_mitigations.py::test_the_plugin_makes_its_socket_directory_private_and_binds_with_a_private_umask` |
| The token in logs | all | Never logged | `test_bridge_reliability.py::test_logs_never_contain_the_token` |

## Files

File tools take **local absolute paths** (see [File paths](#file-paths)) and act with the user's
permissions anywhere they can read or write: confinement to chosen folders is an accepted risk (D1). What
stops A from turning that into code execution or a leak:

| Threat | Platforms | Mitigation | Test |
|---|---|---|---|
| A leaks the user's Windows credentials through a network path | Windows | UNC and device paths refused before any file system access, in every file tool, `gimp_export_layers` included | `test_os_paths.py::test_windows_refuses_network_and_device_paths`, `::test_file_tools_refuse_what_the_os_rule_refuses`, `test_format_tools.py::test_layer_exports_follow_the_path_rules_of_the_os`, `e2e/test_os_paths.py::test_network_paths_are_refused_on_windows` |
| A replaces a file silently | all | `FILE_EXISTS` unless `overwrite`; every tool that can replace a file is annotated destructive, so clients ask before it runs | `test_file_tools.py::test_path_problems_never_reach_gimp`, `test_format_tools.py::test_existing_targets_and_bad_directories_never_reach_gimp`, `test_api_contract.py::test_every_tool_that_can_replace_a_file_says_it_is_destructive` |
| A writes a script: a palette exported as `~/.zshenv` or a startup `.bat` (#122) | all | Palettes and paths are written only to files with their format's extension (`.gpl`, `.txt`, `.svg`…); `.gpl` names cannot start a line; GIMP's css, python, php and java exports refuse names that would change the code | `test_resource_tools.py::test_a_palette_is_exported_only_to_a_file_named_for_its_format`, `test_path_tools.py::test_paths_are_exported_only_to_svg_files`, `test_resource_helpers.py::test_a_palette_file_keeps_one_line_per_entry_whatever_the_names`, `::test_code_palette_exports_refuse_names_that_would_change_the_code`, `e2e/test_security.py::test_a_palette_never_turns_into_a_script` |
| A writes outside the chosen folder | all | Layer export templates are file names (no `/`, `\`, `:`), checked again in the plug-in | `test_format_tools.py::test_existing_targets_and_bad_directories_never_reach_gimp`, `test_formats.py::test_a_layer_file_name_never_leaves_its_directory` |
| A reads a private file through GIMP (#122) | all | The raw-data loader opens only `.data` and `.raw` files; the colorxhtml export cannot read its characters from a file | `test_formats.py::test_procedures_that_read_any_file_are_refused`, `e2e/test_security.py::test_procedures_that_read_other_files_are_refused` |
| A makes setup expose other servers' API keys | Linux, macOS | A rewritten client configuration keeps its permissions; a new one is created private | `test_setup.py::test_a_private_client_configuration_stays_private` |

## Generic PDB access (`procedures` toolset)

The bridge dispatches a fixed table of operations: no eval, no Script-Fu passthrough. `gimp_call_procedure`
reaches the rest of GIMP's procedure database through an allowlist (`gmb_policy.py`,
[docs/tools.md](tools.md#generic-procedure-access)), evaluated on GIMP's live metadata.

| Threat | Platforms | Mitigation | Test |
|---|---|---|---|
| A evaluates code | all | Script-Fu, Python-Fu, consoles, servers, quitting, deleting images, context changes, UI, help and PDB or plug-in management are denied | `test_pdb_policy.py::test_dangerous_or_incompatible_procedures_are_refused`, `e2e/test_pdb_access.py::test_discover_read_mutate_and_refuse` |
| A reaches files through the PDB | all | `file-*` procedures are outside the allowed families; `GFile`, `GBytes`, parasites and resources are unsupported argument types | `test_pdb_policy.py::test_dangerous_or_incompatible_procedures_are_refused` |
| A runs a third-party plug-in (G'MIC-Qt runs shell commands) (#122) | all | Only the `plug-in-*` procedures shipped with GIMP are callable, from a list kept equal to the GIMP inventory | `test_pdb_policy.py::test_only_the_plug_ins_shipped_with_gimp_are_callable`, `::test_the_list_of_gimp_plug_ins_is_the_inventory_of_gimp` |
| A opens a dialog | all | The run mode is forced to non-interactive | `test_pdb_policy.py::test_bad_arguments_are_refused_before_running` |
| Ids of another session | all | Ids carry the session id | `test_pdb_policy.py::test_arguments_are_converted_from_json_with_ids_bound_to_the_session` |

## Batch

| Threat | Platforms | Mitigation | Test |
|---|---|---|---|
| A glob leaves its directory | all | No drive, root or `..`; matches kept only inside the directory, compared by file identity | `test_batch_tools.py::test_glob_stays_inside_its_directory`, `test_os_paths.py::test_glob_does_not_follow_a_directory_link_out_of_its_directory`, `::test_glob_does_not_follow_a_junction_out_of_its_directory`, `e2e/test_os_paths.py::test_a_batch_glob_never_leaves_its_directory` |
| An output replaces an input | all | Outputs compared with inputs and each other as the OS names files | `test_os_paths.py::test_an_output_spelled_like_an_input_with_another_case_is_refused`, `e2e/test_os_paths.py::test_an_input_is_never_replaced_through_another_spelling` |
| A recipe escalates | all | A recipe cannot run a batch, enable toolsets or close images, nor use a tool of a disabled toolset; unknown step keys are refused | `test_batch_tools.py::test_invalid_recipes_are_refused_before_any_file_is_opened`, `::test_tools_of_disabled_toolsets_are_refused_with_a_hint`, `::test_a_step_with_an_unknown_key_is_refused_before_anything_runs` |
| A exhausts the server (#122) | all | A glob stops after `max_files` matches and runs off the event loop; placeholder widths are limited to three digits | `test_batch_tools.py::test_a_glob_stops_as_soon_as_it_finds_more_than_max_files`, `::test_invalid_recipes_are_refused_before_any_file_is_opened` |
| A cancelled batch leaves images open | all | Images opened by the batch are closed | `e2e/test_protocol.py::test_cancelling_a_batch_stops_it_and_closes_its_images` |

## Resources and prompts

| Threat | Platforms | Mitigation | Test |
|---|---|---|---|
| A bad resource URI crashes the server | all | Parsed ids, `ResourceError` | `test_protocol.py::test_bad_resource_ids_are_errors_not_crashes` |
| Previews flood the context | all | Previews at most 512 px and a byte budget | `test_protocol.py::test_open_images_layer_trees_and_previews_are_resources` |
| Prompt arguments inject instructions | all | Prompt arguments come from the user who picks the prompt; prompts only name existing tools | `test_protocol.py::test_prompts_reference_existing_tools` |

## Supply chain

| Threat | Mitigation | Test |
|---|---|---|
| C moves a tag of an action used by the release | Every action is pinned to a commit | `test_release_workflow.py::test_every_action_is_pinned_to_a_commit` |
| C replaces `mcp-publisher`, which runs with an OIDC token | Checked against its published SHA-256 before it runs, in the `mcp-registry` environment, whose token PyPI refuses | `test_release_workflow.py::test_the_registry_publisher_is_verified_and_cannot_publish_to_pypi` |
| A workflow token does more than it needs | Every workflow declares its permissions; the nightly job that runs a downloaded GIMP keeps no token in its checkout | `test_release_workflow.py::test_every_workflow_declares_its_token_permissions`, `::test_jobs_that_run_downloaded_builds_keep_no_token_in_the_checkout` |
| C publishes in our name | PyPI trusted publishing (no stored secret), approval in protected environments, build attestations | `test_release_workflow.py::test_publish_jobs_use_oidc_and_protected_environments`, `::test_no_long_lived_secret_is_used`, `::test_artifacts_get_build_provenance_attestations` |

## Accepted risks

| | Risk | Why it is accepted |
|---|---|---|
| D1 | File tools reach any path the user can read or write, not only chosen folders | GIMP users open and export everywhere; confining by default would break the main use. What made it dangerous (writing scripts, reading private files, network paths) is closed above. Opt-in confinement is tracked for 1.x (#227). |
| D2 | Prompt injection through data the tools return (metadata, layer and file names, text layers, GIMP's messages) | The server cannot tell instructions from data: the client and the user's approvals are the control. Tool annotations stay honest so that approvals mean something. Length caps and invisible-character stripping are tracked for 1.x (#228). |
| D3 | Code of the same user with the token, including a client that stops reading on Windows (the 10 s send timeout does not apply to pipes yet) | Same trust level as the user. The Windows timeout is tracked for 1.x (#229). |
| D4 | The plug-in trusts any authenticated client's paths | The token makes the client the MCP server; the path rules live in one place, the server, and are tested there. |
| D5 | GIMP's own loaders on untrusted files (Ghostscript, librsvg, libheif, darktable…) and paths inside documents (XCF link layers, SVG references) | Upstream code, the same risk as opening the file in GIMP by hand. |
| D6 | The nightly newest-GIMP job trusts gimp.org for both the file and its checksum | A scheduled, best-effort job with a read-only token and no credentials in its checkout. |
| D7 | Another user squatting the socket or pipe name keeps the bridge from starting | Refusing is the safe outcome; `gimp-mcp doctor` reports it, and the client never talks to the squatter. |
| D8 | `gimp_enable_toolsets` lets the agent enable any toolset, `procedures` included | Needed by the toolset design (ADR 0012); the allowlist above is the control. |
| D9 | A foreign uid reaching a Flatpak GIMP's socket is not tested inside the Flatpak user namespace | The same peer check runs there (Flatpak maps the user to the same uid); the Flatpak end-to-end job proves the positive path. |
| D10 | A plug-in added to a later GIMP is refused by the generic PDB access until the list is regenerated | Failing closed: the list is regenerated with the coverage inventory when a GIMP version becomes supported (docs/compatibility.md). |

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
