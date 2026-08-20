from __future__ import annotations

import contextlib

import random
import re
import urllib.parse
from typing import TYPE_CHECKING, Optional

import aiohttp
import discord
from discord.ext import commands

from uwuipy import Uwuipy

from core.discord.package import Package
from core.discord.ctx import Context
from core.discord.hybrid import command, describe, hybrid, linked_family
from core.discord.views.paginate import send_pages
from core.discord.views.embed import panel_container
from config import color, emojis

from .games import start_connect4, start_rps, start_ttt
from .improper.wyr import WyrView
from .improper.search import (
    build_ddg_search_pages,
    build_image_search_pages,
    fetch_ddg_results,
    fetch_image_results,
)
from .improper.ttt_stats import (
    build_leaderboard_pages,
    build_stats_embed,
    default_leaderboard_scope,
    fetch_ttt_stats,
    leaderboard_rows,
    scope_ids,
)

from core.discord.views.embed import compose, body, c2, panel_container

if TYPE_CHECKING:
    from core.vain import Vain

_CONTEXTS = dict(guilds=True, dms=True, groupchats=True)


def _split_wyr_options(raw: str) -> tuple[str | None, str | None]:
    """Split ``wyr a or b`` or ``wyr a, b`` into two options."""
    text = str(raw or "").strip()
    if not text:
        return None, None
    parts = re.split(r"\s+(?:or)\s+|\s*,\s*", text, maxsplit=1, flags=re.IGNORECASE)
    if len(parts) != 2:
        return None, None
    opt1 = parts[0].strip()
    opt2 = parts[1].strip()
    if not opt1 or not opt2:
        return None, None
    return opt1, opt2

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

    @command(
        name="8ball",
        description="ask the magic 8-ball a question",
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
        embed = panel_container(
            title="🎱 Magic 8-Ball",
            color=color.base,
            lines=[f"**Question:** {question}", f"**Answer:** {response}"],
        )
        await ctx.send(embed=embed)

    @hybrid(
        name="roll",
        description="roll a dice",
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
        
        embed = panel_container(
            title="🎲 Dice Roll",
            color=color.base,
            lines=[f"**Results:** {', '.join(map(str, results))}", f"**Total:** {total}"],
        )
        await ctx.send(embed=embed)

    @hybrid(
        name="flip",
        description="flip a coin",
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

    @command(
        name="choose",
        description="choose from a list of options",
    )
    @describe(options="Options to choose from (separated by commas)")
    async def choose(self, ctx: Context, *, options: str) -> None:
        """Choose from a list of options."""
        choices = [opt.strip() for opt in options.split(",")]
        if len(choices) < 2:
            return await ctx.warn("Please provide at least 2 options")
        
        result = random.choice(choices)
        embed = panel_container(
            title="🎯 Random Choice",
            color=color.base,
            lines=[f"**Options:** {', '.join(choices)}", f"**Chosen:** {result}"],
        )
        await ctx.send(embed=embed)

    @command(
        name="rate",
        description="rate something out of 10",
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

    @command(
        name="uwuify",
        description="uwuify your text",
        aliases=["uwu"],
        example=",uwuify hello world",
    )
    @describe(text="Text to uwuify")
    async def uwuify(self, ctx: Context, *, text: str) -> None:
        """Uwuify your text."""
        try:
            result = Uwuipy().uwuify(text)
        except Exception:
            return await ctx.fail("Failed to uwuify that text")
        if not result:
            return await ctx.warn("I couldn't uwuify that")
        result = result[:2000]
        await ctx.send(content=result)

    @hybrid(
        name="banner",
        description="view a user's banner",
        aliases=["userbanner"],
        guilds=True,
        dms=True,
        groupchats=True,
    )
    @describe(user="user whose banner to view")
    async def banner(self, ctx: Context, user: discord.User = None) -> None:
        target = user or ctx.author
        try:
            fetched = await self.bot.fetch_user(target.id)
        except (discord.NotFound, discord.HTTPException):
            return await ctx.warn("could not fetch that user")

        if not fetched.banner:
            return await ctx.warn(f"{target.mention} doesn't have a banner")

        url = str(fetched.banner.replace(size=4096).url)
        from discord import ui as _ui
        from core.discord.ctx import layout_from_items
        container = _ui.Container()
        for attr in ("accent_color", "accent_colour"):
            if hasattr(container, attr):
                with contextlib.suppress(Exception):
                    setattr(container, attr, None)
        container.add_item(_ui.TextDisplay(f"**{fetched.name}'s banner**"))
        try:
            container.add_item(_ui.MediaGallery(discord.MediaGalleryItem(url)))
        except Exception:
            container.add_item(_ui.TextDisplay(f"[open banner]({url})"))
        view = layout_from_items([container], timeout=None)
        await ctx.send(view=view)

    @command(
        name="ship",
        description="ship two people together",
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

        embed = panel_container(
            title="💕 Ship Calculator",
            color=color.base,
            lines=[
                f"**{member1.display_name}** ❤️ **{member2.display_name}**",
                f"**Ship Name:** {ship_name}",
                f"**Compatibility:** {compatibility}% ❤️",
                match_line,
            ],
        )
        await ctx.send(embed=embed)

    @hybrid(
        name="fact",
        description="get a random fun fact",
    )
    async def fact(self, ctx: Context) -> None:
        """Get a random fun fact."""
        fact = None
        apis = [
            "https://uselessfacts.jsph.pl/api/v2/facts/random?language=en",
            "https://api.aaronstevens.com/funfacts",
            "https://factsapi.io/api/facts/random",
        ]
        for api_url in apis:
            try:
                async with aiohttp.ClientSession() as session:
                    async with session.get(api_url, timeout=aiohttp.ClientTimeout(total=5)) as resp:
                        if resp.status == 200:
                            data = await resp.json()
                            if api_url.startswith("https://uselessfacts"):
                                fact = data.get("text")
                            elif api_url.startswith("https://api.aaronstevens"):
                                fact = data.get("fact")
                            elif api_url.startswith("https://factsapi"):
                                fact = data.get("fact", {}).get("fact") or data.get("fact")
                            if fact:
                                break
            except Exception:
                continue
        if not fact:
            fallback = [
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
            fact = random.choice(fallback)
        embed = c2(
            title="Fun Fact",
            color=color.base,
            message=fact,
            timestamp=False,
        )
        await ctx.send(embed=embed)

    @hybrid(
        name="joke",
        description="get a random joke",
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
        name="duckduckgo",
        description="search the duckduckgo search engine",
        aliases=["ddg"],
        example=",duckduckgo how to get a girlfriend",
        **_CONTEXTS,
    )
    @describe(search="Search query")
    async def duckduckgo(self, ctx: Context, *, search: str) -> None:
        await self._run_ddg_search(ctx, search)

    @hybrid(
        name="duckduckgoimage",
        description="search duckduckgo for an image",
        aliases=["ddgim", "ddgimg", "duckduckgoimages"],
        example=",duckduckgoimage cats",
        **_CONTEXTS,
    )
    @describe(search="Search query")
    async def duckduckgoimage(self, ctx: Context, *, search: str) -> None:
        await self._run_image_search(ctx, search, source="duckduckgo")

    @hybrid(
        name="googleimages",
        description="search google for an image",
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
        description="reverse image search on google",
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
        description="search google for an image",
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
        description="search giphy for gif results",
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

    @command(
        name="wikihow",
        description="how to...?",
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

    @command(
        name="brainly",
        description="search brainly for answers",
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
        description="search for song lyrics",
        guilds=True,
        dms=True,
        groupchats=True,
    )
    @describe(query="Artist and song title (leave empty to detect from your status)")
    async def lyrics(self, ctx: Context, *, query: str = None) -> None:
        import sys
        if sys.version_info < (3, 11):
            import typing
            if not hasattr(typing, "Self"):
                typing.Self = None

        import lyricsgenius

        genius = lyricsgenius.Genius(
            "fs6QAbNhqF0VmAMb4p4FWAZ7TqjKKCcvu-8BOlNwKTJgdVoPr8qd-Mo1AuyJiYuu",
            remove_section_headers=False,
        )

        if not query:
            query = None
            
            member = ctx.author
            activities = list(getattr(member, "activities", None) or ())
            primary = getattr(member, "activity", None)
            if primary is not None and primary not in activities:
                activities.insert(0, primary)
            for act in activities:
                if isinstance(act, discord.Spotify):
                    query = f"{act.title} {act.artist}"
                    break

            
            if not query:
                try:
                    from core.networks.lastfm import LastFM
                    from ext.lastfm.settings import Settings as LfmSettings

                    lfm_data = await LfmSettings.get_user(self.bot, ctx.author.id)
                    if lfm_data:
                        username = lfm_data.get("lastfm_username") if isinstance(lfm_data, dict) else None
                        if not username and isinstance(lfm_data, str):
                            username = lfm_data
                        if username:
                            lfm = LastFM()
                            tracks = await lfm.recent_tracks(username, limit=1)
                            if tracks:
                                track = tracks[0]
                                track_name = track.get("name", "")
                                artist_name = track.get("artist", {}).get("#text") or ""
                                if track_name and artist_name:
                                    query = f"{track_name} {artist_name}"
                except Exception:
                    pass

            
            if not query:
                return await ctx.warn(
                    "I **can't** see your profile because it is private\n"
                    "> -# search a query instead or connect your lastfm"
                )

        async with ctx.typing():
            try:
                song = await self.bot.loop.run_in_executor(
                    None, lambda: genius.search_song(query)
                )
            except Exception:
                return await ctx.warn("Could not search for lyrics.")

            if not song or not song.lyrics:
                return await ctx.warn("No lyrics found for that track.")

            lyrics_text = song.lyrics.strip()
            title = song.title or query
            artist = song.artist or ""
            track_url = song.url or ""

            section_pattern = re.compile(r"(\[.*?\])")
            parts = section_pattern.split(lyrics_text)

            organized_sections = []
            current_section = ""
            current_header = ""
            for part in parts:
                if section_pattern.match(part):
                    if current_section:
                        organized_sections.append((current_header, current_section.strip()))
                    current_header = part
                    current_section = ""
                else:
                    current_section += part
            if current_section:
                organized_sections.append((current_header, current_section.strip()))

            if not organized_sections:
                organized_sections = [("", lyrics_text)]

            pages = []
            for i, (header, content) in enumerate(organized_sections, 1):
                section_text = f"{header}\n{content}" if header else content
                embed = panel_container(
                    title=title,
                    url=track_url,
                    lines=[f"```yaml\n{section_text}```"],
                    author=artist,
                    footer=f"{i}/{len(organized_sections)}",
                )
                pages.append(embed)

            await ctx.paginator(pages)

    @hybrid(
        name="rockpaperscissors",
        description="play rock paper scissors with another member or the bot",
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
        description="play tic-tac-toe with somebody!",
        aliases=["ttt", "tic-tac-toe"],
        example=",tictactoe jonathan",
        **_CONTEXTS,
    )
    @describe(member="Opponent (leave empty to play the bot)")
    async def tictactoe(self, ctx: Context, member: Optional[discord.User] = None) -> None:
        await self._ttt_play(ctx, member)

    @hybrid(
        name="tictactoestatistics",
        description="view tic-tac-toe statistics of a member",
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
        description="view the most tic-tac-toe wins",
        example=",tictactoe leaderboard",
        **_CONTEXTS,
    )
    @linked_family("tictactoe", help_name="tictactoe leaderboard")
    @describe(scope="global, guild, or group (defaults by context)")
    async def tictactoeleaderboard(self, ctx: Context, scope: Optional[str] = None) -> None:
        await self._ttt_leaderboard(ctx, scope)

    @hybrid(
        name="connect4",
        description="play connect four with another member or the bot",
        aliases=["4inarow", "connectfour", "c4"],
        guilds=True,
        dms=True,
        groupchats=True,
    )
    @describe(member="Opponent (leave empty to play the bot)")
    async def connect4(self, ctx, member: Optional[discord.User] = None) -> None:
        await start_connect4(ctx, opponent=member, vs_me=member is None)

    @command(
        name="wouldyourather",
        description="would you rather?",
        aliases=["wyr"],
        **_CONTEXTS,
    )
    @describe(options="Option 1 or Option 2 (split with `or` or a comma)")
    async def wouldyourather(self, ctx: Context, *, options: str) -> None:
        option1, option2 = _split_wyr_options(options)
        if option1 is None:
            return await ctx.warn(f"expected: {ctx.cmd('wyr option1 or option2')}")

        embed = panel_container(
            title="Would You Rather?",
            color=color.base,
            lines=[f"**1:** {option1}", f"**2:** {option2}"],
        )
        if ctx.guild is None:
            view = WyrView(ctx, option1, option2)
            view.message = await ctx.send(embed=embed, view=view)
            return

        me = ctx.guild.me or ctx.guild.get_member(ctx.bot.user.id)
        if me is None or not me.guild_permissions.manage_messages:
            return await ctx.warn("I need **Manage Messages** permission in this server.")

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
