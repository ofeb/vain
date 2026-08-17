from __future__ import annotations

import re
from typing import Optional, Union

import discord
from discord import (
    AutoModTrigger,
    AutoModRuleTriggerType,
    AutoModRuleEventType,
    AutoModRuleAction,
    Embed,
    TextChannel,
)
from discord.ext.commands import group, CommandError

from core.discord.package import Package
from core.managers.permissions import has_permissions
from core.tools.flags.automod import FilterFlags, SpamFilterFlags
from core.tools.human import human_join


BOT_RULE_PREFIX = "vain-filter"


def _bot_rules(guild: discord.Guild):
    """yield automod rules created by the bot"""
    return (
        r for r in guild.auto_moderation_rules
        if r.creator_id == guild.me.id
    )


def _find_rule(rules, *, name: str | None = None, trigger_type: int | None = None):
    """find a bot-created rule by name prefix and/or trigger type"""
    for r in rules:
        if name and not r.name.startswith(name):
            continue
        if trigger_type is not None and r.trigger.type.value != trigger_type:
            continue
        return r
    return None


class FilterCommands(Package):
    """chat filter management using Discord AutoMod + custom bot filters"""

    async def _get_automod_rules(self, guild: discord.Guild):
        """fetch all automod rules for the guild"""
        try:
            return list(await guild.fetch_automod_rules())
        except discord.HTTPException:
            return list(guild.auto_moderation_rules)

    async def _get_bot_rules(self, guild: discord.Guild):
        """fetch only bot-created automod rules"""
        rules = await self._get_automod_rules(guild)
        return [r for r in rules if r.creator_id == guild.me.id]

    @group(
        name="filter",
        aliases=["automod"],
        description="View a variety of options to help clean chat",
        invoke_without_command=True,
    )
    async def filter_(self, ctx):
        return await ctx.send_help()

    @filter_.command(
        name="reset",
        description="Reset all word filtered words. This can't be undone.",
    )
    @has_permissions(manage_guild=True)
    async def filter_reset(self, ctx):
        from core.discord.views.confirm import ConfirmView
        view = ConfirmView(ctx)
        ok = await view.prompt(
            "Clear **all** filtered words? This action **can't be undone**."
        )
        if not ok:
            return await ctx.warn("Cancelled\n> -# **no changes were made**")

        bot_rules = await self._get_bot_rules(ctx.guild)
        rule = _find_rule(bot_rules, trigger_type=AutoModRuleTriggerType.keyword.value)

        if not rule:
            raise CommandError("no word filter rule found")

        await rule.edit(
            trigger=AutoModTrigger(
                type=AutoModRuleTriggerType.keyword,
                keyword_filter=[],
            ),
            reason=f"filter reset by {ctx.author}",
        )
        return await ctx.success("Word filter cleared")

    @filter_.command(
        name="add",
        aliases=["create", "set", "c", "a"],
        description="add words to the filter",
        example=",filter add badword",
    )
    @has_permissions(manage_guild=True)
    async def filter_add(self, ctx, *, words):
        word_list = words if isinstance(words, list) else [words]
        if any(len(w) > 60 or len(w) < 1 for w in word_list):
            raise CommandError("each word must be 1–60 characters")

        bot_rules = await self._get_bot_rules(ctx.guild)
        rule = _find_rule(bot_rules, trigger_type=AutoModRuleTriggerType.keyword.value)

        if not rule:
            if len(word_list) > 1000:
                raise CommandError("can only filter 1000 words max")
            await ctx.guild.create_automod_rule(
                name=f"{BOT_RULE_PREFIX} - words",
                event_type=AutoModRuleEventType.message_send,
                trigger=AutoModTrigger(
                    type=AutoModRuleTriggerType.keyword,
                    keyword_filter=[f"*{w}*" for w in word_list],
                ),
                enabled=True,
                actions=[
                    AutoModRuleAction(
                        custom_message=f"blocked by {self.bot.user.name} - blacklisted word"
                    )
                ],
                reason=f"word filter by {ctx.author}",
            )
        else:
            kf = list(rule.trigger.keyword_filter or [])
            new = [f"*{w}*" for w in word_list]
            kf.extend(new)
            if len(kf) > 1000:
                raise CommandError("hit the 1000 word limit")
            await rule.edit(
                trigger=AutoModTrigger(
                    type=AutoModRuleTriggerType.keyword,
                    keyword_filter=kf,
                ),
                reason=f"filter updated by {ctx.author}",
            )

        return await ctx.success(
            f"added to word filter: {human_join(word_list, final='and', markdown='`')}"
        )

    @filter_.command(
        name="remove",
        aliases=["del", "delete", "d", "r", "rem"],
        description="remove words from the filter",
    )
    @has_permissions(manage_guild=True)
    async def filter_remove(self, ctx, *, words):
        word_list = words if isinstance(words, list) else [words]

        bot_rules = await self._get_bot_rules(ctx.guild)
        rule = _find_rule(bot_rules, trigger_type=AutoModRuleTriggerType.keyword.value)

        if not rule:
            raise CommandError("no word filter configured")

        kf = list(rule.trigger.keyword_filter or [])
        dropped = []
        for w in word_list:
            target = f"*{w.lower()}*"
            if target in kf:
                kf.remove(target)
                dropped.append(w.lower())

        if not dropped:
            return await ctx.warn(f"none of those words are filtered")

        await rule.edit(
            trigger=AutoModTrigger(
                type=AutoModRuleTriggerType.keyword,
                keyword_filter=kf,
            ),
            reason=f"filter edited by {ctx.author}",
        )
        return await ctx.success(
            f"removed: {human_join(dropped, final='and', markdown='`')}"
        )

    @filter_.command(
        name="list",
        aliases=["ls", "show", "view"],
        description="View a list of filtered words in guild",
    )
    @has_permissions(manage_guild=True)
    async def filter_list(self, ctx):
        bot_rules = await self._get_bot_rules(ctx.guild)
        rule = _find_rule(bot_rules, trigger_type=AutoModRuleTriggerType.keyword.value)

        if not rule:
            raise CommandError("no word filter configured")

        words = [w.replace("*", "") for w in (rule.trigger.keyword_filter or [])]
        if not words:
            return await ctx.warn("no words in the filter")

        embed = Embed(title="Filtered Words").set_author(
            name=str(ctx.author), icon_url=ctx.author.display_avatar.url
        )
        return await ctx.paginate(
            embed, [f"`{i}` {w}" for i, w in enumerate(words, start=1)]
        )

    

    @filter_.group(
        name="links",
        aliases=["urls"],
        description="Delete any message that contains a link",
        example=",filter links on",
        invoke_without_command=True,
    )
    @has_permissions(manage_guild=True)
    async def filter_links(self, ctx, setting: Optional[bool] = True, *, flags: FilterFlags = None):
        """toggle link filter using Discord AutoMod keyword rule"""
        bot_rules = await self._get_bot_rules(ctx.guild)
        existing = _find_rule(bot_rules, name=f"{BOT_RULE_PREFIX} - links")

        if setting:
            if existing:
                return await ctx.warn("link filter is already **enabled**")
            try:
                await ctx.guild.create_automod_rule(
                    name=f"{BOT_RULE_PREFIX} - links",
                    event_type=AutoModRuleEventType.message_send,
                    trigger=AutoModTrigger(
                        type=AutoModRuleTriggerType.keyword,
                        keyword_filter=["*://*"],
                    ),
                    enabled=True,
                    actions=[
                        AutoModRuleAction(
                            custom_message=f"links are not allowed in this channel"
                        )
                    ],
                    reason=f"link filter enabled by {ctx.author}",
                )
            except discord.HTTPException as e:
                raise CommandError(f"failed to create automod rule: {e}")
            return await ctx.success("link filter **enabled**\n> -# **applies to all channels**")
        else:
            if not existing:
                return await ctx.warn("link filter is already **disabled**")
            try:
                await existing.delete(reason=f"link filter disabled by {ctx.author}")
            except discord.HTTPException as e:
                raise CommandError(f"failed to delete automod rule: {e}")
            return await ctx.success("link filter **disabled**")

    @filter_links.command(
        name="whitelist",
        aliases=["wl", "allow", "al"],
        description="Whitelist domains from the link filter",
        example=",filter links whitelist https://safe.com",
    )
    @has_permissions(manage_guild=True)
    async def filter_links_whitelist(self, ctx, *, links):
        bot_rules = await self._get_bot_rules(ctx.guild)
        rule = _find_rule(bot_rules, name=f"{BOT_RULE_PREFIX} - links")

        if not rule:
            raise CommandError("link filter not configured, run `filter links on` first")

        link_list = links if isinstance(links, list) else [links]
        current_allow = list(rule.trigger.allow_list or [])
        current_allow.extend(link_list)
        current_allow = list(set(current_allow))

        await rule.edit(
            trigger=AutoModTrigger(
                type=AutoModRuleTriggerType.keyword,
                keyword_filter=rule.trigger.keyword_filter,
                allow_list=current_allow,
            ),
            reason=f"link whitelist updated by {ctx.author}",
        )
        return await ctx.success(
            f"whitelisted links\n> -# **{human_join(link_list, final='and')}**"
        )

    @filter_links.command(
        name="unwhitelist",
        aliases=["uwl", "removeallow", "ral"],
        description="Remove domains from the link whitelist",
    )
    @has_permissions(manage_guild=True)
    async def filter_links_unwhitelist(self, ctx, *, links):
        bot_rules = await self._get_bot_rules(ctx.guild)
        rule = _find_rule(bot_rules, name=f"{BOT_RULE_PREFIX} - links")

        if not rule:
            raise CommandError("link filter not configured")

        link_list = links if isinstance(links, list) else [links]
        current_allow = list(rule.trigger.allow_list or [])
        removed = []
        for link in link_list:
            if link in current_allow:
                current_allow.remove(link)
                removed.append(link)

        await rule.edit(
            trigger=AutoModTrigger(
                type=AutoModRuleTriggerType.keyword,
                keyword_filter=rule.trigger.keyword_filter,
                allow_list=current_allow,
            ),
            reason=f"link whitelist updated by {ctx.author}",
        )
        return await ctx.success(
            f"removed from whitelist: {human_join(removed or link_list, final='and', markdown='`')}"
        )

    

    @filter_.group(
        name="invites",
        aliases=["invite", "invs", "inv"],
        description="Delete any message that contains a Discord invite",
        example=",filter invites on",
        invoke_without_command=True,
    )
    @has_permissions(manage_guild=True)
    async def filter_invites(self, ctx, setting: Optional[bool] = True, *, flags: FilterFlags = None):
        """toggle invite filter using Discord AutoMod keyword rule"""
        bot_rules = await self._get_bot_rules(ctx.guild)
        existing = _find_rule(bot_rules, name=f"{BOT_RULE_PREFIX} - invites")

        if setting:
            if existing:
                return await ctx.warn("invite filter is already **enabled**")
            try:
                await ctx.guild.create_automod_rule(
                    name=f"{BOT_RULE_PREFIX} - invites",
                    event_type=AutoModRuleEventType.message_send,
                    trigger=AutoModTrigger(
                        type=AutoModRuleTriggerType.keyword,
                        keyword_filter=[
                            "*discord.gg/*",
                            "*discord.com/invite/*",
                            "*discordapp.com/invite/*",
                        ],
                    ),
                    enabled=True,
                    actions=[
                        AutoModRuleAction(
                            custom_message="Discord invites are not allowed"
                        )
                    ],
                    reason=f"invite filter enabled by {ctx.author}",
                )
            except discord.HTTPException as e:
                raise CommandError(f"failed to create automod rule: {e}")
            return await ctx.success("invite filter **enabled**\n> -# **applies to all channels**")
        else:
            if not existing:
                return await ctx.warn("invite filter is already **disabled**")
            try:
                await existing.delete(reason=f"invite filter disabled by {ctx.author}")
            except discord.HTTPException as e:
                raise CommandError(f"failed to delete automod rule: {e}")
            return await ctx.success("invite filter **disabled**")

    @filter_invites.command(
        name="whitelist",
        aliases=["wl", "allow", "al"],
        description="Whitelist specific invite codes",
    )
    @has_permissions(manage_guild=True)
    async def filter_invites_whitelist(self, ctx, *, invites):
        bot_rules = await self._get_bot_rules(ctx.guild)
        rule = _find_rule(bot_rules, name=f"{BOT_RULE_PREFIX} - invites")

        if not rule:
            raise CommandError("invite filter not configured, run `filter invites on` first")

        inv_list = invites if isinstance(invites, list) else [invites]
        current_allow = list(rule.trigger.allow_list or [])
        current_allow.extend(inv_list)
        current_allow = list(set(current_allow))

        await rule.edit(
            trigger=AutoModTrigger(
                type=AutoModRuleTriggerType.keyword,
                keyword_filter=rule.trigger.keyword_filter,
                allow_list=current_allow,
            ),
            reason=f"invite whitelist updated by {ctx.author}",
        )
        return await ctx.success(
            f"whitelisted invites\n> -# **{human_join(inv_list, final='and')}**"
        )

    @filter_invites.command(
        name="unwhitelist",
        aliases=["uwl", "removeallow", "ral"],
        description="Remove invite codes from the whitelist",
    )
    @has_permissions(manage_guild=True)
    async def filter_invites_unwhitelist(self, ctx, *, invites):
        bot_rules = await self._get_bot_rules(ctx.guild)
        rule = _find_rule(bot_rules, name=f"{BOT_RULE_PREFIX} - invites")

        if not rule:
            raise CommandError("invite filter not configured")

        inv_list = invites if isinstance(invites, list) else [invites]
        current_allow = list(rule.trigger.allow_list or [])
        removed = []
        for inv in inv_list:
            if inv in current_allow:
                current_allow.remove(inv)
                removed.append(inv)

        await rule.edit(
            trigger=AutoModTrigger(
                type=AutoModRuleTriggerType.keyword,
                keyword_filter=rule.trigger.keyword_filter,
                allow_list=current_allow,
            ),
            reason=f"invite whitelist updated by {ctx.author}",
        )
        return await ctx.success(
            f"removed from whitelist: {human_join(removed or inv_list, final='and', markdown='`')}"
        )

    

    @filter_.group(
        name="spam",
        aliases=["antispam", "flood", "flooding"],
        description="Delete messages from users that send messages too fast",
        example=",filter spam on --threshold 5",
        invoke_without_command=True,
    )
    @has_permissions(manage_guild=True)
    async def filter_spam(self, ctx, setting: Optional[bool] = True, *, flags: SpamFilterFlags = None):
        """toggle spam filter using Discord AutoMod spam trigger"""
        bot_rules = await self._get_bot_rules(ctx.guild)
        existing = _find_rule(bot_rules, name=f"{BOT_RULE_PREFIX} - spam")

        threshold = flags.threshold if flags else 5

        if setting:
            if existing:
                return await ctx.warn("spam filter is already **enabled**")
            try:
                await ctx.guild.create_automod_rule(
                    name=f"{BOT_RULE_PREFIX} - spam",
                    event_type=AutoModRuleEventType.message_send,
                    trigger=AutoModTrigger(
                        type=AutoModRuleTriggerType.spam,
                    ),
                    enabled=True,
                    actions=[
                        AutoModRuleAction(
                            custom_message="slow down, you are sending messages too fast"
                        )
                    ],
                    reason=f"spam filter enabled by {ctx.author}",
                )
            except discord.HTTPException as e:
                raise CommandError(f"failed to create automod rule: {e}")
            return await ctx.success(
                f"spam filter **enabled**\n> -# **Discord native spam detection**"
            )
        else:
            if not existing:
                return await ctx.warn("spam filter is already **disabled**")
            try:
                await existing.delete(reason=f"spam filter disabled by {ctx.author}")
            except discord.HTTPException as e:
                raise CommandError(f"failed to delete automod rule: {e}")
            return await ctx.success("spam filter **disabled**")

    

    @filter_.group(
        name="caps",
        description="Delete messages that contain too many uppercase characters",
        example=",filter caps on --threshold 70",
    )
    @has_permissions(manage_guild=True)
    async def filter_caps(self, ctx, setting: Optional[bool] = True, *, flags: FilterFlags = None):
        """toggle caps filter (custom bot filter)"""
        threshold = flags.threshold if flags else 70

        if setting:
            await self.db.execute(
                """INSERT INTO moderation.caps (guild_id, threshold, action)
                   VALUES($1, $2, $3)
                   ON CONFLICT(guild_id) DO UPDATE SET threshold = $2, action = $3""",
                ctx.guild.id, threshold, (flags.punishment if flags else "delete"),
            )
            return await ctx.success(
                f"caps filter **enabled**\n> -# **threshold: {threshold}%**"
            )
        else:
            await self.db.execute(
                """DELETE FROM moderation.caps WHERE guild_id = $1""",
                ctx.guild.id,
            )
            return await ctx.success("caps filter **disabled**")

    @filter_caps.group(
        name="exempt",
        aliases=["wl", "ex"],
        description="Exempt roles from the caps filter",
        invoke_without_command=True,
    )
    @has_permissions(manage_guild=True)
    async def filter_caps_exempt(self, ctx, *, roles):
        row = await self.db.fetchrow(
            """SELECT exempt_roles FROM moderation.caps WHERE guild_id = $1""",
            ctx.guild.id,
        )
        if not row:
            raise CommandError("caps filter not configured, run `filter caps on` first")
        current = list(set(row.exempt_roles or []))
        for r in roles:
            if r.id in current:
                current.remove(r.id)
            else:
                current.append(r.id)
        valid = [rid for rid in current if ctx.guild.get_role(rid)]
        await self.db.execute(
            """UPDATE moderation.caps SET exempt_roles = $1 WHERE guild_id = $2""",
            valid, ctx.guild.id,
        )
        mentions = [ctx.guild.get_role(rid).mention for rid in valid if ctx.guild.get_role(rid)]
        return await ctx.success(
            f"exempt roles: {human_join(mentions, final='and') if mentions else 'none'}"
        )

    @filter_caps_exempt.command(name="list", aliases=["ls", "show", "view"])
    @has_permissions(manage_guild=True)
    async def filter_caps_exempt_list(self, ctx):
        row = await self.db.fetchrow(
            """SELECT exempt_roles FROM moderation.caps WHERE guild_id = $1""",
            ctx.guild.id,
        )
        if not row or not row.exempt_roles:
            raise CommandError("no roles exempted from caps filter")
        roles = [ctx.guild.get_role(rid) for rid in row.exempt_roles if ctx.guild.get_role(rid)]
        embed = Embed(title="Caps Exempt Roles").set_author(
            name=str(ctx.author), icon_url=ctx.author.display_avatar.url
        )
        return await ctx.paginate(
            embed,
            [f"`{i}` {r.mention} (`{r.id}`)" for i, r in enumerate(roles, start=1)],
        )

    

    @filter_.group(
        name="spoilers",
        description="Delete any message exceeding the threshold for spoilers",
        example=",filter spoilers on --threshold 2",
    )
    @has_permissions(manage_guild=True)
    async def filter_spoilers(self, ctx, setting: Optional[bool] = True, *, flags: SpamFilterFlags = None):
        """toggle spoiler filter (custom bot filter)"""
        threshold = flags.threshold if flags else 5

        if setting:
            await self.db.execute(
                """INSERT INTO moderation.spoilers (guild_id, threshold, action)
                   VALUES($1, $2, $3)
                   ON CONFLICT(guild_id) DO UPDATE SET threshold = $2, action = $3""",
                ctx.guild.id, threshold, (flags.punishment if flags else "delete"),
            )
            return await ctx.success(
                f"spoiler filter **enabled**\n> -# **threshold: {threshold}**"
            )
        else:
            await self.db.execute(
                """DELETE FROM moderation.spoilers WHERE guild_id = $1""",
                ctx.guild.id,
            )
            return await ctx.success("spoiler filter **disabled**")

    @filter_spoilers.group(
        name="exempt",
        aliases=["wl", "ex"],
        description="Exempt roles from the spoilers filter",
        invoke_without_command=True,
    )
    @has_permissions(manage_guild=True)
    async def filter_spoilers_exempt(self, ctx, *, roles):
        row = await self.db.fetchrow(
            """SELECT exempt_roles FROM moderation.spoilers WHERE guild_id = $1""",
            ctx.guild.id,
        )
        if not row:
            raise CommandError("spoiler filter not configured, run `filter spoilers on` first")
        current = list(set((row.exempt_roles or []) + [r.id for r in roles]))
        valid = [rid for rid in current if ctx.guild.get_role(rid)]
        await self.db.execute(
            """UPDATE moderation.spoilers SET exempt_roles = $1 WHERE guild_id = $2""",
            valid, ctx.guild.id,
        )
        mentions = [ctx.guild.get_role(rid).mention for rid in valid if ctx.guild.get_role(rid)]
        return await ctx.success(
            f"exempt: {human_join(mentions, final='and') if mentions else 'none'}"
        )

    @filter_spoilers_exempt.command(name="list", aliases=["ls", "show", "view"])
    @has_permissions(manage_guild=True)
    async def filter_spoilers_exempt_list(self, ctx):
        row = await self.db.fetchrow(
            """SELECT exempt_roles FROM moderation.spoilers WHERE guild_id = $1""",
            ctx.guild.id,
        )
        if not row or not row.exempt_roles:
            raise CommandError("no roles exempted from spoiler filter")
        roles = [ctx.guild.get_role(rid) for rid in row.exempt_roles if ctx.guild.get_role(rid)]
        embed = Embed(title="Spoiler Exempt Roles").set_author(
            name=str(ctx.author), icon_url=ctx.author.display_avatar.url
        )
        return await ctx.paginate(
            embed,
            [f"`{i}` {r.mention} (`{r.id}`)" for i, r in enumerate(roles, start=1)],
        )

    

    @filter_.group(
        name="musicfiles",
        description="Delete any message that contains a music file",
        example=",filter musicfiles on",
    )
    @has_permissions(manage_guild=True)
    async def filter_musicfile(self, ctx, setting: Optional[bool] = True, *, flags: SpamFilterFlags = None):
        """toggle music file filter (custom bot filter)"""
        if setting:
            await self.db.execute(
                """INSERT INTO moderation.music (guild_id, action)
                   VALUES($1, $2)
                   ON CONFLICT(guild_id) DO UPDATE SET action = $2""",
                ctx.guild.id, (flags.punishment if flags else "delete"),
            )
            return await ctx.success("music file filter **enabled**")
        else:
            await self.db.execute(
                """DELETE FROM moderation.music WHERE guild_id = $1""",
                ctx.guild.id,
            )
            return await ctx.success("music file filter **disabled**")

    @filter_musicfile.group(
        name="exempt",
        aliases=["wl", "ex"],
        description="Exempt roles from the music files filter",
        invoke_without_command=True,
    )
    @has_permissions(manage_guild=True)
    async def filter_musicfile_exempt(self, ctx, *, roles):
        row = await self.db.fetchrow(
            """SELECT exempt_roles FROM moderation.music WHERE guild_id = $1""",
            ctx.guild.id,
        )
        if not row:
            raise CommandError("music file filter not configured, run `filter musicfiles on` first")
        current = list(set((row.exempt_roles or []) + [r.id for r in roles]))
        valid = [rid for rid in current if ctx.guild.get_role(rid)]
        await self.db.execute(
            """UPDATE moderation.music SET exempt_roles = $1 WHERE guild_id = $2""",
            valid, ctx.guild.id,
        )
        mentions = [ctx.guild.get_role(rid).mention for rid in valid if ctx.guild.get_role(rid)]
        return await ctx.success(
            f"exempt: {human_join(mentions, final='and') if mentions else 'none'}"
        )

    @filter_musicfile_exempt.command(name="list", aliases=["ls", "show", "view"])
    @has_permissions(manage_guild=True)
    async def filter_musicfile_exempt_list(self, ctx):
        row = await self.db.fetchrow(
            """SELECT exempt_roles FROM moderation.music WHERE guild_id = $1""",
            ctx.guild.id,
        )
        if not row or not row.exempt_roles:
            raise CommandError("no roles exempted from music file filter")
        roles = [ctx.guild.get_role(rid) for rid in row.exempt_roles if ctx.guild.get_role(rid)]
        embed = Embed(title="Music File Exempt Roles").set_author(
            name=str(ctx.author), icon_url=ctx.author.display_avatar.url
        )
        return await ctx.paginate(
            embed,
            [f"`{i}` {r.mention} (`{r.id}`)" for i, r in enumerate(roles, start=1)],
        )

    

    @filter_.group(
        name="massmention",
        aliases=["mm", "mention"],
        description="Delete any message exceeding the threshold for user mentions",
        example=",filter massmention on --threshold 5",
        invoke_without_command=True,
    )
    @has_permissions(manage_guild=True)
    async def filter_massmention(self, ctx, setting: Optional[bool] = True, *, flags: SpamFilterFlags = None):
        """toggle mass mention filter using Discord AutoMod mention_spam trigger"""
        bot_rules = await self._get_bot_rules(ctx.guild)
        existing = _find_rule(bot_rules, name=f"{BOT_RULE_PREFIX} - mentions")

        threshold = flags.threshold if flags else 5

        if setting:
            if existing:
                return await ctx.warn("mass mention filter is already **enabled**")
            try:
                await ctx.guild.create_automod_rule(
                    name=f"{BOT_RULE_PREFIX} - mentions",
                    event_type=AutoModRuleEventType.message_send,
                    trigger=AutoModTrigger(
                        type=AutoModRuleTriggerType.mention_spam,
                        mention_total_limit=threshold,
                    ),
                    enabled=True,
                    actions=[
                        AutoModRuleAction(
                            custom_message="too many mentions in one message"
                        )
                    ],
                    reason=f"mass mention filter enabled by {ctx.author}",
                )
            except discord.HTTPException as e:
                raise CommandError(f"failed to create automod rule: {e}")
            return await ctx.success(
                f"mass mention filter **enabled**\n> -# **threshold: {threshold} mentions**"
            )
        else:
            if not existing:
                return await ctx.warn("mass mention filter is already **disabled**")
            try:
                await existing.delete(reason=f"mass mention filter disabled by {ctx.author}")
            except discord.HTTPException as e:
                raise CommandError(f"failed to delete automod rule: {e}")
            return await ctx.success("mass mention filter **disabled**")

    

    @filter_.group(
        name="emoji",
        aliases=["emojis", "emote", "emotes"],
        description="Delete any message exceeding the threshold for emojis",
        example=",filter emoji on --threshold 5",
        invoke_without_command=True,
    )
    @has_permissions(manage_guild=True)
    async def filter_emoji(self, ctx, setting: Optional[bool] = True, *, flags: SpamFilterFlags = None):
        """toggle emoji filter (custom bot filter)"""
        threshold = flags.threshold if flags else 5

        if setting:
            await self.db.execute(
                """INSERT INTO moderation.emoji (guild_id, threshold, action)
                   VALUES($1, $2, $3)
                   ON CONFLICT(guild_id) DO UPDATE SET threshold = $2, action = $3""",
                ctx.guild.id, threshold, (flags.punishment if flags else "delete"),
            )
            return await ctx.success(
                f"emoji filter **enabled**\n> -# **threshold: {threshold}**"
            )
        else:
            await self.db.execute(
                """DELETE FROM moderation.emoji WHERE guild_id = $1""",
                ctx.guild.id,
            )
            return await ctx.success("emoji filter **disabled**")

    @filter_emoji.group(
        name="exempt",
        aliases=["wl", "ex"],
        description="Exempt roles from the emoji filter",
        invoke_without_command=True,
    )
    @has_permissions(manage_guild=True)
    async def filter_emoji_exempt(self, ctx, *, roles):
        row = await self.db.fetchrow(
            """SELECT exempt_roles FROM moderation.emoji WHERE guild_id = $1""",
            ctx.guild.id,
        )
        if not row:
            raise CommandError("emoji filter not configured, run `filter emoji on` first")
        current = list(set((row.exempt_roles or []) + [r.id for r in roles]))
        valid = [rid for rid in current if ctx.guild.get_role(rid)]
        await self.db.execute(
            """UPDATE moderation.emoji SET exempt_roles = $1 WHERE guild_id = $2""",
            valid, ctx.guild.id,
        )
        mentions = [ctx.guild.get_role(rid).mention for rid in valid if ctx.guild.get_role(rid)]
        return await ctx.success(
            f"exempt: {human_join(mentions, final='and') if mentions else 'none'}"
        )

    @filter_emoji_exempt.command(name="list", aliases=["ls", "show", "view"])
    @has_permissions(manage_guild=True)
    async def filter_emoji_exempt_list(self, ctx):
        row = await self.db.fetchrow(
            """SELECT exempt_roles FROM moderation.emoji WHERE guild_id = $1""",
            ctx.guild.id,
        )
        if not row or not row.exempt_roles:
            raise CommandError("no roles exempted from emoji filter")
        roles = [ctx.guild.get_role(rid) for rid in row.exempt_roles if ctx.guild.get_role(rid)]
        embed = Embed(title="Emoji Exempt Roles").set_author(
            name=str(ctx.author), icon_url=ctx.author.display_avatar.url
        )
        return await ctx.paginate(
            embed,
            [f"`{i}` {r.mention} (`{r.id}`)" for i, r in enumerate(roles, start=1)],
        )

    

    @filter_.group(
        name="regex",
        aliases=["re"],
        description="add or toggle regex patterns",
        example=r",filter regex \b\d+\.\d+\b",
        invoke_without_command=True,
    )
    @has_permissions(manage_guild=True)
    async def filter_regex(self, ctx, pattern: str, *, flags: FilterFlags = None):
        """toggle a regex pattern (custom bot filter)"""
        try:
            re.compile(pattern)
        except re.error as e:
            raise CommandError(f"invalid regex: {e}")

        existing = await self.db.fetchrow(
            """SELECT id FROM moderation.regex WHERE guild_id = $1 AND regex = $2""",
            ctx.guild.id, pattern,
        )
        if existing:
            await self.db.execute(
                """DELETE FROM moderation.regex WHERE guild_id = $1 AND regex = $2""",
                ctx.guild.id, pattern,
            )
            return await ctx.success(f"removed regex\n> -# **`{pattern}`**")

        await self.db.execute(
            """INSERT INTO moderation.regex (guild_id, regex, action)
               VALUES($1, $2, $3)
               ON CONFLICT(guild_id, regex) DO UPDATE SET action = $3""",
            ctx.guild.id, pattern, (flags.punishment if flags else "delete"),
        )
        return await ctx.success(
            f"added regex\n> -# **`{pattern}`** · {(flags.punishment if flags else 'delete')}"
        )

    @filter_regex.command(name="list", aliases=["ls", "show", "view"])
    @has_permissions(manage_guild=True)
    async def filter_regex_list(self, ctx):
        rows = await self.db.fetch(
            "SELECT regex FROM moderation.regex WHERE guild_id = $1",
            ctx.guild.id,
        )
        if not rows:
            raise CommandError("no regex patterns configured")
        patterns = [r.regex for r in rows]
        embed = Embed(title="Regex Patterns").set_author(
            name=str(ctx.author), icon_url=ctx.author.display_avatar.url
        )
        return await ctx.paginate(
            embed, [f"`{i}` **{p}**" for i, p in enumerate(patterns, start=1)]
        )

    @filter_regex.group(
        name="exempt",
        aliases=["wl", "ex"],
        description="exempt roles from regex filter",
        invoke_without_command=True,
    )
    @has_permissions(manage_guild=True)
    async def filter_regex_exempt(self, ctx, *, roles):
        row = await self.db.fetchrow(
            """SELECT exempt_roles FROM moderation.regex WHERE guild_id = $1 LIMIT 1""",
            ctx.guild.id,
        )
        current = list(row.exempt_roles or []) if row else []
        updated = list(set(current + [r.id for r in roles]))
        valid = [rid for rid in updated if ctx.guild.get_role(rid)]
        await self.db.execute(
            """UPDATE moderation.regex SET exempt_roles = $1 WHERE guild_id = $2""",
            valid, ctx.guild.id,
        )
        mentions = [ctx.guild.get_role(rid).mention for rid in valid if ctx.guild.get_role(rid)]
        return await ctx.success(
            f"exempt: {human_join(mentions, final='and') if mentions else 'none'}"
        )

    @filter_regex_exempt.command(name="list", aliases=["ls", "show", "view"])
    @has_permissions(manage_guild=True)
    async def filter_regex_exempt_list(self, ctx):
        row = await self.db.fetchrow(
            """SELECT exempt_roles FROM moderation.regex WHERE guild_id = $1 LIMIT 1""",
            ctx.guild.id,
        )
        current = list(row.exempt_roles or []) if row else []
        if not current:
            raise CommandError("no roles exempted from regex filter")
        roles = [ctx.guild.get_role(rid) for rid in current if ctx.guild.get_role(rid)]
        embed = Embed(title="Regex Exempt Roles").set_author(
            name=str(ctx.author), icon_url=ctx.author.display_avatar.url
        )
        return await ctx.paginate(
            embed,
            [f"`{i}` {r.mention} (`{r.id}`)" for i, r in enumerate(roles, start=1)],
        )
