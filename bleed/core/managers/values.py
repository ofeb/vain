from __future__ import annotations

from pathlib import Path
from typing import Final

token = "MTUxMTQ1NjA0NDUwNzcyOTk5MQ.GWsqgz.7rmtleiKikC8L5ly62NmfgcO7dCgyuy1qlH7nQ"

class bot:
    prefix = ";"
    owners = (1449456965334859860, 197390603443634177)
    support = "https://discord.gg/tornbio"
    status = "online"
    activity_type = "none"
    activity_text = ""
    stream_url = ""

class emojis:
    approve = "<:embeds_approve:1511705992323272745>"
    warn = "<:embeds_warn:1511705997918343168>"
    deny = "<:embeds_deny:1511705993283633253>"
    loading = "<a:embeds_loading:1511705994823077988>"
    cooldown = "<:embeds_cooldown:1511705992755417129>"
    add = "<:embeds_add:1511705992469942292>"
    remove = "<:embeds_remove:1511705995850551357>"
    lastfm = "<:embeds_lastfm:1511705994458300618>"
    spotify = "<:embeds_spotify:1511705997130072235>"
    shazam = "<:embeds_shazam:1511705996555194368>"
    juul = "<:embeds_juul:1511705993795604490>"
    no_juul = "<:embeds_no_juul:1511705995653419008>"

    class paginator:
        previous = "<:paginator_previous:1511706003836633288>"
        next = "<:paginator_next:1511706003853279353>"
        navigate = "<:paginator_navigate:1511706003672928286>"
        cancel = "<:paginator_cancel:1511706003303825571>"

    class interface:
        lock = "<:interface_lock:1511706000007106721>"
        unlock = "<:interface_unlock:1511706000690774097>"
        ghost = "<:interface_ghost:1511705999264710756>"
        reveal = "<:interface_reveal:1511706000405692449>"
        claim = "<:interface_claim:1511705997897633954>"
        disconnect = "<:interface_disconnect:1511705999264972800>"
        activity = "<:interface_activity:1511705997889114273>"
        information = "<:interface_information:1511705999550185646>"
        increase = "<:interface_increase:1511705999348596767>"
        decrease = "<:interface_decrease:1511705998434500719>"

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
    dsn = ""

class redis:
    url = "redis://127.0.0.1:6379"
    enabled = False

class api:
    gemini = "AQ.Ab8RN6KgI2bxOLtU7XQFkqJ8Q_XPtlEmExj4LPruvSlOQtP6WA"
    llm = "gemini-2.5-flash-lite"
    ocr = "K85711694388957"
    aiproject = "projects/268591218263"
    google_perspective = ""
    weather = ""
    jeyy = "64P38CPI6SQ36CHJ6GO34CHP6CP3AE8.CDQN4P8.5pFC0ci9fCKDNICIzIzMlA"
    fnbr = "811d14f2-ad01-4005-bc82-7f660f1ec7b4"
    cloudconvert = "eyJ0eXAiOiJKV1QiLCJhbGciOiJSUzI1NiJ9.eyJhdWQiOiIxIiwianRpIjoiOWE3NWNlMzIwY2M4Nzg5NWM3NmE5YzQ4NWYwNTY0MmUwNTg1MmI5OWNlOWYxN2QwMWU1MGEyMDEzMDJmNTAzYjY5NjQ2YTY1ZDI4MThiNzkiLCJpYXQiOjE3NDc0MzgyMDkuNzc0NDgyLCJuYmYiOjE3NDc0MzgyMDkuNzc0NDg0LCJleHAiOjQ5MDMxMTE4MDkuNzcwMzQsInN1YiI6IjcxOTA1ODMzIiwic2NvcGVzIjpbInVzZXIucmVhZCIsInVzZXIud3JpdGUiLCJ0YXNrLnJlYWQiLCJ0YXNrLndyaXRlIiwid2ViaG9vay5yZWFkIiwid2ViaG9vay53cml0ZSIsInByZXNldC5yZWFkIiwicHJlc2V0LndyaXRlIl19.qNeJ_jvIaPq_tIOFq6GYDMkzThlnwxZEsqa_Gk2A_AvuUfmLXgLIbTn8xkgjL6pt_fVi_ImXpDXMR6_EIAzjmWU9xfuOSABdFQ6ULD5RJhz8iyjjxZ1PoQfwblWfYQfDiPmkvfTAGWEtZNb_Drryp5PiEWNC5dbluGCbA9ZJSWZB1AuLotu8hhmvvnQGWnEurKro9ptFpBibLNFT7XRd0KkN_-y-MOdXvGZbNr05tIKoiNvdsl2jdEXR9VADSESpWykUOmDoyW3PUDD-QcVagq-z7zbnliAnSpsJc-G47oOUSRtsnlYvvRyWB5vmqLnwS0F5czqsQI-ULuC_50nAItZRgvyh3bfaMIE8Y245JmO4DRhykG5ZRX9g__hHhi8NSNKi3kiVm0LWZNKdGXVgRi6sGaMsIKEJ8eLwvSsjEIqWEPeseMnlWS4IdT4HBC-qFmox04t5AlV2AaPVSf4ed9DTV3DjVg4ldct7MqMk-jAWGD7kh6QbB9aI596wyYOyCQGIdZ2MVpfHGBJIs7fvbHbE-g2sYOQ2J3v-Qmd93-ilJU__OTDj4uwbifHs6NIfP5JS49KgpwwPskQzCcp6g5Wev_e2OAP4ESWoSMO6B9xPYBicTkjgAC7caUIbVL59_mLqRx0nfWmshONRsoZdTZ_hRaLQgBXPeMFuggeIF8g"
    clever = ""
    wolfram = ""
    osu = ""
    soundcloud = ""
    openrouter = "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"
    serpapi = "a8621740d4458f15ad3348c54454fb711c54df4dab6b2a53d003a3b17778ca45"
    kraken = ""
    reshare = "95168cb4fe93ec7d78793cd7b8544b7fc2178149"
    transcribe_url = "http://127.0.0.1:8789/"
    soundcloud_client_id = "Fs1xmKNbd3b0EiU1o1MHY4KfC41SVpjS"
    spotify_client_id = ""
    spotify_client_secret = ""
    spotify_redirect_uri = ""
    twitch_client_id = ""
    twitch_client_secret = ""

    class lastfm:
        key = "dcf2076953c014eb54760b3355e1b8dd"
        secret = "20665e5f1beef54fdd8a635f0e7618f8"
        keys = ["dcf2076953c014eb54760b3355e1b8dd"]

    class instagram:
        cookies = [
            {
                "ds_user_id": "75758144693",
                "sessionid": "75758144693%3ARn1mzuF9D8twLL%3A21%3AAYgNYUqCZwbQlSxYravzXBo35vJC5V4MHk-KWaZPzA",
            },
        ]
        username = "ybnafim"
        password = "Nafim@2009"
        graphql = ["https://www.instagram.com/graphql/query/?query_id=17888483320059182"]
        post_query_hash = "2c4f4e870eeeee575e7210848365d854"

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
    enabled = False
    lavalink_host = "127.0.0.1"
    lavalink_port = 2333
    lavalink_password = "youshallnotpass"

root: Final[Path] = Path(__file__).resolve().parents[2]
