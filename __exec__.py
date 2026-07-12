from __future__ import annotations

import logging
import os
import sys
from pathlib import Path

RUNTIME_ROOT = Path(__file__).resolve().parent


def configure_logging() -> None:
    level_name = os.environ.get("VAIN_LOG_LEVEL", "INFO").upper()
    level = getattr(logging, level_name, logging.INFO)
    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)-8s %(name)s %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
        force=True,
    )
    logging.getLogger("discord").setLevel(logging.INFO)
    logging.getLogger("vain").setLevel(level)


def bootstrap() -> Path:
    runtime = RUNTIME_ROOT
    runtime_str = str(runtime)
    if runtime_str not in sys.path:
        sys.path.insert(0, runtime_str)
    os.chdir(runtime)
    os.environ.setdefault("JISHAKU_NO_UNDERSCORE", "True")
    return runtime


def main() -> None:
    bootstrap()
    configure_logging()

    log = logging.getLogger("vain")
    log.info("starting vain-bot")

    from core.vain import Vain
    from core.managers.values import token

    if not token:
        raise RuntimeError(
            "Bot token is not set. Set token in core/managers/values.py."
        )

    import dcspoof
    dcspoof.mode("ios")

    log.info("launching discord client")
    Vain().run(token, reconnect=True)
