from __future__ import annotations

import asyncio
import re
from asyncio import create_task
from datetime import datetime, timezone, timedelta
from typing import List, Optional

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
)
from core.discord.package import Package
from core.managers.permissions import has_permissions

URL = re.compile(r"https?://[^\s]+")
BULK_DELETE_LIMIT = timedelta(days=14)


class Purge(Package):
    """purge management"""

    def __init__(self, bot):
        super().__init__(bot)
        self.tasks: dict[str, asyncio.Task] = {}

    async def delete_messages(self, messages: List[Message]):
        if not messages:
            return 0

        async def purge(messages: List[Message]) -> None:
            channel = messages[0].channel
            now = datetime.now(timezone.utc)
            bulkable = [m for m in messages if (now - m.created_at) < BULK_DELETE_LIMIT]
            non_bulk = [m for m in messages if (now - m.created_at) >= BULK_DELETE_LIMIT]
            amount = len(bulkable)

            async def bulk():
                if amount > 100:
                    for chunk in discord.utils.chunk_list(bulkable, 100):
                        await channel.delete_messages(chunk)
                        await asyncio.sleep(1)
                else:
                    await channel.delete_messages(bulkable)

            async def nonbulk():
                for message in non_bulk:
                    await message.delete()

            await bulk()
            await nonbulk()

        key = f"purge-{messages[0].guild.id}"
        if self.tasks.get(key):
            raise MaxConcurrencyReached(1, BucketType.guild)
        task = create_task(purge(messages))
        self.tasks[key] = task
        try:
            await task
        finally:
            self.tasks.pop(key, None)
        return len(messages)

    def _with_invoke(self, ctx: Context, messages: List[Message]) -> List[Message]:
        """Always include the invoking command message so purge N deletes N+1."""
        out = list(messages)
        if ctx.message not in out:
            out.append(ctx.message)
        return out

    async def _success(
        self,
        ctx: Context,
        *,
        purge_type: str,
        amount: int,
        delete_after: float = 5.0,
    ):
        return await ctx.success(
            f"**purge** complete!\n"
            f"> -# **type**: {purge_type}\n"
            f"> -# **amount**: {amount}",
            delete_after=delete_after,
        )

    @group(
        name="purge",
        description="Deletes the specified amount of messages from the current channel",
        example=",purge jonathan 100",
        invoke_without_command=True,
    )
    @has_permissions(manage_messages=True)
    async def purge(
        self, ctx: Context, member: Optional[Member] = None, search: Optional[int] = 100
    ):
        if member:
            messages = [
                m
                async for m in ctx.channel.history()
                if m.author.id == member.id and m != ctx.message
            ]
            if len(messages) == 0:
                raise CommandError("No purgable messages found")
            purge_type = f"member · {member.display_name}"
        else:
            messages = [m async for m in ctx.channel.history() if m != ctx.message]
            if len(messages) == 0:
                raise CommandError("No purgable messages found")
            purge_type = "regular"

        to_delete = self._with_invoke(ctx, messages[:search])
        amount = await self.delete_messages(to_delete)
        return await self._success(ctx, purge_type=purge_type, amount=amount)

    @purge.command(
        name="attachments",
        aliases=["files", "attachment", "file"],
        description="Purge messages that contain attachments or files",
        example=",purge attachments 50",
    )
    @has_permissions(manage_messages=True)
    async def purge_attachments(self, ctx: Context, search: Optional[int] = 100):
        def check(message: Message) -> bool:
            for attachment in message.attachments:
                if attachment.content_type not in (
                    "image/jpg",
                    "image/png",
                    "image/jpeg",
                    "image/gif",
                ):
                    return True
            return False

        messages = [
            m async for m in ctx.channel.history() if m != ctx.message and check(m)
        ]
        if not messages:
            raise CommandError("No purgable messages found")
        to_delete = self._with_invoke(ctx, messages[:search])
        amount = await self.delete_messages(to_delete)
        return await self._success(ctx, purge_type="attachments", amount=amount)

    @purge.command(
        name="endswith",
        description="Purge messages that ends with a given substring",
        example=",purge endswith st",
    )
    @has_permissions(manage_messages=True)
    async def purge_endswith(self, ctx: Context, *, substring: str):
        def check(message: Message) -> bool:
            return message.content.endswith(substring)

        messages = [
            m async for m in ctx.channel.history() if m != ctx.message and check(m)
        ]
        if not messages:
            raise CommandError("No purgable messages found")
        to_delete = self._with_invoke(ctx, messages)
        amount = await self.delete_messages(to_delete)
        return await self._success(
            ctx, purge_type=f"endswith · `{substring}`", amount=amount
        )

    @purge.command(
        name="mentions",
        description="Purge mentions for a member from chat",
        example=",purge mentions jonathan 100",
    )
    @has_permissions(manage_messages=True)
    async def purge_mentions(
        self, ctx: Context, member: Optional[Member] = None, search: Optional[int] = 100
    ):
        if member is None:

            def check(message: Message) -> bool:
                return True if message.mentions else False

            purge_type = "mentions"
        else:

            def check(message: Message) -> bool:
                return message.mentions and member in message.mentions

            purge_type = f"mentions · {member.display_name}"

        messages = [
            m async for m in ctx.channel.history() if m != ctx.message and check(m)
        ]
        if not messages:
            raise CommandError("No purgable messages found")
        to_delete = self._with_invoke(ctx, messages[:search])
        amount = await self.delete_messages(to_delete)
        return await self._success(ctx, purge_type=purge_type, amount=amount)

    @purge.command(
        name="emoji",
        description="Purge messages containing custom emojis",
        example=",purge emoji 20",
    )
    @has_permissions(manage_messages=True)
    async def purge_emoji(self, ctx: Context, search: Optional[int] = 100):
        def check(message: Message) -> bool:
            return True if message.emojis else False

        messages = [
            m async for m in ctx.channel.history() if m != ctx.message and check(m)
        ]
        if not messages:
            raise CommandError("No purgable messages found")
        to_delete = self._with_invoke(ctx, messages[:search])
        amount = await self.delete_messages(to_delete)
        return await self._success(ctx, purge_type="emoji", amount=amount)

    @purge.command(
        name="before", description="Purge messages before a given message ID"
    )
    @has_permissions(manage_messages=True)
    async def purge_before(self, ctx: Context, message: Message):
        def check(m: Message) -> bool:
            return m.created_at < message.created_at

        messages = [
            m async for m in ctx.channel.history() if m != ctx.message and check(m)
        ]
        if not messages:
            raise CommandError("No purgable messages found")
        to_delete = self._with_invoke(ctx, messages)
        amount = await self.delete_messages(to_delete)
        return await self._success(ctx, purge_type="before", amount=amount)

    @purge.command(
        name="stickers",
        description="Purge messages with stickers",
        example=",purge stickers 30",
    )
    @has_permissions(manage_messages=True)
    async def purge_stickers(self, ctx: Context, search: Optional[int] = 100):
        def check(message: Message) -> bool:
            return True if message.stickers else False

        messages = [
            m async for m in ctx.channel.history() if m != ctx.message and check(m)
        ]
        if not messages:
            raise CommandError("No purgable messages found")
        to_delete = self._with_invoke(ctx, messages[:search])
        amount = await self.delete_messages(to_delete)
        return await self._success(ctx, purge_type="stickers", amount=amount)

    @purge.command(
        name="contains", description="Purges messages containing given substring"
    )
    @has_permissions(manage_messages=True)
    async def purge_contains(self, ctx: Context, *, substring: str):
        def check(message: Message) -> bool:
            if substring.endswith("*"):
                return True if substring in str(message.content) else False
            else:
                return True if substring in str(message.content).split(" ") else False

        messages = [
            m async for m in ctx.channel.history() if m != ctx.message and check(m)
        ]
        if not messages:
            raise CommandError("No purgable messages found")
        to_delete = self._with_invoke(ctx, messages)
        amount = await self.delete_messages(to_delete)
        return await self._success(
            ctx, purge_type=f"contains · `{substring}`", amount=amount
        )

    @purge.command(name="between", description="Purge between two messages")
    @has_permissions(manage_messages=True)
    async def purge_between(self, ctx: Context, start_id: Message, finish_id: Message):
        def check(message: Message) -> bool:
            return (
                True
                if start_id.created_at <= message.created_at <= finish_id.created_at
                else False
            )

        messages = [
            m async for m in ctx.channel.history() if m != ctx.message and check(m)
        ]
        if not messages:
            raise CommandError("No purgable messages found")
        to_delete = self._with_invoke(ctx, messages)
        amount = await self.delete_messages(to_delete)
        return await self._success(ctx, purge_type="between", amount=amount)

    @purge.command(name="webhooks", description="Purge messages from webhooks in chat")
    @has_permissions(manage_messages=True)
    async def purge_webhooks(self, ctx: Context, search: Optional[int] = 100):
        def check(message: Message) -> bool:
            return True if message.author.webhook_id else False

        messages = [
            m async for m in ctx.channel.history() if m != ctx.message and check(m)
        ]
        if not messages:
            raise CommandError("No purgable messages found")
        to_delete = self._with_invoke(ctx, messages[:search])
        amount = await self.delete_messages(to_delete)
        return await self._success(ctx, purge_type="webhooks", amount=amount)

    @purge.command(name="bots", description="Purge messages from bots in chat")
    @has_permissions(manage_messages=True)
    async def purge_bots(self, ctx: Context, search: Optional[int] = 100):
        def check(message: Message) -> bool:
            return True if message.author.bot else False

        messages = [
            m async for m in ctx.channel.history() if m != ctx.message and check(m)
        ]
        if not messages:
            raise CommandError("No purgable messages found")
        to_delete = self._with_invoke(ctx, messages[:search])
        amount = await self.delete_messages(to_delete)
        return await self._success(ctx, purge_type="bots", amount=amount)

    @purge.command(
        name="reactions", description="Purge reactions from messages in chat"
    )
    @has_permissions(manage_messages=True)
    async def purge_reactions(self, ctx: Context, search: Optional[int] = 100):
        def check(message: Message) -> bool:
            return True if message.reactions else False

        async def remove_reactions(messages: List[Message]) -> None:
            for message in messages:
                await message.clear_reactions()

        key = f"purge-{ctx.guild.id}"
        if self.tasks.get(key):
            raise MaxConcurrencyReached(1, BucketType.guild)
        messages = [
            m async for m in ctx.channel.history() if m != ctx.message and check(m)
        ]
        if not messages:
            raise CommandError("No purgable messages found")
        task = create_task(remove_reactions(messages[:search]))
        self.tasks[key] = task
        try:
            await task
        finally:
            self.tasks.pop(key, None)
        return await self._success(
            ctx, purge_type="reactions", amount=len(messages[:search])
        )

    @purge.command(
        name="images", description="Purge images (including links) from chat"
    )
    @has_permissions(manage_messages=True)
    async def purge_images(self, ctx: Context, search: Optional[int] = 100):
        def check(message: Message) -> bool:
            if URL.findall(message.content):
                return True
            return True if message.attachments else False

        messages = [
            m async for m in ctx.channel.history() if m != ctx.message and check(m)
        ]
        if not messages:
            raise CommandError("No purgable messages found")
        to_delete = self._with_invoke(ctx, messages[:search])
        amount = await self.delete_messages(to_delete)
        return await self._success(ctx, purge_type="images", amount=amount)

    @purge.command(name="after", description="Purge messages after a given message ID")
    @has_permissions(manage_messages=True)
    async def purge_after(self, ctx: Context, message: Message):
        def check(m: Message) -> bool:
            return True if m.created_at > message.created_at else False

        messages = [
            m async for m in ctx.channel.history() if m != ctx.message and check(m)
        ]
        if not messages:
            raise CommandError("No purgable messages found")
        to_delete = self._with_invoke(ctx, messages)
        amount = await self.delete_messages(to_delete)
        return await self._success(ctx, purge_type="after", amount=amount)

    @purge.command(name="links", description="Purge messages containing links")
    @has_permissions(manage_messages=True)
    async def purge_links(self, ctx: Context, search: Optional[int] = 100):
        def check(message: Message) -> bool:
            if URL.findall(message.content):
                return True
            return False

        messages = [
            m async for m in ctx.channel.history() if m != ctx.message and check(m)
        ]
        if not messages:
            raise CommandError("No purgable messages found")
        to_delete = self._with_invoke(ctx, messages[:search] if search else messages)
        amount = await self.delete_messages(to_delete)
        return await self._success(ctx, purge_type="links", amount=amount)

    @purge.command(name="embeds", description="Purge embeds from chat")
    @has_permissions(manage_messages=True)
    async def purge_embeds(self, ctx: Context, search: Optional[int] = 100):
        def check(message: Message) -> bool:
            return True if message.embeds else False

        messages = [
            m async for m in ctx.channel.history() if m != ctx.message and check(m)
        ]
        if not messages:
            raise CommandError("No purgable messages found")
        to_delete = self._with_invoke(ctx, messages[:search])
        amount = await self.delete_messages(to_delete)
        return await self._success(ctx, purge_type="embeds", amount=amount)

    @purge.command(
        name="startswith",
        description="Purge messages that start with a given substring",
    )
    @has_permissions(manage_messages=True)
    async def purge_startswith(self, ctx: Context, *, substring: str):
        def check(message: Message) -> bool:
            return True if message.content.startswith(substring) else False

        messages = [
            m async for m in ctx.channel.history() if m != ctx.message and check(m)
        ]
        if not messages:
            raise CommandError("No purgable messages found")
        to_delete = self._with_invoke(ctx, messages)
        amount = await self.delete_messages(to_delete)
        return await self._success(
            ctx, purge_type=f"startswith · `{substring}`", amount=amount
        )

    @purge.command(name="humans", description="Purge messages from humans in chat")
    @has_permissions(manage_messages=True)
    async def purge_humans(self, ctx: Context, search: Optional[int] = 100):
        def check(message: Message) -> bool:
            return True if not message.author.bot else False

        messages = [
            m async for m in ctx.channel.history() if m != ctx.message and check(m)
        ]
        if not messages:
            raise CommandError("No purgable messages found")
        to_delete = self._with_invoke(ctx, messages[:search])
        amount = await self.delete_messages(to_delete)
        return await self._success(ctx, purge_type="humans", amount=amount)

    @purge.command(name="upto", description="Purge messages up to a message link")
    @has_permissions(manage_messages=True)
    async def purge_upto(self, ctx: Context, message: Message):
        def check(m: Message) -> bool:
            return m.created_at < message.created_at

        messages = [
            m async for m in ctx.channel.history() if m != ctx.message and check(m)
        ]
        if not messages:
            raise CommandError("No purgable messages found")
        to_delete = self._with_invoke(ctx, messages)
        amount = await self.delete_messages(to_delete)
        return await self._success(ctx, purge_type="upto", amount=amount)

    @command(
        name="botclear",
        aliases=["botpurge", "bc", "bp"],
        description="Clear the last 30 messages sent by any bots",
        example=",botclear",
    )
    @has_permissions(manage_messages=True)
    async def botclear(self, ctx: Context):
        """Purge the most recent 30 messages from any bots (not just this bot)."""
        messages = [
            m
            async for m in ctx.channel.history(limit=200)
            if m.author.bot and m != ctx.message
        ][:30]
        if not messages:
            raise CommandError("No bot messages found")
        to_delete = self._with_invoke(ctx, messages)
        amount = await self.delete_messages(to_delete)
        return await ctx.success(
            f"**botclear** complete!\n"
            f"> -# **type**: bot\n"
            f"> -# **amount**: {amount}",
            delete_after=2.0,
        )
