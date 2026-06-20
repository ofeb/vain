from __future__ import annotations

import re
from datetime import datetime

import discord
from discord import Embed
from discord.ext.commands import command, group

from core.discord.package import Package
from core.discord.views.paginate import PaginateView


class ServerCommands(Package):
    """standalone server commands"""

    def _parse_embed_script(self, script: str) -> dict:
        """Parse embed script format: {key: value}$v{key2: value2}"""
        result = {}
        parts = script.split("$v")
        for part in parts:
            part = part.strip()
            if not part.startswith("{") or not part.endswith("}"):
                continue
            content = part[1:-1].strip()
            colon_idx = content.find(":")
            if colon_idx == -1:
                continue
            key = content[:colon_idx].strip().lower()
            value = content[colon_idx + 1:].strip()
            result[key] = value
        return result

    def _parse_fields(self, embed_data: dict) -> list[dict]:
        """Extract fields from embed data."""
        fields = []
        for key, value in embed_data.items():
            if key.startswith("field"):
                parts = value.split("&&")
                if len(parts) >= 2:
                    name = parts[0].strip()
                    val = parts[1].strip()
                    inline = False
                    if len(parts) >= 3:
                        inline_str = parts[2].strip().lower()
                        inline = inline_str in ("true", "1", "yes", "on")
                    fields.append({"name": name, "value": val, "inline": inline})
        return fields

    def _parse_author(self, embed_data: dict) -> dict | None:
        """Extract author from embed data."""
        author_str = embed_data.get("author")
        if not author_str:
            return None
        parts = author_str.split("&&")
        result = {}
        if len(parts) >= 1:
            result["name"] = parts[0].strip()
        if len(parts) >= 2:
            result["icon_url"] = parts[1].strip()
        if len(parts) >= 3:
            result["url"] = parts[2].strip()
        return result

    def _parse_footer(self, embed_data: dict) -> dict | None:
        """Extract footer from embed data."""
        footer_str = embed_data.get("footer")
        if not footer_str:
            return None
        parts = footer_str.split("&&")
        result = {}
        if len(parts) >= 1:
            result["text"] = parts[0].strip()
        if len(parts) >= 2:
            result["icon_url"] = parts[1].strip()
        return result

    def _parse_color(self, color_str: str) -> int:
        """Parse color from hex string."""
        color_str = color_str.strip().lstrip("#")
        try:
            return int(color_str, 16)
        except ValueError:
            return self.color

    def _parse_timestamp(self, timestamp_str: str) -> datetime | None:
        """Parse timestamp string."""
        timestamp_str = timestamp_str.strip().lower()
        if timestamp_str in ("now", "true", "yes"):
            return datetime.utcnow()
        try:
            return datetime.fromisoformat(timestamp_str)
        except ValueError:
            return None

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

        embed_data = self._parse_embed_script(script)
        
        if not embed_data:
            embed = Embed(description=script, color=self.color)
            return await ctx.send(embed=embed)

        embed = Embed(color=self.color)

        if "title" in embed_data:
            embed.title = embed_data["title"][:256]

        if "description" in embed_data:
            embed.description = embed_data["description"][:4096]

        if "color" in embed_data:
            embed.color = self._parse_color(embed_data["color"])

        if "url" in embed_data:
            embed.url = embed_data["url"]

        if "image" in embed_data:
            embed.set_image(url=embed_data["image"])

        if "thumbnail" in embed_data:
            embed.set_thumbnail(url=embed_data["thumbnail"])

        if "timestamp" in embed_data:
            ts = self._parse_timestamp(embed_data["timestamp"])
            if ts:
                embed.timestamp = ts

        author = self._parse_author(embed_data)
        if author:
            embed.set_author(
                name=author.get("name", ""),
                icon_url=author.get("icon_url"),
                url=author.get("url"),
            )

        footer = self._parse_footer(embed_data)
        if footer:
            embed.set_footer(
                text=footer.get("text", ""),
                icon_url=footer.get("icon_url"),
            )

        fields = self._parse_fields(embed_data)
        for field in fields:
            embed.add_field(
                name=field["name"][:256],
                value=field["value"][:1024],
                inline=field["inline"],
            )

        await ctx.send(embed=embed)

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

        embed_data = self._parse_embed_script(script)
        if not embed_data:
            embed = Embed(description=script, color=self.color)
            return await ctx.send(embed=embed)

        embed = Embed(color=self.color)

        if "title" in embed_data:
            embed.title = embed_data["title"][:256]

        if "description" in embed_data:
            embed.description = embed_data["description"][:4096]

        if "color" in embed_data:
            embed.color = self._parse_color(embed_data["color"])

        if "url" in embed_data:
            embed.url = embed_data["url"]

        if "image" in embed_data:
            embed.set_image(url=embed_data["image"])

        if "thumbnail" in embed_data:
            embed.set_thumbnail(url=embed_data["thumbnail"])

        if "timestamp" in embed_data:
            ts = self._parse_timestamp(embed_data["timestamp"])
            if ts:
                embed.timestamp = ts

        author = self._parse_author(embed_data)
        if author:
            embed.set_author(
                name=author.get("name", ""),
                icon_url=author.get("icon_url"),
                url=author.get("url"),
            )

        footer = self._parse_footer(embed_data)
        if footer:
            embed.set_footer(
                text=footer.get("text", ""),
                icon_url=footer.get("icon_url"),
            )

        fields = self._parse_fields(embed_data)
        for field in fields:
            embed.add_field(
                name=field["name"][:256],
                value=field["value"][:1024],
                inline=field["inline"],
            )

        await ctx.send(embed=embed)

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
