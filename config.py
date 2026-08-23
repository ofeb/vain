from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Final

from core.managers.app_emojis import default_emoji, prime_emoji_environment

repo_root: Final[Path] = Path(__file__).resolve().parent
root: Final[Path] = repo_root
storage: Final[Path] = root / "core" / "storage"

prime_emoji_environment()




class Bot:
    prefix: str = ","
    owners: list[int] = [1137513168965476352, 1449456965334859860, 1480279800701784074, 1276212418711650411, 1269433308945711135, 368896789438529538]
    token: str = "MTQxMTQwOTM5MjMzNDY3MjAxMw.GUte_c.SoJin1xjFeAzcnbIlAGy5psC0WQPbF6dqbdxyo"
    support: str = "https://discord.gg/vains"
    website: str = "https://vain.bot"
    docs: str = "https://docs.vain.bot"
    status: str = "online"
    activity_type: str = "none"
    activity_text: str = ""
    stream_url: str = ""



bot = Bot


class emojis:
    approve: str = default_emoji("approve", "<:approve:1540866276313014415>")
    warn: str = default_emoji("warn", "<:warning:1540866713740906558>")
    deny: str = default_emoji("deny", "<:deny:1540868770975719464>")
    loading: str = default_emoji("loading", "<a:embeds_loading:1511705994823077988>")
    cooldown: str = default_emoji("cooldown", "<:cooldown:1525919040776835075>")
    add: str = "<:embeds_add:1511705992469942292>"
    remove: str = "<:embeds_remove:1511705995850551357>"
    lastfm: str = "<:embeds_lastfm:1511705994458300618>"
    spotify: str = "<:embeds_spotify:1511705997130072235>"
    shazam: str = "<:embeds_shazam:1511705996555194368>"
    juul: str = "<:embeds_juul:1511705993795604490>"
    no_juul: str = "<:embeds_no_juul:1511705995653419008>"

    
    human: str = "<:human:1527022590160404782>"
    likes: str = "<:likes:1527023309915558052>"
    comments: str = "<:comments:1527023647917740132>"
    saves: str = "<:saves:1527023807015944243>"
    music: str = "<:music:1527022832121413772>"
    region: str = "<:region:1527024322558951431>"
    repost: str = "<:reposts:1527024036276867167>"
    reposts: str = "<:reposts:1527024036276867167>"

    class paginator:
        previous: str = "<:paginator_previous:1511706003836633288>"
        next: str = "<:paginator_next:1511706003853279353>"
        navigate: str = "<:search:1479154501066817600>"
        cancel: str = "<:delete:1535040504516055191>"
        search: str = "<:search:1479154501066817600>"
        delete: str = "<:delete:1535040504516055191>"
        left: str = "⬅️"
        right: str = "➡️"

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

    class ticket:
        claim: str = default_emoji("ticket_claim", "<:claim:1535044178898325595>")
        close: str = default_emoji("ticket_close", "<:delete:1535040504516055191>")
        transcript: str = default_emoji(
            "ticket_transcript", "<:transcript:1535045337117491340>"
        )
        open: str = default_emoji("ticket_open", "<:open:1535046932487999540>")


class color:
    neutral: int = 0x2A2B2F
    approve: int = 0xA8D8A8
    warn: int = 0xF5D76E
    deny: int = 0xE07A7A
    base: int = 0xE1D2DE
    cooldown: int = 0xC9B3C4
    settings: int = 0xE1D2DE
    dark: int = 0xA890A4
    shazam: int = 0xD4C0D0
    voicemaster: int = 0xDCC8D6
    unknown: int = 0xC8B8C4

    @classmethod
    def update_base(cls, new_color: int) -> None:
        cls.base = new_color


class database:
    enabled: bool = True
    dsn: str = "postgresql://postgres:astral2026@localhost:5432/vain"


class redis:
    enabled: bool = True
    url: str = "redis://127.0.0.1:6379/0"


class api:
    google_perspective: str = ""
    openweathermap: str = "caa6d1f353a1f24663e101a62cbdc148"
    vain_rest: str = (
        "sk-15fa10dc8354be314cf148002cfd1cc83443f6c26d6af77b1fb65aaf63276da6"
    )
    fnbr: str = ""
    cloudconvert: str = ""
    clever: str = ""
    wolfram: str = ""
    osu: str = ""
    soundcloud: str = ""
    openrouter: str = ""
    serpapi: str = ""
    kraken: str = ""
    transcribe_url: str = "http://127.0.0.1:8789/"
    soundcloud_client_id: str = ""
    spotify_client_id: str = "78ecc85f9b5941a182fb265371d0976c"
    spotify_client_secret: str = "b48124cec1e2470383ccfc11599d7d7f"
    spotify_redirect_uri: str = ""
    twitch_client_id: str = ""
    twitch_client_secret: str = ""
    llm: str = "gemini-2.5-flash-lite"
    gemini_api_key: str = "AQ.Ab8RN6KgI2bxOLtU7XQFkqJ8Q_XPtlEmExj4LPruvSlOQtP6WA"
    groq_api_key: str = "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"
    gemini_model: str = "gemini-2.5-flash-lite"
    gemini_project: str = "projects/268591218263"
    ocr_space_api_key: str = "K85711694388957"

    social_base: str = "https://scl.guilt.bot"
    social_cf_client_id: str = "e263d488792e91ef3c26e324b4f8c1da.access"
    social_cf_client_secret: str = (
        "579b6bd1c5a0ecff20a58a7e1accac28fc286d4865e96314e5bb657d5c99c8c4"
    )

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
        COOKIES: list[dict[str, str]] = []
        USERNAME: str = ""
        PASSWORD: str = ""
        GRAPHQL: list[str] = [
            "https://www.instagram.com/graphql/query/?query_id=17888483320059182",
        ]
        POST_QUERY_HASH: str = "2c4f4e870eeeee575e7210848365d854"

        cookies = COOKIES
        username = USERNAME
        password = PASSWORD
        graphql = GRAPHQL
        post_query_hash = POST_QUERY_HASH

        @classmethod
        def cookie_entries(cls) -> list[dict[str, str]]:
            return list(getattr(cls, "COOKIES", None) or getattr(cls, "cookies", None) or [])

        @classmethod
        def cookie_header(cls, *, index: int = 0) -> str:
            
            entries = cls.cookie_entries()
            if not entries:
                return ""
            entry = entries[index % len(entries)]
            parts: list[str] = []
            for key in ("ds_user_id", "sessionid", "csrftoken"):
                val = str(entry.get(key, "")).strip()
                if val:
                    parts.append(f"{key}={val}")
            return "; ".join(parts)


class music:
    host: str = "127.0.0.1"
    port: int = 2009
    password: str = "youshallnotpass"
    search_sources: tuple[str, ...] = (
        "ytmsearch",
        "ytsearch",
        "scsearch",
    )

    @classmethod
    def identifier(cls) -> str:
        raw = f"vain:{cls.host}:{cls.port}:{cls.password}".encode()
        return hashlib.sha256(raw).hexdigest()[:16]


music_enabled: bool = True


class lastfm_color:
    value: str = "#c1272d"


class lastfm_crown:
    min_plays: int = 5


class lastfm_callback:
    url: str = ""
