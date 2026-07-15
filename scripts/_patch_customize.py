from pathlib import Path

path = Path("ext/server/extended/customize/customize.py")
text = path.read_text(encoding="utf-8-sig")
marker = '    @group(\n        name="context",'
idx = text.find(marker)
if idx < 0:
    raise SystemExit("marker not found")
head = text[:idx].rstrip() + "\n\n"

context_block = r'''
    # ── Context (guild + personal) ──────────────────────────────────────────
    # Guild:  ,context color|emoji ...
    # User:   ,context self color|emoji ...
    # Customize must NOT own these groups.

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

    # ── personal ────────────────────────────────────────────────────────────
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

    # guild color
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

    # guild emoji
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

    # personal color
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

    # personal emoji
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
'''

path.write_text(head + context_block.lstrip("\n"), encoding="utf-8")
print("wrote", path, "lines", len((head + context_block).splitlines()))
