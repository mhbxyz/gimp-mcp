# ADR 0007 — Resources, prompts, progress heartbeats and cancellation semantics

- Status: accepted (2026-11-08)
- Context issue: #62

## Context

Until v0.3.0 the server only exposed tools. MCP also has resources (state a client can read or
attach without a tool call), prompts (workflows a user picks) and progress notifications. GIMP
constrains what can be offered:

* the bridge is request/response and GIMP runs one request at a time; libgimp gives a plug-in no
  completion fraction for the procedures it calls;
* a procedure running inside GIMP cannot be aborted from outside;
* images can be opened and closed in GIMP's UI, which the server does not see.

## Decision

* **Resources**: `gimp://images` (static) and, per open image, `gimp://images/{image}/layers`
  (JSON) and `gimp://images/{image}/preview` (PNG, 512 px), also published as templates. The ids
  are the tools' ids, so a resource and a tool talk about the same thing. `resources/list` asks the
  bridge for the open images each time (no cache); without GIMP it lists only `gimp://images`.
* **List-change notifications** are sent after tools declared with `changes_images=True` (those
  that open or close images), through both the legacy notification and the 2026 subscription
  stream. Changes made in GIMP's UI are not pushed (there is no event channel from GIMP); they
  appear at the next listing. Inside a batch, nested tools send nothing; the batch notifies once.
* **Prompts** are static, parameterized texts naming the tools to call; a unit test fails if a
  prompt names a tool that does not exist.
* **Progress**: the server keeps the current MCP request in a context variable
  (`GimpServer.call_tool`). Any bridge call lasting more than a second sends a heartbeat every
  second (elapsed seconds, no total) rather than a fake percentage. A batch reports files done out
  of the total and suppresses heartbeats so its progress values keep increasing, as MCP requires.
* **Cancellation**: the MCP request is interrupted at once; the GIMP operation in flight is **not**
  (it cannot be). The bridge drops the connection so the late answer is never mistaken for another
  one, and remembers that GIMP may be busy: the next handshake waits up to the request timeout
  instead of the 3 s connect timeout (a frozen GIMP is still detected after a real timeout). A
  batch's cleanup runs shielded from the cancellation and also closes an image whose opening was in
  flight (matched by file path among the images that appeared since the batch started).

## Consequences

* Clients that ignore resources, prompts or progress are unaffected; tools behave as before.
* A user cancelling a long filter gets control back immediately, but the change still lands in the
  image; the documentation says so and suggests checkpoints to undo it.
* After a cancellation the next call can take as long as the abandoned operation.
