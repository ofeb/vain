from __future__ import annotations

import re
from html import unescape
from typing import Any
from urllib.parse import parse_qs, unquote, urlparse

import aiohttp
import discord

DDG_ICON = "https://vain.bot/img/duckduckgo.png"
GOOGLE_ICON = "https://vain.bot/img/google.png"
_DDG_HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
_RESULTS_PER_PAGE = 3
_FETCH_LIMIT = 12
_IMAGE_LIMIT = 50


def _unwrap_ddg_url(url: str) -> str:
    if "duckduckgo.com/l/" not in url:
        return url
    parsed = urlparse(url)
    uddg = parse_qs(parsed.query).get("uddg", [None])[0]
    return unquote(uddg) if uddg else url


def _parse_ddg_html(html: str) -> list[dict[str, str]]:
    results: list[dict[str, str]] = []
    blocks = re.split(r'<div class="result results_links[^"]*">', html)
    for block in blocks[1:]:
        title_match = re.search(
            r'class="result__a"[^>]*href="([^"]+)"[^>]*>(.*?)</a>',
            block,
            re.S,
        )
        if not title_match:
            continue
        raw_url = title_match.group(1).replace("&amp;", "&")
        if raw_url.startswith("//"):
            raw_url = "https:" + raw_url
        url = _unwrap_ddg_url(raw_url)
        title = re.sub(r"<[^>]+>", "", title_match.group(2))
        title = unescape(title).strip()
        snippet_match = re.search(
            r'class="result__snippet"[^>]*>(.*?)</(?:a|td|div)>',
            block,
            re.S,
        )
        snippet = ""
        if snippet_match:
            snippet = re.sub(r"<[^>]+>", "", snippet_match.group(1))
            snippet = unescape(snippet).strip()
        if title and url:
            results.append({"title": title, "url": url, "snippet": snippet})
    return results


async def fetch_ddg_results(session: aiohttp.ClientSession, query: str) -> list[dict[str, str]]:
    results: list[dict[str, str]] = []
    offset = 0
    while len(results) < _FETCH_LIMIT:
        params: dict[str, Any] = {"q": query}
        if offset:
            params["s"] = str(offset)
        async with session.post(
            "https://html.duckduckgo.com/html/",
            data=params,
            headers=_DDG_HEADERS,
        ) as resp:
            if resp.status != 200:
                break
            batch = _parse_ddg_html(await resp.text())
        if not batch:
            break
        results.extend(batch)
        offset += len(batch)
        if len(batch) < 10:
            break
    return results[:_FETCH_LIMIT]


def build_ddg_search_pages(
    results: list[dict[str, str]],
    author: discord.User,
) -> list[discord.Embed]:
    if not results:
        return []
    total_pages = max(1, (len(results) + _RESULTS_PER_PAGE - 1) // _RESULTS_PER_PAGE)
    pages: list[discord.Embed] = []
    for index in range(0, len(results), _RESULTS_PER_PAGE):
        chunk = results[index : index + _RESULTS_PER_PAGE]
        page_num = index // _RESULTS_PER_PAGE + 1
        embed = discord.Embed(title="Search Results")
        embed.set_author(name=author.display_name, icon_url=author.display_avatar.url)
        for item in chunk:
            snippet = item["snippet"] or "No description available."
            embed.add_field(
                name=f"**{item['title']}**",
                value=f"**{item['url']}**\n{snippet[:900]}",
                inline=False,
            )
        embed.set_footer(
            text=f"Page {page_num}/{total_pages} of Duck Duck Go Results",
            icon_url=DDG_ICON,
        )
        pages.append(embed)
    return pages


def _parse_bing_images(html: str) -> list[str]:
    urls = re.findall(r'murl&quot;:&quot;(https?://[^&]+?)&quot;', html)
    cleaned: list[str] = []
    seen: set[str] = set()
    for url in urls:
        url = unescape(url)
        if url not in seen:
            seen.add(url)
            cleaned.append(url)
    return cleaned


async def _fetch_ddg_images(session: aiohttp.ClientSession, query: str, limit: int) -> list[str]:
    async with session.get(
        "https://duckduckgo.com/",
        params={"q": query, "iax": "images", "ia": "images"},
        headers=_DDG_HEADERS,
    ) as resp:
        if resp.status != 200:
            return []
        html = await resp.text()
    match = re.search(r"vqd=['\"]([^'\"]+)['\"]", html)
    if not match:
        return []

    images: list[str] = []
    vqd = match.group(1)
    for page in range(1, 6):
        async with session.get(
            "https://duckduckgo.com/i.js",
            params={
                "l": "us-en",
                "o": "json",
                "q": query,
                "vqd": vqd,
                "f": ",,,",
                "p": str(page),
            },
            headers={**_DDG_HEADERS, "Referer": "https://duckduckgo.com/"},
        ) as resp:
            if resp.status != 200:
                break
            try:
                data = await resp.json(content_type=None)
            except aiohttp.ContentTypeError:
                break
        batch = [item["image"] for item in data.get("results", []) if item.get("image")]
        if not batch:
            break
        images.extend(batch)
        if len(images) >= limit or len(batch) < 20:
            break
    return images[:limit]


async def _fetch_bing_images(session: aiohttp.ClientSession, query: str, limit: int) -> list[str]:
    images: list[str] = []
    seen: set[str] = set()
    offset = 0
    while len(images) < limit:
        async with session.get(
            "https://www.bing.com/images/search",
            params={"q": query, "first": offset + 1, "count": 35},
            headers=_DDG_HEADERS,
        ) as resp:
            if resp.status != 200:
                break
            batch = _parse_bing_images(await resp.text())
        added = 0
        for url in batch:
            if url in seen:
                continue
            seen.add(url)
            images.append(url)
            added += 1
            if len(images) >= limit:
                break
        if not added:
            break
        offset += 35
    return images[:limit]


async def fetch_image_results(session: aiohttp.ClientSession, query: str, *, limit: int = _IMAGE_LIMIT) -> list[str]:
    images = await _fetch_ddg_images(session, query, limit)
    if len(images) < limit:
        remaining = limit - len(images)
        bing_images = await _fetch_bing_images(session, query, remaining)
        seen = set(images)
        for url in bing_images:
            if url not in seen:
                images.append(url)
                seen.add(url)
            if len(images) >= limit:
                break
    return images[:limit]


def build_image_search_pages(
    images: list[str],
    author: discord.User,
    *,
    query: str,
    source: str,
) -> list[discord.Embed]:
    if not images:
        return []
    total_pages = len(images)
    if source == "google":
        footer_label = "Google Results"
        icon_url = GOOGLE_ICON
    else:
        footer_label = "Duck Duck Go Results"
        icon_url = DDG_ICON
    pages: list[discord.Embed] = []
    for index, image_url in enumerate(images, start=1):
        embed = discord.Embed(title="Image Results", description=f"**{query}**")
        embed.set_author(name=author.display_name, icon_url=author.display_avatar.url)
        embed.set_image(url=image_url)
        embed.set_footer(text=f"Page {index}/{total_pages} of {footer_label}", icon_url=icon_url)
        pages.append(embed)
    return pages
