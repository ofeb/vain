from __future__ import annotations

import io
import re

import aiohttp
import discord
from discord.ext.commands import group

from core.discord.package import Package
from core.managers.permissions import has_permissions

_NAME_RE = re.compile(r"^[A-Za-z0-9_\-]{2,30}$")


def _sanitize_sticker_name(raw: str | None, *, fallback: str = "sticker") -> str:
    text = re.sub(r"[^A-Za-z0-9_\-]+", "_", (raw or "").strip()).strip("_")
    if len(text) < 2:
        text = fallback
    return text[:30]


class Sticker(Package):
    """sticker management"""

    @group(
        name="sticker",
        description="Modify or add stickers to your server",
        invoke_without_command=True,
    )
    async def sticker(self, ctx):
        """sticker group help"""
        return await ctx.send_help(ctx.command)

    @sticker.command(
        name="tag",
        description="Add server vanity to stickers",
    )
    @has_permissions(manage_expressions=True, manage_guild=True)
    async def sticker_tag(self, ctx):
        """add server vanity to stickers"""
        vanity = getattr(ctx.guild, "vanity_url_code", None) or ctx.guild.name
        tag = f"_{vanity}"[:12]
        updated = 0
        for sticker in list(ctx.guild.stickers):
            base = sticker.name
            if base.endswith(tag) or len(base) + len(tag) > 30:
                continue
            new_name = _sanitize_sticker_name(f"{base}{tag}", fallback=base)
            if new_name == sticker.name:
                continue
            try:
                await sticker.edit(
                    name=new_name,
                    reason=f"sticker tag by {ctx.author} ({ctx.author.id})",
                )
                updated += 1
            except Exception:
                continue
        await ctx.success(f"Tagged **{updated}** sticker(s) with `{tag}`")

    @sticker.command(
        name="remove",
        description="Removes sticker from server",
    )
    @has_permissions(manage_expressions=True)
    async def sticker_remove(self, ctx, *, name: str):
        """remove sticker from server"""
        if ctx.guild is None:
            return await ctx.warn("This command can only be used in a server")
        needle = (name or "").strip().lower()
        sticker = next(
            (s for s in ctx.guild.stickers if s.name.lower() == needle),
            None,
        )
        if sticker is None:
            sticker = next(
                (s for s in ctx.guild.stickers if needle in s.name.lower()),
                None,
            )
        if not sticker:
            return await ctx.warn(f"Sticker `{name}` not found")

        try:
            await sticker.delete(reason=f"sticker remove by {ctx.author} ({ctx.author.id})")
        except discord.Forbidden:
            return await ctx.warn("I don't have permission to delete stickers")
        except discord.HTTPException as e:
            return await ctx.fail(f"Failed to remove sticker: {getattr(e, 'text', e)}"[:150])
        await ctx.success(f"Removed sticker `{sticker.name}`")

    @sticker.command(
        name="cleanup",
        description="Cleans server sticker names",
    )
    @has_permissions(manage_expressions=True, manage_guild=True)
    async def sticker_cleanup(self, ctx):
        """clean up sticker names"""
        if ctx.guild is None:
            return await ctx.warn("This command can only be used in a server")
        count = 0
        for sticker in list(ctx.guild.stickers):
            new_name = _sanitize_sticker_name(sticker.name, fallback=sticker.name)
            if new_name != sticker.name:
                try:
                    await sticker.edit(
                        name=new_name,
                        reason=f"sticker cleanup by {ctx.author} ({ctx.author.id})",
                    )
                    count += 1
                except Exception:
                    pass

        await ctx.success(f"Cleaned up **{count}** sticker name(s)")

    @sticker.command(
        name="rename",
        description="Rename the attached sticker to given new name",
    )
    @has_permissions(manage_expressions=True)
    async def sticker_rename(self, ctx, *, new_name: str):
        """rename sticker"""
        if ctx.guild is None:
            return await ctx.warn("This command can only be used in a server")
        if not ctx.message.stickers:
            return await ctx.warn("Attach a sticker to rename")

        partial = ctx.message.stickers[0]
        
        sticker = discord.utils.get(ctx.guild.stickers, id=partial.id)
        if sticker is None:
            sticker = discord.utils.get(ctx.guild.stickers, name=partial.name)
        if sticker is None:
            return await ctx.warn("That sticker isn't from this server")

        clean = _sanitize_sticker_name(new_name, fallback=sticker.name)
        if not _NAME_RE.match(clean):
            return await ctx.warn("Sticker names must be 2–30 letters, numbers, `_` or `-`")
        try:
            await sticker.edit(
                name=clean,
                reason=f"sticker rename by {ctx.author} ({ctx.author.id})",
            )
            await ctx.success(f"Renamed sticker to `{clean}`")
        except discord.Forbidden:
            await ctx.warn("I don't have permission to rename stickers")
        except Exception as e:
            await ctx.fail(f"Failed to rename sticker: {str(e)[:150]}")

    @sticker.command(
        name="add",
        description="Add a sticker from URL, attachment, or another sticker",
        example=",sticker add https://… coolname",
    )
    @has_permissions(manage_expressions=True)
    async def sticker_add(self, ctx, *, args: str | None = None):
        """add sticker from URL / attachment / message sticker"""
        if ctx.guild is None:
            return await ctx.warn("This command can only be used in a server")
        me = ctx.guild.me
        if me is None or not me.guild_permissions.manage_expressions:
            return await ctx.warn("I need **Manage Expressions** to add stickers")

        tokens = (args or "").strip().split()
        source_url: str | None = None
        name: str | None = None

        url_token = next((t for t in tokens if t.lower().startswith("http")), None)
        if url_token:
            source_url = url_token.strip("<>")
            rest = [t for t in tokens if t != url_token]
            name = " ".join(rest) if rest else None
        elif ctx.message.attachments:
            att = ctx.message.attachments[0]
            source_url = att.url
            name = " ".join(tokens) if tokens else (att.filename.rsplit(".", 1)[0] if att.filename else None)
        elif ctx.message.stickers:
            st = ctx.message.stickers[0]
            source_url = getattr(st, "url", None)
            if not source_url and getattr(st, "id", None):
                source_url = f"https://media.discordapp.net/stickers/{st.id}.png"
            name = " ".join(tokens) if tokens else getattr(st, "name", None)
        else:
            return await ctx.warn(
                "Provide a sticker image URL, attachment, or sticker "
                f"- e.g. `{ctx.clean_prefix}sticker add https://… name`"
            )

        if not source_url:
            return await ctx.warn("Couldn't resolve a sticker image source")

        clean = _sanitize_sticker_name(name, fallback="sticker")
        if not _NAME_RE.match(clean):
            return await ctx.warn("Sticker names must be 2–30 letters, numbers, `_` or `-`")

        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(
                    source_url, timeout=aiohttp.ClientTimeout(total=25)
                ) as resp:
                    if resp.status != 200:
                        return await ctx.fail("Failed to download sticker image")
                    data = await resp.read()
        except Exception:
            return await ctx.fail("Failed to download sticker image")

        if not data or len(data) > 512 * 1024:
            return await ctx.fail("Sticker image missing or larger than **512KB**")

        
        lower = source_url.lower()
        if ".gif" in lower:
            filename = f"{clean}.gif"
        elif ".json" in lower:
            filename = f"{clean}.json"
        else:
            filename = f"{clean}.png"

        try:
            created = await ctx.guild.create_sticker(
                name=clean,
                description=f"Added by {ctx.author}",
                emoji="🎨",
                file=discord.File(io.BytesIO(data), filename=filename),
                reason=f"sticker add by {ctx.author} ({ctx.author.id})",
            )
        except discord.Forbidden:
            return await ctx.warn("I don't have permission to create stickers")
        except discord.HTTPException as e:
            return await ctx.fail(f"Discord rejected the sticker: {getattr(e, 'text', e)}"[:180])

        await ctx.success(f"Added sticker **{created.name}**")
