from __future__ import annotations

import discord

from core.discord.package import Package


class AntiraidEvents:
    @Package.listener()
    async def on_member_join(self, member: discord.Member) -> None:
        if member.guild is None:
            return

        if await self.db.consume_antiraid_whitelist(member.guild.id, member.id):
            return

        now = datetime.now(timezone.utc)
        cfg = await self._cached_config(member.guild.id)
        log = self.join_log[member.guild.id]
        log.append((now, member.id))
        cutoff = now - timedelta(seconds=MASSJOIN_WINDOW)
        while log and log[0][0] < cutoff:
            log.popleft()

        if cfg.punish_until and cfg.punish_until <= now:
            cfg = await self._set_punish_window(member.guild.id, None)

        if (
            cfg.raid_active
            and cfg.massjoin.enabled
            and cfg.massjoin.punish_new
            and cfg.punish_until
            and cfg.punish_until > now
        ):
            await self._sanction_member(
                member,
                cfg.massjoin.action or "ban",
                reason="antiraid: massjoin window active",
            )
            return

        if cfg.massjoin.enabled and len(log) >= cfg.massjoin.threshold and not cfg.raid_active:
            await self._toggle_raid(member.guild.id, True)
            if cfg.massjoin.lock_channels:
                await self._disable_chat(member.guild)
            if cfg.massjoin.punish_new:
                await self._set_punish_window(
                    member.guild.id,
                    now + timedelta(minutes=10),
                )

            for target in await self._build_member_list(member.guild, log):
                await self._sanction_member(
                    target,
                    cfg.massjoin.action or "ban",
                    reason="antiraid: massjoin limit hit",
                )
            log.clear()

        if member.bot:
            return

        cfg = await self._cached_config(member.guild.id)
        if cfg.avatar.enabled and member.avatar is None:
            await self._sanction_member(
                member,
                cfg.avatar.action or "kick",
                reason="antiraid: no avatar",
            )
            return

        if cfg.newaccounts.enabled:
            age = now - member.created_at
            if age < timedelta(days=cfg.newaccounts.threshold):
                await self._sanction_member(
                    member,
                    cfg.newaccounts.action or "ban",
                    reason="antiraid: account too new",
                )

