from __future__ import annotations

import discord
from discord.ext.commands import command, group

import discord
from core.discord.hybrid import hybrid
from core.discord.package import Package
from core.discord.views.paginate import send_pages
from core.tools.aesthetic import aesthetic_embed, body, caption, compose
from core.tools.embed import BadEmbed, ParseError, PreparedScript, parse


class ServerCommands(Package):
    """standalone server commands"""

    @staticmethod
    def _normalize_embed_script(script: str) -> str:
        from core.tools.embed import maybe_wrap_embed_script
        value = maybe_wrap_embed_script(str(script).strip())
        lowered = value.lower()
        if lowered.startswith("{embed}") or lowered.startswith("embed$v"):
            return value
        if value.startswith("$v{"):
            return "{embed}" + value
        if value.startswith("{"):
            return f"{{embed}}$v{value}"
        return value

    async def _send_embed_script(self, ctx, script: str):
        normalized = self._normalize_embed_script(script)

        from core.tools.embed import is_embed_script
        if not is_embed_script(normalized):
            payload = {"content": normalized}
        else:
            try:
                payload = await parse(normalized, sendable=True)
            except (ParseError, BadEmbed) as error:
                return await ctx.warn(
                    f"{error}\n`{script}`"
                )

        if not payload or (
            payload.get("content") in {None, ""}
            and payload.get("embed") is None
            and payload.get("view") is None
        ):
            return await ctx.warn("Provide **valid embed code**.")

        try:
            return await PreparedScript(payload).send(ctx)
        except discord.HTTPException as error:
            message = str(error)
            if "):" in message:
                message = message.split("):", 1)[1].strip()
            return await ctx.warn(message or "invalid embed data")

    @group(
        name="embedcreate",
        aliases=["ce", "createembed"],
        usage="(script)",
        example="{title: Hello}$v{description: This is a test}$v{color: FF0000}",
        invoke_without_command=True,
    )
    async def embedcreate(self, ctx, *, script: str = None):
        """Create a custom embed using embed scripting."""
        if script is None:
            return await ctx.send_help()
        return await self._send_embed_script(ctx, script)

    @embedcreate.command(
        name="preview",
        aliases=["view"],
        usage="(script)",
        example="{title: Hello}$v{description: Test}",
    )
    async def embedcreate_preview(self, ctx, *, script: str = None):
        """Preview an embed script without sending it."""
        if script is None:
            return await ctx.fail("Provide an embed script to preview")
        return await self._send_embed_script(ctx, script)

    @command(
        name="variables",
        aliases=["vars"],
        usage="(category)",
        example="user",
    )
    async def variables(self, ctx, category: str = None):
        """List all available variables for embed scripting."""
        categories = {
            "guild": {
                "description": "Server/Guild variables",
                "variables": {
                    "{guild.name}": "Server name",
                    "{guild.id}": "Server ID",
                    "{guild.member_count}": "Member count",
                    "{guild.owner}": "Server owner",
                    "{guild.owner_id}": "Server owner ID",
                    "{guild.created_at}": "Server creation date",
                    "{guild.icon}": "Server icon URL",
                    "{guild.banner}": "Server banner URL",
                    "{guild.boost_count}": "Boost count",
                    "{guild.boost_tier}": "Boost tier",
                },
            },
            "user": {
                "description": "User variables",
                "variables": {
                    "{user}": "User mention",
                    "{user.name}": "Username",
                    "{user.id}": "User ID",
                    "{user.mention}": "User mention",
                    "{user.avatar}": "Avatar URL",
                    "{user.created_at}": "Account creation date",
                    "{user.joined_at}": "Server join date",
                    "{user.top_role}": "Highest role",
                    "{user.roles}": "All roles",
                },
            },
            "channel": {
                "description": "Channel variables",
                "variables": {
                    "{channel}": "Channel mention",
                    "{channel.name}": "Channel name",
                    "{channel.id}": "Channel ID",
                    "{channel.mention}": "Channel mention",
                    "{channel.topic}": "Channel topic",
                    "{channel.category}": "Category name",
                },
            },
            "moderation": {
                "description": "Moderation variables",
                "variables": {
                    "{moderator}": "Moderator mention",
                    "{target}": "Target user",
                    "{reason}": "Reason",
                    "{duration}": "Duration",
                    "{action}": "Action type",
                    "{case_id}": "Case ID",
                },
            },
            "date": {
                "description": "Date/Time variables",
                "variables": {
                    "{date}": "Current date",
                    "{time}": "Current time",
                    "{datetime}": "Current date and time",
                    "{timestamp}": "Unix timestamp",
                    "{unix}": "Unix timestamp",
                },
            },
            "invite": {
                "description": "Invite variables (for join/leave)",
                "variables": {
                    "{inviter}": "Who created the invite",
                    "{invitee}": "Who joined using the invite",
                    "{invites}": "Inviter's total invite count",
                    "{code}": "Invite code",
                    "{url}": "Invite URL",
                },
            },
        }

        if category:
            category = category.lower()
            if category not in categories:
                await ctx.fail(
                    f"Invalid category `{category}`. Available: {', '.join(categories.keys())}"
                )
                return

            cat = categories[category]
            lines = [f"`{var}` — {desc}" for var, desc in cat["variables"].items()]
            embed = discord.Embed(
                color=self.color,
                title=cat["description"],
                description=compose(
                    body(*lines),
                    caption("Use these variables in embedcreate, autoresponders, and more"),
                ),
                timestamp=discord.utils.utcnow(),
            )
            return await ctx.send(embed=embed)

        pages = []
        for cat in categories.values():
            lines = [f"`{var}` — {desc}" for var, desc in cat["variables"].items()]
            pages.append(discord.Embed(
                color=self.color,
                title=cat["description"],
                description=compose(
                    body(*lines),
                    caption(f"Use {ctx.clean_prefix}variables <category> for more details"),
                ),
                timestamp=discord.utils.utcnow(),
            ))

        await send_pages(ctx, pages)

    @hybrid(
        name="serverinfo",
        description="View information about the server",
        aliases=["si", "server", "guildinfo", "gi"],
        guild_only=True,
    )
    async def serverinfo(self, ctx):
        """show server info"""
        g = ctx.guild
        e = aesthetic_embed(color=self.color, title=g.name, message="", timestamp=True)

        if g.icon:
            e.set_thumbnail(url=g.icon.url)

        if g.banner:
            e.set_image(url=g.banner.url)

        owner = g.owner
        owner_text = f"{owner} — {owner.id}" if owner else "Unknown"
        owner_icon = owner.display_avatar.url if owner else None
        e.set_author(name=f"owned by {owner_text}", icon_url=owner_icon)

        humans = sum(1 for m in g.members if not m.bot)
        bots = sum(1 for m in g.members if m.bot)

        categories = len(g.categories)
        text_channels = len(g.text_channels)
        voice_channels = len(g.voice_channels)
        total_channels = categories + text_channels + voice_channels

        role_limit = 250
        emoji_limit = g.emoji_limit or 50
        sticker_limit = getattr(g, "sticker_limit", 5) or 5

        boosters = getattr(g, "premium_subscribers", None) or []
        booster_count = len(boosters)

        features = g.features or []
        shown = features[:6]
        extra = len(features) - len(shown)
        features_str = ", ".join(f.replace("_", " ").title() for f in shown)
        if extra > 0:
            features_str += f" **+ {extra}** more"

        vanity = "N/A"
        if "VANITY_URL" in features:
            try:
                vinv = await g.vanity_invite()
                vanity = vinv.code
            except Exception:
                vanity = "N/A"

        mfa = "Require_2fa" if g.mfa_level else "None"

        e.add_field(
            name=f"Members ({g.member_count})",
            value=body(
                f"Boosters: `{booster_count}`",
                f"Humans: `{humans}`",
                f"Bots: `{bots}`",
            ),
            inline=True,
        )
        e.add_field(
            name=f"Counts ({total_channels})",
            value=body(
                f"Stickers: `{len(g.stickers)}/{sticker_limit}`",
                f"Emojis: `{len(g.emojis)}/{emoji_limit}`",
                f"Roles: `{len(g.roles)}/{role_limit}`",
            ),
            inline=True,
        )
        e.add_field(
            name=f"Channels ({total_channels})",
            value=body(
                f"Categories: `{categories}`",
                f"Text: `{text_channels}`",
                f"Voice: `{voice_channels}`",
            ),
            inline=True,
        )
        e.add_field(
            name="Boosts",
            value=body(
                f"Level: `{g.premium_tier}`",
                f"Boosts: `{g.premium_subscription_count or 0}`",
                f"Boosters: `{booster_count}`",
            ),
            inline=True,
        )

        icon_url = f"[view]({g.icon.url})" if g.icon else "`none`"
        banner_url = "`none`"
        splash_url = "`none`"
        if hasattr(g, "banner") and g.banner:
            banner_url = f"[view]({g.banner.url})"
        if hasattr(g, "splash") and g.splash:
            splash_url = f"[view]({g.splash.url})"
        e.add_field(
            name="Design",
            value=body(
                f"Icon: {icon_url}",
                f"Banner: {banner_url}",
                f"Splash: {splash_url}",
            ),
            inline=True,
        )
        e.add_field(
            name="System",
            value=body(
                f"Verification: `{str(g.verification_level).replace('_', ' ').title()}`",
                f"Mfa level: `{mfa}`",
                f"Vanity: `{vanity}`",
            ),
            inline=True,
        )
        if features_str:
            e.add_field(
                name=f"Features ({len(features)})",
                value=body(features_str),
                inline=False,
            )

        e.description = compose(
            e.description or "",
            caption(
                f"ID: {g.id} • Shard {g.shard_id if g.shard_id is not None else 0} • "
                f"Cluster ID {getattr(g, 'cluster_id', 'N/A')}"
            ),
        )
        await ctx.send(embed=e)

    @command(
        name="roles",
        aliases=["rolelist"],
        description="View all roles in the server",
    )
    async def roles(self, ctx):
        """list all roles"""
        lines = [r.mention for r in reversed(ctx.guild.roles) if r.name != "@everyone"]
        if not lines:
            from discord.ext.commands import CommandError
            raise CommandError("no roles in this server")
        e = aesthetic_embed(
            color=self.color,
            title=f"Roles ({len(lines)})",
            message=" ".join(lines),
        )
        await ctx.send(embed=e)

    @command(
        name="bots",
        description="List all bots in the server",
    )
    async def bots(self, ctx):
        """list all bots"""
        bots = [m for m in ctx.guild.members if m.bot]
        e = aesthetic_embed(
            color=self.color,
            title=f"Bots ({len(bots)})",
            message=" ".join(b.mention for b in bots) or "none",
        )
        await ctx.send(embed=e)

    @command(
        name="icon",
        aliases=["servericon", "guildicon"],
        description="View the server's icon",
    )
    async def icon(self, ctx):
        """show server icon"""
        if not ctx.guild.icon:
            from discord.ext.commands import CommandError
            raise CommandError("this server has no icon")
        e = aesthetic_embed(color=self.color, message="", timestamp=False)
        e.set_image(url=ctx.guild.icon.url)
        e.set_author(name=ctx.guild.name)
        await ctx.send(embed=e)

    @command(
        name="serverbanner",
        aliases=["guildbanner"],
        description="View the server's banner",
    )
    async def serverbanner(self, ctx):
        """show server banner"""
        if not ctx.guild.banner:
            from discord.ext.commands import CommandError
            raise CommandError("this server has no banner")
        e = aesthetic_embed(color=self.color, message="", timestamp=False)
        e.set_image(url=ctx.guild.banner.url)
        e.set_author(name=ctx.guild.name)
        await ctx.send(embed=e)
