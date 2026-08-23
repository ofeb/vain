from __future__ import annotations

from typing import Optional

import discord
from discord.ext import commands
from discord.ext.commands import CommandError

from core.discord.package import Package
from core.discord.ctx import Context
from core.discord.hybrid import group
from core.managers.permissions import has_permissions

from .settings import Settings as InviteSettings

from core.discord.views.embed import panel_embed

class InviteTracker(Package):
    """invite tracking system"""

    async def _get_config(self, guild_id: int) -> dict:
        guild = self.bot.get_guild(guild_id)
        if guild is None:
            return dict(InviteSettings.COLUMNS)
        settings = await InviteSettings.fetch(self.bot, guild)
        return {
            "enabled": bool(settings.enabled),
            "channel_id": settings.channel_id,
            "message": settings.message,
            "leave_message": settings.leave_message,
            "fake_remove": settings.fake_remove,
        }

    async def _get_invites(self, guild_id: int, user_id: int) -> dict:
        row = await self.db.fetchrow(
            "SELECT * FROM invite_counts WHERE guild_id = $1 AND user_id = $2",
            guild_id,
            user_id,
        )
        if not row:
            return {"invites": 0, "leaves": 0, "fake": 0, "bonus": 0}
        return dict(row)

    

    @group(
        name="invites",
        description="view and manage invite tracking",
        invoke_without_command=True,
    )
    @has_permissions(manage_guild=True)
    async def invites(self, ctx: Context):
        await ctx.send_help(ctx.command)

    @invites.command(name="view", description="View a user's invite stats")
    async def invites_view(self, ctx: Context, user: Optional[discord.Member] = None):
        if user is None:
            user = ctx.author

        data = await self._get_invites(ctx.guild.id, user.id)
        real = data["invites"] - data["leaves"] - data["fake"] + data["bonus"]

        embed = panel_embed(
            color=self.color,
            lines=[
                f"**{user.display_name}**'s invites",
                f"Regular: **{data['invites']}**",
                f"Left: **{data['leaves']}**",
                f"Fake: **{data['fake']}**",
                f"Bonus: **{data['bonus']}**",
                f"Net: **{real}**",
            ],
            thumbnail=user.display_avatar.url,
            timestamp=False,
        )
        return await ctx.send(embed=embed)

    @invites.command(
        name="leaderboard",
        aliases=["lb", "top", "rank"],
        description="view the invite leaderboard",
    )
    @has_permissions(manage_guild=True)
    async def invites_leaderboard(self, ctx: Context):
        rows = await self.db.fetch(
            """SELECT user_id, invites, leaves, fake, bonus,
                      (invites - leaves - fake + bonus) AS real
               FROM invite_counts WHERE guild_id = $1
               ORDER BY real DESC LIMIT 20""",
            ctx.guild.id,
        )
        if not rows:
            raise CommandError("No invite data found for this server")

        values = []
        medals = ["", "", ""]
        for i, row in enumerate(rows):
            member = ctx.guild.get_member(row["user_id"])
            name = member.display_name if member else f"<@{row['user_id']}>"
            medal = medals[i] if i < 3 else f"`{i + 1}`"
            values.append(
                f"{medal} {name} - **{row['real']}** invites "
                f"({row['invites']} regular, {row['leaves']} left, {row['fake']} fake)"
            )

        embed = panel_embed(title="Invite Leaderboard", color=self.color, lines=[], timestamp=False)
        return await ctx.paginate(embed, values)

    @invites.command(
        name="resetall",
        description="wipe all invite stats for the server",
    )
    @has_permissions(manage_guild=True)
    async def invites_resetall(self, ctx: Context):
        from core.discord.views.confirm import ConfirmView
        from config import color as color_values
        import discord as _discord

        view = ConfirmView(ctx)
        message = (
            "This will **wipe all invite stats** for this server.\n"
            "This action **can't be undone**.\n"
            "Are you sure you want to do this?\n"
        )
        if not await view.prompt(message):
            return await ctx.warn("Reset was **cancelled**\n> -# **invite tracker:** no changes were made")
        await self.db.execute(
            "DELETE FROM invite_counts WHERE guild_id = $1", ctx.guild.id
        )
        await self.db.execute(
            "DELETE FROM invite_uses WHERE guild_id = $1", ctx.guild.id
        )
        await self.db.execute(
            "DELETE FROM member_invites WHERE guild_id = $1", ctx.guild.id
        )
        return await ctx.success(
            "Wiped all invite stats for this server. This action **can't** be undone."
        )

    @invites.command(
        name="purge",
        description="delete all invites with 0 uses created by members",
    )
    @has_permissions(manage_guild=True)
    async def invites_purge(self, ctx: Context):
        from core.discord.views.confirm import ConfirmView

        await ctx.typing()
        invites = await ctx.guild.invites()

        purgeable = [
            inv for inv in invites
            if inv.uses == 0
            and inv.inviter is not None
            and not inv.inviter.bot
            and not inv.max_uses
            and not inv.max_age
        ]

        if not purgeable:
            return await ctx.warn("No **purgeable** invites found\n> -# **invites:** all invites have uses or are temporary")

        view = ConfirmView(ctx)
        message = (
            f"This will **delete {len(purgeable)} invite(s)** with 0 uses.\n"
            f"This action **can't be undone**.\n"
            f"Are you sure you want to do this?"
        )
        if not await view.prompt(message):
            return await ctx.warn("Purge was **cancelled**\n> -# **invites:** no invites were deleted")

        deleted = 0
        failed = 0
        for inv in purgeable:
            try:
                await inv.delete(reason=f"Invite purge by {ctx.author}")
                deleted += 1
            except discord.HTTPException:
                failed += 1

        parts = [f"**{deleted}** invite(s) deleted"]
        if failed:
            parts.append(f"**{failed}** failed to delete")
        return await ctx.success(", ".join(parts))

    @invites.command(
        name="resetuser",
        description="reset invite counts for one user",
    )
    @has_permissions(manage_guild=True)
    async def invites_resetuser(self, ctx: Context, member: discord.Member):
        await self.db.execute(
            "DELETE FROM invite_counts WHERE guild_id = $1 AND user_id = $2",
            ctx.guild.id,
            member.id,
        )
        await self.db.execute(
            "DELETE FROM invite_uses WHERE guild_id = $1 AND inviter_id = $2",
            ctx.guild.id,
            member.id,
        )
        await self.db.execute(
            "DELETE FROM member_invites WHERE guild_id = $1 AND (invitee_id = $2 OR inviter_id = $2)",
            ctx.guild.id,
            member.id,
        )
        return await ctx.success(
            f"Reset invite counts for **{member.display_name}**"
        )

    @invites.command(
        name="bonus",
        description="add bonus invites to a user",
    )
    @has_permissions(manage_guild=True)
    async def invites_bonus(
        self, ctx: Context, member: discord.Member, amount: int
    ):
        await self.db.execute(
            """
            INSERT INTO invite_counts (guild_id, user_id, invites, leaves, fake, bonus)
                VALUES ($1, $2, 0, 0, 0, $3)
            ON CONFLICT (guild_id, user_id)
                DO UPDATE SET bonus = invite_counts.bonus + $3
            """,
            ctx.guild.id,
            member.id,
            amount,
        )
        return await ctx.success(
            f"Added **{amount}** bonus invites to **{member.display_name}**"
        )

    @invites.command(
        name="userinvites",
        description="Break down a member's invite contributions",
    )
    async def invites_userinvites(
        self, ctx: Context, user: Optional[discord.Member] = None
    ):
        if user is None:
            user = ctx.author

        data = await self._get_invites(ctx.guild.id, user.id)
        real = data["invites"] - data["leaves"] - data["fake"] + data["bonus"]

        rows = await self.db.fetch(
            """SELECT code, uses FROM invite_uses
               WHERE guild_id = $1 AND inviter_id = $2
               ORDER BY uses DESC""",
            ctx.guild.id,
            user.id,
        )

        invite_lines = []
        for row in rows:
            invite_lines.append(f"`{row['code']}` - **{row['uses']}** uses")

        description = (
            f"**{user.display_name}** invite breakdown\n\n"
            f"Regular: **{data['invites']}**\n"
            f"Left: **{data['leaves']}**\n"
            f"Fake: **{data['fake']}**\n"
            f"Bonus: **{data['bonus']}**\n"
            f"Net: **{real}**"
        )
        if invite_lines:
            description += "\n\n**Active invites:**\n" + "\n".join(invite_lines)

        embed = panel_embed(color=self.color, lines=description.split("\n"), thumbnail=user.display_avatar.url, timestamp=False)
        return await ctx.send(embed=embed)

    

    @group(
        name="invitetracker",
        aliases=["it"],
        description="configure invite tracking",
        invoke_without_command=True,
    )
    @has_permissions(manage_guild=True)
    async def invitetracker(self, ctx: Context):
        await ctx.send_help(ctx.command)

    

    @invitetracker.group(
        name="join",
        description="configure invite join messages",
        invoke_without_command=True,
    )
    @has_permissions(manage_guild=True)
    async def invitetracker_join(self, ctx: Context):
        await ctx.send_help(ctx.command)

    @invitetracker_join.command(
        name="set",
        description="set the channel for invite join logs",
    )
    @has_permissions(manage_guild=True)
    async def invitetracker_join_set(self, ctx: Context, channel: Optional[discord.TextChannel] = None):
        if channel is None:
            channel = ctx.channel
        default_message = "{inviter.mention} invited {invitee.mention}. They have **{invites}** {invite_word}."
        default_leave = "{invitee.mention} left. {inviter.mention} now has **{invites}** {invite_word}."
        await self.db.execute(
            """
            INSERT INTO invite_config (guild_id, enabled, channel_id, message, leave_message, fake_remove)
                VALUES ($1, TRUE, $2, $3, $4, TRUE)
            ON CONFLICT (guild_id)
                DO UPDATE SET enabled = TRUE, channel_id = $2, message = $3, leave_message = $4
            """,
            ctx.guild.id,
            channel.id,
            default_message,
            default_leave,
        )
        return await ctx.success(
            f"Invite join logging enabled in {channel.mention}"
        )

    @invitetracker_join.command(
        name="on",
        description="enable invite join messages",
    )
    @has_permissions(manage_guild=True)
    async def invitetracker_join_on(self, ctx: Context):
        config = await self._get_config(ctx.guild.id)
        default_message = "{inviter.mention} invited {invitee.mention}. They have **{invites}** {invite_word}."
        default_leave = "{invitee.mention} left. {inviter.mention} now has **{invites}** {invite_word}."
        if not config["channel_id"]:
            await self.db.execute(
                """
                INSERT INTO invite_config (guild_id, enabled, channel_id, message, leave_message, fake_remove)
                    VALUES ($1, TRUE, $2, $3, $4, TRUE)
                ON CONFLICT (guild_id)
                    DO UPDATE SET enabled = TRUE, channel_id = $2, message = $3, leave_message = $4
                """,
                ctx.guild.id,
                ctx.channel.id,
                default_message,
                default_leave,
            )
        else:
            await self.db.execute(
                "UPDATE invite_config SET enabled = TRUE WHERE guild_id = $1",
                ctx.guild.id,
            )
        return await ctx.success("Invite join messages enabled")

    @invitetracker_join.command(
        name="off",
        description="disable invite join messages",
    )
    @has_permissions(manage_guild=True)
    async def invitetracker_join_off(self, ctx: Context):
        await self.db.execute(
            "UPDATE invite_config SET enabled = FALSE WHERE guild_id = $1",
            ctx.guild.id,
        )
        return await ctx.success("Invite join messages disabled")

    @invitetracker_join.command(
        name="remove",
        description="disable invite join logging",
    )
    @has_permissions(manage_guild=True)
    async def invitetracker_join_remove(self, ctx: Context):
        await self.db.execute(
            "UPDATE invite_config SET enabled = FALSE WHERE guild_id = $1",
            ctx.guild.id,
        )
        return await ctx.success("Invite join tracking disabled")

    @invitetracker_join.command(
        name="message",
        description="set the invite join message",
        usage="(text)",
        example=",invitetracker join message welcome {user.mention} invited by {inviter.mention}",
    )
    @has_permissions(manage_guild=True)
    async def invitetracker_join_message(self, ctx: Context, *, message: str):
        await self.db.execute(
            """
            INSERT INTO invite_config (guild_id, message)
                VALUES ($1, $2)
            ON CONFLICT (guild_id)
                DO UPDATE SET message = $2
            """,
            ctx.guild.id,
            message,
        )
        return await ctx.success("Invite join message updated")

    @invitetracker_join.command(
        name="view",
        description="view current invite join configuration",
    )
    @has_permissions(manage_guild=True)
    async def invitetracker_join_view(self, ctx: Context):
        config = await self._get_config(ctx.guild.id)
        channel = ctx.guild.get_channel(config["channel_id"]) if config["channel_id"] else None

        embed = panel_embed(title="Invite Join Config", color=self.color, lines=[], timestamp=False)
        embed.add_field(name="Enabled", value=str(config["enabled"]), inline=True)
        embed.add_field(
            name="Channel",
            value=channel.mention if channel else "Not set",
            inline=True,
        )
        embed.add_field(
            name="Join Message",
            value=config["message"][:1024],
            inline=False,
        )
        return await ctx.send(embed=embed)

    

    @invitetracker.group(
        name="leave",
        description="configure invite leave messages",
        invoke_without_command=True,
    )
    @has_permissions(manage_guild=True)
    async def invitetracker_leave(self, ctx: Context):
        await ctx.send_help(ctx.command)

    @invitetracker_leave.command(
        name="set",
        description="set the channel for invite leave logs",
    )
    @has_permissions(manage_guild=True)
    async def invitetracker_leave_set(self, ctx: Context, channel: Optional[discord.TextChannel] = None):
        if channel is None:
            channel = ctx.channel
        config = await self._get_config(ctx.guild.id)
        await self.db.execute(
            """
            INSERT INTO invite_config (guild_id, enabled, channel_id, message, leave_message, fake_remove)
                VALUES ($1, TRUE, $2, $3, $4, $5)
            ON CONFLICT (guild_id)
                DO UPDATE SET enabled = TRUE, channel_id = $2
            """,
            ctx.guild.id,
            channel.id,
            config["message"],
            config["leave_message"],
            config["fake_remove"],
        )
        return await ctx.success(
            f"Invite leave logging enabled in {channel.mention}"
        )

    @invitetracker_leave.command(
        name="remove",
        description="disable invite leave logging",
    )
    @has_permissions(manage_guild=True)
    async def invitetracker_leave_remove(self, ctx: Context):
        await self.db.execute(
            "UPDATE invite_config SET enabled = FALSE WHERE guild_id = $1",
            ctx.guild.id,
        )
        return await ctx.success("Invite leave tracking disabled")

    @invitetracker_leave.command(
        name="on",
        description="enable invite leave messages",
    )
    @has_permissions(manage_guild=True)
    async def invitetracker_leave_on(self, ctx: Context):
        config = await self._get_config(ctx.guild.id)
        if not config["channel_id"]:
            await self.db.execute(
                """
                INSERT INTO invite_config (guild_id, enabled, channel_id, message, leave_message, fake_remove)
                    VALUES ($1, TRUE, $2, $3, $4, $5)
                ON CONFLICT (guild_id)
                    DO UPDATE SET enabled = TRUE, channel_id = $2
                """,
                ctx.guild.id,
                ctx.channel.id,
                config["message"],
                config["leave_message"],
                config["fake_remove"],
            )
        else:
            await self.db.execute(
                "UPDATE invite_config SET enabled = TRUE WHERE guild_id = $1",
                ctx.guild.id,
            )
        return await ctx.success("Invite leave messages enabled")

    @invitetracker_leave.command(
        name="off",
        description="disable invite leave messages",
    )
    @has_permissions(manage_guild=True)
    async def invitetracker_leave_off(self, ctx: Context):
        await self.db.execute(
            "UPDATE invite_config SET enabled = FALSE WHERE guild_id = $1",
            ctx.guild.id,
        )
        return await ctx.success("Invite leave messages disabled")

    @invitetracker_leave.command(
        name="message",
        description="set the invite leave message",
        usage="(text)",
        example=",invitetracker leave message {user.mention} left the server",
    )
    @has_permissions(manage_guild=True)
    async def invitetracker_leave_message(self, ctx: Context, *, message: str):
        await self.db.execute(
            """
            INSERT INTO invite_config (guild_id, leave_message)
                VALUES ($1, $2)
            ON CONFLICT (guild_id)
                DO UPDATE SET leave_message = $2
            """,
            ctx.guild.id,
            message,
        )
        return await ctx.success("Invite leave message updated")

    @invitetracker_leave.command(
        name="view",
        description="view current invite leave configuration",
    )
    @has_permissions(manage_guild=True)
    async def invitetracker_leave_view(self, ctx: Context):
        config = await self._get_config(ctx.guild.id)
        channel = ctx.guild.get_channel(config["channel_id"]) if config["channel_id"] else None

        embed = panel_embed(title="Invite Leave Config", color=self.color, lines=[], timestamp=False)
        embed.add_field(name="Enabled", value=str(config["enabled"]), inline=True)
        embed.add_field(
            name="Channel",
            value=channel.mention if channel else "Not set",
            inline=True,
        )
        embed.add_field(
            name="Leave Message",
            value=config["leave_message"][:1024],
            inline=False,
        )
        return await ctx.send(embed=embed)

from .events import InviteTrackerEvents

async def setup(bot) -> None:
    await bot.add_cog(InviteTracker(bot))
    await bot.add_cog(InviteTrackerEvents(bot))
