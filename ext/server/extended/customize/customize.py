from __future__ import annotations

from urllib.parse import urlparse

import aiohttp
import discord
from discord import Embed
from discord.ext.commands import group

from core.discord.package import Package
from core.managers.permissions import has_permissions

BIO_LINKS = ("https://vain.bot/", "discord.gg/vainbot")
BIO_MAX_LENGTH = 190
CLEAR_WORDS = {"clear", "none", "off", "remove", "reset"}

VALID_EMOJI_KEYS = {
    "success", "approve", "warn", "deny", "cooldown", "loading", "info", "information", "shazam",
}
VALID_COLOR_KEYS = {
    "base", "approve", "warn", "deny", "cooldown", "settings", "dark", "information", "shazam",
}
VALID_VM_EMOJI_KEYS = {
    "lock", "unlock", "ghost", "reveal", "claim", "disconnect", "activity", "increase", "decrease",
}


class CustomizeCommands(Package):
    """customize bot look in server"""

    async def _require_server_owner(self, ctx) -> bool:
        if ctx.guild is None:
            await ctx.warn("this command only works in **guilds**")
            return False
        if ctx.author.id != ctx.guild.owner_id:
            await ctx.warn("only the **server owner** can use this command")
            return False
        return True

    @staticmethod
    def _is_image_url(value: str) -> bool:
        parsed = urlparse(value.strip())
        return parsed.scheme in {"http", "https"} and bool(parsed.netloc)

    async def _read_image_bytes(self, ctx, source: str | None) -> bytes | None:
        if not source:
            if not ctx.message.attachments:
                return None

            attachment = ctx.message.attachments[0]
            if not attachment.content_type or not attachment.content_type.startswith("image/"):
                await ctx.warn("uploaded file must be a **valid image**")
                return None
            return await attachment.read()

        if not self._is_image_url(source):
            await ctx.warn("provide a valid **http** or **https** image url")
            return None

        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(source) as response:
                    content_type = response.headers.get("content-type", "")
                    if response.status != 200:
                        await ctx.fail("failed to fetch that image")
                        return None
                    if "image/" not in content_type:
                        await ctx.warn("that url must point to a **valid image**")
                        return None
                    return await response.read()
        except (aiohttp.ClientError, ValueError):
            await ctx.fail("failed to fetch that image")
            return None

    def _normalized_bio(self, text: str) -> str:
        bio = text.strip()
        lower = bio.lower()
        if not any(link in lower for link in BIO_LINKS):
            bio = f"{bio}\nhttps://vain.bot/"
        return bio

    async def _reset_server_profile(self, ctx) -> list[str]:
        """Clear per-server bot nickname, avatar, banner, and bio."""
        warnings: list[str] = []
        me = ctx.guild.me
        reason = f"customize reset by {ctx.author}"
        for label, kwargs in (
            ("nickname", {"nick": None}),
            ("avatar", {"avatar": None}),
            ("banner", {"banner": None}),
            ("bio", {"bio": None}),
        ):
            try:
                await me.edit(reason=reason, **kwargs)
            except discord.Forbidden:
                warnings.append(f"missing permission to reset my **{label}**")
            except discord.HTTPException:
                warnings.append(f"failed to reset my **{label}**")
        return warnings

    @group(
        name="customize",
        aliases=["customization"],
        description="Customize the bot's appearance in your server",
        invoke_without_command=True,
    )
    async def customize(self, ctx):
        """show customize help"""
        if not await self._require_server_owner(ctx):
            return
        await ctx.send_help(ctx.command)

    @customize.command(
        name="reset",
        description="Reset all server customizations",
    )
    async def customize_reset(self, ctx):
        """Reset all server customizations."""
        if not await self._require_server_owner(ctx):
            return
        await self.db.reset_guild_customize(ctx.guild.id)
        warnings = await self._reset_server_profile(ctx)
        if warnings:
            return await ctx.warn(
                "reset all **server** customizations, but "
                + "; ".join(warnings)
            )
        return await ctx.success("reset all **server** customizations")

    @customize.command(
        name="name",
        aliases=["nick", "nickname"],
        description="Change the bot's nickname in the server",
        example=",customize name Vain",
    )
    async def customize_name(self, ctx, *, name: str = None):
        """change bot nickname"""
        if not await self._require_server_owner(ctx):
            return
        try:
            await ctx.guild.me.edit(
                nick=name,
                reason=f"nickname changed by {ctx.author}",
            )
            if name:
                await ctx.success(f"changed my name to **{name}**")
            else:
                await ctx.success("reset my server name")
        except discord.Forbidden:
            await ctx.warn("i **don't** have permission to change my **nickname**")
        except discord.HTTPException as e:
            await ctx.fail(f"failed to change nickname: `{e.text}`")

    @customize.command(
        name="avatar",
        aliases=["pfp", "av"],
        description="Change or reset the bot's server avatar",
        example=",customize avatar https://vain.bot/avatar.png",
    )
    async def customize_avatar(self, ctx, source: str = None):
        """change bot server avatar"""
        if not await self._require_server_owner(ctx):
            return
        try:
            me = ctx.guild.me
            if source and source.lower() in CLEAR_WORDS:
                await me.edit(avatar=None)
                return await ctx.success("reset my server avatar")

            data = await self._read_image_bytes(ctx, source)
            if data is None:
                if not source and not ctx.message.attachments:
                    await ctx.warn("provide an image url or attachment")
                return

            await me.edit(avatar=data)
            return await ctx.success("updated my **server avatar**")
        except discord.Forbidden:
            await ctx.warn("i **don't** have permission to change my server avatar")
        except discord.HTTPException as e:
            await ctx.fail(f"failed to update server avatar: `{e.text}`")

    @customize.command(
        name="banner",
        description="Change or reset the bot's server banner",
        example=",customize banner https://vain.bot/banner.png",
    )
    async def customize_banner(self, ctx, source: str = None):
        """change bot server banner"""
        if not await self._require_server_owner(ctx):
            return
        async with ctx.typing():
            try:
                me = ctx.guild.me
                if source and source.lower() in CLEAR_WORDS:
                    await me.edit(banner=None)
                    return await ctx.success("reset my server banner")

                data = await self._read_image_bytes(ctx, source)
                if data is None:
                    if not source and not ctx.message.attachments:
                        await ctx.warn("provide an image url or attachment")
                    return

                await me.edit(banner=data)
                return await ctx.success("updated my **server banner**")
            except discord.Forbidden:
                await ctx.warn("i lack permission to change my banner (may need more boosts)")
            except discord.HTTPException as e:
                await ctx.fail(f"failed to update server banner: `{e.text}`")

    @customize.command(
        name="bio",
        description="Change or reset the bot's server bio",
        example=",customize bio Vain is a really cool bot",
    )
    async def customize_bio(self, ctx, *, bio: str = None):
        """change bot server bio"""
        if not await self._require_server_owner(ctx):
            return
        try:
            me = ctx.guild.me
            if not bio:
                return await ctx.warn("provide a bio or say `none` to clear it")
            if bio.lower() in CLEAR_WORDS:
                await me.edit(bio=None)
                return await ctx.success("reset my bio")

            normalized = self._normalized_bio(bio)
            if len(normalized) > BIO_MAX_LENGTH:
                return await ctx.warn(
                    f"bio must stay under **{BIO_MAX_LENGTH}** characters after the Vain link is appended"
                )

            await me.edit(bio=normalized)
            e = Embed(
                color=self.color,
                description=f"{ctx.author.mention}: updated my bio: `{bio}`",
            )
            await ctx.reply(embed=e)
        except discord.HTTPException as e:
            await ctx.fail(f"failed to update bio: `{e.text}`")

    @customize.group(
        name="emoji",
        usage="(subcommand) <args>",
        example="warn :new_emoji:",
        invoke_without_command=True,
    )
    async def customize_emoji(self, ctx):
        """Customize server embed emojis."""
        if not await self._require_server_owner(ctx):
            return
        await ctx.send_help(ctx.command)

    @customize_emoji.command(
        name="list",
        aliases=["view"],
        example="",
    )
    async def customize_emoji_list(self, ctx):
        """View all customizable emoji slots."""
        settings = await self.db.get_guild_customize(ctx.guild.id)
        current = settings.get("emoji", {})

        default_emoji = {
            "success": "<:approve:1525918671774679261>",
            "warn": "<:warn:1525918556435255336>",
            "deny": "<:deny:1525918867115741215>",
            "cooldown": "<:cooldown:1525919040776835075>",
            "loading": "<a:embeds_loading:1511705994823077988>",
            "info": "<:interface_information:1511705999550185646>",
        }

        lines = []
        for key, default in default_emoji.items():
            custom = current.get(key, default)
            lines.append(f"**{key}**: {custom}")

        embed = Embed(
            title="Server Emoji Settings",
            description="\n".join(lines),
            color=self.color,
        )
        embed.set_footer(text=f"Use {ctx.clean_prefix}customize emoji <key> <emoji> to change")
        await ctx.send(embed=embed)

    @customize_emoji.command(
        name="success",
        description="Set the success/approve emoji",
        example=":white_check_mark:",
    )
    async def customize_emoji_success(self, ctx, emoji: str = None):
        """Set the success emoji."""
        if not await self._require_server_owner(ctx):
            return
        if not emoji or emoji.lower() in CLEAR_WORDS:
            settings = await self.db.get_guild_customize(ctx.guild.id)
            emoji_dict = settings.get("emoji", {})
            emoji_dict.pop("success", None)
            await self.db.set_guild_customize(ctx.guild.id, "emoji", emoji_dict)
            return await ctx.success("reset **success** emoji to default")

        settings = await self.db.get_guild_customize(ctx.guild.id)
        emoji_dict = settings.get("emoji", {})
        emoji_dict["success"] = emoji
        await self.db.set_guild_customize(ctx.guild.id, "emoji", emoji_dict)
        return await ctx.success(f"set **success** emoji to {emoji}")

    @customize_emoji.command(
        name="warn",
        description="Set the warning emoji",
        example=":warning:",
    )
    async def customize_emoji_warn(self, ctx, emoji: str = None):
        """Set the warn emoji."""
        if not await self._require_server_owner(ctx):
            return
        if not emoji or emoji.lower() in CLEAR_WORDS:
            settings = await self.db.get_guild_customize(ctx.guild.id)
            emoji_dict = settings.get("emoji", {})
            emoji_dict.pop("warn", None)
            await self.db.set_guild_customize(ctx.guild.id, "emoji", emoji_dict)
            return await ctx.success("reset **warn** emoji to default")

        settings = await self.db.get_guild_customize(ctx.guild.id)
        emoji_dict = settings.get("emoji", {})
        emoji_dict["warn"] = emoji
        await self.db.set_guild_customize(ctx.guild.id, "emoji", emoji_dict)
        return await ctx.success(f"set **warn** emoji to {emoji}")

    @customize_emoji.command(
        name="deny",
        aliases=["error"],
        description="Set the deny/error emoji",
        example=":x:",
    )
    async def customize_emoji_deny(self, ctx, emoji: str = None):
        """Set the deny emoji."""
        if not await self._require_server_owner(ctx):
            return
        if not emoji or emoji.lower() in CLEAR_WORDS:
            settings = await self.db.get_guild_customize(ctx.guild.id)
            emoji_dict = settings.get("emoji", {})
            emoji_dict.pop("deny", None)
            await self.db.set_guild_customize(ctx.guild.id, "emoji", emoji_dict)
            return await ctx.success("reset **deny** emoji to default")

        settings = await self.db.get_guild_customize(ctx.guild.id)
        emoji_dict = settings.get("emoji", {})
        emoji_dict["deny"] = emoji
        await self.db.set_guild_customize(ctx.guild.id, "emoji", emoji_dict)
        return await ctx.success(f"set **deny** emoji to {emoji}")

    @customize_emoji.command(
        name="cooldown",
        description="Set the cooldown emoji",
        example=":clock1:",
    )
    async def customize_emoji_cooldown(self, ctx, emoji: str = None):
        """Set the cooldown emoji."""
        if not await self._require_server_owner(ctx):
            return
        if not emoji or emoji.lower() in CLEAR_WORDS:
            settings = await self.db.get_guild_customize(ctx.guild.id)
            emoji_dict = settings.get("emoji", {})
            emoji_dict.pop("cooldown", None)
            await self.db.set_guild_customize(ctx.guild.id, "emoji", emoji_dict)
            return await ctx.success("reset **cooldown** emoji to default")

        settings = await self.db.get_guild_customize(ctx.guild.id)
        emoji_dict = settings.get("emoji", {})
        emoji_dict["cooldown"] = emoji
        await self.db.set_guild_customize(ctx.guild.id, "emoji", emoji_dict)
        return await ctx.success(f"set **cooldown** emoji to {emoji}")

    @customize_emoji.command(
        name="loading",
        description="Set the loading emoji",
        example=":loading:",
    )
    async def customize_emoji_loading(self, ctx, emoji: str = None):
        """Set the loading emoji."""
        if not await self._require_server_owner(ctx):
            return
        if not emoji or emoji.lower() in CLEAR_WORDS:
            settings = await self.db.get_guild_customize(ctx.guild.id)
            emoji_dict = settings.get("emoji", {})
            emoji_dict.pop("loading", None)
            await self.db.set_guild_customize(ctx.guild.id, "emoji", emoji_dict)
            return await ctx.success("reset **loading** emoji to default")

        settings = await self.db.get_guild_customize(ctx.guild.id)
        emoji_dict = settings.get("emoji", {})
        emoji_dict["loading"] = emoji
        await self.db.set_guild_customize(ctx.guild.id, "emoji", emoji_dict)
        return await ctx.success(f"set **loading** emoji to {emoji}")

    @customize_emoji.command(
        name="info",
        aliases=["information"],
        description="Set the info emoji",
        example=":information_source:",
    )
    async def customize_emoji_info(self, ctx, emoji: str = None):
        """Set the info emoji."""
        if not await self._require_server_owner(ctx):
            return
        if not emoji or emoji.lower() in CLEAR_WORDS:
            settings = await self.db.get_guild_customize(ctx.guild.id)
            emoji_dict = settings.get("emoji", {})
            emoji_dict.pop("info", None)
            await self.db.set_guild_customize(ctx.guild.id, "emoji", emoji_dict)
            return await ctx.success("reset **info** emoji to default")

        settings = await self.db.get_guild_customize(ctx.guild.id)
        emoji_dict = settings.get("emoji", {})
        emoji_dict["info"] = emoji
        await self.db.set_guild_customize(ctx.guild.id, "emoji", emoji_dict)
        return await ctx.success(f"set **info** emoji to {emoji}")

    @customize_emoji.group(
        name="voicemaster",
        aliases=["vm"],
        usage="(subcommand) <args>",
        example="lock :lock_emoji:",
        invoke_without_command=True,
    )
    async def customize_emoji_vm(self, ctx):
        """Customize voicemaster emojis."""
        if not await self._require_server_owner(ctx):
            return
        await ctx.send_help(ctx.command)

    @customize_emoji_vm.command(
        name="list",
        aliases=["view"],
        example="",
    )
    async def customize_emoji_vm_list(self, ctx):
        """View all voicemaster emoji slots."""
        settings = await self.db.get_guild_customize(ctx.guild.id)
        current = settings.get("voicemaster_emoji", {})

        default_vm = {
            "lock": "<:interface_lock:1511706000007106721>",
            "unlock": "<:interface_unlock:1511706000690774097>",
            "ghost": "<:interface_ghost:1511705999264710756>",
            "reveal": "<:interface_reveal:1511706000405692449>",
            "claim": "<:interface_claim:1511705997897633954>",
            "disconnect": "<:interface_disconnect:1511705999264972800>",
            "activity": "<:interface_activity:1511705997889114273>",
            "increase": "<:interface_increase:1511705999348596767>",
            "decrease": "<:interface_decrease:1511705998434500719>",
        }

        lines = []
        for key, default in default_vm.items():
            custom = current.get(key, default)
            lines.append(f"**{key}**: {custom}")

        embed = Embed(
            title="Voicemaster Emoji Settings",
            description="\n".join(lines),
            color=self.color,
        )
        embed.set_footer(text=f"Use {ctx.clean_prefix}customize emoji vm <key> <emoji> to change")
        await ctx.send(embed=embed)

    @customize_emoji_vm.command(
        name="lock",
        description="Set the lock emoji",
        example=":lock:",
    )
    async def customize_emoji_vm_lock(self, ctx, emoji: str = None):
        """Set the lock emoji."""
        if not await self._require_server_owner(ctx):
            return
        if not emoji or emoji.lower() in CLEAR_WORDS:
            settings = await self.db.get_guild_customize(ctx.guild.id)
            vm_dict = settings.get("voicemaster_emoji", {})
            vm_dict.pop("lock", None)
            await self.db.set_guild_customize(ctx.guild.id, "voicemaster_emoji", vm_dict)
            return await ctx.success("reset **lock** emoji to default")

        settings = await self.db.get_guild_customize(ctx.guild.id)
        vm_dict = settings.get("voicemaster_emoji", {})
        vm_dict["lock"] = emoji
        await self.db.set_guild_customize(ctx.guild.id, "voicemaster_emoji", vm_dict)
        return await ctx.success(f"set **lock** emoji to {emoji}")

    @customize_emoji_vm.command(
        name="unlock",
        description="Set the unlock emoji",
        example=":unlock:",
    )
    async def customize_emoji_vm_unlock(self, ctx, emoji: str = None):
        """Set the unlock emoji."""
        if not await self._require_server_owner(ctx):
            return
        if not emoji or emoji.lower() in CLEAR_WORDS:
            settings = await self.db.get_guild_customize(ctx.guild.id)
            vm_dict = settings.get("voicemaster_emoji", {})
            vm_dict.pop("unlock", None)
            await self.db.set_guild_customize(ctx.guild.id, "voicemaster_emoji", vm_dict)
            return await ctx.success("reset **unlock** emoji to default")

        settings = await self.db.get_guild_customize(ctx.guild.id)
        vm_dict = settings.get("voicemaster_emoji", {})
        vm_dict["unlock"] = emoji
        await self.db.set_guild_customize(ctx.guild.id, "voicemaster_emoji", vm_dict)
        return await ctx.success(f"set **unlock** emoji to {emoji}")

    @customize_emoji_vm.command(
        name="ghost",
        description="Set the ghost emoji",
        example=":ghost:",
    )
    async def customize_emoji_vm_ghost(self, ctx, emoji: str = None):
        """Set the ghost emoji."""
        if not await self._require_server_owner(ctx):
            return
        if not emoji or emoji.lower() in CLEAR_WORDS:
            settings = await self.db.get_guild_customize(ctx.guild.id)
            vm_dict = settings.get("voicemaster_emoji", {})
            vm_dict.pop("ghost", None)
            await self.db.set_guild_customize(ctx.guild.id, "voicemaster_emoji", vm_dict)
            return await ctx.success("reset **ghost** emoji to default")

        settings = await self.db.get_guild_customize(ctx.guild.id)
        vm_dict = settings.get("voicemaster_emoji", {})
        vm_dict["ghost"] = emoji
        await self.db.set_guild_customize(ctx.guild.id, "voicemaster_emoji", vm_dict)
        return await ctx.success(f"set **ghost** emoji to {emoji}")

    @customize_emoji_vm.command(
        name="reveal",
        description="Set the reveal emoji",
        example=":eyes:",
    )
    async def customize_emoji_vm_reveal(self, ctx, emoji: str = None):
        """Set the reveal emoji."""
        if not await self._require_server_owner(ctx):
            return
        if not emoji or emoji.lower() in CLEAR_WORDS:
            settings = await self.db.get_guild_customize(ctx.guild.id)
            vm_dict = settings.get("voicemaster_emoji", {})
            vm_dict.pop("reveal", None)
            await self.db.set_guild_customize(ctx.guild.id, "voicemaster_emoji", vm_dict)
            return await ctx.success("reset **reveal** emoji to default")

        settings = await self.db.get_guild_customize(ctx.guild.id)
        vm_dict = settings.get("voicemaster_emoji", {})
        vm_dict["reveal"] = emoji
        await self.db.set_guild_customize(ctx.guild.id, "voicemaster_emoji", vm_dict)
        return await ctx.success(f"set **reveal** emoji to {emoji}")

    @customize_emoji_vm.command(
        name="claim",
        description="Set the claim emoji",
        example=":hand:",
    )
    async def customize_emoji_vm_claim(self, ctx, emoji: str = None):
        """Set the claim emoji."""
        if not await self._require_server_owner(ctx):
            return
        if not emoji or emoji.lower() in CLEAR_WORDS:
            settings = await self.db.get_guild_customize(ctx.guild.id)
            vm_dict = settings.get("voicemaster_emoji", {})
            vm_dict.pop("claim", None)
            await self.db.set_guild_customize(ctx.guild.id, "voicemaster_emoji", vm_dict)
            return await ctx.success("reset **claim** emoji to default")

        settings = await self.db.get_guild_customize(ctx.guild.id)
        vm_dict = settings.get("voicemaster_emoji", {})
        vm_dict["claim"] = emoji
        await self.db.set_guild_customize(ctx.guild.id, "voicemaster_emoji", vm_dict)
        return await ctx.success(f"set **claim** emoji to {emoji}")

    @customize_emoji_vm.command(
        name="disconnect",
        aliases=["dc"],
        description="Set the disconnect emoji",
        example=": telephone_receiver:",
    )
    async def customize_emoji_vm_disconnect(self, ctx, emoji: str = None):
        """Set the disconnect emoji."""
        if not await self._require_server_owner(ctx):
            return
        if not emoji or emoji.lower() in CLEAR_WORDS:
            settings = await self.db.get_guild_customize(ctx.guild.id)
            vm_dict = settings.get("voicemaster_emoji", {})
            vm_dict.pop("disconnect", None)
            await self.db.set_guild_customize(ctx.guild.id, "voicemaster_emoji", vm_dict)
            return await ctx.success("reset **disconnect** emoji to default")

        settings = await self.db.get_guild_customize(ctx.guild.id)
        vm_dict = settings.get("voicemaster_emoji", {})
        vm_dict["disconnect"] = emoji
        await self.db.set_guild_customize(ctx.guild.id, "voicemaster_emoji", vm_dict)
        return await ctx.success(f"set **disconnect** emoji to {emoji}")

    @customize_emoji_vm.command(
        name="activity",
        description="Set the activity emoji",
        example=":game_die:",
    )
    async def customize_emoji_vm_activity(self, ctx, emoji: str = None):
        """Set the activity emoji."""
        if not await self._require_server_owner(ctx):
            return
        if not emoji or emoji.lower() in CLEAR_WORDS:
            settings = await self.db.get_guild_customize(ctx.guild.id)
            vm_dict = settings.get("voicemaster_emoji", {})
            vm_dict.pop("activity", None)
            await self.db.set_guild_customize(ctx.guild.id, "voicemaster_emoji", vm_dict)
            return await ctx.success("reset **activity** emoji to default")

        settings = await self.db.get_guild_customize(ctx.guild.id)
        vm_dict = settings.get("voicemaster_emoji", {})
        vm_dict["activity"] = emoji
        await self.db.set_guild_customize(ctx.guild.id, "voicemaster_emoji", vm_dict)
        return await ctx.success(f"set **activity** emoji to {emoji}")

    @customize_emoji_vm.command(
        name="increase",
        description="Set the increase emoji",
        example=":arrow_up:",
    )
    async def customize_emoji_vm_increase(self, ctx, emoji: str = None):
        """Set the increase emoji."""
        if not await self._require_server_owner(ctx):
            return
        if not emoji or emoji.lower() in CLEAR_WORDS:
            settings = await self.db.get_guild_customize(ctx.guild.id)
            vm_dict = settings.get("voicemaster_emoji", {})
            vm_dict.pop("increase", None)
            await self.db.set_guild_customize(ctx.guild.id, "voicemaster_emoji", vm_dict)
            return await ctx.success("reset **increase** emoji to default")

        settings = await self.db.get_guild_customize(ctx.guild.id)
        vm_dict = settings.get("voicemaster_emoji", {})
        vm_dict["increase"] = emoji
        await self.db.set_guild_customize(ctx.guild.id, "voicemaster_emoji", vm_dict)
        return await ctx.success(f"set **increase** emoji to {emoji}")

    @customize_emoji_vm.command(
        name="decrease",
        description="Set the decrease emoji",
        example=":arrow_down:",
    )
    async def customize_emoji_vm_decrease(self, ctx, emoji: str = None):
        """Set the decrease emoji."""
        if not await self._require_server_owner(ctx):
            return
        if not emoji or emoji.lower() in CLEAR_WORDS:
            settings = await self.db.get_guild_customize(ctx.guild.id)
            vm_dict = settings.get("voicemaster_emoji", {})
            vm_dict.pop("decrease", None)
            await self.db.set_guild_customize(ctx.guild.id, "voicemaster_emoji", vm_dict)
            return await ctx.success("reset **decrease** emoji to default")

        settings = await self.db.get_guild_customize(ctx.guild.id)
        vm_dict = settings.get("voicemaster_emoji", {})
        vm_dict["decrease"] = emoji
        await self.db.set_guild_customize(ctx.guild.id, "voicemaster_emoji", vm_dict)
        return await ctx.success(f"set **decrease** emoji to {emoji}")

    
    
    
    

    COLOR_KEYS = (
        "base",
        "approve",
        "warn",
        "deny",
        "cooldown",
        "settings",
        "dark",
        "information",
        "shazam",
    )
    EMOJI_KEYS = (
        "success",
        "warn",
        "deny",
        "cooldown",
        "loading",
        "info",
        "shazam",
    )

    @group(
        name="context",
        aliases=["ctx"],
        description="Server or personal embed color/emoji customization",
        example=",context color base #2A2B2F",
        invoke_without_command=True,
    )
    @has_permissions(manage_guild=True)
    async def context(self, ctx):
        """Server context settings. Use `context self` for personal."""
        await ctx.send_help(ctx.command)

    
    @context.group(
        name="self",
        aliases=["me", "personal"],
        description="Personal per-user embed customization",
        example=",context self color base #2A2B2F",
        invoke_without_command=True,
    )
    async def context_self(self, ctx):
        """Personal colors/emojis for your responses."""
        await ctx.send_help(ctx.command)

    async def _personal_set_color(self, ctx, key: str, hex_code: str | None, nice: str):
        gid = getattr(ctx.guild, "id", 0) if ctx.guild else 0
        if not hex_code or str(hex_code).lower() in CLEAR_WORDS:
            s = await self.db.get_user_customize(ctx.author.id, gid)
            c = s.get("color", {})
            c.pop(key, None)
            await self.db.set_user_customize(ctx.author.id, gid, "color", c)
            return await ctx.success(f"reset your **{nice}** color to default")
        h = str(hex_code).lstrip("#")
        try:
            int(h, 16)
        except Exception:
            return await ctx.warn("provide a valid hex (e.g. `#2A2B2F`)")
        s = await self.db.get_user_customize(ctx.author.id, gid)
        c = s.get("color", {})
        c[key] = h
        await self.db.set_user_customize(ctx.author.id, gid, "color", c)
        return await ctx.success(f"set your **{nice}** color to `#{h}`")

    async def _personal_set_emoji(self, ctx, key: str, emoji: str | None, nice: str):
        gid = getattr(ctx.guild, "id", 0) if ctx.guild else 0
        if not emoji or str(emoji).lower() in CLEAR_WORDS:
            s = await self.db.get_user_customize(ctx.author.id, gid)
            e = s.get("emoji", {})
            e.pop(key, None)
            await self.db.set_user_customize(ctx.author.id, gid, "emoji", e)
            return await ctx.success(f"reset your **{nice}** emoji to default")
        s = await self.db.get_user_customize(ctx.author.id, gid)
        e = s.get("emoji", {})
        e[key] = emoji
        await self.db.set_user_customize(ctx.author.id, gid, "emoji", e)
        return await ctx.success(f"set your **{nice}** emoji to {emoji}")

    async def _guild_set_color(self, ctx, key: str, hex_code: str | None, nice: str):
        if not hex_code or str(hex_code).lower() in CLEAR_WORDS:
            s = await self.db.get_guild_customize(ctx.guild.id)
            c = s.get("color", {})
            c.pop(key, None)
            await self.db.set_guild_customize(ctx.guild.id, "color", c)
            return await ctx.success(f"reset server **{nice}** color to default")
        h = str(hex_code).lstrip("#")
        try:
            int(h, 16)
        except Exception:
            return await ctx.warn("provide a valid hex (e.g. `#2A2B2F`)")
        s = await self.db.get_guild_customize(ctx.guild.id)
        c = s.get("color", {})
        c[key] = h
        await self.db.set_guild_customize(ctx.guild.id, "color", c)
        return await ctx.success(f"set server **{nice}** color to `#{h}`")

    async def _guild_set_emoji(self, ctx, key: str, emoji: str | None, nice: str):
        if not emoji or str(emoji).lower() in CLEAR_WORDS:
            s = await self.db.get_guild_customize(ctx.guild.id)
            e = s.get("emoji", {})
            e.pop(key, None)
            await self.db.set_guild_customize(ctx.guild.id, "emoji", e)
            return await ctx.success(f"reset server **{nice}** emoji to default")
        s = await self.db.get_guild_customize(ctx.guild.id)
        e = s.get("emoji", {})
        e[key] = emoji
        await self.db.set_guild_customize(ctx.guild.id, "emoji", e)
        return await ctx.success(f"set server **{nice}** emoji to {emoji}")

    
    @context.group(
        name="color",
        aliases=["colour", "colors", "colours"],
        description="Server embed color customization",
        example=",context color base #2A2B2F",
        invoke_without_command=True,
    )
    @has_permissions(manage_guild=True)
    async def context_server_color(self, ctx):
        await ctx.send_help(ctx.command)

    @context_server_color.command(name="list", aliases=["view", "show"], description="List server colors", example=",context color list")
    @has_permissions(manage_guild=True)
    async def context_server_color_list(self, ctx):
        s = await self.db.get_guild_customize(ctx.guild.id)
        cur = s.get("color", {})
        lines = [f"**{k}**: `#{v}`" for k, v in cur.items()] or ["(none set)"]
        await ctx.send(embed=Embed(title="Server Colors", description="\n".join(lines), color=self.color), raw_embed=True)

    @context_server_color.command(name="base", description="Set server base embed color", example=",context color base #2A2B2F")
    @has_permissions(manage_guild=True)
    async def context_server_color_base(self, ctx, hex_code: str = None):
        return await self._guild_set_color(ctx, "base", hex_code, "base")

    @context_server_color.command(name="approve", aliases=["success"], description="Set server approve color", example=",context color approve #a8d8a8")
    @has_permissions(manage_guild=True)
    async def context_server_color_approve(self, ctx, hex_code: str = None):
        return await self._guild_set_color(ctx, "approve", hex_code, "approve")

    @context_server_color.command(name="warn", description="Set server warn color", example=",context color warn #f5d76e")
    @has_permissions(manage_guild=True)
    async def context_server_color_warn(self, ctx, hex_code: str = None):
        return await self._guild_set_color(ctx, "warn", hex_code, "warn")

    @context_server_color.command(name="deny", aliases=["fail", "error"], description="Set server deny color", example=",context color deny #e07a7a")
    @has_permissions(manage_guild=True)
    async def context_server_color_deny(self, ctx, hex_code: str = None):
        return await self._guild_set_color(ctx, "deny", hex_code, "deny")

    @context_server_color.command(name="cooldown", description="Set server cooldown color", example=",context color cooldown #bba0d2")
    @has_permissions(manage_guild=True)
    async def context_server_color_cooldown(self, ctx, hex_code: str = None):
        return await self._guild_set_color(ctx, "cooldown", hex_code, "cooldown")

    @context_server_color.command(name="settings", description="Set server settings color", example=",context color settings #d4b8d0")
    @has_permissions(manage_guild=True)
    async def context_server_color_settings(self, ctx, hex_code: str = None):
        return await self._guild_set_color(ctx, "settings", hex_code, "settings")

    @context_server_color.command(name="dark", description="Set server dark color", example=",context color dark #9b7a9e")
    @has_permissions(manage_guild=True)
    async def context_server_color_dark(self, ctx, hex_code: str = None):
        return await self._guild_set_color(ctx, "dark", hex_code, "dark")

    @context_server_color.command(name="information", aliases=["info"], description="Set server information color", example=",context color information #5865F2")
    @has_permissions(manage_guild=True)
    async def context_server_color_information(self, ctx, hex_code: str = None):
        return await self._guild_set_color(ctx, "information", hex_code, "information")

    @context_server_color.command(name="shazam", description="Set server shazam color", example=",context color shazam #c2a8d0")
    @has_permissions(manage_guild=True)
    async def context_server_color_shazam(self, ctx, hex_code: str = None):
        return await self._guild_set_color(ctx, "shazam", hex_code, "shazam")

    
    @context.group(
        name="emoji",
        aliases=["emojis"],
        description="Server embed emoji customization",
        example=",context emoji warn :warning:",
        invoke_without_command=True,
    )
    @has_permissions(manage_guild=True)
    async def context_server_emoji(self, ctx):
        await ctx.send_help(ctx.command)

    @context_server_emoji.command(name="list", aliases=["view", "show"], description="List server emojis", example=",context emoji list")
    @has_permissions(manage_guild=True)
    async def context_server_emoji_list(self, ctx):
        s = await self.db.get_guild_customize(ctx.guild.id)
        cur = s.get("emoji", {})
        lines = [f"**{k}**: {v}" for k, v in cur.items()] or ["(none set)"]
        await ctx.send(embed=Embed(title="Server Emojis", description="\n".join(lines), color=self.color), raw_embed=True)

    @context_server_emoji.command(name="success", aliases=["approve"], description="Set server success emoji", example=",context emoji success :white_check_mark:")
    @has_permissions(manage_guild=True)
    async def context_server_emoji_success(self, ctx, emoji: str = None):
        return await self._guild_set_emoji(ctx, "success", emoji, "success")

    @context_server_emoji.command(name="warn", description="Set server warn emoji", example=",context emoji warn :warning:")
    @has_permissions(manage_guild=True)
    async def context_server_emoji_warn(self, ctx, emoji: str = None):
        return await self._guild_set_emoji(ctx, "warn", emoji, "warn")

    @context_server_emoji.command(name="deny", aliases=["fail"], description="Set server deny emoji", example=",context emoji deny :x:")
    @has_permissions(manage_guild=True)
    async def context_server_emoji_deny(self, ctx, emoji: str = None):
        return await self._guild_set_emoji(ctx, "deny", emoji, "deny")

    @context_server_emoji.command(name="cooldown", description="Set server cooldown emoji", example=",context emoji cooldown :hourglass:")
    @has_permissions(manage_guild=True)
    async def context_server_emoji_cooldown(self, ctx, emoji: str = None):
        return await self._guild_set_emoji(ctx, "cooldown", emoji, "cooldown")

    @context_server_emoji.command(name="loading", description="Set server loading emoji", example=",context emoji loading :arrows_counterclockwise:")
    @has_permissions(manage_guild=True)
    async def context_server_emoji_loading(self, ctx, emoji: str = None):
        return await self._guild_set_emoji(ctx, "loading", emoji, "loading")

    @context_server_emoji.command(name="info", aliases=["information"], description="Set server info emoji", example=",context emoji info :information_source:")
    @has_permissions(manage_guild=True)
    async def context_server_emoji_info(self, ctx, emoji: str = None):
        return await self._guild_set_emoji(ctx, "info", emoji, "info")

    @context_server_emoji.command(name="shazam", description="Set server shazam emoji", example=",context emoji shazam :musical_note:")
    @has_permissions(manage_guild=True)
    async def context_server_emoji_shazam(self, ctx, emoji: str = None):
        return await self._guild_set_emoji(ctx, "shazam", emoji, "shazam")

    
    @context_self.group(
        name="color",
        aliases=["colour", "colors", "colours"],
        description="Personal embed color customization",
        example=",context self color base #2A2B2F",
        invoke_without_command=True,
    )
    async def context_self_color(self, ctx):
        await ctx.send_help(ctx.command)

    @context_self_color.command(name="list", aliases=["view", "show"], description="List your personal colors", example=",context self color list")
    async def cself_color_list(self, ctx):
        gid = getattr(ctx.guild, "id", 0) if ctx.guild else 0
        s = await self.db.get_user_customize(ctx.author.id, gid)
        cur = s.get("color", {})
        lines = [f"**{k}**: `#{v}`" for k, v in cur.items()] or ["(none set)"]
        await ctx.send(embed=Embed(title="Your Colors", description="\n".join(lines), color=self.color), raw_embed=True)

    @context_self_color.command(name="base", description="Set your personal base color", example=",context self color base #2A2B2F")
    async def cself_color_base(self, ctx, hex_code: str = None):
        return await self._personal_set_color(ctx, "base", hex_code, "base")

    @context_self_color.command(name="approve", aliases=["success"], description="Set your personal approve color", example=",context self color approve #a8d8a8")
    async def cself_color_approve(self, ctx, hex_code: str = None):
        return await self._personal_set_color(ctx, "approve", hex_code, "approve")

    @context_self_color.command(name="warn", description="Set your personal warn color", example=",context self color warn #f5d76e")
    async def cself_color_warn(self, ctx, hex_code: str = None):
        return await self._personal_set_color(ctx, "warn", hex_code, "warn")

    @context_self_color.command(name="deny", aliases=["fail"], description="Set your personal deny color", example=",context self color deny #e07a7a")
    async def cself_color_deny(self, ctx, hex_code: str = None):
        return await self._personal_set_color(ctx, "deny", hex_code, "deny")

    @context_self_color.command(name="cooldown", description="Set your personal cooldown color", example=",context self color cooldown #bba0d2")
    async def cself_color_cooldown(self, ctx, hex_code: str = None):
        return await self._personal_set_color(ctx, "cooldown", hex_code, "cooldown")

    @context_self_color.command(name="settings", description="Set your personal settings color", example=",context self color settings #d4b8d0")
    async def cself_color_settings(self, ctx, hex_code: str = None):
        return await self._personal_set_color(ctx, "settings", hex_code, "settings")

    @context_self_color.command(name="dark", description="Set your personal dark color", example=",context self color dark #9b7a9e")
    async def cself_color_dark(self, ctx, hex_code: str = None):
        return await self._personal_set_color(ctx, "dark", hex_code, "dark")

    @context_self_color.command(name="information", aliases=["info"], description="Set your personal information color", example=",context self color information #5865F2")
    async def cself_color_information(self, ctx, hex_code: str = None):
        return await self._personal_set_color(ctx, "information", hex_code, "information")

    @context_self_color.command(name="shazam", description="Set your personal shazam color", example=",context self color shazam #c2a8d0")
    async def cself_color_shazam(self, ctx, hex_code: str = None):
        return await self._personal_set_color(ctx, "shazam", hex_code, "shazam")

    
    @context_self.group(
        name="emoji",
        aliases=["emojis"],
        description="Personal embed emoji customization",
        example=",context self emoji warn :warning:",
        invoke_without_command=True,
    )
    async def context_self_emoji(self, ctx):
        await ctx.send_help(ctx.command)

    @context_self_emoji.command(name="list", aliases=["view", "show"], description="List your personal emojis", example=",context self emoji list")
    async def cself_emoji_list(self, ctx):
        gid = getattr(ctx.guild, "id", 0) if ctx.guild else 0
        s = await self.db.get_user_customize(ctx.author.id, gid)
        cur = s.get("emoji", {})
        lines = [f"**{k}**: {v}" for k, v in cur.items()] or ["(none set)"]
        await ctx.send(embed=Embed(title="Your Emojis", description="\n".join(lines), color=self.color), raw_embed=True)

    @context_self_emoji.command(name="success", aliases=["approve"], description="Set your personal success emoji", example=",context self emoji success :white_check_mark:")
    async def cself_emoji_success(self, ctx, emoji: str = None):
        return await self._personal_set_emoji(ctx, "success", emoji, "success")

    @context_self_emoji.command(name="warn", description="Set your personal warn emoji", example=",context self emoji warn :warning:")
    async def cself_emoji_warn(self, ctx, emoji: str = None):
        return await self._personal_set_emoji(ctx, "warn", emoji, "warn")

    @context_self_emoji.command(name="deny", aliases=["fail"], description="Set your personal deny emoji", example=",context self emoji deny :x:")
    async def cself_emoji_deny(self, ctx, emoji: str = None):
        return await self._personal_set_emoji(ctx, "deny", emoji, "deny")

    @context_self_emoji.command(name="cooldown", description="Set your personal cooldown emoji", example=",context self emoji cooldown :hourglass:")
    async def cself_emoji_cooldown(self, ctx, emoji: str = None):
        return await self._personal_set_emoji(ctx, "cooldown", emoji, "cooldown")

    @context_self_emoji.command(name="loading", description="Set your personal loading emoji", example=",context self emoji loading :arrows_counterclockwise:")
    async def cself_emoji_loading(self, ctx, emoji: str = None):
        return await self._personal_set_emoji(ctx, "loading", emoji, "loading")

    @context_self_emoji.command(name="info", aliases=["information"], description="Set your personal info emoji", example=",context self emoji info :information_source:")
    async def cself_emoji_info(self, ctx, emoji: str = None):
        return await self._personal_set_emoji(ctx, "info", emoji, "info")

    @context_self_emoji.command(name="shazam", description="Set your personal shazam emoji", example=",context self emoji shazam :musical_note:")
    async def cself_emoji_shazam(self, ctx, emoji: str = None):
        return await self._personal_set_emoji(ctx, "shazam", emoji, "shazam")

    @context_self.command(name="reset", description="Reset all your personal customizations", example=",context self reset")
    async def cself_reset(self, ctx):
        gid = getattr(ctx.guild, "id", 0) if ctx.guild else 0
        await self.db.reset_user_customize(ctx.author.id, gid)
        return await ctx.success("reset all your **personal** customizations")
