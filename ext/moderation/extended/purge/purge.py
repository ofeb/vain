from __future__ import annotations

import asyncio
import re
from asyncio import create_task
from typing import List, Optional

import discord
from discord import Member, Message
from discord.ext import commands
from discord.ext.commands import group, CommandError
from discord.utils import BucketType

from core.discord.package import Package
from core.managers.permissions import has_permissions

URL = re.compile(r"https?://[^\s]+")


class Purge(Package):
    """purge management"""

    def __init__(self, bot):
        super().__init__(bot)
        self.tasks: dict[str, asyncio.Task] = {}

    async def delete_messages(self, messages: List[Message]):
        async def purge(messages: List[Message]) -> None:
            channel = messages[0].channel
            bulkable = [m for m in messages if m.is_deleteable()]
            non_bulk = [m for m in messages if not m.is_deleteable()]
            amount = len(bulkable)

            async def bulk():
                if amount > 100:
                    for chunk in [bulkable[i:i+100] for i in range(0, len(bulkable), 100)]:
                        await channel.delete_messages(chunk)
                        await asyncio.sleep(1)
                else:
                    await channel.delete_messages(bulkable)

            async def nonbulk():
                for message in non_bulk:
                    await message.delete()

            await bulk()
            await nonbulk()

        if task := self.tasks.get(f"purge-{messages[0].guild.id}"):
            raise CommandError("A purge is already running in this server")
        task = create_task(purge(messages))
        self.tasks[f"purge-{messages[0].guild.id}"] = task
        await task
        self.tasks.pop(f"purge-{messages[0].guild.id}", None)

    @group(
        name="purge",
        description="Deletes the specified amount of messages from the current channel",
        example=",purge jonathan 100",
        invoke_without_command=True,
    )
    @has_permissions(manage_messages=True)
    async def purge(
        self, ctx, member: Optional[Member] = None, search: Optional[int] = 100
    ):
        if member:
            messages = [
                m
                async for m in ctx.channel.history()
                if m.author.id == member.id and m != ctx.message
            ]
            if len(messages) == 0:
                raise CommandError("No purgable messages found")
        else:
            messages = [m async for m in ctx.channel.history() if m != ctx.message]
            if len(messages) == 0:
                raise CommandError("No purgable messages found")
        await self.delete_messages(messages[:search])
        return await ctx.send("\U0001f44d")

    @purge.command(
        name="startswith",
        description="Purge messages that start with a given substring",
        example=",purge startswith hello",
    )
    @has_permissions(manage_messages=True)
    async def purge_startswith(self, ctx, *, substring: str):
        def check(message: Message) -> bool:
            return message.content.startswith(substring)

        messages = [
            m async for m in ctx.channel.history() if m != ctx.message and check(m)
        ]
        if not messages:
            raise CommandError("No purgable messages found")
        await self.delete_messages(messages)
        return await ctx.send("\U0001f44d")

    @purge.command(
        name="embeds",
        description="Purge embeds from chat",
    )
    @has_permissions(manage_messages=True)
    async def purge_embeds(self, ctx, search: Optional[int] = 100):
        def check(message: Message) -> bool:
            return True if message.embeds else False

        messages = [
            m async for m in ctx.channel.history() if m != ctx.message and check(m)
        ]
        if not messages:
            raise CommandError("No purgable messages found")
        await self.delete_messages(messages[:search])
        return await ctx.send("\U0001f44d")

    @purge.command(
        name="files",
        aliases=["attachments", "attachment", "file"],
        description="Purge files/attachments from chat",
    )
    @has_permissions(manage_messages=True)
    async def purge_files(self, ctx, search: Optional[int] = 100):
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
        await self.delete_messages(messages[:search])
        return await ctx.send("\U0001f44d")

    @purge.command(
        name="images",
        description="Purge images (including links) from chat",
    )
    @has_permissions(manage_messages=True)
    async def purge_images(self, ctx, search: Optional[int] = 100):
        def check(message: Message) -> bool:
            if URL.findall(message.content):
                return True
            return True if message.attachments else False

        messages = [
            m async for m in ctx.channel.history() if m != ctx.message and check(m)
        ]
        if not messages:
            raise CommandError("No purgable messages found")
        await self.delete_messages(messages[:search])
        return await ctx.send("\U0001f44d")

    @purge.command(
        name="contains",
        description="Purges messages containing given substring",
        example=",purge contains hello",
    )
    @has_permissions(manage_messages=True)
    async def purge_contains(self, ctx, *, substring: str):
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
        await self.delete_messages(messages)
        return await ctx.send("\U0001f44d")

    @purge.command(
        name="before",
        description="Purge messages before a given message ID",
    )
    @has_permissions(manage_messages=True)
    async def purge_before(self, ctx, message: Message):
        def check(message: Message, m: Message) -> bool:
            if message.created_at <= m.created_at:
                return True
            else:
                return False

        messages = [
            m async for m in ctx.channel.history() if m != ctx.message and check(m, message)
        ]
        if not messages:
            raise CommandError("No purgable messages found")
        await self.delete_messages(messages)
        return await ctx.send("\U0001f44d")

    @purge.command(
        name="bots",
        description="Purge messages from bots in chat",
    )
    @has_permissions(manage_messages=True)
    async def purge_bots(self, ctx, search: Optional[int] = 100):
        def check(message: Message) -> bool:
            return True if message.author.bot else False

        messages = [
            m async for m in ctx.channel.history() if m != ctx.message and check(m)
        ]
        if not messages:
            raise CommandError("No purgable messages found")
        await self.delete_messages(messages[:search])
        return await ctx.send("\U0001f44d")

    @purge.command(
        name="after",
        description="Purge messages after a given message ID",
    )
    @has_permissions(manage_messages=True)
    async def purge_after(self, ctx, message: Message):
        def check(m: Message) -> bool:
            return True if m.created_at > message.created_at else False

        messages = [
            m async for m in ctx.channel.history() if m != ctx.message and check(m)
        ]
        if not messages:
            raise CommandError("No purgable messages found")
        await self.delete_messages(messages)
        return await ctx.send("\U0001f44d")

    @purge.command(
        name="webhooks",
        description="Purge messages from webhooks in chat",
    )
    @has_permissions(manage_messages=True)
    async def purge_webhooks(self, ctx, search: Optional[int] = 100):
        def check(message: Message) -> bool:
            return True if message.webhook_id else False

        messages = [
            m async for m in ctx.channel.history() if m != ctx.message and check(m)
        ]
        if not messages:
            raise CommandError("No purgable messages found")
        await self.delete_messages(messages[:search])
        return await ctx.send("\U0001f44d")

    @purge.command(
        name="between",
        description="Purge between two messages",
    )
    @has_permissions(manage_messages=True)
    async def purge_between(self, ctx, start_id: Message, finish_id: Message):
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
        await self.delete_messages(messages)
        return await ctx.send("\U0001f44d")

    @purge.command(
        name="links",
        description="Purge messages containing links",
    )
    @has_permissions(manage_messages=True)
    async def purge_links(self, ctx, search: Optional[int] = 100):
        def check(message: Message) -> bool:
            if URL.findall(message.content):
                return True
            return False

        messages = [
            m async for m in ctx.channel.history() if m != ctx.message and check(m)
        ]
        if not messages:
            raise CommandError("No purgable messages found")
        await self.delete_messages(messages)
        return await ctx.send("\U0001f44d")

    @purge.command(
        name="activity",
        description="Purge activity messages from chat",
    )
    @has_permissions(manage_messages=True)
    async def purge_activity(self, ctx, search: Optional[int] = 100):
        def check(message: Message) -> bool:
            return bool(message.activity)

        messages = [
            m async for m in ctx.channel.history() if m != ctx.message and check(m)
        ]
        if not messages:
            raise CommandError("No purgable messages found")
        await self.delete_messages(messages[:search])
        return await ctx.send("\U0001f44d")

    @purge.command(
        name="humans",
        description="Purge messages from humans in chat",
    )
    @has_permissions(manage_messages=True)
    async def purge_humans(self, ctx, search: Optional[int] = 100):
        def check(message: Message) -> bool:
            return True if not message.author.bot else False

        messages = [
            m async for m in ctx.channel.history() if m != ctx.message and check(m)
        ]
        if not messages:
            raise CommandError("No purgable messages found")
        await self.delete_messages(messages[:search])
        return await ctx.send("\U0001f44d")

    @purge.command(
        name="endswith",
        description="Purge messages that ends with a given substring",
        example=",purge endswith st",
    )
    @has_permissions(manage_messages=True)
    async def purge_endswith(self, ctx, *, substring: str):
        def check(message: Message) -> bool:
            return message.content.endswith(substring)

        messages = [
            m async for m in ctx.channel.history() if m != ctx.message and check(m)
        ]
        if not messages:
            raise CommandError("No purgable messages found")
        await self.delete_messages(messages)
        return await ctx.send("\U0001f44d")

    @purge.command(
        name="reactions",
        description="Purge reactions from messages in chat",
    )
    @has_permissions(manage_messages=True)
    async def purge_reactions(self, ctx, search: Optional[int] = 100):
        def check(message: Message) -> bool:
            return True if message.reactions else False

        async def remove_reactions(messages: List[Message]) -> None:
            for message in messages:
                await message.clear_reactions()

        if task := self.tasks.get(f"purge-{ctx.guild.id}"):
            raise CommandError("A purge is already running in this server")
        messages = [
            m async for m in ctx.channel.history() if m != ctx.message and check(m)
        ]
        if not messages:
            raise CommandError("No purgable messages found")
        task = create_task(remove_reactions(messages))
        self.tasks[f"purge-{ctx.guild.id}"] = task
        await task
        self.tasks.pop(f"purge-{ctx.guild.id}", None)
        return await ctx.send("\U0001f44d")

    @purge.command(
        name="stickers",
        description="Purge stickers from chat",
    )
    @has_permissions(manage_messages=True)
    async def purge_stickers(self, ctx, search: Optional[int] = 100):
        def check(message: Message) -> bool:
            return True if message.stickers else False

        messages = [
            m async for m in ctx.channel.history() if m != ctx.message and check(m)
        ]
        if not messages:
            raise CommandError("No purgable messages found")
        await self.delete_messages(messages[:search])
        return await ctx.send("\U0001f44d")

    @purge.command(
        name="mentions",
        description="Purge mentions for a member from chat",
        example=",purge mentions jonathan 100",
    )
    @has_permissions(manage_messages=True)
    async def purge_mentions(
        self, ctx, member: Optional[Member] = None, search: Optional[int] = 100
    ):
        if member is None:

            def check(message: Message) -> bool:
                return True if message.mentions else False

        else:

            def check(message: Message) -> bool:
                return message.mentions and member in message.mentions

        messages = [
            m async for m in ctx.channel.history() if m != ctx.message and check(m)
        ]
        if not messages:
            raise CommandError("No purgable messages found")
        await self.delete_messages(messages[:search])
        return await ctx.send("\U0001f44d")

    @purge.command(
        name="emoji",
        description="Purge emojis from chat",
    )
    @has_permissions(manage_messages=True)
    async def purge_emoji(self, ctx, search: Optional[int] = 100):
        def check(message: Message) -> bool:
            return True if message.emojis else False

        messages = [
            m async for m in ctx.channel.history() if m != ctx.message and check(m)
        ]
        if not messages:
            raise CommandError("No purgable messages found")
        await self.delete_messages(messages[:search])
        return await ctx.send("\U0001f44d")

    @purge.command(
        name="emotes",
        description="Purge emotes from chat",
    )
    @has_permissions(manage_messages=True)
    async def purge_emotes(self, ctx, search: Optional[int] = 100):
        def check(message: Message) -> bool:
            return True if message.emojis else False

        messages = [
            m async for m in ctx.channel.history() if m != ctx.message and check(m)
        ]
        if not messages:
            raise CommandError("No purgable messages found")
        await self.delete_messages(messages[:search])
        return await ctx.send("\U0001f44d")

    @purge.command(
        name="upto",
        description="Purge messages up to a message link",
    )
    @has_permissions(manage_messages=True)
    async def purge_upto(self, ctx, messagelink: str):
        match = re.search(r"channels/\d+/(\d+)/(\d+)", messagelink)
        if not match:
            raise CommandError("Invalid message link")
        message_id = int(match.group(3))
        try:
            target = await ctx.channel.fetch_message(message_id)
        except discord.NotFound:
            raise CommandError("Message not found in this channel")

        messages = [
            m async for m in ctx.channel.history()
            if m != ctx.message and m.created_at >= target.created_at
        ]
        if not messages:
            raise CommandError("No purgable messages found")
        await self.delete_messages(messages)
        return await ctx.send("\U0001f44d")
