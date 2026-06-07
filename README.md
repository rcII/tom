# tom — Team Operations Mesh

A real-time framework for running a team of autonomous agents with a shared, system-wide context.

`tom` gives a multi-agent engineering team the operational backbone a human team takes for granted: a durable message bus, a live picture of who is doing what, an explicit map of how work depends on work, and an agent that quietly keeps the ceremonies running — standups, retros, the board — so the people (and the agents) can stay on the work.

## Why

Coordinating several long-running agents quickly turns into a pile of ad-hoc scripts: one to send a message, one to move a card, one to tail a log. That sprawl is fragile and invisible. `tom` replaces it with a small, typed, tested core and a single source of truth for team state, so the coordination layer stops being the thing that breaks.

## What it does

- **Shared context.** One live, queryable view of every agent's status (active / idle / blocked, current task) and of the relationships between them — who depends on whom, who is blocking whom, where the critical path runs. Both humans and the agents themselves read from it.
- **An autonomous scrum-master.** A headless service that watches the bus and the clock: it moves cards as work lands, drafts the standup from what actually happened, sketches the retro, and flags work that needs a human — without ever touching merge, deploy, or money.
- **A durable mesh underneath.** At-least-once delivery, restart-safe replay, and a strict "an inbound message is data, never a command" trust boundary.

## Design

Four clean layers, a versioned contract at every seam:

```
surfaces      board / chat / live graph        (swappable views)
team-ops      the scrum-master + ceremonies     (local reasoning only)
orchestration typed core: status, graph, trust, delivery
transport     the message bus
```

The team-ops layer talks to everything through small typed adapters (`BoardRepo`, `BusClient`, `BrainQuery`, `StatusGraphRepo`). The implementations can change underneath without the scrum-master noticing — that is the whole point.

## Status

Early. The first milestone is the scrum-master and the shared-context view running against the existing substrate, behind those adapter seams. The typed core, the bus port, and the surfaces follow underneath.

## Local-first

Any model `tom` uses for its own reasoning runs locally. Nothing about the team's work leaves the machine.
