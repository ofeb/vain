from typing import Optional
from discord.ext.commands import group, has_permissions, CommandError, EmbedConverter, param, MessageLinkConverter
from discord import Embed, Webhook, Message
from core.discord.package import Package
from lib.classes.embed import Script
import string
import random


def make_token(length: int = 8) -> str:
    """generate short random id"""
    pool = string.ascii_lowercase + string.digits
    return "".join(random.choice(pool) for _ in range(length))


class WebhookCommands(Package):
    """webhook management commands"""

    @group(
        name="webhook",
        aliases=["webhooks", "wh"],
        description="Set up webhooks in your server",
        invoke_without_command=True,
    )
    async def webhook(self, ctx):
        """show webhook help"""
        return await ctx.send_help()

    @webhook.command(
        name="create",
        aliases=["c", "add", "setup", "a"],
        description="Create webhook to forward messages to",
        example=",webhook create purp",
    )
    @has_permissions(manage_webhooks=True)
    async def webhook_create(self, ctx, *, name: str):
        """make a new webhook"""
        wh = await ctx.channel.create_webhook(
            name=name, reason=f"Requested by {ctx.author}"
        )
        token = make_token()
        await self.db.execute(
            """INSERT INTO webhooks (guild_id, channel_id, id, name, url, created_by) VALUES($1, $2, $3, $4, $5, $6)""",
            ctx.guild.id,
            ctx.channel.id,
            token,
            name,
            wh.url,
            ctx.author.id,
        )
        return await ctx.success(
            f"Webhook `{token}` created in {ctx.channel.mention}. Save this id — you'll need it to edit webhook messages!"
        )

    @webhook.command(
        name="edit",
        aliases=["editmsg", "e"],
        description="Send message to existing channel webhook",
        example=",webhook edit https://discord.com/channels/... {embed}{description: yo}",
    )
    @has_permissions(manage_webhooks=True)
    async def webhook_edit(
        self,
        ctx,
        message: Message = param(
            converter=MessageLinkConverter, default=MessageLinkConverter.fallback
        ),
        embed_code: Optional[EmbedConverter] = None,
    ):
        """edit existing webhook message"""
        if not embed_code:
            raise CommandError("gotta provide an embed code")
        row = await self.db.fetchrow(
            """SELECT * FROM webhooks WHERE guild_id = $1 AND message_ids @> ARRAY[$2];""",
            ctx.guild.id,
            message.id,
        )
        if not row:
            raise CommandError(
                f"no webhook found for [that message]({message.jump_url})"
            )
        builder = Script(embed_code, ctx.author)
        await builder.compile()
        await builder.send(message)
        return await ctx.success(
            f"edited webhook message [`{message.id}`]({message.jump_url}) for `{row.id}`"
        )

    @webhook.command(
        name="delete",
        aliases=["del", "rem", "remove", "d", "r"],
        description="Delete webhook for a channel",
        example=",webhook delete tx53151",
    )
    @has_permissions(manage_webhooks=True)
    async def webhook_delete(self, ctx, identifier: str):
        """remove a webhook"""
        row = await self.db.fetchrow(
            """DELETE FROM webhooks WHERE guild_id = $1 AND id = $2 RETURNING *""",
            ctx.guild.id,
            identifier,
        )
        if not row:
            raise CommandError(f"no webhook found with id `{identifier}`")
        from ext.information.views import confirm
        prompt = await ctx.warning(
            f"you sure you wanna delete webhook `{identifier}`?"
        )
        confirmed = await confirm(self, ctx, prompt)
        if confirmed:
            ch = ctx.guild.get_channel(row.channel_id)
            wh = Webhook.from_url(
                row.url, client=self.bot, bot_token=self.bot.config["token"]
            )
            await wh.delete()
            return await ctx.success(
                f"deleted webhook for {ch.mention if ch else 'deleted channel'} (`{identifier}`)"
            )
        else:
            await prompt.delete()

    @webhook.command(
        name="send",
        description="Send message to existing channel webhook",
        example=",webhook send txru114 {embed}{description: sup}",
    )
    @has_permissions(manage_webhooks=True)
    async def webhook_send(self, ctx, identifier: str, embed_code: EmbedConverter):
        """send through existing webhook"""
        row = await self.db.fetchrow(
            """SELECT * FROM webhooks WHERE guild_id = $1 AND id = $2""",
            ctx.guild.id,
            identifier,
        )
        if not row:
            raise CommandError(f"no webhook found with id `{identifier}`")
        builder = Script(embed_code, ctx.author)
        await builder.compile()
        payload = await builder.data(True)
        wh = Webhook.from_url(
            row.url, client=self.bot, bot_token=self.bot.config["token"]
        )
        await wh.send(**payload)

    @webhook.command(
        name="list",
        aliases=["ls", "show", "view"],
        description="List all available webhooks in the server",
    )
    @has_permissions(manage_webhooks=True)
    async def webhook_list(self, ctx):
        """list server webhooks"""
        entries = await self.db.fetch(
            """SELECT id, created_by FROM webhooks WHERE guild_id = $1""",
            ctx.guild.id,
        )
        if not entries:
            raise CommandError("no webhooks exist in this server")
        lines = []
        for entry in entries:
            usr = self.bot.get_user(entry.created_by)
            if usr:
                lines.append(f"`{entry.id}` {usr.mention} — **{usr}**")
        return await ctx.paginate(
            Embed(title="Server Webhooks").set_author(
                name=str(ctx.author), icon_url=ctx.author.display_avatar.url
            ),
            lines,
        )
