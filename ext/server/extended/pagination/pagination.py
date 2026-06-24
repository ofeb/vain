from discord.ext.commands import group, CommandError
from discord import Message

from core.discord.package import Package
from core.managers.converters import EmbedConverter
from core.managers.permissions import has_permissions

from .views import embed_script_from_message, sync_stored_pagination


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
            """
            SELECT pages, current_page
            FROM pagination
            WHERE guild_id = $1 AND channel_id = $2 AND message_id = $3
            """,
            ctx.guild.id,
            message.channel.id,
            message.id,
        )
        if not row:
            raise CommandError("that message isnt a paginator")
        pages = list(row["pages"] or [])
        pages.append(embed_code)
        current_page = int(row["current_page"] or 0)
        await self.db.execute(
            """
            UPDATE pagination SET pages = $1
            WHERE guild_id = $2 AND channel_id = $3 AND message_id = $4
            """,
            pages,
            ctx.guild.id,
            message.channel.id,
            message.id,
        )
        await sync_stored_pagination(
            self.bot,
            guild_id=ctx.guild.id,
            channel_id=message.channel.id,
            message=message,
            pages=pages,
            current_page=current_page,
        )
        return await ctx.success("page added")

    @pagination.command(name="update", description="Update an existing page on pagination embed")
    @has_permissions(manage_messages=True)
    async def pagination_update(
        self, ctx, message: Message, page_id: int, *, embed_code: EmbedConverter
    ):
        """update existing page"""
        row = await self.db.fetchrow(
            """
            SELECT pages, current_page
            FROM pagination
            WHERE guild_id = $1 AND channel_id = $2 AND message_id = $3
            """,
            ctx.guild.id,
            message.channel.id,
            message.id,
        )
        if not row:
            raise CommandError("that message isnt a paginator")
        pages = list(row["pages"] or [])
        idx = page_id - 1 if page_id > 0 else page_id
        try:
            pages[idx] = embed_code
        except IndexError:
            raise CommandError("that page doesnt exist")
        current_page = int(row["current_page"] or 0)
        await self.db.execute(
            """
            UPDATE pagination SET pages = $1
            WHERE guild_id = $2 AND channel_id = $3 AND message_id = $4
            """,
            pages,
            ctx.guild.id,
            message.channel.id,
            message.id,
        )
        await sync_stored_pagination(
            self.bot,
            guild_id=ctx.guild.id,
            channel_id=message.channel.id,
            message=message,
            pages=pages,
            current_page=current_page if current_page != idx else idx,
        )
        return await ctx.success("page updated")

    @pagination.command(name="reset", aliases=["clear"], description="Remove every existing pagination in guild")
    @has_permissions(administrator=True)
    async def pagination_reset(self, ctx):
        """wipe server paginators"""
        await self.db.execute(
            """DELETE FROM pagination WHERE guild_id = $1""",
            ctx.guild.id,
        )
        return await ctx.success("all paginators cleared")

    @pagination.command(name="list", aliases=["ls", "show", "view"], description="View all existing pagination embeds")
    @has_permissions(manage_messages=True)
    async def pagination_list(self, ctx):
        """list paginators"""
        entries = await self.db.fetch(
            """SELECT * FROM pagination WHERE guild_id = $1""",
            ctx.guild.id,
        )
        if not entries:
            raise CommandError("no paginators set up")
        from discord import Embed

        embed = Embed(title="Pagination Embeds").set_author(
            name=str(ctx.author),
            icon_url=ctx.author.display_avatar.url,
        )
        rows = [
            f"`{i}` [{p.message_id}](https://discordapp.com/channels/{p.guild_id}/{p.channel_id}/{p.message_id}) - <@!{p.creator_id}> (`{len(p.pages)}`)"
            for i, p in enumerate(entries, start=1)
        ]
        if not rows:
            raise CommandError("no paginators set up")
        return await ctx.paginate(embed, rows)

    @pagination.command(
        name="restorereactions",
        aliases=["rr", "restore"],
        description="Restore pagination buttons on an existing pagination embed",
    )
    @has_permissions(manage_messages=True)
    async def pagination_restorereactions(self, ctx, message: Message):
        """restore paginator buttons"""
        row = await self.db.fetchrow(
            """
            SELECT pages, current_page
            FROM pagination
            WHERE guild_id = $1 AND channel_id = $2 AND message_id = $3
            """,
            ctx.guild.id,
            message.channel.id,
            message.id,
        )
        if not row:
            raise CommandError("that message isnt a paginator")
        pages = list(row["pages"] or [])
        if len(pages) <= 1:
            raise CommandError("that paginator only has **one page**")
        await sync_stored_pagination(
            self.bot,
            guild_id=ctx.guild.id,
            channel_id=message.channel.id,
            message=message,
            pages=pages,
            current_page=int(row["current_page"] or 0),
        )
        return await ctx.success("pagination buttons restored")

    @pagination.command(name="set", description="Set up an existing embed to be paginated")
    @has_permissions(manage_messages=True)
    async def pagination_set(self, ctx, message: Message):
        """convert embed to paginator"""
        try:
            code = embed_script_from_message(message)
        except ValueError:
            raise CommandError("cant edit that message")
        pages = [code]
        await self.db.execute(
            """
            INSERT INTO pagination (guild_id, message_id, channel_id, creator_id, pages)
            VALUES($1, $2, $3, $4, $5)
            ON CONFLICT (guild_id, channel_id, message_id) DO UPDATE
            SET pages = EXCLUDED.pages, creator_id = EXCLUDED.creator_id, current_page = 0
            """,
            ctx.guild.id,
            message.id,
            message.channel.id,
            ctx.author.id,
            pages,
        )
        await sync_stored_pagination(
            self.bot,
            guild_id=ctx.guild.id,
            channel_id=message.channel.id,
            message=message,
            pages=pages,
            current_page=0,
        )
        return await ctx.success(
            f"[`{message.id}`]({message.jump_url}) is now a **pagination embed**"
        )

    @pagination.command(name="delete", description="Delete a pagination embed entirely")
    @has_permissions(manage_messages=True)
    async def pagination_delete(self, ctx, message: Message):
        """delete a paginator"""
        row = await self.db.fetchrow(
            """
            SELECT * FROM pagination
            WHERE guild_id = $1 AND channel_id = $2 AND message_id = $3
            """,
            ctx.guild.id,
            message.channel.id,
            message.id,
        )
        if not row:
            raise CommandError("that message isnt a paginator")
        await self.db.execute(
            """
            DELETE FROM pagination
            WHERE guild_id = $1 AND channel_id = $2 AND message_id = $3
            """,
            ctx.guild.id,
            message.channel.id,
            message.id,
        )
        await message.edit(view=None)
        return await ctx.success(
            f"deleted paginator [`{message.id}`]({message.jump_url})"
        )

    @pagination.command(name="remove", description="Remove a page from a pagination embed")
    @has_permissions(manage_messages=True)
    async def pagination_remove(self, ctx, message: Message, page_id: int):
        """drop a page"""
        row = await self.db.fetchrow(
            """
            SELECT pages, current_page
            FROM pagination
            WHERE guild_id = $1 AND channel_id = $2 AND message_id = $3
            """,
            ctx.guild.id,
            message.channel.id,
            message.id,
        )
        if not row:
            raise CommandError("that message isnt a paginator")
        pages = list(row["pages"] or [])
        idx = page_id - 1 if page_id > 0 else page_id
        try:
            pages.pop(idx)
        except IndexError:
            raise CommandError("that page doesnt exist")
        if not pages:
            await self.db.execute(
                """
                DELETE FROM pagination
                WHERE guild_id = $1 AND channel_id = $2 AND message_id = $3
                """,
                ctx.guild.id,
                message.channel.id,
                message.id,
            )
            await message.edit(view=None)
            return await ctx.success(
                f"removed the last page and deleted [`{message.id}`]({message.jump_url})"
            )

        current_page = min(int(row["current_page"] or 0), len(pages) - 1)
        if idx < current_page:
            current_page = max(0, current_page - 1)
        elif idx == current_page:
            current_page = min(current_page, len(pages) - 1)
        await self.db.execute(
            """
            UPDATE pagination
            SET pages = $1, current_page = $2
            WHERE guild_id = $3 AND channel_id = $4 AND message_id = $5
            """,
            pages,
            current_page,
            ctx.guild.id,
            message.channel.id,
            message.id,
        )
        await sync_stored_pagination(
            self.bot,
            guild_id=ctx.guild.id,
            channel_id=message.channel.id,
            message=message,
            pages=pages,
            current_page=current_page,
        )
        return await ctx.success(
            f"removed page **{page_id}** from [`{message.id}`]({message.jump_url})"
        )
