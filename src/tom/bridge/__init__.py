"""R8 external-channel bridges — channels as event sources on the spine.

An external channel (Telegram, voice) is an EVENT SOURCE, never a session-child
plugin and never a polling loop. A supervised bridge holds the channel via
webhook PUSH and republishes each update as a NATS event, so the session consumes
the channel from NATS and buffers across reconnects — the drop becomes
structurally impossible (a session-child plugin detaches on any transient; a
durable NATS subject does not).

This package is the bridge's pure core: the :mod:`tom.bridge.channel_event`
shape an update becomes, and the per-channel mapper (:mod:`tom.bridge.telegram`)
that turns a raw update into one. The webhook receiver, the NATS publish, and the
systemd supervision are the runtime shell layered on top.
"""
