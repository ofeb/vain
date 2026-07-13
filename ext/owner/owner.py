from __future__ import annotations

import io
import logging
import textwrap
import traceback
from datetime import datetime, timezone, timedelta
from typing import TYPE_CHECKING, Optional

import discord
from discord.ext import commands
from discord.ext.commands import CommandError

from core.discord.package import Package
from core.discord.ctx import Context
from core.discord.hybrid import group, command, describe
from core.managers.values import color

if TYPE_CHECKING:
    from core.vain import Vain

log = logging.getLogger("vain.owner")


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
        embed = discord.Embed(
            description=message,
            color=color.base,
            timestamp=datetime.now(timezone.utc),
        )
        try:
            await ch.send(embed=embed)
        except discord.HTTPException:
            pass

    async def _resolve_user(self, argument: str) -> discord.User:
        """resolve a user from mention, ID, or name"""
        try:
            return await commands.UserConverter().convert(
                type("FakeCtx", (), {"bot": self.bot, "author": None, "guild": None})(),
                argument,
            )
        except (commands.BadArgument, commands.CommandError):
            try:
                return await self.bot.fetch_user(int(argument))
            except (ValueError, discord.NotFound):
                raise CommandError(f"Could not find user `{argument}`")

    def _parse_duration(self, duration: str) -> int | None:
        units = {"s": 1, "m": 60, "h": 3600, "d": 86400, "w": 604800}
        duration = duration.strip().lower()
        if not duration:
            return None
        unit = duration[-1]
        if unit not in units:
            return None
        try:
            value = int(duration[:-1])
            return value * units[unit]
        except ValueError:
            return None

    # ─── owner root ─────────────────────────────────────────────────

    @group(
        name="owner",
        description="Bot owner commands",
        invoke_without_command=True,
        aliases=["dev"],
    )
    async def owner(self, ctx: Context) -> None:
        await ctx.send_help(ctx.command)

    @owner.command(
        name="reload",
        description="Reload all or a specific extension",
        aliases=["rl"],
    )
    @describe(extension="Extension name to reload, or 'all'")
    async def owner_reload(self, ctx: Context, *, extension: str = "all") -> None:
        if extension == "all":
            success = []
            failed = []
            for ext in list(self.bot.extensions.keys()):
                try:
                    await self.bot.reload_extension(ext)
                    success.append(ext)
                except Exception as e:
                    failed.append((ext, str(e)))
            msg = f"Reloaded **{len(success)}** extensions."
            if failed:
                msg += f"\nFailed **{len(failed)}**: " + ", ".join(
                    f"`{f[0]}` ({f[1]})" for f in failed[:3]
                )
            await ctx.success(msg)
        else:
            ext_name = f"ext.{extension}"
            if ext_name not in self.bot.extensions:
                await ctx.fail(f"Extension `{extension}` is not loaded.")
                return
            try:
                await self.bot.reload_extension(ext_name)
                await ctx.success(f"Reloaded `{extension}`")
            except Exception as e:
                await ctx.fail(f"Failed to reload `{extension}`: {e}")

    @owner.command(
        name="load",
        description="Load a new extension",
        aliases=["add"],
    )
    @describe(extension="Extension name to load")
    async def owner_load(self, ctx: Context, *, extension: str) -> None:
        try:
            await self.bot.load_extension(f"ext.{extension}")
            await ctx.success(f"Loaded `{extension}`")
        except Exception as e:
            await ctx.fail(f"Failed to load `{extension}`: {e}")

    @owner.command(
        name="unload",
        description="Unload a loaded extension",
        aliases=["remove"],
    )
    @describe(extension="Extension name to unload")
    async def owner_unload(self, ctx: Context, *, extension: str) -> None:
        try:
            await self.bot.unload_extension(f"ext.{extension}")
            await ctx.success(f"Unloaded `{extension}`")
        except Exception as e:
            await ctx.fail(f"Failed to unload `{extension}`: {e}")

    @owner.command(
        name="sync",
        description="Sync slash commands to a specific guild or globally",
    )
    @describe(guild_id="Guild ID to sync to (leave empty for global)")
    async def owner_sync(self, ctx: Context, guild_id: str = None) -> None:
        if guild_id:
            guild = discord.Object(id=int(guild_id))
            synced = await self.bot.tree.sync(guild=guild)
            await ctx.success(
                f"Synced **{len(synced)}** commands to guild `{guild_id}`"
            )
        else:
            synced = await self.bot.tree.sync()
            await ctx.success(f"Synced **{len(synced)}** commands globally")

    @owner.command(
        name="guilds",
        description="List all guilds the bot is in",
    )
    async def owner_guilds(self, ctx: Context) -> None:
        entries = []
        for i, guild in enumerate(
            sorted(
                self.bot.guilds,
                key=lambda g: g.member_count,
                reverse=True,
            ),
            1,
        ):
            owner_name = str(guild.owner) if guild.owner else "Unknown"
            entries.append(
                f"`{i}.` **{guild.name}** (`{guild.id}`) — "
                f"{guild.member_count} members — Owner: {owner_name}"
            )

        pages = [entries[i : i + 15] for i in range(0, len(entries), 15)]
        page = 0
        embed = discord.Embed(
            title=f"Guilds ({len(self.bot.guilds)})",
            description="\n".join(pages[page]),
            color=color.base,
        )
        embed.set_footer(text=f"Page {page + 1}/{len(pages)}")
        await ctx.send(embed=embed)

    @owner.command(
        name="leave",
        description="Leave a server by ID",
    )
    @describe(guild_id="ID of the server to leave")
    async def owner_leave(self, ctx: Context, guild_id: str) -> None:
        guild = self.bot.get_guild(int(guild_id))
        if not guild:
            await ctx.fail(f"Server `{guild_id}` not found.")
            return
        await guild.leave()
        await ctx.success(f"Left **{guild.name}** (`{guild.id}`)")

    @owner.command(
        name="dm",
        description="Send a DM to a user",
    )
    @describe(user_id="User ID to message", message="Message content")
    async def owner_dm(self, ctx: Context, user_id: str, *, message: str) -> None:
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

    @owner.command(
        name="eval",
        description="Evaluate Python code",
        aliases=["exec", ">"],
    )
    @describe(code="Python code to evaluate")
    async def owner_eval(self, ctx: Context, *, code: str) -> None:
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
                    await ctx.send(f"```py\n{result}```")
        except Exception as e:
            tb = "".join(traceback.format_exception(type(e), e, e.__traceback__))
            await ctx.send(f"```py\n{tb[:1900]}```")

    @owner.command(
        name="shutdown",
        description="Shut down the bot",
        aliases=["die", "kill"],
    )
    async def owner_shutdown(self, ctx: Context) -> None:
        await ctx.success("Shutting down...")
        await self.bot.close()

    # ─── debug ───────────────────────────────────────────────────────

    @owner.command(
        name="debug",
        description="Run a command and capture logs into a file",
    )
    @describe(command="Command to run (e.g. punch @user, help)")
    async def owner_debug(self, ctx: Context, *, command: str = "") -> None:
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
            target_cmd = self.bot.get_command(command)
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
                f"Command `{command}` raised an error — see attached log"
            )
        else:
            await ctx.success(f"Command `{command}` ran — see attached log")
        await ctx.send(file=file)

    # ─── traceback ───────────────────────────────────────────────────

    @owner.command(
        name="traceback",
        description="View stored traceback by error ID or last error",
        aliases=["tb"],
    )
    @describe(error_id="Error ID to look up (leave empty for last error)")
    async def owner_traceback(
        self, ctx: Context, error_id: str = ""
    ) -> None:
        store = self.bot._error_store
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

        file = discord.File(
            io.BytesIO(tb_text.encode("utf-8")),
            filename=f"traceback-{key}.txt",
        )
        embed = discord.Embed(
            title=f"Traceback #{key}",
            description=f"```\n{tb_text[:1800]}\n```" if len(tb_text) < 1900 else "See attached file",
            color=color.deny,
        )
        await ctx.send(embed=embed, file=file)

    # ─── edit group ──────────────────────────────────────────────────

    @group(
        name="botedit",
        description="Edit bot appearance",
        invoke_without_command=True,
    )
    async def botedit(self, ctx: Context) -> None:
        await ctx.send_help(ctx.command)

    @botedit.command(name="pfp", description="Change bot avatar")
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

    @botedit.command(name="banner", description="Change bot banner")
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

    @botedit.command(name="bio", description="Change bot bio/about me")
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
        description="Change bot custom status",
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

    # ─── devlogs ─────────────────────────────────────────────────────

    @group(
        name="devlogs",
        aliases=["botlogs"],
        description="Configure dev logging channel",
        invoke_without_command=True,
    )
    @describe(channel="Channel to log bot events")
    async def devlogs(
        self, ctx: Context, channel: discord.TextChannel = None
    ) -> None:
        if channel is None:
            current = await self.bot.db.fetchval(
                "SELECT channel_id FROM devlog_config WHERE bot_id = $1",
                self.bot.user.id,
            )
            if current:
                ch = self.bot.get_channel(current)
                await ctx.send(
                    f"Current devlog channel: {ch.mention if ch else f'<#{current}>'}"
                )
            else:
                await ctx.fail(
                    "No devlog channel set. Usage: `devlogs #channel`"
                )
            return
        await self.bot.db.execute(
            """
            INSERT INTO devlog_config (bot_id, channel_id)
                VALUES ($1, $2)
            ON CONFLICT (bot_id)
                DO UPDATE SET channel_id = $2
            """,
            self.bot.user.id,
            channel.id,
        )
        await ctx.success(f"Devlog channel set to {channel.mention}")

    @devlogs.command(name="remove", description="Remove devlog channel")
    async def devlogs_remove(self, ctx: Context) -> None:
        await self.bot.db.execute(
            "DELETE FROM devlog_config WHERE bot_id = $1",
            self.bot.user.id,
        )
        await ctx.success("Devlog channel removed")

    @devlogs.command(name="view", description="View current devlog channel")
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
            await ctx.fail("No devlog channel set")

    # ─── blacklist ───────────────────────────────────────────────────

    @group(
        name="blacklist",
        aliases=["bl"],
        description="Blacklist a user or guild from using the bot",
        invoke_without_command=True,
    )
    async def blacklist(self, ctx: Context) -> None:
        await ctx.send_help(ctx.command)

    @blacklist.command(name="user", description="Blacklist a user")
    @describe(
        user="User ID, mention, or name",
        duration="Duration (e.g. 1h, 7d) or empty for permanent",
    )
    async def blacklist_user(
        self, ctx: Context, user: str, *, duration: str = None
    ) -> None:
        target = await self._resolve_user(user)
        expires_at = None
        if duration:
            seconds = self._parse_duration(duration)
            if seconds is None:
                await ctx.fail(
                    "Invalid duration format. Use e.g. `1h`, `7d`, `30m`"
                )
                return
            expires_at = datetime.now(timezone.utc) + timedelta(seconds=seconds)

        await self.bot.db.execute(
            """
            INSERT INTO blacklist (user_id, guild_id, expires_at)
                VALUES ($1, NULL, $2)
            """,
            target.id,
            expires_at,
        )
        await self.bot.forget(
            f"blacklist:{ctx.guild.id if ctx.guild else 0}:{target.id}"
        )

        duration_str = f" for **{duration}**" if duration else " permanently"
        await ctx.success(f"Blacklisted **{target}**{duration_str}")
        await self._log_devlog(
            f"**{ctx.author}** blacklisted **{target}** (`{target.id}`){duration_str}"
        )

    @blacklist.command(name="guild", description="Blacklist a guild")
    @describe(guild_id="Guild ID to blacklist")
    async def blacklist_guild(self, ctx: Context, guild_id: str) -> None:
        guild = self.bot.get_guild(int(guild_id))
        guild_name = guild.name if guild else "Unknown"

        await self.bot.db.execute(
            """
            INSERT INTO blacklist (user_id, guild_id)
                VALUES (NULL, $1)
            """,
            int(guild_id),
        )
        await ctx.success(f"Blacklisted guild **{guild_name}** (`{guild_id}`)")
        await self._log_devlog(
            f"**{ctx.author}** blacklisted guild **{guild_name}** (`{guild_id}`)"
        )

    @blacklist.command(
        name="list",
        aliases=["blacklists", "bls"],
        description="View all blacklisted users and guilds",
    )
    async def blacklist_list(self, ctx: Context) -> None:
        rows = await self.bot.db.fetch(
            "SELECT user_id, guild_id, created_at, expires_at "
            "FROM blacklist ORDER BY created_at DESC"
        )
        if not rows:
            raise CommandError("No blacklisted users or guilds")

        values = []
        for row in rows:
            if row["user_id"]:
                entry = f"User: <@{row['user_id']}> (`{row['user_id']}`)"
                if row["expires_at"]:
                    entry += f" — expires <t:{int(row['expires_at'].timestamp())}:R>"
                values.append(entry)
            elif row["guild_id"]:
                entry = f"Guild: `{row['guild_id']}`"
                if row["expires_at"]:
                    entry += f" — expires <t:{int(row['expires_at'].timestamp())}:R>"
                values.append(entry)

        embed = discord.Embed(title="Blacklist", color=color.base)
        return await ctx.paginate(embed, values)

    # ─── whitelist ───────────────────────────────────────────────────

    @command(
        name="whitelist",
        aliases=["unblacklist"],
        description="Remove a user or guild from blacklist",
    )
    @describe(user="User to whitelist", guild_id="Guild ID to whitelist")
    async def whitelist(
        self, ctx: Context, user: str = None, guild_id: str = None
    ) -> None:
        if user:
            target = await self._resolve_user(user)
            await self.bot.db.execute(
                "DELETE FROM blacklist WHERE user_id = $1", target.id
            )
            await self.bot.forget(
                f"blacklist:{ctx.guild.id if ctx.guild else 0}:{target.id}"
            )
            await ctx.success(f"Whitelisted **{target}**")
            await self._log_devlog(
                f"**{ctx.author}** whitelisted **{target}** (`{target.id}`)"
            )
        elif guild_id:
            await self.bot.db.execute(
                "DELETE FROM blacklist WHERE guild_id = $1", int(guild_id)
            )
            await ctx.success(f"Whitelisted guild `{guild_id}`")
            await self._log_devlog(
                f"**{ctx.author}** whitelisted guild `{guild_id}`"
            )
        else:
            await ctx.fail("Provide a user or guild ID")

    # ─── portal ──────────────────────────────────────────────────────

    @command(
        name="portal",
        description="Get an invite link for a server via DM",
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
                await ctx.fail("Cannot create invite — no permissions")
                return
            await ctx.author.send(
                f"**{guild.name}** (`{guild.id}`)\n{invite.url}"
            )
            await ctx.success("Invite sent to your DMs")
        except discord.Forbidden:
            await ctx.fail("Cannot DM you — check your privacy settings")


async def setup(bot: commands.Bot):
    await bot.add_cog(Owner(bot))
