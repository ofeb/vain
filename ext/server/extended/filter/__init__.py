from __future__ import annotations

import contextlib
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
from .settings import Settings


BOT_RULE_PREFIX = "vain-filter"


def _bot_rules(guild: discord.Guild):
    """yield automod rules created by the bot"""
    return (
        r for r in guild.auto_moderation_rules
        if r.creator_id == guild.me.id
    )


def _find_rule(rules, *, name: str | None = None, trigger_type: int | None = None):
    """find a bot-created rule by exact/prefix name and/or trigger type.

    Prefer exact name match when ``name`` is given so keyword-type rules
    (words / links / invites) do not collide with each other.
    """
    if name:
        exact = None
        prefix = None
        for r in rules:
            if r.name == name:
                exact = r
                break
            if prefix is None and r.name.startswith(name):
                if trigger_type is not None and r.trigger.type.value != trigger_type:
                    continue
                prefix = r
        return exact or prefix
    for r in rules:
        if trigger_type is not None and r.trigger.type.value != trigger_type:
            continue
        return r
    return None


WORDS_RULE = f"{BOT_RULE_PREFIX} - words"
LINKS_RULE = f"{BOT_RULE_PREFIX} - links"
INVITES_RULE = f"{BOT_RULE_PREFIX} - invites"
SPAM_RULE = f"{BOT_RULE_PREFIX} - spam"
MENTIONS_RULE = f"{BOT_RULE_PREFIX} - mentions"

INVITE_KEYWORDS = [
    "*discord.gg/*",
    "*discord.com/invite/*",
    "*discordapp.com/invite/*",
    "*.gg/*",
]


def _normalize_invite_code(raw: str) -> str:
    """Extract a bare invite code from a user-supplied token."""
    s = (raw or "").strip()
    if not s:
        return ""
    lower = s.lower()
    for prefix in (
        "https://discord.gg/",
        "http://discord.gg/",
        "discord.gg/",
        "https://discord.com/invite/",
        "http://discord.com/invite/",
        "discord.com/invite/",
        "https://discordapp.com/invite/",
        "http://discordapp.com/invite/",
        "discordapp.com/invite/",
        ".gg/",
        "/",
    ):
        if lower.startswith(prefix):
            s = s[len(prefix):]
            break
    
    s = s.split("?")[0].split("#")[0].strip().strip("/")
    return s


def _invite_allow_entries(code: str) -> list[str]:
    """Build AutoMod allow_list entries that cover all invite forms for a code."""
    code = _normalize_invite_code(code)
    if not code:
        return []
    
    entries = {
        code,
        f"*{code}*",
        f"discord.gg/{code}",
        f"*discord.gg/{code}*",
        f"discord.com/invite/{code}",
        f"*discord.com/invite/{code}*",
        f"discordapp.com/invite/{code}",
        f"*discordapp.com/invite/{code}*",
        f".gg/{code}",
        f"*.gg/{code}*",
        f"/{code}",
        f"*/{code}*",
    }
    
    return [e for e in entries if 1 <= len(e) <= 60]


def _link_allow_entries(raw: str) -> list[str]:
    """Normalize a domain/url into AutoMod allow_list entries."""
    s = (raw or "").strip()
    if not s:
        return []
    lower = s.lower()
    for prefix in ("https://", "http://"):
        if lower.startswith(prefix):
            s = s[len(prefix):]
            lower = s.lower()
            break
    s = s.split("/")[0].split("?")[0].strip().strip(".")
    if not s:
        return []
    entries = {s, f"*{s}*", f"*://{s}*", f"*://*.{s}*"}
    return [e for e in entries if 1 <= len(e) <= 60]



class FilterCommands(Package):
    """chat filter management using Discord AutoMod + custom bot filters"""

    async def _ensure_words_table(self) -> None:
        settings = Settings(self.bot, None)  # type: ignore[arg-type]
        await settings.ensure_words_table()

    async def cog_load(self) -> None:
        await self._ensure_words_table()

    def _split_words(self, words) -> list[str]:
        """Split user input into individual filter words."""
        if isinstance(words, list):
            raw = " ".join(str(w) for w in words)
        else:
            raw = str(words or "")
        
        parts = []
        for chunk in raw.replace(",", " ").split():
            w = chunk.strip().lower()
            if w:
                parts.append(w)
        return parts

    async def _sync_words_automod(self, guild: discord.Guild, words: list[str], *, author) -> None:
        """Keep the Discord AutoMod keyword rule in sync with the DB word list."""
        bot_rules = await self._get_bot_rules(guild)
        rule = _find_rule(bot_rules, name=WORDS_RULE)
        keywords = [f"*{w}*" for w in words]
        try:
            if not words:
                if rule:
                    await rule.delete(reason=f"word filter cleared by {author}")
                return
            if not rule:
                await guild.create_automod_rule(
                    name=WORDS_RULE,
                    event_type=AutoModRuleEventType.message_send,
                    trigger=AutoModTrigger(
                        type=AutoModRuleTriggerType.keyword,
                        keyword_filter=keywords[:1000],
                    ),
                    enabled=True,
                    actions=[
                        AutoModRuleAction(
                            custom_message=f"blocked by {self.bot.user.name} - blacklisted word"
                        )
                    ],
                    reason=f"word filter by {author}",
                )
            else:
                await rule.edit(
                    trigger=AutoModTrigger(
                        type=AutoModRuleTriggerType.keyword,
                        keyword_filter=keywords[:1000],
                        allow_list=list(rule.trigger.allow_list or []),
                    ),
                    enabled=True,
                    reason=f"filter updated by {author}",
                )
        except discord.HTTPException:
            
            pass

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
        description="view a variety of options to help clean chat",
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

        settings = Settings(self.bot, ctx.guild)
        await settings.clear_filter_words(ctx.guild.id)
        for cog in self.bot.cogs.values():
            if hasattr(cog, "_words_cache"):
                cog._words_cache.pop(ctx.guild.id, None)
        bot_rules = await self._get_bot_rules(ctx.guild)
        rule = _find_rule(bot_rules, name=WORDS_RULE)
        if rule:
            try:
                await rule.delete(reason=f"filter reset by {ctx.author}")
            except discord.HTTPException:
                with contextlib.suppress(discord.HTTPException):
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
        await self._ensure_words_table()
        word_list = self._split_words(words)
        if not word_list:
            raise CommandError("provide at least one word")
        if any(len(w) > 60 or len(w) < 1 for w in word_list):
            raise CommandError("each word must be 1–60 characters")

        settings = Settings(self.bot, ctx.guild)
        for w in word_list:
            await settings.add_filter_words(ctx.guild.id, [w])

        all_words = await settings.fetch_filter_words(ctx.guild.id)
        if len(all_words) > 1000:
            raise CommandError("can only filter 1000 words max")

        await self._sync_words_automod(ctx.guild, all_words, author=ctx.author)

        
        try:
            events = self.bot.get_cog("FilterEvents") or self.bot.get_cog("Filter")
            if events is not None and hasattr(events, "_words_cache"):
                events._words_cache.pop(ctx.guild.id, None)
            
            for cog in self.bot.cogs.values():
                if hasattr(cog, "_words_cache"):
                    cog._words_cache.pop(ctx.guild.id, None)
        except Exception:
            pass

        return await ctx.success(
            f"added to word filter: {human_join(word_list, final='and', markdown='`')}\n> -# **applies to everyone** except members with **Administrator**"
        )

    @filter_.command(
        name="remove",
        aliases=["del", "delete", "d", "r", "rem"],
        description="remove words from the filter",
    )
    @has_permissions(manage_guild=True)
    async def filter_remove(self, ctx, *, words):
        await self._ensure_words_table()
        word_list = self._split_words(words)
        if not word_list:
            raise CommandError("provide at least one word")

        settings = Settings(self.bot, ctx.guild)
        dropped = []
        for w in word_list:
            result = await settings.remove_filter_words(ctx.guild.id, [w])
            dropped.extend(result)

        remaining = await settings.fetch_filter_words(ctx.guild.id)
        actually_dropped = [w for w in word_list if w not in remaining]
        if not actually_dropped:
            return await ctx.warn("none of those words are filtered")

        await self._sync_words_automod(ctx.guild, list(remaining), author=ctx.author)
        for cog in self.bot.cogs.values():
            if hasattr(cog, "_words_cache"):
                cog._words_cache.pop(ctx.guild.id, None)

        return await ctx.success(
            f"removed: {human_join(actually_dropped, final='and', markdown='`')}"
        )

    @filter_.command(
        name="list",
        aliases=["ls", "show", "view"],
        description="view a list of filtered words in guild",
    )
    @has_permissions(manage_guild=True)
    async def filter_list(self, ctx):
        await self._ensure_words_table()
        settings = Settings(self.bot, ctx.guild)
        words = await settings.fetch_filter_words(ctx.guild.id)
        if not words:
            
            bot_rules = await self._get_bot_rules(ctx.guild)
            rule = _find_rule(bot_rules, name=WORDS_RULE)
            if rule:
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
        description="delete any message that contains a link",
        example=",filter links on",
        invoke_without_command=True,
    )
    @has_permissions(manage_guild=True)
    async def filter_links(self, ctx, setting: Optional[bool] = True, *, flags: FilterFlags = None):
        """toggle link filter using Discord AutoMod keyword rule"""
        bot_rules = await self._get_bot_rules(ctx.guild)
        existing = _find_rule(bot_rules, name=LINKS_RULE)

        if setting:
            if existing:
                return await ctx.warn("link filter is already **enabled**")
            try:
                await ctx.guild.create_automod_rule(
                    name=LINKS_RULE,
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
        description="whitelist domains from the link filter",
        example=",filter links whitelist https://safe.com",
    )
    @has_permissions(manage_guild=True)
    async def filter_links_whitelist(self, ctx, *, links):
        bot_rules = await self._get_bot_rules(ctx.guild)
        rule = _find_rule(bot_rules, name=LINKS_RULE)

        if not rule:
            raise CommandError("link filter not configured, run `filter links on` first")

        link_list = links if isinstance(links, list) else [links]
        domains = []
        entries: list[str] = []
        for raw in link_list:
            for e in _link_allow_entries(str(raw)):
                entries.append(e)
            label = str(raw).strip()
            for prefix in ("https://", "http://"):
                if label.lower().startswith(prefix):
                    label = label[len(prefix):]
            label = label.split("/")[0].strip()
            if label:
                domains.append(label)

        if not entries:
            raise CommandError("provide at least one domain (e.g. `youtube.com`)")

        current_allow = list(rule.trigger.allow_list or [])
        existing = {a.lower() for a in current_allow}
        for e in entries:
            if e.lower() not in existing:
                current_allow.append(e)
                existing.add(e.lower())
        if len(current_allow) > 100:
            current_allow = current_allow[:100]

        await rule.edit(
            trigger=AutoModTrigger(
                type=AutoModRuleTriggerType.keyword,
                keyword_filter=list(rule.trigger.keyword_filter or ["*://*"]),
                allow_list=current_allow,
            ),
            enabled=True,
            reason=f"link whitelist updated by {ctx.author}",
        )
        return await ctx.success(
            f"whitelisted links\n> -# **{human_join(domains or link_list, final='and', markdown='`')}**"
        )

    @filter_links.command(
        name="unwhitelist",
        aliases=["uwl", "removeallow", "ral"],
        description="remove domains from the link whitelist",
    )
    @has_permissions(manage_guild=True)
    async def filter_links_unwhitelist(self, ctx, *, links):
        bot_rules = await self._get_bot_rules(ctx.guild)
        rule = _find_rule(bot_rules, name=LINKS_RULE)

        if not rule:
            raise CommandError("link filter not configured")

        link_list = links if isinstance(links, list) else [links]
        drop_set: set[str] = set()
        labels = []
        for raw in link_list:
            for e in _link_allow_entries(str(raw)):
                drop_set.add(e.lower())
            drop_set.add(str(raw).strip().lower())
            labels.append(str(raw).strip())

        current_allow = list(rule.trigger.allow_list or [])
        kept = [a for a in current_allow if a.lower() not in drop_set]

        await rule.edit(
            trigger=AutoModTrigger(
                type=AutoModRuleTriggerType.keyword,
                keyword_filter=list(rule.trigger.keyword_filter or ["*://*"]),
                allow_list=kept,
            ),
            reason=f"link whitelist updated by {ctx.author}",
        )
        return await ctx.success(
            f"removed from whitelist: {human_join(labels or link_list, final='and', markdown='`')}"
        )

    @filter_.group(
        name="invites",
        aliases=["invite", "invs", "inv"],
        description="delete any message that contains a discord invite",
        example=",filter invites on",
        invoke_without_command=True,
    )
    @has_permissions(manage_guild=True)
    async def filter_invites(self, ctx, setting: Optional[bool] = True, *, flags: FilterFlags = None):
        """toggle invite filter using Discord AutoMod keyword rule"""
        bot_rules = await self._get_bot_rules(ctx.guild)
        existing = _find_rule(bot_rules, name=INVITES_RULE)

        if setting:
            if existing:
                return await ctx.warn("invite filter is already **enabled**")
            try:
                await ctx.guild.create_automod_rule(
                    name=INVITES_RULE,
                    event_type=AutoModRuleEventType.message_send,
                    trigger=AutoModTrigger(
                        type=AutoModRuleTriggerType.keyword,
                        keyword_filter=list(INVITE_KEYWORDS),
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
        description="whitelist specific invite codes",
    )
    @has_permissions(manage_guild=True)
    async def filter_invites_whitelist(self, ctx, *, invites):
        bot_rules = await self._get_bot_rules(ctx.guild)
        rule = _find_rule(bot_rules, name=INVITES_RULE)

        if not rule:
            raise CommandError("invite filter not configured, run `filter invites on` first")

        inv_list = invites if isinstance(invites, list) else [invites]
        codes = []
        entries: list[str] = []
        for raw in inv_list:
            code = _normalize_invite_code(str(raw))
            if not code:
                continue
            codes.append(code)
            entries.extend(_invite_allow_entries(code))

        if not codes:
            raise CommandError("provide at least one invite code (e.g. `bars` or `discord.gg/bars`)")

        current_allow = list(rule.trigger.allow_list or [])
        existing = {a.lower() for a in current_allow}
        for e in entries:
            if e.lower() not in existing:
                current_allow.append(e)
                existing.add(e.lower())

        
        if len(current_allow) > 100:
            current_allow = current_allow[:100]

        await rule.edit(
            trigger=AutoModTrigger(
                type=AutoModRuleTriggerType.keyword,
                keyword_filter=list(rule.trigger.keyword_filter or INVITE_KEYWORDS),
                allow_list=current_allow,
            ),
            enabled=True,
            reason=f"invite whitelist updated by {ctx.author}",
        )
        return await ctx.success(
            f"whitelisted invites\n> -# **{human_join(codes, final='and', markdown='`')}**"
        )

    @filter_invites.command(
        name="unwhitelist",
        aliases=["uwl", "removeallow", "ral"],
        description="remove invite codes from the whitelist",
    )
    @has_permissions(manage_guild=True)
    async def filter_invites_unwhitelist(self, ctx, *, invites):
        bot_rules = await self._get_bot_rules(ctx.guild)
        rule = _find_rule(bot_rules, name=INVITES_RULE)

        if not rule:
            raise CommandError("invite filter not configured")

        inv_list = invites if isinstance(invites, list) else [invites]
        codes = []
        drop_set: set[str] = set()
        for raw in inv_list:
            code = _normalize_invite_code(str(raw))
            if not code:
                continue
            codes.append(code)
            for e in _invite_allow_entries(code):
                drop_set.add(e.lower())
            drop_set.add(code.lower())
            drop_set.add(str(raw).strip().lower())

        current_allow = list(rule.trigger.allow_list or [])
        kept = [a for a in current_allow if a.lower() not in drop_set]
        removed = codes or [str(x) for x in inv_list]

        await rule.edit(
            trigger=AutoModTrigger(
                type=AutoModRuleTriggerType.keyword,
                keyword_filter=list(rule.trigger.keyword_filter or INVITE_KEYWORDS),
                allow_list=kept,
            ),
            reason=f"invite whitelist updated by {ctx.author}",
        )
        return await ctx.success(
            f"removed from whitelist: {human_join(removed, final='and', markdown='`')}"
        )

    

    @filter_.group(
        name="spam",
        aliases=["antispam", "flood", "flooding"],
        description="delete messages from users that send messages too fast",
        example=",filter spam on --threshold 5",
        invoke_without_command=True,
    )
    @has_permissions(manage_guild=True)
    async def filter_spam(self, ctx, setting: Optional[bool] = True, *, flags: SpamFilterFlags = None):
        """toggle spam filter using Discord AutoMod spam trigger"""
        bot_rules = await self._get_bot_rules(ctx.guild)
        existing = _find_rule(bot_rules, name=SPAM_RULE)

        threshold = flags.threshold if flags else 5

        if setting:
            if existing:
                return await ctx.warn("spam filter is already **enabled**")
            try:
                await ctx.guild.create_automod_rule(
                    name=SPAM_RULE,
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
        description="delete messages that contain too many uppercase characters",
        example=",filter caps on --threshold 70",
    )
    @has_permissions(manage_guild=True)
    async def filter_caps(self, ctx, setting: Optional[bool] = True, *, flags: FilterFlags = None):
        """toggle caps filter (custom bot filter)"""
        threshold = flags.threshold if flags else 70

        settings = Settings(self.bot, ctx.guild)
        if setting:
            await settings.upsert_module(
                "caps",
                threshold=threshold,
                action=(flags.punishment if flags else "delete"),
            )
            return await ctx.success(
                f"caps filter **enabled**\n> -# **threshold: {threshold}%**"
            )
        else:
            await settings.delete_module("caps")
            return await ctx.success("caps filter **disabled**")

    @filter_caps.group(
        name="exempt",
        aliases=["wl", "ex"],
        description="exempt roles from the caps filter",
        invoke_without_command=True,
    )
    @has_permissions(manage_guild=True)
    async def filter_caps_exempt(self, ctx, *, roles):
        settings = Settings(self.bot, ctx.guild)
        current = await settings.get_exempt_roles("caps", ctx.guild.id)
        if not current:
            raise CommandError("caps filter not configured, run `filter caps on` first")
        current_set = set(current)
        for r in roles:
            if r.id in current_set:
                current_set.remove(r.id)
            else:
                current_set.add(r.id)
        valid = [rid for rid in current_set if ctx.guild.get_role(rid)]
        await settings.set_exempt_roles("caps", ctx.guild.id, valid)
        mentions = [ctx.guild.get_role(rid).mention for rid in valid if ctx.guild.get_role(rid)]
        return await ctx.success(
            f"exempt roles: {human_join(mentions, final='and') if mentions else 'none'}"
        )

    @filter_caps_exempt.command(name="list", aliases=["ls", "show", "view"])
    @has_permissions(manage_guild=True)
    async def filter_caps_exempt_list(self, ctx):
        settings = Settings(self.bot, ctx.guild)
        current = await settings.get_exempt_roles("caps", ctx.guild.id)
        if not current:
            raise CommandError("no roles exempted from caps filter")
        roles = [ctx.guild.get_role(rid) for rid in current if ctx.guild.get_role(rid)]
        embed = Embed(title="Caps Exempt Roles").set_author(
            name=str(ctx.author), icon_url=ctx.author.display_avatar.url
        )
        return await ctx.paginate(
            embed,
            [f"`{i}` {r.mention} (`{r.id}`)" for i, r in enumerate(roles, start=1)],
        )

    

    @filter_.group(
        name="spoilers",
        description="delete any message exceeding the threshold for spoilers",
        example=",filter spoilers on --threshold 2",
    )
    @has_permissions(manage_guild=True)
    async def filter_spoilers(self, ctx, setting: Optional[bool] = True, *, flags: SpamFilterFlags = None):
        """toggle spoiler filter (custom bot filter)"""
        threshold = flags.threshold if flags else 5

        settings = Settings(self.bot, ctx.guild)
        if setting:
            await settings.upsert_module(
                "spoilers",
                threshold=threshold,
                action=(flags.punishment if flags else "delete"),
            )
            return await ctx.success(
                f"spoiler filter **enabled**\n> -# **threshold: {threshold}**"
            )
        else:
            await settings.delete_module("spoilers")
            return await ctx.success("spoiler filter **disabled**")

    @filter_spoilers.group(
        name="exempt",
        aliases=["wl", "ex"],
        description="exempt roles from the spoilers filter",
        invoke_without_command=True,
    )
    @has_permissions(manage_guild=True)
    async def filter_spoilers_exempt(self, ctx, *, roles):
        settings = Settings(self.bot, ctx.guild)
        current = await settings.get_exempt_roles("spoilers", ctx.guild.id)
        if not current:
            raise CommandError("spoiler filter not configured, run `filter spoilers on` first")
        current_set = set(current + [r.id for r in roles])
        valid = [rid for rid in current_set if ctx.guild.get_role(rid)]
        await settings.set_exempt_roles("spoilers", ctx.guild.id, valid)
        mentions = [ctx.guild.get_role(rid).mention for rid in valid if ctx.guild.get_role(rid)]
        return await ctx.success(
            f"exempt: {human_join(mentions, final='and') if mentions else 'none'}"
        )

    @filter_spoilers_exempt.command(name="list", aliases=["ls", "show", "view"])
    @has_permissions(manage_guild=True)
    async def filter_spoilers_exempt_list(self, ctx):
        settings = Settings(self.bot, ctx.guild)
        current = await settings.get_exempt_roles("spoilers", ctx.guild.id)
        if not current:
            raise CommandError("no roles exempted from spoiler filter")
        roles = [ctx.guild.get_role(rid) for rid in current if ctx.guild.get_role(rid)]
        embed = Embed(title="Spoiler Exempt Roles").set_author(
            name=str(ctx.author), icon_url=ctx.author.display_avatar.url
        )
        return await ctx.paginate(
            embed,
            [f"`{i}` {r.mention} (`{r.id}`)" for i, r in enumerate(roles, start=1)],
        )

    

    @filter_.group(
        name="musicfiles",
        description="delete any message that contains a music file",
        example=",filter musicfiles on",
    )
    @has_permissions(manage_guild=True)
    async def filter_musicfile(self, ctx, setting: Optional[bool] = True, *, flags: SpamFilterFlags = None):
        """toggle music file filter (custom bot filter)"""
        settings = Settings(self.bot, ctx.guild)
        if setting:
            await settings.upsert_module(
                "music",
                action=(flags.punishment if flags else "delete"),
            )
            return await ctx.success("music file filter **enabled**")
        else:
            await settings.delete_module("music")
            return await ctx.success("music file filter **disabled**")

    @filter_musicfile.group(
        name="exempt",
        aliases=["wl", "ex"],
        description="exempt roles from the music files filter",
        invoke_without_command=True,
    )
    @has_permissions(manage_guild=True)
    async def filter_musicfile_exempt(self, ctx, *, roles):
        settings = Settings(self.bot, ctx.guild)
        current = await settings.get_exempt_roles("music", ctx.guild.id)
        if not current:
            raise CommandError("music file filter not configured, run `filter musicfiles on` first")
        current_set = set(current + [r.id for r in roles])
        valid = [rid for rid in current_set if ctx.guild.get_role(rid)]
        await settings.set_exempt_roles("music", ctx.guild.id, valid)
        mentions = [ctx.guild.get_role(rid).mention for rid in valid if ctx.guild.get_role(rid)]
        return await ctx.success(
            f"exempt: {human_join(mentions, final='and') if mentions else 'none'}"
        )

    @filter_musicfile_exempt.command(name="list", aliases=["ls", "show", "view"])
    @has_permissions(manage_guild=True)
    async def filter_musicfile_exempt_list(self, ctx):
        settings = Settings(self.bot, ctx.guild)
        current = await settings.get_exempt_roles("music", ctx.guild.id)
        if not current:
            raise CommandError("no roles exempted from music file filter")
        roles = [ctx.guild.get_role(rid) for rid in current if ctx.guild.get_role(rid)]
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
        description="delete any message exceeding the threshold for user mentions",
        example=",filter massmention on --threshold 5",
        invoke_without_command=True,
    )
    @has_permissions(manage_guild=True)
    async def filter_massmention(self, ctx, setting: Optional[bool] = True, *, flags: SpamFilterFlags = None):
        """toggle mass mention filter using Discord AutoMod mention_spam trigger"""
        bot_rules = await self._get_bot_rules(ctx.guild)
        existing = _find_rule(bot_rules, name=MENTIONS_RULE)

        threshold = flags.threshold if flags else 5

        if setting:
            if existing:
                return await ctx.warn("mass mention filter is already **enabled**")
            try:
                await ctx.guild.create_automod_rule(
                    name=MENTIONS_RULE,
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
        description="delete any message exceeding the threshold for emojis",
        example=",filter emoji on --threshold 5",
        invoke_without_command=True,
    )
    @has_permissions(manage_guild=True)
    async def filter_emoji(self, ctx, setting: Optional[bool] = True, *, flags: SpamFilterFlags = None):
        """toggle emoji filter (custom bot filter)"""
        threshold = flags.threshold if flags else 5

        settings = Settings(self.bot, ctx.guild)
        if setting:
            await settings.upsert_module(
                "emoji",
                threshold=threshold,
                action=(flags.punishment if flags else "delete"),
            )
            return await ctx.success(
                f"emoji filter **enabled**\n> -# **threshold: {threshold}**"
            )
        else:
            await settings.delete_module("emoji")
            return await ctx.success("emoji filter **disabled**")

    @filter_emoji.group(
        name="exempt",
        aliases=["wl", "ex"],
        description="exempt roles from the emoji filter",
        invoke_without_command=True,
    )
    @has_permissions(manage_guild=True)
    async def filter_emoji_exempt(self, ctx, *, roles):
        settings = Settings(self.bot, ctx.guild)
        current = await settings.get_exempt_roles("emoji", ctx.guild.id)
        if not current:
            raise CommandError("emoji filter not configured, run `filter emoji on` first")
        current_set = set(current + [r.id for r in roles])
        valid = [rid for rid in current_set if ctx.guild.get_role(rid)]
        await settings.set_exempt_roles("emoji", ctx.guild.id, valid)
        mentions = [ctx.guild.get_role(rid).mention for rid in valid if ctx.guild.get_role(rid)]
        return await ctx.success(
            f"exempt: {human_join(mentions, final='and') if mentions else 'none'}"
        )

    @filter_emoji_exempt.command(name="list", aliases=["ls", "show", "view"])
    @has_permissions(manage_guild=True)
    async def filter_emoji_exempt_list(self, ctx):
        settings = Settings(self.bot, ctx.guild)
        current = await settings.get_exempt_roles("emoji", ctx.guild.id)
        if not current:
            raise CommandError("no roles exempted from emoji filter")
        roles = [ctx.guild.get_role(rid) for rid in current if ctx.guild.get_role(rid)]
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

        settings = Settings(self.bot, ctx.guild)
        existing = await settings.fetch_regex_row(ctx.guild.id, pattern)
        if existing:
            await settings.delete_regex(ctx.guild.id, pattern)
            return await ctx.success(f"removed regex\n> -# **`{pattern}`**")

        await settings.upsert_regex(
            ctx.guild.id,
            pattern,
            (flags.punishment if flags else "delete"),
        )
        return await ctx.success(
            f"added regex\n> -# **`{pattern}`** · {(flags.punishment if flags else 'delete')}"
        )

    @filter_regex.command(name="list", aliases=["ls", "show", "view"])
    @has_permissions(manage_guild=True)
    async def filter_regex_list(self, ctx):
        settings = Settings(self.bot, ctx.guild)
        patterns = await settings.fetch_regex_patterns(ctx.guild.id)
        if not patterns:
            raise CommandError("no regex patterns configured")
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
        settings = Settings(self.bot, ctx.guild)
        current = await settings.get_exempt_roles("regex", ctx.guild.id)
        updated = list(set(current + [r.id for r in roles]))
        valid = [rid for rid in updated if ctx.guild.get_role(rid)]
        await settings.set_exempt_roles("regex", ctx.guild.id, valid)
        mentions = [ctx.guild.get_role(rid).mention for rid in valid if ctx.guild.get_role(rid)]
        return await ctx.success(
            f"exempt: {human_join(mentions, final='and') if mentions else 'none'}"
        )

    @filter_regex_exempt.command(name="list", aliases=["ls", "show", "view"])
    @has_permissions(manage_guild=True)
    async def filter_regex_exempt_list(self, ctx):
        settings = Settings(self.bot, ctx.guild)
        current = await settings.get_exempt_roles("regex", ctx.guild.id)
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
