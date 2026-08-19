from __future__ import annotations

import asyncio
import re
from asyncio import create_task
from datetime import datetime, timezone, timedelta
from typing import List, Optional, Callable, Awaitable

import discord
from discord import Member, Message
from discord.ext import commands
from discord.ext.commands import (
    group,
    command,
    CommandError,
    MaxConcurrencyReached,
    BucketType,
    Context,
    MemberConverter,
)
from core.discord.package import Package
from core.managers.permissions import has_permissions

URL = re.compile(r"https?://[^\s]+")
BULK_DELETE_LIMIT = timedelta(days=14)
DEFAULT_AMOUNT = 30
SCAN_CAP = 1000


class Purge(Package):
    """purge management"""

    def __init__(self, bot):
        super().__init__(bot)
        self.tasks: dict[str, asyncio.Task] = {}

    @staticmethod
    def _clamp_amount(search: Optional[int]) -> int:
        if search is None:
            return DEFAULT_AMOUNT
        try:
            n = int(search)
        except (TypeError, ValueError):
            return DEFAULT_AMOUNT
        if n < 1:
            return DEFAULT_AMOUNT
        return min(n, SCAN_CAP)

    async def delete_messages(self, messages: List[Message]) -> int:
        if not messages:
            return 0

        async def _run(messages: List[Message]) -> None:
            channel = messages[0].channel
            now = datetime.now(timezone.utc)
            bulkable = [m for m in messages if (now - m.created_at) < BULK_DELETE_LIMIT]
            non_bulk = [m for m in messages if (now - m.created_at) >= BULK_DELETE_LIMIT]

            if bulkable:
                if len(bulkable) > 100:
                    for chunk in discord.utils.chunk_list(bulkable, 100):
                        await channel.delete_messages(chunk)
                        await asyncio.sleep(1)
                else:
                    await channel.delete_messages(bulkable)

            for message in non_bulk:
                await message.delete()

        key = f"purge-{messages[0].guild.id}"
        if self.tasks.get(key):
            raise MaxConcurrencyReached(1, BucketType.guild)
        task = create_task(_run(messages))
        self.tasks[key] = task
        try:
            await task
        finally:
            self.tasks.pop(key, None)
        return len(messages)

    def _with_invoke(self, ctx: Context, messages: List[Message]) -> List[Message]:
        out = list(messages)
        invoke_id = ctx.message.id
        if not any(getattr(m, "id", None) == invoke_id for m in out):
            out.append(ctx.message)
        return out

    async def _collect(
        self,
        ctx: Context,
        check: Callable[[Message], bool],
        amount: int,
    ) -> List[Message]:
        scan = min(max(amount * 5, amount + 50), SCAN_CAP)
        matched: List[Message] = []
        async for m in ctx.channel.history(limit=scan):
            if m.id == ctx.message.id:
                continue
            if check(m):
                matched.append(m)
                if len(matched) >= amount:
                    break
        return matched

    async def _success(
        self,
        ctx: Context,
        *,
        purge_type: str,
        amount: int,
        delete_after: float = 10.0,
    ):
        return await ctx.success(
            f"**purge** complete!\n"
            f"> -# **type**: {purge_type}\n"
            f"> -# **amount**: {amount}",
            delete_after=delete_after,
        )

    @group(
        name="purge",
        aliases=["c", "clear"],
        example=",purge 100",
        description="purge messages from chat (default 30, max 1000)",
        invoke_without_command=True,
    )
    @has_permissions(manage_messages=True)
    async def purge(self, ctx: Context, *args: str):
        member: Optional[Member] = None
        search: Optional[int] = None

        if len(args) == 1:
            token = args[0]
            try:
                search = int(token)
            except ValueError:
                try:
                    member = await MemberConverter().convert(ctx, token)
                except Exception as exc:
                    raise CommandError(f"Member `{token}` not found") from exc
        elif len(args) >= 2:
            try:
                member = await MemberConverter().convert(ctx, args[0])
            except Exception as exc:
                raise CommandError(f"Member `{args[0]}` not found") from exc
            try:
                search = int(args[1])
            except ValueError as exc:
                raise CommandError(f"Invalid amount `{args[1]}`") from exc

        amount = self._clamp_amount(search)

        if member is not None:
            def check(message: Message) -> bool:
                return message.author.id == member.id
            purge_type = member.display_name
        else:
            def check(message: Message) -> bool:
                return True
            purge_type = "messages"

        messages = await self._collect(ctx, check, amount)
        if not messages:
            raise CommandError("No purgable messages found")
        to_delete = self._with_invoke(ctx, messages)
        await self.delete_messages(to_delete)
        return await self._success(ctx, purge_type=purge_type, amount=len(messages))

    @purge.command(
        name="attachments",
        aliases=["files", "file", "a"],
        example=",purge attachments 50",
        description="purge messages with attachments",
    )
    @has_permissions(manage_messages=True)
    async def purge_attachments(self, ctx: Context, search: Optional[int] = None):
        amount = self._clamp_amount(search)

        def check(message: Message) -> bool:
            return bool(message.attachments)

        messages = await self._collect(ctx, check, amount)
        if not messages:
            raise CommandError("No purgable messages found")
        to_delete = self._with_invoke(ctx, messages)
        await self.delete_messages(to_delete)
        return await self._success(ctx, purge_type="attachments", amount=len(messages))

    @purge.command(
        name="endswith",
        aliases=["es", "ends"],
        example=",purge endswith st 30",
        description="purge messages ending with a substring",
    )
    @has_permissions(manage_messages=True)
    async def purge_endswith(
        self, ctx: Context, substring: str, search: Optional[int] = None
    ):
        amount = self._clamp_amount(search)
        needle = substring.lower()

        def check(message: Message) -> bool:
            return bool(message.content) and message.content.lower().endswith(needle)

        messages = await self._collect(ctx, check, amount)
        if not messages:
            raise CommandError("No purgable messages found")
        to_delete = self._with_invoke(ctx, messages)
        await self.delete_messages(to_delete)
        return await self._success(
            ctx, purge_type=f"endswith · `{substring}`", amount=len(messages)
        )

    @purge.command(
        name="mentions",
        aliases=["mention", "ping", "pings"],
        example=",purge mentions jonathan 100",
        description="purge messages that mention a member (or any mention)",
    )
    @has_permissions(manage_messages=True)
    async def purge_mentions(
        self,
        ctx: Context,
        member: Optional[Member] = None,
        search: Optional[int] = None,
    ):
        amount = self._clamp_amount(search)

        if member is None:
            def check(message: Message) -> bool:
                return bool(message.mentions)
            purge_type = "mentions"
        else:
            def check(message: Message) -> bool:
                return member in message.mentions
            purge_type = f"mentions · {member.display_name}"

        messages = await self._collect(ctx, check, amount)
        if not messages:
            raise CommandError("No purgable messages found")
        to_delete = self._with_invoke(ctx, messages)
        await self.delete_messages(to_delete)
        return await self._success(ctx, purge_type=purge_type, amount=len(messages))

    @purge.command(
        name="emoji",
        aliases=["emojis", "emote", "emotes"],
        example=",purge emoji 20",
        description="purge messages containing emoji",
    )
    @has_permissions(manage_messages=True)
    async def purge_emoji(self, ctx: Context, search: Optional[int] = None):
        amount = self._clamp_amount(search)
        custom = re.compile(r"<a?:\w+:\d+>")

        def check(message: Message) -> bool:
            content = message.content or ""
            return bool(custom.search(content)) or any(
                ord(c) > 0x1F300 for c in content
            )

        messages = await self._collect(ctx, check, amount)
        if not messages:
            raise CommandError("No purgable messages found")
        to_delete = self._with_invoke(ctx, messages)
        await self.delete_messages(to_delete)
        return await self._success(ctx, purge_type="emoji", amount=len(messages))

    @purge.command(
        name="before",
        description="purge messages before a given message",
    )
    @has_permissions(manage_messages=True)
    async def purge_before(
        self, ctx: Context, message: Message, search: Optional[int] = None
    ):
        amount = self._clamp_amount(search)

        def check(m: Message) -> bool:
            return m.created_at < message.created_at

        messages = await self._collect(ctx, check, amount)
        if not messages:
            raise CommandError("No purgable messages found")
        to_delete = self._with_invoke(ctx, messages)
        await self.delete_messages(to_delete)
        return await self._success(ctx, purge_type="before", amount=len(messages))

    @purge.command(
        name="stickers",
        aliases=["sticker"],
        example=",purge stickers 30",
        description="purge messages with stickers",
    )
    @has_permissions(manage_messages=True)
    async def purge_stickers(self, ctx: Context, search: Optional[int] = None):
        amount = self._clamp_amount(search)

        def check(message: Message) -> bool:
            return bool(message.stickers)

        messages = await self._collect(ctx, check, amount)
        if not messages:
            raise CommandError("No purgable messages found")
        to_delete = self._with_invoke(ctx, messages)
        await self.delete_messages(to_delete)
        return await self._success(ctx, purge_type="stickers", amount=len(messages))

    @purge.command(
        name="contains",
        aliases=["contain", "has"],
        example=",purge contains hello 30",
        description="purge messages containing a substring",
    )
    @has_permissions(manage_messages=True)
    async def purge_contains(
        self, ctx: Context, substring: str, search: Optional[int] = None
    ):
        amount = self._clamp_amount(search)
        needle = substring.lower()

        def check(message: Message) -> bool:
            return bool(message.content) and needle in message.content.lower()

        messages = await self._collect(ctx, check, amount)
        if not messages:
            raise CommandError("No purgable messages found")
        to_delete = self._with_invoke(ctx, messages)
        await self.delete_messages(to_delete)
        return await self._success(
            ctx, purge_type=f"contains · `{substring}`", amount=len(messages)
        )

    @purge.command(
        name="between",
        description="purge messages between two messages",
    )
    @has_permissions(manage_messages=True)
    async def purge_between(
        self,
        ctx: Context,
        start: Message,
        end: Message,
        search: Optional[int] = None,
    ):
        amount = self._clamp_amount(search)
        older, newer = sorted((start, end), key=lambda m: m.created_at)

        def check(m: Message) -> bool:
            return older.created_at < m.created_at < newer.created_at

        messages = await self._collect(ctx, check, amount)
        if not messages:
            raise CommandError("No purgable messages found")
        to_delete = self._with_invoke(ctx, messages)
        await self.delete_messages(to_delete)
        return await self._success(ctx, purge_type="between", amount=len(messages))

    @purge.command(
        name="bots",
        aliases=["bot"],
        example=",purge bots 30",
        description="purge messages from bots",
    )
    @has_permissions(manage_messages=True)
    async def purge_bots(self, ctx: Context, search: Optional[int] = None):
        amount = self._clamp_amount(search)

        def check(message: Message) -> bool:
            return bool(message.author.bot)

        messages = await self._collect(ctx, check, amount)
        if not messages:
            raise CommandError("No purgable messages found")
        to_delete = self._with_invoke(ctx, messages)
        await self.delete_messages(to_delete)
        return await self._success(ctx, purge_type="bots", amount=len(messages))

    @purge.command(
        name="webhooks",
        aliases=["webhook", "wh"],
        example=",purge webhooks 30",
        description="purge messages sent by webhooks",
    )
    @has_permissions(manage_messages=True)
    async def purge_webhooks(self, ctx: Context, search: Optional[int] = None):
        amount = self._clamp_amount(search)

        def check(message: Message) -> bool:
            return message.webhook_id is not None

        messages = await self._collect(ctx, check, amount)
        if not messages:
            raise CommandError("No purgable messages found")
        to_delete = self._with_invoke(ctx, messages)
        await self.delete_messages(to_delete)
        return await self._success(ctx, purge_type="webhooks", amount=len(messages))

    @purge.command(
        name="reactions",
        aliases=["reacts", "reaction"],
        example=",purge reactions 30",
        description="purge messages that have reactions",
    )
    @has_permissions(manage_messages=True)
    async def purge_reactions(self, ctx: Context, search: Optional[int] = None):
        amount = self._clamp_amount(search)

        def check(message: Message) -> bool:
            return bool(message.reactions)

        messages = await self._collect(ctx, check, amount)
        if not messages:
            raise CommandError("No purgable messages found")
        to_delete = self._with_invoke(ctx, messages)
        await self.delete_messages(to_delete)
        return await self._success(ctx, purge_type="reactions", amount=len(messages))

    @purge.command(
        name="images",
        aliases=["image", "img", "pics", "pictures"],
        example=",purge images 30",
        description="purge messages with images",
    )
    @has_permissions(manage_messages=True)
    async def purge_images(self, ctx: Context, search: Optional[int] = None):
        amount = self._clamp_amount(search)

        def check(message: Message) -> bool:
            if any(
                (a.content_type or "").startswith("image/")
                for a in message.attachments
            ):
                return True
            return any(e.image or e.thumbnail for e in message.embeds)

        messages = await self._collect(ctx, check, amount)
        if not messages:
            raise CommandError("No purgable messages found")
        to_delete = self._with_invoke(ctx, messages)
        await self.delete_messages(to_delete)
        return await self._success(ctx, purge_type="images", amount=len(messages))

    @purge.command(
        name="after",
        description="purge messages after a given message",
    )
    @has_permissions(manage_messages=True)
    async def purge_after(
        self, ctx: Context, message: Message, search: Optional[int] = None
    ):
        amount = self._clamp_amount(search)

        def check(m: Message) -> bool:
            return m.created_at > message.created_at

        messages = await self._collect(ctx, check, amount)
        if not messages:
            raise CommandError("No purgable messages found")
        to_delete = self._with_invoke(ctx, messages)
        await self.delete_messages(to_delete)
        return await self._success(ctx, purge_type="after", amount=len(messages))

    @purge.command(
        name="links",
        aliases=["link", "urls", "url"],
        example=",purge links 30",
        description="purge messages containing links",
    )
    @has_permissions(manage_messages=True)
    async def purge_links(self, ctx: Context, search: Optional[int] = None):
        amount = self._clamp_amount(search)

        def check(message: Message) -> bool:
            return bool(message.content) and bool(URL.search(message.content))

        messages = await self._collect(ctx, check, amount)
        if not messages:
            raise CommandError("No purgable messages found")
        to_delete = self._with_invoke(ctx, messages)
        await self.delete_messages(to_delete)
        return await self._success(ctx, purge_type="links", amount=len(messages))

    @purge.command(
        name="embeds",
        aliases=["embed"],
        example=",purge embeds 30",
        description="purge messages containing embeds",
    )
    @has_permissions(manage_messages=True)
    async def purge_embeds(self, ctx: Context, search: Optional[int] = None):
        amount = self._clamp_amount(search)

        def check(message: Message) -> bool:
            return bool(message.embeds)

        messages = await self._collect(ctx, check, amount)
        if not messages:
            raise CommandError("No purgable messages found")
        to_delete = self._with_invoke(ctx, messages)
        await self.delete_messages(to_delete)
        return await self._success(ctx, purge_type="embeds", amount=len(messages))

    @purge.command(
        name="startswith",
        aliases=["ss", "starts"],
        example=",purge startswith hi 30",
        description="purge messages starting with a substring",
    )
    @has_permissions(manage_messages=True)
    async def purge_startswith(
        self, ctx: Context, substring: str, search: Optional[int] = None
    ):
        amount = self._clamp_amount(search)
        needle = substring.lower()

        def check(message: Message) -> bool:
            return bool(message.content) and message.content.lower().startswith(needle)

        messages = await self._collect(ctx, check, amount)
        if not messages:
            raise CommandError("No purgable messages found")
        to_delete = self._with_invoke(ctx, messages)
        await self.delete_messages(to_delete)
        return await self._success(
            ctx, purge_type=f"startswith · `{substring}`", amount=len(messages)
        )

    @purge.command(
        name="humans",
        aliases=["human", "users", "user"],
        example=",purge humans 30",
        description="purge messages from humans",
    )
    @has_permissions(manage_messages=True)
    async def purge_humans(self, ctx: Context, search: Optional[int] = None):
        amount = self._clamp_amount(search)

        def check(message: Message) -> bool:
            return not message.author.bot

        messages = await self._collect(ctx, check, amount)
        if not messages:
            raise CommandError("No purgable messages found")
        to_delete = self._with_invoke(ctx, messages)
        await self.delete_messages(to_delete)
        return await self._success(ctx, purge_type="humans", amount=len(messages))

    @purge.command(
        name="upto",
        description="purge messages up to a given message",
    )
    @has_permissions(manage_messages=True)
    async def purge_upto(
        self, ctx: Context, message: Message, search: Optional[int] = None
    ):
        amount = self._clamp_amount(search)

        def check(m: Message) -> bool:
            return m.created_at <= message.created_at

        messages = await self._collect(ctx, check, amount)
        if not messages:
            raise CommandError("No purgable messages found")
        to_delete = self._with_invoke(ctx, messages)
        await self.delete_messages(to_delete)
        return await self._success(ctx, purge_type="upto", amount=len(messages))

    async def _do_selfpurge(self, ctx: Context, search: Optional[int] = None):
        amount = self._clamp_amount(search)
        author_id = ctx.author.id

        def check(message: Message) -> bool:
            return message.author.id == author_id

        messages = await self._collect(ctx, check, amount)
        if not messages:
            raise CommandError("No purgable messages found")
        to_delete = self._with_invoke(ctx, messages)
        await self.delete_messages(to_delete)
        return await self._success(ctx, purge_type="self", amount=len(messages))

    @purge.command(
        name="self",
        aliases=["me", "own"],
        example=",purge self 30",
        description="purge your own messages (default 30, no permission required)",
    )
    async def purge_self(self, ctx: Context, search: Optional[int] = None):
        return await self._do_selfpurge(ctx, search)

    @command(
        name="selfpurge",
        aliases=["sme", "me"],
        description="purge your own messages (default 30, no permission required)",
        example=",selfpurge 30",
    )
    async def selfpurge(self, ctx: Context, search: Optional[int] = None):
        return await self._do_selfpurge(ctx, search)

    @command(
        name="botclear",
        aliases=["botpurge", "bc", "bp"],
        description="clear recent messages sent by any bots (default 30, max 1000)",
        example=",botclear 30",
    )
    @has_permissions(manage_messages=True)
    async def botclear(self, ctx: Context, search: Optional[int] = None):
        amount = self._clamp_amount(search)

        def check(message: Message) -> bool:
            return bool(message.author.bot)

        messages = await self._collect(ctx, check, amount)
        if not messages:
            raise CommandError("No bot messages found")
        to_delete = self._with_invoke(ctx, messages)
        await self.delete_messages(to_delete)
        return await ctx.success(
            f"**botclear** complete!\n"
            f"> -# **type**: bot\n"
            f"> -# **amount**: {len(messages)}",
            delete_after=10.0,
        )
