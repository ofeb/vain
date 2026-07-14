from __future__ import annotations

import json
import re
from datetime import datetime
from io import BytesIO
from typing import Any
from urllib.parse import quote

import aiohttp
import discord
from PIL import Image

from core.tools.aesthetic import label_line, panel_embed

WEATHER_COLOR = 0xD4B8D0
DEFINE_COLOR = 0xBBA0D2
CASHAPP_GREEN = 0xA8D8A8
CASHAPP_FOOTER_ICON = "https://cash.app/favicon-32x32.png"
GITHUB_CREATED_ICON = "https://cdn.discordapp.com/emojis/843537056541442068.png"
UD_FOOTER_ICON = "https://www.urbandictionary.com/favicon-32x32.png"
GOOGLE_FOOTER_ICON = "https://www.gstatic.com/images/branding/product/2x/translate_24dp.png"
_CASHAPP_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    ),
}
_GITHUB_HEADERS = {
    "Accept": "application/vnd.github+json",
    "User-Agent": "Vain-bot",
}


def _title_case_weather(text: str) -> str:
    return " ".join(word.capitalize() for word in text.split())


async def fetch_weather(session: aiohttp.ClientSession, location: str) -> dict[str, Any]:
    from core.managers.values import api

    api_key = api.openweathermap.strip()
    if not api_key:
        raise ValueError("OpenWeatherMap API key is not configured.")
    params = {"q": location, "appid": api_key, "units": "metric"}
    async with session.get("https://api.openweathermap.org/data/2.5/weather", params=params) as resp:
        data = await resp.json(content_type=None)
        if resp.status != 200:
            message = data.get("message", "Could not fetch weather for that location.")
            raise ValueError(str(message))
        return data


def build_weather_embed(data: dict[str, Any], author: discord.User) -> discord.Embed:
    weather = data["weather"][0]
    main = data["main"]
    wind = data.get("wind", {})
    sys = data.get("sys", {})

    city = data["name"]
    country = sys.get("country", "")
    place = f"{city}, {country}" if country else city
    description = _title_case_weather(weather.get("description", "Unknown"))

    temp_c = float(main["temp"])
    temp_f = (temp_c * 9 / 5) + 32
    wind_mph = float(wind.get("speed", 0)) * 2.237
    humidity = int(main.get("humidity", 0))
    visibility_km = float(data.get("visibility", 0)) / 1000

    lines = [
        label_line("Temperature", f"{temp_c:.2f} °C / {temp_f:.2f} °F"),
        label_line("Wind", f"{wind_mph:.1f} mph"),
        label_line("Humidity", f"{humidity}%"),
    ]
    if sunrise := sys.get("sunrise"):
        lines.append(label_line("Sun Rise", f"<t:{int(sunrise)}:T>"))
    if sunset := sys.get("sunset"):
        lines.append(label_line("Sun Set", f"<t:{int(sunset)}:T>"))
    lines.append(label_line("Visibility", f"{visibility_km:.1f} km"))

    icon = weather.get("icon")
    return panel_embed(
        title=f"{description} in {place}",
        url=f"http://openweathermap.org/city/{data['id']}",
        color=WEATHER_COLOR,
        author=author.display_name,
        author_icon=author.display_avatar.url,
        lines=lines,
        timestamp=False,
        thumbnail=f"https://openweathermap.org/img/w/{icon}.png" if icon else None,
    )


async def fetch_dictionary(session: aiohttp.ClientSession, word: str) -> dict[str, Any]:
    url = f"https://api.dictionaryapi.dev/api/v2/entries/en/{word.strip().lower()}"
    async with session.get(url) as resp:
        if resp.status == 404:
            raise ValueError(f"No definition found for **{word}**.")
        if resp.status != 200:
            raise ValueError("Dictionary service is unavailable right now.")
        payload = await resp.json(content_type=None)
        if not payload:
            raise ValueError(f"No definition found for **{word}**.")
        return payload[0]


def build_define_embed(entry: dict[str, Any], author: discord.User) -> discord.Embed:
    word = entry.get("word", "unknown")
    phonetic = entry.get("phonetic") or ""
    if not phonetic:
        for phone in entry.get("phonetics", []):
            if text := phone.get("text"):
                phonetic = text
                break

    title = f"{word} ∙ {phonetic}" if phonetic else word
    description = "No definition available."
    for meaning in entry.get("meanings", []):
        for definition in meaning.get("definitions", []):
            if text := definition.get("definition"):
                description = text
                break
        if description != "No definition available.":
            break

    slug = word.replace(" ", "_")
    return panel_embed(
        title=title,
        url=f"https://en.wiktionary.org/wiki/{slug}",
        color=DEFINE_COLOR,
        author=author.display_name,
        author_icon=author.display_avatar.url,
        lines=[description[:4096]],
        timestamp=False,
    )


async def fetch_urban_dictionary(session: aiohttp.ClientSession, word: str) -> list[dict[str, Any]]:
    params = {"term": word.strip()}
    async with session.get("https://api.urbandictionary.com/v0/define", params=params) as resp:
        if resp.status != 200:
            raise ValueError("Urban Dictionary is unavailable right now.")
        payload = await resp.json(content_type=None)
        results = payload.get("list") or []
        if not results:
            raise ValueError(f"No Urban Dictionary results for **{word}**.")
        return results


def _clean_ud_text(text: str, *, limit: int = 900) -> str:
    cleaned = re.sub(r"\[([^\]]+)\]", r"\1", text or "")
    cleaned = cleaned.replace("\r\n", "\n").strip()
    if len(cleaned) > limit:
        cleaned = cleaned[: limit - 3].rstrip() + "..."
    return cleaned


def build_urban_embed(
    entry: dict[str, Any],
    *,
    author: discord.User,
    page: int,
    total: int,
) -> discord.Embed:
    word = entry.get("word", "unknown")
    definition = _clean_ud_text(entry.get("definition", ""))
    example = _clean_ud_text(entry.get("example", ""), limit=500)
    thumbs_up = int(entry.get("thumbs_up", 0))
    thumbs_down = int(entry.get("thumbs_down", 0))
    permalink = entry.get("permalink") or f"https://www.urbandictionary.com/define.php?term={word}"

    lines = [definition]
    if example:
        lines.append(label_line("Example", example))
    lines.append(label_line("Votes", f"👍 `{thumbs_up} / {thumbs_down}` 👎"))

    embed = panel_embed(
        title=word,
        url=permalink,
        color=DEFINE_COLOR,
        author=author.display_name,
        author_icon=author.display_avatar.url,
        lines=lines,
        timestamp=False,
    )
    embed.set_footer(
        text=f"-# Page {page}/{total} of Urban Dictionary Results",
        icon_url=UD_FOOTER_ICON,
    )
    return embed


def normalize_cashtag(username: str) -> str:
    tag = username.strip().lstrip("$").strip()
    if not tag or not re.fullmatch(r"[A-Za-z0-9._-]+", tag):
        raise ValueError("Provide a valid **Cash App** cashtag.")
    return tag


def _parse_profile_html(html: str) -> dict[str, Any]:
    match = re.search(r"var profile = (\{.*?\});", html, re.S)
    if not match:
        raise ValueError("Could not find that **Cash App** profile.")
    return json.loads(match.group(1))


def _hex_to_int(value: str) -> int:
    cleaned = value.strip().lstrip("#")
    if len(cleaned) == 3:
        cleaned = "".join(ch * 2 for ch in cleaned)
    return int(cleaned, 16)


def _is_vibrant(rgb: tuple[int, int, int]) -> bool:
    r, g, b = rgb
    mx, mn = max(r, g, b), min(r, g, b)
    if mx < 120:
        return False
    if mx - mn < 28:
        return False
    if mx and (mx - mn) / mx < 0.45:
        return False
    return True


def _dominant_rgb_from_image(data: bytes) -> tuple[int, int, int] | None:
    with Image.open(BytesIO(data)).convert("RGB") as img:
        img = img.resize((128, 128))
        quantized = img.quantize(colors=10, method=Image.Quantize.MEDIANCUT)
        palette = quantized.getpalette() or []
        counts = sorted(quantized.getcolors() or [], reverse=True)
        for _count, idx in counts:
            rgb = (palette[idx * 3], palette[idx * 3 + 1], palette[idx * 3 + 2])
            if _is_vibrant(rgb):
                return rgb
        if counts:
            idx = counts[0][1]
            return (palette[idx * 3], palette[idx * 3 + 1], palette[idx * 3 + 2])
    return None


async def _avatar_embed_color(
    session: aiohttp.ClientSession,
    profile: dict[str, Any],
) -> int:
    avatar = profile.get("avatar") or {}
    accent = str(avatar.get("accent_color") or "").strip()
    image_url = avatar.get("image_url")

    if image_url:
        try:
            async with session.get(image_url) as resp:
                if resp.status == 200:
                    rgb = _dominant_rgb_from_image(await resp.read())
                    if rgb and _is_vibrant(rgb):
                        return (rgb[0] << 16) + (rgb[1] << 8) + rgb[2]
        except Exception:
            pass

    if accent:
        try:
            return _hex_to_int(accent)
        except ValueError:
            pass

    return CASHAPP_GREEN


async def fetch_cashapp_profile(session: aiohttp.ClientSession, username: str) -> dict[str, Any]:
    tag = normalize_cashtag(username)
    url = f"https://cash.app/{tag}"
    async with session.get(url, headers=_CASHAPP_HEADERS) as resp:
        if resp.status == 404:
            raise ValueError(f"Could not find **${tag}** on Cash App.")
        if resp.status != 200:
            raise ValueError("Cash App is unavailable right now.")
        html = await resp.text()
    profile = _parse_profile_html(html)
    profile["_cashtag"] = tag
    profile["_embed_color"] = await _avatar_embed_color(session, profile)
    return profile


def build_cashapp_embed(profile: dict[str, Any], author: discord.User) -> discord.Embed:
    tag = profile["_cashtag"]
    display_name = profile.get("display_name") or tag
    formatted = profile.get("formatted_cashtag") or f"${tag}"
    if not formatted.startswith("$"):
        formatted = f"${formatted}"
    profile_url = f"https://cash.app/{tag}"
    avatar = profile.get("avatar") or {}
    image_url = avatar.get("image_url")

    embed = panel_embed(
        title=f"{display_name} (@{tag})",
        url=profile_url,
        color=profile.get("_embed_color", CASHAPP_GREEN),
        author=author.display_name,
        author_icon=author.display_avatar.url,
        lines=[f"Pay [{formatted}]({profile_url}) here."],
        timestamp=False,
        thumbnail=image_url,
    )
    embed.set_footer(text="-# CashApp", icon_url=CASHAPP_FOOTER_ICON)
    return embed


def _format_github_repo_date(iso: str) -> str:
    dt = datetime.fromisoformat(iso.replace("Z", "+00:00"))
    return dt.strftime("%m/%d/%y")


def _github_info_lines(user: dict[str, Any]) -> list[str]:
    lines: list[str] = []
    if bio := (user.get("bio") or "").strip():
        lines.append(bio)
    if email := (user.get("email") or "").strip():
        lines.append(f"📧 {email}")
    if company := (user.get("company") or "").strip():
        lines.append(f"🏢 [{company}](http://google.com/search?q={quote(company)})")
    if twitter := (user.get("twitter_username") or "").strip():
        lines.append(f"🐦 [@{twitter}](https://twitter.com/{twitter})")
    if location := (user.get("location") or "").strip():
        lines.append(f"🌎 [{location}](http://maps.google.com/?q={quote(location)})")
    return lines


def _format_github_repos(login: str, repos: list[dict[str, Any]], *, limit: int = 3) -> str:
    rows: list[str] = []
    for repo in repos[:limit]:
        name = repo.get("name", "repository")
        stars = int(repo.get("stargazers_count") or 0)
        updated = _format_github_repo_date(repo.get("updated_at") or repo.get("pushed_at") or "")
        url = repo.get("html_url") or f"https://github.com/{login}/{name}"
        rows.append(f"[`⭐ {stars}, {updated} {name}`]({url})")
    return "\n".join(rows)


async def fetch_github_profile(session: aiohttp.ClientSession, username: str) -> dict[str, Any]:
    login = username.strip().lstrip("@")
    if not login or not re.fullmatch(r"[A-Za-z0-9](?:[A-Za-z0-9-]{0,37}[A-Za-z0-9])?", login):
        raise ValueError("Provide a valid **GitHub** username.")

    headers = dict(_GITHUB_HEADERS)
    async with session.get(f"https://api.github.com/users/{login}", headers=headers) as resp:
        if resp.status == 404:
            raise ValueError(f"Could not find **{login}** on GitHub.")
        if resp.status != 200:
            raise ValueError("GitHub is unavailable right now.")
        user = await resp.json(content_type=None)

    async with session.get(
        f"https://api.github.com/users/{login}/repos",
        headers=headers,
        params={"sort": "updated", "per_page": 100},
    ) as resp:
        repos = await resp.json(content_type=None) if resp.status == 200 else []

    if not isinstance(repos, list):
        repos = []

    user["_repos"] = repos
    return user


def build_github_embed(user: dict[str, Any], author: discord.User) -> discord.Embed:
    login = user.get("login") or "unknown"
    display_name = (user.get("name") or login).strip()
    profile_url = user.get("html_url") or f"https://github.com/{login}"
    repos = user.get("_repos") or []
    public_repos = int(user.get("public_repos") or len(repos))

    lines: list[str] = []
    info_lines = _github_info_lines(user)
    if info_lines:
        lines.append(label_line("Information", "\n".join(info_lines)))
    if repos:
        lines.append(
            label_line(
                f"Repositories ({public_repos})",
                _format_github_repos(login, repos),
            )
        )

    embed = panel_embed(
        title=f"{display_name} (@{login})",
        url=profile_url,
        author=author.display_name,
        author_icon=author.display_avatar.url,
        lines=lines,
        timestamp=False,
        thumbnail=user.get("avatar_url"),
    )
    if created := user.get("created_at"):
        embed.timestamp = datetime.fromisoformat(created.replace("Z", "+00:00"))
    embed.set_footer(text="-# Created on", icon_url=GITHUB_CREATED_ICON)
    return embed
