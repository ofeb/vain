from __future__ import annotations

import contextlib
import re
from datetime import datetime, timezone, timedelta

import discord
from discord.ext import commands
from discord.ext.commands import group

from core.discord.package import Package
from core.discord.views.embed import c2
from core.managers.permissions import has_permissions
from core.tools.moderation_args import parse_duration_seconds, is_duration_token


_PUNISHMENTS = ("none", "ban", "softban", "hardban", "warn", "timeout")


class Highlight(Package):
    """Keyword highlights with optional log destination and punishment."""

    def __init__(self, bot):
        super().__init__(bot)

    async def cog_load(self) -> None:
        await self._ensure_schema()
        await super().cog_load()

    async def _ensure_schema(self) -> None:
        await self.bot.db.execute(
            """
            CREATE TABLE IF NOT EXISTS highlights (
                guild_id BIGINT NOT NULL,
                user_id BIGINT NOT NULL,
                keyword TEXT NOT NULL,
                PRIMARY KEY (guild_id, user_id, keyword)
            )
            """
        )
        await self.bot.db.execute(
            """
            CREATE TABLE IF NOT EXISTS highlight_ignores (
                guild_id BIGINT NOT NULL,
                user_id BIGINT NOT NULL,
                target_id BIGINT NOT NULL,
                target_type TEXT NOT NULL,
                PRIMARY KEY (guild_id, user_id, target_id, target_type)
            )
            """
        )
        await self.bot.db.execute(
            """
            CREATE TABLE IF NOT EXISTS highlight_config (
                guild_id BIGINT PRIMARY KEY,
                log_type TEXT NOT NULL DEFAULT 'dm',
                log_channel_id BIGINT,
                punishment TEXT NOT NULL DEFAULT 'none',
                timeout_seconds INTEGER,
                delete_after_seconds INTEGER
            )
            """
        )

    async def _get_config(self, guild_id: int) -> dict:
        await self._ensure_schema()
        row = await self.bot.db.fetchrow(
            "SELECT * FROM highlight_config WHERE guild_id = $1",
            guild_id,
        )
        if row:
            return dict(row)
        return {
            "guild_id": guild_id,
            "log_type": "dm",
            "log_channel_id": None,
            "punishment": "none",
            "timeout_seconds": None,
            "delete_after_seconds": None,
        }

    @group(
        name="highlight",
        aliases=["hl"],
        description="Set notifications for when a keyword is said",
        invoke_without_command=True,
    )
    @has_permissions(guild_owner=True)
    async def highlight(self, ctx):
        return await ctx.send_help(ctx.command)

    @highlight.command(name="add", description="Add a highlighted keyword")
    async def highlight_add(self, ctx, *, keyword: str):
        kw = keyword.strip().lower()
        if not kw:
            return await ctx.warn("Provide a keyword")
        await self.bot.db.execute(
            "INSERT INTO highlights (guild_id, user_id, keyword) VALUES($1, $2, $3) "
            "ON CONFLICT(guild_id, user_id, keyword) DO NOTHING",
            ctx.guild.id,
            ctx.author.id,
            kw,
        )
        return await ctx.success(f"Added keyword\n> -# **keyword:** `{kw}`")

    @highlight.command(name="remove", description="Remove a highlighted keyword", aliases=["rm", "del"])
    async def highlight_remove(self, ctx, *, keyword: str):
        kw = keyword.strip().lower()
        await self.bot.db.execute(
            "DELETE FROM highlights WHERE guild_id = $1 AND user_id = $2 AND keyword = $3",
            ctx.guild.id,
            ctx.author.id,
            kw,
        )
        return await ctx.success(f"Removed keyword\n> -# **keyword:** `{kw}`")

    @highlight.command(name="list", description="List all your highlighted keywords", aliases=["ls"])
    async def highlight_list(self, ctx):
        rows = await self.bot.db.fetch(
            "SELECT keyword FROM highlights WHERE guild_id = $1 AND user_id = $2",
            ctx.guild.id,
            ctx.author.id,
        )
        if not rows:
            return await ctx.warn(
                "You have no keywords set\n"
                f"> -# **add one with:** {ctx.cmd('highlight add <keyword>')}"
            )
        keywords = [f"`{h['keyword']}`" for h in rows]
        return await ctx.success(f"Your keywords\n{', '.join(keywords)}")

    @highlight.command(name="reset", description="Remove all your highlighted keywords")
    async def highlight_reset(self, ctx):
        await self.bot.db.execute(
            "DELETE FROM highlights WHERE guild_id = $1 AND user_id = $2",
            ctx.guild.id,
            ctx.author.id,
        )
        return await ctx.success("Cleared all your highlighted keywords")

    @highlight.command(
        name="type",
        description="Where highlight logs are sent (dm or channel)",
        example=",highlight type channel #logs",
    )
    @has_permissions(manage_guild=True)
    async def highlight_type(self, ctx, kind: str = None, channel: discord.TextChannel = None):
        """Set highlight log destination: dm or channel."""
        if not kind:
            cfg = await self._get_config(ctx.guild.id)
            if cfg["log_type"] == "channel" and cfg.get("log_channel_id"):
                return await ctx.normal(
                    f"Highlight logs go to <#{cfg['log_channel_id']}>\n"
                    f"> -# **change with:** {ctx.cmd('highlight type dm')} or "
                    f"{ctx.cmd('highlight type channel #channel')}"
                )
            return await ctx.normal(
                "Highlight logs are sent via **DM**\n"
                f"> -# **change with:** {ctx.cmd('highlight type channel #channel')}"
            )

        kind = kind.strip().lower()
        if kind in {"dm", "dms", "direct"}:
            await self.bot.db.execute(
                """
                INSERT INTO highlight_config (guild_id, log_type, log_channel_id)
                VALUES ($1, 'dm', NULL)
                ON CONFLICT (guild_id) DO UPDATE
                  SET log_type = 'dm', log_channel_id = NULL
                """,
                ctx.guild.id,
            )
            return await ctx.success("Highlight logs will be sent via **DM**")

        if kind in {"channel", "ch", "log", "logs"}:
            dest = channel
            if dest is None and ctx.message.channel_mentions:
                dest = ctx.message.channel_mentions[0]
            if dest is None:
                return await ctx.warn(
                    "Provide a channel\n"
                    f"> -# **usage:** {ctx.cmd('highlight type channel #channel')}"
                )
            await self.bot.db.execute(
                """
                INSERT INTO highlight_config (guild_id, log_type, log_channel_id)
                VALUES ($1, 'channel', $2)
                ON CONFLICT (guild_id) DO UPDATE
                  SET log_type = 'channel', log_channel_id = $2
                """,
                ctx.guild.id,
                dest.id,
            )
            return await ctx.success(f"Highlight logs will post in {dest.mention}")

        return await ctx.warn(
            "Type must be **dm** or **channel**\n"
            f"> -# **usage:** {ctx.cmd('highlight type dm')} · "
            f"{ctx.cmd('highlight type channel #channel')}"
        )

    @highlight.command(
        name="punishment",
        aliases=["punish", "action"],
        description="Punishment when a highlighted keyword is used",
        example=",highlight punishment timeout 10m --delete 5s",
    )
    @has_permissions(manage_guild=True)
    async def highlight_punishment(self, ctx, *, args: str = None):
        """Set punishment: ban, softban, hardban, warn, timeout <amount>, or none.
        Optional --delete <duration> to delete the triggering message after that delay.
        """
        if not args or not str(args).strip():
            cfg = await self._get_config(ctx.guild.id)
            pun = cfg.get("punishment") or "none"
            extra = ""
            if pun == "timeout" and cfg.get("timeout_seconds"):
                extra = f" ({cfg['timeout_seconds']}s)"
            delete_info = "off"
            if cfg.get("delete_after_seconds"):
                delete_info = f"{cfg['delete_after_seconds']}s"
            return await ctx.normal(
                f"Highlight punishment is **{pun}**{extra}\n"
                f"> -# **delete after:** {delete_info}\n"
                f"> -# **set with:** {ctx.cmd('highlight punishment timeout 10m --delete 5s')}"
            )

        tokens = args.split()
        delete_after = None
        
        cleaned = []
        i = 0
        while i < len(tokens):
            tok = tokens[i]
            low = tok.lower()
            if low in {"--delete", "-delete", "--del", "-del"}:
                if i + 1 < len(tokens) and is_duration_token(tokens[i + 1]):
                    delete_after = parse_duration_seconds(tokens[i + 1])
                    i += 2
                    continue
                
                delete_after = 0
                i += 1
                continue
            if low.startswith("--delete=") or low.startswith("-delete="):
                raw = tok.split("=", 1)[1]
                if is_duration_token(raw):
                    delete_after = parse_duration_seconds(raw)
                i += 1
                continue
            cleaned.append(tok)
            i += 1

        if not cleaned:
            return await ctx.warn(
                "Provide a punishment\n"
                f"> -# **options:** `none` `ban` `softban` `hardban` `warn` `timeout <amount>`"
            )

        action = cleaned[0].lower()
        timeout_seconds = None

        if action in {"none", "off", "disable"}:
            action = "none"
        elif action in {"ban", "softban", "hardban", "warn"}:
            pass
        elif action == "timeout":
            if len(cleaned) < 2 or not is_duration_token(cleaned[1]):
                return await ctx.warn(
                    "Provide a timeout duration\n"
                    f"> -# **usage:** {ctx.cmd('highlight punishment timeout 10m')}"
                )
            timeout_seconds = parse_duration_seconds(cleaned[1])
            if not timeout_seconds or timeout_seconds < 1:
                return await ctx.warn("Invalid timeout duration")
        else:
            
            return await ctx.warn(
                f"Unknown punishment `{action}`\n"
                f"> -# **options:** `none` `ban` `softban` `hardban` `warn` `timeout <amount>`"
            )

        await self.bot.db.execute(
            """
            INSERT INTO highlight_config (
                guild_id, punishment, timeout_seconds, delete_after_seconds
            ) VALUES ($1, $2, $3, $4)
            ON CONFLICT (guild_id) DO UPDATE SET
                punishment = $2,
                timeout_seconds = $3,
                delete_after_seconds = $4
            """,
            ctx.guild.id,
            action,
            timeout_seconds,
            delete_after,
        )

        bits = [f"Highlight punishment set to **{action}**"]
        if timeout_seconds:
            bits.append(f"> -# **timeout:** {timeout_seconds}s")
        if delete_after is not None:
            bits.append(f"> -# **delete after:** {delete_after}s")
        else:
            bits.append("> -# **delete after:** off")
        return await ctx.success("\n".join(bits))

    @highlight.command(name="ignore", description="Ignore highlights from a member, role, or channel")
    async def highlight_ignore(self, ctx, target: discord.Role | discord.Member | discord.TextChannel):
        if isinstance(target, discord.Member):
            ttype, label = "user", target.mention
        elif isinstance(target, discord.Role):
            ttype, label = "role", target.mention
        else:
            ttype, label = "channel", target.mention
        await self.bot.db.execute(
            "INSERT INTO highlight_ignores (guild_id, user_id, target_id, target_type) "
            "VALUES ($1, $2, $3, $4) ON CONFLICT DO NOTHING",
            ctx.guild.id,
            ctx.author.id,
            target.id,
            ttype,
        )
        return await ctx.success(f"Ignoring highlights from {label}")

    @highlight.command(name="unignore", description="Stop ignoring a member, role, or channel")
    async def highlight_unignore(self, ctx, target: discord.Role | discord.Member | discord.TextChannel):
        if isinstance(target, discord.Member):
            ttype = "user"
        elif isinstance(target, discord.Role):
            ttype = "role"
        else:
            ttype = "channel"
        await self.bot.db.execute(
            "DELETE FROM highlight_ignores WHERE guild_id = $1 AND user_id = $2 "
            "AND target_id = $3 AND target_type = $4",
            ctx.guild.id,
            ctx.author.id,
            target.id,
            ttype,
        )
        return await ctx.success(f"No longer ignoring {target.mention}")

    @highlight.command(name="ignorelist", aliases=["ignores"], description="List ignored targets")
    async def highlight_ignore_list(self, ctx):
        ignores = await self.bot.db.fetch(
            "SELECT target_id, target_type FROM highlight_ignores "
            "WHERE guild_id = $1 AND user_id = $2",
            ctx.guild.id,
            ctx.author.id,
        )
        if not ignores:
            return await ctx.warn(
                "You aren't ignoring anyone\n"
                f"> -# **ignore with:** {ctx.cmd('highlight ignore <target>')}"
            )
        lines = []
        for ignore in ignores:
            if ignore["target_type"] == "user":
                member = ctx.guild.get_member(ignore["target_id"])
                if member:
                    lines.append(f"> {member.mention} (user)")
            elif ignore["target_type"] == "role":
                role = ctx.guild.get_role(ignore["target_id"])
                if role:
                    lines.append(f"> {role.mention} (role)")
            elif ignore["target_type"] == "channel":
                channel = ctx.guild.get_channel(ignore["target_id"])
                if channel:
                    lines.append(f"> {channel.mention} (channel)")
        if not lines:
            return await ctx.warn("All ignored targets are gone from this server")
        return await ctx.success("Ignored targets\n" + "\n".join(lines))

    async def _is_ignored(self, guild: discord.Guild, owner_id: int, message: discord.Message) -> bool:
        rows = await self.bot.db.fetch(
            "SELECT target_id, target_type FROM highlight_ignores "
            "WHERE guild_id = $1 AND user_id = $2",
            guild.id,
            owner_id,
        )
        if not rows:
            return False
        author = message.author
        channel_id = message.channel.id
        role_ids = {r.id for r in getattr(author, "roles", [])} if isinstance(author, discord.Member) else set()
        for row in rows:
            if row["target_type"] == "user" and row["target_id"] == author.id:
                return True
            if row["target_type"] == "channel" and row["target_id"] == channel_id:
                return True
            if row["target_type"] == "role" and row["target_id"] in role_ids:
                return True
        return False

    def _build_log_embed(
        self,
        *,
        keyword: str,
        message: discord.Message,
        owner: discord.abc.User | None = None,
    ):
        author = message.author
        content = (message.content or "").strip() or "*no text*"
        if len(content) > 900:
            content = content[:897] + "..."
        
        pattern = re.compile(re.escape(keyword), re.IGNORECASE)
        shown = pattern.sub(lambda m: f"**{m.group(0)}**", content)
        lines = [
            f"**Keyword** `{keyword}` was mentioned",
            f"> -# **author:** {author.mention} (`{author.id}`)",
            f"> -# **channel:** {message.channel.mention}",
            f"> -# **message:** [jump]({message.jump_url})",
            "",
            shown,
        ]
        return c2(
            message="\n".join(lines),
            footer=f"{author}",
            timestamp=True,
        )

    async def _apply_punishment(self, message: discord.Message, cfg: dict) -> None:
        action = (cfg.get("punishment") or "none").lower()
        if action == "none":
            return
        member = message.author
        if not isinstance(member, discord.Member):
            return
        if member.bot or member.guild_permissions.administrator:
            return
        guild = message.guild
        me = guild.me
        if me is None:
            return
        reason = "Highlight keyword punishment"

        try:
            if action == "warn":
                
                with contextlib.suppress(Exception):
                    await message.channel.send(
                        f"{member.mention} was **warned** for using a highlighted keyword.",
                        delete_after=8,
                    )
            elif action == "timeout":
                secs = int(cfg.get("timeout_seconds") or 60)
                until = datetime.now(timezone.utc) + timedelta(seconds=secs)
                await member.timeout(until, reason=reason)
            elif action == "ban":
                await member.ban(reason=reason, delete_message_days=0)
            elif action == "hardban":
                await member.ban(reason=reason, delete_message_days=7)
            elif action == "softban":
                uid = member.id
                await member.ban(reason=reason, delete_message_days=1)
                await guild.unban(discord.Object(id=uid), reason="Highlight softban")
        except Exception:
            pass

        delete_after = cfg.get("delete_after_seconds")
        if delete_after is not None:
            try:
                import asyncio
                delay = max(0, int(delete_after))
                if delay > 0:
                    await asyncio.sleep(delay)
                await message.delete()
            except Exception:
                pass

    @Package.listener()
    async def on_message(self, message: discord.Message) -> None:
        if message.author.bot or not message.guild or not message.content:
            return
        
        rows = await self.bot.db.fetch(
            "SELECT user_id, keyword FROM highlights WHERE guild_id = $1",
            message.guild.id,
        )
        if not rows:
            return

        content_lower = message.content.lower()
        
        hits: dict[str, set[int]] = {}
        for row in rows:
            kw = row["keyword"]
            if kw and kw in content_lower:
                hits.setdefault(kw, set()).add(row["user_id"])
        if not hits:
            return

        cfg = await self._get_config(message.guild.id)

        
        notified: set[int] = set()
        for keyword, user_ids in hits.items():
            for uid in user_ids:
                if uid == message.author.id or uid in notified:
                    continue
                if await self._is_ignored(message.guild, uid, message):
                    continue
                notified.add(uid)
                embed = self._build_log_embed(keyword=keyword, message=message)
                if cfg.get("log_type") == "channel" and cfg.get("log_channel_id"):
                    ch = message.guild.get_channel(cfg["log_channel_id"])
                    if ch is not None:
                        with contextlib.suppress(Exception):
                            await ch.send(content=f"<@{uid}>", embed=embed)
                        continue
                
                user = self.bot.get_user(uid)
                if user is None:
                    with contextlib.suppress(Exception):
                        user = await self.bot.fetch_user(uid)
                if user is not None:
                    with contextlib.suppress(Exception):
                        await user.send(embed=embed)

        
        await self._apply_punishment(message, cfg)
