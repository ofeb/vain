from __future__ import annotations

from discord import Embed
from discord.ext.commands import command

from core.discord.package import Package


class ServerCommands(Package):
    """standalone server commands"""

    @command(
        name="serverinfo",
        aliases=["si", "server", "guildinfo", "gi"],
        description="View information about the server",
    )
    async def serverinfo(self, ctx):
        """show server info"""
        g = ctx.guild
        e = Embed(title=g.name, color=self.color)
        e.set_thumbnail(url=g.icon.url if g.icon else None)
        e.add_field(name="Owner", value=str(g.owner), inline=True)
        e.add_field(name="Members", value=str(g.member_count), inline=True)
        e.add_field(name="Channels", value=str(len(g.channels)), inline=True)
        e.add_field(name="Roles", value=str(len(g.roles)), inline=True)
        e.add_field(name="Boosts", value=str(g.premium_subscription_count), inline=True)
        e.add_field(name="Created", value=f"<t:{int(g.created_at.timestamp())}:R>", inline=True)
        if g.banner:
            e.set_image(url=g.banner.url)
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
        e = Embed(
            title=f"Roles ({len(lines)})",
            description=" ".join(lines),
            color=self.color,
        )
        await ctx.send(embed=e)

    @command(
        name="bots",
        description="List all bots in the server",
    )
    async def bots(self, ctx):
        """list all bots"""
        bots = [m for m in ctx.guild.members if m.bot]
        e = Embed(
            title=f"Bots ({len(bots)})",
            description=" ".join(b.mention for b in bots) or "none",
            color=self.color,
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
        e = Embed(color=self.color)
        e.set_image(url=ctx.guild.icon.url)
        e.set_author(name=ctx.guild.name)
        await ctx.send(embed=e)

    @command(
        name="banner",
        aliases=["serverbanner"],
        description="View the server's banner",
    )
    async def banner(self, ctx):
        """show server banner"""
        if not ctx.guild.banner:
            from discord.ext.commands import CommandError
            raise CommandError("this server has no banner")
        e = Embed(color=self.color)
        e.set_image(url=ctx.guild.banner.url)
        e.set_author(name=ctx.guild.name)
        await ctx.send(embed=e)
