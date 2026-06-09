"""Run the Telegram webhook→NATS bridge: ``python -m tom.bridge``.

Resolves the listener config and the NATS publisher from the environment (both
fail loud on a missing required value) and serves until stopped. The systemd unit
supplies the environment; the secret comes from an operator-created env file, not
the unit.
"""

from __future__ import annotations

import logging
import os

from tom.bridge.publisher import nats_publisher_from_env
from tom.bridge.server import bridge_config_from_env, run

_LOG_LEVEL_ENV = "TOM_BRIDGE_LOG_LEVEL"
_DEFAULT_LOG_LEVEL = "INFO"


def main() -> None:
    logging.basicConfig(
        level=os.environ.get(_LOG_LEVEL_ENV, _DEFAULT_LOG_LEVEL),
        format="%(asctime)s %(name)s %(levelname)s %(message)s",
    )
    run(bridge_config_from_env(), nats_publisher_from_env())


if __name__ == "__main__":
    main()
