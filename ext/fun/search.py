from __future__ import annotations

import re
from html import unescape
from typing import Any
from urllib.parse import parse_qs, unquote, urlparse

import aiohttp
import discord

DDG_ICON = "https://bleed.bot/img/duckduckgo.png"
_DDG_HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
_RESULTS_PER_PAGE = 3
_FETCH_LIMIT = 12


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
