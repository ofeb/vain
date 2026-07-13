from __future__ import annotations

from typing import Optional

import discord
from discord.ext import commands
from discord.ext.commands import CommandError

from core.discord.package import Package
from core.discord.ctx import Context
from core.discord.hybrid import group
from core.managers.permissions import has_permissions


class InviteTracker(Package):
    """invite tracking system"""

    async def _get_config(self, guild_id: int) -> dict:
        row = await self.db.fetchrow(
            "SELECT * FROM invite_config WHERE guild_id = $1", guild_id
        )
        if not row:
            return {
                "enabled": False,
                "channel_id": None,
                "message": "{inviter} invited {invitee}. They have **{invites}** {invite_word}.",
                "leave_message": "{invitee} left. {inviter} now has **{invites}** {invite_word}.",
                "fake_remove": True,
            }
        return dict(row)

    async def _get_invites(self, guild_id: int, user_id: int) -> dict:
        row = await self.db.fetchrow(
            "SELECT * FROM invite_counts WHERE guild_id = $1 AND user_id = $2",
            guild_id,
            user_id,
        )
        if not row:
            return {"invites": 0, "leaves": 0, "fake": 0, "bonus": 0}
        return dict(row)

    # ─── invites root ───────────────────────────────────────────────

    @group(
        name="invites",
        description="View and manage invite tracking",
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

        embed = discord.Embed(
            color=self.color,
            description=(
                f"**{user.display_name}**'s invites\n"
                f"Regular: **{data['invites']}**\n"
                f"Left: **{data['leaves']}**\n"
                f"Fake: **{data['fake']}**\n"
                f"Bonus: **{data['bonus']}**\n"
                f"Net: **{real}**"
            ),
        )
        embed.set_thumbnail(url=user.display_avatar.url)
        return await ctx.send(embed=embed)

    @invites.command(
        name="leaderboard",
        aliases=["lb", "top", "rank"],
        description="View the invite leaderboard",
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
                f"{medal} {name} — **{row['real']}** invites "
                f"({row['invites']} regular, {row['leaves']} left, {row['fake']} fake)"
            )

        embed = discord.Embed(title="Invite Leaderboard", color=self.color)
        return await ctx.paginate(embed, values)

    @invites.command(
        name="resetall",
        description="Wipe all invite stats for the server",
    )
    @has_permissions(manage_guild=True)
    async def invites_resetall(self, ctx: Context):
        await self.db.execute(
            "DELETE FROM invite_counts WHERE guild_id = $1", ctx.guild.id
        )
        await self.db.execute(
            "DELETE FROM invite_uses WHERE guild_id = $1", ctx.guild.id
        )
        await self.db.execute(
            "DELETE FROM member_invites WHERE guild_id = $1", ctx.guild.id
        )
        return await ctx.success("Wiped all invite stats for this server")

    @invites.command(
        name="resetuser",
        description="Reset invite counts for one user",
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
        description="Add bonus invites to a user",
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
            invite_lines.append(f"`{row['code']}` — **{row['uses']}** uses")

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

        embed = discord.Embed(description=description, color=self.color)
        embed.set_thumbnail(url=user.display_avatar.url)
        return await ctx.send(embed=embed)

    # ─── invitetracker root ─────────────────────────────────────────

    @group(
        name="invitetracker",
        aliases=["it"],
        description="Configure invite tracking",
        invoke_without_command=True,
    )
    @has_permissions(manage_guild=True)
    async def invitetracker(self, ctx: Context):
        await ctx.send_help(ctx.command)

    # ─── invitetracker join ─────────────────────────────────────────

    @invitetracker.group(
        name="join",
        description="Configure invite join messages",
        invoke_without_command=True,
    )
    @has_permissions(manage_guild=True)
    async def invitetracker_join(self, ctx: Context):
        await ctx.send_help(ctx.command)

    @invitetracker_join.command(
        name="set",
        description="Set the channel for invite join logs",
    )
    @has_permissions(manage_guild=True)
    async def invitetracker_join_set(self, ctx: Context, channel: Optional[discord.TextChannel] = None):
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
            f"Invite join logging enabled in {channel.mention}"
        )

    @invitetracker_join.command(
        name="on",
        description="Enable invite join messages",
    )
    @has_permissions(manage_guild=True)
    async def invitetracker_join_on(self, ctx: Context):
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
        return await ctx.success("Invite join messages enabled")

    @invitetracker_join.command(
        name="off",
        description="Disable invite join messages",
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
        description="Disable invite join logging",
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
        description="Set the invite join message",
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
        description="View current invite join configuration",
    )
    @has_permissions(manage_guild=True)
    async def invitetracker_join_view(self, ctx: Context):
        config = await self._get_config(ctx.guild.id)
        channel = ctx.guild.get_channel(config["channel_id"]) if config["channel_id"] else None

        embed = discord.Embed(title="Invite Join Config", color=self.color)
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

    # ─── invitetracker leave ────────────────────────────────────────

    @invitetracker.group(
        name="leave",
        description="Configure invite leave messages",
        invoke_without_command=True,
    )
    @has_permissions(manage_guild=True)
    async def invitetracker_leave(self, ctx: Context):
        await ctx.send_help(ctx.command)

    @invitetracker_leave.command(
        name="set",
        description="Set the channel for invite leave logs",
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
        description="Disable invite leave logging",
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
        description="Enable invite leave messages",
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
        description="Disable invite leave messages",
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
        description="Set the invite leave message",
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
        description="View current invite leave configuration",
    )
    @has_permissions(manage_guild=True)
    async def invitetracker_leave_view(self, ctx: Context):
        config = await self._get_config(ctx.guild.id)
        channel = ctx.guild.get_channel(config["channel_id"]) if config["channel_id"] else None

        embed = discord.Embed(title="Invite Leave Config", color=self.color)
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
