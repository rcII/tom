# tom

Team Operations Mesh. A backplane for a team of coding agents: it keeps a live
picture of who's doing what and what depends on what, runs the standing
ceremonies, and pokes idle sessions back to work, so the agents spend their time
on the work instead of on coordinating.

## Why it exists

Run a few long-lived agents at once and the glue between them turns into a heap
of one-off scripts. One to send a message, one to move a card on the board, one
to check who's stuck. None of it is tested, all of it is load-bearing, and when
it breaks you find out late. tom is that glue rewritten as one small typed
library with real tests, plus a daemon that runs the parts that should just run.

## What works today

**A shared picture of the team.** One model you can query: every session's
status (active, idle, or blocked, and what it's on), and the graph of how they
relate. It's folded from the message log, so it rebuilds the same way after a
restart, and the questions you'd actually ask resolve with a plain graph walk
and no model in the loop: `who_is_idle()`, `who_blocks_whom()`,
`who_depends_on(x)`, `critical_path()`, `status_of(session)`. Idle is reported
honestly. If a session simply went quiet we say so (inferred, no heartbeat)
rather than claiming we measured it asleep.

**A scrum-master that stays out of the way.** A headless service that watches
the bus and the clock. It moves a card to done only after `gh` confirms the PR
really merged (never on the say-so of a message), drafts the standup and retro
from what actually happened, and suggests tickets without pretending to estimate
them. Its whole vocabulary is: move a card, write a ceremony draft, suggest a
ticket, nudge someone. It can't merge, deploy, or spend money, and a test fails
if anyone gives it a fifth power.

**An auto-waker, running now.** Channels are passive. A message lands in an idle
session's inbox but nothing reads it until the session takes a turn, so idle
sessions sit on work. The wake relay watches the inboxes and the panes; when a
session is idle and has genuinely new mail, it sends one line to that session's
tmux pane to start a turn. That's all it does. It won't interrupt a busy pane,
it won't fire on the backlog of already-read mail, and it resolves each target
to one specific pane so a wake can never land in the wrong window.

It runs as a `systemd --user` service:

```
cp deploy/tom-wake.service ~/.config/systemd/user/
systemctl --user enable --now tom-wake.service
journalctl --user -u tom-wake -f
```

The session-to-pane map and the timing live in the unit as environment
variables. A window that holds more than one agent gets addressed by its exact
pane (`7:2.0`), so a shared window is never guessed at.

## How it's built

Four layers, each talking to the next through a small typed adapter, so any one
can change without the others noticing:

```
surfaces       the board, chat, the live graph
team-ops       the scrum-master, the ceremonies, the wake relay
orchestration  the typed core: status, graph, trust, delivery
transport      the message bus (NATS)
```

The scrum-master only knows four interfaces (`BoardRepo`, `BusClient`,
`BrainQuery`, `StatusGraphRepo`). Today they wrap the scripts and files the team
already runs on; later they point at the typed core, and the scrum-master itself
doesn't change. One rule holds everywhere: an inbound message is data, never a
command. The scrum-master reads it and decides; it never does what the text says
just because the text says it.

## Running it

```
uv sync --group dev
uv run pytest
uv run ruff check .
uv run mypy --strict src tests
```

CI runs the same three on every push, on a self-hosted runner.

## Local-first

Any model tom uses for its own reasoning talks to a local endpoint. There's no
cloud fallback anywhere in the code: it calls the one endpoint you configure and
fails loudly if it can't reach it, instead of quietly reaching for something
else. Nothing about the team's work leaves the machine.
