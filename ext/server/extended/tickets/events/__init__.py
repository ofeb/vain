from __future__ import annotations

import json
from contextlib import suppress
from logging import getLogger
from typing import Any, Optional

import discord
from discord import (
    HTTPException,
    Interaction,
    Member,
    PermissionOverwrite,
    TextChannel,
)
from core.discord.views.embed import panel_container
from discord.utils import snowflake_time, utcnow

from core.discord.package import Package

from ..improper.views import TicketOpenView
from ..settings import Settings, TicketButton, TicketDropdownOption

logger = getLogger("tickets")


class TicketEvents(Package):
    @Package.listener("on_interaction")
    async def on_ticket_interaction(self, interaction: Interaction) -> None:
        if not interaction.data or not interaction.guild:
            return
        if not isinstance(interaction.user, Member):
            return

        custom_id = interaction.data.get("custom_id") or ""
        if not custom_id.startswith("ticket.create"):
            return

        if not interaction.guild.me.guild_permissions.manage_channels:
            embed = panel_container(
                color=0x2B2D31,
                lines=["I need the **Manage Channels** permission to open tickets."],
            )
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return

        component_type = interaction.data.get("component_type", 0)
        identifier = custom_id.rsplit(":", 1)[-1]

        settings = await Settings.fetch(self.bot, interaction.guild)
        if settings.is_blacklisted(interaction.user):
            embed = panel_container(
                color=0x2B2D31,
                lines=["You are not allowed to open tickets here."],
            )
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return

        record: Optional[TicketButton | TicketDropdownOption] = None
        if component_type == 2:
            record = await settings.fetch_button(identifier)
        elif component_type == 3:
            values = interaction.data.get("values") or []
            if values:
                record = await settings.fetch_dropdown_option(identifier, values[0])

        if not record:
            embed = panel_container(
                color=0x2B2D31,
                lines=["This control is no longer valid."],
            )
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return

        existing = await settings.fetch_user_open_ticket(identifier, interaction.user.id)
        if existing:
            ch = interaction.guild.get_channel(existing["channel_id"])
            if ch:
                embed = panel_container(
                    color=0x2B2D31,
                    lines=[f"You already have an open ticket: {ch.mention}"],
                )
                await interaction.response.send_message(embed=embed, ephemeral=True)
                return

        max_tickets = settings.record.get("max_tickets")
        if max_tickets:
            count = await settings.count_open_tickets()
            if count is not None and int(count) >= int(max_tickets):
                embed = panel_container(
                    color=0x2B2D31,
                    lines=[f"The server has reached the maximum of **{max_tickets}** open tickets."],
                )
                await interaction.response.send_message(embed=embed, ephemeral=True)
                return

        await interaction.response.defer(ephemeral=True, thinking=True)

        category = None
        cat_id = record.get("category_id")
        if cat_id:
            cat = interaction.guild.get_channel(int(cat_id))
            if isinstance(cat, discord.CategoryChannel):
                category = cat

        overwrites: dict[Any, PermissionOverwrite] = {
            interaction.guild.default_role: PermissionOverwrite(view_channel=False),
            interaction.user: PermissionOverwrite(
                view_channel=True,
                send_messages=True,
                attach_files=True,
                embed_links=True,
                read_message_history=True,
            ),
        }
        for role in settings.staff_roles:
            overwrites[role] = PermissionOverwrite(
                view_channel=True,
                send_messages=True,
                manage_messages=True,
                attach_files=True,
            )

        topic = (record.get("topic") or "")[:1024] or None
        try:
            channel = await interaction.guild.create_text_channel(
                name=f"ticket-{interaction.user.name}"[:100],
                category=category,
                overwrites=overwrites,
                topic=topic,
                reason=f"Ticket opened by {interaction.user} ({interaction.user.id})",
            )
        except HTTPException as exc:
            embed = panel_container(
                color=0x2B2D31,
                lines=[f"Could not create the channel: `{exc.text}`"],
            )
            await interaction.followup.send(embed=embed, ephemeral=True)
            return

        await settings.insert_open_ticket(
            identifier, channel.id, interaction.user.id
        )

        from ..improper.views import TicketControlView

        control = TicketControlView(self)
        await self._send_open_message(
            channel,
            interaction=interaction,
            settings=settings,
            record=record,
            view=control,
        )

        embed = panel_container(
            color=0x2B2D31,
            lines=[f"Your ticket has been created: {channel.mention}"],
        )
        await interaction.followup.send(embed=embed, ephemeral=True)
        logger.info(
            "Ticket %s opened by %s in %s",
            channel.id,
            interaction.user.id,
            interaction.guild.id,
        )

    @Package.listener("on_guild_channel_delete")
    async def on_ticket_channel_delete(
        self, channel: discord.abc.GuildChannel
    ) -> None:
        if not isinstance(channel, TextChannel):
            return
        settings = await Settings.fetch(self.bot, channel.guild)
        await settings.delete_open_ticket(channel.id)

    @Package.listener("on_ready")
    async def _restore_ticket_panels(self) -> None:
        if not getattr(self.bot, "db", None) or not self.bot.db.pool:
            return
        try:
            rows = await self.db.fetch(
                """
                SELECT p.id AS panel_id, p.panel_type, COALESCE(
                    json_agg(
                        json_build_object(
                            'id', o.id,
                            'name', o.name,
                            'label', o.label,
                            'emoji', o.emoji,
                            'description', o.description
                        )
                        ORDER BY o.position, o.id
                    ) FILTER (WHERE o.id IS NOT NULL),
                    '[]'::json
                ) AS options
                FROM ticket_panels p
                LEFT JOIN ticket_options o ON o.panel_id = p.id AND o.active = TRUE
                GROUP BY p.id, p.panel_type
                """
            )
        except Exception:
            return
        for row in rows:
            options = row["options"]
            if isinstance(options, str):
                options = json.loads(options)
            if not options:
                continue
            self.bot.add_view(TicketOpenView(self, int(row["panel_id"]), options, row["panel_type"]))

    async def _send_open_message(
        self,
        channel: TextChannel,
        *,
        interaction: Interaction,
        settings: Settings,
        record: dict,
        view: discord.ui.View,
    ) -> None:
        """Send welcome content - button template > guild open_embed > Vain default."""
        from config import color as _color

        DEFAULT_OPEN_TITLE = "Ticket Created"
        DEFAULT_OPEN_DESCRIPTION = "Staff will be with you shortly"

        user = interaction.user
        guild = interaction.guild
        template = (record.get("template") or settings.open_embed or "").strip()

        if template:
            try:
                await self.bot.send_embed(
                    channel,
                    template,
                    user=user,
                    member=user,
                    guild=guild,
                    channel=channel,
                    view=view,
                )
                return
            except TypeError:
                try:
                    msg = await self.bot.send_embed(
                        channel,
                        template,
                        user=user,
                        member=user,
                        guild=guild,
                        channel=channel,
                    )
                    with suppress(HTTPException):
                        await msg.edit(view=view)
                    return
                except Exception:
                    pass
            except Exception:
                content = (
                    template.replace("{user.mention}", user.mention)
                    .replace("{user.name}", getattr(user, "display_name", str(user)))
                    .replace("{user}", user.mention)
                    .replace("{channel}", channel.mention)
                    .replace("{guild}", guild.name if guild else "")
                )
                with suppress(HTTPException):
                    await channel.send(content=content, view=view)
                return

        embed = panel_container(
            title=DEFAULT_OPEN_TITLE,
            color=_color.base,
            lines=[DEFAULT_OPEN_DESCRIPTION],
        )
        with suppress(HTTPException):
            await channel.send(content=user.mention, embed=embed, view=view)