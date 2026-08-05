from __future__ import annotations

import json
from contextlib import suppress
from logging import getLogger
from typing import Any, Literal, Optional, Union

import discord
from discord import (
    ButtonStyle,
    CategoryChannel,
    Embed,
    HTTPException,
    Interaction,
    Member,
    Message,
    PermissionOverwrite,
    Role,
    SelectOption,
    TextChannel,
    Thread,
)
from discord.ext.commands import Cog, group, command
from discord.ext.tasks import loop
from discord.ui import Button, Select, View
from discord.utils import snowflake_time, utcnow

from core.discord.package import Package
from core.managers.permissions import has_permissions

from .checks import in_ticket, staff
from .settings import Settings, Ticket, TicketButton, TicketDropdownOption
from .transcript import Transcript

logger = getLogger("tickets")

STYLE_MAP = {
    "blurple": ButtonStyle.primary,
    "grey": ButtonStyle.secondary,
    "gray": ButtonStyle.secondary,
    "green": ButtonStyle.success,
    "red": ButtonStyle.danger,
}


def _ephemeral(interaction: Interaction, content: str, *, followup: bool = False):
    embed = Embed(color=0x2B2D31, description=content)
    if followup:
        return interaction.followup.send(embed=embed, ephemeral=True)
    return interaction.response.send_message(embed=embed, ephemeral=True)


class TicketPanelView(View):
    """Dynamic view rebuilt from the current panel message components."""

    def __init__(self):
        super().__init__(timeout=None)


# ─────────────────────────────────────────────────────────────
# Main Package
# ─────────────────────────────────────────────────────────────

class Tickets(Package):
    """Ticket system – panels, buttons, dropdowns, staff tools & transcripts."""

    def __init__(self, bot):
        super().__init__(bot)
        self.description = "Full ticket system with panels, staff controls and transcripts"

    async def cog_load(self) -> None:
        # ensure schema on every load
        await self._ensure_schema()
        self._inactivity_loop.start()
        await super().cog_load()

    async def cog_unload(self) -> None:
        self._inactivity_loop.cancel()
        await super().cog_unload()

    async def _ensure_schema(self) -> None:
        """Create / migrate ticket tables if they are missing."""
        schema_path = __file__.replace("__init__.py", "schema.sql")
        try:
            with open(schema_path, "r", encoding="utf-8") as f:
                sql = f.read()
            # run each statement separately for safety
            for stmt in sql.split(";"):
                stmt = stmt.strip()
                if stmt:
                    await self.db.execute(stmt)
            logger.info("Ticket schema synchronized")
        except Exception as exc:
            logger.warning("Could not fully sync ticket schema: %s", exc)

    # ── inactivity sweeper ───────────────────────────────────

    @loop(minutes=5)
    async def _inactivity_loop(self) -> None:
        rows = await self.db.fetch(
            """
            SELECT o.channel_id, s.inactivity_timeout
            FROM tickets.open o
            JOIN tickets.settings s ON o.guild_id = s.guild_id
            WHERE s.inactivity_timeout IS NOT NULL
            """
        )
        to_delete: list[int] = []
        for row in rows:
            timeout = row["inactivity_timeout"]
            if not timeout:
                continue
            channel = self.bot.get_channel(row["channel_id"])
            if not isinstance(channel, TextChannel):
                to_delete.append(row["channel_id"])
                continue
            if not channel.last_message_id:
                continue
            age = (utcnow() - snowflake_time(channel.last_message_id)).total_seconds()
            if age >= timeout:
                with suppress(HTTPException):
                    await channel.delete(reason="Ticket inactive for too long")
                logger.info("Closed inactive ticket %s", channel.id)
                to_delete.append(row["channel_id"])

        if to_delete:
            await self.db.execute(
                "DELETE FROM tickets.open WHERE channel_id = ANY($1::BIGINT[])",
                to_delete,
            )

    # ── interaction listener (create ticket) ─────────────────

    @Cog.listener("on_interaction")
    async def on_ticket_interaction(self, interaction: Interaction) -> None:
        if not interaction.data or not interaction.guild:
            return
        if not isinstance(interaction.user, Member):
            return

        custom_id = interaction.data.get("custom_id") or ""
        if not custom_id.startswith("ticket.create"):
            return

        if not interaction.guild.me.guild_permissions.manage_channels:
            return await _ephemeral(
                interaction, "I need the **Manage Channels** permission to open tickets."
            )

        component_type = interaction.data.get("component_type", 0)
        identifier = custom_id.rsplit(":", 1)[-1]

        settings = await Settings.fetch(self.bot, interaction.guild)
        if settings.is_blacklisted(interaction.user):
            return await _ephemeral(interaction, "You are not allowed to open tickets here.")

        record: Optional[TicketButton | TicketDropdownOption] = None
        if component_type == 2:  # button
            record = await settings.fetch_button(identifier)
        elif component_type == 3:  # select
            values = interaction.data.get("values") or []
            if values:
                record = await settings.fetch_dropdown_option(identifier, values[0])

        if not record:
            return await _ephemeral(interaction, "This control is no longer valid.")

        # already has an open ticket?
        existing = await self.db.fetchrow(
            """
            SELECT channel_id FROM tickets.open
            WHERE id = $1 AND guild_id = $2 AND user_id = $3
            """,
            identifier,
            interaction.guild.id,
            interaction.user.id,
        )
        if existing:
            ch = interaction.guild.get_channel(existing["channel_id"])
            if ch:
                return await _ephemeral(
                    interaction, f"You already have an open ticket: {ch.mention}"
                )

        # max tickets check
        if settings.record.get("max_tickets"):
            count = await self.db.fetchval(
                "SELECT COUNT(*) FROM tickets.open WHERE guild_id = $1",
                interaction.guild.id,
            )
            if count >= settings.record["max_tickets"]:
                return await _ephemeral(
                    interaction,
                    f"The server has reached the maximum of **{settings.record['max_tickets']}** open tickets.",
                )

        await interaction.response.defer(ephemeral=True, thinking=True)

        category = None
        cat_id = record.get("category_id")
        if cat_id:
            cat = interaction.guild.get_channel(cat_id)
            if isinstance(cat, CategoryChannel):
                category = cat

        overwrites = {
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

        try:
            channel = await interaction.guild.create_text_channel(
                name=f"ticket-{interaction.user.name}"[:100],
                category=category,
                overwrites=overwrites,
                topic=(record.get("topic") or "")[:1024] or None,
                reason=f"Ticket opened by {interaction.user} ({interaction.user.id})",
            )
        except HTTPException as exc:
            return await _ephemeral(
                interaction,
                f"Could not create the channel: `{exc.text}`",
                followup=True,
            )

        await self.db.execute(
            """
            INSERT INTO tickets.open (id, guild_id, channel_id, user_id)
            VALUES ($1, $2, $3, $4)
            ON CONFLICT (id, guild_id, user_id)
            DO UPDATE SET channel_id = EXCLUDED.channel_id
            """,
            identifier,
            interaction.guild.id,
            channel.id,
            interaction.user.id,
        )

        # welcome message
        template = record.get("template")
        if template:
            content = (
                template.replace("{user}", interaction.user.mention)
                .replace("{user.mention}", interaction.user.mention)
                .replace("{user.name}", interaction.user.display_name)
            )
            with suppress(HTTPException):
                await channel.send(content)
        else:
            embed = Embed(
                title="Ticket Opened",
                description="A staff member will be with you shortly.\nUse the buttons below or wait for assistance.",
                color=0x5865F2,
            )
            with suppress(HTTPException):
                await channel.send(content=interaction.user.mention, embed=embed)

        await _ephemeral(
            interaction,
            f"Your ticket has been created: {channel.mention}",
            followup=True,
        )
        logger.info(
            "Ticket %s opened by %s in %s",
            channel.id,
            interaction.user.id,
            interaction.guild.id,
        )

    @Cog.listener("on_guild_channel_delete")
    async def on_ticket_channel_delete(self, channel: discord.abc.GuildChannel) -> None:
        if not isinstance(channel, TextChannel):
            return
        await self.db.execute(
            "DELETE FROM tickets.open WHERE channel_id = $1", channel.id
        )

    # ── command group ────────────────────────────────────────

    @group(
        name="ticket",
        aliases=["tickets", "tix"],
        description="Configure and manage the ticket system",
        invoke_without_command=True,
        example=",ticket",
    )
    @has_permissions(manage_channels=True)
    async def ticket(self, ctx) -> Message:
        return await ctx.send_help()

    # ── panel ────────────────────────────────────────────────

    @ticket.command(
        name="panel",
        description="Set an existing message as the ticket panel",
        example=",ticket panel 123456789012345678",
        usage="<message id | message link>",
    )
    @has_permissions(manage_channels=True)
    async def ticket_panel(self, ctx, message: Message):
        if message.author.id != self.bot.user.id:
            return await ctx.warn("The panel message must be sent by me so I can edit its components.")

        settings = await Settings.fetch(self.bot, ctx.guild)
        await settings.upsert(channel_id=message.channel.id, message_id=message.id)
        return await ctx.success(
            f"Panel set to [this message]({message.jump_url}).\n"
            f"Add controls with `{ctx.clean_prefix}ticket button` or `{ctx.clean_prefix}ticket dropdown`."
        )

    # ── inactivity ───────────────────────────────────────────

    @ticket.group(
        name="inactivity",
        aliases=["timeout", "idle"],
        description="Automatically close tickets after a period of silence",
        invoke_without_command=True,
        example=",ticket inactivity 2h",
    )
    @has_permissions(manage_channels=True)
    async def ticket_inactivity(self, ctx, *, duration: str = None):
        if duration is None:
            return await ctx.send_help()

        # simple parser: 30m, 2h, 1d
        duration = duration.lower().strip()
        seconds = 0
        try:
            if duration.endswith("m"):
                seconds = int(duration[:-1]) * 60
            elif duration.endswith("h"):
                seconds = int(duration[:-1]) * 3600
            elif duration.endswith("d"):
                seconds = int(duration[:-1]) * 86400
            else:
                seconds = int(duration)
        except ValueError:
            return await ctx.warn("Use a duration like `30m`, `2h` or `1d` (minimum 30 minutes).")

        if seconds < 1800:
            return await ctx.warn("Inactivity timeout must be at least **30 minutes**.")

        settings = await Settings.fetch(self.bot, ctx.guild)
        await settings.upsert(inactivity_timeout=seconds)
        human = f"{seconds // 3600}h {(seconds % 3600) // 60}m" if seconds >= 3600 else f"{seconds // 60}m"
        return await ctx.success(f"Tickets will auto-close after **{human}** of inactivity.")

    @ticket_inactivity.command(
        name="disable",
        aliases=["off", "remove"],
        description="Turn off automatic inactivity closing",
    )
    @has_permissions(manage_channels=True)
    async def ticket_inactivity_disable(self, ctx):
        settings = await Settings.fetch(self.bot, ctx.guild)
        await settings.upsert(inactivity_timeout=None)
        return await ctx.success("Inactivity auto-close has been disabled.")

    # ── limit ────────────────────────────────────────────────

    @ticket.command(
        name="limit",
        aliases=["max"],
        description="Set the maximum number of open tickets allowed at once",
        example=",ticket limit 25",
        usage="<0-200>",
    )
    @has_permissions(manage_channels=True)
    async def ticket_limit(self, ctx, amount: int):
        if amount < 0 or amount > 200:
            return await ctx.warn("Limit must be between **0** (unlimited) and **200**.")
        settings = await Settings.fetch(self.bot, ctx.guild)
        await settings.upsert(max_tickets=amount if amount > 0 else None)
        if amount == 0:
            return await ctx.success("Open-ticket limit removed.")
        return await ctx.success(f"Maximum open tickets set to **{amount}**.")

    # ── staff roles ──────────────────────────────────────────

    @ticket.group(
        name="staff",
        aliases=["support"],
        description="Manage roles that can view and control tickets",
        invoke_without_command=True,
        example=",ticket staff @Support",
    )
    @has_permissions(manage_channels=True)
    async def ticket_staff(self, ctx, role: Role = None):
        if role is None:
            return await ctx.send_help()

        settings = await Settings.fetch(self.bot, ctx.guild)
        ids = list(settings.record.get("staff_role_ids") or [])
        if role.id in ids:
            ids.remove(role.id)
            await settings.upsert(staff_role_ids=ids)
            return await ctx.success(f"{role.mention} can no longer manage tickets.")
        ids.append(role.id)
        await settings.upsert(staff_role_ids=ids)
        return await ctx.success(f"{role.mention} can now manage tickets.")

    @ticket_staff.command(
        name="list",
        description="Show all ticket staff roles",
    )
    @has_permissions(manage_channels=True)
    async def ticket_staff_list(self, ctx):
        settings = await Settings.fetch(self.bot, ctx.guild)
        roles = settings.staff_roles
        if not roles:
            return await ctx.warn("No staff roles configured.")
        embed = Embed(
            title="Ticket Staff Roles",
            description="\n".join(f"{r.mention} (`{r.id}`)" for r in roles),
            color=0x5865F2,
        )
        return await ctx.send(embed=embed)

    # ── blacklist ────────────────────────────────────────────

    @ticket.group(
        name="blacklist",
        aliases=["block"],
        description="Prevent members or roles from opening tickets",
        invoke_without_command=True,
        example=",ticket blacklist @user",
    )
    @has_permissions(manage_channels=True)
    async def ticket_blacklist(self, ctx, target: Union[Member, Role] = None):
        if target is None:
            return await ctx.send_help()

        settings = await Settings.fetch(self.bot, ctx.guild)
        ids = list(settings.record.get("blacklisted_ids") or [])
        if target.id in ids:
            ids.remove(target.id)
            await settings.upsert(blacklisted_ids=ids)
            return await ctx.success(f"{target.mention} can open tickets again.")
        ids.append(target.id)
        await settings.upsert(blacklisted_ids=ids)
        return await ctx.success(f"{target.mention} is now blocked from opening tickets.")

    @ticket_blacklist.command(
        name="list",
        description="Show everyone currently blacklisted",
    )
    @has_permissions(manage_channels=True)
    async def ticket_blacklist_list(self, ctx):
        settings = await Settings.fetch(self.bot, ctx.guild)
        items = settings.blacklisted
        if not items:
            return await ctx.warn("The blacklist is empty.")
        embed = Embed(
            title="Ticket Blacklist",
            description="\n".join(f"{t.mention} (`{t.id}`)" for t in items),
            color=0x5865F2,
        )
        return await ctx.send(embed=embed)

    # ── transcript destinations ──────────────────────────────

    @ticket.group(
        name="transcript",
        aliases=["logs"],
        description="Where closed-ticket transcripts are sent",
        invoke_without_command=True,
    )
    @has_permissions(manage_channels=True)
    async def ticket_transcript(self, ctx):
        return await ctx.send_help()

    @ticket_transcript.command(
        name="add",
        description="Add a channel (or DM) as a transcript destination",
        example=",ticket transcript add #ticket-logs",
        usage="<channel | dm>",
    )
    @has_permissions(manage_channels=True)
    async def ticket_transcript_add(self, ctx, target: Union[TextChannel, str]):
        settings = await Settings.fetch(self.bot, ctx.guild)
        dests = list(settings.record.get("transcript_destinations") or [])
        if isinstance(target, str) and target.lower() == "dm":
            value = "dm"
            label = "the ticket opener’s DMs"
        elif isinstance(target, TextChannel):
            value = str(target.id)
            label = target.mention
        else:
            return await ctx.warn("Provide a text channel or the word `dm`.")

        if value in dests:
            return await ctx.warn(f"{label} is already a transcript destination.")
        dests.append(value)
        await settings.upsert(transcript_destinations=dests)
        return await ctx.success(f"Transcripts will also be sent to {label}.")

    @ticket_transcript.command(
        name="remove",
        description="Remove a transcript destination",
        example=",ticket transcript remove #ticket-logs",
    )
    @has_permissions(manage_channels=True)
    async def ticket_transcript_remove(self, ctx, target: Union[TextChannel, str]):
        settings = await Settings.fetch(self.bot, ctx.guild)
        dests = list(settings.record.get("transcript_destinations") or [])
        if isinstance(target, str) and target.lower() == "dm":
            value = "dm"
            label = "DM"
        elif isinstance(target, TextChannel):
            value = str(target.id)
            label = target.mention
        else:
            return await ctx.warn("Provide a text channel or `dm`.")

        if value not in dests:
            return await ctx.warn(f"{label} is not a transcript destination.")
        dests.remove(value)
        await settings.upsert(transcript_destinations=dests)
        return await ctx.success(f"Removed {label} from transcript destinations.")

    @ticket_transcript.command(
        name="list",
        description="Show current transcript destinations",
    )
    @has_permissions(manage_channels=True)
    async def ticket_transcript_list(self, ctx):
        settings = await Settings.fetch(self.bot, ctx.guild)
        dests = settings.transcript_destinations
        if not dests:
            return await ctx.warn("No transcript destinations configured.")
        lines = []
        for d in dests:
            if d == "dm":
                lines.append("• Ticket opener’s DMs")
            else:
                lines.append(f"• {d.mention}")
        embed = Embed(title="Transcript Destinations", description="\n".join(lines), color=0x5865F2)
        return await ctx.send(embed=embed)

    # ── button management ────────────────────────────────────

    @ticket.group(
        name="button",
        aliases=["btn"],
        description="Add or remove buttons on the ticket panel",
        invoke_without_command=True,
    )
    @has_permissions(manage_channels=True)
    async def ticket_button(self, ctx):
        return await ctx.send_help()

    @ticket_button.command(
        name="add",
        description="Add a button that opens a ticket",
        example=",ticket button add support --style green --emoji 🎫",
        usage="<identifier> [label] [--style <color>] [--emoji <emoji>] [--category <category>] [--topic <text>]",
    )
    @has_permissions(manage_channels=True)
    async def ticket_button_add(
        self,
        ctx,
        identifier: str,
        label: str = "Open Ticket",
        *,
        style: str = "green",
        emoji: Optional[str] = None,
        category: Optional[CategoryChannel] = None,
        topic: Optional[str] = None,
    ):
        identifier = identifier.lower().replace(" ", "-")[:32]
        style = style.lower()
        if style not in STYLE_MAP:
            return await ctx.warn("Style must be one of: blurple, grey, green, red.")

        settings = await Settings.fetch(self.bot, ctx.guild)
        message = await settings.fetch_message()
        if not message:
            return await ctx.warn(
                f"Set a panel first with `{ctx.clean_prefix}ticket panel <message>`."
            )

        # persist
        await self.db.execute(
            """
            INSERT INTO tickets.button (id, guild_id, category_id, topic, style, emoji, label)
            VALUES ($1, $2, $3, $4, $5, $6, $7)
            ON CONFLICT (guild_id, id) DO UPDATE SET
                category_id = EXCLUDED.category_id,
                topic       = EXCLUDED.topic,
                style       = EXCLUDED.style,
                emoji       = EXCLUDED.emoji,
                label       = EXCLUDED.label
            """,
            identifier,
            ctx.guild.id,
            category.id if category else None,
            topic,
            style,
            emoji,
            label[:80],
        )

        # rebuild view from current components + new button
        view = View(timeout=None)
        # keep existing non-ticket buttons if any
        for row in message.components:
            for child in row.children:
                if getattr(child, "custom_id", None) and str(child.custom_id).startswith("ticket.create"):
                    continue  # will re-add from DB
                # we only manage our own buttons; skip others for safety
        # load all buttons for this guild
        buttons = await self.db.fetch(
            "SELECT * FROM tickets.button WHERE guild_id = $1", ctx.guild.id
        )
        for b in buttons:
            btn = Button(
                style=STYLE_MAP.get(b["style"], ButtonStyle.success),
                label=b["label"] or "Open Ticket",
                emoji=b["emoji"],
                custom_id=f"ticket.create:{b['id']}",
            )
            view.add_item(btn)

        # also keep any dropdowns
        dropdowns = await self.db.fetch(
            "SELECT * FROM tickets.dropdown WHERE guild_id = $1", ctx.guild.id
        )
        for d in dropdowns:
            opts = []
            for o in d["options"] or []:
                opts.append(
                    SelectOption(
                        label=o.get("label", "Option")[:100],
                        value=o.get("id", "opt"),
                        description=(o.get("description") or "")[:100] or None,
                        emoji=o.get("emoji"),
                    )
                )
            if opts:
                select = Select(
                    placeholder=d.get("placeholder") or "Choose a category…",
                    options=opts,
                    custom_id=f"ticket.create:{d['id']}",
                )
                view.add_item(select)

        try:
            await message.edit(view=view)
        except HTTPException as exc:
            return await ctx.warn(f"Could not update the panel: `{exc.text}`")

        return await ctx.success(
            f"Button **{label}** (`{identifier}`) added to the panel."
        )

    @ticket_button.command(
        name="remove",
        description="Remove a button from the panel",
        example=",ticket button remove support",
        usage="<identifier>",
    )
    @has_permissions(manage_channels=True)
    async def ticket_button_remove(self, ctx, identifier: str):
        identifier = identifier.lower().replace(" ", "-")
        deleted = await self.db.execute(
            "DELETE FROM tickets.button WHERE guild_id = $1 AND id = $2",
            ctx.guild.id,
            identifier,
        )
        if deleted == "DELETE 0":
            return await ctx.warn(f"No button with id `{identifier}` found.")

        # refresh panel
        settings = await Settings.fetch(self.bot, ctx.guild)
        message = await settings.fetch_message()
        if message:
            await self._refresh_panel(message, ctx.guild.id)

        return await ctx.success(f"Button `{identifier}` removed.")

    @ticket_button.command(
        name="list",
        description="List all buttons on the panel",
    )
    @has_permissions(manage_channels=True)
    async def ticket_button_list(self, ctx):
        rows = await self.db.fetch(
            "SELECT id, label, style, emoji FROM tickets.button WHERE guild_id = $1",
            ctx.guild.id,
        )
        if not rows:
            return await ctx.warn("No buttons configured.")
        lines = [
            f"**{r['label']}** (`{r['id']}`) — {r['style']}"
            + (f" {r['emoji']}" if r["emoji"] else "")
            for r in rows
        ]
        embed = Embed(title="Ticket Buttons", description="\n".join(lines), color=0x5865F2)
        return await ctx.send(embed=embed)

    # ── dropdown management (simplified but complete) ────────

    @ticket.group(
        name="dropdown",
        aliases=["select", "menu"],
        description="Manage dropdown menus on the ticket panel",
        invoke_without_command=True,
    )
    @has_permissions(manage_channels=True)
    async def ticket_dropdown(self, ctx):
        return await ctx.send_help()

    @ticket_dropdown.command(
        name="create",
        description="Create a new dropdown on the panel",
        example=",ticket dropdown create categories",
        usage="<identifier> [placeholder]",
    )
    @has_permissions(manage_channels=True)
    async def ticket_dropdown_create(
        self, ctx, identifier: str, *, placeholder: str = "Select a category…"
    ):
        identifier = identifier.lower().replace(" ", "-")[:32]
        settings = await Settings.fetch(self.bot, ctx.guild)
        message = await settings.fetch_message()
        if not message:
            return await ctx.warn("Set a panel first with `,ticket panel`.")

        await self.db.execute(
            """
            INSERT INTO tickets.dropdown (id, guild_id, placeholder, options)
            VALUES ($1, $2, $3, '[]'::jsonb)
            ON CONFLICT (guild_id, id) DO UPDATE SET placeholder = EXCLUDED.placeholder
            """,
            identifier,
            ctx.guild.id,
            placeholder[:100],
        )
        await self._refresh_panel(message, ctx.guild.id)
        return await ctx.success(
            f"Dropdown `{identifier}` created. Add options with "
            f"`{ctx.clean_prefix}ticket dropdown option {identifier} <opt-id> <label>`."
        )

    @ticket_dropdown.command(
        name="option",
        description="Add an option to a dropdown",
        example=",ticket dropdown option categories billing Billing Support",
        usage="<dropdown-id> <option-id> <label> [--emoji] [--category] [--topic]",
    )
    @has_permissions(manage_channels=True)
    async def ticket_dropdown_option(
        self,
        ctx,
        dropdown_id: str,
        option_id: str,
        *,
        label: str,
        emoji: Optional[str] = None,
        category: Optional[CategoryChannel] = None,
        topic: Optional[str] = None,
    ):
        dropdown_id = dropdown_id.lower().replace(" ", "-")
        option_id = option_id.lower().replace(" ", "-")[:32]

        row = await self.db.fetchrow(
            "SELECT options FROM tickets.dropdown WHERE guild_id = $1 AND id = $2",
            ctx.guild.id,
            dropdown_id,
        )
        if not row:
            return await ctx.warn(f"Dropdown `{dropdown_id}` does not exist.")

        options = list(row["options"] or [])
        # replace if exists
        options = [o for o in options if o.get("id") != option_id]
        options.append(
            {
                "id": option_id,
                "label": label[:100],
                "emoji": emoji,
                "description": None,
                "category_id": category.id if category else None,
                "template": None,
                "topic": topic,
            }
        )
        if len(options) > 25:
            return await ctx.warn("A dropdown can have at most 25 options.")

        await self.db.execute(
            "UPDATE tickets.dropdown SET options = $1::jsonb WHERE guild_id = $2 AND id = $3",
            json.dumps(options),
            ctx.guild.id,
            dropdown_id,
        )

        settings = await Settings.fetch(self.bot, ctx.guild)
        message = await settings.fetch_message()
        if message:
            await self._refresh_panel(message, ctx.guild.id)

        return await ctx.success(f"Option **{label}** added to `{dropdown_id}`.")

    @ticket_dropdown.command(
        name="remove",
        description="Remove a dropdown entirely",
        example=",ticket dropdown remove categories",
    )
    @has_permissions(manage_channels=True)
    async def ticket_dropdown_remove(self, ctx, identifier: str):
        identifier = identifier.lower().replace(" ", "-")
        deleted = await self.db.execute(
            "DELETE FROM tickets.dropdown WHERE guild_id = $1 AND id = $2",
            ctx.guild.id,
            identifier,
        )
        if deleted == "DELETE 0":
            return await ctx.warn(f"No dropdown `{identifier}` found.")

        settings = await Settings.fetch(self.bot, ctx.guild)
        message = await settings.fetch_message()
        if message:
            await self._refresh_panel(message, ctx.guild.id)
        return await ctx.success(f"Dropdown `{identifier}` removed.")

    # ── in-ticket staff commands ─────────────────────────────

    @ticket.command(
        name="add",
        aliases=["permit", "allow"],
        description="Add a member or role to the current ticket",
        example=",ticket add @user",
    )
    @in_ticket()
    @staff()
    async def ticket_add(self, ctx, target: Union[Member, Role]):
        await ctx.channel.set_permissions(
            target,
            view_channel=True,
            send_messages=True,
            attach_files=True,
            reason=f"Added by {ctx.author} ({ctx.author.id})",
        )
        return await ctx.success(f"Added {target.mention} to the ticket.")

    @ticket.command(
        name="remove",
        aliases=["deny", "hide"],
        description="Remove a member or role from the current ticket",
        example=",ticket remove @user",
    )
    @in_ticket()
    @staff()
    async def ticket_remove(self, ctx, target: Union[Member, Role]):
        await ctx.channel.set_permissions(
            target,
            overwrite=None,
            reason=f"Removed by {ctx.author} ({ctx.author.id})",
        )
        return await ctx.success(f"Removed {target.mention} from the ticket.")

    @ticket.command(
        name="close",
        aliases=["end", "delete", "resolve"],
        description="Close the current ticket and send a transcript",
        example=",ticket close",
    )
    @in_ticket()
    @staff()
    async def ticket_close(self, ctx):
        settings = await Settings.fetch(self.bot, ctx.guild)
        if settings.transcript_destinations:
            async with ctx.typing():
                await Transcript.create(
                    self.bot,
                    ctx.guild,
                    ctx.channel,
                    ctx.ticket,
                    settings.transcript_destinations,
                )

        await self.db.execute(
            "DELETE FROM tickets.open WHERE channel_id = $1", ctx.channel.id
        )
        with suppress(HTTPException):
            await ctx.channel.delete(
                reason=f"Closed by {ctx.author} ({ctx.author.id})"
            )

    # ── utility ──────────────────────────────────────────────

    async def _refresh_panel(self, message: Message, guild_id: int) -> None:
        """Rebuild the panel view from the database and edit the message."""
        view = View(timeout=None)

        buttons = await self.db.fetch(
            "SELECT * FROM tickets.button WHERE guild_id = $1 ORDER BY id", guild_id
        )
        for b in buttons:
            view.add_item(
                Button(
                    style=STYLE_MAP.get(b["style"], ButtonStyle.success),
                    label=b["label"] or "Open Ticket",
                    emoji=b["emoji"],
                    custom_id=f"ticket.create:{b['id']}",
                )
            )

        dropdowns = await self.db.fetch(
            "SELECT * FROM tickets.dropdown WHERE guild_id = $1", guild_id
        )
        for d in dropdowns:
            opts = []
            for o in d["options"] or []:
                opts.append(
                    SelectOption(
                        label=o.get("label", "Option")[:100],
                        value=o.get("id", "opt"),
                        description=(o.get("description") or "")[:100] or None,
                        emoji=o.get("emoji"),
                    )
                )
            if opts:
                view.add_item(
                    Select(
                        placeholder=(d.get("placeholder") or "Choose…")[:100],
                        options=opts,
                        custom_id=f"ticket.create:{d['id']}",
                    )
                )

        with suppress(HTTPException):
            await message.edit(view=view)


async def setup(bot) -> None:
    await bot.add_cog(Tickets(bot))
