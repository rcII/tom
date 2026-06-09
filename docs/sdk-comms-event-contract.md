# Hook event contract (draft)

This is tom's half of the SDK comms system: the contract for the event stream the
whole thing rides on, plus the data the status widget renders. It's a draft for
converging with TPM (who owns the producer side, what each hook fires) and viz
(who builds the console). The code is in `tom/schemas/session_event.py`,
`tom/schemas/decision.py`, and `tom/projection/session_events.py`.

The split, settled: tom owns the data and the substrate (this contract, the
status/relationship projection it renders), viz builds the UI, TPM owns the
producer (which hook fires what, on Claude 2.1.169) and CCH.

## The event

Every hook firing becomes one `SessionEvent` on the bus:

```
SessionEvent(event_id, session, hook, ts, origin=first-party, payload)
```

`hook` is one of: `session-start`, `user-prompt-submit`, `pre-tool-use`,
`post-tool-use`, `notification`, `stop`, `session-end`, `permission-request`.
Subject: `team.event.session.<identity>.<hook>`.

**First-party, not inter-session.** These come from our own sessions' hooks. They
are trusted by authenticating the producer, which is a different path from the
untrusted inter-session message that goes through `admit()`. The two must not be
conflated: a first-party event is telemetry the producer is allowed to assert; an
inter-session message is data the receiver decides whether to act on. So the event
stream does not pass through the peer trust gate. It gets its own authenticated
first-party path (the producer signs / the transport authenticates the origin) —
TPM and I converge on the exact mechanism, but the contract draws the line here.

## Per-hook payload (TPM pins this)

The `payload` is open in the schema and the projection never reads it for meaning
(kind comes from `hook`, structurally). But the surfaces want known fields. This
is the proposed shape; TPM confirms against what each hook actually carries on
2.1.169:

| hook | payload fields (proposed) | feeds |
|---|---|---|
| `session-start` | `cwd`, `model` | status: active |
| `user-prompt-submit` | `task` (the prompt, summarized) | status: active + current task |
| `pre-tool-use` | `tool`, `input_summary` | status: active; an edge if the tool targets another session/PR |
| `post-tool-use` | `tool`, `ok` | status: active |
| `notification` | `text` | console timeline; status: alive |
| `stop` | (none) | status: **measured idle** |
| `session-end` | (none) | graph: retire the node |
| `permission-request` | `tool`, `input_summary`, `prompt` | a decision card; status: blocked |

## Folding into the status the model already computes

The hook stream is a richer source for the projection tom already built (#1-3:
HR-A status, HR-B relationship graph, the query verbs). `status_signal_from_event`
maps each event to the existing `StatusSignal`, so the console and the widget read
off one model. Two derivations carry the weight:

- **`stop` is a measured idle.** A Stop fires when a session finishes its turn, so
  it told us it's idle — `idle_basis = measured`, not the inferred "we haven't
  heard from it" the wake relay had to settle for. This is the measured-idle
  upgrade I'd flagged as a follow-up; the hook stream just delivers it.
- **`permission-request` is blocked.** A session waiting on a human decision reads
  as blocked on the status surface, and a card is raised so the wait is visible.

Relationship edges (HR-B) derive the same way a bus message does today: a
`pre-tool-use` that targets another session or a PR is an edge; the kind comes
from the validated event, never free text.

## R1b: kill the silent block

The headline. Today a permission prompt or a clarifying question blocks a session
silently in its pane until a human notices (the 8.5h-silent-block class). The fix
has two halves:

1. **Routine permissions resolve programmatically** (the producer's `can_use_tool`
   / a `PreToolUse` decision, TPM's side), by rule, so they never produce a
   blocking prompt at all.
2. **The ones that genuinely need a human** raise a `permission-request` event →
   a `DecisionCard` in the one decision store → rendered in the console, the
   board's needs-human lane, and Telegram → resolved there into a
   `DecisionResolution` (allow / deny / answered) that writes who, when, the
   verdict, and the surface. The resolution flows back to release the session. A
   `permission-request` raises the card; the matching resolution unblocks it (an
   `unblocked` signal returns the session to active).

The session is never silently blocked: the block becomes a visible, attributable,
routable card the instant it would have happened.

## The decision store (one source, three renders)

`DecisionCard` + `DecisionResolution` are the one store. The console, the sprint
board's needs-human/in_review lane, and the Telegram push leg all render the same
cards and resolutions; none is a separate source of truth. An inter-session
message can enqueue a card but can never resolve one — resolution is a human act
on a surface, recorded with provenance, so a texted signoff carries the same
weight as one clicked in the console (RFC-001 AC-29/AC-30).

## The status-widget data contract (what viz renders)

The widget (R3 / em1233 HR-A+HR-B) renders the projected model. viz subscribes;
tom serves. The shape is the model tom already computes:

- **nodes** — sessions and (as they earn it) tasks / PRs, each with status
  (`active` / `idle` / `blocked`), `idle_basis`, current task, current PR.
- **edges** — `message` / `review-of` / `depends-on` / `blocks` / `hands-off`,
  colored by kind.
- **derived answers** — `who_is_idle`, `who_blocks_whom`, `critical_path`,
  `status_of`, the existing `tom.queries` verbs, so the widget highlights the same
  things an agent would ask the model.

It's render-only and subscribe-only (RFC-001 §5.5): the console holds
subscribe-only credentials and cannot publish to `team.*`; it reflects the model
and never writes it. The dependency canvas (#15) is the text v0 of exactly this.

## Seams with TPM's half

- **Producer**: which hook fires what payload on 2.1.169 (the table above).
- **R1b mechanism**: `can_use_tool` vs a blocking `PreToolUse` hook for the
  interactive runtime; the card flow + resolution write-back is mine.
- **Context-injection (R4)**: I wire the inbound NATS event → `UserPromptSubmit`
  `additionalContext`; TPM specs the CCH recall payload it injects.

## Status

Draft. The schemas type-check and the derivation is tested (Stop→measured-idle,
PermissionRequest→blocked). The RFC itself lands in the vault, extending RFC-001;
these schemas are the tom-repo artifacts behind it. Not an accepted contract until
the convergence above closes.
