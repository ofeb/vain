from __future__ import annotations

from discord.ext.commands import group

from core.discord.package import Package


class Snapchat(Package):
    """snapchat management"""

    @group(
        name="snapchat",
        description="Get bitmoji and QR scan code for user",
        invoke_without_command=True,
    )
    async def snapchat(self, ctx, username: str):
        """get snapchat profile"""
        await ctx.send("Snapchat does not provide a public API for this feature")

    @snapchat.command(
        name="story",
        description="Gets all current stories for the given Snapchat user",
    )
    async def snapchat_story(self, ctx, username: str):
        """get snapchat stories"""
        await ctx.send("Snapchat does not provide a public API for this feature")
