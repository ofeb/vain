from discord.ext.commands import group, CommandError
from discord import TextChannel
from core.discord.package import Package


from core.managers.converters import ModuleConverter
from core.managers.permissions import has_permissions
class ModuleEnableCommands(Package):
    """re-enable modules per channel"""

    @group(
        name="enablemodule",
        description="Enable a module in a channel",
        example=",enablemodule servers #text",
        invoke_without_command=True,
    )
    @has_permissions(manage_channels=True)
    async def enablemodule(self, ctx, module: ModuleConverter, channel: TextChannel):
        """enable module in channel"""
        stored = await self.db.fetchval(
            """SELECT channel_ids FROM disabled_modules WHERE guild_id = $1 AND module = $2""",
            ctx.guild.id,
            module,
        )
        if not stored:
            raise CommandError("that module wasnt disabled anywhere")
        if channel.id not in stored:
            raise CommandError(f"that module wasnt disabled in {channel.mention}")
        stored.remove(channel.id)
        await self.db.execute(
            """UPDATE disabled_modules SET channel_ids = $1 WHERE guild_id = $2 AND module = $3""",
            stored, ctx.guild.id, module,
        )
        label = module.replace("_", " ")
        return await ctx.success(f"**enabled** `{label}` in {channel.mention}")

    @enablemodule.command(
        name="all",
        description="Enables a module in every channel",
        example=",enablemodule all servers",
    )
    @has_permissions(manage_channels=True)
    async def enablemodule_all(self, ctx, *, module: ModuleConverter):
        """enable module everywhere"""
        await self.db.execute(
            """DELETE FROM disabled_modules WHERE guild_id = $1 AND module = $2""",
            ctx.guild.id,
            module,
        )
        label = module.replace("_", " ")
        return await ctx.success(f"**enabled** `{label}` in all channels")
