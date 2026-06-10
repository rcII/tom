# Comms-system deploy runbook

How to stand up the SDK comms-system on a host, verify it, and roll it back. The
moment the RFC bundle lands, deploy should be this checklist — not a scramble.

The system is three supervised `systemd --user` daemons plus the NATS server they
ride on:

| daemon | unit | what it does |
|---|---|---|
| Telegram bridge | `tom-telegram-bridge.service` | holds the Telegram channel by webhook push, republishes each update to NATS |
| wake relay | `tom-wake.service` | wakes an idle tmux session when its inbox has new messages (the cold-start fallback) |
| NATS | (your existing `nats-server`) | the event spine everything publishes to and reads from |

Each unit is installed from a **main checkout**, never an in-review branch, so a
daemon never runs mutable code. Bring them up one at a time and verify each before
the next.

## 0. Prerequisites

- `nats-server` running and reachable at `NATS_URL` (default `nats://127.0.0.1:4222`).
- The `nats` CLI on `PATH` (the bridge shells to it to publish). Check: `nats --version`.
- `uv` installed at `~/.local/bin/uv` (the units invoke `uv run --project ~/code/tom`).
- `~/code/tom` checked out to `main` and current: `git -C ~/code/tom checkout main && git -C ~/code/tom pull`.
- For the bridge only: a public HTTPS endpoint that terminates TLS and forwards the
  webhook path to the bridge's loopback port (Telegram requires HTTPS; the bridge
  speaks plain HTTP on `127.0.0.1`). Any reverse proxy works — nginx, caddy.

## 1. Telegram bridge

### 1a. The secret (never in the unit, never in git)

The bridge authenticates each webhook with a secret token Telegram echoes in the
`X-Telegram-Bot-Api-Secret-Token` header. It lives in an operator-created,
mode-600 env file — not the unit, not the repo:

```sh
mkdir -p ~/.config/tom
install -m 600 /dev/null ~/.config/tom/telegram-bridge.env
printf 'TELEGRAM_WEBHOOK_SECRET=%s\n' "$(openssl rand -hex 32)" \
  > ~/.config/tom/telegram-bridge.env
```

### 1b. Install + start the unit

```sh
cp ~/code/tom/deploy/tom-telegram-bridge.service ~/.config/systemd/user/
systemctl --user daemon-reload
systemctl --user enable --now tom-telegram-bridge.service
journalctl --user -u tom-telegram-bridge -f      # expect: "telegram bridge listening on 127.0.0.1:8788/telegram/webhook"
```

### 1c. Point the reverse proxy at it

Forward `https://<your-host><TOM_BRIDGE_PATH>` to `http://127.0.0.1:<TOM_BRIDGE_PORT>`.
With the defaults that's `…/telegram/webhook` → `127.0.0.1:8788`.

### 1d. Register the webhook with Telegram (one time)

Tell Telegram where to push, with the **same** secret you generated in 1a:

```sh
SECRET=$(. ~/.config/tom/telegram-bridge.env; echo "$TELEGRAM_WEBHOOK_SECRET")
curl -sS "https://api.telegram.org/bot<BOT_TOKEN>/setWebhook" \
  --data-urlencode "url=https://<your-host>/telegram/webhook" \
  --data-urlencode "secret_token=$SECRET"
# confirm
curl -sS "https://api.telegram.org/bot<BOT_TOKEN>/getWebhookInfo"
```

`getWebhookInfo` should show your URL, `pending_update_count` draining to 0, and no
`last_error_message`.

### 1e. Config knobs

The secret comes from the env file (1a); everything else is in the unit as
`Environment=` and is safe to edit + `daemon-reload` + restart.

| variable | default | meaning |
|---|---|---|
| `TELEGRAM_WEBHOOK_SECRET` | *(required, env file)* | the secret token Telegram echoes; an empty value fails loud |
| `NATS_URL` | `nats://127.0.0.1:4222` | where the bridge publishes |
| `TOM_BRIDGE_HOST` | `127.0.0.1` | listen address (keep on loopback, behind the proxy) |
| `TOM_BRIDGE_PORT` | `8788` | listen port |
| `TOM_BRIDGE_PATH` | `/telegram/webhook` | the path the proxy forwards |
| `TOM_BRIDGE_MAX_BODY_BYTES` | `65536` | reject a body past this with 413, before reading it |
| `TOM_BRIDGE_NATS_BIN` | `nats` | the nats CLI binary (name on PATH or absolute) |
| `TOM_BRIDGE_PUBLISH_TIMEOUT_SECONDS` | `10` | publish timeout before a 500 (Telegram retries) |
| `TOM_BRIDGE_LOG_LEVEL` | `INFO` | log level |

A malformed numeric knob (port, body cap, timeout) fails loud at startup rather
than reverting to the default — a typo stops the daemon, it doesn't run wrong.

### 1f. What the bridge publishes

Each update becomes one NATS event on:

```
team.event.channel.telegram.<kind>
```

where `<kind>` is `message`, `edited_message`, `channel_post`, `callback_query`,
… or `unknown` (an update type we don't model is still forwarded, never dropped).
The envelope: `{event_id, source, kind, subject, ts, payload}`. `event_id` is
`telegram-<update_id>` — stable across redeliveries, so a consumer dedups on it.

## 2. Wake relay

```sh
cp ~/code/tom/deploy/tom-wake.service ~/.config/systemd/user/
systemctl --user daemon-reload
systemctl --user enable --now tom-wake.service
journalctl --user -u tom-wake -f
```

Before enabling, confirm the pane map for this host — `TOM_WAKE_PANES` is
`session=tmux-target` pairs (`tmux list-panes -a` to read them). A window holding
more than one `claude` pane must be given the fully-qualified `session:window.pane`
(e.g. `options-analyst=7:2.0`); a bare window is refused and logged, never guessed.

| variable | meaning |
|---|---|
| `TOM_WAKE_PANES` | `session=tmux-target` map (e.g. `tpm=7:1,catalyst=7:4`) |
| `TOM_WAKE_INBOX_ROOT` | the inbox root the relay watches |
| `TOM_WAKE_STATE_FILE` | where the per-session watermark persists (survives restart) |
| `TOM_WAKE_MESSAGE` | what a woken pane is sent (quote it — spaces) |
| `TOM_WAKE_DEBOUNCE_SECONDS` | don't re-wake the same session inside this window |
| `TOM_WAKE_INTERVAL_SECONDS` | sweep cadence |
| `TOM_WAKE_BUSY_MARKERS` | pane text that marks it busy, so active work isn't interrupted (quote it) |

## 3. Verify the whole path

1. **Bridge alive:** `systemctl --user is-active tom-telegram-bridge` → `active`;
   the listening line in the journal.
2. **A real update flows:** with a NATS subscriber watching, send the bot a
   message and confirm one event lands:
   ```sh
   nats sub 'team.event.channel.telegram.>' &     # in one shell
   # send the bot "ping" from Telegram; expect a message event with your chat_id
   ```
3. **Auth holds:** a POST to the webhook path *without* the secret header is
   rejected (401) and publishes nothing:
   ```sh
   curl -s -o /dev/null -w '%{http_code}\n' -XPOST \
     http://127.0.0.1:8788/telegram/webhook -d '{"update_id":1}'   # -> 401
   ```
4. **Body cap holds:** a POST past `TOM_BRIDGE_MAX_BODY_BYTES` is 413, unread.
5. **Wake relay:** drop a test message in an inbox and confirm the journal logs a
   wake for that session (and that a busy pane is skipped).

## 4. Rollback

Each daemon is independent — roll back the one that's misbehaving, leave the rest.

```sh
# stop + disable a daemon
systemctl --user disable --now tom-telegram-bridge.service   # or tom-wake.service

# revert to the previous code, then restart
git -C ~/code/tom checkout <previous-good-sha>
systemctl --user restart tom-telegram-bridge.service
```

To take the bridge fully offline at the source, drop Telegram's webhook so updates
stop arriving (they queue on Telegram's side and replay when you re-register):

```sh
curl -sS "https://api.telegram.org/bot<BOT_TOKEN>/deleteWebhook"
```

NATS keeps buffering published events regardless, so a consumer that was down
catches up on reconnect — that's the point of routing the channel through the bus.

## Notes

- The units cap restarts (`StartLimitBurst=5` in `300s`) so a crash on bad config
  can't restart-storm; after five failures systemd holds until you reset it
  (`systemctl --user reset-failed <unit>`).
- The bridge binds loopback on purpose. Do not expose `TOM_BRIDGE_PORT` publicly —
  the only thing that should reach it is the TLS proxy forwarding the webhook path.
