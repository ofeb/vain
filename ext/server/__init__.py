from __future__ import annotations

import asyncio
import contextlib
import aiohttp
from io import BytesIO

import discord
from discord.ext.commands import command, group
from colorthief import ColorThief

from urllib.parse import urlparse

from core.discord.hybrid import hybrid, command
from core.discord.package import Package
from core.discord.views.paginate import send_pages
from core.discord.views.rolepages import (
    build_inrole_pages,
    build_roles_pages,
    build_booster_pages,
    build_booster_loss_pages,
)
from core.managers.permissions import has_permissions
from core.tools.embed import BadEmbed, ParseError, PreparedScript, parse

from core.discord.views.embed import compose, body, caption, c2, panel_container

_CLEAR_MEDIA = frozenset({"clear", "none", "off", "remove", "reset", "delete", "del"})
_MAX_GUILD_MEDIA_BYTES = 10 * 1024 * 1024

async def get_dominant_color(url: str, fallback: int = 0xE1D2DE) -> int:
    """Fetch image and return dominant color using colorthief."""
    if not url:
        return fallback
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url, timeout=8) as resp:
                if resp.status != 200:
                    return fallback
                data = await resp.read()

        def _extract():
            ct = ColorThief(BytesIO(data))
            r, g, b = ct.get_color(quality=1)

            if (r + g + b) < 80:
                r = min(r + 60, 255)
                g = min(g + 60, 255)
                b = min(b + 60, 255)
            return (r << 16) + (g << 8) + b

        return await asyncio.to_thread(_extract)
    except Exception:
        return fallback

async def get_bot_dominant_color(bot) -> int:
    if bot.user and bot.user.display_avatar:
        return await get_dominant_color(str(bot.user.display_avatar.url))
    return 0xE1D2DE

class ServerCommands(Package):
    """standalone server commands"""

    @staticmethod
    def _is_image_url(value: str) -> bool:
        parsed = urlparse((value or "").strip())
        return parsed.scheme in {"http", "https"} and bool(parsed.netloc)

    async def _read_guild_image(self, ctx, source: str | None) -> bytes | None:
        """Load image bytes from attachment or http(s) url for guild branding."""
        if not source:
            if not ctx.message.attachments:
                return None
            attachment = ctx.message.attachments[0]
            ctype = (attachment.content_type or "").lower()
            if ctype and not ctype.startswith("image/"):
                await ctx.warn("Invalid file type\n> -# **provide an image (png, jpg, gif, etc.)**")
                return None
            if attachment.size and attachment.size > _MAX_GUILD_MEDIA_BYTES:
                await ctx.warn("File too large\n> -# **max size is 10MB - try compressing the image**")
                return None
            data = await attachment.read()
            if len(data) > _MAX_GUILD_MEDIA_BYTES:
                await ctx.warn("File too large\n> -# **max size is 10MB - try compressing the image**")
                return None
            return data

        raw = source.strip()
        if raw.lower() in _CLEAR_MEDIA:
            return b""

        if not self._is_image_url(raw):
            await ctx.warn("Invalid URL\n> -# **provide a direct link to an image (http/https)**")
            return None

        try:
            timeout = aiohttp.ClientTimeout(total=15)
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.get(raw) as response:
                    if response.status != 200:
                        await ctx.fail("Failed to fetch image\n> -# **check if the url is valid and accessible**")
                        return None
                    content_type = (response.headers.get("content-type") or "").lower()
                    if "image/" not in content_type:
                        await ctx.warn("Invalid content type\n> -# **url must point directly to an image file**")
                        return None
                    data = await response.read()
                    if len(data) > _MAX_GUILD_MEDIA_BYTES:
                        await ctx.warn("File too large\n> -# **max size is 10MB - try compressing the image**")
                        return None
                    return data
        except (aiohttp.ClientError, asyncio.TimeoutError, ValueError):
            await ctx.fail("Failed to fetch image\n> -# **the url may be invalid or the server is unreachable**")
            return None

    async def _set_guild_media(
        self,
        ctx,
        *,
        field: str,
        label: str,
        source: str | None,
        requires_feature: str | None = None,
        feature_hint: str | None = None,
    ):
        """Shared set/clear path for icon, banner, and splash."""
        if ctx.guild is None:
            return await ctx.warn("Server only\n> -# **this command can only be used in a server**")

        me = ctx.guild.me
        if me is None or not me.guild_permissions.manage_guild:
            return await ctx.warn(
                f"Missing permissions\n> -# **you need `Manage Server` to change the {label}**"
            )

        if requires_feature and requires_feature not in (ctx.guild.features or []):
            return await ctx.warn(
                feature_hint
                or f"Feature required\n> -# **this server needs `{requires_feature.replace('_', ' ').title()}` to set a {label}**"
            )

        clear = bool(source and source.strip().lower() in _CLEAR_MEDIA)
        if clear:
            data = None
        else:
            data = await self._read_guild_image(ctx, source)
            if data is None:
                if not source and not ctx.message.attachments:
                    await ctx.warn(
                        f"Missing image\n> -# **provide an image url or attachment, or use `none` to clear**"
                    )
                return
            if data == b"":
                data = None
                clear = True

        reason = f"{label} {'cleared' if clear else 'updated'} by {ctx.author} ({ctx.author.id})"
        try:
            async with ctx.typing():
                await ctx.guild.edit(**{field: data}, reason=reason)
        except discord.Forbidden:
            return await ctx.warn(
                f"Missing permissions\n> -# **i don't have permission to change the {label}**"
            )
        except discord.HTTPException as error:
            message = getattr(error, "text", None) or str(error)
            if "):" in message:
                message = message.split("):", 1)[-1].strip()
            return await ctx.fail(
                f"Failed to update {label}\n> -# **{message or 'something went wrong - try again later'}**"
            )

        if clear:
            return await ctx.success(f"Cleared {label}\n> -# **server {label} has been cleared**")
        return await ctx.success(f"Updated {label}\n> -# **server {label} has been updated**")

    @staticmethod
    def _normalize_embed_script(script: str, *, prefer: str = "embed") -> str:
        """Normalize script mode.

        - ``{container}`` → container
        - ``{embed}`` / bare field tags → embed
        - plain text (no field tags) → plain content (no wrap)
        prefer is only used when the script has field tags but no mode tag and
        the caller explicitly wants containers (rare).
        """
        from core.tools.embed import (
            is_container_script,
            is_embed_script,
            maybe_wrap_embed_script,
        )

        from core.tools.embed import _strip_code_fences
        value = _strip_code_fences(str(script).strip())
        if not value:
            return value
        if is_container_script(value):
            return value
        
        if prefer == "container" and is_embed_script(value):
            lowered = value.lower()
            if not (
                lowered.startswith("{embed}")
                or lowered.startswith("embed$v")
                or lowered.startswith("{container}")
                or lowered.startswith("container$v")
            ):
                if value.startswith("$v{"):
                    return "{container}" + value
                if value.startswith("{"):
                    return f"{{container}}$v{value}"
        return maybe_wrap_embed_script(value)

    async def _send_embed_script(self, ctx, script: str, *, prefer: str = "embed"):
        normalized = self._normalize_embed_script(script, prefer=prefer)

        try:
            from core.tools.embed import Script
            sc = Script(normalized, user=ctx.author)

            rendered = sc.render(
                guild=ctx.guild,
                channel=ctx.channel,
                member=ctx.author,
                user=ctx.author,
                target=ctx.author,
                date=discord.utils.utcnow().strftime("%Y-%m-%d"),
                time=discord.utils.utcnow().strftime("%H:%M"),
                datetime=str(discord.utils.utcnow()),
            )
            normalized = self._normalize_embed_script(rendered, prefer=prefer)
        except Exception:
            pass

        from core.tools.embed import extract_self_destruct, is_container_script, is_embed_script

        if not is_embed_script(normalized) and not is_container_script(normalized):
            normalized, self_destruct = extract_self_destruct(normalized)
            payload = {"content": normalized}
            if self_destruct is not None:
                payload["delete_after"] = self_destruct
        else:
            try:
                payload = await parse(normalized, sendable=True)
            except (ParseError, BadEmbed) as error:
                return await ctx.warn(
                    f"Parse error\n> -# **{error}**"
                )

        if not payload or (
            payload.get("content") in {None, ""}
            and payload.get("embed") is None
            and payload.get("view") is None
        ):
            return await ctx.warn("Invalid script\n> -# **provide valid embed or container script code**")

        try:
            
            if payload.get("embed") is not None:
                return await ctx.send(
                    content=payload.get("content"),
                    embed=payload.get("embed"),
                    view=payload.get("view"),
                    raw_embed=True,
                    delete_after=payload.get("delete_after"),
                )
            return await PreparedScript(payload).send(ctx)
        except discord.HTTPException as error:
            message = str(error)
            if "):" in message:
                message = message.split("):", 1)[1].strip()
            return await ctx.warn(f"Send failed\n> -# **{message or 'invalid embed data'}**")

    @group(
        name="embedcreate",
        aliases=["ce", "createembed"],
        description="create and send a classic embed. use {embed} or bare {title}/{description}. supports variables",
        usage="(script)",
        example="{title: Hello from {guild.name}}$v{description: Sent by {user} in {channel.name} on {date}}$v{color: #5865F2}",
        invoke_without_command=True,
    )
    async def embedcreate(self, ctx, *, script: str = None):
        """Create a classic Discord embed using embed scripting."""
        if script is None:
            return await ctx.send_help()
        return await self._send_embed_script(ctx, script, prefer="embed")

    @embedcreate.command(
        name="preview",
        aliases=["view"],
        usage="(script)",
        example="{title: Hello}$v{description: Test}",
    )
    async def embedcreate_preview(self, ctx, *, script: str = None):
        """Preview an embed script without sending it."""
        if script is None:
            return await ctx.fail("Missing script\n> -# **provide an embed script to preview**")
        return await self._send_embed_script(ctx, script, prefer="embed")

    @group(
        name="containercreate",
        aliases=["cc", "createcontainer"],
        description="create and send a components v2 container. use {container}, {divider}, {title}, {description}, {button}",
        usage="(script)",
        example="{container}$v{title: Hello}$v{description: World}$v{divider}$v{button: link && Site && https://example.com}",
        invoke_without_command=True,
    )
    async def containercreate(self, ctx, *, script: str = None):
        """Create a Components V2 container using container scripting."""
        if script is None:
            return await ctx.send_help()
        return await self._send_embed_script(ctx, script, prefer="container")

    @containercreate.command(
        name="preview",
        aliases=["view"],
        usage="(script)",
    )
    async def containercreate_preview(self, ctx, *, script: str = None):
        """Preview a container script."""
        if script is None:
            return await ctx.fail("Missing script\n> -# **provide a container script to preview**")
        return await self._send_embed_script(ctx, script, prefer="container")

    @command(
        name="variables",
        aliases=["vars", "var", "variable"],
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
                    "{guild.vanity}": "Guild vanity code (e.g. bars)",
                    "{guild.vanity_url}": "Full discord.gg vanity invite URL",
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
                    "{timestamp}": "Unix timestamp (seconds)",
                    "{unix}": "Unix timestamp (seconds)",
                },
            },
            "timestamp": {
                "description": "Timestamp formats",
                "variables": {
                    "{timestamp}": "Raw unix seconds - use inside content, not as a field param",
                    "<t:{timestamp}:t>": "Short time - 16:20",
                    "<t:{timestamp}:T>": "Long time - 16:20:30",
                    "<t:{timestamp}:d>": "Short date - 20/04/2021",
                    "<t:{timestamp}:D>": "Long date - 20 April 2021",
                    "<t:{timestamp}:f>": "Short date/time - 20 April 2021 16:20",
                    "<t:{timestamp}:F>": "Long date/time - Tuesday, 20 April 2021 16:20",
                    "<t:{timestamp}:R>": "Relative - 2 months ago / in 3 days",
                    "{user.created_at}": "Account created (formatted)",
                    "{unix(user.created_at)}": "Account created (unix) - wrap in <t:…:R>",
                    "{user.joined_at}": "Server join (formatted)",
                    "{unix(user.joined_at)}": "Server join (unix)",
                    "$v{timestamp}": "Embed flag - sets embed timestamp to now (not a content var)",
                },
            },
            "honeypot": {
                "description": "Honeypot trap variables",
                "variables": {
                    "{honeypot.caught}": "Accounts caught count",
                    "{honeypot.caught_count}": "Accounts caught count",
                    "{honeypot.channel}": "Honeypot channel mention",
                    "{honeypot.channel.name}": "Honeypot channel name",
                    "{honeypot.channel.id}": "Honeypot channel ID",
                    "{honeypot.punishment}": "Configured punishment phrase (e.g. softbanned, timed out, kicked)",
                    "{honeypot.punishments}": "Configured punishment phrase (e.g. softbanned, timed out, kicked)",
                    "{guild.name}": "Server name",
                    "{guild.id}": "Server ID",
                    "{guild.icon}": "Server icon URL",
                    "{guild.member_count}": "Member count",
                },
            },
            "bumper": {
                "description": "Bump reminder variables (Disboard)",
                "variables": {
                    "{bumper}": "Member who bumped (mention)",
                    "{bumper.mention}": "Member who bumped (mention)",
                    "{bumper.name}": "Bumper username",
                    "{bumper.display}": "Bumper display name",
                    "{bumper.display_name}": "Bumper display name",
                    "{bumper.id}": "Bumper user ID",
                    "{bumper.userid}": "Bumper user ID",
                    "{bumper.avatar}": "Bumper avatar URL",
                    "{bumper.created_at}": "Bumper account created (formatted)",
                    "{user.mention}": "Same as bumper when used in bump scripts",
                    "{bump.role}": "Configured reminder role mention",
                    "{bump.channel}": "Configured reminder channel mention",
                    "{bump.next}": "Next bump unix timestamp",
                    "{bump.last}": "Last bump unix timestamp",
                    "{next_bump_at}": "Next bump unix timestamp",
                    "{last_bump_at}": "Last bump unix timestamp",
                    "{bumper_label}": "Bumper display name (or `nobody` when none)",
                    "{last_bump_ts}": "Last bump as `<t:…:R>` (or `never` when none)",
                    "{next_bump_ts}": "Next reminder as `<t:…:R>` (or `never` when none)",
                    "{timestamp}": "Unix timestamp (now)",
                    "{guild.name}": "Guild name",
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
            "giveaway": {
                "description": "Giveaway variables (winner DMs / scripts)",
                "variables": {
                    "{prize}": "Giveaway prize name",
                    "{giveaway.prize}": "Giveaway prize name",
                    "{winners}": "Winner mentions",
                    "{giveaway.winners}": "Winner mentions",
                    "{winner_count}": "Number of winners",
                    "{host}": "Giveaway host mention",
                    "{entries}": "Entry count",
                    "{jump_url}": "Link to the giveaway message",
                    "{giveaway.url}": "Link to the giveaway message",
                    "{user}": "Winner mention",
                    "{user.mention}": "Winner mention",
                    "{guild.name}": "Server name",
                },
            },
            "vanity": {
                "description": "Vanity status variables (vanity notifications)",
                "variables": {
                    "{vanity}": "Guild vanity code (e.g. bars)",
                    "{vanity.name}": "Guild vanity code",
                    "{vanity.code}": "Guild vanity code",
                    "{vanity.url}": "https://discord.gg/<vanity>",
                    "{guild.vanity}": "Guild vanity code",
                    "{vanity.role}": "Vanity reward role mention",
                    "{vanity.role.mention}": "Vanity reward role mention",
                    "{vanity.role.name}": "Vanity reward role name",
                    "{vanity.role.id}": "Vanity reward role ID",
                    "{user.mention}": "Member who started repping",
                },
            },
            "nuke": {
                "description": "Nuke / autonuke script variables",
                "variables": {
                    "{nuke.interval}": "Scheduled interval (autonuke)",
                    "{nuke.threshold}": "Same as interval (human duration)",
                    "{nuke.reconfigured}": "Systems re-pointed after clone (welcome, leave, boost, logs, …)",
                    "{nuke.channel}": "New channel mention after clone",
                    "{nuke.channel.name}": "New channel name",
                    "{nuke.channel.id}": "New channel id",
                    "{nuke.old}": "Old channel name before the nuke",
                    "{channel}": "New channel mention",
                    "{guild}": "Server name",
                    "{user}": "Member who triggered a manual nuke",
                },
            },
            "level": {
                "description": "Level-up message variables",
                "variables": {
                    "{level}": "New level reached",
                    "{xp}": "Current XP in this level",
                    "{target_xp}": "XP required for next level",
                    "{user}": "Member who leveled up",
                    "{user.mention}": "Member mention",
                    "{guild.name}": "Server name",
                },
            },
            "tag": {
                "description": "Server tag variables (tag notifications)",
                "variables": {
                    "{tag}": "Member's primary guild tag text",
                    "{tag.name}": "Member's primary guild tag text",
                    "{tag.role}": "Tag reward role mention",
                    "{tag.role.mention}": "Tag reward role mention",
                    "{tag.role.name}": "Tag reward role name",
                    "{tag.role.id}": "Tag reward role ID",
                    "{user.mention}": "Member who started repping the tag",
                },
            },
        }

        if category:
            category = category.lower()
            if category not in categories:
                await ctx.fail(
                    f"Invalid category\n> -# **`{category}` is not a valid variable category**"
                )
                return

            cat = categories[category]
            lines = [f"`{var}` - {desc}" for var, desc in cat["variables"].items()]
            embed = panel_container(
                color=self.color,
                title=cat["description"],
                lines=lines,
                footer="Use these variables in embedcreate, autoresponders, and more",
                timestamp=True,
            )
            return await ctx.send(embed=embed)

        pages = []
        search_options = []
        for idx, (key, cat) in enumerate(categories.items()):
            lines = [f"`{var}` - {desc}" for var, desc in cat["variables"].items()]
            pages.append(panel_container(
                color=self.color,
                title=cat["description"],
                lines=lines,
                footer=f"Use {ctx.invoke_prefix}variables <category> for more details",
                timestamp=True,
            ))
            search_options.append(
                discord.SelectOption(
                    label=cat["description"][:100],
                    value=str(idx),
                    description=key[:100],
                )
            )

        await send_pages(
            ctx,
            pages,
            search_options=search_options,
            search_placeholder="Jump to category…",
        )

    @command(
        name="serverinfo",
        description="view detailed information about the current server",
        aliases=["si", "server", "guildinfo", "gi"],
        usage="",
        example=",serverinfo",
    )
    async def serverinfo(self, ctx):
        """show server info"""
        g = ctx.guild

        try:
            dom_color = await get_bot_dominant_color(self.bot)
        except Exception:
            dom_color = self.color

        owner = g.owner

        if owner is None and g.owner_id:
            try:
                owner = await g.fetch_member(g.owner_id)
            except Exception:
                owner = None

        owner_text = f"<@{owner.id}>" if owner else (
            f"<@{g.owner_id}>" if g.owner_id else "Unknown"
        )

        humans = sum(1 for member in g.members if not member.bot)
        bots = sum(1 for member in g.members if member.bot)

        categories = len(g.categories)
        text_channels = len(g.text_channels)
        voice_channels = len(g.voice_channels)
        total_channels = text_channels + voice_channels

        role_limit = 250
        emoji_limit = g.emoji_limit or 50
        sticker_limit = getattr(g, "sticker_limit", 5) or 5

        boosters = getattr(g, "premium_subscribers", None) or []
        booster_count = len(boosters)

        features = g.features or []
        shown_features = features[:6]
        extra_features = max(0, len(features) - len(shown_features))

        features_str = ", ".join(
            feature.replace("_", " ").title()
            for feature in shown_features
        )

        if extra_features:
            features_str += f" **+ {extra_features}** more"

        vanity = "None"

        if "VANITY_URL" in features:
            try:
                invite = await g.vanity_invite()
                vanity = invite.code if invite else "None"
            except Exception:
                vanity = "None"

        mfa = "Required" if g.mfa_level else "None"

        created = (
            f"<t:{int(g.created_at.timestamp())}:D> "
            f"(<t:{int(g.created_at.timestamp())}:R>)"
        )

        icon_url = g.icon.url if g.icon else None
        banner_url = g.banner.url if g.banner else None
        splash_url = g.splash.url if g.splash else None

        content = (
            f"-# **{g.name}**\n"
            f"> -# **Owner:** {owner_text}\n"
            f"> -# **Created:** {created}\n"
            f"> -# **Verification:** `{str(g.verification_level).replace('_', ' ').title()}`\n"
            f"> -# **Vanity:** `{vanity}`\n"
            f"> -# **MFA:** `{mfa}`\n"
            f"> -# **Guild ID:** `{g.id}`\n"
            f"\n"
            f"-# **Members**\n"
            f"> -# Total: `{g.member_count}`\n"
            f"> -# Humans: `{humans}`\n"
            f"> -# Bots: `{bots}`\n"
            f"> -# Boosters: `{booster_count}`\n"
            f"\n"
            f"-# **Channels ({total_channels})**\n"
            f"> -# Text: `{text_channels}`\n"
            f"> -# Voice: `{voice_channels}`\n"
            f"> -# Categories: `{categories}`\n"
            f"\n"
            f"-# **Counts**\n"
            f"> -# Roles: `{len(g.roles)}/{role_limit}`\n"
            f"> -# Emojis: `{len(g.emojis)}/{emoji_limit}`\n"
            f"> -# Stickers: `{len(g.stickers)}/{sticker_limit}`\n"
            f"\n"
            f"-# **Boosts**\n"
            f"> -# Level: `{g.premium_tier}`\n"
            f"> -# Boosts: `{g.premium_subscription_count or 0}`\n"
            f"> -# Boosters: `{booster_count}`"
        )

        if features_str:
            content += (
                f"\n\n"
                f"-# **Features ({len(features)})**\n"
                f"> -# {features_str}"
            )

        container = discord.ui.Container()

        container.add_item(
            discord.ui.TextDisplay(content)
        )

        assets = []

        if icon_url:
            assets.append(
                discord.ui.Button(
                    label="Icon",
                    style=discord.ButtonStyle.link,
                    url=icon_url,
                )
            )

        if banner_url:
            assets.append(
                discord.ui.Button(
                    label="Banner",
                    style=discord.ButtonStyle.link,
                    url=banner_url,
                )
            )

        if splash_url:
            assets.append(
                discord.ui.Button(
                    label="Splash",
                    style=discord.ButtonStyle.link,
                    url=splash_url,
                )
            )

        if assets:
            container.add_item(
                discord.ui.ActionRow(*assets)
            )

        view = discord.ui.LayoutView()
        view.add_item(container)

        await ctx.send(view=view)

    @staticmethod
    def _strip_commas(value: str) -> str:
        cleaned = (value or "").strip()
        while cleaned and cleaned[-1] in ",;":
            cleaned = cleaned[:-1].strip()
        return cleaned

    @classmethod
    def _find_any_channel(cls, guild: discord.Guild, value: str):
        raw = cls._strip_commas(value)
        if not raw:
            return None
        token = raw
        if token.startswith("<#") and token.endswith(">"):
            token = token[2:-1]
            if token.startswith("!"):
                token = token[1:]
        if token.isdigit():
            channel = guild.get_channel(int(token))
            if channel is not None:
                return channel
        lowered = raw.lower()
        return discord.utils.find(lambda c: c.name.lower() == lowered, guild.channels)

    @classmethod
    def _find_category(cls, guild: discord.Guild, value: str):
        raw = cls._strip_commas(value)
        if not raw:
            return None
        if raw.lower() in {"none", "reset", "clear", "remove"}:
            return "__none__"
        token = raw
        if token.startswith("<#") and token.endswith(">"):
            token = token[2:-1]
        if token.isdigit():
            channel = guild.get_channel(int(token))
            if isinstance(channel, discord.CategoryChannel):
                return channel
        lowered = raw.lower()
        return discord.utils.find(
            lambda c: isinstance(c, discord.CategoryChannel) and c.name.lower() == lowered,
            guild.categories,
        )

    @classmethod
    def _split_channel_args(cls, guild: discord.Guild, value: str):
        """Split '<channel> <tail>' - tolerates multi-word names and commas."""
        raw = cls._strip_commas(value or "")
        if not raw:
            return None, ""
        if "," in raw:
            head, tail = raw.split(",", 1)
            return cls._find_any_channel(guild, head), cls._strip_commas(tail)
        tokens = raw.split()
        for i in range(len(tokens), 0, -1):
            candidate = " ".join(tokens[:i])
            found = cls._find_any_channel(guild, candidate)
            if found is not None:
                return found, cls._strip_commas(" ".join(tokens[i:]))
        return cls._find_any_channel(guild, tokens[0]), cls._strip_commas(" ".join(tokens[1:]))

    @group(
        name="channel",
        aliases=["chan"],
        description="create, delete and reorganise server channels",
        usage="",
        example=",channel create general",
    )
    @has_permissions(manage_channels=True)
    async def channel(self, ctx):
        """manage server channels"""
        return await ctx.send_help(ctx.command)

    @channel.command(
        name="create",
        aliases=["add"],
        description="create a text or voice channel",
        usage="<name> [category] [voice]",
        example=",channel create general, General --voice",
    )
    @has_permissions(manage_channels=True)
    async def channel_create(self, ctx, *, payload: str):
        """create a channel - include 'voice' for a voice channel"""
        text = self._strip_commas(payload)
        if not text:
            return await ctx.warn("Usage: `channel create <name> [category] [voice]`")
        kind = "text"
        tokens = text.split()
        lowered = [t.lower().strip(",") for t in tokens]
        if "voice" in lowered:
            kind = "voice"
            idx = lowered.index("voice")
            tokens.pop(idx)
            text = " ".join(tokens).strip()
        pieces = [p.strip() for p in text.split(",") if p.strip()]
        name = self._strip_commas(pieces[0])
        if not name:
            return await ctx.warn("Provide a **name** for the new channel")
        category = None
        if len(pieces) > 1:
            category_raw = ",".join(pieces[1:])
            resolved = self._find_category(ctx.guild, category_raw)
            if isinstance(resolved, discord.CategoryChannel):
                category = resolved
            elif resolved is None:
                return await ctx.warn(f"No category found for **{self._strip_commas(category_raw)}**")
        reason = f"{ctx.author} used channel create"
        try:
            if kind == "voice":
                created = await ctx.guild.create_voice_channel(name=name, category=category, reason=reason)
            else:
                created = await ctx.guild.create_text_channel(name=name, category=category, reason=reason)
        except discord.HTTPException as exc:
            return await ctx.warn(f"I couldn't create **{name}** - `{exc}`")
        where = f" under {category.mention}" if category else ""
        return await ctx.success(f"Created {created.mention}{where}")

    @channel.command(
        name="delete",
        aliases=["del", "remove"],
        description="delete a channel by mention, id or name",
        usage="<channel>",
        example=",channel delete #general",
    )
    @has_permissions(manage_channels=True)
    async def channel_delete(self, ctx, *, target: str):
        """delete a channel"""
        target_channel = self._find_any_channel(ctx.guild, target)
        if target_channel is None:
            return await ctx.warn(f"No channel found for **{self._strip_commas(target)}**")
        mention = getattr(target_channel, "mention", f"`{target_channel.name}`")
        await target_channel.delete(reason=f"{ctx.author} used channel delete")
        return await ctx.success(f"Deleted {mention}")

    @channel.command(
        name="duplicate",
        aliases=["copy", "clone"],
        description="duplicate a channel with its permissions",
        usage="<channel>",
        example=",channel duplicate #general",
    )
    @has_permissions(manage_channels=True)
    async def channel_duplicate(self, ctx, *, target: str):
        """clone a channel"""
        target_channel = self._find_any_channel(ctx.guild, target)
        if target_channel is None:
            return await ctx.warn(f"No channel found for **{self._strip_commas(target)}**")
        try:
            clone = await target_channel.clone(reason=f"{ctx.author} used channel duplicate")
        except discord.HTTPException as exc:
            return await ctx.warn(f"I couldn't duplicate **{target_channel.name}** - `{exc}`")
        return await ctx.success(f"Duplicated {target_channel.mention} → {clone.mention}")

    @channel.command(
        name="rename",
        aliases=["name"],
        description="rename a channel",
        usage="<channel> <new name>",
        example=",channel rename #general chat",
    )
    @has_permissions(manage_channels=True)
    async def channel_rename(self, ctx, *, payload: str):
        """rename a channel"""
        target_channel, new_name = self._split_channel_args(ctx.guild, payload)
        if target_channel is None:
            return await ctx.warn("No matching **channel** found")
        if not new_name:
            return await ctx.warn("Provide a **new name** for the channel")
        old = target_channel.name
        try:
            await target_channel.edit(name=new_name, reason=f"{ctx.author} used channel rename")
        except discord.HTTPException as exc:
            return await ctx.warn(f"I couldn't rename **{old}** - `{exc}`")
        return await ctx.success(f"Renamed `{old}` → `{new_name}`")

    @channel.command(
        name="description",
        aliases=["topic", "desc"],
        description="set the channel description (text channels)",
        usage="<channel> [description]",
        example=",channel description #general chill vibes only",
    )
    @has_permissions(manage_channels=True)
    async def channel_description(self, ctx, *, payload: str):
        """set or clear a channel's description"""
        target_channel, description = self._split_channel_args(ctx.guild, payload)
        if target_channel is None:
            return await ctx.warn("No matching **channel** found")
        if not hasattr(target_channel, "topic"):
            return await ctx.warn(f"{getattr(target_channel, 'mention', 'This channel')} doesn't support descriptions")
        cleared = description.lower() in {"none", "clear", "reset", "remove"} if description else True
        topic = None if cleared else description[:1024]
        try:
            await target_channel.edit(topic=topic, reason=f"{ctx.author} used channel description")
        except discord.HTTPException as exc:
            return await ctx.warn(f"I couldn't update **{target_channel.name}** - `{exc}`")
        if cleared:
            return await ctx.success(f"Cleared the description of {target_channel.mention}")
        return await ctx.success(f"Set the description of {target_channel.mention}:\n> {topic}")

    @channel.command(
        name="move",
        description="move a channel into another category",
        usage="<channel> <new category|none>",
        example=",channel move #general, Text Channels",
    )
    @has_permissions(manage_channels=True)
    async def channel_move(self, ctx, *, payload: str):
        """move a channel into a category ('none' to uncategory it)"""
        target_channel, category_raw = self._split_channel_args(ctx.guild, payload)
        if target_channel is None:
            return await ctx.warn("No matching **channel** found")
        if isinstance(target_channel, discord.CategoryChannel):
            return await ctx.warn("You can't move a **category** into another category")
        if not category_raw:
            return await ctx.warn("Provide a **category** (or `none`) to move it into")
        resolved = self._find_category(ctx.guild, category_raw)
        if resolved is None:
            return await ctx.warn(f"No category found for **{self._strip_commas(category_raw)}**")
        category = None if resolved == "__none__" else resolved
        destination = category.mention if category else "**no category**"
        try:
            await target_channel.edit(category=category, reason=f"{ctx.author} used channel move")
        except discord.HTTPException as exc:
            return await ctx.warn(f"I couldn't move **{target_channel.name}** - `{exc}`")
        return await ctx.success(f"Moved {target_channel.mention} to {destination}")

    @group(
        name="boosters",
        aliases=["bstrs"],
        description="view all users currently boosting the server",
        usage="",
        example=",boosters",
    )
    async def boosters(self, ctx):
        """view all users currently boosting the server"""
        members = list(ctx.guild.premium_subscribers)
        if not members:
            return await ctx.warn("no users are **boosting** this server")
        pages = build_booster_pages(ctx.guild, members)
        await send_pages(ctx, pages)

    @boosters.command(
        name="lost",
        description="view users who are no longer boosting the server",
        usage="",
        example=",boosters lost",
    )
    async def boosters_lost(self, ctx):
        """view users who are no longer boosting the server"""
        rows = await self.db.fetch(
            "SELECT user_id, user_name, lost_at FROM booster_losses "
            "WHERE guild_id = $1 ORDER BY lost_at DESC",
            ctx.guild.id,
        )
        if not rows:
            return await ctx.warn("no users have **stopped boosting** this server")
        losses = []
        for row in rows:
            member = ctx.guild.get_member(row["user_id"])
            name = member.display_name if member else (row["user_name"] or str(row["user_id"]))
            losses.append(
                {
                    "user_id": row["user_id"],
                    "name": name,
                    "lost_at": row["lost_at"],
                }
            )
        pages = build_booster_loss_pages(ctx.guild, losses)
        await send_pages(ctx, pages)

    @Package.listener("on_member_update")
    async def _booster_track_update(self, before: discord.Member, after: discord.Member) -> None:
        if before.premium_since == after.premium_since:
            return
        if after.premium_since and not before.premium_since:
            with contextlib.suppress(Exception):
                await self.db.execute(
                    "DELETE FROM booster_losses WHERE guild_id = $1 AND user_id = $2",
                    after.guild.id, after.id,
                )
        elif before.premium_since and not after.premium_since:
            with contextlib.suppress(Exception):
                await self.db.execute(
                    "INSERT INTO booster_losses (guild_id, user_id, user_name) "
                    "VALUES ($1, $2, $3) "
                    "ON CONFLICT (guild_id, user_id) "
                    "DO UPDATE SET lost_at = CURRENT_TIMESTAMP, user_name = EXCLUDED.user_name",
                    after.guild.id, after.id, after.display_name,
                )

    @Package.listener("on_member_remove")
    async def _booster_track_remove(self, member: discord.Member) -> None:
        if not member.premium_since:
            return
        with contextlib.suppress(Exception):
            await self.db.execute(
                "INSERT INTO booster_losses (guild_id, user_id, user_name) "
                "VALUES ($1, $2, $3) "
                "ON CONFLICT (guild_id, user_id) "
                "DO UPDATE SET lost_at = CURRENT_TIMESTAMP, user_name = EXCLUDED.user_name",
                member.guild.id, member.id, member.display_name,
            )

    @command(
        name="roles",
        aliases=["rolelist"],
        description="view all roles in the server",
    )
    async def roles(self, ctx):
        """list all roles"""
        roles = [r for r in reversed(ctx.guild.roles) if r.name != "@everyone"]
        if not roles:
            from discord.ext.commands import CommandError
            raise CommandError("no roles in this server")
        pages = build_roles_pages(ctx.guild, roles)
        await send_pages(ctx, pages)

    @command(
        name="inrole",
        aliases=["membersinrole", "withrole", "dump"],
        description="list every member with a role",
        usage="<role>",
        example=",inrole members",
    )
    async def inrole(self, ctx, *, role: discord.Role):
        """list members holding a role"""
        members = role.members
        if not members:
            from discord.ext.commands import CommandError
            raise CommandError(f"no members have {role.mention}")
        pages = build_inrole_pages(role, members)
        await send_pages(ctx, pages)

    @command(
        name="bots",
        description="list all bots in the server",
    )
    async def bots(self, ctx):
        """list all bots"""
        bots = [m for m in ctx.guild.members if m.bot]
        e = c2(
            color=self.color,
            title=f"Bots ({len(bots)})",
            message=" ".join(b.mention for b in bots) or "none",
        )
        await ctx.send(embed=e)

    @command(
        name="icon",
        aliases=["servericon", "guildicon"],
        description="view the server icon",
        guild_only=True,
    )
    async def icon(self, ctx):
        return await self.serveravatar(ctx)

    @command(
        name="serveravatar",
        aliases=["sav"],
        description="view the server avatar or a user's avatar",
        usage="[member]",
        guild_only=True,
    )
    async def serveravatar(self, ctx, member: discord.Member = None):
        from discord import ui as _ui
        from core.discord.ctx import layout_from_items

        if member:
            if not member.guild_avatar:
                return await ctx.warn(f"**{member.display_name}** has no server avatar")
            url = str(member.guild_avatar.replace(size=4096).url)
            label = f"**{member.display_name}'s server avatar**"
        else:
            if not ctx.guild or not ctx.guild.icon:
                return await ctx.warn("this server has no avatar")
            url = str(ctx.guild.icon.replace(size=4096).url)
            label = f"**{ctx.guild.name}'s server avatar**"

        container = _ui.Container()
        for attr in ("accent_color", "accent_colour"):
            if hasattr(container, attr):
                with contextlib.suppress(Exception):
                    setattr(container, attr, None)
        container.add_item(_ui.TextDisplay(label))
        try:
            container.add_item(_ui.MediaGallery(discord.MediaGalleryItem(url)))
        except Exception:
            container.add_item(_ui.TextDisplay(f"[open avatar]({url})"))
        await ctx.send(view=layout_from_items([container], timeout=None))

    @command(
        name="serverbanner",
        aliases=["sbanner", "guildbanner"],
        description="view the server banner or a user's banner",
        usage="[member]",
        guild_only=True,
    )
    async def serverbanner(self, ctx, member: discord.Member = None):
        from discord import ui as _ui
        from core.discord.ctx import layout_from_items

        if member:
            if not member.guild_banner:
                return await ctx.warn(f"**{member.display_name}** has no server banner")
            banner_url = str(member.guild_banner.replace(size=4096).url)
            label = f"**{member.display_name}'s server banner**"
        else:
            if not ctx.guild or not ctx.guild.banner:
                return await ctx.warn("this server has no banner")
            banner_url = str(ctx.guild.banner.replace(size=4096).url)
            label = f"**{ctx.guild.name}'s server banner**"

        container = _ui.Container()
        for attr in ("accent_color", "accent_colour"):
            if hasattr(container, attr):
                with contextlib.suppress(Exception):
                    setattr(container, attr, None)
        container.add_item(_ui.TextDisplay(label))
        try:
            container.add_item(_ui.MediaGallery(discord.MediaGalleryItem(banner_url)))
        except Exception:
            container.add_item(_ui.TextDisplay(f"[open banner]({banner_url})"))
        await ctx.send(view=layout_from_items([container], timeout=None))

    @command(
        name="seticon",
        aliases=["setservericon", "guildiconset"],
        description="set or clear the server icon from an attachment or image url",
        usage="[url or none]",
        example=",seticon https://i.imgur.com/icon.png",
    )
    @has_permissions(manage_guild=True)
    async def seticon(self, ctx, source: str = None):
        """set server icon"""
        return await self._set_guild_media(
            ctx,
            field="icon",
            label="icon",
            source=source,
        )

    @command(
        name="setbanner",
        aliases=["setserverbanner", "guildbannerset"],
        description="set or clear the server banner from an attachment or image url (boost level 2+)",
        usage="[url or none]",
        example=",setbanner https://i.imgur.com/banner.png",
    )
    @has_permissions(manage_guild=True)
    async def setbanner(self, ctx, source: str = None):
        """set server banner"""
        return await self._set_guild_media(
            ctx,
            field="banner",
            label="banner",
            source=source,
            requires_feature="BANNER",
            feature_hint="this server needs **boost level 2** (or the banner feature) to set a **banner**",
        )

    @command(
        name="setsplash",
        aliases=["setserversplash", "guildsplashset", "setinvitesplash"],
        description="set or clear the invite splash from an attachment or image url (boost level 1+)",
        usage="[url or none]",
        example=",setsplash https://i.imgur.com/splash.png",
    )
    @has_permissions(manage_guild=True)
    async def setsplash(self, ctx, source: str = None):
        """set invite splash"""
        return await self._set_guild_media(
            ctx,
            field="splash",
            label="splash",
            source=source,
            requires_feature="INVITE_SPLASH",
            feature_hint="this server needs **boost level 1** (or invite splash) to set a **splash**",
        )

from asyncio import Lock
from collections import defaultdict

from discord.ext import commands
from typing import TYPE_CHECKING

from core.discord.mixin import _Meta
from core.discord.package import Package

from .extended.alias import AliasCommands
from .extended.autoresponder import AutoresponderCommands
from .extended.badge import BadgeCommands
from .extended.boost import BoostCommands
from .extended.boosterrole import BoosterroleCommands
from .extended.customize import CustomizeCommands
from .extended.disable.command import CommandDisableCommands
from .extended.disable.event import EventDisableCommands
from .extended.disable.module import ModuleDisableCommands
from .extended.enable.command import CommandEnableCommands
from .extended.enable.event import EventEnableCommands
from .extended.enable.module import ModuleEnableCommands
from .extended.filter import FilterCommands
from .extended.goodbye import GoodbyeCommands
from .extended.ignore import IgnoreCommands
from .extended.imgonly import ImgonlyCommands
from .extended.invoke import InvokeCommands
from .extended.pagination import PaginationCommands
from .extended.pin import PinCommands
from .extended.prefix import PrefixCommands
from .extended.reposter import ReposterCommands
from .extended.set import SetCommands
from .extended.settings import SettingsCommands
from .extended.stickymessage import StickymessageCommands
from .extended.suggest import SuggestCommands
from .extended.webhook import WebhookCommands
from .extended.welcome import WelcomeCommands
from .extended.steal import Steal
from .extended.embedcode import Embedcode
from .extended.embed import EmbedCommands
from .extended.vanity import VanityCommands
from .extended.tag import TagCommands
from .extended.pingonjoin import PingOnJoinCommands
from .events import ServerEvents

if TYPE_CHECKING:
    from core.vain import Vain

class Server(
    ServerCommands,
    PrefixCommands,
    AliasCommands,
    WebhookCommands,
    BoosterroleCommands,
    BoostCommands,
    WelcomeCommands,
    GoodbyeCommands,
    StickymessageCommands,
    InvokeCommands,
    CustomizeCommands,
    PaginationCommands,
    CommandDisableCommands,
    CommandEnableCommands,
    EventDisableCommands,
    EventEnableCommands,
    ModuleDisableCommands,
    ModuleEnableCommands,
    IgnoreCommands,
    AutoresponderCommands,
    ImgonlyCommands,
    FilterCommands,
    PinCommands,
    SetCommands,
    BadgeCommands,
    SettingsCommands,
    ReposterCommands,
    SuggestCommands,
    Steal,
    Embedcode,
    EmbedCommands,
    VanityCommands,
    TagCommands,
    PingOnJoinCommands,
    ServerEvents,
    Package,
    metaclass=_Meta,
):
    """main server extension - all subcommands combined"""

    def __init__(self, bot: Vain) -> None:
        Package.__init__(self, bot)
        self.ar_locks = defaultdict(Lock)
        self.leave_locks = defaultdict(Lock)
        self.join_locks = defaultdict(Lock)
        self.boost_locks = defaultdict(Lock)
        self.sticky_locks = defaultdict(Lock)
        self.pinned_ids = {}
        
        self._msg_counts: dict[int, int] = defaultdict(int)
        self._last_activity: dict = {}
        self._pending_repost: set[int] = set()
        self._last_repost_at: dict[int, float] = {}
        self._worker_task = None
        from asyncio import Queue as _Queue

        self._queue = _Queue()

    async def cog_load(self) -> None:
        
        with contextlib.suppress(Exception):
            await StickymessageCommands._ensure_schema(self)  # type: ignore[misc]
        with contextlib.suppress(Exception):
            StickymessageCommands._ensure_runtime(self)  # type: ignore[misc]
        with contextlib.suppress(Exception):
            await FilterCommands._ensure_words_table(self)  # type: ignore[misc]
        with contextlib.suppress(Exception):
            await ImgonlyCommands.cog_load(self)  # type: ignore[misc]

async def setup(bot: Vain) -> None:
    """load server extension"""
    await bot.add_cog(Server(bot))
