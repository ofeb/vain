from __future__ import annotations

from typing import TYPE_CHECKING

import discord
from discord.ext.commands import group

from core.discord.package import Package
from core.discord.views.paginate import send_pages
from core.managers.permissions import has_permissions

from .settings import Settings, fetch_all

if TYPE_CHECKING:
    from core.vain import Vain


class Uwulock(Package):
    """Uwulock members so their messages get uwuified."""

    @group(
        name="uwulock",
        description="Uwulock a member so their messages get uwuified",
        invoke_without_command=True,
        example=",uwulock @member",
    )
    @has_permissions(manage_messages=True)
    async def uwulock(self, ctx, member: discord.Member = None) -> None:
        """Toggle uwulock for a member (defaults to you)."""
        if ctx.guild is None:
            return await ctx.warn("This command can only be used in a server")

        target = member or ctx.author
        settings = await Settings.fetch(self.bot, ctx.guild)
        if settings.is_locked(target.id):
            await settings.remove(target.id)
            return await ctx.success(f"{target.mention} is **not a simp** anymore :(")
        await settings.add(target.id)
        return await ctx.success(f"{target.mention} is now a **simp** :)")

    @uwulock.command(
        name="clear",
        aliases=["reset"],
        description="Remove all uwulocks in this server",
    )
    async def uwulock_clear(self, ctx) -> None:
        """Remove all uwulocks in this server."""
        if ctx.guild is None:
            return await ctx.warn("This command can only be used in a server")

        settings = await Settings.fetch(self.bot, ctx.guild)
        if not settings:
            return await ctx.warn("No members are **uwulocked**")
        await settings.clear()
        return await ctx.success("Removed **uwulock** from everyone")

    @uwulock.command(
        name="list",
        aliases=["ls", "show", "view"],
        description="List uwulocked members",
    )
    async def uwulock_list(self, ctx) -> None:
        """List uwulocked members."""
        if ctx.guild is None:
            return await ctx.warn("This command can only be used in a server")

        rows = await fetch_all(self.bot, ctx.guild)
        if not rows:
            return await ctx.warn("No members are **uwulocked**")

        lines = []
        for row in rows:
            member = ctx.guild.get_member(int(row["user_id"]))
            lines.append(
                f"{member.mention} (`{member.id}`)"
                if member
                else f"<@{row['user_id']}> (`{row['user_id']}`)"
            )

        per_page = 15
        total_pages = max(1, (len(lines) + per_page - 1) // per_page)
        pages: list[discord.Embed] = []
        for index in range(0, len(lines), per_page):
            chunk = lines[index : index + per_page]
            embed = discord.Embed(
                title="Uwulocked Members",
                color=self.color,
                description="\n".join(chunk),
            )
            embed.set_author(name=str(ctx.author), icon_url=ctx.author.display_avatar.url)
            embed.set_footer(text=f"Page {index // per_page + 1}/{total_pages}")
            pages.append(embed)
        return await send_pages(ctx, pages)


async def setup(bot: Vain):
    from .events import UwulockEvents

    await bot.add_cog(Uwulock(bot))
    await bot.add_cog(UwulockEvents(bot))
