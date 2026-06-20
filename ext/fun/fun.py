from __future__ import annotations

import random
import re
import urllib.parse
from typing import TYPE_CHECKING

import aiohttp
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

    @hybrid(
        name="google",
        description="Search the largest search engine on the internet",
        aliases=["g"],
        guild_only=True,
    )
    @describe(search="Search query")
    async def google(self, ctx: Context, *, search: str) -> None:
        query = urllib.parse.quote(search)
        embed = discord.Embed(
            title="Google Search",
            description=f"[Search for **{search}** on Google](https://www.google.com/search?q={query})",
            color=color.base,
        )
        embed.set_footer(text="Google", icon_url="https://www.google.com/favicon.ico")
        await ctx.send(embed=embed)

    @hybrid(
        name="duckduckgo",
        description="Search the DuckDuckGo search engine",
        aliases=["ddg"],
        guild_only=True,
    )
    @describe(search="Search query")
    async def duckduckgo(self, ctx: Context, *, search: str) -> None:
        query = urllib.parse.quote(search)
        embed = discord.Embed(
            title="DuckDuckGo Search",
            description=f"[Search for **{search}** on DuckDuckGo](https://duckduckgo.com/?q={query})",
            color=color.base,
        )
        embed.set_footer(text="DuckDuckGo", icon_url="https://duckduckgo.com/favicon.ico")
        await ctx.send(embed=embed)

    @hybrid(
        name="duckduckgoimage",
        description="Search DuckDuckGo for an image",
        aliases=["ddgim", "ddgimg"],
        guild_only=True,
    )
    @describe(search="Search query")
    async def duckduckgoimage(self, ctx: Context, *, search: str) -> None:
        query = urllib.parse.quote(search)
        embed = discord.Embed(
            title="DuckDuckGo Image Search",
            description=f"[Search for **{search}** images on DuckDuckGo](https://duckduckgo.com/?q={query}&iar=images&iax=images&ia=images)",
            color=color.base,
        )
        embed.set_footer(text="DuckDuckGo", icon_url="https://duckduckgo.com/favicon.ico")
        await ctx.send(embed=embed)

    @hybrid(
        name="reverseimage",
        description="Reverse image search on Google",
        aliases=["rimage", "rimg"],
        guild_only=True,
    )
    @describe(url="Image URL to reverse search")
    async def reverseimage(self, ctx: Context, url: str = None) -> None:
        if not url and ctx.message.attachments:
            url = ctx.message.attachments[0].url
        if not url:
            return await ctx.fail("Provide an image URL or attach an image.")

        query = urllib.parse.quote(url)
        embed = discord.Embed(
            title="Reverse Image Search",
            description=f"[Reverse search this image on Google](https://lens.google.com/uploadbyurl?url={query})",
            color=color.base,
        )
        embed.set_thumbnail(url=url)
        await ctx.send(embed=embed)

    @hybrid(
        name="image",
        description="Search Google for an image",
        aliases=["im", "img"],
        guild_only=True,
    )
    @describe(search="Search query")
    async def image(self, ctx: Context, *, search: str) -> None:
        query = urllib.parse.quote(search)
        embed = discord.Embed(
            title="Image Search",
            description=f"[Search for **{search}** images on Google](https://www.google.com/search?q={query}&tbm=isch)",
            color=color.base,
        )
        await ctx.send(embed=embed)

    @hybrid(
        name="giphy",
        description="Search Giphy for gif results",
        aliases=["gif"],
        guild_only=True,
    )
    @describe(keyword="Search keyword")
    async def giphy(self, ctx: Context, *, keyword: str) -> None:
        query = urllib.parse.quote(keyword)
        embed = discord.Embed(
            title="Giphy Search",
            description=f"[Search for **{keyword}** on Giphy](https://giphy.com/search/{query})",
            color=color.base,
        )
        await ctx.send(embed=embed)

    @hybrid(
        name="tenor",
        description="Search Tenor for gif results",
        guild_only=True,
    )
    @describe(keyword="Search keyword")
    async def tenor(self, ctx: Context, *, keyword: str) -> None:
        query = urllib.parse.quote(keyword)
        embed = discord.Embed(
            title="Tenor Search",
            description=f"[Search for **{keyword}** on Tenor](https://tenor.com/search/{query})",
            color=color.base,
        )
        await ctx.send(embed=embed)

    @hybrid(
        name="wikihow",
        description="How to...?",
        aliases=["whow"],
        guild_only=True,
    )
    @describe(query="What you want to learn how to do")
    async def wikihow(self, ctx: Context, *, query: str) -> None:
        query_encoded = urllib.parse.quote(query)
        embed = discord.Embed(
            title="WikiHow",
            description=f"[How to {query}?](https://www.wikihow.com/wikiHowTo?search={query_encoded})",
            color=color.base,
        )
        await ctx.send(embed=embed)

    @hybrid(
        name="brainly",
        description="Search Brainly for answers",
        guild_only=True,
    )
    @describe(query="Question to search for")
    async def brainly(self, ctx: Context, *, query: str) -> None:
        query_encoded = urllib.parse.quote(query)
        embed = discord.Embed(
            title="Brainly",
            description=f"[Search for **{query}** on Brainly](https://brainly.com/app/ask?q={query_encoded})",
            color=color.base,
        )
        await ctx.send(embed=embed)

    @hybrid(
        name="rps",
        description="Play Rock-Paper-Scissors with me!",
        aliases=["rockpaperscissors"],
        guild_only=True,
    )
    @describe(choice="rock, paper, or scissors")
    async def rps(self, ctx: Context, *, choice: str) -> None:
        choice = choice.lower().strip()
        if choice not in ("rock", "paper", "scissors"):
            return await ctx.fail("Choose `rock`, `paper`, or `scissors`.")

        bot_choice = random.choice(["rock", "paper", "scissors"])
        emojis_map = {"rock": "🪨", "paper": "📄", "scissors": "✂️"}

        if choice == bot_choice:
            result = "It's a tie!"
        elif (choice == "rock" and bot_choice == "scissors") or \
             (choice == "paper" and bot_choice == "rock") or \
             (choice == "scissors" and bot_choice == "paper"):
            result = "You win!"
        else:
            result = "I win!"

        embed = discord.Embed(
            title="Rock Paper Scissors",
            description=f"{emojis_map[choice]} **You:** {choice.title()}\n{emojis_map[bot_choice]} **Bot:** {bot_choice.title()}\n\n**{result}**",
            color=color.base,
        )
        await ctx.send(embed=embed)

    @hybrid(
        name="wouldyourather",
        description="Would you rather?",
        aliases=["wyr"],
        guild_only=True,
    )
    @describe(option1="First option", option2="Second option")
    async def wouldyourather(self, ctx: Context, option1: str, option2: str) -> None:
        embed = discord.Embed(
            title="Would You Rather?",
            description=f"**1:** {option1}\n**2:** {option2}",
            color=color.base,
        )
        msg = await ctx.send(embed=embed)
        await msg.add_reaction("1️⃣")
        await msg.add_reaction("2️⃣")

    @hybrid(
        name="quote",
        description="Quote a message",
        guild_only=True,
    )
    @describe(message_link="Message link to quote")
    async def quote(self, ctx: Context, message_link: str) -> None:
        try:
            msg = await ctx.bot.fetch_message(message_link)
        except Exception:
            return await ctx.fail("Could not fetch that message.")

        embed = discord.Embed(
            description=msg.content[:4000],
            color=color.base,
            timestamp=msg.created_at,
        )
        embed.set_author(name=str(msg.author), icon_url=msg.author.display_avatar.url)
        embed.set_footer(text=f"Quoted from #{msg.channel.name}")
        await ctx.send(embed=embed)


async def setup(bot: commands.Bot):
    await bot.add_cog(Fun(bot))
