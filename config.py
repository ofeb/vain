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
    approve: str = default_emoji("approve", "<:approve_new:1526186163457490974>")
    warn: str = default_emoji("warn", "<:warning:1526186228561477642>")
    deny: str = default_emoji("deny", "<:deny:1526186193971052634>")
    loading: str = default_emoji("loading", "<a:ctx_loading:1517184450595651765>")
    cooldown: str = default_emoji("cooldown", "<:cooldown:1525919040776835075>")
    add: str = default_emoji("add", "<:ctx_add:1517184446556537104>")
    remove: str = default_emoji("remove", "<:ctx_remove:1517184460876026018>")
    lastfm: str = default_emoji("lastfm", "<:ctx_lastfm:1517184449891139829>")
    spotify: str = default_emoji("spotify", "<:ctx_spotify:1517184462197362821>")
    shazam: str = default_emoji("shazam", "<:ctx_shazam:1517184461538590810>")
    juul: str = default_emoji("juul", "<:ctx_juul:1517184449429766266>")
    no_juul: str = default_emoji("no_juul", "<:ctx_no_juul:1517184459827576855>")

    
    human: str = "<:human:1527022590160404782>"
    likes: str = "<:likes:1527023309915558052>"
    comments: str = "<:comments:1527023647917740132>"
    saves: str = "<:saves:1527023807015944243>"
    music: str = "<:music:1527022832121413772>"
    region: str = "<:region:1527024322558951431>"
    repost: str = "<:reposts:1527024036276867167>"
    reposts: str = "<:reposts:1527024036276867167>"

    class paginator:
        previous: str = default_emoji("paginator_previous", "<:paginator_previous:1517184479293079745>")
        next: str = default_emoji("paginator_next", "<:paginator_next:1517184477816684565>")
        navigate: str = default_emoji("paginator_navigate", "<:paginator_navigate:1517184477678403867>")
        cancel: str = default_emoji("paginator_cancel", "<:paginator_cancel:1517184476306870386>")
        search: str = default_emoji("paginator_navigate", "<:paginator_navigate:1517184477678403867>")
        delete: str = default_emoji("paginator_cancel", "<:paginator_cancel:1517184476306870386>")
        left: str = "⬅️"
        right: str = "➡️"

    class interface:
        lock: str = default_emoji("interface_lock", "<:interface_lock:1517184482707243261>")
        unlock: str = default_emoji("interface_unlock", "<:interface_unlock:1517184483944698076>")
        ghost: str = default_emoji("interface_ghost", "<:interface_ghost:1517184480513753308>")
        reveal: str = default_emoji("interface_reveal", "<:interface_reveal:1517184483378335937>")
        claim: str = default_emoji("interface_claim", "<:interface_claim:1517184477225553920>")
        disconnect: str = default_emoji("interface_disconnect", "<:interface_disconnect:1517184479767036066>")
        activity: str = default_emoji("interface_activity", "<:interface_activity:1517184476097024160>")
        information: str = default_emoji("interface_information", "<:interface_information:1517184481830899903>")
        increase: str = default_emoji("interface_increase", "<:interface_increase:1517184481214206022>")
        decrease: str = default_emoji("interface_decrease", "<:interface_decrease:1517184478689235134>")

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
    dsn: str = "postgresql://bleed_user:bleed@localhost:5432/bleed"


class redis:
    enabled: bool = False
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
