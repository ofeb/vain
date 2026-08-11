from __future__ import annotations

import re

_ANGLE_URL_RE = re.compile(r"<(https?://[^>\s]+)>", re.IGNORECASE)


def _split_trigger_response(raw: str) -> tuple[str, str] | None:
    """Split a trigger and response pair from a command payload."""
    if "," not in raw:
        return None
    if ", " in raw:
        trigger, response = raw.split(", ", 1)
    else:
        trigger, response = raw.split(",", 1)
    trigger = trigger.strip()
    response = response.strip()
    if not trigger or not response:
        return None
    return trigger, response


def _parse_response_flags(raw: str) -> tuple[str, dict[str, object], str | None]:
    """Parse trailing autoresponder flags from the response body.

    Supported flags:
    - ``--strict`` / ``--not_strict`` (default: **not strict**)
    - ``--self_destruct <time>`` / ``--self-destruct`` (e.g. 10, 10s, 5m, 5mins, 1h)
    - ``--delete`` / ``--delete_trigger`` (delete the trigger message)
    - ``--reply on|off|yes|no|true|false`` (reply to the trigger)
    - ``--ignore_command_check``
    """
    flags = {
        "strict": None,
        "self_destruct": None,
        "delete": False,
        "reply": False,
        "ignore_command_check": False,
    }
    remaining = raw
    error: str | None = None
    flag_re = re.compile(
        r"(?:\s+--(?P<flag>strict|not_strict|not-strict|delete|delete_trigger|delete-trigger|reply|"
        r"ignore_command_check|ignore-command-check|self_destruct|self-destruct)"
        r"(?:=(?P<eqval>\S+)|\s+(?P<val>(?!\-\-)\S+))?)\s*$",
        re.IGNORECASE,
    )

    while True:
        match = flag_re.search(remaining)
        if not match:
            break

        flag = match.group("flag").lower()
        value = match.group("eqval") or match.group("val")
        if flag == "strict":
            flags["strict"] = True
        elif flag in {"not_strict", "not-strict"}:
            flags["strict"] = False
        elif flag in {"delete", "delete_trigger", "delete-trigger"}:
            flags["delete"] = True
        elif flag == "reply":
            if value is None:
                flags["reply"] = True
            else:
                low = value.lower()
                if low in {"yes", "true", "on", "1", "y"}:
                    flags["reply"] = True
                elif low in {"no", "false", "off", "0", "n"}:
                    flags["reply"] = False
                else:
                    error = "reply must be `on`/`yes`/`true` or `off`/`no`/`false`."
        elif flag in {"ignore_command_check", "ignore-command-check"}:
            flags["ignore_command_check"] = True
        elif flag in {"self_destruct", "self-destruct"}:
                if value is None:
                    error = "self_destruct must be a duration like 10, 10s, 5m, 5mins or 1h."
                else:
                    from core.tools.embed import parse_duration_token

                    seconds = parse_duration_token(value)
                    if seconds is None:
                        error = "self_destruct must be a duration like 10, 10s, 5m, 5mins or 1h."
                    else:
                        flags["self_destruct"] = seconds

        remaining = remaining[: match.start()].rstrip()

    return remaining.strip(), flags, error


def _is_embed_script(response: str) -> bool:
    """Return True when the response should be parsed as embed or container script."""
    from core.tools.embed import is_embed_script as _core_is_embed_script
    from core.tools.embed import is_container_script

    return _core_is_embed_script(response) or is_container_script(response)


def _matches_trigger(content: str, trigger: str, *, strict: bool) -> bool:
    """Match trigger against message content.

    Strict: entire message must equal the trigger.
    Not strict: trigger must appear as a whole word/phrase (word boundaries),
    so ``pic`` does not fire inside ``suspicious``.
    """
    content = (content or "").lower().strip()
    trigger = (trigger or "").lower().strip()
    if not trigger:
        return False
    if strict:
        return content == trigger
    pattern = re.compile(
        r"(?<!\w)" + re.escape(trigger) + r"(?!\w)",
        re.IGNORECASE,
    )
    return pattern.search(content) is not None


def _normalize_embed_script_urls(response: str) -> str:
    """Unwrap angle-bracket URLs inside embed scripts copied from Discord."""
    if not _is_embed_script(response):
        return response
    return _ANGLE_URL_RE.sub(r"\1", response)
