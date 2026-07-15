"""custom bot context with helpers.
extends commands.Context with send shortcuts and cache.
use ctx.success ctx.fail ctx.warn for quick replies"""

from __future__ import annotations

import asyncio
from typing import Any, Optional

import discord
from discord.ext import commands

from core.managers.app_emojis import format_embed_emoji
from core.managers.values import color, emojis, lastfm_color, lastfm_color
from core.tools.aesthetic import (
    body,
    embed_to_layout,
    embeds_to_layout,
    layout_from_components,
    view_has_interactive_controls,
)


class Cache:
    """lightweight in memory key value cache.
    supports ttl expiry and set operations.
    stores per bot instance"""

    def __init__(self, bot=None) -> None:
        self.bot = bot
        self._data: dict = {}
        self._futures: dict = {}

    async def _expire(self, key: str, ttl: int) -> None:
        await asyncio.sleep(ttl)
        self._data.pop(key, None)

    async def set(self, key: Any, value: Any, ttl: Optional[int] = None) -> int:
        self._data[key] = value
        if ttl is not None:
            if key in self._futures:
                self._futures[key].cancel()
            self._futures[key] = asyncio.ensure_future(self._expire(key, ttl))
        return 1

    async def get(self, key: Any) -> Any:
        return self._data.get(key)

    async def delete(self, key: Any) -> int:
        self._data.pop(key, None)
        return 1

    async def sadd(self, key: Any, *values: Any) -> int:
        if key not in self._data:
            self._data[key] = set()
        assert isinstance(self._data[key], set), "key is a set"
        added = {v for v in values if v not in self._data[key]}
        self._data[key].update(added)
        return len(added)

    async def smembers(self, key: Any):
        return self._data.get(key, set())

    async def ratelimited(self, key: str, limit: int, window: int) -> Optional[float]:
        """simple in memory rate limit check"""
        import time
        now = time.time()
        bucket = self._data.setdefault(f"rl:{key}", [])
        bucket[:] = [t for t in bucket if now - t < window]
        if len(bucket) >= limit:
            return window - (now - bucket[0])
        bucket.append(now)
        return None


class Context(commands.Context):
    """extended bot context with reply helpers.
    adds success fail warn and embed shortcuts.
    also tracks flags for parsed command args"""

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.flags: dict[str, Any] = {}
        self._custom_emoji: dict | None = None
        self._custom_color: dict | None = None

    
    
    
    

    @property
    def color(self) -> int:
        return self.bot.color

    async def _get_emoji(self, key: str) -> str:
        """Get emoji with guild/user customization override"""
        if self._custom_emoji is None:
            try:
                self._custom_emoji = await self.bot.db.get_emoji(
                    self.guild.id if self.guild else None,
                    self.author.id if self.guild else None,
                )
            except Exception:
                self._custom_emoji = {
                    "success": emojis.approve,
                    "warn": emojis.warn,
                    "deny": emojis.deny,
                    "cooldown": emojis.cooldown,
                    "loading": emojis.loading,
                    "info": emojis.interface.information,
                }
        raw = self._custom_emoji.get(key, getattr(emojis, key, emojis.approve))
        return format_embed_emoji(self.bot, raw, fallback_key=key)

    async def _get_color(self, key: str) -> int:
        """Get color with guild/user customization override"""
        if self._custom_color is None:
            try:
                self._custom_color = await self.bot.db.get_color(
                    self.guild.id if self.guild else 0,
                    self.author.id if self.guild else None,
                )
            except Exception:
                self._custom_color = {
                    "base": color.base,
                    "approve": color.approve,
                    "warn": color.warn,
                    "deny": color.deny,
                    "cooldown": color.cooldown,
                    "settings": color.settings,
                    "dark": color.dark,
                }
        return self._custom_color.get(key, getattr(color, key, color.base))

    def _strip_self_mention(self, message: str) -> str:
        text = str(message or "").strip()
        mention = str(getattr(self.author, "mention", "")).strip()
        if mention and text.startswith(mention):
            text = text[len(mention):].lstrip()
            if text.startswith(":"):
                text = text[1:].lstrip()
        return text

    def _message_embed(
        self,
        message: str,
        *,
        emoji: str = "",
        color_value: Optional[int] = None,
    ) -> discord.Embed:
        
        prefix = f"{emoji} " if emoji else ""
        line = f"{prefix}**{self.author.display_name}**: {message}"
        return discord.Embed(
            color=color_value or self.bot.color,
            description=body(line),
        )

    async def _send_embed_response(
        self,
        embed: discord.Embed,
        *,
        return_embed: bool = False,
        **kwargs,
    ):
        if return_embed:
            return embed
        kwargs.setdefault("mention_author", False)
        return await self.reply(embed=embed, **kwargs)

    async def success(self, message: str, **kw):
        """send a success reply with vain styling"""
        emoji = await self._get_emoji("success")
        color_value = await self._get_color("approve")
        return await self._send_embed_response(
            self._message_embed(
                self._strip_self_mention(message),
                emoji=emoji,
                color_value=color_value,
            ),
            **kw,
        )

    async def fail(self, message: str, **kw):
        """send a failure reply with vain styling"""
        emoji = await self._get_emoji("deny")
        color_value = await self._get_color("deny")
        return await self._send_embed_response(
            self._message_embed(
                self._strip_self_mention(message),
                emoji=emoji,
                color_value=color_value,
            ),
            **kw,
        )

    async def warn(self, message: str, **kw):
        """send a warning reply with vain styling"""
        emoji = await self._get_emoji("warn")
        color_value = await self._get_color("warn")
        return await self._send_embed_response(
            self._message_embed(
                self._strip_self_mention(message),
                emoji=emoji,
                color_value=color_value,
            ),
            **kw,
        )

    async def cooldown(self, message: str, **kw):
        """send a cooldown reply with vain styling"""
        emoji = await self._get_emoji("cooldown")
        color_value = await self._get_color("cooldown")
        return await self._send_embed_response(
            self._message_embed(
                self._strip_self_mention(message),
                emoji=emoji,
                color_value=color_value,
            ),
            **kw,
        )

    async def warning(self, message: str, **kw):
        """legacy alias for warn"""
        return await self.warn(message, **kw)

    async def normal(self, message: str, *, emoji: str = "", **kw):
        """send a neutral informational reply"""
        return await self._send_embed_response(
            self._message_embed(self._strip_self_mention(message), emoji=emoji),
            **kw,
        )

    async def info(self, message: str, **kw):
        """send an informational reply using vain's info emoji."""
        emoji = await self._get_emoji("info")
        return await self.normal(message, emoji=emoji, **kw)

    async def lastfm(self, message: str, **kw):
        """send a compact Last.fm reply with vain styling."""
        try:
            color_value = discord.Color.from_str(lastfm_color.value)
        except ValueError:
            color_value = discord.Color(0xBBA0D2)

        return await self._send_embed_response(
            self._message_embed(
                self._strip_self_mention(message),
                emoji=emojis.lastfm,
                color_value=color_value.value,
            ),
            **kw,
        )

    async def search(self, message: str, **kw):
        """send a search-style informational reply"""
        return await self.normal(message, emoji="🔎", **kw)

    deny = fail

    async def send(
        self,
        content: Optional[str] = None,
        *,
        tts: bool = False,
        embed: Optional[discord.Embed] = None,
        embeds: Optional[list[discord.Embed]] = None,
        file: Optional[discord.File] = None,
        files: Optional[list[discord.File]] = None,
        stickers: Any = None,
        delete_after: Optional[float] = None,
        nonce: Any = None,
        allowed_mentions: Optional[discord.AllowedMentions] = None,
        reference: Any = None,
        mention_author: Optional[bool] = None,
        view: Optional[discord.ui.View | discord.ui.LayoutView] = None,
        suppress_embeds: bool = False,
        ephemeral: bool = False,
        silent: bool = False,
        poll: Any = None,
        components: Any = None,
        flags: Any = None,
        raw_embed: bool = False,
        log: bool = False,
        **kwargs: Any,
    ) -> discord.Message:
        """Send a message.

        Supports Components V2 via ``components=`` (list of Containers/Items) or
        ``view=LayoutView``. By default, classic embeds are auto-converted into
        V2 containers with dividers so live bot replies look consistent.

        Pass ``raw_embed=True`` or ``log=True`` to keep a classic embed (logs).
        Classic interactive ``View``s (buttons/selects) keep embeds as-is so
        callbacks keep working.
        """
        
        kwargs.pop("flags", None)
        if flags is not None:
            
            pass

        base_kw: dict[str, Any] = {
            "tts": tts,
            "delete_after": delete_after,
            "nonce": nonce,
            "allowed_mentions": allowed_mentions,
            "reference": reference,
            "mention_author": mention_author,
            "suppress_embeds": suppress_embeds,
            "ephemeral": ephemeral,
            "silent": silent,
        }
        if stickers is not None:
            base_kw["stickers"] = stickers
        if poll is not None:
            base_kw["poll"] = poll
        
        base_kw = {k: v for k, v in base_kw.items() if v is not None}
        base_kw.update(kwargs)

        file_list: list[discord.File] = []
        if file is not None:
            file_list.append(file)
        if files:
            file_list.extend(list(files))

        
        if components is not None:
            layout = layout_from_components(components)
            send_kw = dict(base_kw)
            
            send_kw.pop("suppress_embeds", None)
            if len(file_list) == 1:
                send_kw["file"] = file_list[0]
            elif file_list:
                send_kw["files"] = file_list
            return await super().send(view=layout, **send_kw)

        
        if isinstance(view, discord.ui.LayoutView):
            send_kw = dict(base_kw)
            send_kw.pop("suppress_embeds", None)
            if len(file_list) == 1:
                send_kw["file"] = file_list[0]
            elif file_list:
                send_kw["files"] = file_list
            
            return await super().send(view=view, **send_kw)

        
        should_container = (
            not raw_embed
            and not log
            and not view_has_interactive_controls(view)
            and (embed is not None or embeds)
        )
        if should_container:
            try:
                if embed is not None and not embeds:
                    layout = embed_to_layout(
                        embed,
                        view=view if isinstance(view, discord.ui.View) else None,
                        attachment_files=file_list or None,
                    )
                else:
                    layout = embeds_to_layout(list(embeds or []))
                send_kw = dict(base_kw)
                send_kw.pop("suppress_embeds", None)
                if len(file_list) == 1:
                    send_kw["file"] = file_list[0]
                elif file_list:
                    send_kw["files"] = file_list
                
                return await super().send(view=layout, **send_kw)
            except Exception:
                
                pass

        send_kw = dict(base_kw)
        if embed is not None:
            send_kw["embed"] = embed
        if embeds is not None:
            send_kw["embeds"] = embeds
        if view is not None:
            send_kw["view"] = view
        if len(file_list) == 1:
            send_kw["file"] = file_list[0]
        elif file_list:
            send_kw["files"] = file_list
        return await super().send(content=content, **send_kw)

    async def send_embed(self, code: str, **kw) -> discord.Message:
        """parse embed script and send it"""
        return await self.bot.send_embed(self, code, **kw)

    async def send_help(self, *args: Any):
        """route help requests through vain's custom help handler"""
        help_handler = getattr(self.bot, "_vain_help", None)
        if help_handler is not None:
            entity = args[0] if args else self.command
            if isinstance(entity, str):
                entity = self.bot.get_command(entity)
            if entity is not None:
                owner = self.author.id in self.bot.owners
                if isinstance(entity, commands.Group):
                    family = help_handler._family_targets(
                        self.bot,
                        entity,
                        owner=owner,
                    )
                    subs = [target for target in family if target is not entity]
                    if subs:
                        return await help_handler._send_group(
                            self,  
                            entity,
                            targets=family,
                        )
                return await help_handler.send_brief(self, entity)
            return await help_handler.invoke(self, None)
        return await super().send_help(*args)

    async def paginate(self, *args, **kw) -> discord.Message:
        """send paginated embeds or build pages from lines"""
        from core.tools.pages import Paginator, build_pages

        if len(args) == 1:
            pages = args[0]
        elif len(args) == 2 and isinstance(args[0], discord.Embed):
            split = kw.pop("split", 10)
            pages = build_pages(args[0], args[1], split=split)
        else:
            raise TypeError("paginate expects a page list or an embed with lines")

        p = Paginator(self, pages, **kw)
        return await p.start()
