from __future__ import annotations

import random
import re
import urllib.parse
from typing import TYPE_CHECKING, Optional

import aiohttp
import discord
from discord.ext import commands

from core.discord.package import Package
from core.discord.ctx import Context
from core.discord.hybrid import hybrid, describe, linked_family
from core.discord.views.paginate import send_pages
from config import color, emojis

from .games import start_connect4, start_rps, start_ttt
from .proper.search import (
    build_ddg_search_pages,
    build_image_search_pages,
    fetch_ddg_results,
    fetch_image_results,
)
from .proper.ttt_stats import (
    build_leaderboard_pages,
    build_stats_embed,
    default_leaderboard_scope,
    fetch_ttt_stats,
    leaderboard_rows,
    scope_ids,
)

from core.discord.views.embed import compose, body, c2

if TYPE_CHECKING:
    from core.vain import Vain

_CONTEXTS = dict(guilds=True, dms=True, groupchats=True)

class Fun(Package):
    """Fun commands and games."""

    async def _ttt_play(self, ctx: Context, member: Optional[discord.User] = None) -> None:
        await start_ttt(ctx, opponent=member, vs_me=member is None)

    async def _ttt_statistics(self, ctx: Context, member: Optional[discord.User] = None) -> None:
        target = member or ctx.author
        stats = await fetch_ttt_stats(self.bot.db, target.id)
        await ctx.send(embed=build_stats_embed(target, stats))

    async def _ttt_leaderboard(self, ctx: Context, scope: Optional[str] = None) -> None:
        selected = (scope or default_leaderboard_scope(ctx.channel)).strip().lower()
        if selected not in {"global", "guild", "group"}:
            return await ctx.warn("Scope must be **global**, **guild**, or **group**.")
        if selected == "guild" and ctx.guild is None:
            return await ctx.warn("Guild leaderboard can only be used in a server.")
        if selected == "group" and scope_ids(ctx.channel, ctx.guild)[1] is None:
            return await ctx.warn("Group leaderboard can only be used in a group chat.")
        rows = await leaderboard_rows(
            self.bot.db,
            ctx.channel,
            ctx.guild,
            scope=selected,
        )
        title = "Most Tic-Tac-Toe wins"
        pages = await build_leaderboard_pages(
            self.bot,
            rows=rows,
            author=ctx.author,
            title=title,
        )
        if not rows:
            await ctx.send(embed=pages[0])
            return
        await send_pages(ctx, pages)

    @hybrid(
        name="8ball",
        description="Ask the magic 8-ball a question",
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
            "**don't** count on it.",
            "My reply is no.",
            "My sources say no.",
            "Outlook not so good.",
            "Very doubtful.",
        ]
        response = random.choice(responses)
        embed = discord.Embed(
            title="🎱 Magic 8-Ball",
            color=color.base,
            description=compose(
                body(f"**Question:** {question}", f"**Answer:** {response}"),
            ),
        )
        await ctx.send(embed=embed)

    @hybrid(
        name="roll",
        description="Roll a dice",
    )
    @describe(sides="Number of sides on the dice (default 6)", count="Number of dice to roll (default 1)")
    async def roll(self, ctx: Context, sides: int = 6, count: int = 1) -> None:
        """Roll a dice."""
        if sides < 2 or sides > 100:
            return await ctx.warn("Sides must be between 2 and 100")
        if count < 1 or count > 10:
            return await ctx.warn("Count must be between 1 and 10")
        
        results = [random.randint(1, sides) for _ in range(count)]
        total = sum(results)
        
        embed = discord.Embed(
            title="🎲 Dice Roll",
            color=color.base,
            description=compose(
                body(
                    f"**Results:** {', '.join(map(str, results))}",
                    f"**Total:** {total}",
                ),
            ),
        )
        await ctx.send(embed=embed)

    @hybrid(
        name="flip",
        description="Flip a coin",
    )
    async def flip(self, ctx: Context) -> None:
        """Flip a coin."""
        result = random.choice(["Heads", "Tails"])
        embed = c2(
            title="🪙 Coin Flip",
            color=color.base,
            message=f"**Result:** {result}",
            timestamp=False,
        )
        await ctx.send(embed=embed)

    @hybrid(
        name="choose",
        description="Choose from a list of options",
    )
    @describe(options="Options to choose from (separated by commas)")
    async def choose(self, ctx: Context, *, options: str) -> None:
        """Choose from a list of options."""
        choices = [opt.strip() for opt in options.split(",")]
        if len(choices) < 2:
            return await ctx.warn("Please provide at least 2 options")
        
        result = random.choice(choices)
        embed = discord.Embed(
            title="🎯 Random Choice",
            color=color.base,
            description=compose(
                body(f"**Options:** {', '.join(choices)}", f"**Chosen:** {result}"),
            ),
        )
        await ctx.send(embed=embed)

    @hybrid(
        name="rate",
        description="Rate something out of 10",
    )
    @describe(thing="Thing to rate")
    async def rate(self, ctx: Context, *, thing: str) -> None:
        """Rate something out of 10."""
        rating = random.randint(1, 10)
        embed = c2(
            title="⭐ Rating",
            color=color.base,
            message=f"**{thing}** gets a **{rating}/10**",
            timestamp=False,
        )
        await ctx.send(embed=embed)

    @hybrid(
        name="banner",
        description="Get a user's banner",
        aliases=["userbanner"],
        guilds=True,
        dms=True,
        groupchats=True,
    )
    @describe(user="User to get banner from (defaults to you)")
    async def banner(self, ctx: Context, user: discord.User = None) -> None:
        """Get a user's banner (works with mentions, IDs, and DMs)."""
        target = user or ctx.author
        try:
            fetched = await self.bot.fetch_user(target.id)
        except (discord.NotFound, discord.HTTPException):
            return await ctx.warn("could not fetch that user")

        if not fetched.banner:
            return await ctx.warn(f"{target.mention} doesn't have a banner")

        embed = c2(
            title=f"{fetched.display_name}'s banner",
            color=color.base,
            message="",
            timestamp=False,
        )
        embed.set_image(url=fetched.banner.url)
        await ctx.send(embed=embed)

    @hybrid(
        name="ship",
        description="Ship two people together",
    )
    @describe(member1="First member", member2="Second member (defaults to you)")
    async def ship(self, ctx: Context, member1: discord.Member, member2: discord.Member = None) -> None:
        """Ship two people together."""
        member2 = member2 or ctx.author
        
        if member1 == member2:
            return await ctx.warn("You **can't** ship someone with themselves!")
        
        combined_id = str(member1.id + member2.id)
        compatibility = int(combined_id[-2:]) % 100 + 1
        
        ship_name = f"{member1.display_name[:len(member1.display_name)//2]}{member2.display_name[len(member2.display_name)//2:]}"
        
        if compatibility >= 80:
            match_line = "🌟 Perfect match!"
        elif compatibility >= 60:
            match_line = "✨ Great match!"
        elif compatibility >= 40:
            match_line = "💫 Could work!"
        else:
            match_line = "💔 Not a great match..."

        embed = discord.Embed(
            title="💕 Ship Calculator",
            color=color.base,
            description=compose(
                body(
                    f"**{member1.display_name}** ❤️ **{member2.display_name}**",
                    f"**Ship Name:** {ship_name}",
                    f"**Compatibility:** {compatibility}% ❤️",
                    match_line,
                ),
            ),
        )
        await ctx.send(embed=embed)

    @hybrid(
        name="fact",
        description="Get a random fun fact",
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
        embed = c2(
            title="🎉 Fun Fact",
            color=color.base,
            message=random.choice(facts),
            timestamp=False,
        )
        await ctx.send(embed=embed)

    @hybrid(
        name="joke",
        description="Get a random joke",
    )
    async def joke(self, ctx: Context) -> None:
        """Get a random joke."""
        jokes = [
            "Why **don't** scientists trust atoms? Because they make up everything!",
            "Why did the scarecrow win an award? Because he was outstanding in his field!",
            "I told my wife she was drawing her eyebrows too high. She looked surprised.",
            "Why **don't** eggs tell jokes? They'd crack each other up!",
            "What do you call a fake noodle? An impasta!",
            "Why did the bicycle fall over? Because it was two-tired!",
            "What do you call a bear with no teeth? A gummy bear!",
            "Why **can't** you give Elsa a balloon? Because she will let it go!",
            "What do you call a fish without eyes? A fsh!",
            "Why did the math book look so sad? Because it had too many problems!",
        ]
        embed = c2(
            title="😂 Joke",
            color=color.base,
            message=random.choice(jokes),
            timestamp=False,
        )
        await ctx.send(embed=embed)

    async def _run_ddg_search(self, ctx: Context, search: str) -> None:
        try:
            async with aiohttp.ClientSession() as session:
                results = await fetch_ddg_results(session, search)
            if not results:
                return await ctx.warn("No results found for that search.")
            pages = build_ddg_search_pages(results, ctx.author)
            await send_pages(ctx, pages)
        except aiohttp.ClientError:
            await ctx.fail("Could not reach DuckDuckGo.")

    async def _run_image_search(self, ctx: Context, search: str, *, source: str) -> None:
        try:
            async with aiohttp.ClientSession() as session:
                images = await fetch_image_results(session, search)
            if not images:
                return await ctx.warn("No images found for that search.")
            pages = build_image_search_pages(images, ctx.author, query=search, source=source)
            await send_pages(ctx, pages)
        except aiohttp.ClientError:
            await ctx.fail("Could not fetch image results.")

    @hybrid(
        name="google",
        description="Search the largest search engine on the internet",
        aliases=["g"],
        example=",google how to get a girlfriend",
        **_CONTEXTS,
    )
    @describe(search="Search query")
    @commands.cooldown(1, 5, commands.BucketType.user)
    async def google(self, ctx: Context, *, search: str) -> None:
        await self._run_ddg_search(ctx, search)

    @google.error
    async def google_error(self, ctx: Context, error: commands.CommandError) -> None:
        if isinstance(error, commands.CommandOnCooldown):
            await ctx.cooldown(
                f"Please wait **{error.retry_after:.2f} seconds** before using this command again"
            )

    @hybrid(
        name="duckduckgo",
        description="Search the DuckDuckGo search engine",
        aliases=["ddg"],
        example=",duckduckgo how to get a girlfriend",
        **_CONTEXTS,
    )
    @describe(search="Search query")
    async def duckduckgo(self, ctx: Context, *, search: str) -> None:
        await self._run_ddg_search(ctx, search)

    @hybrid(
        name="duckduckgoimage",
        description="Search DuckDuckGo for an image",
        aliases=["ddgim", "ddgimg", "duckduckgoimages"],
        example=",duckduckgoimage cats",
        **_CONTEXTS,
    )
    @describe(search="Search query")
    async def duckduckgoimage(self, ctx: Context, *, search: str) -> None:
        await self._run_image_search(ctx, search, source="duckduckgo")

    @hybrid(
        name="googleimages",
        description="Search Google for an image",
        aliases=["gimg", "googleimage", "gimages"],
        example=",googleimages cats",
        **_CONTEXTS,
    )
    @describe(search="Search query")
    @commands.cooldown(1, 5, commands.BucketType.user)
    async def googleimages(self, ctx: Context, *, search: str) -> None:
        await self._run_image_search(ctx, search, source="google")

    @googleimages.error
    async def googleimages_error(self, ctx: Context, error: commands.CommandError) -> None:
        if isinstance(error, commands.CommandOnCooldown):
            await ctx.cooldown(
                f"Please wait **{error.retry_after:.2f} seconds** before using this command again"
            )

    @hybrid(
        name="reverseimage",
        description="Reverse image search on Google",
        aliases=["rimage", "rimg"],
    )
    @describe(url="Image URL to reverse search")
    async def reverseimage(self, ctx: Context, url: str = None) -> None:
        if not url and ctx.message.attachments:
            url = ctx.message.attachments[0].url
        if not url:
            return await ctx.warn("Provide an image URL or attach an image.")

        query = urllib.parse.quote(url)
        embed = c2(
            title="Reverse Image Search",
            color=color.base,
            message=f"[Reverse search this image on Google](https://lens.google.com/uploadbyurl?url={query})",
            timestamp=False,
        )
        embed.set_thumbnail(url=url)
        await ctx.send(embed=embed)

    @hybrid(
        name="image",
        description="Search Google for an image",
        aliases=["im", "img"],
    )
    @describe(search="Search query")
    async def image(self, ctx: Context, *, search: str) -> None:
        query = urllib.parse.quote(search)
        embed = c2(
            title="Image Search",
            color=color.base,
            message=f"[Search for **{search}** images on Google](https://www.google.com/search?q={query}&tbm=isch)",
            timestamp=False,
        )
        await ctx.send(embed=embed)

    @hybrid(
        name="giphy",
        description="Search Giphy for gif results",
        aliases=["gif"],
    )
    @describe(keyword="Search keyword")
    async def giphy(self, ctx: Context, *, keyword: str) -> None:
        query = urllib.parse.quote(keyword)
        embed = c2(
            title="Giphy Search",
            color=color.base,
            message=f"[Search for **{keyword}** on Giphy](https://giphy.com/search/{query})",
            timestamp=False,
        )
        await ctx.send(embed=embed)

    @hybrid(
        name="tenor",
        description="Search Tenor for gif results",
    )
    @describe(keyword="Search keyword")
    async def tenor(self, ctx: Context, *, keyword: str) -> None:
        query = urllib.parse.quote(keyword)
        embed = c2(
            title="Tenor Search",
            color=color.base,
            message=f"[Search for **{keyword}** on Tenor](https://tenor.com/search/{query})",
            timestamp=False,
        )
        await ctx.send(embed=embed)

    @hybrid(
        name="wikihow",
        description="How to...?",
        aliases=["whow"],
    )
    @describe(query="What you want to learn how to do")
    async def wikihow(self, ctx: Context, *, query: str) -> None:
        query_encoded = urllib.parse.quote(query)
        embed = c2(
            title="WikiHow",
            color=color.base,
            message=f"[How to {query}?](https://www.wikihow.com/wikiHowTo?search={query_encoded})",
            timestamp=False,
        )
        await ctx.send(embed=embed)

    @hybrid(
        name="brainly",
        description="Search Brainly for answers",
    )
    @describe(query="Question to search for")
    async def brainly(self, ctx: Context, *, query: str) -> None:
        query_encoded = urllib.parse.quote(query)
        embed = c2(
            title="Brainly",
            color=color.base,
            message=f"[Search for **{query}** on Brainly](https://brainly.com/app/ask?q={query_encoded})",
            timestamp=False,
        )
        await ctx.send(embed=embed)

    @hybrid(
        name="lyrics",
        description="Search for song lyrics",
    )
    @describe(query="Artist and song title")
    async def lyrics(self, ctx: Context, *, query: str) -> None:
        artist, _, title = query.partition(" - ")
        if not title.strip():
            parts = query.rsplit(" ", 1)
            if len(parts) == 2:
                artist, title = parts[0], parts[1]
            else:
                artist, title = query, query
        url = f"https://api.lyrics.ovh/v1/{urllib.parse.quote(artist.strip())}/{urllib.parse.quote(title.strip())}"
        async with self.bot.session.get(url) as resp:
            if resp.status != 200:
                return await ctx.warn("Could not find lyrics for that track.")
            data = await resp.json()
        lyrics_text = data.get("lyrics")
        if not lyrics_text:
            return await ctx.warn("Could not find lyrics for that track.")
        embed = discord.Embed(
            title=f"{title.strip()} — {artist.strip()}",
            color=color.base,
            description=compose(body(lyrics_text[:4000])),
        )
        await ctx.send(embed=embed)

    @hybrid(
        name="rockpaperscissors",
        description="Play rock paper scissors with another member or the bot",
        aliases=["rps"],
        guilds=True,
        dms=True,
        groupchats=True,
    )
    @describe(member="Opponent (leave empty to play the bot)", rounds="Number of rounds (1-3)")
    async def rockpaperscissors(
        self,
        ctx,
        member: Optional[discord.User] = None,
        rounds: int = 1,
    ) -> None:
        if rounds < 1 or rounds > 3:
            return await ctx.warn("Rounds must be between **1** and **3**.")
        await start_rps(ctx, opponent=member, rounds=rounds, vs_me=member is None)

    @hybrid(
        name="tictactoe",
        description="Play tic-tac-toe with somebody!",
        aliases=["ttt", "tic-tac-toe"],
        example=",tictactoe jonathan",
        **_CONTEXTS,
    )
    @describe(member="Opponent (leave empty to play the bot)")
    async def tictactoe(self, ctx: Context, member: Optional[discord.User] = None) -> None:
        await self._ttt_play(ctx, member)

    @hybrid(
        name="tictactoestatistics",
        description="View tic-tac-toe statistics of a member",
        example=",tictactoe statistics jonathan",
        **_CONTEXTS,
    )
    @linked_family("tictactoe", help_name="tictactoe statistics")
    @describe(member="Member to view (defaults to you)")
    async def tictactoestatistics(
        self,
        ctx: Context,
        member: Optional[discord.User] = None,
    ) -> None:
        await self._ttt_statistics(ctx, member)

    @hybrid(
        name="tictactoeleaderboard",
        description="View the most tic-tac-toe wins",
        example=",tictactoe leaderboard",
        **_CONTEXTS,
    )
    @linked_family("tictactoe", help_name="tictactoe leaderboard")
    @describe(scope="global, guild, or group (defaults by context)")
    async def tictactoeleaderboard(self, ctx: Context, scope: Optional[str] = None) -> None:
        await self._ttt_leaderboard(ctx, scope)

    @hybrid(
        name="connect4",
        description="Play connect four with another member or the bot",
        aliases=["4inarow", "connectfour", "c4"],
        guilds=True,
        dms=True,
        groupchats=True,
    )
    @describe(member="Opponent (leave empty to play the bot)")
    async def connect4(self, ctx, member: Optional[discord.User] = None) -> None:
        await start_connect4(ctx, opponent=member, vs_me=member is None)

    @hybrid(
        name="wouldyourather",
        description="Would you rather?",
        aliases=["wyr"],
    )
    @describe(option1="First option", option2="Second option")
    async def wouldyourather(self, ctx: Context, option1: str, option2: str) -> None:
        if ctx.guild is None:
            return await ctx.warn("This command can only be used in a server.")
        me = ctx.guild.me or ctx.guild.get_member(ctx.bot.user.id)
        if me is None or not ctx.channel.permissions_for(me).add_reactions:
            return await ctx.warn("I need **Add Reactions** permission in this channel.")

        embed = discord.Embed(
            title="Would You Rather?",
            color=color.base,
            description=compose(body(f"**1:** {option1}", f"**2:** {option2}")),
        )
        msg = await ctx.send(embed=embed)
        try:
            await msg.add_reaction("1️⃣")
            await msg.add_reaction("2️⃣")
        except (discord.Forbidden, discord.HTTPException):
            await ctx.warn("Couldn't add reactions to the poll message.")

async def setup(bot: Vain):
    from .events import FunEvents

    await bot.add_cog(Fun(bot))
    await bot.add_cog(FunEvents(bot))
