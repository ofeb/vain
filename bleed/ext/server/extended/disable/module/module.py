from discord.ext.commands import group, has_permissions, CommandError, ModuleConverter
from discord import Embed, TextChannel
from core.discord.package import Package


class ModuleDisableCommands(Package):
    """disable modules per channel"""

    @group(
        name="disablemodule",
        description="Disable a module in a channel",
        example=",disablemodule servers #text",
        invoke_without_command=True,
    )
    @has_permissions(manage_channels=True)
    async def disablemodule(self, ctx, module: ModuleConverter, channel: TextChannel):
        """block a module"""
        row = await self.db.fetchrow(
            """SELECT * FROM disabled_modules WHERE guild_id = $1 AND event = $2""",
            ctx.guild.id, module,
        )
        if row:
            ids = list(row.channel_ids)
            ids.append(channel.id)
            await self.db.execute(
                """UPDATE disabled_modules SET channel_ids = $1 WHERE guild_id = $2 AND event = $3""",
                ids, ctx.guild.id, module,
            )
        else:
            await self.db.execute(
                """INSERT INTO disabled_modules (guild_id, event, channel_ids) VALUES($1, $2, $3)""",
                ctx.guild.id, module, [channel.id],
            )
        label = module.replace("_", " ")
        return await ctx.success(f"**disabled** `{label}` in {channel.mention}")

    @disablemodule.command(
        name="list",
        aliases=["ls", "show", "view"],
        description="View a list of disabled modules in guild",
    )
    @has_permissions(manage_channels=True)
    async def disablemodule_list(self, ctx):
        """list disabled modules"""
        data = await self.db.fetch(
            """SELECT module, channel_ids FROM disabled_modules WHERE guild_id = $1""",
            ctx.guild.id,
        )
        if not data:
            raise CommandError("no modules have been disabled")
        lines = []
        for row in data:
            label = row.module.replace("_", " ")
            for cid in row.channel_ids:
                ch = ctx.guild.get_channel(cid)
                if ch:
                    lines.append(f"**{label}** — ({ch.mention})")
        numbered = [f"`{i}` {ln}" for i, ln in enumerate(lines, start=1)]
        return await ctx.paginate(
            Embed(color=self.bot.color, title="Disabled Modules").set_author(
                name=str(ctx.author), icon_url=ctx.author.display_avatar.url
            ),
            numbered,
        )

    @disablemodule.command(
        name="all",
        description="Disable a module in every channel",
        example=",disablemodule all servers",
    )
    @has_permissions(manage_channels=True)
    async def disablemodule_all(self, ctx, module: ModuleConverter):
        """block module everywhere"""
        existing = await self.db.fetchrow(
            """SELECT * FROM disabled_modules WHERE guild_id = $1 AND module = $2""",
            ctx.guild.id, module,
        )
        if existing:
            fresh = [c.id for c in ctx.guild.text_channels if c.id not in existing.channel_ids]
            ids = list(existing.channel_ids) + fresh
            await self.db.execute(
                """UPDATE disabled_modules SET channel_ids = $1 WHERE guild_id = $2 AND module = $3""",
                ids, ctx.guild.id, module,
            )
        else:
            all_ids = [c.id for c in ctx.guild.text_channels]
            await self.db.execute(
                """INSERT INTO disabled_modules (guild_id, module, channel_ids) VALUES($1, $2, $3)""",
                ctx.guild.id, module, all_ids,
            )
        label = module.replace("_", " ")
        return await ctx.success(f"**disabled** `{label}` in all channels")
