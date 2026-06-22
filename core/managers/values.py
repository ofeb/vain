from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Final

from .app_emojis import prime_emoji_environment

repo_root: Final[Path] = Path(__file__).resolve().parents[2]
root: Final[Path] = repo_root

prime_emoji_environment()

token: str = "MTUxMTQ1NjA0NDUwNzcyOTk5MQ.Gz-98R.ptCp8ALKvK4aceJyCT7P-Uo8pD68IrUP97XWos"
_DEFAULT_OWNER_IDS: Final[tuple[int, ...]] = (
    197390603443634177,
    1449456965334859860,
    1480279800701784074,
)


class bot:
    prefix: str = ","
    owners: tuple[int, ...] = _DEFAULT_OWNER_IDS
    support: str = "https://discord.gg/percsbio"
    website: str = "https://percs.cc"
    docs: str = "https://docs.bleed.bot"
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
    enabled: bool = True
    dsn: str = "postgresql://bleed_user:bleed@localhost:5432/bleed"


class redis:
    enabled: bool = False
    url: str = "redis://127.0.0.1:6379/0"


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
    soundcloud_client_id: str = ""
    spotify_client_id: str = "78ecc85f9b5941a182fb265371d0976c"
    spotify_client_secret: str = "b48124cec1e2470383ccfc11599d7d7f"
    spotify_redirect_uri: str = ""
    twitch_client_id: str = ""
    twitch_client_secret: str = ""
    llm: str = "gemini-2.5-flash-lite"

    class lastfm:
        key: str = ""
        secret: str = ""
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
    host: str = "127.0.0.1"
    port: int = 2009
    password: str = "youshallnotpass"
    search_sources: tuple[str, ...] = (
        "spsearch",
        "dzsearch",
        "scsearch",
        "ytsearch",
    )

    @classmethod
    def identifier(cls) -> str:
        raw = f"bleed:{cls.host}:{cls.port}:{cls.password}".encode()
        return hashlib.sha256(raw).hexdigest()[:16]


music_enabled: bool = True


class lastfm_color:
    value: str = "#c1272d"


class lastfm_crown:
    min_plays: int = 5


class lastfm_callback:
    url: str = ""
