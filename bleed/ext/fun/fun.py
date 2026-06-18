from __future__ import annotations

import random
import re
from typing import TYPE_CHECKING

import discord
from discord.ext import commands

from core.discord.ctx import Context
from core.discord.hybrid import hybrid, describe, group
from core.managers.values import color, emojis

if TYPE_CHECKING:
    pass


class Fun(commands.Cog):
    """Fun commands and games."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @hybrid(
        name="8ball",
        description="Ask the magic 8-ball a question",
        guild_only=True,
    )
    @describe(question="Your question for the magic 8-ball")
    async def eightball(self, ctx: Context, *, question: str) -> None:
        """Ask the magic 8-ball a question."""
        responses = [
            "It is certain.",
            "It is decidedly so.",
            "Without a doubt.",
            "Yes definitely.",
            "You may rely on it.",
            "As I see it, yes.",
            "Most likely.",
            "Outlook good.",
            "Yes.",
            "Signs point to yes.",
            "Reply hazy, try again.",
            "Ask again later.",
            "Better not tell you now.",
            "Cannot predict now.",
            "Concentrate and ask again.",
            "Don't count on it.",
            "My reply is no.",
            "My sources say no.",
            "Outlook not so good.",
            "Very doubtful.",
        ]
        response = random.choice(responses)
        embed = discord.Embed(
            title="🎱 Magic 8-Ball",
            description=f"**Question:** {question}\n**Answer:** {response}",
            color=color.base,
        )
        await ctx.send(embed=embed)

    @hybrid(
        name="roll",
        description="Roll a dice",
        guild_only=True,
    )
    @describe(sides="Number of sides on the dice (default 6)", count="Number of dice to roll (default 1)")
    async def roll(self, ctx: Context, sides: int = 6, count: int = 1) -> None:
        """Roll a dice."""
        if sides < 2 or sides > 100:
            return await ctx.fail("Sides must be between 2 and 100")
        if count < 1 or count > 10:
            return await ctx.fail("Count must be between 1 and 10")
        
        results = [random.randint(1, sides) for _ in range(count)]
        total = sum(results)
        
        embed = discord.Embed(
            title="🎲 Dice Roll",
            description=f"**Results:** {', '.join(map(str, results))}\n**Total:** {total}",
            color=color.base,
        )
        await ctx.send(embed=embed)

    @hybrid(
        name="flip",
        description="Flip a coin",
        guild_only=True,
    )
    async def flip(self, ctx: Context) -> None:
        """Flip a coin."""
        result = random.choice(["Heads", "Tails"])
        embed = discord.Embed(
            title="🪙 Coin Flip",
            description=f"**Result:** {result}",
            color=color.base,
        )
        await ctx.send(embed=embed)

    @hybrid(
        name="choose",
        description="Choose from a list of options",
        guild_only=True,
    )
    @describe(options="Options to choose from (separated by commas)")
    async def choose(self, ctx: Context, *, options: str) -> None:
        """Choose from a list of options."""
        choices = [opt.strip() for opt in options.split(",")]
        if len(choices) < 2:
            return await ctx.fail("Please provide at least 2 options")
        
        result = random.choice(choices)
        embed = discord.Embed(
            title="🎯 Random Choice",
            description=f"**Options:** {', '.join(choices)}\n**Chosen:** {result}",
            color=color.base,
        )
        await ctx.send(embed=embed)

    @hybrid(
        name="rate",
        description="Rate something out of 10",
        guild_only=True,
    )
    @describe(thing="Thing to rate")
    async def rate(self, ctx: Context, *, thing: str) -> None:
        """Rate something out of 10."""
        rating = random.randint(1, 10)
        embed = discord.Embed(
            title="⭐ Rating",
            description=f"**{thing}** gets a **{rating}/10**",
            color=color.base,
        )
        await ctx.send(embed=embed)

    @hybrid(
        name="slap",
        description="Slap someone",
        guild_only=True,
    )
    @describe(member="Member to slap")
    async def slap(self, ctx: Context, member: discord.Member) -> None:
        """Slap someone."""
        if member == ctx.author:
            return await ctx.fail("You can't slap yourself!")
        
        embed = discord.Embed(
            description=f"{ctx.author.mention} slapped {member.mention}! 👋",
            color=color.base,
        )
        await ctx.send(embed=embed)

    @hybrid(
        name="hug",
        description="Hug someone",
        guild_only=True,
    )
    @describe(member="Member to hug")
    async def hug(self, ctx: Context, member: discord.Member) -> None:
        """Hug someone."""
        embed = discord.Embed(
            description=f"{ctx.author.mention} hugged {member.mention}! 🤗",
            color=color.base,
        )
        await ctx.send(embed=embed)

    @hybrid(
        name="pat",
        description="Pat someone",
        guild_only=True,
    )
    @describe(member="Member to pat")
    async def pat(self, ctx: Context, member: discord.Member) -> None:
        """Pat someone."""
        embed = discord.Embed(
            description=f"{ctx.author.mention} patted {member.mention}! 🥰",
            color=color.base,
        )
        await ctx.send(embed=embed)

    @hybrid(
        name="kiss",
        description="Kiss someone",
        guild_only=True,
    )
    @describe(member="Member to kiss")
    async def kiss(self, ctx: Context, member: discord.Member) -> None:
        """Kiss someone."""
        embed = discord.Embed(
            description=f"{ctx.author.mention} kissed {member.mention}! 💋",
            color=color.base,
        )
        await ctx.send(embed=embed)

    @hybrid(
        name="kill",
        description="Kill someone (for fun)",
        guild_only=True,
    )
    @describe(member="Member to kill")
    async def kill(self, ctx: Context, member: discord.Member) -> None:
        """Kill someone (for fun)."""
        if member == ctx.author:
            return await ctx.fail("You can't kill yourself!")
        
        deaths = [
            f"{ctx.author.mention} killed {member.mention} with a spoon 🥄",
            f"{ctx.author.mention} threw {member.mention} off a cliff 🧗",
            f"{ctx.author.mention} deleted {member.mention}'s save file 💾",
            f"{ctx.author.mention} unplugged {member.mention}'s pc 💻",
            f"{ctx.author.mention} fed {member.mention} to the sharks 🦈",
        ]
        embed = discord.Embed(
            description=random.choice(deaths),
            color=color.base,
        )
        await ctx.send(embed=embed)

    @hybrid(
        name="avatar",
        description="Get a user's avatar",
        guild_only=True,
    )
    @describe(member="Member to get avatar from (defaults to you)")
    async def avatar(self, ctx: Context, member: discord.Member = None) -> None:
        """Get a user's avatar."""
        member = member or ctx.author
        embed = discord.Embed(
            title=f"{member.display_name}'s Avatar",
            color=color.base,
        )
        embed.set_image(url=member.display_avatar.url)
        await ctx.send(embed=embed)

    @hybrid(
        name="banner",
        description="Get a user's banner",
        guild_only=True,
    )
    @describe(member="Member to get banner from (defaults to you)")
    async def banner(self, ctx: Context, member: discord.Member = None) -> None:
        """Get a user's banner."""
        member = member or ctx.author
        user = await self.bot.fetch_user(member.id)
        
        if not user.banner:
            return await ctx.fail(f"{member.mention} doesn't have a banner")
        
        embed = discord.Embed(
            title=f"{member.display_name}'s Banner",
            color=color.base,
        )
        embed.set_image(url=user.banner.url)
        await ctx.send(embed=embed)

    @hybrid(
        name="ship",
        description="Ship two people together",
        guild_only=True,
    )
    @describe(member1="First member", member2="Second member (defaults to you)")
    async def ship(self, ctx: Context, member1: discord.Member, member2: discord.Member = None) -> None:
        """Ship two people together."""
        member2 = member2 or ctx.author
        
        if member1 == member2:
            return await ctx.fail("You can't ship someone with themselves!")
        
        combined_id = str(member1.id + member2.id)
        compatibility = int(combined_id[-2:]) % 100 + 1
        
        ship_name = f"{member1.display_name[:len(member1.display_name)//2]}{member2.display_name[len(member2.display_name)//2:]}"
        
        embed = discord.Embed(
            title="💕 Ship Calculator",
            description=f"**{member1.display_name}** ❤️ **{member2.display_name}**\n"
                        f"**Ship Name:** {ship_name}\n"
                        f"**Compatibility:** {compatibility}% ❤️",
            color=color.base,
        )
        
        if compatibility >= 80:
            embed.description += "\n\n🌟 Perfect match!"
        elif compatibility >= 60:
            embed.description += "\n\n✨ Great match!"
        elif compatibility >= 40:
            embed.description += "\n\n💫 Could work!"
        else:
            embed.description += "\n\n💔 Not a great match..."
        
        await ctx.send(embed=embed)

    @hybrid(
        name="fact",
        description="Get a random fun fact",
        guild_only=True,
    )
    async def fact(self, ctx: Context) -> None:
        """Get a random fun fact."""
        facts = [
            "Honey never spoils. Archaeologists have found pots of honey in ancient Egyptian tombs that are over 3,000 years old and still perfectly good to eat.",
            "The shortest war in history was between Britain and Zanzibar in 1896. Zanzibar surrendered after 38 minutes.",
            "A day on Venus is longer than a year on Venus.",
            "Octopuses have three hearts and blue blood.",
            "Bananas are berries, but strawberries aren't.",
            "The Hawaiian alphabet has only 12 letters.",
            "A group of flamingos is called a 'flamboyance'.",
            "The human brain uses 20% of the body's total oxygen and energy.",
            "Cows have best friends and get stressed when separated.",
            "The first oranges weren't orange - they were green.",
        ]
        embed = discord.Embed(
            title="🎉 Fun Fact",
            description=random.choice(facts),
            color=color.base,
        )
        await ctx.send(embed=embed)

    @hybrid(
        name="joke",
        description="Get a random joke",
        guild_only=True,
    )
    async def joke(self, ctx: Context) -> None:
        """Get a random joke."""
        jokes = [
            "Why don't scientists trust atoms? Because they make up everything!",
            "Why did the scarecrow win an award? Because he was outstanding in his field!",
            "I told my wife she was drawing her eyebrows too high. She looked surprised.",
            "Why don't eggs tell jokes? They'd crack each other up!",
            "What do you call a fake noodle? An impasta!",
            "Why did the bicycle fall over? Because it was two-tired!",
            "What do you call a bear with no teeth? A gummy bear!",
            "Why can't you give Elsa a balloon? Because she will let it go!",
            "What do you call a fish without eyes? A fsh!",
            "Why did the math book look so sad? Because it had too many problems!",
        ]
        embed = discord.Embed(
            title="😂 Joke",
            description=random.choice(jokes),
            color=color.base,
        )
        await ctx.send(embed=embed)


async def setup(bot: commands.Bot):
    await bot.add_cog(Fun(bot))
