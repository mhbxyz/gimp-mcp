# Tool reference

All tools return structured content (`structuredContent`) described by their
output schema, plus the same JSON as text. On failure `isError` is `true` and
`structuredContent` is:

```json
{"error": {"code": "NOT_FOUND", "message": "...", "hint": "...", "details": {}, "outcome": "not_applied"}}
```

`outcome`: `not_applied` (nothing changed, safe to retry), `unknown` (a
mutation may have been applied: inspect before retrying), absent for reads.

## Ids

Opaque strings bound to the GIMP session: `image:<n>@<session>` and
`item:<n>@<session>` (layers, groups, text layers, masks). They stay valid
until the object is deleted or GIMP restarts; after a restart they fail with
`SESSION_CHANGED`.

## Session

### `gimp_status`

Read-only. Returns `connected`, `gimp_version`, `session_id`,
`bridge_protocol`, `socket` and `images[]` (`id`, `name` — GIMP's localized
display name —, `file`, `width`, `height`, `dirty`).

## Error codes

| Code | Meaning |
|---|---|
| `GIMP_NOT_RUNNING` | No bridge socket, or stale socket (GIMP exited). |
| `BRIDGE_UNAVAILABLE` | Socket present but no answer in time (GIMP busy/frozen) or token unreadable. |
| `VERSION_INCOMPATIBLE` | GIMP < 3.2 or plug-in protocol mismatch. |
| `UNAUTHORIZED` | Bad token (stale token file, wrong socket). |
| `TIMEOUT` | No answer within the request timeout; mutation outcome `unknown`. |
| `DISCONNECTED` | Connection lost during a request; mutation outcome `unknown`. |
| `PROTOCOL_ERROR` | Malformed or mismatched bridge message. |
| `SESSION_CHANGED` | Id issued by a previous GIMP session. |
| `INVALID_ID` | Malformed id or wrong kind (item id where an image id is expected…). |
| `GIMP_ERROR` | Unexpected failure inside GIMP; for a mutation the outcome is `unknown`. |
