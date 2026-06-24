from __future__ import annotations

import re
from typing import Any

import aiohttp
import discord

from core.managers.values import api

WEATHER_COLOR = 0x3498DB
DEFINE_COLOR = 0xE8E8E6
UD_FOOTER_ICON = "https://www.urbandictionary.com/favicon-32x32.png"
GOOGLE_FOOTER_ICON = "https://www.gstatic.com/images/branding/product/2x/translate_24dp.png"


def _title_case_weather(text: str) -> str:
    return " ".join(word.capitalize() for word in text.split())


async def fetch_weather(session: aiohttp.ClientSession, location: str) -> dict[str, Any]:
    if not api.openweathermap:
        raise ValueError("OpenWeatherMap API key is not configured.")
    params = {"q": location, "appid": api.openweathermap, "units": "metric"}
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

    embed = discord.Embed(
        title=f"{description} in {place}",
        url=f"http://openweathermap.org/city/{data['id']}",
        color=WEATHER_COLOR,
    )
    embed.set_author(name=author.display_name, icon_url=author.display_avatar.url)
    icon = weather.get("icon")
    if icon:
        embed.set_thumbnail(url=f"https://openweathermap.org/img/w/{icon}.png")

    embed.add_field(name="**Temperature**", value=f"{temp_c:.2f} °C / {temp_f:.2f} °F", inline=True)
    embed.add_field(name="**Wind**", value=f"{wind_mph:.1f} mph", inline=True)
    embed.add_field(name="**Humidity**", value=f"{humidity}%", inline=True)
    if sunrise := sys.get("sunrise"):
        embed.add_field(name="**Sun Rise**", value=f"<t:{int(sunrise)}:T>", inline=True)
    if sunset := sys.get("sunset"):
        embed.add_field(name="**Sun Set**", value=f"<t:{int(sunset)}:T>", inline=True)
    embed.add_field(name="**Visibility**", value=f"{visibility_km:.1f} km", inline=True)
    return embed


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
    embed = discord.Embed(
        title=title,
        description=description[:4096],
        url=f"https://en.wiktionary.org/wiki/{slug}",
        color=DEFINE_COLOR,
    )
    embed.set_author(name=author.display_name, icon_url=author.display_avatar.url)
    return embed


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

    embed = discord.Embed(
        title=word,
        description=definition,
        url=permalink,
        color=DEFINE_COLOR,
    )
    embed.set_author(name=author.display_name, icon_url=author.display_avatar.url)
    if example:
        embed.add_field(name="**Example**", value=example, inline=False)
    embed.add_field(name="**Votes**", value=f"👍 `{thumbs_up} / {thumbs_down}` 👎", inline=False)
    embed.set_footer(
        text=f"Page {page}/{total} of Urban Dictionary Results",
        icon_url=UD_FOOTER_ICON,
    )
    return embed
