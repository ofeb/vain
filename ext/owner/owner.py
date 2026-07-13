from __future__ import annotations

import asyncio
import io
import textwrap
import traceback
from datetime import datetime, timezone, timedelta
from typing import TYPE_CHECKING, Optional

import discord
from discord.ext import commands
from discord.ext.commands import group, CommandError

from core.discord.ctx import Context
from core.discord.hybrid import describe, hybrid, group
from core.managers.values import color

if TYPE_CHECKING:
    pass


class Owner(commands.Cog):
    """Owner tools, reload, jishaku, and bot management."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot

    async def cog_check(self, ctx: Context) -> bool:
        if not await self.bot.is_owner(ctx.author):
            raise commands.NotOwner("You are not the bot owner.")
        return True

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
                msg += f"\nFailed **{len(failed)}**: " + ", ".join(f"`{f[0]}` ({f[1]})" for f in failed[:3])
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
            await ctx.success(f"Synced **{len(synced)}** commands to guild `{guild_id}`")
        else:
            synced = await self.bot.tree.sync()
            await ctx.success(f"Synced **{len(synced)}** commands globally")

    @owner.command(
        name="guilds",
        description="List all guilds the bot is in",
    )
    async def owner_servers(self, ctx: Context) -> None:
        entries = []
        for i, guild in enumerate(sorted(self.bot.guilds, key=lambda g: g.member_count, reverse=True), 1):
            owner_name = str(guild.owner) if guild.owner else "Unknown"
            entries.append(f"`{i}.` **{guild.name}** (`{guild.id}`) — {guild.member_count} members — Owner: {owner_name}")

        pages = [entries[i:i + 15] for i in range(0, len(entries), 15)]
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

    @hybrid(
        name="reload",
        description="Reload all bot extensions",
    )
    async def reload(self, ctx: Context) -> None:
        if not await self.bot.is_owner(ctx.author):
            return
        success = 0
        for ext in list(self.bot.extensions.keys()):
            try:
                await self.bot.reload_extension(ext)
                success += 1
            except Exception:
                pass
        await ctx.success(f"Reloaded **{success}** extensions.")

    @hybrid(
        name="sync",
        description="Sync slash commands globally",
    )
    async def sync(self, ctx: Context) -> None:
        if not await self.bot.is_owner(ctx.author):
            return
        synced = await self.bot.tree.sync()
        await ctx.success(f"Synced **{len(synced)}** commands globally.")

    @hybrid(
        name="guilds",
        description="List all guilds the bot is in",
    )
    async def guilds(self, ctx: Context) -> None:
        if not await self.bot.is_owner(ctx.author):
            return
        server_list = "\n".join(
            f"**{g.name}** (`{g.id}`) — {g.member_count} members"
            for g in sorted(self.bot.guilds, key=lambda g: g.member_count, reverse=True)[:20]
        )
        embed = discord.Embed(
            title=f"Guilds ({len(self.bot.guilds)})",
            description=server_list or "No guilds.",
            color=color.base,
        )
        await ctx.send(embed=embed)

    # ─── edit group ─────────────────────────────────────────────────

    @owner.group(
        name="edit",
        description="Edit bot appearance",
        invoke_without_command=True,
    )
    async def owner_edit(self, ctx: Context) -> None:
        await ctx.send_help(ctx.command)

    @owner_edit.command(name="pfp", description="Change bot avatar")
    @describe(url="Image URL or attachment")
    async def owner_edit_pfp(self, ctx: Context, url: str = None) -> None:
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

    @owner_edit.command(name="banner", description="Change bot banner")
    @describe(url="Image URL or attachment")
    async def owner_edit_banner(self, ctx: Context, url: str = None) -> None:
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

    @owner_edit.command(name="bio", description="Change bot bio/about me")
    @describe(text="New bio text (max 190 chars)")
    async def owner_edit_bio(self, ctx: Context, *, text: str) -> None:
        if len(text) > 190:
            await ctx.fail("Bio must be 190 characters or less")
            return
        async with ctx.typing():
            await self.bot.http.edit_profile(bio=text)
        await ctx.success("Bot bio updated")

    @owner_edit.command(name="customstatus", aliases=["status", "activity"], description="Change bot custom status")
    @describe(text="Status text (empty to clear)")
    async def owner_edit_customstatus(self, ctx: Context, *, text: str = "") -> None:
        async with ctx.typing():
            if text:
                await self.bot.change_presence(
                    activity=discord.CustomActivity(name=text)
                )
            else:
                await self.bot.change_presence(activity=None)
        await ctx.success(f"Status updated" if text else "Status cleared")

    # ─── devlogs / botlogs ──────────────────────────────────────────

    @owner.group(
        name="devlogs",
        aliases=["botlogs"],
        description="Configure dev logging channel",
        invoke_without_command=True,
    )
    @describe(channel="Channel to log bot events")
    async def owner_devlogs(self, ctx: Context, channel: discord.TextChannel = None) -> None:
        if channel is None:
            current = await self.bot.db.fetchval(
                "SELECT channel_id FROM devlog_config WHERE bot_id = $1",
                self.bot.user.id,
            )
            if current:
                ch = self.bot.get_channel(current)
                await ctx.send(f"Current devlog channel: {ch.mention if ch else f'<#{current}>'}")
            else:
                await ctx.fail("No devlog channel set. Usage: `owner devlogs #channel`")
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

    @owner_devlogs.command(name="remove", description="Remove devlog channel")
    async def owner_devlogs_remove(self, ctx: Context) -> None:
        await self.bot.db.execute(
            "DELETE FROM devlog_config WHERE bot_id = $1",
            self.bot.user.id,
        )
        await ctx.success("Devlog channel removed")

    @owner_devlogs.command(name="view", description="View current devlog channel")
    async def owner_devlogs_view(self, ctx: Context) -> None:
        current = await self.bot.db.fetchval(
            "SELECT channel_id FROM devlog_config WHERE bot_id = $1",
            self.bot.user.id,
        )
        if current:
            ch = self.bot.get_channel(current)
            await ctx.success(f"Devlog channel: {ch.mention if ch else f'<#{current}>'}")
        else:
            await ctx.fail("No devlog channel set")

    # ─── portal ─────────────────────────────────────────────────────

    @owner.command(
        name="portal",
        description="Get an invite link for a server via DM",
    )
    @describe(guild_id="Guild ID to get invite for")
    async def owner_portal(self, ctx: Context, guild_id: str) -> None:
        guild = self.bot.get_guild(int(guild_id))
        if not guild:
            await ctx.fail(f"Bot is not in guild `{guild_id}`")
            return
        try:
            invite = None
            for ch in guild.text_channels:
                if ch.permissions_for(guild.me).create_instant_invite:
                    invite = await ch.create_invite(max_age=0, max_uses=0, unique=False)
                    break
            if not invite:
                await ctx.fail("Cannot create invite — no permissions")
                return
            await ctx.author.send(f"**{guild.name}** (`{guild.id}`)\n{invite.url}")
            await ctx.success("Invite sent to your DMs")
        except discord.Forbidden:
            await ctx.fail("Cannot DM you — check your privacy settings")

    # ─── blacklist ──────────────────────────────────────────────────

    @owner.group(
        name="blacklist",
        aliases=["bl"],
        description="Blacklist a user or guild from using the bot",
        invoke_without_command=True,
    )
    async def owner_blacklist(self, ctx: Context) -> None:
        await ctx.send_help(ctx.command)

    @owner_blacklist.command(name="user", description="Blacklist a user")
    @describe(user="User to blacklist", duration="Duration (e.g. 1h, 7d) or empty for permanent")
    async def owner_blacklist_user(
        self, ctx: Context, user: discord.User, *, duration: str = None
    ) -> None:
        expires_at = None
        if duration:
            seconds = self._parse_duration(duration)
            if seconds is None:
                await ctx.fail("Invalid duration format. Use e.g. `1h`, `7d`, `30m`")
                return
            expires_at = datetime.now(timezone.utc) + timedelta(seconds=seconds)

        await self.bot.db.execute(
            """
            INSERT INTO blacklist (user_id, guild_id, expires_at)
                VALUES ($1, NULL, $2)
            ON CONFLICT DO NOTHING
            """,
            user.id,
            expires_at,
        )
        # Cache the blacklist
        await self.bot.remember(f"blacklist:{ctx.guild.id if ctx.guild else 0}:{user.id}", 300, lambda: True)

        duration_str = f" for **{duration}**" if duration else " permanently"
        await ctx.success(f"Blacklisted **{user}**{duration_str}")

        # Log to devlogs
        await self._log_devlog(
            f"**{ctx.author}** blacklisted **{user}** (`{user.id}`){duration_str}"
        )

    @owner_blacklist.command(name="guild", description="Blacklist a guild")
    @describe(guild_id="Guild ID to blacklist")
    async def owner_blacklist_guild(
        self, ctx: Context, guild_id: str
    ) -> None:
        guild = self.bot.get_guild(int(guild_id))
        guild_name = guild.name if guild else "Unknown"

        await self.bot.db.execute(
            """
            INSERT INTO blacklist (user_id, guild_id)
                VALUES (NULL, $1)
            ON CONFLICT DO NOTHING
            """,
            int(guild_id),
        )

        await ctx.success(f"Blacklisted guild **{guild_name}** (`{guild_id}`)")
        await self._log_devlog(
            f"**{ctx.author}** blacklisted guild **{guild_name}** (`{guild_id}`)"
        )

    @owner.command(
        name="whitelist",
        aliases=["unblacklist"],
        description="Remove a user or guild from blacklist",
    )
    @describe(user="User to whitelist", guild_id="Guild ID to whitelist")
    async def owner_whitelist(
        self, ctx: Context, user: discord.User = None, guild_id: str = None
    ) -> None:
        if user:
            await self.bot.db.execute(
                "DELETE FROM blacklist WHERE user_id = $1", user.id
            )
            await self.bot.redis.delete(f"blacklist:*:{user.id}") if self.bot.redis else None
            await ctx.success(f"Whitelisted **{user}**")
            await self._log_devlog(
                f"**{ctx.author}** whitelisted **{user}** (`{user.id}`)"
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

    @owner.command(
        name="blacklistlist",
        aliases=["blacklists", "bls"],
        description="View all blacklisted users and guilds",
    )
    async def owner_blacklistlist(self, ctx: Context) -> None:
        rows = await self.bot.db.fetch(
            "SELECT user_id, guild_id, created_at, expires_at FROM blacklist ORDER BY created_at DESC"
        )
        if not rows:
            raise CommandError("No blacklisted users or guilds")

        values = []
        for row in rows:
            if row["user_id"]:
                values.append(f"User: <@{row['user_id']}> (`{row['user_id']}`)")
            elif row["guild_id"]:
                values.append(f"Guild: `{row['guild_id']}`")

        embed = discord.Embed(title="Blacklist", color=color.base)
        return await ctx.paginate(embed, values)

    def _parse_duration(self, duration: str) -> int | None:
        """Parse duration string like '1h', '7d', '30m' to seconds"""
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

    async def _log_devlog(self, message: str) -> None:
        """Send a message to the devlog channel"""
        channel_id = await self.bot.db.fetchval(
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


async def setup(bot: commands.Bot):
    await bot.add_cog(Owner(bot))
