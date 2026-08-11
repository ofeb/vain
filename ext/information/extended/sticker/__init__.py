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
        await ctx.success(f"Stickers tagged\n> -# **count:** {updated} updated with `{tag}`")

    @sticker.command(
        name="remove",
        description="Removes sticker from server",
    )
    @has_permissions(manage_expressions=True)
    async def sticker_remove(self, ctx, *, name: str):
        """remove sticker from server"""
        if ctx.guild is None:
            return await ctx.warn("This command can only be used in a **server**\n> -# **usage:** this command requires a guild")
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
            return await ctx.warn(f"Could not find that sticker\n> -# **name:** `{name}`")

        try:
            await sticker.delete(reason=f"sticker remove by {ctx.author} ({ctx.author.id})")
        except discord.Forbidden:
            return await ctx.warn("Missing **Manage Expressions** permission\n> -# **required:** Manage Expressions")
        except discord.HTTPException as e:
            return await ctx.fail(f"Could not remove that sticker\n> -# **error:** {getattr(e, 'text', e)}"[:150])
        await ctx.success(f"Sticker removed\n> -# **name:** `{sticker.name}`")

    @sticker.command(
        name="cleanup",
        description="Cleans server sticker names",
    )
    @has_permissions(manage_expressions=True, manage_guild=True)
    async def sticker_cleanup(self, ctx):
        """clean up sticker names"""
        if ctx.guild is None:
            return await ctx.warn("This command can only be used in a **server**\n> -# **usage:** this command requires a guild")
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

        await ctx.success(f"Names cleaned\n> -# **count:** {count} updated")

    @sticker.command(
        name="rename",
        description="Rename the attached sticker to given new name",
    )
    @has_permissions(manage_expressions=True)
    async def sticker_rename(self, ctx, *, new_name: str):
        """rename sticker"""
        if ctx.guild is None:
            return await ctx.warn("This command can only be used in a **server**\n> -# **usage:** this command requires a guild")
        if not ctx.message.stickers:
            return await ctx.warn("Please **attach a sticker** to rename\n> -# **usage:** reply to a sticker or attach one")

        partial = ctx.message.stickers[0]
        
        sticker = discord.utils.get(ctx.guild.stickers, id=partial.id)
        if sticker is None:
            sticker = discord.utils.get(ctx.guild.stickers, name=partial.name)
        if sticker is None:
            return await ctx.warn("That sticker is not from this server\n> -# **reason:** it may have been deleted or is from another guild")

        clean = _sanitize_sticker_name(new_name, fallback=sticker.name)
        if not _NAME_RE.match(clean):
            return await ctx.warn("Please provide a **valid sticker name**\n> -# **format:** 2–30 chars, letters/numbers/`_`/`-`")
        try:
            await sticker.edit(
                name=clean,
                reason=f"sticker rename by {ctx.author} ({ctx.author.id})",
            )
            await ctx.success(f"Sticker renamed\n> -# **name:** `{clean}`")
        except discord.Forbidden:
            await ctx.warn("Missing **Manage Expressions** permission\n> -# **required:** Manage Expressions")
        except Exception as e:
            await ctx.fail(f"Could not rename that sticker\n> -# **error:** {str(e)[:100]}")

    @sticker.command(
        name="add",
        description="Add a sticker from URL, attachment, or another sticker",
        example=",sticker add https://… coolname",
    )
    @has_permissions(manage_expressions=True)
    async def sticker_add(self, ctx, *, args: str | None = None):
        """add sticker from URL / attachment / message sticker"""
        if ctx.guild is None:
            return await ctx.warn("This command can only be used in a **server**\n> -# **usage:** this command requires a guild")
        me = ctx.guild.me
        if me is None or not me.guild_permissions.manage_expressions:
            return await ctx.warn("Missing **Manage Expressions** permission\n> -# **required:** Manage Expressions")

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
                "Please provide a **source** for the sticker\n> -# **usage:** provide a URL, attachment, or sticker"
            )

        if not source_url:
            return await ctx.warn("Could not resolve an image from your input\n> -# **reason:** check the URL or attachment")

        clean = _sanitize_sticker_name(name, fallback="sticker")
        if not _NAME_RE.match(clean):
            return await ctx.warn("Please provide a **valid sticker name**\n> -# **format:** 2–30 chars, letters/numbers/`_`/`-`")

        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(
                    source_url, timeout=aiohttp.ClientTimeout(total=25)
                ) as resp:
                    if resp.status != 200:
                        return await ctx.fail("Could not download that image\n> -# **reason:** HTTP error")
                    data = await resp.read()
        except Exception:
            return await ctx.fail("Could not download that image\n> -# **reason:** network error")

        if not data or len(data) > 512 * 1024:
            return await ctx.fail("That image is too large\n> -# **limit:** 512KB")

        
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
            return await ctx.warn("Missing **Manage Expressions** permission\n> -# **required:** Manage Expressions")
        except discord.HTTPException as e:
            return await ctx.fail(f"Discord rejected that sticker\n> -# **error:** {getattr(e, 'text', e)}"[:180])

        await ctx.success(f"Sticker added\n> -# **name:** {created.name}")
