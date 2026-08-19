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
        description="manage server emotes",
        invoke_without_command=True,
    )
    async def emoji(self, ctx):
        """emoji management"""
        return await ctx.send_help(ctx.command)

    @emoji.command(
        name="enlarge",
        aliases=["large", "big", "show"],
        description="returns a large version of a custom emoji",
    )
    async def emoji_enlarge(self, ctx, *, emoji: str | None = None):
        f"Show a large custom emoji - {ctx.cmd('emoji enlarge <:name:id>')}."""
        token = (emoji or "").strip()
        if not token:
            return await ctx.warn(f"Please provide a **valid emoji**\n> -# **usage:** {ctx.cmd('emoji enlarge <:name:id>')}")

        
        token = token.split()[0]
        custom = _parse_partial_emoji(token)
        if custom is None or not custom.id or not custom.url:
            return await ctx.warn(f"Please provide a **valid emoji**\n> -# **usage:** {ctx.cmd('emoji enlarge <:name:id>')}")

        e = c2(message=str(custom), timestamp=False)
        e.set_image(url=str(custom.url))
        await ctx.send(embed=e)

    @emoji.command(
        name="removemany",
        description="bulk remove emotes from the current server",
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

        await ctx.success(f"Removed emotes\n> -# **count:** {removed} deleted, {failed} failed")

    @emoji.command(
        name="removeduplicates",
        description="remove duplicates of emotes",
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

        await ctx.success(f"Duplicates removed\n> -# **count:** {removed} deleted")

    @emoji.command(
        name="remove",
        description="removes emote from server",
    )
    @has_permissions(manage_expressions=True)
    async def emoji_remove(self, ctx, emoji: str):
        """remove emote"""
        try:
            custom_emoji = _parse_partial_emoji(emoji)
            if custom_emoji is None:
                return await ctx.warn(f"No emoji was provided\n> -# **usage:** {ctx.cmd('emoji remove <:name:id>')}")
            emoji_obj = discord.utils.get(ctx.guild.emojis, id=custom_emoji.id)
            if emoji_obj is None:
                emoji_obj = discord.utils.get(ctx.guild.emojis, name=custom_emoji.name)
            if emoji_obj:
                await emoji_obj.delete()
                await ctx.success(f"Emote removed\n> -# **name:** `{emoji_obj.name}`")
            else:
                await ctx.warn("That emote was not found in this server\n> -# **reason:** it may have been deleted or is from another guild")
        except Exception as e:
            await ctx.fail(f"Could not remove that emote\n> -# **error:** {str(e)[:100]}")

    @emoji.command(
        name="stats",
        description="show top ten most used emotes",
    )
    @has_permissions(manage_expressions=True)
    async def emoji_stats(self, ctx):
        """show emote usage stats"""
        if ctx.guild is None:
            return await ctx.warn("This command can only be used in a **server**\n> -# **usage:** this command requires a guild")
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
                return await ctx.warn("No emote usage data available\n> -# **reason:** no usage stats or emotes found")
            lines = [
                f"**#{i}** {em} `{em.name}`"
                for i, em in enumerate(sorted(emojis, key=lambda e: e.name.lower())[:10], start=1)
            ]
            e = c2(
                title=f"Server emotes · {ctx.guild.name}",
                message="\n".join(lines) + "\n> -# usage tracking not available yet",
                timestamp=False,
            )
            return await ctx.send(embed=e)

        lines = [
            f"**#{i} {row['emoji_name']}** - `{row['uses']}` uses"
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
        description="show info about a custom emoji",
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
                f"Please provide a **valid emoji or message link**\n> -# **usage:** {ctx.cmd('emoji information <:name:id>')} or a message link"
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
        description="bulk add emotes to the current server",
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

        await ctx.success(f"Emotes added\n> -# **count:** {added} added, {failed} failed")

    @emoji.command(
        name="rename",
        description="renames emote to the new name provided",
    )
    @has_permissions(manage_expressions=True)
    async def emoji_rename(self, ctx, emoji: str, *, new_name: str):
        """rename emote"""
        try:
            custom_emoji = _parse_partial_emoji(emoji)
            if custom_emoji is None:
                return await ctx.warn(f"No emoji was provided\n> -# **usage:** {ctx.cmd('emoji rename <:name:id> newname')}")
            emoji_obj = discord.utils.get(ctx.guild.emojis, id=custom_emoji.id)
            if emoji_obj is None:
                emoji_obj = discord.utils.get(ctx.guild.emojis, name=custom_emoji.name)
            if emoji_obj:
                clean = _sanitize_name(new_name, fallback=emoji_obj.name)
                await emoji_obj.edit(name=clean)
                await ctx.success(f"Emote renamed\n> -# **name:** `{clean}`")
            else:
                await ctx.warn("That emote was not found in this server\n> -# **reason:** it may have been deleted or is from another guild")
        except Exception as e:
            await ctx.fail(f"Could not rename that emote\n> -# **error:** {str(e)[:100]}")

    @emoji.command(
        name="add",
        description="add an emote from emoji, image url, attachment, or sticker",
    )
    @has_permissions(manage_expressions=True)
    async def emoji_add(self, ctx, *, args: str | None = None):
        """Add emoji from custom emoji, image URL, attachment, or sticker.

        Name is optional. Defaults:
          • custom emoji / sticker → original name
          • URL / attachment → file stem
        """
        if ctx.guild is None:
            return await ctx.warn("This command can only be used in a **server**\n> -# **usage:** this command requires a guild")

        me = ctx.guild.me
        if me is None or not me.guild_permissions.manage_expressions:
            return await ctx.warn("Missing **Manage Expressions** permission\n> -# **required:** Manage Expressions")

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
                    "Please provide a **source** for the emoji\n> -# **usage:** provide an emoji, URL, attachment, or sticker"
                )

        if not source_url:
            return await ctx.warn("Could not resolve an image from your input\n> -# **reason:** check the URL or attachment")

        name = _sanitize_name(optional_name, fallback=default_name) if optional_name else default_name
        if not _NAME_RE.match(name):
            name = _sanitize_name(name, fallback="emoji")

        async with aiohttp.ClientSession() as session:
            data = await _download(session, source_url)
        if not data:
            return await ctx.fail("Could not download the image\n> -# **reason:** image missing, too large, or blocked")

        try:
            created = await ctx.guild.create_custom_emoji(
                name=name,
                image=data,
                reason=f"emoji add by {ctx.author} ({ctx.author.id})",
            )
        except discord.Forbidden:
            return await ctx.warn("Missing **Manage Expressions** permission\n> -# **required:** Manage Expressions")
        except discord.HTTPException as e:
            return await ctx.fail(f"Discord rejected that emote\n> -# **error:** {getattr(e, 'text', e)}"[:180])

        await ctx.success(f"Emote added\n> -# **name:** {created} (`{created.name}`)")
