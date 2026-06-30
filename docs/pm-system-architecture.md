# pm-system Architecture

Agent-sovereignty, event-driven PM/ticketing per ADR-009. Every ticket is an
event; the SQLite read-model is a left-fold projection that can be rebuilt by
replaying the NATS JetStream log.

---

## Component Overview

```
┌─────────────────────────────────────────────────────────────────────┐
│                        NATS Bus Topology                             │
│                                                                     │
│  catalyst-nats :4222               comms-nats :4322 (DBL-107)      │
│  (trading + TEAM_TICKETS)          (inter-session comms + ops)      │
│                                                                     │
│  ┌──────────────────┐              ┌─────────────────────────┐     │
│  │ TEAM_TICKETS     │              │ req.board.*             │     │
│  │ TEAM_DECISIONS   │              │ team.event.pm.*         │     │
│  │ team.ticket.*    │              │ team.event.consent.*    │     │
│  │ team.agent.*     │              │ team.inbox.*            │     │
│  │ team.deploy.*    │              │ team.event.governed_    │     │
│  │ team.brain.*     │              │   close.signed          │     │
│  │ pipeline.stage.* │              │ req.alarm.*             │     │
│  └──────────────────┘              └─────────────────────────┘     │
└─────────────────────────────────────────────────────────────────────┘
```

> **DBL-107 split status:** TEAM_TICKETS + store-reflector + gh-projector remain
> on catalyst-nats (:4222). Board-read-responder, health-monitor, liveness-bridge,
> service-alert all already point to comms-nats (:4322). Migration is in-flight;
> durable fix = dedicated comms NATS container.

---

## JetStream Streams

### `TEAM_TICKETS` (catalyst-nats :4222)

Source of truth — the durable, replayable write-model. Every ticket event is
appended here; board.db is a left-fold projection over this log.

```python
# streams.py:71-84
_DEFAULT_STREAM_NAME = "TEAM_TICKETS"       # env: PM_TEAM_TICKETS_STREAM
_DEFAULT_SUBJECT     = "team.ticket.>"      # env: PM_TEAM_TICKETS_SUBJECT
RetentionPolicy.LIMITS                      # NOT WORK_QUEUE/INTEREST — replay
StorageType.FILE                            # survives nats-server restart
max_msgs_per_subject = -1 (unlimited)       # per-subject cap destroys history
max_age = 0, max_bytes = -1, max_msgs = -1  # no eviction under LIMITS
allow_rollup_hdrs = False                   # prevents publisher-driven history wipe
duplicate_window ≥ ack_wait × max_deliver  # 180s default (30s × 5 + margin)
```

**Consumer:** `store-reflector` (durable, ack=explicit, max-deliver=5,
ack-wait=30s). Connects to :4222 (pm-store-reflector.service:24).

### `TEAM_DECISIONS` (catalyst-nats :4222)

Decision event log — same replay/dedup invariants as TEAM_TICKETS.

```python
# streams.py:75-77
_DEFAULT_DECISIONS_STREAM_NAME = "TEAM_DECISIONS"
_DEFAULT_DECISIONS_SUBJECT     = "team.decision.>"
```

**Consumer:** decision-reflector daemon (folds into board.db decisions table).

### `TEAM_INBOX` (comms-nats :4322)

Inter-session async mailbox. One wildcard token = one recipient address.

```python
# inbox_stream.py:51-52
_DEFAULT_SUBJECT = "team.inbox.*"   # env: PM_TEAM_INBOX_SUBJECT
```

---

## NATS Subjects Reference

### Sovereignty Subjects (forgery-proofed by C1 ACLs)

| Subject | Description | Source |
|---------|-------------|--------|
| `team.ticket.<agent>.<id>.<verb>` | Agent-sovereignty ticket events | `emit.py:179` |
| `team.agent.<agent>.<verb>` | Agent lifecycle events (started/heartbeat/idle) | `lifecycle.py:86` |
| `team.decision.<agent>.<id>.<verb>` | Decision event-log | `decision_reflector.py:55` |

The C1 publish-ACL block (config/nats/team-ticket-acls.conf) enforces that each
user may only publish `team.ticket.<self>.>` and `team.agent.<self>.>`. Server
rejects any cross-sovereignty publish at the wire level.

### Shared Event Subjects

| Subject | Description | Source |
|---------|-------------|--------|
| `team.deploy.<service>` | Deploy-reconciler events (drift/sync per service) | `deploy/event.py:23,42` |
| `team.event.pm.health.degraded` | Health-monitor breach alert | `ops/health_monitor.py:281` |
| `team.event.pm.service.down.<unit>` | Service-down crash alert (systemd OnFailure) | `ops/service_alert.py:60,158` |
| `team.event.pm.reflector.<kind>.<verdict>` | Reflector-watchdog stall/lag events | `reflector_watchdog.py:212-213,243` |
| `team.event.governed_close.signed` | Operator-signed governed-close event | `operator/governed_close.py:31` |
| `team.event.consent.<verb>` | Operator consent events (act/deny) | `operator/consent.py:54,75` |
| `team.event.docs.context7.<slug>` | Context7 doc-fetch events | `context7_hook.py:82-83,370` |
| `team.event.agent.dispatch.<agent>` | Deferred-dispatch SLO-elapsed nudge | `deferred_dispatch.py:40-41,61` |
| `team.event.agent.stuck.<agent>` | Agent-stuck detection event | `liveness_detector.py:305-306,335` |
| `team.event.ticket.stale.<lane>` | Ticket-staleness breach event | `staleness_detector.py:190-191,225` |
| `team.brain.capture` | Team Brain memory-capture requests | `team_brain/capture_consumer.py:32` |
| `team.inbox.*` | Direct peer-to-peer messages | `inbox_stream.py:52` |
| `team.todo.>` | TODO publish hook | C1 ACL shared block |
| `team.checkin.>` | Session check-in hook | C1 ACL shared block |
| `team.broadcast.>` | Broadcast-to-all | C1 ACL shared block |
| `pipeline.stage.>` | Catalyst DVC pipeline stage events (catalyst-sole publisher) | C1 ACL CATALYST_PERMS |

### Req/Reply Subjects

| Subject | Description | Source |
|---------|-------------|--------|
| `req.board.agents.get` | Board read API — agent list | `board_read_responder.py:42` |
| `req.board.decisions.get` | Board read API — decisions list | `board_read_responder.py:43` |
| `req.board.version` | Board read API — liveness/version probe | `board_read_responder.py:44` |
| `req.alarm.fire` | Fire / upsert an alarm record | `alarm/state.py` + `alarm/cli.py:31` |
| `req.alarm.get` | Query alarm state (by id or ack_state) | `alarm/state.py` + `alarm/cli.py:31` |
| `req.alarm.ack` | Acknowledge an alarm | `alarm/state.py` + `alarm/cli.py:31` |
| `req.alarm.update` | Update alarm (resolve / change state) | `alarm/state.py` + `alarm/cli.py:31` |

---

## Systemd Daemons

### `pm-store-reflector.service`

Folds `TEAM_TICKETS` events into board.db (the SQLite read-model). The
source-of-truth consumer — board.db can be rebuilt by replaying the stream.

- **Bus:** catalyst-nats :4222 (`pm-store-reflector.service:24`)
- **Consumes:** `TEAM_TICKETS` durable consumer `store-reflector`
- **Emits:** `pm.board.reflected` (internal heartbeat)
- **Emits (cascade):** `team.event.agent.dispatch.>` (inc-ai-23 auto-unblock,
  least-privilege ACL — store-reflector.service: STORE_REFLECTOR_PERMS)
- **Writes:** board.db tickets table (via `store/fold.py`)
- **Entrypoint:** `scripts/run-store-reflector-daemon.sh`

### `pm-gh-projector.service`

Event-driven GitHub Projects v2 projector. Reads board.db, reconciles with
GitHub Projects GraphQL API (WP C3).

- **Bus:** catalyst-nats :4222 (`pm-gh-projector.service:27`)
- **Reads:** board.db (via board_read_api)
- **Writes:** GitHub Projects v2 (graphql mutations via `gh_apply.py`)
- **Entrypoint:** `scripts/run_gh_projector.py`
- **Pre-start:** `scripts/pm-version-stamp.sh pm-gh-projector` (self-attesting SHA)

### `pm-board-read-responder.service`

FastStream req/reply responder serving `req.board.*` read API (read-only board.db
projection for viz, EM-5181/5203/5277).

- **Bus:** comms-nats :4322 (`pm-board-read-responder.service:23`)
- **Listens:** `req.board.agents.get`, `req.board.decisions.get`, `req.board.version`
- **Reads:** board.db (read-only)
- **Entrypoint:** `scripts/run_board_read_responder.py`

### `pm-health-monitor.service`

One-shot timer: daemons active + no failed units + projections fresh + liveness KV
populated. Pages operator via NATS on breach.

- **Bus:** comms-nats :4322 (`pm-health-monitor.service:20`)
- **Reads:** systemd `is-active`, `list-units --failed`, projection mtimes,
  `AGENT_LIVENESS` KV key-count (via `nats kv ls`)
- **Publishes:** `team.event.pm.health.degraded` (on breach, `health_monitor.py:281`)
- **Entrypoint:** `python -m pm_system.ops.health_monitor`

### `pm-liveness-bridge.service`

Feeds `AGENT_LIVENESS` KV from heartbeat/*.beat file mtimes (the file-based
heartbeat-to-KV bridge for sessions that don't natively write KV).

- **Bus:** comms-nats :4322 (`pm-liveness-bridge.service:15`)
- **Reads:** `~/.claude/heartbeats/<agent>.beat` file mtimes
- **Writes:** `AGENT_LIVENESS` NATS KV bucket
- **Entrypoint:** `deploy/run-liveness-bridge.sh`

### `pm-service-alert@.service` (template)

Per-service crash alert. Instantiated by systemd OnFailure of another unit.
Sends Telegram page + publishes NATS team-event.

- **Bus:** comms-nats :4322 (`pm-service-alert@.service:38`)
- **Publishes:** `team.event.pm.service.down.<unit>` (`service_alert.py:60,158`)
- **Entrypoint:** `python -m pm_system.ops.service_alert %i`

### `pm-deferred-dispatcher.service`

One-pass dispatcher: emits `team.event.agent.dispatch.<agent>` for any
wait-state ticket whose SLO deadline has elapsed (RFC-002 WP-1 / inc-ai-23).

- **Bus:** not pinned (uses PM_NATS_URL default)
- **Reads:** board.db (open wait-state tickets with elapsed deadlines)
- **Publishes:** `team.event.agent.dispatch.<agent>` (`deferred_dispatch.py:61`)
- **Entrypoint:** `scripts/run-deferred-dispatcher.sh`

### `pm-deploy-reconciler.service`

One-pass READ-ONLY merged-not-deployed detection (EM-4869). Checks each known
service's deployed SHA vs `origin/main`; emits drift tickets as `TEAM_TICKETS`
events.

- **Bus:** catalyst-nats :4222 (TEAM_TICKETS publish)
- **Reads:** each service's `/version` endpoint or git-HEAD attestation
- **Publishes:** `team.ticket.<owner>.<deploy-drift-service>.created`
  (via `deploy/board.py:drift_ticket_event` with real agent owner from
  `_REPO_TO_AGENT` — deploy/board.py:27–32)
- **Emits:** `team.deploy.<service>` (`deploy/event.py:23,42`)
- **Entrypoint:** `scripts/run-deploy-reconciler.sh`

---

## Data Store: `board.db` (SQLite)

Location: `~/.claude/inter-session/pm-store/board.db`

| Table | Description | Schema source |
|-------|-------------|---------------|
| `tickets` | Ticket read-model (left-fold of TEAM_TICKETS) | `store/schema.py` |
| `decisions` | Decision read-model (left-fold of TEAM_DECISIONS) | `store/decision_fold.py` |
| `schema_version` | Migration sentinel (current: v6) | `store/schema.py` |
| `alarm_state` | Alarm ack/resolution state (PR #368, migration 6) | `store/schema.py` |

**Fold engine:** `store/fold.py:fold_event` — applies a `TicketEvent` to the
tickets table. Idempotent (dedup by `message_id`). Supports status transitions:
created → blocked/open/done; priority promotions; metadata updates.

**Rebuild:** replay the TEAM_TICKETS JetStream stream from seq 0 into a fresh
board.db via `store/backfill_blocked_deps.py`.

---

## C1 ACL Sovereignty Model

`config/nats/team-ticket-acls.conf` — drop-in `include` for comms-nats.

```
┌──────────────┬─────────────────────────────────────────────────────────┐
│ Principal    │ Sovereign publish                                        │
├──────────────┼─────────────────────────────────────────────────────────┤
│ tpm          │ team.ticket.tpm.>  team.agent.tpm.>                     │
│ catalyst     │ team.ticket.catalyst.>  team.agent.catalyst.>           │
│              │ pipeline.stage.> (sole publisher)                       │
│ options-analyst│ team.ticket.options-analyst.>  team.agent.options-…  │
│ viz          │ team.ticket.viz.>  team.agent.viz.>                     │
│ virtu        │ team.ticket.virtu.>  team.agent.virtu.>                 │
│ tom          │ team.ticket.tom.>  team.agent.tom.>                     │
├──────────────┼─────────────────────────────────────────────────────────┤
│ ALL agents   │ team.event.>  team.todo.>  team.checkin.>               │
│ (shared)     │ team.broadcast.>  team.inbox.>  req.>  _INBOX.>         │
│              │ $JS.API.>  $JS.ACK.>                                    │
├──────────────┼─────────────────────────────────────────────────────────┤
│ store-reflector│ $JS.API.>  $JS.ACK.TEAM_TICKETS.store-reflector.>   │
│ (least-priv) │ pm.board.reflected  team.event.agent.dispatch.>        │
├──────────────┼─────────────────────────────────────────────────────────┤
│ system       │ Full access (infra: nats-bridge, provisioning scripts)  │
│ default      │ team.event.>  team.todo.>  team.checkin.>               │
│ (no-auth)    │ team.broadcast.>  team.inbox.>  req.>  _INBOX.>         │
│              │ (NOT team.ticket.> — forgery-proofed)                   │
└──────────────┴─────────────────────────────────────────────────────────┘
```

**Forgery-proof invariant:** A session user publishing to
`team.ticket.<other>.>` is rejected at the wire. The `authorize_seed`
cross-emit exception in `migration.py` allows `system` identity to emit
as any agent at seed time ONLY — this is the one structural bypass, clearly
scoped to seed initialization.

---

## Key Data Flows

### 1. Ticket Lifecycle

```
Session (e.g. catalyst) → NATS publish team.ticket.catalyst.<id>.created
  → TEAM_TICKETS stream (appended, seq N)
  → store-reflector consumer (durable, ack-wait=30s)
  → store/fold.py:fold_event → board.db tickets row (upsert)
  → gh_projector_daemon reads board.db diff → GitHub Projects v2 GraphQL mutation
```

### 2. Deploy-Drift Detection

```
pm-deploy-reconciler.service (cron)
  → deploy/reconciler.py: probe each service /version endpoint
  → deploy/board.py:drift_ticket_event → TicketEvent{agent=real_owner}
  → publish team.ticket.<owner>.deploy-drift-<svc>.created
  → TEAM_TICKETS → fold → board.db (blocked if genuine drift, open if advisory)
```

`_REPO_TO_AGENT` mapping (deploy/board.py:27–32):
```python
"catalyst-trading-platform" → "catalyst"
"options-analyst"           → "options-analyst"
"pm-system"                 → "tpm"
<unknown>                   → "tpm"   # fallback, never "system"
```

### 3. Health-Monitor Alert Flow

```
pm-health-monitor.service (timer, one-shot)
  → ops/health_monitor.py:evaluate_health → HealthBreach tuple
  → ops/health_monitor.py:diagnose_breaches → enrich with journal excerpt
  → ops/health_monitor.py:format_health_page → operator-facing page text
    (includes 🔑 ack: req.alarm.ack hints per breach, health_monitor.py:281)
  → NC.publish team.event.pm.health.degraded (if breach)
```

### 4. Deferred Dispatch (inc-ai-23)

```
pm-deferred-dispatcher.service (cron, every N min)
  → deferred_dispatch.py: query board.db for wait-state tickets past SLO
  → publish team.event.agent.dispatch.<agent>
    (the receiving session's inbox-bridge surfaces this as a task nudge)

  OR

pm-store-reflector fold (cascade path, WP-2 inc-ai-23)
  → on a newly-unblocked ticket: store-reflector publishes team.event.agent.dispatch.<owner>
    (STORE_REFLECTOR_PERMS narrow grant — deploy ACL conf:line ~80)
```

### 5. Alarm State (PR #368 / migration 6)

```
Health-monitor breach → req.alarm.fire (NATS req/reply)
  → alarm-state responder → board.db alarm_state upsert
    (alarm_id = "<check>:<subject>", idempotent, occurrence_count++)

Operator acks via pm-alarm CLI:
  pm-alarm ack daemon_down:pm-store-reflector.service --by tpm
  → req.alarm.ack → responder → board.db alarm_state ack_state=acked

Operator query:
  pm-alarm list --state unacked
  → req.alarm.get → responder → AlarmStateReply
```

---

## External Surfaces

| Surface | Direction | Owner daemon |
|---------|-----------|--------------|
| GitHub Projects v2 (GraphQL) | Write (upsert cards/fields) | pm-gh-projector |
| Telegram (via team-notify.py) | Write (EM pages) | health-monitor, service-alert |
| AGENT_LIVENESS KV bucket | Read/write | liveness-bridge (write), health-monitor (read) |
| Context7 API | Read | context7_hook.py (publishes team.event.docs.context7.*) |
| CCH memory API (:8001) | Write | team_brain/capture_consumer.py |

---

## Alarm State Table Schema (migration 6)

```sql
CREATE TABLE alarm_state (
    alarm_id         TEXT PRIMARY KEY,    -- "<check>:<subject>", idempotent
    alarm_type       TEXT NOT NULL,
    ack_state        TEXT NOT NULL DEFAULT 'unacked',  -- unacked|acked|resolved
    acked_by         TEXT,
    responder        TEXT,
    resolution_path  TEXT,
    first_fired_at   TEXT NOT NULL,
    last_fired_at    TEXT NOT NULL,
    occurrence_count INTEGER NOT NULL DEFAULT 1,
    last_payload     TEXT,               -- JSON
    updated_at       TEXT NOT NULL
);
```

Applied to live board.db as schema v5 → v6 (2026-06-30).
