from __future__ import annotations

import os
from pathlib import Path
from typing import Final

from .app_emojis import prime_emoji_environment

try:
    from dotenv import load_dotenv
except Exception:
    load_dotenv = None

repo_root: Final[Path] = Path(__file__).resolve().parents[2]
root: Final[Path] = repo_root

if load_dotenv is not None:
    for candidate in (repo_root / ".env", repo_root.parent / ".env"):
        if candidate.exists():
            load_dotenv(candidate, override=False)


def _env(name: str, default: str = "", *, aliases: tuple[str, ...] = ()) -> str:
    for key in (name, *aliases):
        value = os.getenv(key)
        if value is not None and str(value).strip() != "":
            return value
    return default


def _env_bool(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None or not str(value).strip():
        return default
    return str(value).strip().lower() not in {"0", "false", "no", "off"}

prime_emoji_environment()

token: str = _env(
    "BLEED_TOKEN",
    "MTUxMTQ1NjA0NDUwNzcyOTk5MQ.Gz-98R.ptCp8ALKvK4aceJyCT7P-Uo8pD68IrUP97XWos",
    aliases=("DISCORD_TOKEN", "TOKEN"),
)
_DEFAULT_OWNER_IDS: Final[tuple[int, ...]] = (
    197390603443634177,
    1449456965334859860,
)


class bot:
    prefix: str = _env("BLEED_PREFIX", ",")
    owners: tuple[int, ...] = _DEFAULT_OWNER_IDS
    support: str = _env("BLEED_SUPPORT_URL", "https://discord.gg/bleed")
    website: str = _env("BLEED_WEBSITE_URL", "https://bleed.bot")
    docs: str = _env("BLEED_DOCS_URL", "https://docs.bleed.bot")
    status: str = "online"
    activity_type: str = "none"
    activity_text: str = ""
    stream_url: str = ""


class emojis:
    approve: str = "<:embeds_approve:1511705992323272745>"
    warn: str = "<:embeds_warn:1511705997918343168>"
    deny: str = "<:embeds_deny:1511705993283633253>"
    loading: str = "<a:embeds_loading:1511705994823077988>"
    cooldown: str = "<:embeds_cooldown:1511705992755417129>"
    add: str = "<:embeds_add:1511705992469942292>"
    remove: str = "<:embeds_remove:1511705995850551357>"
    lastfm: str = "<:embeds_lastfm:1511705994458300618>"
    spotify: str = "<:embeds_spotify:1511705997130072235>"
    shazam: str = "<:embeds_shazam:1511705996555194368>"
    juul: str = "<:embeds_juul:1511705993795604490>"
    no_juul: str = "<:embeds_no_juul:1511705995653419008>"

    class paginator:
        previous: str = "<:paginator_previous:1511706003836633288>"
        next: str = "<:paginator_next:1511706003853279353>"
        navigate: str = "<:paginator_navigate:1511706003672928286>"
        cancel: str = "<:paginator_cancel:1511706003303825571>"

    class interface:
        lock: str = "<:interface_lock:1511706000007106721>"
        unlock: str = "<:interface_unlock:1511706000690774097>"
        ghost: str = "<:interface_ghost:1511705999264710756>"
        reveal: str = "<:interface_reveal:1511706000405692449>"
        claim: str = "<:interface_claim:1511705997897633954>"
        disconnect: str = "<:interface_disconnect:1511705999264972800>"
        activity: str = "<:interface_activity:1511705997889114273>"
        information: str = "<:interface_information:1511705999550185646>"
        increase: str = "<:interface_increase:1511705999348596767>"
        decrease: str = "<:interface_decrease:1511705998434500719>"


class color:
    neutral: int = 0xEAEAEA
    approve: int = 0xA8EA7B
    warn: int = 0xFDCF39
    deny: int = 0xFF0000
    base: int = 0x373737
    cooldown: int = 0x4EC3E8
    settings: int = 0x7289DA
    dark: int = 0x2B2D31
    shazam: int = 0x08A8FF
    voicemaster: int = 0x81A3A8
    unknown: int = 0x24243C

    @classmethod
    def update_base(cls, new_color: int) -> None:
        cls.base = new_color


class database:
    enabled: bool = _env_bool("DATABASE_ENABLED", True)
    dsn: str = _env(
        "DATABASE_DSN",
        "postgresql://postgres:sjnjmv7ai0wz7sw0@77.247.127.102:5432/postgres",
        aliases=("DATABASE_URL",),
    )


class redis:
    enabled: bool = _env_bool("REDIS_ENABLED", False)
    url: str = _env("REDIS_URL", "redis://127.0.0.1:6379/0")


class api:
    google_perspective: str = ""
    weather: str = ""
    fnbr: str = ""
    cloudconvert: str = ""
    clever: str = ""
    wolfram: str = ""
    osu: str = ""
    soundcloud: str = ""
    openrouter: str = ""
    serpapi: str = ""
    kraken: str = ""
    reshare: str = ""
    transcribe_url: str = "http://127.0.0.1:8789/"
    soundcloud_client_id: str = _env("SOUNDCLOUD_CLIENT_ID", "")
    spotify_client_id: str = _env(
        "SPOTIFY_CLIENT_ID",
        "78ecc85f9b5941a182fb265371d0976c",
    )
    spotify_client_secret: str = _env(
        "SPOTIFY_CLIENT_SECRET",
        "b48124cec1e2470383ccfc11599d7d7f",
    )
    spotify_redirect_uri: str = ""
    twitch_client_id: str = ""
    twitch_client_secret: str = ""
    llm: str = "gemini-2.5-flash-lite"

    class lastfm:
        key: str = _env("LASTFM_API_KEY", "")
        secret: str = _env("LASTFM_API_SECRET", "")
        keys: tuple[str, ...] = ()

    class twitter:
        bearer: str = ""
        api_key: str = ""
        api_secret: str = ""
        access_token: str = ""
        access_secret: str = ""

    class tiktok:
        session_id: str = ""

    class youtube:
        api_key: str = ""

    class instagram:
        cookies: list[dict] = []
        username: str = ""
        password: str = ""
        graphql: list[str] = [
            "https://www.instagram.com/graphql/query/?query_id=17888483320059182",
        ]
        post_query_hash: str = "2c4f4e870eeeee575e7210848365d854"

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
    enabled: bool = False
    lavalink_host: str = "127.0.0.1"
    lavalink_port: int = 2333
    lavalink_password: str = "youshallnotpass"
