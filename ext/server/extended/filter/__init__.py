from typing import Optional, Union
from discord.ext.commands import group, CommandError
from discord import (
    Embed, TextChannel,
    AutoModTrigger, AutoModRuleTriggerType, AutoModRuleEventType, AutoModRuleAction,
)
from core.managers.permissions import has_permissions
from core.discord.package import Package
from lib.classes.flags.automod import FilterFlags, SpamFilterFlags
from lib.classes.builtins import human_join
import re


LINK_REGEX = r"(http|ftp|https):\/\/(?!open\.spotify\.com|tenor\.com)([\w_-]+(?:(?:\.[\w_-]+)+))([\w.,@?^=%&:\/~+#-]*[\w@?^=%&\/~+#-])"


class MultipleWords:
    """placeholder for word list converter"""
    pass


class MultipleLinks:
    """placeholder for link list converter"""
    pass


class MultipleInvites:
    """placeholder for invite list converter"""
    pass


class MultipleRoles:
    """placeholder for role list converter"""
    pass


class RegexPattern:
    """placeholder for regex converter"""
    pass


class FilterCommands(Package):
    """chat filter management"""

    @group(
        name="filter",
        aliases=["automod"],
        description="View a variety of options to help clean chat",
        invoke_without_command=True,
    )
    async def filter_(self, ctx):
        """filter help"""
        return await ctx.send_help()

    @filter_.command(name="reset", description="Reset all legacy filtered words")
    @has_permissions(manage_guild=True)
    async def filter_reset(self, ctx):
        """clear word filter"""
        rule = next(
            (r for r in await ctx.guild.fetch_automod_rules()
             if r.creator_id == self.bot.user.id and not r.trigger.regex_patterns),
            None,
        )
        if not rule:
            raise CommandError("no word filter rule found")
        rule.trigger.keyword_filter.clear()
        await rule.edit(
            trigger=AutoModTrigger(
                type=AutoModRuleTriggerType.keyword,
                keyword_filter=[],
            ),
            reason=f"filter reset by {ctx.author}",
        )
        return await ctx.success("word filter cleared")

    @filter_.group(
        name="caps",
        description="Delete messages that contain too many uppercase characters",
        example=",filter caps all on --threshold 70",
    )
    @has_permissions(manage_guild=True)
    async def filter_caps(
        self,
        ctx,
        channel: Optional[Union[TextChannel, str]] = None,
        setting: Optional[bool] = False,
        *,
        flags: FilterFlags,
    ):
        """toggle caps filter"""
        if not channel:
            channel = "all"
        channels = (
            [channel.id] if isinstance(channel, TextChannel)
            else [c.id for c in ctx.guild.text_channels]
        )
        await self.db.execute(
            """INSERT INTO moderation.caps (guild_id, channel_ids, threshold, action) VALUES($1, $2, $3, $4) ON CONFLICT(guild_id) DO UPDATE SET channel_ids = excluded.channel_ids, threshold = excluded.threshold, action = excluded.action""",
            ctx.guild.id, channels, flags.threshold, flags.punishment,
        )
        state = "ENABLED" if setting else "DISABLED"
        return await ctx.success(f"caps filter **{state}**")

    @filter_caps.group(
        name="exempt",
        aliases=["wl", "ex"],
        description="Exempt roles from the caps filter",
        example=",filter caps exempt @mods",
        invoke_without_command=True,
    )
    @has_permissions(manage_guild=True)
    async def filter_caps_exempt(self, ctx, *, roles):
        """exempt roles from caps"""
        row = await self.db.fetchval(
            """SELECT guild_id, exempt_roles FROM moderation.caps WHERE guild_id = $1""",
            ctx.guild.id,
        )
        if not row:
            raise CommandError("caps filter not configured")
        current = list(set(row.roles or []))
        for r in roles:
            if r.id in current:
                current.remove(r.id)
            else:
                current.append(r.id)
        valid = [ctx.guild.get_role(rid) for rid in current if ctx.guild.get_role(rid)]
        await self.db.execute(
            """UPDATE moderation.caps SET exempt_roles = $1 WHERE guild_id = $2""",
            [r.id for r in valid], ctx.guild.id,
        )
        return await ctx.success(
            f"exempt roles updated: {human_join([r.mention for r in valid], final='and')}"
        )

    @filter_caps_exempt.command(name="list", aliases=["ls", "show", "view"])
    @has_permissions(manage_guild=True)
    async def filter_caps_exempt_list(self, ctx):
        """list caps exempt roles"""
        row = await self.db.fetchval(
            """SELECT guild_id, exempt_roles FROM moderation.caps WHERE guild_id = $1""",
            ctx.guild.id,
        )
        if not row or not row.roles:
            raise CommandError("no roles exempted from caps filter")
        roles = [ctx.guild.get_role(rid) for rid in row.roles if ctx.guild.get_role(rid)]
        embed = Embed(title="Caps Exempt Roles").set_author(
            name=str(ctx.author), icon_url=ctx.author.display_avatar.url
        )
        return await ctx.paginate(embed, [f"`{i}` {r.mention} (`{r.id}`)" for i, r in enumerate(roles, start=1)])

    @filter_.group(
        name="spam",
        aliases=["antispam", "flood", "flooding"],
        description="Delete messages from users that send messages too fast",
        example=",filter spam all on --threshold 5",
        invoke_without_command=True,
    )
    @has_permissions(manage_guild=True)
    async def filter_spam(
        self,
        ctx,
        channel: Optional[Union[TextChannel, str]] = "all",
        setting: Optional[bool] = True,
        *,
        flags: SpamFilterFlags,
    ):
        """toggle spam filter"""
        channels = (
            [channel.id] if isinstance(channel, TextChannel)
            else [c.id for c in ctx.guild.text_channels]
        )
        await self.db.execute(
            """INSERT INTO moderation.caps (guild_id, channel_ids, threshold, action) VALUES($1, $2, $3, $4) ON CONFLICT(guild_id) DO UPDATE SET channel_ids = excluded.channel_ids, threshold = excluded.threshold, action = excluded.action""",
            ctx.guild.id, channels, flags.threshold, flags.punishment,
        )
        state = "ENABLED" if setting else "DISABLED"
        return await ctx.success(
            f"{state} spam filter across **{len(channels)}** channel(s). threshold: **{flags.threshold}** msgs/5s. punishment: {flags.punishment}"
        )

    @filter_spam.group(
        name="exempt",
        aliases=["wl", "ex"],
        description="Exempt roles from the antispam filter",
        example=",filter spam exempt @mods",
        invoke_without_command=True,
    )
    @has_permissions(manage_guild=True)
    async def filter_spam_exempt(self, ctx, *, roles):
        """exempt roles from spam"""
        row = await self.db.fetchval(
            """SELECT guild_id, exempt_roles FROM moderation.spam WHERE guild_id = $1""",
            ctx.guild.id,
        )
        if not row:
            raise CommandError("spam filter not configured")
        current = list(set(row.roles or []))
        for r in roles:
            if r.id in current:
                current.remove(r.id)
            else:
                current.append(r.id)
        valid = [ctx.guild.get_role(rid) for rid in current if ctx.guild.get_role(rid)]
        await self.db.execute(
            """UPDATE moderation.spam SET exempt_roles = $1 WHERE guild_id = $2""",
            [r.id for r in valid], ctx.guild.id,
        )
        return await ctx.success(
            f"exempt roles: {human_join([r.mention for r in valid], final='and')}"
        )

    @filter_spam_exempt.command(name="list", aliases=["ls", "show", "view"])
    @has_permissions(manage_guild=True)
    async def filter_spam_exempt_list(self, ctx):
        """list spam exempt roles"""
        row = await self.db.fetchval(
            """SELECT guild_id, exempt_roles FROM moderation.spam WHERE guild_id = $1""",
            ctx.guild.id,
        )
        if not row or not row.roles:
            raise CommandError("no roles exempted from spam filter")
        roles = [ctx.guild.get_role(rid) for rid in row.roles if ctx.guild.get_role(rid)]
        embed = Embed(title="Spam Exempt Roles").set_author(
            name=str(ctx.author), icon_url=ctx.author.display_avatar.url
        )
        return await ctx.paginate(embed, [f"`{i}` {r.mention} (`{r.id}`)" for i, r in enumerate(roles, start=1)])

    @filter_.command(
        name="add",
        aliases=["create", "set", "c", "a"],
        description="add words to the filter",
        example=",filter add badword",
    )
    @has_permissions(manage_guild=True)
    async def filter_add(self, ctx, *, words):
        """add filtered words"""
        word_list = words if isinstance(words, list) else [words]
        if any(len(w) > 60 or len(w) < 1 for w in word_list):
            raise CommandError("each word must be 1–60 characters")
        rule = next(
            (r for r in await ctx.guild.fetch_automod_rules()
             if r.creator_id == self.bot.user.id and not r.trigger.regex_patterns),
            None,
        )
        if not rule:
            if len(word_list) >= 1000:
                raise CommandError("can only filter 1000 words max")
            actions = [
                AutoModRuleAction(
                    custom_message=f"blocked by {self.bot.user.name} — blacklisted word"
                )
            ]
            await ctx.guild.create_automod_rule(
                name=f"{self.bot.user.name} - words",
                event_type=AutoModRuleEventType.message_send,
                trigger=AutoModTrigger(
                    type=AutoModRuleTriggerType.keyword,
                    keyword_filter=[f"*{w}*" for w in word_list],
                ),
                enabled=True,
                actions=actions,
                reason=f"word filter created by {ctx.author}",
            )
        else:
            kf = rule.trigger.keyword_filter
            kf.extend([f"*{w}*" for w in word_list])
            if len(kf) >= 1000:
                raise CommandError("hit the 1000 word limit")
            await rule.edit(
                trigger=AutoModTrigger(
                    type=AutoModRuleTriggerType.keyword, keyword_filter=kf
                ),
                reason=f"filter updated by {ctx.author}",
            )
        return await ctx.success(
            f"added to word filter: {human_join(word_list, final='and', markdown='`')}"
        )

    @filter_.group(
        name="links",
        aliases=["urls"],
        description="Delete any message that contains a link",
        example=",filter links all on",
        invoke_without_command=True,
    )
    @has_permissions(manage_guild=True)
    async def filter_links(
        self,
        ctx,
        channel: Optional[Union[TextChannel, str]] = "all",
        setting: Optional[bool] = True,
        *,
        flags: FilterFlags,
    ):
        """toggle link filter"""
        channels = (
            [channel.id] if isinstance(channel, TextChannel)
            else [c.id for c in ctx.guild.text_channels]
        )
        await self.db.execute(
            """INSERT INTO moderation.links (guild_id, channel_ids, action) VALUES($1, $2, $3) ON CONFLICT(guild_id) DO UPDATE SET channel_ids = excluded.channel_ids, action = excluded.action""",
            ctx.guild.id, channels, flags.punishment,
        )
        state = "ENABLED" if setting else "DISABLED"
        return await ctx.success(f"{state} link filter across **{len(channels)}** channel(s)")

    @filter_links.group(
        name="exempt",
        aliases=["ex"],
        description="Exempt roles from the links filter",
        example=",filter links exempt @mods",
        invoke_without_command=True,
    )
    @has_permissions(manage_guild=True)
    async def filter_links_exempt(self, ctx, *, roles):
        """exempt roles from links"""
        row = await self.db.fetchval(
            """SELECT guild_id, exempt_roles FROM moderation.links WHERE guild_id = $1""",
            ctx.guild.id,
        )
        if not row:
            raise CommandError("link filter not configured")
        current = list(set(row.roles or []))
        for r in roles:
            if r.id in current:
                current.remove(r.id)
            else:
                current.append(r.id)
        valid = [ctx.guild.get_role(rid) for rid in current if ctx.guild.get_role(rid)]
        await self.db.execute(
            """UPDATE moderation.links SET exempt_roles = $1 WHERE guild_id = $2""",
            [r.id for r in valid], ctx.guild.id,
        )
        return await ctx.success(
            f"exempt roles: {human_join([r.mention for r in valid], final='and')}"
        )

    @filter_links_exempt.command(name="list", aliases=["ls", "show", "view"])
    @has_permissions(manage_guild=True)
    async def filter_links_exempt_list(self, ctx):
        """list links exempt roles"""
        row = await self.db.fetchval(
            """SELECT guild_id, exempt_roles FROM moderation.links WHERE guild_id = $1""",
            ctx.guild.id,
        )
        if not row or not row.roles:
            raise CommandError("no roles exempted from link filter")
        roles = [ctx.guild.get_role(rid) for rid in row.roles if ctx.guild.get_role(rid)]
        embed = Embed(title="Links Exempt Roles").set_author(
            name=str(ctx.author), icon_url=ctx.author.display_avatar.url
        )
        return await ctx.paginate(embed, [f"`{i}` {r.mention} (`{r.id}`)" for i, r in enumerate(roles, start=1)])

    @filter_links.command(
        name="whitelist",
        aliases=["wl"],
        description="Whitelist links from the links filter",
        example=",filter links whitelist https://safe.com",
    )
    @has_permissions(manage_guild=True)
    async def filter_links_whitelist(self, ctx, *, links):
        """whitelist links"""
        row = await self.db.fetchval(
            """SELECT guild_id, whitelist FROM moderation.links WHERE guild_id = $1""",
            ctx.guild.id,
        )
        if not row:
            raise CommandError("link filter not configured")
        link_list = links if isinstance(links, list) else [links]
        updated = list(set(row.whitelist or []) | set(link_list))
        await self.db.execute(
            """UPDATE moderation.links SET whitelist = $1 WHERE guild_id = $2""",
            updated, ctx.guild.id,
        )
        return await ctx.success(f"whitelisted: {human_join(link_list, final='and')}")

    @filter_.group(
        name="invites",
        aliases=["invite", "invs", "inv"],
        description="Delete any message that contains a server link",
        example=",filter invites all on",
        invoke_without_command=True,
    )
    @has_permissions(manage_guild=True)
    async def filter_invites(
        self,
        ctx,
        channel: Optional[Union[TextChannel, str]] = "all",
        setting: Optional[bool] = True,
        *,
        flags: FilterFlags,
    ):
        """toggle invite filter"""
        channels = (
            [channel.id] if isinstance(channel, TextChannel)
            else [c.id for c in ctx.guild.text_channels]
        )
        await self.db.execute(
            """INSERT INTO moderation.invites (guild_id, channel_ids, action) VALUES($1, $2, $3) ON CONFLICT(guild_id) DO UPDATE SET channel_ids = excluded.channel_ids, action = excluded.action""",
            ctx.guild.id, channels, flags.punishment,
        )
        state = "ENABLED" if setting else "DISABLED"
        return await ctx.success(f"{state} invite filter across **{len(channels)}** channel(s)")

    @filter_invites.group(
        name="exempt",
        aliases=["ex"],
        description="Exempt roles from the invite filter",
        invoke_without_command=True,
    )
    @has_permissions(manage_guild=True)
    async def filter_invites_exempt(self, ctx, *, roles):
        """exempt roles from invites"""
        row = await self.db.fetchval(
            """SELECT guild_id, exempt_roles FROM moderation.invites WHERE guild_id = $1""",
            ctx.guild.id,
        )
        if not row:
            raise CommandError("invite filter not configured")
        current = list(set(row.roles or []))
        for r in roles:
            if r.id in current:
                current.remove(r.id)
            else:
                current.append(r.id)
        valid = [ctx.guild.get_role(rid) for rid in current if ctx.guild.get_role(rid)]
        await self.db.execute(
            """UPDATE moderation.invites SET exempt_roles = $1 WHERE guild_id = $2""",
            [r.id for r in valid], ctx.guild.id,
        )
        return await ctx.success(
            f"exempt roles: {human_join([r.mention for r in valid], final='and')}"
        )

    @filter_invites.command(
        name="whitelist",
        aliases=["wl"],
        description="whitelist invites from filter",
    )
    @has_permissions(manage_guild=True)
    async def filter_invites_whitelist(self, ctx, *, invites):
        """whitelist invites"""
        row = await self.db.fetchval(
            """SELECT guild_id, whitelist FROM moderation.invites WHERE guild_id = $1""",
            ctx.guild.id,
        )
        if not row:
            raise CommandError("invite filter not configured")
        inv_list = invites if isinstance(invites, list) else [invites]
        updated = list(set(row.whitelist or []) | set(inv_list))
        await self.db.execute(
            """UPDATE moderation.invites SET whitelist = $1 WHERE guild_id = $2""",
            updated, ctx.guild.id,
        )
        return await ctx.success(f"whitelisted invites: {human_join(inv_list, final='and')}")

    @filter_invites_exempt.command(name="list", aliases=["ls", "show", "view"])
    @has_permissions(manage_guild=True)
    async def filter_invites_exempt_list(self, ctx):
        """list invite exempt roles"""
        row = await self.db.fetchval(
            """SELECT guild_id, exempt_roles FROM moderation.invites WHERE guild_id = $1""",
            ctx.guild.id,
        )
        if not row or not row.roles:
            raise CommandError("no roles exempted from invite filter")
        roles = [ctx.guild.get_role(rid) for rid in row.roles if ctx.guild.get_role(rid)]
        embed = Embed(title="Invite Exempt Roles").set_author(
            name=str(ctx.author), icon_url=ctx.author.display_avatar.url
        )
        return await ctx.paginate(embed, [f"`{i}` {r.mention} (`{r.id}`)" for i, r in enumerate(roles, start=1)])

    @filter_.command(
        name="list",
        aliases=["ls", "show", "view"],
        description="View a list of filtered words in guild",
    )
    @has_permissions(manage_guild=True)
    async def filter_list(self, ctx):
        """list filtered words"""
        rule = next(
            (r for r in await ctx.guild.fetch_automod_rules()
             if r.creator_id == self.bot.user.id and not r.trigger.regex_patterns),
            None,
        )
        if not rule:
            raise CommandError("no word filter configured")
        words = [w.replace("*", "") for w in rule.trigger.keyword_filter]
        embed = Embed(title="Filtered Words").set_author(
            name=str(ctx.author), icon_url=ctx.author.display_avatar.url
        )
        return await ctx.paginate(embed, [f"`{i}` {w}" for i, w in enumerate(words, start=1)])

    @filter_.command(
        name="remove",
        aliases=["del", "delete", "d", "r", "rem"],
        description="remove words from the filter",
    )
    @has_permissions(manage_guild=True)
    async def filter_remove(self, ctx, *, words):
        """remove filtered words"""
        word_list = words if isinstance(words, list) else [words]
        rule = next(
            (r for r in await ctx.guild.fetch_automod_rules()
             if r.creator_id == self.bot.user.id and not r.trigger.regex_patterns),
            None,
        )
        if not rule:
            raise CommandError("no word filter configured")
        kf = list(rule.trigger.keyword_filter)
        dropped = []
        for w in word_list:
            target = f"*{w.lower()}*"
            if target in kf:
                kf.remove(target)
                dropped.append(w.lower())
        await rule.edit(
            trigger=AutoModTrigger(type=AutoModRuleTriggerType.keyword, keyword_filter=kf),
            reason=f"filter edited by {ctx.author}",
        )
        return await ctx.success(
            f"removed: {human_join(dropped or word_list, final='and')}"
        )

    @filter_.group(
        name="spoilers",
        description="Delete any message exceeding the threshold for spoilers",
        example=",filter spoilers #general on --threshold 2",
    )
    @has_permissions(manage_guild=True)
    async def filter_spoilers(
        self,
        ctx,
        channel: Optional[Union[TextChannel, str]] = "all",
        setting: Optional[bool] = True,
        *,
        flags: SpamFilterFlags,
    ):
        """toggle spoiler filter"""
        channels = (
            [channel.id] if isinstance(channel, TextChannel)
            else [c.id for c in ctx.guild.text_channels]
        )
        await self.db.execute(
            """INSERT INTO moderation.spoilers (guild_id, channel_ids, threshold, action) VALUES($1, $2, $3, $4) ON CONFLICT(guild_id) DO UPDATE SET channel_ids = excluded.channel_ids, threshold = excluded.threshold, action = excluded.action""",
            ctx.guild.id, channels, flags.threshold, flags.punishment,
        )
        state = "ENABLED" if setting else "DISABLED"
        return await ctx.success(f"{state} spoiler filter. threshold: **{flags.threshold}**")

    @filter_spoilers.group(
        name="exempt",
        aliases=["wl", "ex"],
        description="Exempt roles from the spoilers filter",
        invoke_without_command=True,
    )
    @has_permissions(manage_guild=True)
    async def filter_spoilers_exempt(self, ctx, *, roles):
        """exempt from spoilers"""
        row = await self.db.fetchval(
            """SELECT guild_id, exempt_roles FROM moderation.spoilers WHERE guild_id = $1""",
            ctx.guild.id,
        )
        if not row:
            raise CommandError("spoiler filter not configured")
        current = list(set((row.roles or []) + [r.id for r in roles]))
        valid = [ctx.guild.get_role(rid) for rid in current if ctx.guild.get_role(rid)]
        await self.db.execute(
            """UPDATE moderation.spoilers SET exempt_roles = $1 WHERE guild_id = $2""",
            [r.id for r in valid], ctx.guild.id,
        )
        return await ctx.success(
            f"exempt: {human_join([r.mention for r in valid], final='and')}"
        )

    @filter_spoilers_exempt.command(name="list", aliases=["ls", "show", "view"])
    @has_permissions(manage_guild=True)
    async def filter_spoilers_exempt_list(self, ctx):
        """list spoiler exempt roles"""
        row = await self.db.fetchval(
            """SELECT guild_id, exempt_roles FROM moderation.spoilers WHERE guild_id = $1""",
            ctx.guild.id,
        )
        if not row or not row.roles:
            raise CommandError("no roles exempted from spoiler filter")
        roles = [ctx.guild.get_role(rid) for rid in row.roles if ctx.guild.get_role(rid)]
        embed = Embed(title="Spoiler Exempt Roles").set_author(name=str(ctx.author), icon_url=ctx.author.display_avatar.url)
        return await ctx.paginate(embed, [f"`{i}` {r.mention} (`{r.id}`)" for i, r in enumerate(roles, start=1)])

    @filter_.group(
        name="musicfiles",
        description="Delete any message that contains a music file",
        example=",filter musicfiles #general on",
    )
    @has_permissions(manage_guild=True)
    async def filter_musicfile(
        self,
        ctx,
        channel: Optional[Union[TextChannel, str]] = "all",
        setting: Optional[bool] = True,
        *,
        flags: SpamFilterFlags,
    ):
        """toggle music file filter"""
        channels = (
            [channel.id] if isinstance(channel, TextChannel)
            else [c.id for c in ctx.guild.text_channels]
        )
        await self.db.execute(
            """INSERT INTO moderation.music (guild_id, channel_ids, action) VALUES($1, $2, $3) ON CONFLICT(guild_id) DO UPDATE SET channel_ids = excluded.channel_ids, action = excluded.action""",
            ctx.guild.id, channels, flags.punishment,
        )
        state = "ENABLED" if setting else "DISABLED"
        return await ctx.success(f"{state} music file filter across **{len(channels)}** channel(s)")

    @filter_musicfile.group(
        name="exempt",
        aliases=["wl", "ex"],
        description="Exempt roles from the music files filter",
        invoke_without_command=True,
    )
    @has_permissions(manage_guild=True)
    async def filter_musicfile_exempt(self, ctx, *, roles):
        """exempt from music filter"""
        row = await self.db.fetchval(
            """SELECT guild_id, exempt_roles FROM moderation.music WHERE guild_id = $1""",
            ctx.guild.id,
        )
        if not row:
            raise CommandError("music file filter not configured")
        current = list(set((row.roles or []) + [r.id for r in roles]))
        valid = [ctx.guild.get_role(rid) for rid in current if ctx.guild.get_role(rid)]
        await self.db.execute(
            """UPDATE moderation.music SET exempt_roles = $1 WHERE guild_id = $2""",
            [r.id for r in valid], ctx.guild.id,
        )
        return await ctx.success(
            f"exempt: {human_join([r.mention for r in valid], final='and')}"
        )

    @filter_musicfile_exempt.command(name="list", aliases=["ls", "show", "view"])
    @has_permissions(manage_guild=True)
    async def filter_musicfile_exempt_list(self, ctx):
        """list music exempt roles"""
        row = await self.db.fetchval(
            """SELECT guild_id, exempt_roles FROM moderation.music WHERE guild_id = $1""",
            ctx.guild.id,
        )
        if not row or not row.roles:
            raise CommandError("no roles exempted from music file filter")
        roles = [ctx.guild.get_role(rid) for rid in row.roles if ctx.guild.get_role(rid)]
        embed = Embed(title="Music File Exempt Roles").set_author(name=str(ctx.author), icon_url=ctx.author.display_avatar.url)
        return await ctx.paginate(embed, [f"`{i}` {r.mention} (`{r.id}`)" for i, r in enumerate(roles, start=1)])

    @filter_.group(
        name="massmention",
        aliases=["mm", "mention"],
        description="Delete any message exceeding the threshold for user mentions",
        example=",filter massmention all on --threshold 5 --do delete",
        invoke_without_command=True,
    )
    @has_permissions(manage_guild=True)
    async def filter_massmention(
        self,
        ctx,
        channel: Optional[Union[TextChannel, str]] = "all",
        setting: Optional[bool] = True,
        *,
        flags: SpamFilterFlags,
    ):
        """toggle mass mention filter"""
        channels = (
            [channel.id] if isinstance(channel, TextChannel)
            else [c.id for c in ctx.guild.text_channels]
        )
        await self.db.execute(
            """INSERT INTO moderation.mention (guild_id, channel_ids, threshold, action) VALUES($1, $2, $3, $4) ON CONFLICT(guild_id) DO UPDATE SET channel_ids = excluded.channel_ids, threshold = excluded.threshold, action = excluded.action""",
            ctx.guild.id, channels, flags.threshold, flags.punishment,
        )
        state = "ENABLED" if setting else "DISABLED"
        return await ctx.success(f"{state} mass mention filter. threshold: **{flags.threshold}**")

    @filter_massmention.group(
        name="exempt",
        aliases=["wl", "ex"],
        description="Exempt roles from the mass mention filter",
        invoke_without_command=True,
    )
    @has_permissions(manage_guild=True)
    async def filter_massmention_exempt(self, ctx, *, roles):
        """exempt from massmention"""
        row = await self.db.fetchval(
            """SELECT guild_id, exempt_roles FROM moderation.mention WHERE guild_id = $1""",
            ctx.guild.id,
        )
        if not row:
            raise CommandError("mass mention filter not configured")
        current = list(set((row.roles or []) + [r.id for r in roles]))
        valid = [ctx.guild.get_role(rid) for rid in current if ctx.guild.get_role(rid)]
        await self.db.execute(
            """UPDATE moderation.mention SET exempt_roles = $1 WHERE guild_id = $2""",
            [r.id for r in valid], ctx.guild.id,
        )
        return await ctx.success(
            f"exempt: {human_join([r.mention for r in valid], final='and')}"
        )

    @filter_massmention_exempt.command(name="list", aliases=["ls", "show", "view"])
    @has_permissions(manage_guild=True)
    async def filter_massmention_exempt_list(self, ctx):
        """list massmention exempt roles"""
        row = await self.db.fetchval(
            """SELECT guild_id, exempt_roles FROM moderation.mention WHERE guild_id = $1""",
            ctx.guild.id,
        )
        if not row or not row.roles:
            raise CommandError("no roles exempted from mass mention filter")
        roles = [ctx.guild.get_role(rid) for rid in row.roles if ctx.guild.get_role(rid)]
        embed = Embed(title="Mass Mention Exempt Roles").set_author(name=str(ctx.author), icon_url=ctx.author.display_avatar.url)
        return await ctx.paginate(embed, [f"`{i}` {r.mention} (`{r.id}`)" for i, r in enumerate(roles, start=1)])

    @filter_.group(
        name="emoji",
        aliases=["emojis", "emote", "emotes"],
        description="Delete any message exceeding the threshold for emojis",
        example=",filter emoji all on --threshold 5",
        invoke_without_command=True,
    )
    @has_permissions(manage_guild=True)
    async def filter_emoji(
        self,
        ctx,
        channel: Optional[Union[TextChannel, str]] = "all",
        setting: Optional[bool] = True,
        *,
        flags: SpamFilterFlags,
    ):
        """toggle emoji filter"""
        channels = (
            [channel.id] if isinstance(channel, TextChannel)
            else [c.id for c in ctx.guild.text_channels]
        )
        await self.db.execute(
            """INSERT INTO moderation.emoji (guild_id, channel_ids, threshold, action) VALUES($1, $2, $3, $4) ON CONFLICT(guild_id) DO UPDATE SET channel_ids = excluded.channel_ids, threshold = excluded.threshold, action = excluded.action""",
            ctx.guild.id, channels, flags.threshold, flags.punishment,
        )
        state = "ENABLED" if setting else "DISABLED"
        return await ctx.success(f"{state} emoji filter. threshold: **{flags.threshold}**")

    @filter_emoji.group(
        name="exempt",
        aliases=["wl", "ex"],
        description="Exempt roles from the emoji filter",
        invoke_without_command=True,
    )
    @has_permissions(manage_guild=True)
    async def filter_emoji_exempt(self, ctx, *, roles):
        """exempt from emoji filter"""
        row = await self.db.fetchval(
            """SELECT guild_id, exempt_roles FROM moderation.emoji WHERE guild_id = $1""",
            ctx.guild.id,
        )
        if not row:
            raise CommandError("emoji filter not configured")
        current = list(set((row.roles or []) + [r.id for r in roles]))
        valid = [ctx.guild.get_role(rid) for rid in current if ctx.guild.get_role(rid)]
        await self.db.execute(
            """UPDATE moderation.emoji SET exempt_roles = $1 WHERE guild_id = $2""",
            [r.id for r in valid], ctx.guild.id,
        )
        return await ctx.success(
            f"exempt: {human_join([r.mention for r in valid], final='and')}"
        )

    @filter_emoji_exempt.command(name="list", aliases=["ls", "show", "view"])
    @has_permissions(manage_guild=True)
    async def filter_emoji_exempt_list(self, ctx):
        """list emoji exempt roles"""
        row = await self.db.fetchval(
            """SELECT guild_id, exempt_roles FROM moderation.emoji WHERE guild_id = $1""",
            ctx.guild.id,
        )
        if not row or not row.roles:
            raise CommandError("no roles exempted from emoji filter")
        roles = [ctx.guild.get_role(rid) for rid in row.roles if ctx.guild.get_role(rid)]
        embed = Embed(title="Emoji Exempt Roles").set_author(name=str(ctx.author), icon_url=ctx.author.display_avatar.url)
        return await ctx.paginate(embed, [f"`{i}` {r.mention} (`{r.id}`)" for i, r in enumerate(roles, start=1)])

    @filter_.group(
        name="regex",
        aliases=["re"],
        description="add or toggle regex patterns",
        example=r",filter regex \b\d+\.\d+\b",
        invoke_without_command=True,
    )
    @has_permissions(manage_guild=True)
    async def filter_regex(self, ctx, pattern: str, *, flags: FilterFlags):
        """toggle a regex pattern"""
        try:
            re.compile(pattern)
        except re.error as e:
            raise CommandError(f"invalid regex: {e}")
        existing = await self.db.fetchrow(
            """SELECT * FROM moderation.regex WHERE guild_id = $1 AND regex = $2""",
            ctx.guild.id, pattern,
        )
        if existing:
            await self.db.execute(
                """DELETE FROM moderation.regex WHERE guild_id = $1 AND regex = $2""",
                ctx.guild.id, pattern,
            )
            return await ctx.success(f"`{pattern}` removed from regex filter")
        await self.db.execute(
            """INSERT INTO moderation.regex (guild_id, regex, action) VALUES($1, $2, $3) ON CONFLICT(guild_id, regex) DO UPDATE SET action = excluded.action""",
            ctx.guild.id, pattern, flags.punishment,
        )
        return await ctx.success(f"added regex `{pattern}`. punishment: **{flags.punishment}**")

    @filter_regex.command(name="list", aliases=["ls", "show", "view"])
    @has_permissions(manage_guild=True)
    async def filter_regex_list(self, ctx):
        """list regex patterns"""
        rows = await self.db.fetch(
            "SELECT regex FROM moderation.regex WHERE guild_id = $1",
            ctx.guild.id,
        )
        if not rows:
            raise CommandError("no regex patterns configured")
        patterns = [r.regex for r in rows]
        embed = Embed(title="Regex Patterns").set_author(name=str(ctx.author), icon_url=ctx.author.display_avatar.url)
        return await ctx.paginate(embed, [f"`{i}` **{p}**" for i, p in enumerate(patterns, start=1)])

    @filter_regex.group(
        name="exempt",
        aliases=["wl", "ex"],
        description="exempt roles from regex filter",
        invoke_without_command=True,
    )
    @has_permissions(manage_guild=True)
    async def filter_regex_exempt(self, ctx, *, roles):
        """exempt from regex"""
        current = (
            await self.db.fetchval(
                """SELECT exempt_roles FROM moderation.regex_exempt WHERE guild_id = $1""",
                ctx.guild.id,
            ) or []
        )
        updated = list(set(current + [r.id for r in roles]))
        valid = [ctx.guild.get_role(rid) for rid in updated if ctx.guild.get_role(rid)]
        await self.db.execute(
            """UPDATE moderation.regex SET exempt_roles = $1 WHERE guild_id = $2""",
            [r.id for r in valid], ctx.guild.id,
        )
        return await ctx.success(
            f"exempt: {human_join([r.mention for r in valid], final='and')}"
        )

    @filter_regex_exempt.command(name="list", aliases=["ls", "show", "view"])
    @has_permissions(manage_guild=True)
    async def filter_regex_exempt_list(self, ctx):
        """list regex exempt roles"""
        current = (
            await self.db.fetchval(
                """SELECT exempt_roles FROM moderation.regex_exempt WHERE guild_id = $1""",
                ctx.guild.id,
            ) or []
        )
        if not current:
            raise CommandError("no roles exempted from regex filter")
        roles = [ctx.guild.get_role(rid) for rid in current if ctx.guild.get_role(rid)]
        embed = Embed(title="Regex Exempt Roles").set_author(name=str(ctx.author), icon_url=ctx.author.display_avatar.url)
        return await ctx.paginate(embed, [f"`{i}` {r.mention} (`{r.id}`)" for i, r in enumerate(roles, start=1)])
