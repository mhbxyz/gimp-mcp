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
