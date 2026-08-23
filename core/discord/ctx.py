"""custom bot context with helpers.
extends commands.Context with send shortcuts and cache.
use ctx.success ctx.fail ctx.warn for quick replies"""

from __future__ import annotations

import contextlib

import asyncio
from typing import Any, Iterable, Optional, Sequence

import discord
from discord import ui
from discord.ext import commands

from core.managers.app_emojis import format_embed_emoji
from config import color, emojis, lastfm_color, lastfm_color

from core.discord.views.embed import body

def _link_buttons_from_view(view: ui.View | None) -> list[ui.Button]:
    if view is None or isinstance(view, ui.LayoutView):
        return []
    out: list[ui.Button] = []
    for child in getattr(view, "children", ()) or ():
        if isinstance(child, ui.Button) and getattr(child, "url", None):
            out.append(
                ui.Button(
                    style=child.style or discord.ButtonStyle.link,
                    label=child.label,
                    url=child.url,
                    emoji=child.emoji,
                    disabled=child.disabled,
                )
            )
    return out

def _accent_from_embed(embed: discord.Embed) -> int | None:
    colour = embed.colour or embed.color
    if colour is None:
        return None
    try:
        value = int(colour.value)
    except Exception:
        return None
    if value in (0, 0x000000):
        return None
    return value

def _blankish(value: str | None) -> bool:
    if value is None:
        return True
    text = str(value).strip()
    return not text or text in {"\u200b", "‎", "​"}

def embed_to_container(
    embed: discord.Embed,
    *,
    extra_rows: Sequence[ui.ActionRow] | None = None,
    attachment_files: Sequence[discord.File] | None = None,
) -> ui.Container:
    """Convert a rich embed into a Components V2 container that mirrors embed layout.

    Title, author, description, fields, image, and footer are preserved.
    No accent strip / embed colour - C2 cards stay neutral.
    """
    _ = _accent_from_embed(embed)
    container = ui.Container()
    for _attr in ("accent_color", "accent_colour"):
        if hasattr(container, _attr):
            with contextlib.suppress(Exception):
                setattr(container, _attr, None)

    author_name = embed.author.name if embed.author else None
    author_icon = embed.author.icon_url if embed.author else None
    thumb = embed.thumbnail.url if embed.thumbnail else None
    title = embed.title
    if title and embed.url:
        title_md = f"### [{title}]({embed.url})"
    elif title:
        title_md = f"### {title}"
    else:
        title_md = None

    header_bits: list[str] = []
    if author_name and not _blankish(author_name):
        header_bits.append(f"**{author_name}**")
    if title_md:
        header_bits.append(title_md)

    media_url = thumb or author_icon
    has_body = bool(embed.description and not _blankish(embed.description))
    has_fields = bool(embed.fields)
    image_url = embed.image.url if embed.image else None
    has_footer = bool(embed.footer and not _blankish(getattr(embed.footer, "text", None)))
    has_ts = bool(embed.timestamp)

    if header_bits and media_url:
        try:
            container.add_item(
                ui.Section(
                    ui.TextDisplay("\n".join(header_bits)),
                    accessory=ui.Thumbnail(media=str(media_url)),
                )
            )
        except Exception:
            container.add_item(ui.TextDisplay("\n".join(header_bits)))
    elif header_bits:
        container.add_item(ui.TextDisplay("\n".join(header_bits)))

    
    
    def _sep() -> None:
        container.add_item(ui.Separator(visible=True))

    added_content = bool(header_bits)

    if has_body:
        if added_content:
            _sep()
        container.add_item(ui.TextDisplay(str(embed.description)))
        added_content = True

    if has_fields:
        field_chunks: list[str] = []
        for field in embed.fields:
            name = "" if _blankish(field.name) else str(field.name)
            value = "" if _blankish(field.value) else str(field.value)
            if name and value:
                field_chunks.append(f"**{name}**\n{value}")
            elif value:
                field_chunks.append(value)
            elif name:
                field_chunks.append(f"**{name}**")
        if field_chunks:
            if added_content:
                _sep()
            container.add_item(ui.TextDisplay("\n\n".join(field_chunks)))
            added_content = True

    if image_url:
        if added_content:
            _sep()
        try:
            if str(image_url).startswith("attachment://") and attachment_files:
                fname = str(image_url).split("attachment://", 1)[-1]
                match = next((f for f in attachment_files if f.filename == fname), None)
                if match is not None:
                    container.add_item(ui.MediaGallery(discord.MediaGalleryItem(match)))
                else:
                    container.add_item(
                        ui.MediaGallery(discord.MediaGalleryItem(str(image_url)))
                    )
            else:
                container.add_item(
                    ui.MediaGallery(discord.MediaGalleryItem(str(image_url)))
                )
        except Exception:
            container.add_item(ui.TextDisplay(f"[image]({image_url})"))
        added_content = True

    if has_footer or has_ts:
        if added_content:
            _sep()
        footer = ""
        if has_footer:
            footer = str(embed.footer.text)
        if has_ts:
            try:
                from core.tools.human import discord_footer_date

                ts = discord_footer_date(embed.timestamp)
                footer = f"{footer} · {ts}" if footer else ts
            except Exception:
                pass
        if footer:
            container.add_item(ui.TextDisplay(f"-# {footer}"))
        added_content = True

    if extra_rows:
        if added_content:
            _sep()
        for row in extra_rows:
            container.add_item(row)

    return container

def layout_from_items(
    items: Iterable[ui.Item],
    *,
    timeout: float | None = 180,
) -> ui.LayoutView:
    layout = ui.LayoutView(timeout=timeout)
    for item in items:
        layout.add_item(item)
    return layout

def embed_to_layout(
    embed: discord.Embed,
    *,
    view: ui.View | None = None,
    attachment_files: Sequence[discord.File] | None = None,
    timeout: float | None = 180,
) -> ui.LayoutView:
    link_buttons = _link_buttons_from_view(view)
    extra_rows: list[ui.ActionRow] = []
    if link_buttons:
        
        for i in range(0, len(link_buttons), 5):
            row = ui.ActionRow(*link_buttons[i : i + 5])
            extra_rows.append(row)
    container = embed_to_container(
        embed,
        extra_rows=extra_rows or None,
        attachment_files=attachment_files,
    )
    return layout_from_items([container], timeout=timeout)

def embeds_to_layout(
    embeds: Sequence[discord.Embed],
    *,
    timeout: float | None = 180,
) -> ui.LayoutView:
    containers = [embed_to_container(e) for e in embeds]
    return layout_from_items(containers, timeout=timeout)

def layout_from_components(
    components: Sequence[Any] | Any,
    *,
    timeout: float | None = 180,
) -> ui.LayoutView:
    """Wrap Container / Item list into a LayoutView (for components= send kwarg)."""
    if isinstance(components, ui.LayoutView):
        return components
    if not isinstance(components, (list, tuple)):
        components = [components]
    return layout_from_items(components, timeout=timeout)

def view_has_interactive_controls(view: ui.View | ui.LayoutView | None) -> bool:
    """True when a classic View has buttons/selects that need the View dispatch path."""
    if view is None or isinstance(view, ui.LayoutView):
        return False
    for child in getattr(view, "children", ()) or ():
        if isinstance(child, ui.Select):
            return True
        if isinstance(child, ui.Button) and getattr(child, "url", None) is None:
            return True
    return False

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


    @property
    def invoke_prefix(self) -> str:
        """Prefix used by the user"""
        if getattr(self, "interaction", None) is not None:
            return "/"
        p = getattr(self, "clean_prefix", None)
        if p is None or p == "":
            p = getattr(self, "prefix", None)
        if isinstance(p, (list, tuple)):
            p = p[0] if p else ","
        if not p:
            p = ","
        return str(p)

    def cmd(self, invocation: str) -> str:
        """Format a command sample with the active prefix (or `/` for slash).

        Accepts bare names (``timezone set``) or already-prefixed strings
        (``,timezone set``, ``/timezone set``). Returns e.g. ``,timezone set``
        or ``/timezone set`` matching how the user invoked the bot.
        """
        inv = str(invocation or "").strip()
        for lead in ("/", ",", ";", "!", ".", "?"):
            if inv.startswith(lead):
                inv = inv[len(lead) :].lstrip()
                break
        return f"{self.invoke_prefix}{inv}"

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
        colored: bool = True,
    ) -> discord.Embed:
        """Build a compact status embed that becomes a C2 lookalike on send."""
        prefix = f"{emoji} " if emoji else ""
        line = f"{prefix}**{self.author.display_name}**: {message}"
        embed = discord.Embed(description=body(line))
        if colored and color_value is not None:
            embed.color = color_value
        elif colored:
            embed.color = color.base
        return embed

    async def _send_embed_response(
        self,
        embed: discord.Embed,
        *,
        return_embed: bool = False,
        raw_embed: bool = False,
        **kwargs,
    ):
        if return_embed:
            return embed
        kwargs.setdefault("mention_author", False)
        
        if raw_embed:
            kwargs["raw_embed"] = True

        try:
            return await self.send(embed=embed, **kwargs)
        except discord.NotFound:
            try:
                return await super().reply(embed=embed, **kwargs)
            except (discord.NotFound, discord.HTTPException):
                return None
        except discord.HTTPException:
            try:
                return await super().send(embed=embed, **kwargs)
            except (discord.NotFound, discord.HTTPException):
                return None

    async def success(self, message: str, **kw):
        """send a success reply with approve colour"""
        emoji = await self._get_emoji("success")
        return await self._send_embed_response(
            self._message_embed(
                self._strip_self_mention(message),
                emoji=emoji,
                color_value=None,
            ),
            **kw,
        )

    def _ephemeral_if_app(self, kw: dict) -> dict:
        if getattr(self, "interaction", None) is not None:
            kw.setdefault("ephemeral", True)
        return kw

    async def fail(self, message: str, **kw):
        """send a failure reply with deny colour"""
        kw = self._ephemeral_if_app(kw)
        emoji = await self._get_emoji("deny")
        return await self._send_embed_response(
            self._message_embed(
                self._strip_self_mention(message),
                emoji=emoji,
                color_value=None,
            ),
            **kw,
        )

    async def warn(self, message: str, **kw):
        """send a warning reply with warn colour"""
        kw = self._ephemeral_if_app(kw)
        emoji = await self._get_emoji("warn")
        return await self._send_embed_response(
            self._message_embed(
                self._strip_self_mention(message),
                emoji=emoji,
                color_value=None,
            ),
            **kw,
        )

    async def cooldown(self, message: str, **kw):
        """send a cooldown reply as a C2 embed lookalike"""
        kw = self._ephemeral_if_app(kw)
        emoji = await self._get_emoji("cooldown")
        return await self._send_embed_response(
            self._message_embed(
                self._strip_self_mention(message),
                emoji=emoji,
                color_value=None,
            ),
            **kw,
        )

    async def warning(self, message: str, **kw):
        """legacy alias for warn"""
        return await self.warn(message, **kw)

    async def normal(self, message: str, *, emoji: str = "", **kw):
        """send a neutral informational reply as a C2 embed lookalike"""
        return await self._send_embed_response(
            self._message_embed(
                self._strip_self_mention(message),
                emoji=emoji,
                color_value=await self._get_color("base"),
            ),
            **kw,
        )

    async def info(self, message: str, **kw):
        """send an informational reply using vain's info emoji."""
        emoji = await self._get_emoji("info")
        return await self.normal(message, emoji=emoji, **kw)

    async def lastfm(self, message: str, **kw):
        """send a compact Last.fm reply as a C2 embed lookalike."""
        return await self._send_embed_response(
            self._message_embed(
                self._strip_self_mention(message),
                emoji=emojis.lastfm,
                color_value=lastfm_color if isinstance(lastfm_color, int) else color.base,
            ),
            **kw,
        )

    async def search(self, message: str, **kw):
        """send a search-style informational reply"""
        return await self.normal(message, emoji="🔎", **kw)

    deny = fail


    async def _deliver(self, **send_kw):
        """Send to the current channel, then DM if the channel is gone."""
        try:
            return await super().send(**send_kw)
        except discord.NotFound as exc:
            code = getattr(getattr(exc, "code", None), "real", None) or getattr(exc, "code", None)
            text = str(exc)
            if "10003" not in text and code != 10003:
                raise
        except discord.HTTPException as exc:
            text = str(exc)
            if "10003" not in text and "Unknown Channel" not in text:
                raise
        
        dest = None
        author = getattr(self, "author", None)
        if author is not None:
            with contextlib.suppress(Exception):
                dest = author.dm_channel or await author.create_dm()
        if dest is None:
            return None
        send_kw.pop("reference", None)
        send_kw.pop("mention_author", None)
        with contextlib.suppress(discord.HTTPException, discord.Forbidden):
            return await dest.send(**send_kw)
        return None

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
            if content is not None and str(content).strip():
                content_kw = dict(send_kw)
                content_kw.pop("file", None)
                content_kw.pop("files", None)
                content_kw.pop("ephemeral", None)
                try:
                    await super().send(content=str(content), **content_kw)
                except Exception:
                    pass
            return await self._deliver(view=layout, **send_kw)


        if isinstance(view, discord.ui.LayoutView):
            send_kw = dict(base_kw)
            send_kw.pop("suppress_embeds", None)
            if len(file_list) == 1:
                send_kw["file"] = file_list[0]
            elif file_list:
                send_kw["files"] = file_list
            if content is not None and str(content).strip():
                content_kw = dict(send_kw)
                content_kw.pop("file", None)
                content_kw.pop("files", None)
                content_kw.pop("ephemeral", None)
                try:
                    await super().send(content=str(content), **content_kw)
                except Exception:
                    pass
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
                    with contextlib.suppress(Exception):
                        embed.color = None
                    layout = embed_to_layout(
                        embed,
                        view=view if isinstance(view, discord.ui.View) else None,
                        attachment_files=file_list or None,
                    )
                else:
                    for _e in list(embeds or []):
                        with contextlib.suppress(Exception):
                            _e.color = None
                    layout = embeds_to_layout(list(embeds or []))
                send_kw = dict(base_kw)
                send_kw.pop("suppress_embeds", None)
                if len(file_list) == 1:
                    send_kw["file"] = file_list[0]
                elif file_list:
                    send_kw["files"] = file_list
                if content is not None and str(content).strip():
                    content_kw = dict(send_kw)
                    content_kw.pop("file", None)
                    content_kw.pop("files", None)
                    content_kw.pop("ephemeral", None)
                    try:
                        await super().send(content=str(content), **content_kw)
                    except Exception:
                        pass
                return await self._deliver(view=layout, **send_kw)
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
        return await self._deliver(content=content, **send_kw)

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
