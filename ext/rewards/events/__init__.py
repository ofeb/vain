from __future__ import annotations

import asyncio
import json
import logging
import random
import time
from collections import defaultdict
from typing import TYPE_CHECKING, Any, Optional

import discord

from core.discord.package import Package

if TYPE_CHECKING:
    from core.vain import Vain

log = logging.getLogger("vain.leveling.events")


XP_COOLDOWN = 45.0
XP_MIN = 15
XP_MAX = 25
_COOLDOWN_PRUNE_EVERY = 500

LevelDest = discord.abc.Messageable


class LevelingEvents:
    """Grant XP on messages when leveling is enabled for the guild."""

    def __init__(self, bot: Optional["Vain"] = None, *args: Any, **kwargs: Any):
        if bot is not None and not hasattr(self, "bot"):
            self.bot = bot
        self._xp_cd: dict[tuple[int, int], float] = {}
        self._xp_cd_ops = 0
        if not hasattr(self, "_xp_locks"):
            self._xp_locks: dict[int, asyncio.Lock] = defaultdict(asyncio.Lock)

    def _calc_target(self, level: int) -> int:
        return max(int((100 * int(level) + 1) ** 0.9), 50)

    def _parse_list(self, raw) -> set[int]:
        if not raw:
            return set()
        if isinstance(raw, list):
            return {int(x) for x in raw}
        try:
            data = json.loads(raw)
            if isinstance(data, list):
                return {int(x) for x in data}
        except Exception:
            pass
        return set()

    def _prune_cooldowns(self, now: float) -> None:
        self._xp_cd_ops += 1
        if self._xp_cd_ops < _COOLDOWN_PRUNE_EVERY:
            return
        self._xp_cd_ops = 0
        cutoff = now - (XP_COOLDOWN * 4)
        dead = [k for k, ts in self._xp_cd.items() if ts < cutoff]
        for k in dead:
            self._xp_cd.pop(k, None)

    def _looks_like_command(self, message: discord.Message) -> bool:
        content = (message.content or "").lstrip()
        if not content:
            return False
        # Mentions as prefix: "<@bot> help"
        me = getattr(message.guild, "me", None) or getattr(self.bot, "user", None)
        if me is not None and (
            content.startswith(f"<@{me.id}>") or content.startswith(f"<@!{me.id}>")
        ):
            return True
        for pfx in (",", "!", ".", "?", ";", "-"):
            if content.startswith(pfx):
                return True
        return False

    def _render_level_message(
        self,
        script: str,
        *,
        member: discord.abc.User,
        guild: Optional[discord.Guild],
        level: int,
        xp: Any = None,
        target_xp: Any = None,
    ) -> str:
        """Apply level-specific placeholders. Longer keys first so {user} cannot
        clobber {user.mention} / {user.name}."""
        text = str(script)
        pairs = [
            ("{user.mention}", member.mention),
            ("{user.name}", getattr(member, "name", str(member))),
            ("{user.display_name}", getattr(member, "display_name", getattr(member, "name", str(member)))),
            ("{user.id}", str(member.id)),
            ("{user}", member.mention),
            ("{member.mention}", member.mention),
            ("{member.name}", getattr(member, "name", str(member))),
            ("{member}", member.mention),
            ("{level}", str(level)),
        ]
        if xp is not None:
            pairs.append(("{xp}", str(int(float(xp)))))
        if target_xp is not None:
            pairs.append(("{target_xp}", str(int(target_xp))))
        if guild is not None:
            pairs.extend(
                [
                    ("{guild.name}", guild.name),
                    ("{guild.id}", str(guild.id)),
                    ("{guild}", guild.name),
                ]
            )
        # Longest placeholder first
        for key, value in sorted(pairs, key=lambda kv: len(kv[0]), reverse=True):
            text = text.replace(key, value)
        return text

    async def _resolve_level_destination(
        self,
        *,
        guild: discord.Guild,
        cfg: Any,
        fallback: Optional[discord.abc.Messageable] = None,
        member: Optional[discord.abc.User] = None,
    ) -> Optional[LevelDest]:
        """Where level-up messages should go.

        channel_id semantics:
          None  → current/fallback channel (\"any\")
          0     → DM the member
          int   → that guild text channel / thread (never silently post elsewhere)
        """
        ch_id = cfg.get("channel_id") if hasattr(cfg, "get") else None
        if ch_id is None and hasattr(cfg, "__getitem__"):
            try:
                ch_id = cfg["channel_id"]
            except Exception:
                ch_id = None

        if ch_id == 0 or ch_id == "0":
            return member  # type: ignore[return-value]

        if ch_id not in (None, "", 0):
            try:
                cid = int(ch_id)
            except (TypeError, ValueError):
                return fallback

            dest: Any = None
            getter = getattr(guild, "get_channel_or_thread", None)
            if callable(getter):
                dest = getter(cid)
            if dest is None:
                dest = guild.get_channel(cid)
            if dest is None:
                # Cache miss / uncached thread — try API
                try:
                    fetched = await self.bot.fetch_channel(cid)
                    fetched_guild = getattr(fetched, "guild", None)
                    if fetched_guild is None or getattr(fetched_guild, "id", None) == guild.id:
                        dest = fetched
                except Exception:
                    dest = None
            if dest is None:
                log.warning(
                    "level-up channel %s missing in guild %s — message not sent",
                    cid,
                    guild.id,
                )
                return None
            if not hasattr(dest, "send"):
                log.warning(
                    "level-up channel %s is not messageable in guild %s",
                    cid,
                    guild.id,
                )
                return None
            return dest  # type: ignore[return-value]

        return fallback

    async def _send_level_message(
        self,
        dest: Any,
        script: str,
        *,
        member: discord.abc.User,
        guild: Optional[discord.Guild],
        level: int,
        source_channel: Optional[discord.abc.Messageable] = None,
        xp: Any = None,
        target_xp: Any = None,
    ) -> Optional[discord.Message]:
        text = self._render_level_message(
            script,
            member=member,
            guild=guild,
            level=level,
            xp=xp,
            target_xp=target_xp,
        )
        channel_ctx = source_channel
        if channel_ctx is None and isinstance(
            dest, (discord.TextChannel, discord.Thread, discord.VoiceChannel)
        ):
            channel_ctx = dest

        try:
            return await self.bot.send_embed(
                dest,
                text,
                member=member,
                user=member,
                guild=guild,
                channel=channel_ctx,
            )
        except Exception as first:
            log.debug("send_embed level-up failed: %s", first, exc_info=True)
            try:
                return await dest.send(content=text[:2000])
            except Exception as second:
                log.warning(
                    "level-up message failed dest=%r guild=%s: %s",
                    getattr(dest, "id", dest),
                    getattr(guild, "id", None),
                    second,
                )
                return None

    @Package.listener("on_message")
    async def on_leveling_message(self, message: discord.Message) -> None:
        if message.author.bot or not message.guild:
            return
        if not isinstance(message.author, discord.Member):
            return
        if not message.content and not message.attachments:
            return

        guild_id = message.guild.id
        user_id = message.author.id
        now = time.monotonic()
        key = (guild_id, user_id)
        last = self._xp_cd.get(key, 0.0)
        if now - last < XP_COOLDOWN:
            return

        lock = self._xp_locks[user_id]
        async with lock:
            # Re-check cooldown under lock so concurrent messages don't double-grant
            now = time.monotonic()
            last = self._xp_cd.get(key, 0.0)
            if now - last < XP_COOLDOWN:
                return

            try:
                cfg = await self.bot.db.fetchrow(
                    "SELECT * FROM leveling WHERE guild_id = $1",
                    guild_id,
                )
                if not cfg:
                    return

                ignored_users = self._parse_list(cfg.get("users"))
                ignored_roles = self._parse_list(cfg.get("roles"))
                ignored_channels = self._parse_list(cfg.get("channels"))
                if user_id in ignored_users:
                    return
                if message.channel.id in ignored_channels:
                    return
                if ignored_roles and any(
                    r.id in ignored_roles for r in message.author.roles
                ):
                    return

                if cfg.get("command") and self._looks_like_command(message):
                    return

                self._xp_cd[key] = now
                self._prune_cooldowns(now)

                multi = float(cfg.get("multiplier") or 1.0)
                if getattr(message.author, "premium_since", None):
                    multi *= float(cfg.get("booster") or 1.0)

                try:
                    role_rows = await self.bot.db.fetch(
                        "SELECT role_id, multiplier FROM level_multiplier WHERE guild_id = $1",
                        guild_id,
                    )
                    best = 1.0
                    member_role_ids = {r.id for r in message.author.roles}
                    for row in role_rows or []:
                        if int(row["role_id"]) in member_role_ids:
                            best = max(best, float(row["multiplier"] or 1.0))
                    multi *= best
                except Exception:
                    pass

                gained = max(1, int(random.randint(XP_MIN, XP_MAX) * multi))

                row = await self.bot.db.fetchrow(
                    "SELECT xp, level, target_xp FROM level_user WHERE guild_id = $1 AND user_id = $2",
                    guild_id,
                    user_id,
                )
                if row:
                    xp = float(row["xp"] or 0) + gained
                    level = int(row["level"] or 1)
                    target = int(row["target_xp"] or self._calc_target(level))
                else:
                    xp = float(gained)
                    level = 1
                    target = self._calc_target(1)

                leveled = False
                safety = 0
                while xp >= target and safety < 50:
                    xp -= target
                    level += 1
                    target = self._calc_target(level)
                    leveled = True
                    safety += 1

                await self.bot.db.execute(
                    """
                    INSERT INTO level_user (guild_id, user_id, xp, level, target_xp)
                    VALUES ($1, $2, $3, $4, $5)
                    ON CONFLICT (guild_id, user_id) DO UPDATE SET
                        xp = EXCLUDED.xp,
                        level = EXCLUDED.level,
                        target_xp = EXCLUDED.target_xp
                    """,
                    guild_id,
                    user_id,
                    xp,
                    level,
                    target,
                )

                if leveled:
                    await self._on_level_up(
                        message, cfg, level, xp=xp, target_xp=target
                    )
            except Exception:
                log.exception(
                    "xp grant failed guild=%s user=%s",
                    getattr(message.guild, "id", None),
                    message.author.id,
                )

    async def _apply_level_rewards(
        self,
        member: discord.Member,
        guild: discord.Guild,
        cfg: Any,
        level: int,
    ) -> None:
        rewards = await self.bot.db.fetch(
            "SELECT role_id, level FROM level_rewards WHERE guild_id = $1 AND level <= $2",
            guild.id,
            level,
        )
        if not rewards:
            return

        stack = bool(cfg.get("stack"))
        if stack:
            to_add = []
            for r in rewards:
                role = guild.get_role(int(r["role_id"]))
                if role and role not in member.roles:
                    to_add.append(role)
            if to_add:
                try:
                    await member.add_roles(*to_add, reason="Level reward")
                except Exception:
                    pass
            return

        # Highest reward only — drop lower reward roles when present
        by_level: dict[int, list[discord.Role]] = {}
        for r in rewards:
            role = guild.get_role(int(r["role_id"]))
            if role is not None:
                by_level.setdefault(int(r["level"]), []).append(role)
        if not by_level:
            return
        highest = max(by_level)
        keep = set(by_level[highest])
        remove = []
        for lv, roles in by_level.items():
            if lv == highest:
                continue
            for role in roles:
                if role in member.roles and role not in keep:
                    remove.append(role)
        if remove:
            try:
                await member.remove_roles(*remove, reason="Level reward (highest only)")
            except Exception:
                pass
        to_add = [role for role in keep if role not in member.roles]
        if to_add:
            try:
                await member.add_roles(*to_add, reason="Level reward")
            except Exception:
                pass

    async def _on_level_up(
        self,
        message: discord.Message,
        cfg: Any,
        level: int,
        *,
        xp: Any = None,
        target_xp: Any = None,
    ) -> None:
        member = message.author
        guild = message.guild
        if guild is None or not isinstance(member, discord.Member):
            return

        try:
            await self._apply_level_rewards(member, guild, cfg, level)
        except Exception:
            log.exception(
                "level rewards failed guild=%s user=%s level=%s",
                guild.id,
                member.id,
                level,
            )

        script = cfg.get("message")
        if not script or str(script).strip().lower() == "none":
            return

        dest = await self._resolve_level_destination(
            guild=guild,
            cfg=cfg,
            fallback=message.channel,
            member=member,
        )
        if dest is None:
            return

        await self._send_level_message(
            dest,
            str(script),
            member=member,
            guild=guild,
            level=level,
            source_channel=message.channel,
            xp=xp,
            target_xp=target_xp,
        )
