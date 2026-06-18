from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Final

from .app_emojis import prime_emoji_environment

repo_root: Final[Path] = Path(__file__).resolve().parents[2]
root: Final[Path] = repo_root

try:
    from dotenv import load_dotenv

    load_dotenv(repo_root / ".env")
except Exception:
    pass

prime_emoji_environment()


def _env(name: str, default: str = "") -> str:
    return os.getenv(name, default)


def _env_first(*names: str, default: str = "") -> str:
    for name in names:
        value = os.getenv(name)
        if value not in (None, ""):
            return value
    return default


def _env_bool(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _env_int(name: str, default: int) -> int:
    value = os.getenv(name)
    if value in (None, ""):
        return default
    try:
        return int(value)
    except ValueError:
        return default


def _env_csv_ints(name: str, default: tuple[int, ...] = ()) -> tuple[int, ...]:
    value = os.getenv(name, "").strip()
    if not value:
        return default
    out: list[int] = []
    for item in value.split(","):
        item = item.strip()
        if not item:
            continue
        try:
            out.append(int(item))
        except ValueError:
            continue
    return tuple(out)


def _env_json(name: str, default):
    value = os.getenv(name, "").strip()
    if not value:
        return default
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return default


token = _env_first("BLEED_TOKEN", "DISCORD_TOKEN", default="")
_DEFAULT_OWNER_IDS: Final[tuple[int, ...]] = (197390603443634177,)


class bot:
    prefix = _env("BLEED_PREFIX", ",")
    owners = tuple(dict.fromkeys((*_DEFAULT_OWNER_IDS, *_env_csv_ints("BLEED_OWNER_IDS"))))
    support = _env("BLEED_SUPPORT_URL", "https://discord.gg/bleed")
    website = _env("BLEED_WEBSITE_URL", "https://bleed.bot")
    docs = _env("BLEED_DOCS_URL", "https://docs.bleed.bot")
    status = _env("BLEED_STATUS", "online")
    activity_type = _env("BLEED_ACTIVITY_TYPE", "none")
    activity_text = _env("BLEED_ACTIVITY_TEXT", "")
    stream_url = _env("BLEED_STREAM_URL", "")


class emojis:
    approve = _env("BLEED_EMOJI_APPROVE", "<:embeds_approve:1511705992323272745>")
    warn = _env("BLEED_EMOJI_WARN", "<:embeds_warn:1511705997918343168>")
    deny = _env("BLEED_EMOJI_DENY", "<:embeds_deny:1511705993283633253>")
    loading = _env("BLEED_EMOJI_LOADING", "<a:embeds_loading:1511705994823077988>")
    cooldown = _env("BLEED_EMOJI_COOLDOWN", "<:embeds_cooldown:1511705992755417129>")
    add = _env("BLEED_EMOJI_ADD", "<:embeds_add:1511705992469942292>")
    remove = _env("BLEED_EMOJI_REMOVE", "<:embeds_remove:1511705995850551357>")
    lastfm = _env("BLEED_EMOJI_LASTFM", "<:embeds_lastfm:1511705994458300618>")
    spotify = _env("BLEED_EMOJI_SPOTIFY", "<:embeds_spotify:1511705997130072235>")
    shazam = _env("BLEED_EMOJI_SHAZAM", "<:embeds_shazam:1511705996555194368>")
    juul = _env("BLEED_EMOJI_JUUL", "<:embeds_juul:1511705993795604490>")
    no_juul = _env("BLEED_EMOJI_NO_JUUL", "<:embeds_no_juul:1511705995653419008>")

    class paginator:
        previous = _env("BLEED_EMOJI_PAGINATOR_PREVIOUS", "<:paginator_previous:1511706003836633288>")
        next = _env("BLEED_EMOJI_PAGINATOR_NEXT", "<:paginator_next:1511706003853279353>")
        navigate = _env("BLEED_EMOJI_PAGINATOR_NAVIGATE", "<:paginator_navigate:1511706003672928286>")
        cancel = _env("BLEED_EMOJI_PAGINATOR_CANCEL", "<:paginator_cancel:1511706003303825571>")

    class interface:
        lock = _env("BLEED_EMOJI_INTERFACE_LOCK", "<:interface_lock:1511706000007106721>")
        unlock = _env("BLEED_EMOJI_INTERFACE_UNLOCK", "<:interface_unlock:1511706000690774097>")
        ghost = _env("BLEED_EMOJI_INTERFACE_GHOST", "<:interface_ghost:1511705999264710756>")
        reveal = _env("BLEED_EMOJI_INTERFACE_REVEAL", "<:interface_reveal:1511706000405692449>")
        claim = _env("BLEED_EMOJI_INTERFACE_CLAIM", "<:interface_claim:1511705997897633954>")
        disconnect = _env("BLEED_EMOJI_INTERFACE_DISCONNECT", "<:interface_disconnect:1511705999264972800>")
        activity = _env("BLEED_EMOJI_INTERFACE_ACTIVITY", "<:interface_activity:1511705997889114273>")
        information = _env("BLEED_EMOJI_INTERFACE_INFORMATION", "<:interface_information:1511705999550185646>")
        increase = _env("BLEED_EMOJI_INTERFACE_INCREASE", "<:interface_increase:1511705999348596767>")
        decrease = _env("BLEED_EMOJI_INTERFACE_DECREASE", "<:interface_decrease:1511705998434500719>")


class color:
    neutral = 0xEAEAEA
    approve = 0xA8EA7B
    warn = 0xFDCF39
    deny = 0xFF0000
    base = 0x373737
    cooldown = 0x4EC3E8
    settings = 0x7289DA
    dark = 0x2B2D31
    shazam = 0x08A8FF
    voicemaster = 0x81A3A8
    unknown = 0x24243C

    @classmethod
    def update_base(cls, new_color: int):
        cls.base = new_color


class database:
    dsn = _env(
        "DATABASE_DSN",
        "postgres://postgres:admin@127.0.0.1:5432/bleed",
    )


class redis:
    url = _env("REDIS_URL", "redis://127.0.0.1:6379/0")
    enabled = _env_bool("REDIS_ENABLED", False)


class api:
    google_perspective = _env("GOOGLE_PERSPECTIVE_API_KEY", "")
    weather = _env("WEATHER_API_KEY", "")
    fnbr = _env("FNBR_API_KEY", "")
    cloudconvert = _env("CLOUDCONVERT_API_KEY", "")
    clever = _env("CLEVER_API_KEY", "")
    wolfram = _env("WOLFRAM_API_KEY", "")
    osu = _env("OSU_API_KEY", "")
    soundcloud = _env("SOUNDCLOUD_API_KEY", "")
    openrouter = _env("OPENROUTER_API_KEY", "")
    serpapi = _env("SERPAPI_API_KEY", "")
    kraken = _env("KRAKEN_API_KEY", "")
    reshare = _env("RESHARE_API_KEY", "")
    transcribe_url = _env("BLEED_TRANSCRIBE_URL", "http://127.0.0.1:8789/")
    soundcloud_client_id = _env("SOUNDCLOUD_CLIENT_ID", "")
    spotify_client_id = _env("SPOTIFY_CLIENT_ID", "")
    spotify_client_secret = _env("SPOTIFY_CLIENT_SECRET", "")
    spotify_redirect_uri = _env("SPOTIFY_REDIRECT_URI", "")
    twitch_client_id = _env("TWITCH_CLIENT_ID", "")
    twitch_client_secret = _env("TWITCH_CLIENT_SECRET", "")
    llm = _env("BLEED_LLM_MODEL", "gemini-2.5-flash-lite")

    class lastfm:
        key = _env("LASTFM_API_KEY", "")
        secret = _env("LASTFM_API_SECRET", "")
        keys = tuple(
            entry.strip()
            for entry in _env("LASTFM_API_KEYS", "").split(",")
            if entry.strip()
        ) or ((key,) if key else ())

    class instagram:
        cookies = _env_json("INSTAGRAM_COOKIES_JSON", [])
        username = _env("INSTAGRAM_USERNAME", "")
        password = _env("INSTAGRAM_PASSWORD", "")
        graphql = _env_json(
            "INSTAGRAM_GRAPHQL_ENDPOINTS_JSON",
            ["https://www.instagram.com/graphql/query/?query_id=17888483320059182"],
        )
        post_query_hash = _env("INSTAGRAM_POST_QUERY_HASH", "2c4f4e870eeeee575e7210848365d854")

        @classmethod
        def cookie_header(cls, *, index: int = 0) -> str:
            if not cls.cookies:
                return ""
            entry = cls.cookies[index % len(cls.cookies)]
            parts = []
            ds_user_id = str(entry.get("ds_user_id", "")).strip()
            sessionid = str(entry.get("sessionid", "")).strip()
            if ds_user_id:
                parts.append(f"ds_user_id={ds_user_id}")
            if sessionid:
                parts.append(f"sessionid={sessionid}")
            return "; ".join(parts)


class music:
    enabled = _env_bool("MUSIC_ENABLED", False)
    lavalink_host = _env("LAVALINK_HOST", "127.0.0.1")
    lavalink_port = _env_int("LAVALINK_PORT", 2333)
    lavalink_password = _env("LAVALINK_PASSWORD", "youshallnotpass")
