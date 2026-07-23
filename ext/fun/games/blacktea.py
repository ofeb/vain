from __future__ import annotations

import asyncio
from typing import List

import discord
from discord.ext import commands

from core.discord.ctx import Context
from config import color




def compose(*parts: str) -> str:
    return "\n".join(part for part in parts if part)

def body(*lines: str) -> str:
    return "\n".join(f"> {line}" for line in lines if line)

def caption(text: str) -> str:
    return f"-# {text}"

def c2(
    *,
    color: int,
    message: str,
    title: str | None = None,
    footer: str | None = None,
    author: str | None = None,
    timestamp: bool = True,
) -> discord.Embed:
    description = compose(
        body(message),
        caption(footer) if footer else None,
    )
    embed = discord.Embed(color=color, description=description)
    if title:
        embed.title = title
    if author:
        embed.set_author(name=author)
    if timestamp:
        embed.timestamp = discord.utils.utcnow()
    return embed



class BlackteaButton(discord.ui.Button):
    def __init__(self):
        self.users: List[int] = []
        super().__init__(emoji="☕", label="(0)")

    async def callback(self, interaction: discord.Interaction):
        if interaction.user.id in self.users:
            self.users.remove(interaction.user.id)
        else:
            self.users.append(interaction.user.id)

        self.label = f"({len(self.users)})"
        await interaction.response.edit_message(view=self.view)


async def start_blacktea(ctx: Context, *, life_count: int = 3, timeout: int = 10):
    """Start a blacktea game."""
    ctx.bot.blacktea_matches[ctx.guild.id] = {}
    embed = c2(
        color=color.base,
        title="BlackTea Matchmaking",
        message="The game will begin in **15** seconds. Please click the :coffee: to join the game.",
        timestamp=False,
    )
    embed.set_author(name=ctx.author.name, icon_url=ctx.author.display_avatar.url)
    embed.add_field(
        name="Goal",
        value=compose(
            body(
                f"You have **{timeout}** {'seconds' if timeout > 1 else 'second'} to find a word containing the given set of letters",
                "Failure to do so, will take away a life",
                f"Each player has **{life_count}** {'lives' if life_count > 1 else 'life'}",
                "The last one standing wins",
            ),
        ),
        inline=False,
    )

    view = discord.ui.View(timeout=18)

    async def on_timeout():
        view.children[0].disabled = True
        await view.message.edit(view=view)

    view.on_timeout = on_timeout
    button = BlackteaButton()
    view.add_item(button)

    view.message = await ctx.reply(embed=embed, view=view)
    ctx.bot.blacktea_messages[ctx.guild.id] = [view.message]
    await asyncio.sleep(15)

    if len(button.users) < 2:
        ctx.bot.blacktea_matches.pop(ctx.guild.id, None)
        return await view.message.edit(
            embed=c2(
                color=color.base,
                message="There are not enough players",
                timestamp=False,
            )
        )

    ctx.bot.blacktea_matches[ctx.guild.id] = {user: life_count for user in button.users}

    async def check_word(message: discord.Message):
        word = message.content.lower()
        return await ctx.bot.redis.sismember("words", word) == 1

    while len(ctx.bot.blacktea_matches[ctx.guild.id].keys()) > 1:
        await asyncio.sleep(0)
        for user in button.users:
            word = await ctx.bot.redis.random("words")
            e = c2(
                color=color.base,
                message=f":coffee: <@{user}> Say a word containing **{word[:3].upper()}**",
                timestamp=False,
            )
            m = await ctx.send(embed=e)
            ctx.bot.blacktea_messages[ctx.guild.id].append(m)
            try:
                message = await ctx.bot.wait_for(
                    "message",
                    timeout=timeout,
                    check=lambda msg: (
                        msg.author.id == user
                        and msg.channel == ctx.channel
                        and word[:3] in msg.content.lower()
                    ),
                )
                if not await check_word(message):
                    raise TimeoutError()
                await message.add_reaction("✅")
            except (asyncio.TimeoutError, TimeoutError):
                lifes = ctx.bot.blacktea_matches[ctx.guild.id].get(user)
                if lifes - 1 == 0:
                    e = c2(
                        color=color.base,
                        message=f"☠️ <@{user}> You're eliminated",
                        timestamp=False,
                    )
                    m = await ctx.send(embed=e)
                    ctx.bot.blacktea_messages[ctx.guild.id].append(m)
                    ctx.bot.blacktea_matches[ctx.guild.id].pop(user)
                    button.users.remove(user)

                    if len(ctx.bot.blacktea_matches[ctx.guild.id].keys()) == 1:
                        break
                else:
                    ctx.bot.blacktea_matches[ctx.guild.id][user] = lifes - 1
                    e = c2(
                        color=color.base,
                        message=f"🕰️ <@{user}> Time's up. **{lifes-1}** life(s) remaining",
                        timestamp=False,
                    )
                    m = await ctx.send(embed=e)
                    ctx.bot.blacktea_messages[ctx.guild.id].append(m)
    user = list(ctx.bot.blacktea_matches[ctx.guild.id].keys())[0]
    embed = c2(
        color=color.base,
        message=f"👑 <@{user}> Won the game",
        timestamp=False,
    )
    for c in discord.utils.chunk_list(ctx.bot.blacktea_messages[ctx.guild.id], 99):
        await ctx.channel.delete_messages(c)
    ctx.bot.blacktea_messages.pop(ctx.guild.id, None)
    ctx.bot.blacktea_matches.pop(ctx.guild.id, None)
    return await ctx.send(embed=embed)
