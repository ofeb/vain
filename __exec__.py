from __future__ import annotations

import os
import sys
from pathlib import Path

RUNTIME_ROOT = Path(__file__).resolve().parent


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

    from core.bleed import Bleed
    from core.managers.values import token

    if not token:
        raise RuntimeError(
            "Bot token is not set. Set token in core/managers/values.py."
        )

    import dcspoof
    dcspoof.mode("ios")

    Bleed().run(token, reconnect=True)
