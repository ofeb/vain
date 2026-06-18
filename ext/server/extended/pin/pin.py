from discord.ext.commands import group, has_permissions, CommandError, Boolean
from discord import Embed, TextChannel
from core.discord.package import Package


class PinCommands(Package):
    """pin archival management"""

    @group(
        name="pins",
        description="Pin archival system commands",
        invoke_without_command=True,
    )
    async def pins(self, ctx):
        """pins help"""
        return await ctx.send_help()

    @pins.command(name="archive", description="Archive the pins in the current channel")
    @has_permissions(manage_guild=True)
    async def pins_archive(self, ctx):
        """run pin archive"""
        cfg = await self.db.fetchrow(
            """SELECT channel_id, enabled, unpinning FROM pin_config WHERE guild_id = $1""",
            ctx.guild.id,
        )
        if not cfg:
            raise CommandError("pin archival hasnt been set up")
        if not cfg.channel_id:
            raise CommandError("no archive channel set")
        if not cfg.enabled:
            raise CommandError("pin archival is disabled")
        dest = ctx.guild.get_channel(cfg.channel_id)
        if not dest:
            raise CommandError("archive channel was deleted")
        msg = await ctx.send(
            embed=Embed(color=self.bot.color, description="archiving pins, hold on...")
        )
        archived = await ctx.channel.archive_pins(dest, cfg.unpinning)
        count = len(archived)
        return await msg.edit(
            embed=await ctx.success(
                f"archived **{count}** {'pin' if count == 1 else 'pins'}",
                return_embed=True,
            )
        )

    @pins.command(
        name="config",
        description="View the pin archival config",
        aliases=["show", "cfg", "settings"],
    )
    @has_permissions(manage_guild=True)
    async def pins_config(self, ctx):
        """view pin config"""
        cfg = await self.db.fetchrow(
            """SELECT * FROM pin_config WHERE guild_id = $1""", ctx.guild.id
        )
        if not cfg:
            raise CommandError("pin archival hasnt been set up")
        if not cfg.channel_id:
            ch_val = "N/A"
        elif not (ch := ctx.guild.get_channel(cfg.channel_id)):
            ch_val = "channel deleted"
        else:
            ch_val = ch.mention

        def tick(val: bool) -> str:
            emojis = self.bot.config.get("emojis", {})
            return emojis.get("success", "yes") if val else emojis.get("fail", "no")

        embed = Embed(color=self.bot.color, title="Pin Archive Config")
        embed.description = (
            f"**Active:** {tick(cfg.enabled)}\n"
            f"**Unpin After:** {tick(cfg.unpinning)}\n"
            f"**Destination:** {ch_val}"
        )
        embed.set_author(name=str(ctx.author), icon_url=ctx.author.display_avatar.url)
        return await ctx.send(embed=embed)

    @pins.command(
        name="unpin",
        description="Enable or disable the unpinning of messages during archival",
    )
    @has_permissions(manage_guild=True)
    async def pins_unpin(self, ctx, option: Boolean):
        """toggle auto-unpin"""
        await self.db.execute(
            """INSERT INTO pin_config (guild_id, unpinning) VALUES($1, $2) ON CONFLICT(guild_id) DO UPDATE SET unpinning = excluded.unpinning""",
            ctx.guild.id, option,
        )
        state = "enabled" if option else "disabled"
        return await ctx.success(f"auto-unpin **{state}**")

    @pins.command(name="set", description="Enable or disable the pin archival system")
    @has_permissions(manage_guild=True)
    async def pins_set(self, ctx, option: Boolean):
        """toggle pin archival"""
        await self.db.execute(
            """INSERT INTO pin_config (guild_id, enabled) VALUES($1, $2) ON CONFLICT(guild_id) DO UPDATE SET enabled = excluded.enabled""",
            ctx.guild.id, option,
        )
        state = "enabled" if option else "disabled"
        return await ctx.success(f"pin archival **{state}**")

    @pins.command(name="channel", description="Set the pin archival channel")
    @has_permissions(manage_guild=True)
    async def pins_channel(self, ctx, *, channel: TextChannel):
        """set archive channel"""
        await self.db.execute(
            """INSERT INTO pin_config (guild_id, channel_id) VALUES($1, $2) ON CONFLICT(guild_id) DO UPDATE SET channel_id = excluded.channel_id""",
            ctx.guild.id, channel.id,
        )
        return await ctx.success(f"archive channel set to {channel.mention}")

    @pins.command(name="reset", description="Reset the pin archival config")
    @has_permissions(manage_guild=True)
    async def pins_reset(self, ctx):
        """clear pin config"""
        from ext.information.views import confirm
        prompt = await ctx.warning("clear the pin archive config?")
        ok = await confirm(self, ctx, prompt, ctx.author)
        if not ok:
            return await prompt.delete()
        await self.db.execute(
            """DELETE FROM pin_config WHERE guild_id = $1""", ctx.guild.id
        )
        return await prompt.edit(
            embed=await ctx.success("pin archive config cleared", return_embed=True)
        )
