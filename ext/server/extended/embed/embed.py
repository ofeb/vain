from __future__ import annotations

import re
from typing import TYPE_CHECKING

import discord
from discord.ext.commands import CommandError

from core.discord.ctx import Context
from core.discord.hybrid import describe, hybrid
from core.discord.package import Package
from core.managers.permissions import has_permissions
from core.managers.values import color
from core.tools.aesthetic import aesthetic_embed, body

if TYPE_CHECKING:
    from core.vain import Vain


class EmbedCommands(Package):
    """saved embed templates and management"""

    @hybrid(
        name="embed",
        description="Create and manage saved embed templates",
        group=True,
        aliases=["savedembed"],
        guild_only=True,
    )
    @has_permissions(manage_messages=True)
    async def embed(self, ctx: Context) -> None:
        if ctx.invoked_subcommand is None:
            await ctx.send_help(ctx.command)

    @embed.command(
        name="create",
        description="Save an embed script as a template",
        aliases=["add", "save"],
    )
    @describe(name="Template name", script="Embed script to save")
    async def embed_create(self, ctx: Context, name: str, *, script: str) -> None:
        name = name.lower().strip()
        if not re.fullmatch(r"[a-z0-9_-]{1,50}", name):
            return await ctx.warn("Name must be **1-50** characters: letters, numbers, `_`, `-`.")
        await self.db.execute(
            """
            INSERT INTO saved_embeds (guild_id, name, script, author_id)
            VALUES ($1, $2, $3, $4)
            ON CONFLICT (guild_id, name)
            DO UPDATE SET script = EXCLUDED.script, author_id = EXCLUDED.author_id, updated_at = NOW()
            """,
            ctx.guild.id,
            name,
            script,
            ctx.author.id,
        )
        await ctx.success(f"Saved embed template **`{name}`**.")

    @embed.command(
        name="edit",
        description="Edit a saved embed template",
        aliases=["update"],
    )
    @describe(name="Template name", script="New embed script")
    async def embed_edit(self, ctx: Context, name: str, *, script: str) -> None:
        name = name.lower().strip()
        row = await self.db.fetchrow(
            "SELECT name FROM saved_embeds WHERE guild_id = $1 AND name = $2",
            ctx.guild.id,
            name,
        )
        if not row:
            return await ctx.warn(f"No embed template named **`{name}`**.")
        await self.db.execute(
            """
            UPDATE saved_embeds
            SET script = $3, author_id = $4, updated_at = NOW()
            WHERE guild_id = $1 AND name = $2
            """,
            ctx.guild.id,
            name,
            script,
            ctx.author.id,
        )
        await ctx.success(f"Updated embed template **`{name}`**.")

    @embed.command(name="list", description="List saved embed templates")
    async def embed_list(self, ctx: Context) -> None:
        rows = await self.db.fetch(
            "SELECT name, author_id, updated_at FROM saved_embeds WHERE guild_id = $1 ORDER BY name",
            ctx.guild.id,
        )
        if not rows:
            return await ctx.warn("No saved embed templates yet.")
        lines = [
            f"**`{row['name']}`** — <@{row['author_id']}> ({discord.utils.format_dt(row['updated_at'], style='R')})"
            for row in rows
        ]
        embed = discord.Embed(
            title=f"Saved Embeds ({len(lines)})",
            description=body(*lines[:40]),
            color=color.base,
            timestamp=discord.utils.utcnow(),
        )
        await ctx.send(embed=embed)

    @embed.command(name="preview", description="Preview a saved embed or raw script")
    @describe(target="Template name or raw embed script")
    async def embed_preview(self, ctx: Context, *, target: str) -> None:
        row = await self.db.fetchrow(
            "SELECT script FROM saved_embeds WHERE guild_id = $1 AND name = $2",
            ctx.guild.id,
            target.lower().strip(),
        )
        script = row["script"] if row else target
        await self._send_embed_script(ctx, script)

    @embed.command(name="send", description="Send a saved embed template")
    @describe(name="Template name")
    async def embed_send(self, ctx: Context, name: str) -> None:
        row = await self.db.fetchrow(
            "SELECT script FROM saved_embeds WHERE guild_id = $1 AND name = $2",
            ctx.guild.id,
            name.lower().strip(),
        )
        if not row:
            return await ctx.warn(f"No embed template named **`{name}`**.")
        await self._send_embed_script(ctx, row["script"])

    @embed.command(name="copy", description="Copy embed code from a message link")
    @describe(message="Discord message link")
    async def embed_copy(self, ctx: Context, *, message: str) -> None:
        channel_id, message_id = self._parse_message_link(message)
        channel = ctx.guild.get_channel(channel_id)
        if not channel:
            return await ctx.warn("Could not find that channel.")
        try:
            msg = await channel.fetch_message(message_id)
        except discord.NotFound:
            return await ctx.warn("Message not found.")
        except discord.HTTPException:
            return await ctx.warn("Could not fetch that message.")
        if not msg.embeds:
            return await ctx.warn("That message has no embeds.")
        code = self._embed_to_code(msg.embeds[0])
        if len(code) > 2000:
            return await ctx.warn("Embed code is too long to send here.")
        await ctx.send(embed=aesthetic_embed(
            color=color.base,
            title="Embed Code",
            message=f"```{code}```",
            timestamp=False,
        ))

    @embed.command(name="delete", description="Delete a saved embed template", aliases=["remove"])
    @describe(name="Template name")
    async def embed_delete(self, ctx: Context, name: str) -> None:
        name = name.lower().strip()
        result = await self.db.execute(
            "DELETE FROM saved_embeds WHERE guild_id = $1 AND name = $2",
            ctx.guild.id,
            name,
        )
        if result == "DELETE 0":
            return await ctx.warn(f"No embed template named **`{name}`**.")
        await ctx.success(f"Deleted embed template **`{name}`**.")

    @hybrid(
        name="editembed",
        description="Edit a saved embed template",
        aliases=["embededit"],
        guild_only=True,
    )
    @describe(name="Template name", script="New embed script")
    @has_permissions(manage_messages=True)
    async def editembed(self, ctx: Context, name: str, *, script: str) -> None:
        await self.embed_edit(ctx, name, script=script)

    def _parse_message_link(self, link: str) -> tuple[int, int]:
        pattern = r"discord(?:app)?\.com/channels/(\d+)/(\d+)/(\d+)"
        match = re.search(pattern, link)
        if not match:
            raise CommandError("Invalid message link.")
        return int(match.group(2)), int(match.group(3))

    def _embed_to_code(self, embed: discord.Embed) -> str:
        lines = ["{embed}"]
        if embed.title:
            lines.append(f"{{title: {embed.title}}}")
        if embed.description:
            lines.append(f"{{description: {embed.description}}}")
        if embed.color:
            lines.append(f"{{color: #{embed.color.value:06x}}}")
        if embed.author and embed.author.name:
            author_text = embed.author.name
            if embed.author.url:
                author_text += f" | {embed.author.url}"
            if embed.author.icon_url:
                author_text += f" | {embed.author.icon_url}"
            lines.append(f"{{author: {author_text}}}")
        if embed.footer and embed.footer.text:
            footer_text = embed.footer.text
            if embed.footer.icon_url:
                footer_text += f" | {embed.footer.icon_url}"
            lines.append(f"{{footer: {footer_text}}}")
        if embed.image:
            lines.append(f"{{image: {embed.image.url}}}")
        if embed.thumbnail:
            lines.append(f"{{thumbnail: {embed.thumbnail.url}}}")
        for field in embed.fields:
            lines.append(f"{{field: {field.name} | {field.value or ''} | {str(field.inline).lower()}}}")
        return "\n".join(lines)
