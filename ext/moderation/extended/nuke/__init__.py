from __future__ import annotations

import asyncio
import contextlib
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Optional

import discord
from discord import Embed, TextChannel
from discord.ext import tasks
from discord.ext.commands import group, CommandError, TextChannelConverter
from humanize import naturaldelta

from core.discord.package import Package
from core.discord.views.confirm import ConfirmView
from core.managers.permissions import has_permissions
from core.tools.embed import parse_duration_token

if TYPE_CHECKING:
    from core.vain import Vain


_DEFAULT_CHANNEL_ID = 0
_AUTONUKE_DEFAULT_CHANNEL_ID = -1
_DEFAULT_MESSAGE = "first"

_NUKE_VARIABLES = [
    "`{nuke.interval}` - scheduled interval for this channel (autonuke only)",
    "`{nuke.threshold}` - same as interval (seconds as human duration)",
    "`{nuke.reconfigured}` - systems re-pointed after the clone (welcome, leave, boost, logs, …)",
    "`{nuke.channel}` - the new channel mention after the nuke",
    "`{nuke.channel.name}` - new channel name",
    "`{nuke.channel.id}` - new channel id",
    "`{nuke.old}` - old channel name before the nuke",
    "`{channel}` / `{channel.mention}` - new channel",
    "`{guild}` / `{guild.name}` - the server",
    "`{user}` / `{user.mention}` - member who triggered a manual nuke (manual only)",
]


class Nuke(Package):
    """nuke management - one-shot channel clone+delete and scheduled autonuke"""

    def __init__(self, bot: Vain):
        super().__init__(bot)
        self._nuke_lock = asyncio.Lock()

    async def cog_load(self) -> None:
        if not self._autonuke_loop.is_running():
            self._autonuke_loop.start()
        await super().cog_load()

    async def cog_unload(self) -> None:
        if self._autonuke_loop.is_running():
            self._autonuke_loop.cancel()
        await super().cog_unload()

    
    
    

    async def _get_default_message(self, guild_id: int) -> str:
        row = await self.db.fetchval(
            "SELECT message FROM nuke WHERE guild_id = $1 AND channel_id = $2",
            guild_id,
            _DEFAULT_CHANNEL_ID,
        )
        return row or _DEFAULT_MESSAGE

    async def _set_default_message(self, guild_id: int, message: str) -> None:
        await self.db.execute(
            """INSERT INTO nuke (guild_id, channel_id, last_nuke, nuke_threshold, message)
               VALUES ($1, $2, $3, $4, $5)
               ON CONFLICT (guild_id, channel_id)
               DO UPDATE SET message = excluded.message""",
            guild_id,
            _DEFAULT_CHANNEL_ID,
            datetime.now(timezone.utc).replace(tzinfo=None),
            0,
            message,
        )

    async def _get_autonuke_default_message(self, guild_id: int) -> str:
        row = await self.db.fetchval(
            "SELECT message FROM nuke WHERE guild_id = $1 AND channel_id = $2",
            guild_id,
            _AUTONUKE_DEFAULT_CHANNEL_ID,
        )
        return row or _DEFAULT_MESSAGE

    async def _set_autonuke_default_message(self, guild_id: int, message: str) -> None:
        await self.db.execute(
            """INSERT INTO nuke (guild_id, channel_id, last_nuke, nuke_threshold, message)
               VALUES ($1, $2, $3, $4, $5)
               ON CONFLICT (guild_id, channel_id)
               DO UPDATE SET message = excluded.message""",
            guild_id,
            _AUTONUKE_DEFAULT_CHANNEL_ID,
            datetime.now(timezone.utc).replace(tzinfo=None),
            0,
            message,
        )

    async def _perform_nuke(
        self,
        channel: TextChannel,
        *,
        reason: str,
        message: str | None = None,
        author: discord.abc.User | None = None,
        interval: int | None = None,
    ) -> TextChannel | None:
        guild = channel.guild
        category = channel.category
        position = channel.position
        old_name = channel.name
        old_id = channel.id

        is_interface = False
        try:
            interface_id = await self.db.fetchval(
                "SELECT interface_channel_id FROM voicemaster_config WHERE guild_id = $1",
                guild.id,
            )
            if interface_id and interface_id in (old_id, channel.id):
                is_interface = True
        except Exception:
            pass

        try:
            new_channel = await channel.clone(reason=reason)
        except (discord.Forbidden, discord.HTTPException):
            return None

        try:
            await channel.delete(reason=reason)
        except (discord.NotFound, discord.HTTPException, discord.Forbidden):
            pass

        try:
            await new_channel.edit(position=position)
        except (discord.NotFound, discord.HTTPException, discord.Forbidden):
            pass

        if category is not None:
            matches = [c for c in category.text_channels if c.name == old_name]
            if matches:
                new_channel = max(matches, key=lambda c: c.id)

        await self.update_channels_by_id(old_id, new_channel.id, guild.id)

        vm = self.bot.get_cog("VoiceMaster")
        if vm is not None:
            with contextlib.suppress(Exception):
                await vm.reconfigure_after_nuke(old_id, new_channel)

        if not is_interface:
            script = message if message is not None else await self._get_default_message(guild.id)
            if not script:
                script = _DEFAULT_MESSAGE

            reconfigured = (
                "welcome, leave, boost, logs, jail, tickets, starboard, "
                "clownboard, giveaways, counters, suggest, and related systems"
            )
            kwargs = {
                "guild": guild,
                "channel": new_channel,
                "nuke": {
                    "interval": naturaldelta(interval) if interval else "n/a",
                    "threshold": naturaldelta(interval) if interval else "n/a",
                    "reconfigured": reconfigured,
                    "channel": new_channel,
                    "old": old_name,
                },
                "nuke.interval": naturaldelta(interval) if interval else "n/a",
                "nuke.threshold": naturaldelta(interval) if interval else "n/a",
                "nuke.reconfigured": reconfigured,
                "nuke.channel": new_channel.mention,
                "nuke.channel.name": new_channel.name,
                "nuke.channel.id": str(new_channel.id),
                "nuke.old": old_name,
            }
            if author is not None:
                kwargs["user"] = author
                kwargs["member"] = author

            try:
                await self.bot.send_embed(new_channel, script, **kwargs)
            except Exception:
                try:
                    await new_channel.send(content=(script or _DEFAULT_MESSAGE)[:2000])
                except (discord.NotFound, discord.HTTPException):
                    pass

        return new_channel

    async def update_channels(self, old: TextChannel, new: TextChannel) -> None:
        await self.update_channels_by_id(old.id, new.id, old.guild.id)

    async def update_channels_by_id(self, old_id: int, new_id: int, guild_id: int) -> None:
        
        tables = [
            ("guilds", "welcome_channel_id", False),
            ("guilds", "leave_channel_id", False),
            ("guilds", "boost_channel_id", False),
            ("server_settings", "jail_channel_id", False),
            ("server_settings", "jail_message_channel_id", False),
            ("server_settings", "joinlog_channel_id", False),
            ("log_config", "channel_id", False),
            ("log_config", "ignored_channels", True),
            ("modlog_config", "channel_id", False),
            ("moderation_config", "log_channel", False),
            ("roleplay_config", "action_channel", False),
            ("information_config", "info_channel", False),
            ("join_messages", "channel_id", False),
            ("leave_messages", "channel_id", False),
            ("boost_messages", "channel_id", False),
            ("welcome_messages", "channel_id", False),
            ("goodbye_messages", "channel_id", False),
            ("suggest_settings", "channel_id", False),
            ("suggest_settings", "review_channel_id", False),
            ("birthday_notifications", "channel_id", False),
            ("bump_reminder", "channel_id", False),
            ("counters", "channel_id", False),
            ("clownboard", "channel_id", False),
            ("starboard", "channel_id", False),
            ("button_roles", "channel_id", False),
            ("giveaways", "channel_id", False),
            ("ticket_settings", "log_channel_id", False),
            ("ticket_settings", "transcript_channel_id", False),
            ("ticket_panels", "channel_id", False),
            ("tictactoe_channel", "channel_id", False),
            ("disabled_events", "channel_ids", True),
            ("disabled_modules", "channel_ids", True),
            ("auto_responders", "allowed_channel_ids", True),
            ("auto_responders", "denied_channel_ids", True),
            ("trackers", "channel_ids", True),
            ("invite_config", "channel_id", False),
            ("nuke", "channel_id", False),
            ("vanity", "channel_id", False),
            ("guild_tag", "channel_id", False),
            ("sticky_message", "channel_id", False),
            ("pingonjoin", "channel_ids", True),
            ("leveling", "channel_id", False),
            ("voicemaster", "channel_id", False),
            ("voicemaster_config", "category_id", False),
            ("voicemaster_config", "interface_channel_id", False),
        ]

        for table, column, is_array in tables:
            try:
                if is_array:
                    await self.db.execute(
                        f"UPDATE {table} SET {column} = array_replace({column}, $1, $2) "
                        f"WHERE guild_id = $3 AND $1 = ANY({column})",
                        old_id,
                        new_id,
                        guild_id,
                    )
                else:
                    await self.db.execute(
                        f"UPDATE {table} SET {column} = $2 WHERE guild_id = $3 AND {column} = $1",
                        old_id,
                        new_id,
                        guild_id,
                    )
            except Exception:
                continue

    
    
    

    @group(
        name="nuke",
        description="clone and delete a channel (optionally schedule via autonuke)",
        invoke_without_command=True,
        example=",nuke #general",
    )
    @has_permissions(administrator=True)
    async def nuke(self, ctx, channel: Optional[TextChannel] = None):
        """Nuke (clone + delete) a channel after confirmation. Defaults to current channel."""
        channel = channel or ctx.channel
        if not isinstance(channel, TextChannel):
            raise CommandError("You can only nuke text channels")

        view = ConfirmView(ctx, timeout=30.0)
        message = (
            f"This will **nuke** {channel.mention}.\n"
            f"Are you sure you want to do this?\n"
            f"> -# **the channel will be cloned then deleted**"
        )
        if not await view.prompt(message):
            try:
                return await ctx.warn("Nuke **cancelled**")
            except (discord.NotFound, discord.HTTPException):
                return

        old_id = channel.id
        new_channel = await self._perform_nuke(
            channel,
            reason=f"Nuked by {ctx.author}",
            author=ctx.author,
        )
        if new_channel is None:
            return await ctx.fail("Nuke failed\n> -# **missing permissions or channel error**")

        if ctx.channel.id == old_id:
            return
        try:
            await ctx.success(f"Nuked → {new_channel.mention}")
        except (discord.NotFound, discord.HTTPException):
            pass

    @nuke.command(
        name="script",
        aliases=["message", "embed", "msg"],
        description="set the default message/embed script posted after a manual nuke",
        example=",nuke script {embed}$v{description: channel nuked}",
    )
    @has_permissions(administrator=True)
    async def nuke_script(self, ctx, *, message: Optional[str] = None):
        """Set (or clear) the default nuke message / embed script for this server."""
        if message is None or not message.strip():
            current = await self._get_default_message(ctx.guild.id)
            return await ctx.normal(
                f"Current default nuke message:\n```\n{current[:1500]}\n```\n"
                f"Use {ctx.cmd('nuke script <message>')} to change it, or {ctx.cmd('nuke script reset')} to restore `first`."
            )

        if message.strip().lower() in {"reset", "clear", "default", "none"}:
            await self._set_default_message(ctx.guild.id, _DEFAULT_MESSAGE)
            return await ctx.success(
                "Reset default nuke message\n> -# **manual nukes only**"
            )

        script = message.script if hasattr(message, "script") else message
        await self._set_default_message(ctx.guild.id, script)
        preview = script if len(script) <= 200 else script[:200] + "…"
        return await ctx.success(
            f"Default nuke message updated\n> -# **manual nukes only**\n```\n{preview}\n```"
        )

    @nuke.command(
        name="variables",
        aliases=["vars", "variable"],
        description="show variables available in nuke / autonuke embed scripts",
    )
    @has_permissions(administrator=True)
    async def nuke_variables(self, ctx):
        embed = Embed(
            title="Nuke / Autonuke Variables",
                        description=(
                f"Use these inside custom embed scripts for {ctx.cmd('nuke')} and {ctx.cmd('autonuke')}.\n"
                "Also see: https://vain.bot/resources/scripting/variables"
            ),
        )
        embed.set_author(name=str(ctx.author), icon_url=ctx.author.display_avatar.url)
        return await ctx.paginate(embed, _NUKE_VARIABLES)

    
    
    

    @group(
        name="autonuke",
        aliases=["anuke"],
        description="schedule automatic channel nukes",
        invoke_without_command=True,
        example=",autonuke add #general 2h",
    )
    @has_permissions(administrator=True)
    async def autonuke(self, ctx):
        return await ctx.send_help(ctx.command)

    @autonuke.command(
        name="message",
        aliases=["script", "template", "msg"],
        description="set the default message/embed script for all autonukes",
        example=",autonuke message {embed}$v{description: channel autonuked}",
    )
    @has_permissions(administrator=True)
    async def autonuke_message(self, ctx, *, message: Optional[str] = None):
        """Set (or clear) the default autonuke message / embed script for this server."""
        if message is None or not message.strip():
            current = await self._get_autonuke_default_message(ctx.guild.id)
            return await ctx.normal(
                f"Current default autonuke message:\n```\n{current[:1500]}\n```\n"
                f"Use {ctx.cmd('autonuke message <message>')} to change it, or {ctx.cmd('autonuke message reset')} to restore `first`."
            )

        if message.strip().lower() in {"reset", "clear", "default", "none"}:
            await self._set_autonuke_default_message(ctx.guild.id, _DEFAULT_MESSAGE)
            return await ctx.success(
                "Reset default autonuke message\n> -# **applies to all autonukes**"
            )

        script = message.script if hasattr(message, "script") else message
        await self._set_autonuke_default_message(ctx.guild.id, script)
        preview = script if len(script) <= 200 else script[:200] + "…"
        return await ctx.success(
            f"Default autonuke message updated\n> -# **applies to all autonukes**\n```\n{preview}\n```"
        )

    @autonuke.command(
        name="add",
        aliases=["create", "cr", "c", "a", "set"],
        description="schedule a channel to be nuked on an interval",
        example=",autonuke add #general 2h",
    )
    @has_permissions(administrator=True)
    async def autonuke_add(self, ctx, *, args: str = ""):
        """Schedule autonuke.

        Usage: autonuke add [channel] <interval> [custom embed script]
        Channel defaults to the current channel. If no script is given, the
        guild default autonuke message (from {ctx.cmd('autonuke message')}) is used.
        """
        tokens = args.split() if args else []
        channel: TextChannel = ctx.channel  # type: ignore[assignment]
        interval_seconds: int | None = None
        script_tokens: list[str] = []

        i = 0
        if tokens:
            try:
                channel = await TextChannelConverter().convert(ctx, tokens[0])
                i = 1
            except Exception:
                pass

        while i < len(tokens):
            tok = tokens[i]
            parsed = parse_duration_token(tok)
            if parsed is not None:
                interval_seconds = parsed
                i += 1
                break
            script_tokens.append(tok)
            i += 1

        script_tokens.extend(tokens[i:])

        if interval_seconds is None:
            for idx, tok in enumerate(list(script_tokens)):
                parsed = parse_duration_token(tok)
                if parsed is not None:
                    interval_seconds = parsed
                    script_tokens.pop(idx)
                    break

        if interval_seconds is None or interval_seconds < 60:
            raise CommandError(
                "Provide an interval of at least **60 seconds** "
                "(e.g. `2h`, `30m`, `1d`)"
            )

        if not isinstance(channel, TextChannel):
            raise CommandError("You can only schedule text channels")

        custom_script = " ".join(script_tokens).strip() or None
        if custom_script is None:
            message = await self._get_autonuke_default_message(ctx.guild.id)
        else:
            message = custom_script

        await self.db.execute(
            """INSERT INTO nuke (guild_id, channel_id, last_nuke, nuke_threshold, message)
               VALUES ($1, $2, $3, $4, $5)
               ON CONFLICT (guild_id, channel_id)
               DO UPDATE SET last_nuke = excluded.last_nuke,
                             nuke_threshold = excluded.nuke_threshold,
                             message = excluded.message""",
            ctx.guild.id,
            channel.id,
            datetime.now(timezone.utc).replace(tzinfo=None),
            int(interval_seconds),
            message,
        )
        preview = message if len(message) <= 120 else message[:120] + "…"
        return await ctx.success(
            f"Scheduled **autonuke** for {channel.mention}\n"
            f"> -# **every {naturaldelta(interval_seconds)}**\n"
            f"> -# **message:** `{preview}`"
        )

    @autonuke.command(
        name="remove",
        aliases=["delete", "del", "rem", "r", "d"],
        description="remove a scheduled autonuke",
        example=",autonuke remove #text",
    )
    @has_permissions(administrator=True)
    async def autonuke_remove(self, ctx, channel: Optional[TextChannel] = None):
        channel = channel or ctx.channel
        data = await self.db.fetchrow(
            """DELETE FROM nuke
               WHERE guild_id = $1 AND channel_id = $2 AND channel_id <> $3
               RETURNING *""",
            ctx.guild.id,
            channel.id,
            _DEFAULT_CHANNEL_ID,
        )
        if not data:
            raise CommandError("No scheduled autonuke found for this channel")
        return await ctx.success(f"Removed {channel.mention} from **autonuke**")

    @autonuke.command(
        name="list",
        aliases=["ls", "show", "view"],
        description="view all scheduled autonukes",
    )
    @has_permissions(administrator=True)
    async def autonuke_list(self, ctx):
        rows = await self.db.fetch(
            """SELECT channel_id, nuke_threshold, message, last_nuke
               FROM nuke
               WHERE guild_id = $1 AND channel_id <> $2""",
            ctx.guild.id,
            _DEFAULT_CHANNEL_ID,
        )
        if not rows:
            raise CommandError("No scheduled autonuke channels found")

        embed = Embed(title="Scheduled Autonukes")
        embed.set_author(name=str(ctx.author), icon_url=ctx.author.display_avatar.url)
        values = []
        i = 0
        for row in rows:
            ch = ctx.guild.get_channel(row["channel_id"])
            if not ch:
                continue
            i += 1
            msg = row["message"] or _DEFAULT_MESSAGE
            short = msg if len(msg) <= 40 else msg[:40] + "…"
            values.append(
                f"`{i}` {ch.mention} - every **{naturaldelta(row['nuke_threshold'])}**\n"
                f"> -# **message:** `{short}`"
            )
        if not values:
            raise CommandError("No scheduled autonuke channels found")
        return await ctx.paginate(embed, values)

    @autonuke.command(
        name="variables",
        aliases=["vars", "variable"],
        description="show variables available in nuke / autonuke embed scripts",
    )
    @has_permissions(administrator=True)
    async def autonuke_variables(self, ctx):
        return await self.nuke_variables.callback(self, ctx)

    @autonuke.group(
        name="change",
        aliases=["cfg", "edit", "update"],
        description="change an existing autonuke schedule (interval / script)",
        invoke_without_command=True,
        example=",autonuke change interval #general 1h",
    )
    @has_permissions(administrator=True)
    async def autonuke_change(self, ctx):
        return await ctx.send_help(ctx.command)

    @autonuke_change.command(
        name="interval",
        aliases=["time", "threshold", "ci"],
        description="change the autonuke interval for a channel",
        example=",autonuke change interval #general 2h",
        usage="[channel] <interval>",
    )
    @has_permissions(administrator=True)
    async def autonuke_change_interval(self, ctx, *, args: str = ""):
        tokens = args.split() if args else []
        channel: TextChannel = ctx.channel  # type: ignore[assignment]
        interval_token = None
        if tokens:
            try:
                channel = await TextChannelConverter().convert(ctx, tokens[0])
                rest = tokens[1:]
            except Exception:
                rest = tokens
            if rest:
                interval_token = rest[0]
        if not interval_token:
            raise CommandError(
                f"Provide an interval (e.g. `30m`, `2h`, `1d`)\n"
                f"Example: `{ctx.invoke_prefix}autonuke change interval #general 2h`"
            )
        seconds = parse_duration_token(interval_token)
        if seconds is None or seconds < 60:
            raise CommandError("Interval must be at least **60 seconds**")
        if not isinstance(channel, TextChannel):
            raise CommandError("You can only schedule text channels")
        existing = await self.db.fetchval(
            """SELECT 1 FROM nuke
               WHERE guild_id = $1 AND channel_id = $2 AND channel_id <> $3""",
            ctx.guild.id,
            channel.id,
            _DEFAULT_CHANNEL_ID,
        )
        if not existing:
            raise CommandError(
                f"No autonuke for {channel.mention} - use "
                f"`{ctx.invoke_prefix}autonuke add` first"
            )
        await self.db.execute(
            """UPDATE nuke SET nuke_threshold = $1
               WHERE guild_id = $2 AND channel_id = $3""",
            int(seconds),
            ctx.guild.id,
            channel.id,
        )
        return await ctx.success(
            f"Autonuke interval for {channel.mention} set to **{naturaldelta(seconds)}**"
        )

    @autonuke_change.command(
        name="script",
        aliases=["message", "embed", "msg"],
        description="change the autonuke message/script for a channel",
        example=",autonuke change script #general {embed}$v{description: wiped}",
        usage="[channel] <script>",
    )
    @has_permissions(administrator=True)
    async def autonuke_change_script(self, ctx, *, args: str = ""):
        tokens = args.split() if args else []
        channel: TextChannel = ctx.channel  # type: ignore[assignment]
        i = 0
        if tokens:
            try:
                channel = await TextChannelConverter().convert(ctx, tokens[0])
                i = 1
            except Exception:
                pass
        script = " ".join(tokens[i:]).strip()
        if not script:
            raise CommandError("Provide a nuke script/message")
        if not isinstance(channel, TextChannel):
            raise CommandError("You can only schedule text channels")
        existing = await self.db.fetchval(
            """SELECT 1 FROM nuke
               WHERE guild_id = $1 AND channel_id = $2 AND channel_id <> $3""",
            ctx.guild.id,
            channel.id,
            _DEFAULT_CHANNEL_ID,
        )
        if not existing:
            raise CommandError(f"No autonuke for {channel.mention}")
        await self.db.execute(
            """UPDATE nuke SET message = $1
               WHERE guild_id = $2 AND channel_id = $3""",
            script,
            ctx.guild.id,
            channel.id,
        )
        preview = script if len(script) <= 120 else script[:120] + "…"
        return await ctx.success(
            f"Autonuke script for {channel.mention} updated\n```\n{preview}\n```"
        )

    
    
    

    @tasks.loop(seconds=60.0)
    async def _autonuke_loop(self) -> None:
        if getattr(self.db, "pool", None) is None:
            return
        try:
            rows = await self.db.fetch(
                """SELECT guild_id, channel_id, last_nuke, nuke_threshold, message
                   FROM nuke
                   WHERE channel_id <> $1 AND nuke_threshold > 0""",
                _DEFAULT_CHANNEL_ID,
            )
        except Exception:
            return

        now = datetime.now(timezone.utc).replace(tzinfo=None)
        for row in rows:
            try:
                last = row["last_nuke"]
                threshold = int(row["nuke_threshold"] or 0)
                if threshold < 60:
                    continue
                if last is not None:
                    if getattr(last, "tzinfo", None) is not None:
                        last = last.replace(tzinfo=None)
                    elapsed = (now - last).total_seconds()
                    if elapsed < threshold:
                        continue

                guild = self.bot.get_guild(row["guild_id"])
                if guild is None:
                    continue
                channel = guild.get_channel(row["channel_id"])
                if channel is None or not isinstance(channel, TextChannel):
                    continue

                async with self._nuke_lock:
                    new_channel = await self._perform_nuke(
                        channel,
                        reason="Autonuke scheduled interval",
                        message=row["message"] or _DEFAULT_MESSAGE,
                        interval=threshold,
                    )
                    if new_channel is None:
                        continue
                    await self.db.execute(
                        """UPDATE nuke SET last_nuke = $1
                           WHERE guild_id = $2 AND channel_id = $3""",
                        now,
                        guild.id,
                        new_channel.id,
                    )
            except Exception:
                continue

    @_autonuke_loop.before_loop
    async def _before_autonuke_loop(self) -> None:
        await self.bot.wait_until_ready()
