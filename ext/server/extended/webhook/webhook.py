from __future__ import annotations

import contextlib
import re

import aiohttp
import discord
from discord.ext import commands
from discord.ext.commands import CommandError, group, has_permissions

from core.discord.package import Package
from lib.classes.embed import Script

SPACE_RE = re.compile(r"\s+")
DISCORD_NAME_RE = re.compile("discord", re.IGNORECASE)
CLYDE_NAME_RE = re.compile("clyde", re.IGNORECASE)
FORBIDDEN_NAME_RE = re.compile(r"[@#:`]")
WEBHOOK_NAME_MAX = 80


def _sanitize_webhook_name(name: str) -> str:
    cleaned = FORBIDDEN_NAME_RE.sub("", name)
    cleaned = DISCORD_NAME_RE.sub("discrd", cleaned)
    cleaned = CLYDE_NAME_RE.sub("clyd", cleaned)
    if cleaned.casefold() in {"everyone", "here"}:
        cleaned = f"{cleaned}-hook"
    return cleaned[:WEBHOOK_NAME_MAX]


class WebhookCommands(Package):
    """server webhook management."""

    def _normalize_name(self, name: str) -> str:
        return SPACE_RE.sub("", name.strip().lower())

    async def _resolve_webhook(self, ctx, identifier: str):
        token = identifier.strip()
        record = None
        if token.isdigit():
            record = await self.db.fetch_webhook_by_id(ctx.guild.id, int(token))
        if record is None:
            record = await self.db.fetch_webhook_by_name(
                ctx.guild.id,
                _sanitize_webhook_name(self._normalize_name(token)),
            )
        return record

    def _is_locked_for(self, ctx, record) -> bool:
        return bool(record["locked"]) and int(record["owner_id"]) != ctx.author.id

    async def _get_replied_message(self, ctx) -> discord.Message | None:
        reference = getattr(ctx.message, "reference", None)
        message_id = getattr(reference, "message_id", None)
        if not message_id:
            return None

        resolved = getattr(reference, "resolved", None)
        if isinstance(resolved, discord.Message):
            return resolved

        with contextlib.suppress(commands.BadArgument):
            return await commands.MessageConverter().convert(ctx, str(message_id))
        return None

    async def _webhook_client(self, record):
        url = f"https://discord.com/api/webhooks/{record['webhook_id']}/{record['token']}"
        session = aiohttp.ClientSession()
        return session, discord.Webhook.from_url(url, session=session)

    @group(
        name="webhook",
        description="set up webhooks in your server",
        invoke_without_command=True,
    )
    async def webhook(self, ctx):
        """show webhook help"""
        return await ctx.send_help()

    @webhook.command(
        name="create",
        description="create webhook to forward messages to",
        example=",webhook create updates",
    )
    @has_permissions(manage_webhooks=True)
    async def webhook_create(self, ctx, *, name: str):
        if not isinstance(ctx.channel, discord.TextChannel):
            raise CommandError("webhooks can only be created in text channels")

        clean_name = self._normalize_name(name)
        if not clean_name:
            raise CommandError("provide a webhook name")
        storage_name = _sanitize_webhook_name(clean_name)
        if not storage_name:
            raise CommandError("that webhook name becomes empty after sanitizing")
        if await self.db.fetch_webhook_by_name(ctx.guild.id, storage_name):
            raise CommandError("that webhook already exists")

        try:
            webhook = await ctx.channel.create_webhook(
                name=storage_name,
                reason=f"webhook created by {ctx.author}",
            )
        except discord.HTTPException as exc:
            if getattr(exc, "code", None) == 50035:
                raise CommandError(
                    "discord rejected that webhook name; avoid reserved names, `discord`, `clyde`, and special characters like `@`, `#`, `:`, and `` ` ``"
                ) from exc
            raise

        await self.db.add_webhook(
            ctx.guild.id,
            storage_name,
            ctx.channel.id,
            webhook.id,
            webhook.token or "",
            ctx.author.id,
        )

        note = ""
        if storage_name != clean_name:
            note = f" (sanitized from `{clean_name}`)"
        await ctx.success(
            f"created webhook **{storage_name}** for {ctx.channel.mention}{note}"
        )

    @webhook.command(
        name="list",
        description="list all available webhooks in the server",
    )
    @has_permissions(manage_webhooks=True)
    async def webhook_list(self, ctx):
        rows = await self.db.list_webhooks(ctx.guild.id)
        if not rows:
            raise CommandError("no webhooks found")

        lines = []
        for index, row in enumerate(rows, start=1):
            channel = ctx.guild.get_channel(int(row["channel_id"]))
            channel_label = channel.mention if channel else f"`{row['channel_id']}`"
            locked = " (locked)" if row["locked"] else ""
            lines.append(
                f"`{index:02d}` **{row['name']}** - {channel_label} (`{row['webhook_id']}`){locked}"
            )

        embed = discord.Embed(title="Webhooks", color=self.color)
        embed.set_author(name=str(ctx.author), icon_url=ctx.author.display_avatar.url)
        await ctx.paginate(embed, lines)

    @webhook.command(
        name="send",
        aliases=["message"],
        description="send message to existing channel webhook",
        example=",webhook send updates hello",
    )
    @has_permissions(manage_webhooks=True)
    async def webhook_send(self, ctx, identifier: str, *, message: str):
        record = await self._resolve_webhook(ctx, identifier)
        if not record:
            raise CommandError("webhook not found")
        if self._is_locked_for(ctx, record):
            raise CommandError("that webhook is locked")

        builder = Script(message, ctx.author)
        await builder.compile(user=ctx.author, guild=ctx.guild, channel=ctx.channel)
        payload = await builder.data(
            True,
            user=ctx.author,
            guild=ctx.guild,
            channel=ctx.channel,
            allowed_mentions=discord.AllowedMentions.none(),
        )

        session, webhook = await self._webhook_client(record)
        try:
            await webhook.send(**payload)
        finally:
            await session.close()

        await ctx.success(f"sent webhook **{record['name']}**")

    @webhook.command(
        name="edit",
        aliases=["editmessage"],
        description="edit an existing webhook message",
        example=",webhook edit <message link> hello",
    )
    @has_permissions(manage_webhooks=True)
    async def webhook_edit(
        self,
        ctx,
        message_link: str | None = None,
        *,
        message: str | None = None,
    ):
        target = None
        content = message

        if message_link:
            with contextlib.suppress(commands.BadArgument):
                target = await commands.MessageConverter().convert(ctx, message_link)
            if target is None:
                replied = await self._get_replied_message(ctx)
                if replied is None:
                    raise CommandError("invalid message link")
                target = replied
                content = f"{message_link} {message or ''}".strip()
        else:
            target = await self._get_replied_message(ctx)

        if target is None or not content:
            return await ctx.send_help()
        if not target.webhook_id:
            raise CommandError("that message was not sent by a webhook")

        record = await self.db.fetch_webhook_by_id(ctx.guild.id, int(target.webhook_id))
        if not record:
            raise CommandError("webhook not found")
        if self._is_locked_for(ctx, record):
            raise CommandError("that webhook is locked")

        builder = Script(content, ctx.author)
        await builder.compile(user=ctx.author, guild=ctx.guild, channel=ctx.channel)
        payload = await builder.data(
            True,
            user=ctx.author,
            guild=ctx.guild,
            channel=ctx.channel,
            allowed_mentions=discord.AllowedMentions.none(),
        )

        session, webhook = await self._webhook_client(record)
        try:
            await webhook.edit_message(target.id, **payload)
        finally:
            await session.close()

        await ctx.success(f"updated webhook **{record['name']}**")

    @webhook.command(
        name="delete",
        aliases=["remove", "del"],
        description="delete webhook for a channel",
        example=",webhook delete updates",
    )
    @has_permissions(manage_webhooks=True)
    async def webhook_delete(self, ctx, *, identifier: str):
        record = await self._resolve_webhook(ctx, identifier)
        if not record:
            raise CommandError("webhook not found")
        if self._is_locked_for(ctx, record):
            raise CommandError("that webhook is locked")

        session, webhook = await self._webhook_client(record)
        try:
            await webhook.delete(reason=f"webhook removed by {ctx.author}")
        finally:
            await session.close()

        await self.db.remove_webhook(ctx.guild.id, record["name"])
        await ctx.success(f"deleted webhook **{record['name']}**")

    @webhook.command(
        name="lock",
        description="lock your webhook from being accessed by others",
    )
    @has_permissions(manage_webhooks=True)
    async def webhook_lock(self, ctx, *, identifier: str):
        record = await self._resolve_webhook(ctx, identifier)
        if not record:
            raise CommandError("webhook not found")
        if int(record["owner_id"]) != ctx.author.id:
            raise CommandError("only the webhook owner can lock it")

        await self.db.set_webhook_lock(ctx.guild.id, record["name"], True)
        await ctx.success(f"locked webhook **{record['name']}**")

    @webhook.command(
        name="unlock",
        description="unlock your webhook from being accessed by others",
    )
    @has_permissions(manage_webhooks=True)
    async def webhook_unlock(self, ctx, *, identifier: str):
        record = await self._resolve_webhook(ctx, identifier)
        if not record:
            raise CommandError("webhook not found")
        if int(record["owner_id"]) != ctx.author.id:
            raise CommandError("only the webhook owner can unlock it")

        await self.db.set_webhook_lock(ctx.guild.id, record["name"], False)
        await ctx.success(f"unlocked webhook **{record['name']}**")
