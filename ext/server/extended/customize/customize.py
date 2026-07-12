from __future__ import annotations

from urllib.parse import urlparse

import aiohttp
import discord
from discord import Embed
from discord.ext.commands import group

from core.discord.package import Package

BIO_LINKS = ("https://percs.cc/", "discord.gg/percsbio")
BIO_MAX_LENGTH = 190
CLEAR_WORDS = {"clear", "none", "off", "remove", "reset"}

VALID_EMOJI_KEYS = {"success", "warn", "deny", "cooldown", "loading", "info"}
VALID_COLOR_KEYS = {"base", "approve", "warn", "deny", "cooldown", "settings", "dark"}
VALID_VM_EMOJI_KEYS = {"lock", "unlock", "ghost", "reveal", "claim", "disconnect", "activity", "increase", "decrease"}


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
            bio = f"{bio}\nhttps://percs.cc/"
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
        example=",customize name bleed",
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
        example=",customize avatar https://percs.cc/avatar.png",
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
        example=",customize banner https://percs.cc/banner.png",
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
        example=",customize bio bleed is a really cool bot",
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
                    f"bio must stay under **{BIO_MAX_LENGTH}** characters after the bleed link is appended"
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
            "success": "<:embeds_approve:1511705992323272745>",
            "warn": "<:embeds_warn:1511705997918343168>",
            "deny": "<:embeds_deny:1511705993283633253>",
            "cooldown": "<:embeds_cooldown:1511705992755417129>",
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

    @customize.group(
        name="context",
        aliases=["self", "selfcontext"],
        usage="(subcommand) <args>",
        description="Customize your personal embed appearance",
        invoke_without_command=True,
    )
    async def customize_context(self, ctx):
        """Customize your personal embed appearance."""
        await ctx.send_help(ctx.command)

    @customize_context.command(
        name="reset",
        description="Reset all your personal customizations",
    )
    async def customize_context_reset(self, ctx):
        """Reset all your personal customizations."""
        await self.db.reset_user_customize(ctx.author.id, ctx.guild.id)
        return await ctx.success("reset all your **personal** customizations")

    @customize_context.group(
        name="emoji",
        usage="(subcommand) <args>",
        example="warn :new_emoji:",
        invoke_without_command=True,
    )
    async def customize_context_emoji(self, ctx):
        """Customize your personal embed emojis."""
        await ctx.send_help(ctx.command)

    @customize_context_emoji.command(
        name="list",
        aliases=["view"],
        example="",
    )
    async def customize_context_emoji_list(self, ctx):
        """View your personal emoji settings."""
        settings = await self.db.get_user_customize(ctx.author.id, ctx.guild.id)
        current = settings.get("emoji", {})

        if not current:
            return await ctx.warn("You have no **custom emojis** set. Use the default server emojis.")

        lines = [f"**{key}**: {value}" for key, value in current.items()]
        embed = Embed(
            title="Your Emoji Settings",
            description="\n".join(lines),
            color=self.color,
        )
        embed.set_footer(text=f"Use {ctx.clean_prefix}customize context emoji <key> <emoji> to change")
        await ctx.send(embed=embed)

    @customize_context_emoji.command(
        name="success",
        description="Set your personal success emoji",
        example=":white_check_mark:",
    )
    async def customize_context_emoji_success(self, ctx, emoji: str = None):
        """Set your personal success emoji."""
        if not emoji or emoji.lower() in CLEAR_WORDS:
            settings = await self.db.get_user_customize(ctx.author.id, ctx.guild.id)
            emoji_dict = settings.get("emoji", {})
            emoji_dict.pop("success", None)
            await self.db.set_user_customize(ctx.author.id, ctx.guild.id, "emoji", emoji_dict)
            return await ctx.success("reset your **success** emoji to default")

        settings = await self.db.get_user_customize(ctx.author.id, ctx.guild.id)
        emoji_dict = settings.get("emoji", {})
        emoji_dict["success"] = emoji
        await self.db.set_user_customize(ctx.author.id, ctx.guild.id, "emoji", emoji_dict)
        return await ctx.success(f"set your **success** emoji to {emoji}")

    @customize_context_emoji.command(
        name="warn",
        description="Set your personal warning emoji",
        example=":warning:",
    )
    async def customize_context_emoji_warn(self, ctx, emoji: str = None):
        """Set your personal warn emoji."""
        if not emoji or emoji.lower() in CLEAR_WORDS:
            settings = await self.db.get_user_customize(ctx.author.id, ctx.guild.id)
            emoji_dict = settings.get("emoji", {})
            emoji_dict.pop("warn", None)
            await self.db.set_user_customize(ctx.author.id, ctx.guild.id, "emoji", emoji_dict)
            return await ctx.success("reset your **warn** emoji to default")

        settings = await self.db.get_user_customize(ctx.author.id, ctx.guild.id)
        emoji_dict = settings.get("emoji", {})
        emoji_dict["warn"] = emoji
        await self.db.set_user_customize(ctx.author.id, ctx.guild.id, "emoji", emoji_dict)
        return await ctx.success(f"set your **warn** emoji to {emoji}")

    @customize_context_emoji.command(
        name="deny",
        aliases=["error"],
        description="Set your personal deny/error emoji",
        example=":x:",
    )
    async def customize_context_emoji_deny(self, ctx, emoji: str = None):
        """Set your personal deny emoji."""
        if not emoji or emoji.lower() in CLEAR_WORDS:
            settings = await self.db.get_user_customize(ctx.author.id, ctx.guild.id)
            emoji_dict = settings.get("emoji", {})
            emoji_dict.pop("deny", None)
            await self.db.set_user_customize(ctx.author.id, ctx.guild.id, "emoji", emoji_dict)
            return await ctx.success("reset your **deny** emoji to default")

        settings = await self.db.get_user_customize(ctx.author.id, ctx.guild.id)
        emoji_dict = settings.get("emoji", {})
        emoji_dict["deny"] = emoji
        await self.db.set_user_customize(ctx.author.id, ctx.guild.id, "emoji", emoji_dict)
        return await ctx.success(f"set your **deny** emoji to {emoji}")

    @customize_context_emoji.command(
        name="cooldown",
        description="Set your personal cooldown emoji",
        example=":clock1:",
    )
    async def customize_context_emoji_cooldown(self, ctx, emoji: str = None):
        """Set your personal cooldown emoji."""
        if not emoji or emoji.lower() in CLEAR_WORDS:
            settings = await self.db.get_user_customize(ctx.author.id, ctx.guild.id)
            emoji_dict = settings.get("emoji", {})
            emoji_dict.pop("cooldown", None)
            await self.db.set_user_customize(ctx.author.id, ctx.guild.id, "emoji", emoji_dict)
            return await ctx.success("reset your **cooldown** emoji to default")

        settings = await self.db.get_user_customize(ctx.author.id, ctx.guild.id)
        emoji_dict = settings.get("emoji", {})
        emoji_dict["cooldown"] = emoji
        await self.db.set_user_customize(ctx.author.id, ctx.guild.id, "emoji", emoji_dict)
        return await ctx.success(f"set your **cooldown** emoji to {emoji}")

    @customize.group(
        name="color",
        usage="(subcommand) <args>",
        example="warn FF0000",
        invoke_without_command=True,
    )
    async def customize_color(self, ctx):
        """Customize server embed colors."""
        if not await self._require_server_owner(ctx):
            return
        await ctx.send_help(ctx.command)

    @customize_color.command(
        name="list",
        aliases=["view"],
        example="",
    )
    async def customize_color_list(self, ctx):
        """View all customizable color slots."""
        settings = await self.db.get_guild_customize(ctx.guild.id)
        current = settings.get("color", {})

        default_color = {
            "base": "373737",
            "approve": "A8EA7B",
            "warn": "FDCF39",
            "deny": "FF0000",
            "cooldown": "4EC3E8",
            "settings": "7289DA",
            "dark": "2B2D31",
        }

        lines = []
        for key, default in default_color.items():
            custom = current.get(key, default)
            lines.append(f"**{key}**: `#{custom}`")

        embed = Embed(
            title="Server Color Settings",
            description="\n".join(lines),
            color=self.color,
        )
        embed.set_footer(text=f"Use {ctx.clean_prefix}customize color <key> <hex> to change")
        await ctx.send(embed=embed)

    @customize_color.command(
        name="base",
        description="Set the base embed color",
        example="373737",
    )
    async def customize_color_base(self, ctx, hex_code: str = None):
        """Set the base embed color."""
        if not await self._require_server_owner(ctx):
            return
        if not hex_code or hex_code.lower() in CLEAR_WORDS:
            settings = await self.db.get_guild_customize(ctx.guild.id)
            color_dict = settings.get("color", {})
            color_dict.pop("base", None)
            await self.db.set_guild_customize(ctx.guild.id, "color", color_dict)
            return await ctx.success("reset **base** color to default")

        hex_code = hex_code.lstrip("#")
        try:
            int(hex_code, 16)
        except ValueError:
            return await ctx.warn("provide a valid hex color code (e.g., `FF0000`)")

        settings = await self.db.get_guild_customize(ctx.guild.id)
        color_dict = settings.get("color", {})
        color_dict["base"] = hex_code
        await self.db.set_guild_customize(ctx.guild.id, "color", color_dict)
        return await ctx.success(f"set **base** color to `#{hex_code}`")

    @customize_color.command(
        name="approve",
        aliases=["success"],
        description="Set the approve/success color",
        example="A8EA7B",
    )
    async def customize_color_approve(self, ctx, hex_code: str = None):
        """Set the approve color."""
        if not await self._require_server_owner(ctx):
            return
        if not hex_code or hex_code.lower() in CLEAR_WORDS:
            settings = await self.db.get_guild_customize(ctx.guild.id)
            color_dict = settings.get("color", {})
            color_dict.pop("approve", None)
            await self.db.set_guild_customize(ctx.guild.id, "color", color_dict)
            return await ctx.success("reset **approve** color to default")

        hex_code = hex_code.lstrip("#")
        try:
            int(hex_code, 16)
        except ValueError:
            return await ctx.warn("provide a valid hex color code (e.g., `A8EA7B`)")

        settings = await self.db.get_guild_customize(ctx.guild.id)
        color_dict = settings.get("color", {})
        color_dict["approve"] = hex_code
        await self.db.set_guild_customize(ctx.guild.id, "color", color_dict)
        return await ctx.success(f"set **approve** color to `#{hex_code}`")

    @customize_color.command(
        name="warn",
        description="Set the warning color",
        example="FDCF39",
    )
    async def customize_color_warn(self, ctx, hex_code: str = None):
        """Set the warn color."""
        if not await self._require_server_owner(ctx):
            return
        if not hex_code or hex_code.lower() in CLEAR_WORDS:
            settings = await self.db.get_guild_customize(ctx.guild.id)
            color_dict = settings.get("color", {})
            color_dict.pop("warn", None)
            await self.db.set_guild_customize(ctx.guild.id, "color", color_dict)
            return await ctx.success("reset **warn** color to default")

        hex_code = hex_code.lstrip("#")
        try:
            int(hex_code, 16)
        except ValueError:
            return await ctx.warn("provide a valid hex color code (e.g., `FDCF39`)")

        settings = await self.db.get_guild_customize(ctx.guild.id)
        color_dict = settings.get("color", {})
        color_dict["warn"] = hex_code
        await self.db.set_guild_customize(ctx.guild.id, "color", color_dict)
        return await ctx.success(f"set **warn** color to `#{hex_code}`")

    @customize_color.command(
        name="deny",
        aliases=["error"],
        description="Set the deny/error color",
        example="FF0000",
    )
    async def customize_color_deny(self, ctx, hex_code: str = None):
        """Set the deny color."""
        if not await self._require_server_owner(ctx):
            return
        if not hex_code or hex_code.lower() in CLEAR_WORDS:
            settings = await self.db.get_guild_customize(ctx.guild.id)
            color_dict = settings.get("color", {})
            color_dict.pop("deny", None)
            await self.db.set_guild_customize(ctx.guild.id, "color", color_dict)
            return await ctx.success("reset **deny** color to default")

        hex_code = hex_code.lstrip("#")
        try:
            int(hex_code, 16)
        except ValueError:
            return await ctx.warn("provide a valid hex color code (e.g., `FF0000`)")

        settings = await self.db.get_guild_customize(ctx.guild.id)
        color_dict = settings.get("color", {})
        color_dict["deny"] = hex_code
        await self.db.set_guild_customize(ctx.guild.id, "color", color_dict)
        return await ctx.success(f"set **deny** color to `#{hex_code}`")

    @customize_color.command(
        name="cooldown",
        description="Set the cooldown color",
        example="4EC3E8",
    )
    async def customize_color_cooldown(self, ctx, hex_code: str = None):
        """Set the cooldown color."""
        if not await self._require_server_owner(ctx):
            return
        if not hex_code or hex_code.lower() in CLEAR_WORDS:
            settings = await self.db.get_guild_customize(ctx.guild.id)
            color_dict = settings.get("color", {})
            color_dict.pop("cooldown", None)
            await self.db.set_guild_customize(ctx.guild.id, "color", color_dict)
            return await ctx.success("reset **cooldown** color to default")

        hex_code = hex_code.lstrip("#")
        try:
            int(hex_code, 16)
        except ValueError:
            return await ctx.warn("provide a valid hex color code (e.g., `4EC3E8`)")

        settings = await self.db.get_guild_customize(ctx.guild.id)
        color_dict = settings.get("color", {})
        color_dict["cooldown"] = hex_code
        await self.db.set_guild_customize(ctx.guild.id, "color", color_dict)
        return await ctx.success(f"set **cooldown** color to `#{hex_code}`")

    @customize_color.command(
        name="settings",
        description="Set the settings color",
        example="7289DA",
    )
    async def customize_color_settings(self, ctx, hex_code: str = None):
        """Set the settings color."""
        if not await self._require_server_owner(ctx):
            return
        if not hex_code or hex_code.lower() in CLEAR_WORDS:
            settings = await self.db.get_guild_customize(ctx.guild.id)
            color_dict = settings.get("color", {})
            color_dict.pop("settings", None)
            await self.db.set_guild_customize(ctx.guild.id, "color", color_dict)
            return await ctx.success("reset **settings** color to default")

        hex_code = hex_code.lstrip("#")
        try:
            int(hex_code, 16)
        except ValueError:
            return await ctx.warn("provide a valid hex color code (e.g., `7289DA`)")

        settings = await self.db.get_guild_customize(ctx.guild.id)
        color_dict = settings.get("color", {})
        color_dict["settings"] = hex_code
        await self.db.set_guild_customize(ctx.guild.id, "color", color_dict)
        return await ctx.success(f"set **settings** color to `#{hex_code}`")

    @customize_color.command(
        name="dark",
        description="Set the dark embed color",
        example="2B2D31",
    )
    async def customize_color_dark(self, ctx, hex_code: str = None):
        """Set the dark color."""
        if not await self._require_server_owner(ctx):
            return
        if not hex_code or hex_code.lower() in CLEAR_WORDS:
            settings = await self.db.get_guild_customize(ctx.guild.id)
            color_dict = settings.get("color", {})
            color_dict.pop("dark", None)
            await self.db.set_guild_customize(ctx.guild.id, "color", color_dict)
            return await ctx.success("reset **dark** color to default")

        hex_code = hex_code.lstrip("#")
        try:
            int(hex_code, 16)
        except ValueError:
            return await ctx.warn("provide a valid hex color code (e.g., `2B2D31`)")

        settings = await self.db.get_guild_customize(ctx.guild.id)
        color_dict = settings.get("color", {})
        color_dict["dark"] = hex_code
        await self.db.set_guild_customize(ctx.guild.id, "color", color_dict)
        return await ctx.success(f"set **dark** color to `#{hex_code}`")

    @customize_context.group(
        name="color",
        usage="(subcommand) <args>",
        example="warn FF0000",
        invoke_without_command=True,
    )
    async def customize_context_color(self, ctx):
        """Customize your personal embed colors."""
        await ctx.send_help(ctx.command)

    @customize_context_color.command(
        name="list",
        aliases=["view"],
        example="",
    )
    async def customize_context_color_list(self, ctx):
        """View your personal color settings."""
        settings = await self.db.get_user_customize(ctx.author.id, ctx.guild.id)
        current = settings.get("color", {})

        if not current:
            return await ctx.warn("You have no **custom colors** set. Using defaults.")

        lines = [f"**{key}**: `#{value}`" for key, value in current.items()]
        embed = Embed(
            title="Your Color Settings",
            description="\n".join(lines),
            color=self.color,
        )
        embed.set_footer(text=f"Use {ctx.clean_prefix}customize context color <key> <hex> to change")
        await ctx.send(embed=embed)

    @customize_context_color.command(
        name="base",
        description="Set your personal base embed color",
        example="373737",
    )
    async def customize_context_color_base(self, ctx, hex_code: str = None):
        """Set your personal base color."""
        if not hex_code or hex_code.lower() in CLEAR_WORDS:
            settings = await self.db.get_user_customize(ctx.author.id, ctx.guild.id)
            color_dict = settings.get("color", {})
            color_dict.pop("base", None)
            await self.db.set_user_customize(ctx.author.id, ctx.guild.id, "color", color_dict)
            return await ctx.success("reset your **base** color to default")

        hex_code = hex_code.lstrip("#")
        try:
            int(hex_code, 16)
        except ValueError:
            return await ctx.warn("provide a valid hex color code (e.g., `373737`)")

        settings = await self.db.get_user_customize(ctx.author.id, ctx.guild.id)
        color_dict = settings.get("color", {})
        color_dict["base"] = hex_code
        await self.db.set_user_customize(ctx.author.id, ctx.guild.id, "color", color_dict)
        return await ctx.success(f"set your **base** color to `#{hex_code}`")

    @customize_context_color.command(
        name="approve",
        aliases=["success"],
        description="Set your personal approve/success color",
        example="A8EA7B",
    )
    async def customize_context_color_approve(self, ctx, hex_code: str = None):
        """Set your personal approve color."""
        if not hex_code or hex_code.lower() in CLEAR_WORDS:
            settings = await self.db.get_user_customize(ctx.author.id, ctx.guild.id)
            color_dict = settings.get("color", {})
            color_dict.pop("approve", None)
            await self.db.set_user_customize(ctx.author.id, ctx.guild.id, "color", color_dict)
            return await ctx.success("reset your **approve** color to default")

        hex_code = hex_code.lstrip("#")
        try:
            int(hex_code, 16)
        except ValueError:
            return await ctx.warn("provide a valid hex color code (e.g., `A8EA7B`)")

        settings = await self.db.get_user_customize(ctx.author.id, ctx.guild.id)
        color_dict = settings.get("color", {})
        color_dict["approve"] = hex_code
        await self.db.set_user_customize(ctx.author.id, ctx.guild.id, "color", color_dict)
        return await ctx.success(f"set your **approve** color to `#{hex_code}`")

    @customize_context_color.command(
        name="warn",
        description="Set your personal warning color",
        example="FDCF39",
    )
    async def customize_context_color_warn(self, ctx, hex_code: str = None):
        """Set your personal warn color."""
        if not hex_code or hex_code.lower() in CLEAR_WORDS:
            settings = await self.db.get_user_customize(ctx.author.id, ctx.guild.id)
            color_dict = settings.get("color", {})
            color_dict.pop("warn", None)
            await self.db.set_user_customize(ctx.author.id, ctx.guild.id, "color", color_dict)
            return await ctx.success("reset your **warn** color to default")

        hex_code = hex_code.lstrip("#")
        try:
            int(hex_code, 16)
        except ValueError:
            return await ctx.warn("provide a valid hex color code (e.g., `FDCF39`)")

        settings = await self.db.get_user_customize(ctx.author.id, ctx.guild.id)
        color_dict = settings.get("color", {})
        color_dict["warn"] = hex_code
        await self.db.set_user_customize(ctx.author.id, ctx.guild.id, "color", color_dict)
        return await ctx.success(f"set your **warn** color to `#{hex_code}`")

    @customize_context_color.command(
        name="deny",
        aliases=["error"],
        description="Set your personal deny/error color",
        example="FF0000",
    )
    async def customize_context_color_deny(self, ctx, hex_code: str = None):
        """Set your personal deny color."""
        if not hex_code or hex_code.lower() in CLEAR_WORDS:
            settings = await self.db.get_user_customize(ctx.author.id, ctx.guild.id)
            color_dict = settings.get("color", {})
            color_dict.pop("deny", None)
            await self.db.set_user_customize(ctx.author.id, ctx.guild.id, "color", color_dict)
            return await ctx.success("reset your **deny** color to default")

        hex_code = hex_code.lstrip("#")
        try:
            int(hex_code, 16)
        except ValueError:
            return await ctx.warn("provide a valid hex color code (e.g., `FF0000`)")

        settings = await self.db.get_user_customize(ctx.author.id, ctx.guild.id)
        color_dict = settings.get("color", {})
        color_dict["deny"] = hex_code
        await self.db.set_user_customize(ctx.author.id, ctx.guild.id, "color", color_dict)
        return await ctx.success(f"set your **deny** color to `#{hex_code}`")

    @customize_context_color.command(
        name="cooldown",
        description="Set your personal cooldown color",
        example="4EC3E8",
    )
    async def customize_context_color_cooldown(self, ctx, hex_code: str = None):
        """Set your personal cooldown color."""
        if not hex_code or hex_code.lower() in CLEAR_WORDS:
            settings = await self.db.get_user_customize(ctx.author.id, ctx.guild.id)
            color_dict = settings.get("color", {})
            color_dict.pop("cooldown", None)
            await self.db.set_user_customize(ctx.author.id, ctx.guild.id, "color", color_dict)
            return await ctx.success("reset your **cooldown** color to default")

        hex_code = hex_code.lstrip("#")
        try:
            int(hex_code, 16)
        except ValueError:
            return await ctx.warn("provide a valid hex color code (e.g., `4EC3E8`)")

        settings = await self.db.get_user_customize(ctx.author.id, ctx.guild.id)
        color_dict = settings.get("color", {})
        color_dict["cooldown"] = hex_code
        await self.db.set_user_customize(ctx.author.id, ctx.guild.id, "color", color_dict)
        return await ctx.success(f"set your **cooldown** color to `#{hex_code}`")

    @customize_context_color.command(
        name="settings",
        description="Set your personal settings color",
        example="7289DA",
    )
    async def customize_context_color_settings(self, ctx, hex_code: str = None):
        """Set your personal settings color."""
        if not hex_code or hex_code.lower() in CLEAR_WORDS:
            settings = await self.db.get_user_customize(ctx.author.id, ctx.guild.id)
            color_dict = settings.get("color", {})
            color_dict.pop("settings", None)
            await self.db.set_user_customize(ctx.author.id, ctx.guild.id, "color", color_dict)
            return await ctx.success("reset your **settings** color to default")

        hex_code = hex_code.lstrip("#")
        try:
            int(hex_code, 16)
        except ValueError:
            return await ctx.warn("provide a valid hex color code (e.g., `7289DA`)")

        settings = await self.db.get_user_customize(ctx.author.id, ctx.guild.id)
        color_dict = settings.get("color", {})
        color_dict["settings"] = hex_code
        await self.db.set_user_customize(ctx.author.id, ctx.guild.id, "color", color_dict)
        return await ctx.success(f"set your **settings** color to `#{hex_code}`")

    @customize_context_color.command(
        name="dark",
        description="Set your personal dark embed color",
        example="2B2D31",
    )
    async def customize_context_color_dark(self, ctx, hex_code: str = None):
        """Set your personal dark color."""
        if not hex_code or hex_code.lower() in CLEAR_WORDS:
            settings = await self.db.get_user_customize(ctx.author.id, ctx.guild.id)
            color_dict = settings.get("color", {})
            color_dict.pop("dark", None)
            await self.db.set_user_customize(ctx.author.id, ctx.guild.id, "color", color_dict)
            return await ctx.success("reset your **dark** color to default")

        hex_code = hex_code.lstrip("#")
        try:
            int(hex_code, 16)
        except ValueError:
            return await ctx.warn("provide a valid hex color code (e.g., `2B2D31`)")

        settings = await self.db.get_user_customize(ctx.author.id, ctx.guild.id)
        color_dict = settings.get("color", {})
        color_dict["dark"] = hex_code
        await self.db.set_user_customize(ctx.author.id, ctx.guild.id, "color", color_dict)
        return await ctx.success(f"set your **dark** color to `#{hex_code}`")
