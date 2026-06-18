from discord.ext.commands import group, has_permissions, CommandError, EmbedConverter
from discord import Embed, Message, RawReactionActionEvent
from core.discord.package import Package
from lib.classes.embed import Script
from lib.classes.embed import embed_to_code


class PaginationCommands(Package):
    """embed pagination commands"""

    @group(
        name="pagination",
        aliases=["pn", "pages"],
        description="Set up multiple embeds on one message",
        invoke_without_command=True,
    )
    async def pagination(self, ctx):
        """pagination help"""
        return await ctx.send_help(ctx.command)

    @pagination.command(name="add", description="Add a page to a pagination embed")
    @has_permissions(manage_messages=True)
    async def pagination_add(self, ctx, message: Message, *, embed_code: EmbedConverter):
        """add new page"""
        row = await self.db.fetchrow(
            """SELECT * FROM pagination WHERE guild_id = $1 AND channel_id = $2 AND message_id = $3""",
            ctx.guild.id, message.channel.id, message.id,
        )
        if not row:
            raise CommandError("that message isnt a paginator")
        row.pages.append(embed_code)
        await self.db.execute(
            """UPDATE pagination SET pages = $1 WHERE guild_id = $2 AND channel_id = $3 AND message_id = $4""",
            row.pages, ctx.guild.id, message.channel.id, message.id,
        )
        return await ctx.success("page added")

    @pagination.command(name="update", description="Update an existing page on pagination embed")
    @has_permissions(manage_messages=True)
    async def pagination_update(
        self, ctx, message: Message, page_id: int, *, embed_code: EmbedConverter
    ):
        """update existing page"""
        row = await self.db.fetchrow(
            """SELECT * FROM pagination WHERE guild_id = $1 AND channel_id = $2 AND message_id = $3""",
            ctx.guild.id, message.channel.id, message.id,
        )
        if not row:
            raise CommandError("that message isnt a paginator")
        idx = page_id - 1 if page_id > 0 else page_id
        try:
            row.pages[idx] = embed_code
        except Exception:
            raise CommandError("that page doesnt exist")
        if row.current_page == idx:
            self.bot.dispatch("paginator_update", message, row, idx)
        await self.db.execute(
            """UPDATE pagination SET pages = $1 WHERE guild_id = $2 AND channel_id = $3 AND message_id = $4""",
            row.pages, ctx.guild.id, message.channel.id, message.id,
        )
        return await ctx.success("page updated")

    @pagination.command(name="reset", aliases=["clear"], description="Remove every existing pagination in guild")
    @has_permissions(administrator=True)
    async def pagination_reset(self, ctx):
        """wipe server paginators"""
        await self.db.execute(
            """DELETE FROM pagination WHERE guild_id = $1""", ctx.guild.id
        )
        return await ctx.success("all paginators cleared")

    @pagination.command(name="list", aliases=["ls", "show", "view"], description="View all existing pagination embeds")
    @has_permissions(manage_messages=True)
    async def pagination_list(self, ctx):
        """list paginators"""
        entries = await self.db.fetch(
            """SELECT * FROM pagination WHERE guild_id = $1""", ctx.guild.id
        )
        if not entries:
            raise CommandError("no paginators set up")
        embed = Embed(title="Pagination Embeds").set_author(
            name=str(ctx.author), icon_url=ctx.author.display_avatar.url
        )
        rows = [
            f"`{i}` [{p.message_id}](https://discordapp.com/channels/{p.guild_id}/{p.channel_id}/{p.message_id}) - <@!{p.creator_id}> (`{len(p.pages)}`)"
            for i, p in enumerate(entries, start=1)
        ]
        if not rows:
            raise CommandError("no paginators set up")
        return await ctx.paginate(embed, rows)

    @pagination.command(name="restorereactions", aliases=["rr"], description="Restore reactions to an existing pagination")
    @has_permissions(manage_messages=True)
    async def pagination_restorereactions(self, ctx, message: Message):
        """restore paginator reactions"""
        row = await self.db.fetchrow(
            """SELECT * FROM pagination WHERE guild_id = $1 AND channel_id = $2 AND message_id = $3""",
            ctx.guild.id, message.channel.id, message.id,
        )
        if not row:
            raise CommandError("that message isnt a paginator")
        await message.add_reaction("⬅️")
        await message.add_reaction("➡️")
        return await ctx.message.add_reaction(":white_check_mark:")

    @pagination.command(name="set", description="Set up an existing embed to be paginated")
    @has_permissions(manage_messages=True)
    async def pagination_set(self, ctx, message: Message):
        """convert embed to paginator"""
        try:
            base = message.embeds[0]
            code = embed_to_code(base, message.content)
            base.set_footer(text="Page 1 of 1")
            await message.edit(embed=base)
        except Exception:
            raise CommandError("cant edit that message")
        await self.db.execute(
            """INSERT INTO pagination (guild_id, message_id, channel_id, creator_id, pages) VALUES($1, $2, $3, $4, $5)""",
            ctx.guild.id, message.id, message.channel.id, ctx.author.id, [code],
        )
        return await ctx.success(
            f"[`{message.id}`]({message.jump_url}) is now a **pagination embed**"
        )

    @pagination.command(name="delete", description="Delete a pagination embed entirely")
    @has_permissions(manage_messages=True)
    async def pagination_delete(self, ctx, message: Message):
        """delete a paginator"""
        row = await self.db.fetchrow(
            """SELECT * FROM pagination WHERE guild_id = $1 AND channel_id = $2 AND message_id = $3""",
            ctx.guild.id, message.channel.id, message.id,
        )
        if not row:
            raise CommandError("that message isnt a paginator")
        await self.db.execute(
            """DELETE FROM pagination WHERE guild_id = $1 AND channel_id = $2 AND message_id = $3""",
            ctx.guild.id, message.channel.id, message.id,
        )
        return await ctx.success(
            f"deleted paginator [`{message.id}`]({message.jump_url})"
        )

    @pagination.command(name="remove", description="Remove a page from a pagination embed")
    @has_permissions(manage_messages=True)
    async def pagination_remove(self, ctx, message: Message, page_id: int):
        """drop a page"""
        row = await self.db.fetchrow(
            """SELECT * FROM pagination WHERE guild_id = $1 AND channel_id = $2 AND message_id = $3""",
            ctx.guild.id, message.channel.id, message.id,
        )
        if not row:
            raise CommandError("that message isnt a paginator")
        idx = page_id - 1 if page_id > 0 else page_id
        try:
            row.pages.pop(idx)
        except IndexError:
            raise CommandError("that page doesnt exist")
        if not row.pages:
            await self.db.execute(
                """DELETE FROM pagination WHERE guild_id = $1 AND channel_id = $2 AND message_id = $3""",
                ctx.guild.id,
                message.channel.id,
                message.id,
            )
            return await ctx.success(
                f"removed the last page and deleted [`{message.id}`]({message.jump_url})"
            )

        current_page = min(row.current_page, len(row.pages) - 1)
        await self.db.execute(
            """UPDATE pagination SET pages = $1, current_page = $2 WHERE guild_id = $3 AND channel_id = $4 AND message_id = $5""",
            row.pages,
            current_page,
            ctx.guild.id,
            message.channel.id,
            message.id,
        )
        if row.current_page == idx:
            self.bot.dispatch("paginator_update", message, row, current_page)
        return await ctx.success(
            f"removed page **{page_id}** from [`{message.id}`]({message.jump_url})"
        )

    async def on_raw_reaction_add(self, payload: RawReactionActionEvent):
        """handle paginator reaction"""
        if payload.user_id == self.bot.user.id:
            return
        if not payload.guild_id:
            return
        guild = self.bot.get_guild(payload.guild_id)
        if not guild:
            return
        channel = guild.get_channel(payload.channel_id)
        if not channel:
            return
        row = await self.bot.db.fetchrow(
            """SELECT * FROM pagination WHERE guild_id = $1 AND channel_id = $2 AND message_id = $3""",
            payload.guild_id, payload.channel_id, payload.message_id,
        )
        if not row:
            return
        msg = await channel.fetch_message(payload.message_id)
        emoji = str(payload.emoji)
        if emoji == "⬅️":
            page = row.current_page - 1
        elif emoji == "➡️":
            page = row.current_page + 1
        else:
            return
        self.bot.dispatch("paginator_update", msg, row, page)

    async def on_paginator_update(self, message: Message, row, page: int):
        """render a new page"""
        if not message.channel:
            return
        if page >= len(row.pages):
            page = 0
        try:
            idx = page - 1 if page > 0 else page
            script = Script(row.pages[idx], self.bot.user)
            await self.bot.db.execute(
                """UPDATE pagination SET current_page = $1 WHERE guild_id = $2 AND channel_id = $3 AND message_id = $4""",
                idx, message.guild.id, message.channel.id, message.id,
            )
            payload = await script.data(True)
            await message.edit(**payload)
            for rxn in message.reactions:
                users = [u async for u in rxn.users() if u.id != self.bot.user.id]
                for usr in users:
                    await rxn.remove(usr)
        except Exception:
            pass
