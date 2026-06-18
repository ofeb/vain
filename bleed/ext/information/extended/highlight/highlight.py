from __future__ import annotations

from discord.ext.commands import group

from core.discord.package import Package


class Highlight(Package):
    """highlight management"""

    def __init__(self, bot):
        self.bot = bot

    @group(
        name="highlight",
        description="Set notifications for when a keyword is said",
        invoke_without_command=True,
    )
    async def highlight(self, ctx):
        """highlight group help"""
        return await ctx.send_help(ctx.command)

    @highlight.command(
        name="remove",
        description="Remove a highlighted keyword",
    )
    async def highlight_remove(self, ctx, keyword: str):
        """remove highlighted keyword"""
        await self.bot.db.execute(
            "DELETE FROM highlights WHERE guild_id = $1 AND user_id = $2 AND keyword = $3",
            ctx.guild.id, ctx.author.id, keyword.lower()
        )
        await ctx.success(f"Removed highlight `{keyword}`")

    @highlight.command(
        name="list",
        description="List all keywords set in a server",
    )
    async def highlight_list(self, ctx):
        """list highlighted keywords"""
        highlights = await self.bot.db.fetch(
            "SELECT keyword FROM highlights WHERE guild_id = $1 AND user_id = $2",
            ctx.guild.id, ctx.author.id
        )
        
        if not highlights:
            return await ctx.send("You have no highlights set")
        
        keywords = [h['keyword'] for h in highlights]
        await ctx.send(f"Your highlights: {', '.join(keywords)}")

    @highlight.command(
        name="reset",
        description="No description given",
    )
    async def highlight_reset(self, ctx):
        """reset all highlights"""
        await self.bot.db.execute(
            "DELETE FROM highlights WHERE guild_id = $1 AND user_id = $2",
            ctx.guild.id, ctx.author.id
        )
        await ctx.success("Reset all your highlights")

    @highlight.command(
        name="ignore",
        description="Ignore notifications from members or a channel or a role",
    )
    async def highlight_ignore(self, ctx, member_or_channel_or_role):
        """ignore highlight from member/channel/role"""
        target_type = None
        target_id = None
        
        if isinstance(member_or_channel_or_role, discord.Member):
            target_type = "user"
            target_id = member_or_channel_or_role.id
        elif isinstance(member_or_channel_or_role, discord.Role):
            target_type = "role"
            target_id = member_or_channel_or_role.id
        elif isinstance(member_or_channel_or_role, discord.abc.GuildChannel):
            target_type = "channel"
            target_id = member_or_channel_or_role.id
        else:
            return await ctx.send("Invalid target type")
        
        await self.bot.db.execute(
            "INSERT INTO highlight_ignores (guild_id, user_id, target_id, target_type) VALUES($1, $2, $3, $4) ON CONFLICT(guild_id, user_id, target_id, target_type) DO NOTHING",
            ctx.guild.id, ctx.author.id, target_id, target_type
        )
        await ctx.success(f"Ignored {member_or_channel_or_role.mention}")

    @highlight.command(
        name="ignore list",
        description="List all ignored members, channel & roles",
    )
    async def highlight_ignore_list(self, ctx):
        """list ignored highlights"""
        ignores = await self.bot.db.fetch(
            "SELECT target_id, target_type FROM highlight_ignores WHERE guild_id = $1 AND user_id = $2",
            ctx.guild.id, ctx.author.id
        )
        
        if not ignores:
            return await ctx.send("You have no ignored targets")
        
        rows = []
        for ignore in ignores:
            if ignore['target_type'] == "user":
                member = ctx.guild.get_member(ignore['target_id'])
                if member:
                    rows.append(f"User: {member.mention}")
            elif ignore['target_type'] == "role":
                role = ctx.guild.get_role(ignore['target_id'])
                if role:
                    rows.append(f"Role: {role.mention}")
            elif ignore['target_type'] == "channel":
                channel = ctx.guild.get_channel(ignore['target_id'])
                if channel:
                    rows.append(f"Channel: {channel.mention}")
        
        await ctx.send("\n".join(rows))

    @highlight.command(
        name="add",
        description="Add a highlighted keyword",
    )
    async def highlight_add(self, ctx, keyword: str):
        """add highlighted keyword"""
        await self.bot.db.execute(
            "INSERT INTO highlights (guild_id, user_id, keyword) VALUES($1, $2, $3) ON CONFLICT(guild_id, user_id, keyword) DO NOTHING",
            ctx.guild.id, ctx.author.id, keyword.lower()
        )
        await ctx.success(f"Added highlight `{keyword}`")
