from __future__ import annotations

import discord
from discord.ext.commands import command, group

from core.discord.package import Package
from core.tools.embed import BadEmbed, ParseError, PreparedScript, parse


class ServerCommands(Package):
    """standalone server commands"""

    @staticmethod
    def _normalize_embed_script(script: str) -> str:
        value = str(script).strip()
        lowered = value.lower()
        if lowered.startswith("{embed}") or lowered.startswith("embed$v"):
            return value
        if value.startswith("$v{"):
            return "{embed}" + value
        if value.startswith("{"):
            return f"{{embed}}$v{value}"
        return value

    async def _send_embed_script(self, ctx, script: str):
        normalized = self._normalize_embed_script(script)

        from core.tools.embed import is_embed_script
        if not is_embed_script(normalized):
            payload = {"content": normalized}
        else:
            try:
                payload = await parse(normalized, sendable=True)
            except (ParseError, BadEmbed) as error:
                return await ctx.warn(str(error))

        if not payload or (
            payload.get("content") in {None, ""}
            and payload.get("embed") is None
            and payload.get("view") is None
        ):
            return await ctx.warn("Provide **valid embed code**.")

        try:
            return await PreparedScript(payload).send(ctx)
        except discord.HTTPException as error:
            message = str(error)
            if "):" in message:
                message = message.split("):", 1)[1].strip()
            return await ctx.warn(message or "invalid embed data")

    @group(
        name="embedcreate",
        aliases=["ce", "createembed"],
        usage="(script)",
        example="{title: Hello}$v{description: This is a test}$v{color: FF0000}",
        invoke_without_command=True,
    )
    async def embedcreate(self, ctx, *, script: str = None):
        """Create a custom embed using embed scripting."""
        if script is None:
            return await ctx.send_help()
        return await self._send_embed_script(ctx, script)

    @embedcreate.command(
        name="preview",
        aliases=["view"],
        usage="(script)",
        example="{title: Hello}$v{description: Test}",
    )
    async def embedcreate_preview(self, ctx, *, script: str = None):
        """Preview an embed script without sending it."""
        if script is None:
            return await ctx.fail("Provide an embed script to preview")
        return await self._send_embed_script(ctx, script)

    @command(
        name="variables",
        aliases=["vars"],
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
                    "{timestamp}": "Unix timestamp",
                    "{unix}": "Unix timestamp",
                },
            },
        }

        if category:
            category = category.lower()
            if category not in categories:
                await ctx.fail(
                    f"Invalid category `{category}`. Available: {', '.join(categories.keys())}"
                )
                return

            cat = categories[category]
            lines = [f"`{var}` — {desc}" for var, desc in cat["variables"].items()]
            embed = Embed(
                title=f"{cat['description']}",
                description="\n".join(lines),
                color=self.color,
            )
            embed.set_footer(text="Use these variables in embedcreate, autoresponders, and more")
            return await ctx.send(embed=embed)

        pages = []
        for cat in categories.values():
            lines = [f"`{var}` — {desc}" for var, desc in cat["variables"].items()]
            page = Embed(
                title=cat["description"],
                description="\n".join(lines),
                color=self.color,
            )
            page.set_footer(text=f"Use {ctx.clean_prefix}variables <category> for more details")
            pages.append(page)

        view = PaginateView(ctx, pages)
        view.message = await ctx.send(embed=pages[0], view=view)

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
        name="serverbanner",
        aliases=["guildbanner"],
        description="View the server's banner",
    )
    async def serverbanner(self, ctx):
        """show server banner"""
        if not ctx.guild.banner:
            from discord.ext.commands import CommandError
            raise CommandError("this server has no banner")
        e = Embed(color=self.color)
        e.set_image(url=ctx.guild.banner.url)
        e.set_author(name=ctx.guild.name)
        await ctx.send(embed=e)
