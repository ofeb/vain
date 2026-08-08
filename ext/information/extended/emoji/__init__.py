from __future__ import annotations

import re
from pathlib import PurePosixPath
from urllib.parse import unquote, urlparse

import aiohttp
import discord
from discord.ext.commands import group

from core.discord.package import Package
from core.discord.views.embed import c2
from core.managers.permissions import has_permissions

_EMOJI_RE = re.compile(r"<(a)?:([A-Za-z0-9_]{2,32}):(\d{15,25})>")
_NAME_RE = re.compile(r"^[A-Za-z0-9_]{2,32}$")


def _sanitize_name(raw: str | None, *, fallback: str = "emoji") -> str:
    text = (raw or "").strip()
    
    if "." in text and "/" not in text and "\\" not in text:
        text = text.rsplit(".", 1)[0]
    text = re.sub(r"[^A-Za-z0-9_]+", "_", text).strip("_")
    if len(text) < 2:
        text = fallback
    return text[:32]


def _name_from_url(url: str) -> str:
    try:
        path = unquote(urlparse(url).path or "")
        leaf = PurePosixPath(path).name
        return _sanitize_name(leaf, fallback="emoji")
    except Exception:
        return "emoji"


def _parse_partial_emoji(token: str) -> discord.PartialEmoji | None:
    token = (token or "").strip()
    if not token:
        return None
    try:
        pe = discord.PartialEmoji.from_str(token)
        if pe and pe.id:
            return pe
    except Exception:
        pass
    m = _EMOJI_RE.fullmatch(token)
    if m:
        return discord.PartialEmoji(
            animated=bool(m.group(1)),
            name=m.group(2),
            id=int(m.group(3)),
        )
    return None


async def _download(session: aiohttp.ClientSession, url: str) -> bytes | None:
    try:
        async with session.get(url, timeout=aiohttp.ClientTimeout(total=25)) as resp:
            if resp.status != 200:
                return None
            data = await resp.read()
            if not data or len(data) > 256 * 1024:
                return None
            return data
    except Exception:
        return None


class Emoji(Package):
    """emoji management"""

    @group(
        name="emoji",
        description="Manage server emotes",
        invoke_without_command=True,
    )
    async def emoji(self, ctx):
        """emoji management"""
        return await ctx.send_help(ctx.command)

    @emoji.command(
        name="enlarge",
        aliases=["large", "big", "show"],
        description="Returns a large version of a custom emoji",
    )
    async def emoji_enlarge(self, ctx, *, emoji: str | None = None):
        """Show a large custom emoji — `,emoji enlarge <:name:id>`."""
        token = (emoji or "").strip()
        if not token:
            return await ctx.warn("that is **not** a **valid emoji**")

        
        token = token.split()[0]
        custom = _parse_partial_emoji(token)
        if custom is None or not custom.id or not custom.url:
            return await ctx.warn("that is **not** a **valid emoji**")

        e = c2(message=str(custom), timestamp=False)
        e.set_image(url=str(custom.url))
        await ctx.send(embed=e)

    @emoji.command(
        name="removemany",
        description="Bulk remove emotes from the current server",
    )
    @has_permissions(manage_expressions=True)
    async def emoji_removemany(self, ctx, *, emotes: str):
        """bulk remove emotes"""
        emoji_list = emotes.split()
        removed = 0
        failed = 0

        for emoji_str in emoji_list:
            try:
                custom_emoji = _parse_partial_emoji(emoji_str)
                if custom_emoji is None:
                    failed += 1
                    continue
                emoji_obj = discord.utils.get(ctx.guild.emojis, id=custom_emoji.id)
                if emoji_obj is None:
                    emoji_obj = discord.utils.get(ctx.guild.emojis, name=custom_emoji.name)
                if emoji_obj:
                    await emoji_obj.delete()
                    removed += 1
                else:
                    failed += 1
            except Exception:
                failed += 1

        await ctx.success(f"Removed {removed} emotes, failed {failed}")

    @emoji.command(
        name="removeduplicates",
        description="Remove duplicates of emotes",
    )
    @has_permissions(manage_expressions=True)
    async def emoji_removeduplicates(self, ctx):
        """remove duplicate emotes"""
        seen: set[str] = set()
        removed = 0

        for emoji in ctx.guild.emojis:
            if emoji.name in seen:
                try:
                    await emoji.delete()
                    removed += 1
                except Exception:
                    pass
            else:
                seen.add(emoji.name)

        await ctx.success(f"Removed {removed} duplicate emotes")

    @emoji.command(
        name="remove",
        description="Removes emote from server",
    )
    @has_permissions(manage_expressions=True)
    async def emoji_remove(self, ctx, emoji: str):
        """remove emote"""
        try:
            custom_emoji = _parse_partial_emoji(emoji)
            if custom_emoji is None:
                return await ctx.warn("Provide a custom emoji to remove")
            emoji_obj = discord.utils.get(ctx.guild.emojis, id=custom_emoji.id)
            if emoji_obj is None:
                emoji_obj = discord.utils.get(ctx.guild.emojis, name=custom_emoji.name)
            if emoji_obj:
                await emoji_obj.delete()
                await ctx.success(f"Removed emote `{emoji_obj.name}`")
            else:
                await ctx.warn("Emote not found in this server")
        except Exception as e:
            await ctx.fail(f"Failed to remove emote: {str(e)[:150]}")

    @emoji.command(
        name="stats",
        description="Show top ten most used emotes",
    )
    @has_permissions(manage_expressions=True)
    async def emoji_stats(self, ctx):
        """show emote usage stats"""
        if ctx.guild is None:
            return await ctx.warn("This command can only be used in a server")
        try:
            emoji_data = await self.bot.db.fetch(
                "SELECT emoji_name, uses FROM emoji_usage WHERE guild_id = $1 ORDER BY uses DESC LIMIT 10",
                ctx.guild.id,
            )
        except Exception:
            emoji_data = None

        if not emoji_data:
            
            emojis = list(ctx.guild.emojis)
            if not emojis:
                return await ctx.warn("No emoji usage data or server emotes available")
            lines = [
                f"**#{i}** {em} `{em.name}`"
                for i, em in enumerate(sorted(emojis, key=lambda e: e.name.lower())[:10], start=1)
            ]
            e = c2(
                title=f"Server emotes · {ctx.guild.name}",
                message="\n".join(lines) + "\n-# usage tracking not available yet",
                timestamp=False,
            )
            return await ctx.send(embed=e)

        lines = [
            f"**#{i} {row['emoji_name']}** — `{row['uses']}` uses"
            for i, row in enumerate(emoji_data, start=1)
        ]
        e = c2(
            title=f"Top 10 Emojis in {ctx.guild.name}",
            message="\n".join(lines),
            timestamp=False,
        )
        await ctx.send(embed=e)

    @emoji.command(
        name="information",
        aliases=["info", "i"],
        description="Show info about a custom emoji",
        example=",emoji information <:name:id>",
    )
    async def emoji_information(self, ctx, *, emoji: str | None = None):
        """Show id/name/url for a custom emoji (or the first emoji in a linked message)."""
        token = (emoji or "").strip()
        pe = _parse_partial_emoji(token.split()[0]) if token else None

        
        if pe is None and token and "channels/" in token:
            try:
                parts = token.rstrip("/").split("channels/")[-1].split("/")
                if len(parts) >= 3:
                    channel_id, message_id = int(parts[1]), int(parts[2])
                    channel = self.bot.get_channel(channel_id) or await self.bot.fetch_channel(channel_id)
                    msg = await channel.fetch_message(message_id)
                    m = _EMOJI_RE.search(msg.content or "")
                    if m:
                        pe = discord.PartialEmoji(
                            animated=bool(m.group(1)),
                            name=m.group(2),
                            id=int(m.group(3)),
                        )
            except Exception:
                pe = None

        if pe is None or not pe.id:
            return await ctx.warn(
                "Provide a custom emoji or message link "
                f"— e.g. `{ctx.clean_prefix}emoji information <:name:id>`"
            )

        guild_emoji = None
        if ctx.guild is not None:
            guild_emoji = discord.utils.get(ctx.guild.emojis, id=pe.id)

        lines = [
            f"**name:** `{pe.name}`",
            f"**id:** `{pe.id}`",
            f"**animated:** {'yes' if pe.animated else 'no'}",
            f"**url:** [open]({pe.url})",
        ]
        if guild_emoji is not None:
            lines.append(f"**server:** this guild · available `{guild_emoji.available}`")
            if guild_emoji.user:
                lines.append(f"**added by:** {guild_emoji.user}")

        e = c2(
            title=f"Emoji · {pe.name}",
            message="\n".join(lines),
            timestamp=False,
        )
        e.set_thumbnail(url=str(pe.url))
        await ctx.send(embed=e)

    @emoji.command(
        name="addmany",
        description="Bulk add emotes to the current server",
    )
    @has_permissions(manage_expressions=True)
    async def emoji_addmany(self, ctx, *, emotes: str):
        """bulk add emotes"""
        emoji_list = emotes.split()
        added = 0
        failed = 0

        async with aiohttp.ClientSession() as session:
            for emoji_str in emoji_list:
                try:
                    custom_emoji = _parse_partial_emoji(emoji_str)
                    if custom_emoji is None or not custom_emoji.url:
                        failed += 1
                        continue
                    data = await _download(session, str(custom_emoji.url))
                    if not data:
                        failed += 1
                        continue
                    await ctx.guild.create_custom_emoji(
                        name=_sanitize_name(custom_emoji.name),
                        image=data,
                        reason=f"emoji addmany by {ctx.author} ({ctx.author.id})",
                    )
                    added += 1
                except Exception:
                    failed += 1

        await ctx.success(f"Added {added} emotes, failed {failed}")

    @emoji.command(
        name="rename",
        description="Renames emote to the new name provided",
    )
    @has_permissions(manage_expressions=True)
    async def emoji_rename(self, ctx, emoji: str, *, new_name: str):
        """rename emote"""
        try:
            custom_emoji = _parse_partial_emoji(emoji)
            if custom_emoji is None:
                return await ctx.warn("Provide a custom emoji to rename")
            emoji_obj = discord.utils.get(ctx.guild.emojis, id=custom_emoji.id)
            if emoji_obj is None:
                emoji_obj = discord.utils.get(ctx.guild.emojis, name=custom_emoji.name)
            if emoji_obj:
                clean = _sanitize_name(new_name, fallback=emoji_obj.name)
                await emoji_obj.edit(name=clean)
                await ctx.success(f"Renamed emote to `{clean}`")
            else:
                await ctx.warn("Emote not found in this server")
        except Exception as e:
            await ctx.fail(f"Failed to rename emote: {str(e)[:150]}")

    @emoji.command(
        name="add",
        description="Add an emote from emoji, image URL, attachment, or sticker",
    )
    @has_permissions(manage_expressions=True)
    async def emoji_add(self, ctx, *, args: str | None = None):
        """Add emoji from custom emoji, image URL, attachment, or sticker.

        Name is optional. Defaults:
          • custom emoji / sticker → original name
          • URL / attachment → file stem
        """
        if ctx.guild is None:
            return await ctx.warn("This command can only be used in a server")

        me = ctx.guild.me
        if me is None or not me.guild_permissions.manage_expressions:
            return await ctx.warn("I need **Manage Expressions** to add emotes")

        raw = (args or "").strip()
        tokens = raw.split() if raw else []

        source_url: str | None = None
        default_name = "emoji"
        optional_name: str | None = None

        
        stickers = list(getattr(ctx.message, "stickers", None) or [])
        attachments = list(ctx.message.attachments or [])

        
        emoji_token = next((t for t in tokens if _EMOJI_RE.search(t) or t.startswith("<")), None)
        pe = _parse_partial_emoji(emoji_token) if emoji_token else None
        if pe is not None and pe.url:
            source_url = str(pe.url)
            default_name = _sanitize_name(pe.name, fallback="emoji")
            rest = [t for t in tokens if t != emoji_token]
            if rest:
                optional_name = rest[0]
        else:
            
            url_token = next((t for t in tokens if t.lower().startswith("http")), None)
            if url_token:
                source_url = url_token.strip("<>")
                default_name = _name_from_url(source_url)
                rest = [t for t in tokens if t != url_token]
                if rest:
                    optional_name = rest[0]
            elif attachments:
                
                att = attachments[0]
                source_url = att.url
                default_name = _sanitize_name(att.filename, fallback="emoji")
                if tokens:
                    optional_name = tokens[0]
            elif stickers:
                
                st = stickers[0]
                
                url = getattr(st, "url", None)
                if not url and getattr(st, "id", None):
                    fmt = getattr(st, "format", None)
                    ext = "png"
                    try:
                        
                        if str(fmt).lower().endswith("gif") or getattr(fmt, "name", "") == "gif":
                            ext = "gif"
                        elif str(fmt).lower().endswith("apng") or getattr(fmt, "name", "") == "apng":
                            ext = "png"
                    except Exception:
                        pass
                    url = f"https://media.discordapp.net/stickers/{st.id}.{ext}"
                source_url = str(url) if url else None
                default_name = _sanitize_name(getattr(st, "name", None), fallback="sticker")
                if tokens:
                    optional_name = tokens[0]
            else:
                
                return await ctx.warn(
                    "Provide a custom emoji, image URL, attachment, or sticker "
                    f"— e.g. `{ctx.clean_prefix}emoji add <:name:id>` "
                    f"or `{ctx.clean_prefix}emoji add https://… name`"
                )

        if not source_url:
            return await ctx.warn("Couldn't resolve an image source for that emoji")

        name = _sanitize_name(optional_name, fallback=default_name) if optional_name else default_name
        if not _NAME_RE.match(name):
            name = _sanitize_name(name, fallback="emoji")

        async with aiohttp.ClientSession() as session:
            data = await _download(session, source_url)
        if not data:
            return await ctx.fail("Couldn't download that image (missing, too large, or blocked)")

        try:
            created = await ctx.guild.create_custom_emoji(
                name=name,
                image=data,
                reason=f"emoji add by {ctx.author} ({ctx.author.id})",
            )
        except discord.Forbidden:
            return await ctx.warn("I don't have permission to create emotes here")
        except discord.HTTPException as e:
            return await ctx.fail(f"Discord rejected the emote: {getattr(e, 'text', e)}"[:180])

        await ctx.success(f"Added emote {created} (`{created.name}`)")
