from __future__ import annotations

import contextlib
import secrets

import io
import logging
import textwrap
import traceback
from io import BytesIO
from typing import TYPE_CHECKING

import discord
from discord import ui
from discord.ext import commands
from discord.ext.commands import CommandError

from core.discord.package import Package
from core.discord.views.paginate import send_pages
from core.tools.convert.member import resolve_user
from core.tools.human.time import human_date
from core.discord.ctx import Context
from core.discord.hybrid import group, command, describe
from config import color
import asyncio
import aiohttp
from colorthief import ColorThief

from core.discord.views.embed import panel_embed

_TB_DISPLAY_LIMIT = 3900

async def get_dominant_color(url: str, fallback: int = 0xE1D2DE) -> int:
    """Fetch image and return dominant color using colorthief."""
    if not url:
        return fallback
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url, timeout=8) as resp:
                if resp.status != 200:
                    return fallback
                data = await resp.read()

        def _extract():
            ct = ColorThief(BytesIO(data))
            r, g, b = ct.get_color(quality=1)

            if (r + g + b) < 80:
                r = min(r + 60, 255)
                g = min(g + 60, 255)
                b = min(b + 60, 255)
            return (r << 16) + (g << 8) + b

        return await asyncio.to_thread(_extract)
    except Exception:
        return fallback

async def get_bot_dominant_color(bot) -> int:
    if bot.user and bot.user.display_avatar:
        return await get_dominant_color(str(bot.user.display_avatar.url))
    return 0xE1D2DE

if TYPE_CHECKING:
    from core.vain import Vain

log = logging.getLogger("vain/owner")


def _blacklist_since(dt) -> str:
    if dt is None:
        return "unknown"
    if hasattr(dt, "timestamp"):
        pass
    else:
        return str(dt)
    day = dt.day
    if 11 <= day <= 13:
        suf = "th"
    else:
        suf = {1: "st", 2: "nd", 3: "rd"}.get(day % 10, "th")
    return dt.strftime(f"%A, {day}{suf} %B %Y")


async def _ensure_blacklist_history(db) -> None:
    await db.execute(
        """
        CREATE TABLE IF NOT EXISTS blacklist_history (
            hash TEXT PRIMARY KEY,
            user_id BIGINT,
            guild_id BIGINT,
            action TEXT NOT NULL,
            reason TEXT,
            moderator_id BIGINT,
            created_at TIMESTAMPTZ DEFAULT NOW()
        )
        """
    )
    await db.execute(
        """
        CREATE TABLE IF NOT EXISTS blacklist_history_notes (
            id SERIAL PRIMARY KEY,
            history_hash TEXT NOT NULL,
            content TEXT NOT NULL,
            moderator_id BIGINT,
            created_at TIMESTAMPTZ DEFAULT NOW()
        )
        """
    )


def _gen_bl_hash() -> str:
    return secrets.token_hex(3)[:5]


async def _record_blacklist_history(
    db,
    *,
    action: str,
    user_id: int | None = None,
    guild_id: int | None = None,
    reason: str | None = None,
    moderator_id: int | None = None,
) -> str:
    await _ensure_blacklist_history(db)
    for _ in range(12):
        h = _gen_bl_hash()
        try:
            await db.execute(
                """
                INSERT INTO blacklist_history
                    (hash, user_id, guild_id, action, reason, moderator_id)
                VALUES ($1, $2, $3, $4, $5, $6)
                """,
                h, user_id, guild_id, action, reason, moderator_id,
            )
            return h
        except Exception:
            continue
    h = secrets.token_hex(4)
    await db.execute(
        """
        INSERT INTO blacklist_history
            (hash, user_id, guild_id, action, reason, moderator_id)
        VALUES ($1, $2, $3, $4, $5, $6)
        """,
        h, user_id, guild_id, action, reason, moderator_id,
    )
    return h




class Owner(Package):
    """Bot owner tools, reload, management, debug, and traceback."""

    async def cog_check(self, ctx: Context) -> bool:
        if not await self.bot.is_owner(ctx.author):
            raise commands.NotOwner("You are not the bot owner.")
        return True

    async def _log_devlog(self, message: str) -> None:
        channel_id = await self.db.fetchval(
            "SELECT channel_id FROM devlog_config WHERE bot_id = $1",
            self.bot.user.id,
        )
        if not channel_id:
            return
        ch = self.bot.get_channel(channel_id)
        if not ch:
            return
        try:
            dom = await get_bot_dominant_color(self.bot)
        except Exception:
            dom = color.base
        embed = panel_embed(
            color=dom,
            lines=[message],
            timestamp=True,
        )
        try:
            await ch.send(embed=embed)
        except discord.HTTPException:
            pass

    async def _resolve_user(self, argument: str) -> discord.User:
        """Resolve user from mention, ID, username, or display name."""
        arg = (argument or "").strip()
        mention = arg.strip("<@!>")
        if mention.isdigit():
            user = self.bot.get_user(int(mention))
            if user:
                return user
            try:
                return await self.bot.fetch_user(int(mention))
            except discord.NotFound:
                raise CommandError(f"User `{argument}` not found")
        q = arg.lstrip("@").lower()
        matches = [
            u for u in self.bot.users
            if (u.name and u.name.lower() == q)
            or (getattr(u, "global_name", None) and str(u.global_name).lower() == q)
            or (u.display_name and u.display_name.lower() == q)
        ]
        if not matches:
            matches = [
                u for u in self.bot.users
                if (u.name and q in u.name.lower())
                or (getattr(u, "global_name", None) and q in str(u.global_name).lower())
                or (u.display_name and q in u.display_name.lower())
            ]
        if len(matches) == 1:
            return matches[0]
        if len(matches) > 1:
            raise CommandError(
                f"Multiple users match `{argument}` — use a mention or ID"
            )
        raise CommandError(
            f"Could not resolve `{argument}` as a user — use a mention, ID, or username"
        )

    def _resolve_ext(self, name: str) -> str:
        return self.bot._normalize_extension(name)

    @command(
        name="reload",
        description="reload all or a specific extension",
        aliases=["rl"],
    )
    @describe(extension="Extension name to reload, or 'all'")
    async def reload(self, ctx: Context, *, extension: str = "all") -> None:
        raw = (extension or "all").strip()
        if raw.lower() in ("all", "*", "~"):
            before = set(self.bot.extensions.keys())
            
            ordered = sorted(before, key=lambda n: (n == "jishaku", n.startswith("ext.owner"), n))
            success: list[str] = []
            failed: list[tuple[str, str]] = []
            for ext in ordered:
                ok, err = await self.bot.safe_reload_extension(ext)
                if ok:
                    success.append(ext)
                else:
                    failed.append((ext, err or "unknown error"))

            
            missing = before - set(self.bot.extensions.keys())
            recovered = []
            for ext in sorted(missing):
                ok, err = await self.bot.safe_reload_extension(ext)
                if ok:
                    recovered.append(ext)
                else:
                    failed.append((ext, err or "failed recovery"))

            msg = f"Reloaded **{len(success)}** extensions."
            if recovered:
                msg += f"\nRecovered **{len(recovered)}** after unload."
            if failed:
                detail = ", ".join(f"`{n}` ({e})" for n, e in failed[:5])
                msg += f"\nFailed **{len(failed)}**: {detail}"
            return await ctx.success(msg)

        try:
            ext_name = self._resolve_ext(raw)
        except ValueError as e:
            return await ctx.fail(str(e))

        if ext_name not in self.bot.extensions and not ext_name.startswith("ext."):
            return await ctx.fail(f"Extension `{raw}` is not loaded.")

        ok, err = await self.bot.safe_reload_extension(ext_name)
        if ok:
            return await ctx.success(f"Reloaded `{ext_name}`")
        
        if ext_name not in self.bot.extensions:
            ok2, err2 = await self.bot.safe_reload_extension(ext_name)
            if ok2:
                return await ctx.success(f"Reloaded `{ext_name}` (recovered)")
            return await ctx.fail(f"Failed to reload `{ext_name}`\n> -# {err2 or err}")
        return await ctx.fail(f"Failed to reload `{ext_name}`\n> -# {err}")

    @command(
        name="load",
        description="load an extension",
        aliases=["extload"],
    )
    @describe(extension="Extension name to load (e.g. utility or utility.extended.afk)")
    async def load(self, ctx: Context, *, extension: str) -> None:
        try:
            ext_name = self._resolve_ext(extension)
        except ValueError as e:
            return await ctx.fail(str(e))
        if ext_name in self.bot.extensions:
            return await ctx.warn(f"`{ext_name}` is already loaded")
        try:
            await self.bot.load_extension(ext_name)
            return await ctx.success(f"Loaded `{ext_name}`")
        except Exception as e:
            return await ctx.fail(f"Failed to load `{ext_name}`\n> -# {type(e).__name__}: {e}")

    @command(
        name="unload",
        description="unload a loaded extension",
        aliases=["extunload"],
    )
    @describe(extension="Extension name to unload")
    async def unload(self, ctx: Context, *, extension: str) -> None:
        try:
            ext_name = self._resolve_ext(extension)
        except ValueError as e:
            return await ctx.fail(str(e))
        if ext_name not in self.bot.extensions:
            return await ctx.warn(f"`{ext_name}` is not loaded")
        try:
            await self.bot.unload_extension(ext_name)
            return await ctx.success(f"Unloaded `{ext_name}`")
        except Exception as e:
            return await ctx.fail(f"Failed to unload `{ext_name}`\n> -# {type(e).__name__}: {e}")

    @command(
        name="sync",
        description="sync slash commands to a specific guild or globally",
    )
    @describe(guild_id="Guild ID to sync to (leave empty for global)")
    async def sync(self, ctx: Context, guild_id: str = None) -> None:
        if guild_id:
            guild = discord.Object(id=int(guild_id))
            synced = await self.bot.tree.sync(guild=guild)
            await ctx.success(
                f"Synced **{len(synced)}** commands to guild `{guild_id}`"
            )
        else:
            synced = await self.bot.tree.sync()
            await ctx.success(f"Synced **{len(synced)}** commands globally")

    @command(
        name="guilds",
        description="list guilds the bot is in (page / search)",
        aliases=["servers"],
    )
    async def guilds(self, ctx: Context, *, query: str = None) -> None:
        """List guilds. Usage: ,guilds [page] [--search name]"""
        rest = (query or "").strip()
        if not rest and ctx.message and ctx.message.content:
            inv = (ctx.invoked_with or "guilds")
            full = ctx.message.content
            idx = full.lower().find(inv.lower())
            if idx >= 0:
                rest = full[idx + len(inv) :].strip()

        start_page = 1
        search = None
        tokens = rest.split() if rest else []
        i = 0
        while i < len(tokens):
            tok = tokens[i]
            low = tok.lower()
            if low in ("--search", "-s", "--name", "--query"):
                search = " ".join(tokens[i + 1 :]).strip() or None
                break
            if tok.isdigit() and i == 0 and search is None:
                start_page = max(1, int(tok))
                i += 1
                continue
            if not tok.startswith("-") and not tok.isdigit():
                search = " ".join(tokens[i:]).strip()
                break
            i += 1

        guild_list = sorted(
            self.bot.guilds,
            key=lambda g: (g.member_count or 0),
            reverse=True,
        )
        if search:
            q = search.lower()
            guild_list = [g for g in guild_list if q in (g.name or "").lower()]

        if not guild_list:
            tip = f" for `{search}`" if search else ""
            return await ctx.warn(f"No guilds found{tip}")

        entries = []
        for i, guild in enumerate(guild_list, 1):
            owner = guild.owner
            if owner is None:
                try:
                    owner = await guild.fetch_member(guild.owner_id)
                except Exception:
                    owner = None
            owner_name = (
                f"{owner} (`{getattr(owner, 'id', guild.owner_id)}`)"
                if owner
                else f"Unknown (`{guild.owner_id}`)"
            )
            entries.append(
                f"`{i}.` **{guild.name}** (`{guild.id}`) — "
                f"`{guild.member_count or 0}` members — Owner: {owner_name}"
            )

        per_page = 10
        chunks = [entries[i : i + per_page] for i in range(0, len(entries), per_page)] or [[]]
        title_base = f"Guilds ({len(guild_list)})"
        if search:
            title_base += f" · search `{search}`"

        pages = []
        for idx, chunk in enumerate(chunks):
            embed = panel_embed(
                title=title_base,
                lines=chunk,
                footer=f"Page {idx + 1}/{len(chunks)}",
            )
            embed.color = None
            pages.append(embed)

        start_index = min(max(start_page, 1), len(pages)) - 1
        return await send_pages(ctx, pages, start_index=start_index)

    @command(
        name="leaveserver",
        description="leave a server by id",
        aliases=["gleave", "guildleave"],
    )
    @describe(guild_id="ID of the server to leave")
    async def leaveserver(self, ctx: Context, guild_id: str) -> None:
        
        guild = self.bot.get_guild(int(guild_id))
        if not guild:
            await ctx.fail(f"Server `{guild_id}` not found.")
            return
        await guild.leave()
        await ctx.success(f"Left **{guild.name}** (`{guild.id}`)")

    @command(
        name="dm",
        description="send a dm to a user",
    )
    @describe(user_id="User ID to message", message="Message content")
    async def dm(self, ctx: Context, user_id: str, *, message: str) -> None:
        user = self.bot.get_user(int(user_id))
        if not user:
            try:
                user = await self.bot.fetch_user(int(user_id))
            except Exception:
                await ctx.fail(f"User `{user_id}` not found.")
                return
        try:
            await user.send(message)
            await ctx.success(f"Message sent to **{user}**")
        except Exception as e:
            await ctx.fail(f"Failed to DM {user}: {e}")

    @command(
        name="eval",
        description="evaluate python code",
        aliases=["exec", "pyeval"],
    )
    @describe(code="Python code to evaluate")
    async def eval_cmd(self, ctx: Context, *, code: str) -> None:
        code = textwrap.dedent(code).strip("```python ").strip("``` ")
        env = {
            "bot": self.bot,
            "ctx": ctx,
            "discord": discord,
            "commands": commands,
        }
        try:
            result = eval(code, env)
            if result is not None:
                if isinstance(result, discord.Embed):
                    await ctx.send(embed=result)
                else:
                    await ctx.send(f"```python\n{result}\n```")
        except Exception as e:
            tb = "".join(traceback.format_exception(type(e), e, e.__traceback__))
            await self._send_traceback_layout(ctx, key="eval", tb_text=tb)

    @command(
        name="shutdown",
        description="shut down the bot",
        aliases=["die", "kill"],
    )
    async def shutdown(self, ctx: Context) -> None:
        await ctx.success("Shutting down...")
        await self.bot.close()

    @command(
        name="debug",
        description="run a command and capture logs into a file",
    )
    @describe(command="Command to run (e.g. punch @user, help)")
    async def debug(self, ctx: Context, *, command: str = "") -> None:
        if not command:
            await ctx.fail("Provide a command to debug")
            return

        import logging as _logging
        from io import StringIO

        log_capture = StringIO()
        handler = _logging.StreamHandler(log_capture)
        handler.setLevel(_logging.DEBUG)
        handler.setFormatter(
            _logging.Formatter("[%(asctime)s] %(name)s %(levelname)s: %(message)s")
        )

        root_logger = _logging.getLogger()
        root_logger.addHandler(handler)

        stdout_capture = StringIO()
        old_stdout = __import__("sys").stdout
        __import__("sys").stdout = stdout_capture

        stderr_capture = StringIO()
        old_stderr = __import__("sys").stderr
        __import__("sys").stderr = stderr_capture

        error_text = ""
        status = "success"
        try:
            target_cmd = self.bot.get_command(command.split()[0] if command else "")
            if target_cmd is None:
                await ctx.fail(f"Command `{command}` not found")
                return
            import copy as _copy
            fake_msg = _copy.copy(ctx.message)
            fake_msg.content = f"{ctx.prefix}{command}"
            new_ctx = await self.bot.get_context(fake_msg, cls=Context)
            await self.bot.invoke(new_ctx)
        except Exception as exc:
            status = "error"
            error_text = "".join(
                traceback.format_exception(type(exc), exc, exc.__traceback__)
            )
        finally:
            root_logger.removeHandler(handler)
            __import__("sys").stdout = old_stdout
            __import__("sys").stderr = old_stderr

        log_text = log_capture.getvalue()
        stdout_text = stdout_capture.getvalue()
        stderr_text = stderr_capture.getvalue()

        parts = []
        if log_text.strip():
            parts.append(f"=== LOG OUTPUT ===\n{log_text.strip()}")
        if stdout_text.strip():
            parts.append(f"=== STDOUT ===\n{stdout_text.strip()}")
        if stderr_text.strip():
            parts.append(f"=== STDERR ===\n{stderr_text.strip()}")
        if error_text.strip():
            parts.append(f"=== ERROR ===\n{error_text.strip()}")

        if not parts:
            await ctx.fail("No output captured from that command")
            return

        output = "\n\n".join(parts)
        file = discord.File(
            io.BytesIO(output.encode("utf-8")),
            filename=f"debug-{command[:50].replace(' ', '-')}.txt",
        )

        if status == "error":
            await ctx.warning(
                f"Command `{command}` raised an error - see attached log"
            )
        else:
            await ctx.success(f"Command `{command}` ran - see attached log")
        await ctx.send(file=file)

    async def _send_traceback_layout(
        self,
        ctx: Context,
        *,
        key: str,
        tb_text: str,
    ) -> discord.Message:
        """Show traceback in a C2 container as a python code block.

        If the error is too large for TextDisplay, attach a discord.File on
        the message (not inside the container).
        """
        container = ui.Container()
        container.add_item(ui.TextDisplay(f"### Traceback #{key}"))
        container.add_item(ui.Separator(visible=True))

        fenced = f"```python\n{tb_text}\n```"
        attach: discord.File | None = None

        if len(fenced) <= _TB_DISPLAY_LIMIT:
            container.add_item(ui.TextDisplay(fenced))
        else:
            preview_budget = max(200, _TB_DISPLAY_LIMIT - 120)
            preview = tb_text[:preview_budget]
            if len(tb_text) > len(preview):
                preview = preview.rstrip() + "\n..."
            notice = (
                "Error is too large to show fully - see attached file.\n"
                f"```python\n{preview}\n```"
            )
            if len(notice) > _TB_DISPLAY_LIMIT:
                notice = "Error is too large to show - see attached file."
            container.add_item(ui.TextDisplay(notice))
            attach = discord.File(
                io.BytesIO(tb_text.encode("utf-8")),
                filename=f"traceback-{key}.txt",
            )

        layout = ui.LayoutView(timeout=None)
        layout.add_item(container)
        if attach is not None:
            return await ctx.send(view=layout, file=attach)
        return await ctx.send(view=layout)

    @command(
        name="traceback",
        description="view stored traceback by error id or last error",
        aliases=["tb"],
    )
    @describe(error_id="Error ID to look up (leave empty for last error)")
    async def traceback_cmd(self, ctx: Context, error_id: str = "") -> None:
        store = getattr(self.bot, "_error_store", None) or {}
        if not store:
            await ctx.fail("No stored errors yet")
            return

        if not error_id:
            key = max(store.keys(), key=lambda k: int(k))
        else:
            key = error_id

        tb_text = store.get(key)
        if not tb_text:
            await ctx.fail(f"No error stored with ID `{key}`")
            return

        await self._send_traceback_layout(ctx, key=str(key), tb_text=tb_text)

    @group(
        name="botedit",
        description="edit bot appearance",
        invoke_without_command=True,
    )
    async def botedit(self, ctx: Context) -> None:
        await ctx.send_help(ctx.command)

    @botedit.command(name="pfp", description="change bot avatar")
    @describe(url="Image URL or attachment")
    async def botedit_pfp(self, ctx: Context, url: str = None) -> None:
        if url is None and ctx.message.attachments:
            url = ctx.message.attachments[0].url
        if not url:
            await ctx.fail("Provide an image URL or attach an image")
            return
        async with ctx.typing():
            data = await self.bot.http._HTTPClient__session.get(url)
            avatar_bytes = await data.read()
            await self.bot.user.edit(avatar=avatar_bytes)
        await ctx.success("Bot avatar updated")

    @botedit.command(name="banner", description="change bot banner")
    @describe(url="Image URL or attachment")
    async def botedit_banner(self, ctx: Context, url: str = None) -> None:
        if url is None and ctx.message.attachments:
            url = ctx.message.attachments[0].url
        if not url:
            await ctx.fail("Provide an image URL or attach an image")
            return
        async with ctx.typing():
            data = await self.bot.http._HTTPClient__session.get(url)
            banner_bytes = await data.read()
            await self.bot.user.edit(banner=banner_bytes)
        await ctx.success("Bot banner updated")

    @botedit.command(name="bio", description="change bot bio/about me")
    @describe(text="New bio text (max 190 chars)")
    async def botedit_bio(self, ctx: Context, *, text: str) -> None:
        if len(text) > 190:
            await ctx.fail("Bio must be 190 characters or less")
            return
        async with ctx.typing():
            await self.bot.http.edit_profile(bio=text)
        await ctx.success("Bot bio updated")

    @botedit.command(
        name="customstatus",
        aliases=["status", "activity"],
        description="change bot custom status",
    )
    @describe(text="Status text (empty to clear)")
    async def botedit_customstatus(
        self, ctx: Context, *, text: str = ""
    ) -> None:
        async with ctx.typing():
            if text:
                await self.bot.change_presence(
                    activity=discord.CustomActivity(name=text)
                )
            else:
                await self.bot.change_presence(activity=None)
        await ctx.success("Status updated" if text else "Status cleared")

    

    @group(
        name="devlogs",
        aliases=["botlogs"],
        description="dev logging channel + blacklist/whitelist history",
        invoke_without_command=True,
    )
    async def devlogs(self, ctx: Context, *, query: str = None) -> None:
        """Set channel, or view a user's blacklist/whitelist history.

        Usage:
          ,devlogs #channel
          ,devlogs @user [--blacklist|--whitelist|--type blacklist|whitelist]
        """
        from core.discord.ctx import layout_from_items
        import math
        import re as _re

        rest = (query or "").strip()
        if not rest and ctx.message and ctx.message.content:
            inv = ctx.invoked_with or "devlogs"
            full = ctx.message.content
            idx = full.lower().find(inv.lower())
            if idx >= 0:
                rest = full[idx + len(inv) :].strip()

        if ctx.invoked_subcommand is not None:
            return

        
        if rest and not rest.lstrip("-").startswith(("type", "blacklist", "whitelist", "bl", "wl")):
            
            ch = None
            m = _re.search(r"<#(\d+)>", rest)
            if m:
                ch = self.bot.get_channel(int(m.group(1)))
            elif rest.isdigit():
                ch = self.bot.get_channel(int(rest))
            if ch is not None and hasattr(ch, "send"):
                await self.bot.db.execute(
                    """
                    INSERT INTO devlog_config (bot_id, channel_id)
                        VALUES ($1, $2)
                    ON CONFLICT (bot_id)
                        DO UPDATE SET channel_id = $2
                    """,
                    self.bot.user.id,
                    ch.id,
                )
                return await ctx.success(f"Devlog channel set to {ch.mention}")

        
        show_bl = True
        show_wl = True
        tokens = rest.split() if rest else []
        cleaned = []
        i = 0
        while i < len(tokens):
            low = tokens[i].lower().strip(",")
            if low in ("--blacklist", "--bl", "--blist"):
                show_bl, show_wl = True, False
                i += 1
                continue
            if low in ("--whitelist", "--wl", "--wlist"):
                show_bl, show_wl = False, True
                i += 1
                continue
            if low in ("--type", "-t"):
                if i + 1 < len(tokens):
                    tval = tokens[i + 1].lower().strip(",")
                    if tval in ("blacklist", "bl", "blist"):
                        show_bl, show_wl = True, False
                    elif tval in ("whitelist", "wl", "wlist"):
                        show_bl, show_wl = False, True
                    i += 2
                    continue
                i += 1
                continue
            if low.startswith("--type="):
                tval = low.split("=", 1)[1]
                if tval in ("blacklist", "bl", "blist"):
                    show_bl, show_wl = True, False
                elif tval in ("whitelist", "wl", "wlist"):
                    show_bl, show_wl = False, True
                i += 1
                continue
            cleaned.append(tokens[i])
            i += 1
        target = " ".join(cleaned).strip()

        if not target:
            current = await self.bot.db.fetchval(
                "SELECT channel_id FROM devlog_config WHERE bot_id = $1",
                self.bot.user.id,
            )
            if current:
                ch = self.bot.get_channel(current)
                return await ctx.send(
                    f"Current devlog channel: {ch.mention if ch else f'<#{current}>'}\n"
                    f"> -# usage: `{ctx.prefix}devlogs @user` · `{ctx.prefix}devlogs #channel`"
                )
            return await ctx.warn(
                f"No devlog channel set\n> -# **usage:** `{ctx.prefix}devlogs #channel`"
            )

        user = await self._resolve_user(target)
        await _ensure_blacklist_history(self.bot.db)
        actions = []
        if show_bl:
            actions.append("blacklist")
        if show_wl:
            actions.append("whitelist")
        rows = await self.bot.db.fetch(
            """
            SELECT hash, action, reason, moderator_id, created_at
            FROM blacklist_history
            WHERE user_id = $1 AND action = ANY($2::text[])
            ORDER BY created_at DESC
            """,
            user.id,
            actions,
        )
        if not rows:
            kind = "blacklist/whitelist"
            if show_bl and not show_wl:
                kind = "blacklist"
            elif show_wl and not show_bl:
                kind = "whitelist"
            return await ctx.warn(f"No {kind} history for **{user}**")

        
        hashes = [r["hash"] for r in rows]
        note_rows = await self.bot.db.fetch(
            """
            SELECT id, history_hash, content, moderator_id, created_at
            FROM blacklist_history_notes
            WHERE history_hash = ANY($1::text[])
            ORDER BY created_at ASC
            """,
            hashes,
        )
        notes_map: dict[str, list] = {}
        for nr in note_rows:
            notes_map.setdefault(nr["history_hash"], []).append(nr)

        page_size = 3
        total_pages = max(1, math.ceil(len(rows) / page_size))
        pages = []
        title_kind = "history"
        if show_bl and not show_wl:
            title_kind = "blacklist history"
        elif show_wl and not show_bl:
            title_kind = "whitelist history"

        for page_number, start in enumerate(range(0, len(rows), page_size), start=1):
            chunk = rows[start : start + page_size]
            container = ui.Container()
            for attr in ("accent_color", "accent_colour"):
                if hasattr(container, attr):
                    with contextlib.suppress(Exception):
                        setattr(container, attr, None)
            container.add_item(ui.TextDisplay(f"**Devlogs · {title_kind}** - {user}"))
            container.add_item(
                ui.TextDisplay(
                    f"-# {len(rows)} entr{'y' if len(rows) == 1 else 'ies'} · page {page_number}/{total_pages}"
                )
            )
            container.add_item(ui.Separator(visible=True, spacing=discord.SeparatorSpacing.small))
            lines = []
            for idx, row in enumerate(chunk):
                mod = f"<@{row['moderator_id']}>" if row["moderator_id"] else "unknown"
                try:
                    when = human_date(row.get("created_at"), fallback="unknown")
                except Exception:
                    when = _blacklist_since(row["created_at"])
                reason = (row["reason"] or "").strip() or "no reason provided"
                lines.append(f"**`{row['hash']}`** - `{row['action']}`")
                lines.append(f"-# **moderator**: {mod}")
                lines.append(f"-# **when**: {when}")
                lines.append(f"-# **reason**: {reason}")
                nlist = notes_map.get(row["hash"]) or []
                if nlist:
                    note_text = (nlist[-1]["content"] or "").strip() or "none"
                    lines.append(f"-# **note**: {note_text[:200]}")
                else:
                    lines.append("-# **note**: none")
                if idx < len(chunk) - 1:
                    lines.append("\u200b")
            container.add_item(ui.TextDisplay("\n".join(lines)))
            pages.append(layout_from_items([container], timeout=None))
        return await send_pages(ctx, pages)

    @devlogs.command(name="remove", description="remove devlog channel")
    async def devlogs_remove(self, ctx: Context) -> None:
        await self.bot.db.execute(
            "DELETE FROM devlog_config WHERE bot_id = $1",
            self.bot.user.id,
        )
        await ctx.success("Devlog channel removed")

    @devlogs.command(name="view", description="view current devlog channel")
    async def devlogs_view(self, ctx: Context) -> None:
        current = await self.bot.db.fetchval(
            "SELECT channel_id FROM devlog_config WHERE bot_id = $1",
            self.bot.user.id,
        )
        if current:
            ch = self.bot.get_channel(current)
            await ctx.success(
                f"Devlog channel: {ch.mention if ch else f'<#{current}>'}"
            )
        else:
            await ctx.warn("No devlog channel set")

    @devlogs.group(
        name="notes",
        aliases=["note"],
        description="notes on blacklist/whitelist history entries",
        invoke_without_command=True,
    )
    async def devlogs_notes(self, ctx: Context, *, query: str = None) -> None:
        if ctx.invoked_subcommand is not None:
            return
        await ctx.warn(
            f"Usage: `{ctx.prefix}devlogs notes add <hash|@user> <note>` · "
            f"`remove` · `modify`"
        )

    @devlogs_notes.command(name="add", description="add a note to a history entry")
    async def devlogs_notes_add(self, ctx: Context, target: str, *, note: str) -> None:
        await _ensure_blacklist_history(self.bot.db)
        note_body = (note or "").strip()
        if not note_body:
            return await ctx.warn("Provide note content")

        history_hash = None
        token = target.strip().strip("`")
        row = await self.bot.db.fetchrow(
            "SELECT hash, user_id FROM blacklist_history WHERE hash = $1",
            token,
        )
        if row:
            history_hash = row["hash"]
        else:
            user = await self._resolve_user(target)
            row = await self.bot.db.fetchrow(
                """
                SELECT hash FROM blacklist_history
                WHERE user_id = $1
                ORDER BY created_at DESC
                LIMIT 1
                """,
                user.id,
            )
            if not row:
                return await ctx.warn("No history entry found for that user")
            history_hash = row["hash"]

        await self.bot.db.execute(
            "DELETE FROM blacklist_history_notes WHERE history_hash = $1",
            history_hash,
        )
        note_id = await self.bot.db.fetchval(
            """
            INSERT INTO blacklist_history_notes (history_hash, content, moderator_id)
            VALUES ($1, $2, $3)
            RETURNING id
            """,
            history_hash,
            note_body[:1000],
            ctx.author.id,
        )
        return await ctx.success(
            f"Set note on history `{history_hash}`"
        )

    @devlogs_notes.command(name="remove", aliases=["del", "delete", "rm"], description="remove a history note")
    async def devlogs_notes_remove(self, ctx: Context, note_ref: str) -> None:
        await _ensure_blacklist_history(self.bot.db)
        ref = note_ref.strip().lstrip("#").strip("`")
        if not ref.isdigit():
            return await ctx.warn("Provide a note id like `#1` or `12`")
        note_id = int(ref)
        row = await self.bot.db.fetchrow(
            "SELECT id, history_hash FROM blacklist_history_notes WHERE id = $1",
            note_id,
        )
        if not row:
            return await ctx.warn(f"No note `#{note_id}`")
        await self.bot.db.execute(
            "DELETE FROM blacklist_history_notes WHERE id = $1", note_id
        )
        return await ctx.success(
            f"Removed note `#{note_id}` from `{row['history_hash']}`"
        )

    @devlogs_notes.command(name="modify", aliases=["edit"], description="modify a history note")
    async def devlogs_notes_modify(self, ctx: Context, note_ref: str, *, note: str) -> None:
        await _ensure_blacklist_history(self.bot.db)
        ref = note_ref.strip().lstrip("#").strip("`")
        if not ref.isdigit():
            return await ctx.warn("Provide a note id like `#1` or `12`")
        note_id = int(ref)
        body = (note or "").strip()
        if not body:
            return await ctx.warn("Provide the new note content")
        row = await self.bot.db.fetchrow(
            "SELECT id FROM blacklist_history_notes WHERE id = $1",
            note_id,
        )
        if not row:
            return await ctx.warn(f"No note `#{note_id}`")
        await self.bot.db.execute(
            "UPDATE blacklist_history_notes SET content = $2 WHERE id = $1",
            note_id,
            body[:1000],
        )
        return await ctx.success(f"Updated note `#{note_id}`")

    @group(
        name="blacklist",
        aliases=["bl"],
        description="blacklist a user or guild from using the bot",
        invoke_without_command=True,
    )
    @describe(target="User ID/mention or guild ID", reason="Reason for blacklisting")
    async def blacklist(self, ctx: Context, target: str, *, reason: str = None) -> None:
        from core.discord.ctx import layout_from_items

        guild = None
        if target.isdigit():
            guild = self.bot.get_guild(int(target))

        if guild is not None:
            await self.bot.db.execute("DELETE FROM blacklist WHERE guild_id = $1", guild.id)
            await self.bot.db.execute(
                "INSERT INTO blacklist (user_id, guild_id, reason) VALUES (NULL, $1, $2)",
                guild.id, reason,
            )
            await self.bot.forget(f"blacklist:guild:{guild.id}")
            entry_hash = await _record_blacklist_history(
                self.bot.db,
                action="blacklist",
                guild_id=guild.id,
                reason=reason,
                moderator_id=ctx.author.id,
            )
            lines = [
                f"-# **target**: **{guild.name}** (`{guild.id}`)",
                f"-# **type**: guild",
                f"-# **id**: `{entry_hash}`",
            ]
            lines.append(f"-# **reason**: {(reason or '').strip() or 'no reason provided'}")
            lines.append(f"-# **blacklisted since**: {_blacklist_since(discord.utils.utcnow())}")
            container = ui.Container()
            for attr in ("accent_color", "accent_colour"):
                if hasattr(container, attr):
                    with contextlib.suppress(Exception):
                        setattr(container, attr, None)
            container.add_item(ui.TextDisplay("**Blacklisted**"))
            container.add_item(ui.Separator(visible=True, spacing=discord.SeparatorSpacing.small))
            container.add_item(ui.TextDisplay("\n".join(lines)))
            await ctx.send(view=layout_from_items([container], timeout=None))
            await self._log_devlog(
                f"**{ctx.author}** blacklisted guild **{guild.name}** (`{guild.id}`)"
                + (f" — reason: {reason}" if reason else "")
            )
            return

        user = await self._resolve_user(target)
        await self.bot.db.execute("DELETE FROM blacklist WHERE user_id = $1", user.id)
        await self.bot.db.execute(
            "INSERT INTO blacklist (user_id, guild_id, reason) VALUES ($1, NULL, $2)",
            user.id, reason,
        )
        await self.bot.forget(f"blacklist:user:{user.id}")
        entry_hash = await _record_blacklist_history(
            self.bot.db,
            action="blacklist",
            user_id=user.id,
            reason=reason,
            moderator_id=ctx.author.id,
        )
        lines = [
            f"-# **target**: {user.mention} (`{user.id}`)",
            f"-# **type**: user",
            f"-# **id**: `{entry_hash}`",
        ]
        lines.append(f"-# **reason**: {(reason or '').strip() or 'no reason provided'}")
        lines.append(f"-# **blacklisted since**: {_blacklist_since(discord.utils.utcnow())}")
        container = ui.Container()
        for attr in ("accent_color", "accent_colour"):
            if hasattr(container, attr):
                with contextlib.suppress(Exception):
                    setattr(container, attr, None)
        container.add_item(ui.TextDisplay("**Blacklisted**"))
        container.add_item(ui.Separator(visible=True, spacing=discord.SeparatorSpacing.small))
        container.add_item(ui.TextDisplay("\n".join(lines)))
        await ctx.send(
            view=layout_from_items([container], timeout=None),
            allowed_mentions=discord.AllowedMentions.none(),
        )
        await self._log_devlog(
            f"**{ctx.author}** blacklisted **{user}** (`{user.id}`)"
            + (f" — reason: {reason}" if reason else "")
        )

    @blacklist.command(
        name="list",
        aliases=["blacklists", "bls"],
        description="view all blacklisted users and guilds",
    )
    async def blacklist_list(self, ctx: Context) -> None:
        from core.discord.ctx import layout_from_items
        import math

        rows = await self.bot.db.fetch(
            "SELECT user_id, guild_id, reason, created_at FROM blacklist ORDER BY created_at DESC"
        )
        if not rows:
            return await ctx.warn("No blacklisted users or guilds")

        entries = []
        for row in rows:
            if row["user_id"]:
                head = f"<@{row['user_id']}> (`{row['user_id']}`)"
                kind = "user"
            elif row["guild_id"]:
                g = self.bot.get_guild(row["guild_id"])
                name = g.name if g else "unknown guild"
                head = f"**{name}** (`{row['guild_id']}`)"
                kind = "guild"
            else:
                continue
            reason = row["reason"] or "none"
            since = _blacklist_since(row["created_at"])
            entries.append((head, kind, reason, since))

        page_size = 10
        total_pages = max(1, math.ceil(len(entries) / page_size))
        pages = []
        for page_number, start in enumerate(range(0, len(entries), page_size), start=1):
            chunk = entries[start : start + page_size]
            container = ui.Container()
            for attr in ("accent_color", "accent_colour"):
                if hasattr(container, attr):
                    with contextlib.suppress(Exception):
                        setattr(container, attr, None)
            container.add_item(ui.TextDisplay("**Blacklist**"))
            container.add_item(
                ui.TextDisplay(
                    f"-# {len(entries)} entr{'y' if len(entries) == 1 else 'ies'} · Page {page_number}/{total_pages}"
                )
            )
            container.add_item(ui.Separator(visible=True, spacing=discord.SeparatorSpacing.small))
            lines = []
            for i, (head, kind, reason, since) in enumerate(chunk, start=start + 1):
                lines.append(f"**`{i}`** - `{kind}`")
                lines.append(f"-# **target**: {head}")
                lines.append(f"-# **reason**: {reason}")
                lines.append(f"-# **when**: {since}")
            container.add_item(ui.TextDisplay("\n".join(lines)))
            pages.append(layout_from_items([container], timeout=None))
        return await send_pages(ctx, pages)

    @group(
        name="whitelist",
        aliases=["unblacklist"],
        description="remove a user or guild from blacklist",
        invoke_without_command=True,
    )
    @describe(target="User ID/mention or guild ID", reason="Optional reason for the whitelist")
    async def whitelist(self, ctx: Context, target: str, *, reason: str = None) -> None:
        from core.discord.ctx import layout_from_items

        guild = None
        if target.isdigit():
            guild = self.bot.get_guild(int(target))

        if guild is not None:
            await self.bot.db.execute(
                "DELETE FROM blacklist WHERE guild_id = $1", guild.id
            )
            await self.bot.forget(f"blacklist:guild:{guild.id}")
            entry_hash = await _record_blacklist_history(
                self.bot.db,
                action="whitelist",
                guild_id=guild.id,
                reason=reason,
                moderator_id=ctx.author.id,
            )
            lines = [
                f"-# **target**: **{guild.name}** (`{guild.id}`)",
                f"-# **type**: guild",
                f"-# **id**: `{entry_hash}`",
                f"-# **reason**: {(reason or '').strip() or 'no reason provided'}",
            ]
            container = ui.Container()
            for attr in ("accent_color", "accent_colour"):
                if hasattr(container, attr):
                    with contextlib.suppress(Exception):
                        setattr(container, attr, None)
            container.add_item(ui.TextDisplay("**Whitelisted**"))
            container.add_item(ui.Separator(visible=True, spacing=discord.SeparatorSpacing.small))
            container.add_item(ui.TextDisplay("\n".join(lines)))
            await ctx.send(view=layout_from_items([container], timeout=None))
            await self._log_devlog(
                f"**{ctx.author}** whitelisted guild **{guild.name}** (`{guild.id}`)"
            )
            return

        user = await self._resolve_user(target)
        await self.bot.db.execute(
            "DELETE FROM blacklist WHERE user_id = $1", user.id
        )
        await self.bot.forget(f"blacklist:user:{user.id}")
        entry_hash = await _record_blacklist_history(
            self.bot.db,
            action="whitelist",
            user_id=user.id,
            reason=reason,
            moderator_id=ctx.author.id,
        )
        lines = [
            f"-# **target**: {user.mention} (`{user.id}`)",
            f"-# **type**: user",
            f"-# **id**: `{entry_hash}`",
            f"-# **reason**: {(reason or '').strip() or 'no reason provided'}",
        ]
        container = ui.Container()
        for attr in ("accent_color", "accent_colour"):
            if hasattr(container, attr):
                with contextlib.suppress(Exception):
                    setattr(container, attr, None)
        container.add_item(ui.TextDisplay("**Whitelisted**"))
        container.add_item(ui.Separator(visible=True, spacing=discord.SeparatorSpacing.small))
        container.add_item(ui.TextDisplay("\n".join(lines)))
        await ctx.send(
            view=layout_from_items([container], timeout=None),
            allowed_mentions=discord.AllowedMentions.none(),
        )
        await self._log_devlog(
            f"**{ctx.author}** whitelisted **{user}** (`{user.id}`)"
        )

    @whitelist.command(
        name="list",
        description="view all whitelisted users and guilds",
    )
    async def whitelist_list(self, ctx: Context) -> None:
        await ctx.warn("Whitelisting removes entries — use `blacklist list` to see current entries")

    @command(
        name="portal",
        description="get an invite link for a server via dm",
    )
    @describe(guild_id="Guild ID to get invite for")
    async def portal(self, ctx: Context, guild_id: str) -> None:
        guild = self.bot.get_guild(int(guild_id))
        if not guild:
            await ctx.fail(f"Bot is not in guild `{guild_id}`")
            return
        try:
            invite = None
            for ch in guild.text_channels:
                if ch.permissions_for(guild.me).create_instant_invite:
                    invite = await ch.create_invite(
                        max_age=0, max_uses=0, unique=False
                    )
                    break
            if not invite:
                await ctx.fail("Cannot create invite - no permissions")
                return
            await ctx.author.send(
                f"**{guild.name}** (`{guild.id}`)\n{invite.url}"
            )
            await ctx.success("Invite sent to your DMs")
        except discord.Forbidden:
            await ctx.fail("Cannot DM you - check your privacy settings")

from discord.ext import commands

from .events import OwnerEvents

async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(Owner(bot))
    await bot.add_cog(OwnerEvents(bot))

