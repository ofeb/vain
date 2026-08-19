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
from core.discord.views.rolepages import build_inrole_pages, build_roles_pages
from core.managers.permissions import has_permissions
from core.tools.embed import BadEmbed, ParseError, PreparedScript, parse

from core.discord.views.embed import compose, body, caption, c2

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
                await ctx.warn("File too large\n> -# **max size is 10MB — try compressing the image**")
                return None
            data = await attachment.read()
            if len(data) > _MAX_GUILD_MEDIA_BYTES:
                await ctx.warn("File too large\n> -# **max size is 10MB — try compressing the image**")
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
                        await ctx.warn("File too large\n> -# **max size is 10MB — try compressing the image**")
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
                f"Failed to update {label}\n> -# **{message or 'something went wrong — try again later'}**"
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
        search_options = []
        for idx, (key, cat) in enumerate(categories.items()):
            lines = [f"`{var}` - {desc}" for var, desc in cat["variables"].items()]
            pages.append(discord.Embed(
                color=self.color,
                title=cat["description"],
                description=compose(
                    body(*lines),
                    caption(f"Use {ctx.clean_prefix}variables <category> for more details"),
                ),
                timestamp=discord.utils.utcnow(),
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
            search_title="Variable categories",
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

        e = c2(color=dom_color, title=g.name, message=f"Server created <t:{int(g.created_at.timestamp())}:R> • ID: `{g.id}`", timestamp=True)

        if g.icon:
            e.set_thumbnail(url=g.icon.url)

        if g.banner:
            e.set_image(url=g.banner.url)

        owner = g.owner
        if owner is None and g.owner_id:
            try:
                owner = await g.fetch_member(g.owner_id)
            except Exception:
                owner = None
        if owner:
            owner_text = f"{owner} (`{owner.id}`)"
            owner_icon = getattr(owner, 'display_avatar', None) and owner.display_avatar.url
        else:
            owner_text = f"Unknown (`{g.owner_id}`)"
            owner_icon = None
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
        description="view the server avatar",
        guild_only=True,
    )
    async def serveravatar(self, ctx):
        if not ctx.guild or not ctx.guild.icon:
            return await ctx.warn("this server has no avatar")
        url = str(ctx.guild.icon.replace(size=4096).url)
        from discord import ui as _ui
        from core.discord.ctx import layout_from_items
        container = _ui.Container()
        for attr in ("accent_color", "accent_colour"):
            if hasattr(container, attr):
                with contextlib.suppress(Exception):
                    setattr(container, attr, None)
        container.add_item(_ui.TextDisplay(f"**{ctx.guild.name}'s server avatar**"))
        try:
            container.add_item(_ui.MediaGallery(discord.MediaGalleryItem(url)))
        except Exception:
            container.add_item(_ui.TextDisplay(f"[open avatar]({url})"))
        await ctx.send(view=layout_from_items([container], timeout=None))

    @command(
        name="serverbanner",
        aliases=["sbanner", "guildbanner"],
        description="view the server banner",
        guild_only=True,
    )
    async def serverbanner(self, ctx):
        if not ctx.guild or not ctx.guild.banner:
            return await ctx.warn("this server has no banner")
        url = str(ctx.guild.banner.replace(size=4096).url)
        from discord import ui as _ui
        from core.discord.ctx import layout_from_items
        container = _ui.Container()
        for attr in ("accent_color", "accent_colour"):
            if hasattr(container, attr):
                with contextlib.suppress(Exception):
                    setattr(container, attr, None)
        container.add_item(_ui.TextDisplay(f"**{ctx.guild.name}'s server banner**"))
        try:
            container.add_item(_ui.MediaGallery(discord.MediaGalleryItem(url)))
        except Exception:
            container.add_item(_ui.TextDisplay(f"[open banner]({url})"))
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
