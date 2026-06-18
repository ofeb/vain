from discord.ext.commands import group, has_permissions, CommandError
from core.discord.package import Package


class PrefixCommands(Package):
    """server prefix management commands"""

    @group(
        name="prefix",
        description="View guild prefix",
        invoke_without_command=True,
    )
    async def prefix(self, ctx):
        """show current prefix"""
        stored = await self.db.fetchval(
            """SELECT prefixes FROM config WHERE guild_id = $1""", ctx.guild.id
        ) or [","]
        await ctx.pin(
            f"**{ctx.guild.name}** uses {', '.join(f'`{p}`' for p in stored)} as prefix"
        )

    @prefix.command(
        name="set",
        aliases=["setup"],
        description="Set command prefix for server",
        example=",prefix set !",
    )
    @has_permissions(manage_guild=True)
    async def prefix_set(self, ctx, prefix: str):
        """replace the guild prefix"""
        if len(prefix) > 3:
            raise CommandError("prefix cant be longer than **3** characters")
        await self.db.execute(
            """INSERT INTO config (guild_id, prefixes) VALUES($1, $2) ON CONFLICT(guild_id) DO UPDATE SET prefixes = excluded.prefixes""",
            ctx.guild.id,
            [prefix],
        )
        return await ctx.success(f"guild prefix is now `{prefix}`")

    @prefix.command(
        name="add",
        aliases=["a"],
        description="add another prefix to the guild",
        example=",prefix add !",
    )
    @has_permissions(manage_guild=True)
    async def prefix_add(self, ctx, prefix: str):
        """append a guild prefix"""
        if len(prefix) > 3:
            raise CommandError("prefix cant be longer than **3** characters")
        await self.db.execute(
            """INSERT INTO config (guild_id, prefixes) VALUES($1, $2) ON CONFLICT(guild_id) DO UPDATE SET prefixes = ARRAY(SELECT 'prefix_' || unnest(EXCLUDED.prefixes));""",
            ctx.guild.id,
            prefix,
        )
        return await ctx.success(f"`{prefix}` added as a guild prefix")

    @prefix.command(
        name="reset",
        aliases=["rs"],
        description="reset guild prefixes to default",
    )
    @has_permissions(manage_guild=True)
    async def prefix_reset(self, ctx):
        """wipe custom prefixes"""
        try:
            await self.db.execute(
                """UPDATE config SET prefixes = $1 WHERE guild_id = $2""",
                [","],
                ctx.guild.id,
            )
        except Exception:
            pass
        return await ctx.success("server prefixes reset to `,`")

    @prefix.command(
        name="remove",
        aliases=["rm"],
        description="Remove command prefix for server",
    )
    @has_permissions(manage_guild=True)
    async def prefix_remove(self, ctx, prefix: str):
        """drop a single prefix"""
        existing = await self.db.fetchval(
            """SELECT prefixes FROM config WHERE guild_id = $1""", ctx.guild.id
        )
        if prefix not in existing:
            raise CommandError("that prefix isn't set for this server")
        if existing != [","]:
            existing.remove(prefix)
            if len(existing) == 0:
                existing = [","]
            await self.db.execute(
                """UPDATE config SET prefixes = $1 WHERE guild_id = $2""",
                existing,
                ctx.guild.id,
            )
            return await ctx.success(f"removed prefix `{prefix}`")
        else:
            return await ctx.fail("no custom prefix set to remove")

    @prefix.group(
        name="self",
        description="Set personal prefix across all servers with bleed",
        example=",prefix self k!",
        invoke_without_command=True,
    )
    async def prefix_self(self, ctx, prefix: str):
        """personal prefix for you"""
        if len(prefix) > 3:
            raise CommandError("prefix cant be longer than **3** characters")
        await self.db.execute(
            """INSERT INTO self_prefix (user_id, prefix) VALUES($1, $2) ON CONFLICT(user_id) DO UPDATE SET prefix = excluded.prefix""",
            ctx.author.id,
            prefix,
        )
        return await ctx.success(f"your personal prefix is now `{prefix}`")

    @prefix_self.command(
        name="remove",
        aliases=["clear", "cl", "del", "delete", "d", "c", "r"],
        description="clear your personal prefix",
    )
    async def prefix_self_remove(self, ctx):
        """clear your own prefix"""
        await self.db.execute(
            """DELETE FROM self_prefix WHERE user_id = $1""", ctx.author.id
        )
        return await ctx.success("personal prefix cleared")
