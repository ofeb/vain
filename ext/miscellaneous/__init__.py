from __future__ import annotations

import asyncio
import datetime
import json
import random
from typing import TYPE_CHECKING, Optional

import aiohttp
import discord
from discord.ext import commands

from core.discord.ctx import Context
from core.discord.hybrid import describe, hybrid, group
from core.discord.package import Package

from .events import MiscellaneousEvents
from config import color
from ..information.improper.lookup import GOOGLE_FOOTER_ICON

from core.discord.views.embed import compose, body, caption, c2

if TYPE_CHECKING:
    from core.vain import Vain

class Miscellaneous(MiscellaneousEvents, Package):
    def __init__(self, bot: Vain):
        super().__init__(bot)
        self.active_polls: list[dict] = []
    @hybrid(
        name="ping",
        description="Check the bot's response time",
    )
    async def ping(self, ctx: Context) -> None:
        latency = round(self.bot.latency * 1000)
        await ctx.success(f"Pong! **{latency}ms**")

    @hybrid(
        name="uptime",
        description="Check how long the bot has been online",
    )
    async def uptime(self, ctx: Context) -> None:
        now = discord.utils.utcnow()
        delta = now - self.bot.started_at
        hours, remainder = divmod(int(delta.total_seconds()), 3600)
        minutes, seconds = divmod(remainder, 60)
        embed = c2(
            title="Uptime",
            color=color.base,
            message=f"**{hours}h {minutes}m {seconds}s**",
            timestamp=False,
        )
        await ctx.send(embed=embed)

    @hybrid(
        name="invite",
        description="Get the bot's invite link",
    )
    async def invite(self, ctx: Context) -> None:
        bot_id = self.bot.user.id if self.bot.user else "0"
        embed = c2(
            title="Invite Vain",
            color=color.base,
            message="Use the buttons to invite me or join the support server!",
            timestamp=False,
        )
        view = discord.ui.View()
        view.add_item(discord.ui.Button(
            label="Invite",
            style=discord.ButtonStyle.link,
            url=f"https://discord.com/oauth2/authorize?client_id={bot_id}&permissions=8&scope=bot%20applications.commands",
        ))
        view.add_item(discord.ui.Button(
            label="Support",
            style=discord.ButtonStyle.link,
            url=self.bot.support if hasattr(self.bot, 'support') else "https://discord.gg/vains",
        ))
        await ctx.send(embed=embed, view=view)

    @hybrid(
        name="poll",
        description="Create a poll with upvote and downvote reactions",
    )
    @describe(question="The poll question")
    async def poll(self, ctx: Context, *, question: str) -> None:
        embed = c2(
            title="Poll",
            color=color.base,
            message=question,
            footer=f"Started by {ctx.author.display_name}",
            timestamp=False,
        )
        msg = await ctx.send(embed=embed)
        await msg.add_reaction("👍")
        await msg.add_reaction("👎")

    @hybrid(
        name="quickpoll",
        description="Add upvote/downvote reactions to a message",
    )
    @describe(message_id="ID of the message to add reactions to")
    async def quickpoll(self, ctx: Context, message_id: str) -> None:
        try:
            msg = await ctx.channel.fetch_message(int(message_id))
        except (ValueError, discord.NotFound, discord.Forbidden):
            await ctx.fail("Could not find that message.")
            return

        await msg.add_reaction("👍")
        await msg.add_reaction("👎")
        await ctx.success("Added reactions to that message.")

    @hybrid(
        name="avatar",
        description="View a user's avatar",
        aliases=["av"],
        guilds=True,
        dms=True,
        groupchats=True,
    )
    @describe(user="User whose avatar to view")
    async def avatar(self, ctx: Context, *, user: discord.User = None) -> None:
        user = user or ctx.author
        embed = c2(
            title=f"{user.display_name}'s avatar",
            color=color.base,
            message="",
            timestamp=False,
        )
        embed.set_image(url=user.display_avatar.url)
        await ctx.send(embed=embed)

    @hybrid(
        name="translate",
        description="Translate text to another language",
        aliases=["tr"],
        usage="(language) (text)",
        example="es hello world",
        guilds=True,
        dms=True,
        groupchats=True,
    )
    @describe(
        language="Target language code (e.g., en, es, fr, de, ja, ko, zh)",
        text="Text to translate",
    )
    async def translate(self, ctx: Context, language: str = None, *, text: str = None) -> None:
        """Translate text to another language using Google Translate."""
        lang_codes = {
            "af": "Afrikaans", "sq": "Albanian", "am": "Amharic", "ar": "Arabic",
            "hy": "Armenian", "az": "Azerbaijani", "eu": "Basque", "be": "Belarusian",
            "bn": "Bengali", "bs": "Bosnian", "bg": "Bulgarian", "ca": "Catalan",
            "ceb": "Cebuano", "zh": "Chinese (Simplified)", "zh-tw": "Chinese (Traditional)",
            "co": "Corsican", "hr": "Croatian", "cs": "Czech", "da": "Danish",
            "nl": "Dutch", "en": "English", "eo": "Esperanto", "et": "Estonian",
            "fi": "Finnish", "fr": "French", "fy": "Frisian", "gl": "Galician",
            "ka": "Georgian", "de": "German", "el": "Greek", "gu": "Gujarati",
            "ht": "Haitian Creole", "ha": "Hausa", "haw": "Hawaiian", "he": "Hebrew",
            "hi": "Hindi", "hmn": "Hmong", "hu": "Hungarian", "is": "Icelandic",
            "ig": "Igbo", "id": "Indonesian", "ga": "Irish", "it": "Italian",
            "ja": "Japanese", "jv": "Javanese", "kn": "Kannada", "kk": "Kazakh",
            "km": "Khmer", "rw": "Kinyarwanda", "ko": "Korean", "ku": "Kurdish",
            "ky": "Kyrgyz", "lo": "Lao", "la": "Latin", "lv": "Latvian",
            "lt": "Lithuanian", "lb": "Luxembourgish", "mk": "Macedonian",
            "mg": "Malagasy", "ms": "Malay", "ml": "Malayalam", "mt": "Maltese",
            "mi": "Maori", "mr": "Marathi", "mn": "Mongolian", "my": "Myanmar",
            "ne": "Nepali", "no": "Norwegian", "ny": "Chichewa", "or": "Odia",
            "ps": "Pashto", "fa": "Persian", "pl": "Polish", "pt": "Portuguese",
            "pa": "Punjabi", "ro": "Romanian", "ru": "Russian", "sm": "Samoan",
            "gd": "Scots Gaelic", "sr": "Serbian", "st": "Sesotho", "sn": "Shona",
            "sd": "Sindhi", "si": "Sinhala", "sk": "Slovak", "sl": "Slovenian",
            "so": "Somali", "es": "Spanish", "su": "Sundanese", "sw": "Swahili",
            "sv": "Swedish", "tl": "Filipino", "tg": "Tajik", "ta": "Tamil",
            "tt": "Tatar", "te": "Telugu", "th": "Thai", "tr": "Turkish",
            "tk": "Turkmen", "uk": "Ukrainian", "ur": "Urdu", "ug": "Uyghur",
            "uz": "Uzbek", "vi": "Vietnamese", "cy": "Welsh", "xh": "Xhosa",
            "yi": "Yiddish", "yo": "Yoruba", "zu": "Zulu",
        }

        if language is None:
            return await ctx.send_help()

        if language.lower() == "list":
            lines = [f"`{code}` - {name}" for code, name in sorted(lang_codes.items())]
            embed = c2(
                title="Supported Languages",
                message="\n".join(lines),
                footer=f"Use {ctx.clean_prefix}translate <language> <text> to translate",
                timestamp=False,
            )
            return await ctx.send(embed=embed)

        if text is None:
            return await ctx.send_help()

        lang_lower = language.lower()
        if lang_lower not in lang_codes:
            await ctx.warn(
                f"Invalid language code `{language}`. Use `{ctx.clean_prefix}translate list` to see all supported languages."
            )
            return

        try:
            async with aiohttp.ClientSession() as session:
                params = {
                    "client": "gtx",
                    "sl": "auto",
                    "tl": lang_lower,
                    "dt": "t",
                    "q": text,
                }
                async with session.get(
                    "https://translate.googleapis.com/translate_a/single",
                    params=params,
                ) as resp:
                    if resp.status != 200:
                        await ctx.fail("Translation service is currently unavailable.")
                        return
                    data = await resp.json(content_type=None)

            translated = "".join(part[0] for part in data[0] if part[0])
            detected_lang = data[2] if len(data) > 2 else "auto"
            detected_name = lang_codes.get(detected_lang, detected_lang.title())
            target_name = lang_codes[lang_lower]

            embed = c2(
                title=f"Translated from {detected_name} to {target_name}",
                message=f"```{translated[:1000]}```",
                author=ctx.author.display_name,
                footer="Google Translate",
                timestamp=False,
            )
            await ctx.send(embed=embed)

        except Exception as e:
            await ctx.fail(f"Translation failed: {str(e)[:100]}")

    @hybrid(
        name="userinfo",
        description="View information about a user",
        aliases=["ui", "whois"],
    )
    @describe(user="User to get info about")
    async def userinfo(self, ctx: Context, *, user: discord.Member = None) -> None:
        user = user or ctx.author
        roles = [r.mention for r in user.roles if r != ctx.guild.default_role] if ctx.guild else []
        lines = [
            f"**ID:** `{user.id}`",
            f"**Created:** {discord.utils.format_dt(user.created_at, style='D')} ({discord.utils.format_dt(user.created_at, style='R')})",
        ]
        joined = getattr(user, "joined_at", None)
        if joined:
            lines.append(
                f"**Joined:** {discord.utils.format_dt(joined, style='D')} ({discord.utils.format_dt(joined, style='R')})"
            )
        lines.append(f"**Roles ({len(roles)}):** {' '.join(roles[:20]) if roles else 'None'}")
        embed = c2(
            title=f"{user.display_name} ({user})",
            message="\n".join(lines),
            timestamp=False,
        )
        embed.set_thumbnail(url=user.display_avatar.url)
        await ctx.send(embed=embed)

    @hybrid(
        name="color",
        description="Show a hex codes color in an embed",
        aliases=["colour"],
    )
    @describe(hex="Hex color code (e.g. #FF0000)")
    async def color_cmd(self, ctx: Context, *, hex: str) -> None:
        hex_clean = hex.strip().lstrip("#")
        try:
            color_val = int(hex_clean, 16)
        except ValueError:
            return await ctx.warn("Invalid hex color code.")

        embed = c2(
            title=f"Color: #{hex_clean.upper()}",
            color=color_val,
            message="",
            timestamp=False,
        )
        embed.set_thumbnail(url=f"https://singlecolorimage.com/get/{hex_clean}/200x200")
        await ctx.send(embed=embed)

    @hybrid(
        name="charinfo",
        description="Get information about a character/symbol",
    )
    @describe(characters="Characters to get info about")
    async def charinfo(self, ctx: Context, *, characters: str) -> None:
        entries = []
        for char in characters[:10]:
            code = f"U+{ord(char):04X}"
            entries.append(f"`{char}` - {code} - {char.name if hasattr(char, 'name') and char.name else 'character'}")
        embed = c2(
            title="Character Info",
            message="\n".join(entries),
            timestamp=False,
        )
        await ctx.send(embed=embed)

    @hybrid(
        name="randomhex",
        description="Generate a random hex (color)",
    )
    async def randomhex(self, ctx: Context) -> None:
        hex_val = f"{random.randint(0, 0xFFFFFF):06x}"
        embed = c2(
            title="Random Hex Color",
            message=f"#{hex_val.upper()}",
            timestamp=False,
        )
        embed.set_thumbnail(url=f"https://singlecolorimage.com/get/{hex_val}/200x200")
        await ctx.send(embed=embed)

    @hybrid(
        name="jumbo",
        description="Enlarge an emoji",
        aliases=["e", "enlarge", "enlargen"],
    )
    @describe(emoji="Emoji to enlarge")
    async def jumbo(self, ctx: Context, *, emoji: str) -> None:
        import re
        match = re.match(r"<(a?):(\w+):(\d+)>", emoji)
        if not match:
            return await ctx.warn("Provide a valid custom emoji.")

        animated = match.group(1) == "a"
        ext = "gif" if animated else "png"
        emoji_id = match.group(3)
        url = f"https://cdn.discordapp.com/emojis/{emoji_id}.{ext}?size=256"

        embed = c2(
            title=match.group(2),
            color=color.base,
            message="",
            timestamp=False,
        )
        embed.set_image(url=url)
        await ctx.send(embed=embed)

    @group(
        name="addemote",
        description="Downloads emote and adds to server",
        aliases=["adde"],
    )
    @describe(emoji="Emoji or URL", characters="Name for the emote")
    async def addemote(self, ctx: Context, emoji: str, *, characters: str = None) -> None:
        import re
        match = re.match(r"<(a?):(\w+):(\d+)>", emoji)
        if match:
            ext = "gif" if match.group(1) == "a" else "png"
            url = f"https://cdn.discordapp.com/emojis/{match.group(3)}.{ext}"
            name = characters or match.group(2)
        elif emoji.startswith("http"):
            url = emoji
            name = characters or "emote"
        else:
            return await ctx.warn("Provide a valid emoji or image URL.")

        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(url) as resp:
                    if resp.status != 200:
                        return await ctx.fail("Could not download the image.")
                    data = await resp.read()
            emote = await ctx.guild.create_custom_emoji(name=name, image=data)
            await ctx.success(f"Created emoji {emote}")
        except discord.Forbidden:
            await ctx.warn("I **don't** have permission to manage emojis.")
        except Exception as e:
            await ctx.fail(f"Failed: {str(e)[:100]}")
async def setup(bot: Vain):
    await bot.add_cog(Miscellaneous(bot))
