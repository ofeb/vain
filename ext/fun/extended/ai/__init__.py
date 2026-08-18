from __future__ import annotations

import asyncio
import contextlib
import io
import re
from typing import TYPE_CHECKING

import aiohttp
import discord
from discord import app_commands
from discord.ext import commands

from config import color
from core.discord.ctx import Context
from core.discord.hybrid import describe, hybrid
from core.discord.package import Package
from core.discord.views.embed import c2, panel_embed
from core.networks.gemini import GeminiClient
from core.networks import ocr as ocr_net
from core.tools import image_ops

if TYPE_CHECKING:
    from core.vain import Vain

_LANG = re.compile(r"^[a-zA-Z]{2}(?:-[a-zA-Z]{2})?$")
_CONTEXTS = dict(guilds=True, dms=True, groupchats=True)


def _chunk_text(text: str, size: int = 1800) -> list[str]:
    text = text or ""
    if len(text) <= size:
        return [text]
    chunks: list[str] = []
    while text:
        chunks.append(text[:size])
        text = text[size:]
    return chunks


def _is_voice_attachment(att: discord.Attachment) -> bool:
    try:
        if hasattr(att, "is_voice_message") and callable(att.is_voice_message):
            if att.is_voice_message():
                return True
    except Exception:
        pass
    if getattr(att, "duration", None) is not None and getattr(att, "waveform", None) is not None:
        return True
    ctype = (att.content_type or "").lower()
    name = (att.filename or "").lower()
    if ctype.startswith("audio/") or name.endswith((".ogg", ".mp3", ".wav", ".m4a", ".webm")):
        return True
    return False


class AI(Package):
    """Ask, translate, transcribe, OCR, and related context menus."""

    def __init__(self, bot: Vain):
        super().__init__(bot)
        self._menus: list[app_commands.ContextMenu] = []
        self._register_menus()

    def _register_menus(self) -> None:
        menus = [
            app_commands.ContextMenu(name="Quote this message", callback=self.ctx_quote),
            app_commands.ContextMenu(name="Translate this message", callback=self.ctx_translate),
            app_commands.ContextMenu(name="Transcribe this message", callback=self.ctx_transcribe),
            app_commands.ContextMenu(name="Extract Text (OCR)", callback=self.ctx_ocr),
        ]
        for menu in menus:
            try:
                self.bot.tree.add_command(menu)
                self._menus.append(menu)
            except Exception:
                pass

    async def cog_unload(self) -> None:
        for menu in self._menus:
            with contextlib.suppress(Exception):
                self.bot.tree.remove_command(menu.name, type=menu.type)
        self._menus.clear()

    def _gemini(self) -> GeminiClient:
        return GeminiClient()

    async def _ctx_to_context(self, interaction: discord.Interaction) -> Context:
        return await self.bot.get_context(interaction, cls=Context)

    async def ctx_quote(self, interaction: discord.Interaction, message: discord.Message) -> None:
        await interaction.response.defer(thinking=True)
        if not (message.content or "").strip():
            await interaction.followup.send("That message has no text to quote.", ephemeral=True)
            return
        cog = self.bot.get_cog("Manipulation")
        if cog is None or not hasattr(cog, "_generate_quote_image"):
            await interaction.followup.send("Quote is unavailable right now.", ephemeral=True)
            return
        try:
            avatar_url = str(message.author.display_avatar.with_size(512).url)
            image_data = await cog._generate_quote_image(
                message.clean_content,
                message.author.display_name,
                message.author.name,
                avatar_url,
            )
            gif_data = await asyncio.to_thread(image_ops.pil_to_gif, image_data)
            file = discord.File(io.BytesIO(gif_data), filename="quote.gif")
            await interaction.followup.send(file=file)
            image_data = gif_data
            if interaction.guild is not None and hasattr(cog, "_get_quote_channel"):
                dest_id = await cog._get_quote_channel(interaction.guild.id)
                if dest_id and dest_id != getattr(interaction.channel, "id", None):
                    dest = interaction.guild.get_channel(dest_id)
                    if dest is not None and hasattr(dest, "send"):
                        from ext.fun.extended.manipulation import _QuoteChannelView
                        view = _QuoteChannelView(
                            jump_url=message.jump_url,
                            author_id=interaction.user.id,
                        )
                        with contextlib.suppress(Exception):
                            await dest.send(
                                content=(
                                    f"{message.author.mention} · "
                                    f"[Jump to message]({message.jump_url})"
                                ),
                                file=discord.File(io.BytesIO(image_data), filename="quote.gif"),
                                view=view,
                                allowed_mentions=discord.AllowedMentions(users=False),
                            )
        except Exception as exc:
            await interaction.followup.send(f"Couldn't quote that: {exc}", ephemeral=True)

    async def ctx_translate(self, interaction: discord.Interaction, message: discord.Message) -> None:
        await interaction.response.defer(thinking=True)
        text = (message.content or "").strip()
        if not text:
            await interaction.followup.send("That message has no text to translate.", ephemeral=True)
            return
        try:
            out = await self._gemini().translate(text, to_lang="en")
        except Exception as exc:
            await interaction.followup.send(f"Translate failed: {exc}", ephemeral=True)
            return
        embed = panel_embed(
            title="Translate",
            author=str(message.author),
            author_icon=message.author.display_avatar.url,
            lines=[
                f"**Original**\n{text[:900]}",
                f"**English**\n{out[:900] or '*empty*'}",
            ],
            footer="→ English",
            timestamp=False,
        )
        await interaction.followup.send(embed=embed)

    async def ctx_transcribe(self, interaction: discord.Interaction, message: discord.Message) -> None:
        await interaction.response.defer(thinking=True)
        voice = None
        for att in message.attachments:
            if _is_voice_attachment(att):
                voice = att
                break
        if voice is None:
            await interaction.followup.send("No voice message on that message.", ephemeral=True)
            return
        try:
            audio = await voice.read()
            text = await self._gemini().transcribe_audio(
                audio, mime_type=voice.content_type or "audio/ogg"
            )
        except Exception as exc:
            await interaction.followup.send(f"Transcribe failed: {exc}", ephemeral=True)
            return
        embed = panel_embed(
            title="Transcript",
            author=str(message.author),
            author_icon=message.author.display_avatar.url,
            lines=[text[:3500] or "*empty transcript*"],
            footer="voice message",
            timestamp=False,
        )
        await interaction.followup.send(embed=embed)

    async def ctx_ocr(self, interaction: discord.Interaction, message: discord.Message) -> None:
        await interaction.response.defer(thinking=True)
        image = None
        for att in message.attachments:
            ctype = (att.content_type or "").lower()
            name = (att.filename or "").lower()
            if ctype.startswith("image/") or name.endswith((".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp")):
                image = att
                break
        if image is None:
            for emb in message.embeds:
                u = getattr(getattr(emb, "image", None), "url", None) or getattr(
                    getattr(emb, "thumbnail", None), "url", None
                )
                if u:
                    try:
                        timeout = aiohttp.ClientTimeout(total=20)
                        async with aiohttp.ClientSession(timeout=timeout) as session:
                            async with session.get(u) as resp:
                                if resp.status == 200:
                                    data = await resp.read()
                                    text = await ocr_net.ocr_image(data, filename="embed.png")
                                    embed = panel_embed(
                                        title="Extracted text",
                                        author=str(message.author),
                                        author_icon=message.author.display_avatar.url,
                                        lines=[text[:3500] or "*no text found*"],
                                        footer="OCR",
                                        timestamp=False,
                                    )
                                    await interaction.followup.send(embed=embed)
                                    return
                    except Exception as exc:
                        await interaction.followup.send(f"OCR failed: {exc}", ephemeral=True)
                        return
            await interaction.followup.send("No image found on that message.", ephemeral=True)
            return
        try:
            data = await image.read()
            text = await ocr_net.ocr_image(data, filename=image.filename or "image.png")
        except Exception as exc:
            await interaction.followup.send(f"OCR failed: {exc}", ephemeral=True)
            return
        embed = panel_embed(
            title="Extracted text",
            author=str(message.author),
            author_icon=message.author.display_avatar.url,
            lines=[text[:3500] or "*no text found*"],
            footer="OCR",
            timestamp=False,
        )
        await interaction.followup.send(embed=embed)

    @hybrid(
        name="ask",
        aliases=["chatgpt", "gemini", "gpt", "ai"],
        description="Ask a question and get results from AI",
        example=",ask what colors make up purple",
        **_CONTEXTS,
    )
    @describe(question="Your question")
    async def ask(self, ctx: Context, *, question: str) -> None:
        if not question or not question.strip():
            return await ctx.warn("Ask something")
        async with ctx.typing():
            try:
                answer = await self._gemini().prompt(question.strip())
            except Exception as exc:
                return await ctx.fail(f"AI request failed\n> -# {exc}")
        if not answer:
            return await ctx.warn("No response from AI")
        qshow = question.strip()
        if len(qshow) > 80:
            qshow = qshow[:77] + "..."
        pages = _chunk_text(answer, 1800)
        embeds = []
        for i, chunk in enumerate(pages):
            emb = panel_embed(
                title=f"Answer · {qshow}",
                author=str(ctx.author),
                author_icon=ctx.author.display_avatar.url,
                lines=[chunk],
                footer=f"Gemini · {i + 1}/{len(pages)}" if len(pages) > 1 else "Gemini",
                timestamp=False,
            )
            embeds.append(emb)
        if len(embeds) == 1:
            return await ctx.send(embed=embeds[0])
        return await ctx.paginate(embeds)

    @hybrid(
        name="translate",
        aliases=["tr"],
        description="Translate text or a replied message",
        example=",tr es hello",
        **_CONTEXTS,
    )
    @describe(payload="Language codes and/or text")
    async def translate(self, ctx: Context, *, payload: str = None) -> None:
        text = None
        to_lang = "en"
        from_lang = None

        tokens = (payload or "").split()
        if tokens and _LANG.match(tokens[0]):
            if len(tokens) >= 2 and _LANG.match(tokens[1]):
                from_lang = tokens[0].lower()
                to_lang = tokens[1].lower()
                text = " ".join(tokens[2:]).strip() or None
            else:
                to_lang = tokens[0].lower()
                text = " ".join(tokens[1:]).strip() or None

        if text is None:
            if ctx.message and ctx.message.reference:
                ref = ctx.message.reference.resolved
                if not isinstance(ref, discord.Message):
                    try:
                        ref = await ctx.channel.fetch_message(ctx.message.reference.message_id)
                    except Exception:
                        ref = None
                if isinstance(ref, discord.Message) and (ref.content or "").strip():
                    text = ref.content.strip()
            if text is None and tokens and not _LANG.match(tokens[0]):
                text = payload.strip() if payload else None

        if not text:
            return await ctx.warn(
                f"Provide text or reply to a message\n> -# **usage:** {ctx.cmd('tr es')} · {ctx.cmd('tr es en hola')}"
            )

        async with ctx.typing():
            try:
                out = await self._gemini().translate(text, to_lang=to_lang, from_lang=from_lang)
            except Exception as exc:
                return await ctx.fail(f"Translate failed\n> -# {exc}")

        if not out:
            return await ctx.warn("Empty translation")

        src_label = from_lang or "auto"
        embed = panel_embed(
            title="Translate",
            author=str(ctx.author),
            author_icon=ctx.author.display_avatar.url,
            lines=[
                f"**{src_label} → {to_lang}**",
                out[:3500],
            ],
            footer=f"{src_label} → {to_lang}",
            timestamp=False,
        )
        return await ctx.send(embed=embed)

    @hybrid(
        name="transcribe",
        description="Transcribe a Discord voice message",
        example=",transcribe",
        **_CONTEXTS,
    )
    @describe(message="Message with a voice attachment")
    async def transcribe(self, ctx: Context, message: discord.Message = None) -> None:
        voice = None
        source = None

        candidates: list[discord.Message] = []
        if message is not None:
            candidates.append(message)
        if ctx.message and ctx.message.reference:
            ref = ctx.message.reference.resolved
            if not isinstance(ref, discord.Message):
                try:
                    ref = await ctx.channel.fetch_message(ctx.message.reference.message_id)
                except Exception:
                    ref = None
            if isinstance(ref, discord.Message):
                candidates.append(ref)

        for msg in candidates:
            for att in msg.attachments:
                if _is_voice_attachment(att):
                    voice = att
                    source = msg
                    break
            if voice:
                break

        if voice is None and ctx.channel is not None:
            skip = ctx.message.id if ctx.message else None
            try:
                async for past in ctx.channel.history(limit=50):
                    if skip and past.id == skip:
                        continue
                    for att in past.attachments:
                        if _is_voice_attachment(att):
                            voice = att
                            source = past
                            break
                    if voice:
                        break
            except Exception:
                pass

        if voice is None or source is None:
            return await ctx.warn(
                f"No voice message found\n> -# **usage:** reply to a voice memo or run {ctx.cmd('transcribe')}"
            )

        async with ctx.typing():
            try:
                audio = await voice.read()
                text = await self._gemini().transcribe_audio(
                    audio, mime_type=voice.content_type or "audio/ogg"
                )
            except Exception as exc:
                return await ctx.fail(f"Transcribe failed\n> -# {exc}")

        embed = panel_embed(
            title="Transcript",
            author=str(source.author),
            author_icon=source.author.display_avatar.url,
            lines=[text[:3500] or "*empty transcript*"],
            footer="voice message",
            timestamp=False,
        )
        try:
            return await ctx.reply(embed=embed, mention_author=False)
        except Exception:
            return await ctx.send(embed=embed)

    @hybrid(
        name="ocr",
        aliases=["extracttext", "readimage"],
        description="Extract text from an image (OCR)",
        example=",ocr",
        **_CONTEXTS,
    )
    async def ocr(self, ctx: Context) -> None:
        data = None
        filename = "image.png"
        if ctx.message and ctx.message.attachments:
            att = ctx.message.attachments[0]
            data = await att.read()
            filename = att.filename or filename
        elif ctx.message and ctx.message.reference:
            try:
                ref = ctx.message.reference.resolved
                if not isinstance(ref, discord.Message):
                    ref = await ctx.channel.fetch_message(ctx.message.reference.message_id)
                if ref.attachments:
                    att = ref.attachments[0]
                    data = await att.read()
                    filename = att.filename or filename
                else:
                    for emb in ref.embeds:
                        u = getattr(getattr(emb, "image", None), "url", None)
                        if u:
                            timeout = aiohttp.ClientTimeout(total=20)
                            async with aiohttp.ClientSession(timeout=timeout) as session:
                                async with session.get(u) as resp:
                                    if resp.status == 200:
                                        data = await resp.read()
                            break
            except Exception:
                data = None

        if data is None:
            return await ctx.warn("Attach or reply to an image")

        async with ctx.typing():
            try:
                text = await ocr_net.ocr_image(data, filename=filename)
            except Exception as exc:
                return await ctx.fail(f"OCR failed\n> -# {exc}")

        embed = panel_embed(
            title="Extracted text",
            author=str(ctx.author),
            author_icon=ctx.author.display_avatar.url,
            lines=[text[:3500] or "*no text found*"],
            footer="OCR",
            timestamp=False,
        )
        return await ctx.send(embed=embed)


async def setup(bot: Vain) -> None:
    await bot.add_cog(AI(bot))
