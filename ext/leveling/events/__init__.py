from __future__ import annotations

import json
import logging
import random
import time
from collections import defaultdict
from typing import TYPE_CHECKING

import discord

from core.discord.package import Package

if TYPE_CHECKING:
    from core.vain import Vain

log = logging.getLogger("vain.leveling.events")


XP_COOLDOWN = 45.0
XP_MIN = 15
XP_MAX = 25
_COOLDOWN_PRUNE_EVERY = 500


class LevelingEvents:
    """Grant XP on messages when leveling is enabled for the guild."""

    def __init__(self, bot: "Vain" = None, *args, **kwargs):
        
        if bot is not None and not hasattr(self, "bot"):
            self.bot = bot
        self._xp_cd: dict[tuple[int, int], float] = {}
        self._xp_cd_ops = 0

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
            if ignored_roles and any(r.id in ignored_roles for r in message.author.roles):
                return
            
            if cfg.get("command"):
                prefixes = tuple(
                    p
                    for p in (
                        getattr(self.bot, "command_prefix", None),
                        ",",
                        "!",
                        ".",
                        "?",
                    )
                    if isinstance(p, str)
                )
                content = (message.content or "").lstrip()
                if content.startswith(prefixes):
                    
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
                await self._on_level_up(message, cfg, level)
        except Exception:
            log.exception(
                "xp grant failed guild=%s user=%s",
                getattr(message.guild, "id", None),
                message.author.id,
            )

    async def _on_level_up(
        self, message: discord.Message, cfg: dict, level: int
    ) -> None:
        member = message.author
        guild = message.guild
        assert guild is not None

        
        try:
            rewards = await self.bot.db.fetch(
                "SELECT role_id, level FROM level_rewards WHERE guild_id = $1 AND level <= $2",
                guild.id,
                level,
            )
            if rewards:
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
                else:
                    
                    highest = max(rewards, key=lambda r: int(r["level"]))
                    role = guild.get_role(int(highest["role_id"]))
                    if role and role not in member.roles:
                        try:
                            await member.add_roles(role, reason="Level reward")
                        except Exception:
                            pass
        except Exception:
            pass

        script = cfg.get("message")
        if not script or str(script).strip().lower() == "none":
            return

        
        ch_id = cfg.get("channel_id")
        if ch_id == 0:
            dest = member  
        elif ch_id:
            dest = guild.get_channel(int(ch_id)) or message.channel
        else:
            dest = message.channel

        text = (
            str(script)
            .replace("{level}", str(level))
            .replace("{user}", member.mention)
            .replace("{user.mention}", member.mention)
            .replace("{user.name}", member.name)
            .replace("{guild}", guild.name)
            .replace("{guild.name}", guild.name)
        )
        try:
            await self.bot.send_embed(
                dest, text, member=member, user=member, guild=guild, channel=message.channel
            )
        except Exception:
            try:
                await dest.send(content=text[:2000])
            except Exception:
                pass
