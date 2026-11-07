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
`item:<n>@<session>` (layers, groups, text layers, masks, channels, paths).

* **Unique** within the GIMP session: GIMP numbers images and items from two
  global counters, so an item id is unique across all open images.
* **Valid** until the object is deleted (image closed, layer removed) — then
  `NOT_FOUND` — or GIMP restarts — then `SESSION_CHANGED`, even if GIMP reused
  the same number for another object.
* Names are **not** identifiers: GIMP keeps layer names unique *within an
  image* by renaming duplicates (`Title` → `Title #1`), but the same name can
  exist in several images. Always target objects by id.
* Tools never depend on GIMP's active image/layer/selection in the UI.

## Session

### `gimp_status`

Read-only. Returns `connected`, `gimp_version`, `session_id`,
`bridge_protocol`, `socket` and `images[]` (`id`, `name` — GIMP's localized
display name —, `file`, `width`, `height`, `dirty`).

## Inspection

### `gimp_inspect_image(image)`

Read-only. Returns `id`, `name`, `file`, `xcf_file`, `imported_file`,
`exported_file`, `width`, `height` (pixels), `base_type` (`rgb`/`gray`/`indexed`),
`precision` (e.g. `u8-non-linear`), `resolution` (`x`, `y` in ppi), `dirty`
and `layers`: the layer tree, **top-most first**. Each node: `id`, `name`,
`kind` (`layer`/`group`/`text`), `parent` (group id or null), `visible`,
`opacity` (0–100), `mode` (GIMP layer-mode nick: `normal`, `multiply`…), `x`,
`y` (offset of the top-left corner, image pixels), `width`, `height`,
`has_alpha`, `locks` (`content`, `position`, `visibility`, `alpha`), `mask`
(`id`, `apply`, `show`, `edit`, or null) and `children` (groups only).

Errors: `INVALID_ID`, `NOT_FOUND`, `SESSION_CHANGED`.

### `gimp_inspect_item(item)`

Read-only. `id`, `image`, `kind` (`layer`/`group`/`text`/`mask`/`channel`/`path`),
`name`, `parent` (parent group, or the owning layer for a mask), `position`
(index in the parent, 0 = top-most; null for masks), `visible`, and for
layers the same properties as a tree node with `children` as a list of ids.

Errors: `INVALID_ID`, `NOT_FOUND`, `SESSION_CHANGED`.

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
| `NOT_FOUND` | The image/item no longer exists (closed, deleted). |
| `WRONG_KIND` | The id exists but designates another kind of object (e.g. a mask where a layer is required). |
| `INVALID_ARGUMENT` | An argument is out of range or inconsistent. |
| `GIMP_ERROR` | Unexpected failure inside GIMP; for a mutation the outcome is `unknown`. |
