# Should the team run on the Agent SDK instead of tmux panes?

Short answer: yes, the agents themselves should run as long-lived Agent SDK
processes, and when they do the whole tmux-wake apparatus this repo just built
stops being needed. But there are two real gates in front of that — cost and the
loss of the interactive terminal — and one of them lands in a few days. This doc
is the wake-substrate side of the analysis (TPM is writing the orchestration
side; the two converge). It covers what the SDK gives us natively, whether it can
replace the tmux wake, what the migration looks like, what it costs to keep tmux,
and how it lines up with RFC-001.

I read the docs myself first: the [overview](https://code.claude.com/docs/en/agent-sdk/overview),
[streaming vs single mode](https://code.claude.com/docs/en/agent-sdk/streaming-vs-single-mode),
and the [Python API](https://code.claude.com/docs/en/agent-sdk/python), then ran a
three-seat subagent panel (capability/gotchas, runtime design, adversarial).

## The thing I had wrong, and the page that fixes it

The easy mistake — which an earlier read on both sides made — is to treat the SDK
as one-shot `query()` calls: a hub spawning headless workers, no good fit for a
mesh of long-lived peers, so keep tmux and just add a wake hook. That's wrong,
and the reason is **streaming input mode**, which the docs call the default and
recommended way to use the SDK.

A `ClaudeSDKClient` in streaming-input mode, in the docs' own words, "allows the
agent to operate as a long lived process that takes in user input, handles
interruptions, surfaces permission requests, and handles session management." The
sequence diagram annotates it plainly: "Session stays alive." Mechanically:

- The **input** is an async generator you keep yielding user messages into. Every
  yield is a new turn into the *same* session. There is no per-message restart.
- `receive_messages()` is a persistent iterator that yields across many turns. A
  background task drains it while you push new input whenever you want.
- `interrupt()` stops a turn mid-flight. `can_use_tool` surfaces each tool
  request to your own code to allow or deny.

So you can feed a NATS subscriber straight into the input generator and stream the
results back out. That is a real event-bus-driven agent: no polling, no restart
per message, no keystrokes. The whole reason `tom-wake` exists — that a channel
event only surfaces at the next turn boundary, so an idle pane has to be poked —
**does not exist in this model.** A message *is* a turn.

## 1. What the SDK gives natively that we hand-rolled

The full capability map is in TPM's vault doc (`agent-sdk-vs-tmux-orchestration-2026-06-08.md`);
I won't repeat it. From the wake/runtime angle that I own, three things stand out:

| What we built | What the SDK gives | Read |
|---|---|---|
| `tom-wake`: a 30s poll loop + `tmux send-keys` + pane-address resolution + busy-marker screen-scraping + a multi-pane safety check | A streaming-input session that is *already listening*. Input is `queue.put`, not a simulated keystroke. | Replace it |
| `FileMirrorEventSource` (the Phase-1 `BusClient` stand-in) reading `*.msg` files | A first-class durable NATS consumer feeding the input generator | Fulfil the seam |
| `CaptureIdleDetector` greping the pane for "esc to interrupt" to guess busy/idle | The runtime *knows* its own turn state as data; nothing to guess | Delete |
| pane map `TOM_WAKE_PANES=tpm=7:1,...` (hand-maintained tmux coordinates) | `team.inbox.<identity>` subjects; no host coordinates | Delete |

The honest point: the `BusClient` Protocol in `adapters/protocols.py` was always
documented as a Phase-1 seam waiting for "the live typed consumer with its own
reconnect." The streaming-input peer runtime *is* that consumer. We weren't
building the wrong thing so much as building a stand-in for the thing the SDK
already is.

## 2. Can the SDK replace the tmux wake and poll? Yes.

Confirmed against the docs and pinned down by the panel:

- An external coroutine can call `client.query({"type":"user", "message": ...})`
  to push a new message into an already-connected client while another coroutine
  drains `receive_messages()`. That is exactly the NATS-fed input pattern.
- A human can inject into the *same* input stream the bus feeds (one ordered turn
  queue, no second path), `interrupt()` a turn, and answer permission requests
  through `can_use_tool`. Human-in-the-loop is preserved, not lost.
- Each peer is its own OS process with its own `cwd`, `system_prompt`,
  `setting_sources` (so its own `.claude/` and `CLAUDE.md` load exactly as the TUI
  loads them today), `mcp_servers`, and `env`. N processes, N identities. A wedged
  peer takes down only itself — there is no shared supervisor whose crash blacks
  out the team. (That "one crash kills all" worry only applies if you put N
  clients in one process, which you don't.)

So the wake hack isn't replaced by a better wake hack. It's deleted, because the
problem it solved is gone.

## 3. The peer-runtime design

One process per peer (`tom-peer --identity catalyst`), built around one
`ClaudeSDKClient`, joined by two queues. Sketch:

- An **input generator** that blocks on an `asyncio.Queue` and yields one user
  message per item. Idle is a cheap `await queue.get()`, not a poll.
- A **NATS consumer** (durable pull consumer on `team.inbox.<identity>`) that puts
  admitted messages on that queue. It runs the *same* `tom.trust.admit` gate we
  already have, so inbound is still data, never a command.
- A **drain task** iterating `receive_messages()`, republishing outputs to a
  `team.event.peer.output.<identity>` subject for observability, and — this is the
  load-bearing invariant — acking the NATS message only *after* the turn's
  `ResultMessage` lands. Same "handle before ack" rule the `ScrumMasterLoop`
  already enforces, so a crash mid-turn replays the message instead of dropping
  it.
- A **permission callback** (`can_use_tool`) that auto-allows what the loaded
  `.claude/settings` already allows and routes anything else to the human surface,
  failing closed (deny with a reason, surfaced to the bus) when no human is
  attached.

What deletes from this repo: the entire `tom/wake/` tree (`relay`, `runner`,
`pane`, `inbox`, `watermark`, `cli`, `__main__`), `deploy/tom-wake.service`, and
the five `test_wake_*` / `test_pane_driver` files. What stays, unchanged or
lightly repointed: NATS and the envelope schema, `tom.trust.admit`, the
scrum-master and observability (they consume the bus; they neither know nor care
whether peers are TUIs or SDK processes), and the file-mirror as disk-observability
per ADR-007.

The one genuinely new build is the **human-control surface**: a small local socket
that lets a human attach to a peer process, inject a message, watch the streamed
output, interrupt a turn, and answer a permission prompt. It is detachable — the
peer runs headless on the bus with nobody attached, and a human attaches when they
want eyes or hands. That is strictly better than tmux, where "attach" means the
human *is* the only consumer of the pane and competes with `send-keys`.

## 4. The two gates I won't paper over

The adversarial seat earned its keep here. Two things must be settled before any
of this is more than a design.

**Cost and auth, and the clock is real.** Starting June 15 2026, Agent SDK usage
on subscription plans draws from a new, separate monthly Agent SDK credit, not the
interactive limits the panes use today. And the docs steer non-approved SDK
processes to API-key auth, not subscription login. So the realistic shape of this
is five always-on agents on metered API pricing, each re-sending a growing context
on every turn. Nobody has put a number on that. It could be fine; it could be the
thing that decides the whole question. **This gets modeled — tokens/day × 5 ×
context growth, on both the credit path and the API-key path — before we commit.**

**The interactive terminal is a real thing to lose.** Four of these sessions have
a human who sits at the pane: the live scroll you glance at, slash commands, plan
mode, vim mode, the permission UI. A headless SDK process is not that, and the
"thin control surface" has to rebuild a meaningful slice of it (input, streamed
output, permission prompts, an interrupt). That is the one real build, and it
shouldn't be undersold as thin. The peer with no human in its seat — tom itself,
the scrum-master — loses none of this, which is why it's the right pilot.

Two more, lower: a session that lives for days needs a recycle story (context
fills, compaction is lossy, so there's a fork/resume seam — moved from a human's
muscle memory into code we have to write); and the bus-fed model brings
distributed failure modes the TUI didn't have (crash-while-down, replay,
backpressure, a poisoned input message going straight into `query()`). Some of
this is already on the backlog (DBL-032, replay on disconnect).

## 5. RFC-001 alignment

RFC-001 never named the Agent SDK — it settled on NATS as the wire and assumed
human-drivable sessions, and the tmux substrate was the Phase-1 expedient "on the
existing substrate behind clean adapter seams." Streaming input doesn't fight that
intent; it lands it. The `BusClient` seam was explicitly the placeholder for the
live consumer, and this is that consumer. Sovereignty is unaffected: the peers are
*already* cloud Claude Code, so running them on the SDK changes nothing about their
trust posture. tom's own local-only reasoning (`tom-llm`, the Ollama path) is a
separate pillar and is untouched.

The sharp, fair version of EM's charge is narrow: for the one problem the SDK most
cleanly solves — wake on event — we named the fix (EM-606), deferred it, and then
spent that same window hardening the tmux poke it was meant to retire (PRs #20,
#23). The streaming-input runtime is the correct end of that, not a wider hook on
the old substrate.

## 6. Recommendation

1. **Model the cost and confirm the auth path first.** This is days of clock, not
   weeks of build, and it can change everything. Nothing else starts until it's
   done.
2. **Build the peer runtime and pilot it on tom (the scrum-master).** It's the one
   peer no human sits at, so it proves the hard parts — crash, replay, session
   recycle, the bus-fed input — without needing the full control surface first.
3. **Build the human-control surface** against that pilot. This is the real build;
   treat it as such.
4. **Convert the human-driven peers one at a time, shadow then gated handoff**, in
   increasing blast-radius order, keeping each tmux pane alive (idle) until its SDK
   peer has soaked, so rollback is reversing one handoff and is lossless. tpm
   last, since it gates quorum. When the pane map empties, delete `tom/wake/`.

The bus, the mailbox, the envelopes, the trust gate, the scrum-master — all of it
carries forward. What we'd be deleting is the part that simulates a human typing
into a terminal, which is exactly the part EM is asking about.

This is a design, not an accepted decision. Replacing the live inter-session
transport is at least a T2, and the tpm cutover is arguably T3 — it needs a real
ADR and a panel before code, and its first task is pinning the installed
`claude_agent_sdk` version and proving `interrupt()` and `can_use_tool` behave as
documented, because the whole thing rests on them.
