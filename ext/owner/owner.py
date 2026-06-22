from __future__ import annotations

import io
import textwrap
import traceback
from typing import TYPE_CHECKING

import discord
from discord.ext import commands

from core.discord.ctx import Context
from core.discord.hybrid import describe, hybrid, group
from core.managers.values import color

if TYPE_CHECKING:
    pass


class Owner(commands.Cog):
    """Owner tools, reload, jishaku, and bot management."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot

    async def cog_check(self, ctx: Context) -> bool:
        if not await self.bot.is_owner(ctx.author):
            raise commands.NotOwner("You are not the bot owner.")
        return True

    @group(
        name="owner",
        description="Bot owner commands",
        invoke_without_command=True,
        aliases=["dev"],
    )
    async def owner(self, ctx: Context) -> None:
        await ctx.send_help(ctx.command)

    @owner.command(
        name="reload",
        description="Reload all or a specific extension",
        aliases=["rl"],
    )
    @describe(extension="Extension name to reload, or 'all'")
    async def owner_reload(self, ctx: Context, *, extension: str = "all") -> None:
        if extension == "all":
            success = []
            failed = []
            for ext in list(self.bot.extensions.keys()):
                try:
                    await self.bot.reload_extension(ext)
                    success.append(ext)
                except Exception as e:
                    failed.append((ext, str(e)))
            msg = f"Reloaded **{len(success)}** extensions."
            if failed:
                msg += f"\nFailed **{len(failed)}**: " + ", ".join(f"`{f[0]}` ({f[1]})" for f in failed[:3])
            await ctx.success(msg)
        else:
            ext_name = f"ext.{extension}"
            if ext_name not in self.bot.extensions:
                await ctx.fail(f"Extension `{extension}` is not loaded.")
                return
            try:
                await self.bot.reload_extension(ext_name)
                await ctx.success(f"Reloaded `{extension}`")
            except Exception as e:
                await ctx.fail(f"Failed to reload `{extension}`: {e}")

    @owner.command(
        name="load",
        description="Load a new extension",
        aliases=["add"],
    )
    @describe(extension="Extension name to load")
    async def owner_load(self, ctx: Context, *, extension: str) -> None:
        try:
            await self.bot.load_extension(f"ext.{extension}")
            await ctx.success(f"Loaded `{extension}`")
        except Exception as e:
            await ctx.fail(f"Failed to load `{extension}`: {e}")

    @owner.command(
        name="unload",
        description="Unload a loaded extension",
        aliases=["remove"],
    )
    @describe(extension="Extension name to unload")
    async def owner_unload(self, ctx: Context, *, extension: str) -> None:
        try:
            await self.bot.unload_extension(f"ext.{extension}")
            await ctx.success(f"Unloaded `{extension}`")
        except Exception as e:
            await ctx.fail(f"Failed to unload `{extension}`: {e}")

    @owner.command(
        name="sync",
        description="Sync slash commands to a specific guild or globally",
    )
    @describe(guild_id="Guild ID to sync to (leave empty for global)")
    async def owner_sync(self, ctx: Context, guild_id: str = None) -> None:
        if guild_id:
            guild = discord.Object(id=int(guild_id))
            synced = await self.bot.tree.sync(guild=guild)
            await ctx.success(f"Synced **{len(synced)}** commands to guild `{guild_id}`")
        else:
            synced = await self.bot.tree.sync()
            await ctx.success(f"Synced **{len(synced)}** commands globally")

    @owner.command(
        name="guilds",
        description="List all guilds the bot is in",
        aliases=["guilds"],
    )
    async def owner_servers(self, ctx: Context) -> None:
        entries = []
        for i, guild in enumerate(sorted(self.bot.guilds, key=lambda g: g.member_count, reverse=True), 1):
            owner_name = str(guild.owner) if guild.owner else "Unknown"
            entries.append(f"`{i}.` **{guild.name}** (`{guild.id}`) — {guild.member_count} members — Owner: {owner_name}")

        pages = [entries[i:i + 15] for i in range(0, len(entries), 15)]
        page = 0
        embed = discord.Embed(
            title=f"Guilds ({len(self.bot.guilds)})",
            description="\n".join(pages[page]),
            color=color.base,
        )
        embed.set_footer(text=f"Page {page + 1}/{len(pages)}")
        await ctx.send(embed=embed)

    @owner.command(
        name="leave",
        description="Leave a server by ID",
    )
    @describe(guild_id="ID of the server to leave")
    async def owner_leave(self, ctx: Context, guild_id: str) -> None:
        guild = self.bot.get_guild(int(guild_id))
        if not guild:
            await ctx.fail(f"Server `{guild_id}` not found.")
            return
        await guild.leave()
        await ctx.success(f"Left **{guild.name}** (`{guild.id}`)")

    @owner.command(
        name="dm",
        description="Send a DM to a user",
    )
    @describe(user_id="User ID to message", message="Message content")
    async def owner_dm(self, ctx: Context, user_id: str, *, message: str) -> None:
        user = self.bot.get_user(int(user_id))
        if not user:
            try:
                user = await self.bot.fetch_user(int(user_id))
            except Exception:
                await ctx.fail(f"User `{user_id}` not found.")
                return
        try:
            await user.send(message)
            await ctx.success(f"Message sent to **{user}**")
        except Exception as e:
            await ctx.fail(f"Failed to DM {user}: {e}")

    @owner.command(
        name="eval",
        description="Evaluate Python code",
        aliases=["exec", ">"],
    )
    @describe(code="Python code to evaluate")
    async def owner_eval(self, ctx: Context, *, code: str) -> None:
        code = textwrap.dedent(code).strip("```python ").strip("``` ")
        env = {
            "bot": self.bot,
            "ctx": ctx,
            "discord": discord,
            "commands": commands,
        }
        try:
            result = eval(code, env)
            if result is not None:
                if isinstance(result, discord.Embed):
                    await ctx.send(embed=result)
                else:
                    await ctx.send(f"```py\n{result}```")
        except Exception as e:
            tb = "".join(traceback.format_exception(type(e), e, e.__traceback__))
            await ctx.send(f"```py\n{tb[:1900]}```")

    @owner.command(
        name="shutdown",
        description="Shut down the bot",
        aliases=["die", "kill"],
    )
    async def owner_shutdown(self, ctx: Context) -> None:
        await ctx.success("Shutting down...")
        await self.bot.close()

    @hybrid(
        name="reload",
        description="Reload all bot extensions",
    )
    async def reload(self, ctx: Context) -> None:
        if not await self.bot.is_owner(ctx.author):
            return
        success = 0
        for ext in list(self.bot.extensions.keys()):
            try:
                await self.bot.reload_extension(ext)
                success += 1
            except Exception:
                pass
        await ctx.success(f"Reloaded **{success}** extensions.")

    @hybrid(
        name="sync",
        description="Sync slash commands globally",
    )
    async def sync(self, ctx: Context) -> None:
        if not await self.bot.is_owner(ctx.author):
            return
        synced = await self.bot.tree.sync()
        await ctx.success(f"Synced **{len(synced)}** commands globally.")

    @hybrid(
        name="guilds",
        description="List all guilds the bot is in",
    )
    async def guilds(self, ctx: Context) -> None:
        if not await self.bot.is_owner(ctx.author):
            return
        server_list = "\n".join(
            f"**{g.name}** (`{g.id}`) — {g.member_count} members"
            for g in sorted(self.bot.guilds, key=lambda g: g.member_count, reverse=True)[:20]
        )
        embed = discord.Embed(
            title=f"Guilds ({len(self.bot.guilds)})",
            description=server_list or "No guilds.",
            color=color.base,
        )
        await ctx.send(embed=embed)


async def setup(bot: commands.Bot):
    await bot.add_cog(Owner(bot))
