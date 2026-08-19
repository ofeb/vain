from __future__ import annotations

import json
import re
from contextlib import suppress
from logging import getLogger
from secrets import token_hex
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
from discord.ext.commands import Cog, group
from discord.ext.tasks import loop
from discord.ui import Button, Select, View
from discord.utils import snowflake_time, utcnow

from config import color, emojis
from core.discord.package import Package
from core.managers.permissions import has_permissions

from .improper.checks import in_ticket, staff
from .improper.interface import Interface
from .settings import Settings, TicketButton, TicketDropdownOption
from .improper.transcript import Transcript
from .improper.views import (
    OpeningButtonAddModal,
    OpeningButtonEmojiView,
    TicketControlView,
    _parse_emoji,
)
from .events import TicketEvents

logger = getLogger("tickets")

STYLE_MAP = {
    "blurple": ButtonStyle.primary,
    "grey": ButtonStyle.secondary,
    "gray": ButtonStyle.secondary,
    "green": ButtonStyle.success,
    "red": ButtonStyle.danger,
}


DEFAULT_OPEN_TITLE = "Ticket Created"
DEFAULT_OPEN_DESCRIPTION = "Staff will be with you shortly"


def _ephemeral(interaction: Interaction, content: str, *, followup: bool = False):
    embed = Embed(color=color.neutral, description=content)
    if followup:
        return interaction.followup.send(embed=embed, ephemeral=True)
    return interaction.response.send_message(embed=embed, ephemeral=True)


def _button_identifier(custom_id: str | None) -> str:
    if not custom_id:
        return ""
    return custom_id.rsplit(":", 1)[-1]


def _make_identifier(label: str | None = None) -> str:
    base = re.sub(r"[^a-z0-9]+", "-", (label or "").lower()).strip("-")[:24]
    suffix = token_hex(3)
    if base:
        return f"{base}-{suffix}"
    return suffix


class Tickets(TicketEvents, Package):
    """Ticket system – panels, opening buttons, staff controls & transcripts."""

    def __init__(self, bot):
        super().__init__(bot)
        self.description = (
            "Full ticket system with panels, staff controls and transcripts"
        )

    async def cog_load(self) -> None:
        await self._ensure_schema()
        self.bot.add_view(TicketControlView(self))
        self._inactivity_loop.start()
        await super().cog_load()

    async def cog_unload(self) -> None:
        self._inactivity_loop.cancel()
        await super().cog_unload()

    async def _ensure_schema(self) -> None:
        schema_path = __file__.replace("__init__.py", "schema.sql")
        try:
            with open(schema_path, "r", encoding="utf-8") as f:
                sql = f.read()
            for stmt in sql.split(";"):
                stmt = stmt.strip()
                if stmt:
                    await self.db.execute(stmt)
            logger.info("Ticket schema synchronized")
        except Exception as exc:
            logger.warning("Could not fully sync ticket schema: %s", exc)

    

    @loop(minutes=5)
    async def _inactivity_loop(self) -> None:
        settings = await Settings.fetch(self.bot, self.bot.guilds[0]) if self.bot.guilds else None
        if not settings:
            return
        rows = await settings.fetch_tickets_with_inactivity_timeout()
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
            await settings.delete_open_tickets(to_delete)

    



    

    @group(
        name="ticket",
        aliases=["tickets", "tix", "tc"],
        description="configure and manage the ticket system",
        invoke_without_command=True,
        example=",ticket",
    )
    @has_permissions(manage_channels=True)
    async def ticket(self, ctx) -> Message:
        return await ctx.send_help()

    

    @ticket.command(
        name="panel",
        description="set an existing message as the ticket panel",
        example=",tc panel 123456789012345678",
        usage="<message id or message link>",
    )
    @has_permissions(manage_channels=True)
    async def ticket_panel(self, ctx, message: Message):
        if self.bot.user is None or message.author.id != self.bot.user.id:
            return await ctx.warn(
                "The panel message must be sent by me so I can edit its components."
            )

        settings = await Settings.fetch(self.bot, ctx.guild)
        await settings.upsert(channel_id=message.channel.id, message_id=message.id)
        return await ctx.success(
            f"Panel set to [this message]({message.jump_url}).\n"
            f"Add controls with `{ctx.clean_prefix}tc opening button` or "
            f"`{ctx.clean_prefix}tc button` / `{ctx.clean_prefix}tc dropdown`."
        )

    

    @ticket.group(
        name="inactivity",
        aliases=["timeout", "idle"],
        description="automatically close tickets after a period of silence",
        invoke_without_command=True,
        example=",tc inactivity 2h",
    )
    @has_permissions(manage_channels=True)
    async def ticket_inactivity(self, ctx, *, duration: Optional[str] = None):
        if duration is None:
            return await ctx.send_help()

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
            return await ctx.warn(
                "Use a duration like `30m`, `2h` or `1d` (minimum 30 minutes)."
            )

        if seconds < 1800:
            return await ctx.warn(
                "Inactivity timeout must be at least **30 minutes**."
            )

        settings = await Settings.fetch(self.bot, ctx.guild)
        await settings.upsert(inactivity_timeout=seconds)
        human = (
            f"{seconds // 3600}h {(seconds % 3600) // 60}m"
            if seconds >= 3600
            else f"{seconds // 60}m"
        )
        return await ctx.success(
            f"Tickets will auto-close after **{human}** of inactivity."
        )

    @ticket_inactivity.command(
        name="disable",
        aliases=["off", "remove"],
        description="turn off automatic inactivity closing",
    )
    @has_permissions(manage_channels=True)
    async def ticket_inactivity_disable(self, ctx):
        settings = await Settings.fetch(self.bot, ctx.guild)
        await settings.upsert(inactivity_timeout=None)
        return await ctx.success("Inactivity auto-close has been disabled.")

    

    @ticket.command(
        name="limit",
        aliases=["max"],
        description="set the maximum number of open tickets allowed at once",
        example=",tc limit 25",
        usage="<0-200>",
    )
    @has_permissions(manage_channels=True)
    async def ticket_limit(self, ctx, amount: int):
        if amount < 0 or amount > 200:
            return await ctx.warn(
                "Limit must be between **0** (unlimited) and **200**."
            )
        settings = await Settings.fetch(self.bot, ctx.guild)
        await settings.upsert(max_tickets=amount if amount > 0 else None)
        if amount == 0:
            return await ctx.success("Open-ticket limit removed.")
        return await ctx.success(f"Maximum open tickets set to **{amount}**.")

    

    @ticket.group(
        name="staff",
        aliases=["support"],
        description="manage roles that can view and control tickets",
        invoke_without_command=True,
        example=",tc staff @Support",
    )
    @has_permissions(manage_channels=True)
    async def ticket_staff(self, ctx, role: Optional[Role] = None):
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

    @ticket_staff.command(name="list", description="show all ticket staff roles")
    @has_permissions(manage_channels=True)
    async def ticket_staff_list(self, ctx):
        settings = await Settings.fetch(self.bot, ctx.guild)
        roles = settings.staff_roles
        if not roles:
            return await ctx.warn("No staff roles configured.")
        embed = Embed(
            title="Ticket Staff Roles",
            description="\n".join(f"{r.mention} (`{r.id}`)" for r in roles),
            color=color.base,
        )
        return await ctx.send(embed=embed)

    

    @ticket.group(
        name="blacklist",
        aliases=["block"],
        description="prevent members or roles from opening tickets",
        invoke_without_command=True,
        example=",tc blacklist @user",
    )
    @has_permissions(manage_channels=True)
    async def ticket_blacklist(
        self, ctx, target: Optional[Union[Member, Role]] = None
    ):
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
        return await ctx.success(
            f"{target.mention} is now blocked from opening tickets."
        )

    @ticket_blacklist.command(
        name="list", description="show everyone currently blacklisted"
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
            color=color.base,
        )
        return await ctx.send(embed=embed)

    

    @ticket.group(
        name="transcript",
        aliases=["logs", "transcripts"],
        description="where closed-ticket transcripts are sent",
        invoke_without_command=True,
    )
    @has_permissions(manage_channels=True)
    async def ticket_transcript(self, ctx):
        return await ctx.send_help()

    @ticket_transcript.command(
        name="add",
        description="add a channel (or dm) as a transcript destination",
        example=",tc transcript add #ticket-logs",
        usage="<channel or dm>",
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
        description="remove a transcript destination",
        example=",tc transcript remove #ticket-logs",
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
        name="list", description="show current transcript destinations"
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
        embed = Embed(
            title="Transcript Destinations",
            description="\n".join(lines),
            color=color.base,
        )
        return await ctx.send(embed=embed)

    

    @ticket.group(
        name="opening",
        aliases=["open", "welcome"],
        description="customize the ticket open message and opening buttons",
        invoke_without_command=True,
        example=",tc opening",
    )
    @has_permissions(manage_channels=True)
    async def ticket_opening(self, ctx):
        return await ctx.send_help()

    @ticket_opening.group(
        name="embed",
        aliases=["message", "msg"],
        description="customize the default ticket open embed/message",
        invoke_without_command=True,
        example=",tc opening embed {embed}{title: Ticket Created}{description: Staff will be with you shortly}",
    )
    @has_permissions(manage_channels=True)
    async def ticket_opening_embed(self, ctx, *, script: Optional[str] = None):
        if script is None:
            settings = await Settings.fetch(self.bot, ctx.guild)
            current = settings.open_embed
            if not current:
                return await ctx.success(
                    "Using the **default** open message "
                    f"(`{DEFAULT_OPEN_TITLE}` / `{DEFAULT_OPEN_DESCRIPTION}`).\n"
                    f"Set a custom one with `{ctx.clean_prefix}tc opening embed <script>`."
                )
            return await ctx.success(
                f"Current open embed script:\n```\n{current[:1800]}\n```\n"
                f"Reset with `{ctx.clean_prefix}tc opening embed reset`."
            )

        settings = await Settings.fetch(self.bot, ctx.guild)
        await settings.upsert(open_embed=script)
        return await ctx.success(
            "Ticket open message updated. New tickets will use this script "
            "(unless a button has its own template)."
        )

    @ticket_opening_embed.command(
        name="reset",
        aliases=["default", "clear", "remove"],
        description="reset the open message to the vain default",
    )
    @has_permissions(manage_channels=True)
    async def ticket_opening_embed_reset(self, ctx):
        settings = await Settings.fetch(self.bot, ctx.guild)
        await settings.upsert(open_embed=None)
        return await ctx.success(
            f"Open message reset to default: **{DEFAULT_OPEN_TITLE}** - "
            f"{DEFAULT_OPEN_DESCRIPTION}."
        )

    @ticket_opening_embed.command(
        name="test",
        aliases=["preview"],
        description="preview the current open message in this channel",
    )
    @has_permissions(manage_channels=True)
    async def ticket_opening_embed_test(self, ctx):
        settings = await Settings.fetch(self.bot, ctx.guild)
        fake_record: dict = {"template": settings.open_embed}
        
        control = TicketControlView(self)

        class _I:
            user = ctx.author
            guild = ctx.guild

        await self._send_open_message(
            ctx.channel,
            interaction=_I(),  # type: ignore[arg-type]
            settings=settings,
            record=fake_record,
            view=control,
        )
        return await ctx.success("Preview sent above.")

    @ticket_opening.group(
        name="button",
        aliases=["btn", "buttons"],
        description="add or edit ticket opening buttons on the panel",
        invoke_without_command=True,
        example=",tc opening button",
    )
    @has_permissions(manage_channels=True)
    async def ticket_opening_button(self, ctx):
        return await ctx.send_help()

    @ticket_opening_button.command(
        name="add",
        aliases=["create", "new"],
        description="add a ticket opening button (modal or quick flags)",
        example=",tc opening button add support --style green --emoji 🎫",
        usage="[identifier] [label] [--style <color>] [--emoji <emoji>] [--category <category>]",
    )
    @has_permissions(manage_channels=True)
    async def ticket_opening_button_add(
        self,
        ctx,
        identifier: Optional[str] = None,
        label: Optional[str] = None,
        *,
        style: str = "green",
        emoji: Optional[str] = None,
        category: Optional[CategoryChannel] = None,
        topic: Optional[str] = None,
    ):
        
        if identifier is None and label is None:
            return await ctx.send(
                embed=Embed(
                    description=(
                        f"{emojis.approve} {ctx.author.mention}: "
                        "Use the modal to add an opening button, or run:\n"
                        f"`{ctx.clean_prefix}tc opening button add <id> <label> "
                        "--emoji 🎫 --style green`"
                    ),
                    color=color.approve,
                ),
                view=_OpeningAddTrigger(self),
            )

        
        if label is None:
            label = identifier
            identifier = None

        return await self._add_opening_button(
            ctx,
            identifier=identifier,
            label=label or "Open Ticket",
            style=style,
            emoji=emoji,
            category=category,
            topic=topic,
        )

    @ticket_opening_button.command(
        name="emoji",
        aliases=["emote", "icon"],
        description="change an opening button emoji via a select menu of all buttons",
        example=",tc opening button emoji",
    )
    @has_permissions(manage_channels=True)
    async def ticket_opening_button_emoji(self, ctx):
        settings = await Settings.fetch(self.bot, ctx.guild)
        buttons = await settings.fetch_buttons()
        if not buttons:
            return await ctx.warn(
                f"No opening buttons yet. Add one with `{ctx.clean_prefix}tc opening button add`."
            )
        rows = [dict(b) for b in buttons]
        view = OpeningButtonEmojiView(self, rows)
        embed = Embed(
            title="Edit opening button emoji",
            description="Select a button below, then enter the new emoji in the modal.",
            color=color.base,
        )
        for b in rows[:15]:
            e = b.get("emoji") or "-"
            embed.add_field(
                name=str(b.get("label") or b["id"])[:256],
                value=f"id: `{b['id']}` · emoji: {e}",
                inline=False,
            )
        return await ctx.send(embed=embed, view=view)

    @ticket_opening_button.command(
        name="list", description="list all ticket opening buttons"
    )
    @has_permissions(manage_channels=True)
    async def ticket_opening_button_list(self, ctx):
        return await self.ticket_button_list.callback(self, ctx)

    @ticket_opening_button.command(
        name="remove",
        aliases=["delete", "rm"],
        description="remove an opening button",
        example=",tc opening button remove support",
        usage="<identifier>",
    )
    @has_permissions(manage_channels=True)
    async def ticket_opening_button_remove(self, ctx, identifier: str):
        return await self.ticket_button_remove.callback(self, ctx, identifier)

    

    @ticket.group(
        name="button",
        aliases=["btn"],
        description="add or remove buttons on the ticket panel",
        invoke_without_command=True,
    )
    @has_permissions(manage_channels=True)
    async def ticket_button(self, ctx):
        return await ctx.send_help()

    @ticket_button.command(
        name="add",
        description="add a button that opens a ticket",
        example=",tc button add support --style green --emoji 🎫",
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
        return await self._add_opening_button(
            ctx,
            identifier=identifier,
            label=label,
            style=style,
            emoji=emoji,
            category=category,
            topic=topic,
        )

    @ticket_button.command(
        name="remove",
        description="remove a button from the panel",
        example=",tc button remove support",
        usage="<identifier>",
    )
    @has_permissions(manage_channels=True)
    async def ticket_button_remove(self, ctx, identifier: str):
        identifier = identifier.lower().replace(" ", "-")
        settings = await Settings.fetch(self.bot, ctx.guild)
        deleted = await settings.delete_button(identifier)
        if deleted == "DELETE 0":
            return await ctx.warn(f"No button with id `{identifier}` found.")

        message = await settings.fetch_message()
        if message:
            await self._refresh_panel(message, ctx.guild.id)

        return await ctx.success(f"Button `{identifier}` removed.")

    @ticket_button.command(name="list", description="list all buttons on the panel")
    @has_permissions(manage_channels=True)
    async def ticket_button_list(self, ctx):
        settings = await Settings.fetch(self.bot, ctx.guild)
        rows = await settings.fetch_button_list()
        if not rows:
            return await ctx.warn("No buttons configured.")
        lines = [
            f"**{r['label']}** (`{r['id']}`) - {r['style']}"
            + (f" {r['emoji']}" if r["emoji"] else "")
            for r in rows
        ]
        embed = Embed(
            title="Ticket Buttons", description="\n".join(lines), color=color.base
        )
        return await ctx.send(embed=embed)

    @ticket_button.command(
        name="emoji",
        aliases=["emote"],
        description="edit opening button emojis via select menu",
    )
    @has_permissions(manage_channels=True)
    async def ticket_button_emoji(self, ctx):
        return await self.ticket_opening_button_emoji.callback(self, ctx)

    

    @ticket.group(
        name="dropdown",
        aliases=["select", "menu"],
        description="manage dropdown menus on the ticket panel",
        invoke_without_command=True,
    )
    @has_permissions(manage_channels=True)
    async def ticket_dropdown(self, ctx):
        return await ctx.send_help()

    @ticket_dropdown.command(
        name="create",
        description="create a new dropdown on the panel",
        example=",tc dropdown create categories",
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
            return await ctx.warn(
                f"Set a panel first with `{ctx.clean_prefix}tc panel`."
            )

        await settings.upsert_dropdown(identifier, placeholder[:100])
        await self._refresh_panel(message, ctx.guild.id)
        return await ctx.success(
            f"Dropdown `{identifier}` created. Add options with "
            f"`{ctx.clean_prefix}tc dropdown option {identifier} <opt-id> <label>`."
        )

    @ticket_dropdown.command(
        name="option",
        description="add an option to a dropdown",
        example=",tc dropdown option categories billing Billing Support",
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

        settings = await Settings.fetch(self.bot, ctx.guild)
        options = await settings.fetch_dropdown_options(dropdown_id)
        if options is None:
            return await ctx.warn(f"Dropdown `{dropdown_id}` does not exist.")

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

        await settings.update_dropdown_options(dropdown_id, json.dumps(options))

        message = await settings.fetch_message()
        if message:
            await self._refresh_panel(message, ctx.guild.id)

        return await ctx.success(f"Option **{label}** added to `{dropdown_id}`.")

    @ticket_dropdown.command(
        name="remove",
        description="remove a dropdown entirely",
        example=",tc dropdown remove categories",
    )
    @has_permissions(manage_channels=True)
    async def ticket_dropdown_remove(self, ctx, identifier: str):
        identifier = identifier.lower().replace(" ", "-")
        settings = await Settings.fetch(self.bot, ctx.guild)
        deleted = await settings.delete_dropdown(identifier)
        if deleted == "DELETE 0":
            return await ctx.warn(f"No dropdown `{identifier}` found.")

        message = await settings.fetch_message()
        if message:
            await self._refresh_panel(message, ctx.guild.id)
        return await ctx.success(f"Dropdown `{identifier}` removed.")

    

    @ticket.command(
        name="add",
        aliases=["permit", "allow"],
        description="add a member or role to the current ticket",
        example=",tc add @user",
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
        description="remove a member or role from the current ticket",
        example=",tc remove @user",
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
        name="claim",
        aliases=["take"],
        description="claim the current ticket",
        example=",tc claim",
    )
    @in_ticket()
    @staff()
    async def ticket_claim(self, ctx):
        ticket = ctx.ticket
        claimed_by = ticket.get("claimed_by")
        if claimed_by and int(claimed_by) == ctx.author.id:
            return await ctx.warn("You already claimed this ticket.")
        if claimed_by and int(claimed_by) != ctx.author.id:
            claimer = ctx.guild.get_member(int(claimed_by))
            who = claimer.mention if claimer else f"<@{claimed_by}>"
            return await ctx.warn(f"This ticket is already claimed by {who}.")

        settings = await Settings.fetch(self.bot, ctx.guild)
        await settings.claim_ticket(ctx.author.id, ctx.channel.id)
        new_name = f"claimed-{ctx.author.name}"[:100]
        with suppress(HTTPException):
            await ctx.channel.edit(
                name=new_name,
                topic=(
                    f"Claimed by {ctx.author} ({ctx.author.id}) | "
                    + (ctx.channel.topic or "")
                )[:1024],
                reason=f"Claimed by {ctx.author} ({ctx.author.id})",
            )
        return await ctx.success(f"{ctx.author.mention} claimed this ticket.")

    @ticket.command(
        name="close",
        aliases=["end", "delete", "resolve"],
        description="close the current ticket and send a transcript",
        example=",tc close",
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

        await settings.delete_open_ticket(ctx.channel.id)
        with suppress(HTTPException):
            await ctx.channel.delete(
                reason=f"Closed by {ctx.author} ({ctx.author.id})"
            )

    

    async def _fetch_open_ticket(self, channel_id: int) -> Optional[dict]:
        return await Settings.fetch_open_ticket_by_channel(self.bot, channel_id)

    async def claim_ticket(self, interaction: Interaction) -> None:
        if not interaction.guild or not isinstance(interaction.user, Member):
            await _ephemeral(interaction, "This can only be used in a server.")
            return
        if not isinstance(interaction.channel, TextChannel):
            await _ephemeral(
                interaction, "This can only be used inside a ticket channel."
            )
            return

        ticket = await self._fetch_open_ticket(interaction.channel.id)
        if not ticket:
            await _ephemeral(interaction, "This channel is not an open ticket.")
            return

        claimed_by = ticket.get("claimed_by")
        if claimed_by and int(claimed_by) == interaction.user.id:
            await _ephemeral(interaction, "You already claimed this ticket.")
            return
        if claimed_by and int(claimed_by) != interaction.user.id:
            claimer = interaction.guild.get_member(int(claimed_by))
            who = claimer.mention if claimer else f"<@{claimed_by}>"
            await _ephemeral(
                interaction, f"This ticket is already claimed by {who}."
            )
            return

        await interaction.response.defer(ephemeral=True)
        settings = await Settings.fetch(self.bot, interaction.guild)
        await settings.claim_ticket(interaction.user.id, interaction.channel.id)

        new_name = f"claimed-{interaction.user.name}"[:100]
        topic_prefix = f"Claimed by {interaction.user} ({interaction.user.id})"
        old_topic = interaction.channel.topic or ""
        with suppress(HTTPException):
            await interaction.channel.edit(
                name=new_name,
                topic=f"{topic_prefix} | {old_topic}"[:1024],
                reason=f"Claimed by {interaction.user} ({interaction.user.id})",
            )

        notice = Embed(
            description=f"{emojis.ticket.claim} {interaction.user.mention} claimed this ticket.",
            color=color.base,
        )
        with suppress(HTTPException):
            await interaction.channel.send(embed=notice)

        await _ephemeral(
            interaction,
            f"You claimed {interaction.channel.mention}.",
            followup=True,
        )

    async def close_ticket(self, interaction: Interaction) -> None:
        if not interaction.guild or not isinstance(interaction.user, Member):
            await _ephemeral(interaction, "This can only be used in a server.")
            return
        if not isinstance(interaction.channel, TextChannel):
            await _ephemeral(
                interaction, "This can only be used inside a ticket channel."
            )
            return

        ticket = await self._fetch_open_ticket(interaction.channel.id)
        if not ticket:
            await _ephemeral(interaction, "This channel is not an open ticket.")
            return

        await interaction.response.defer(ephemeral=True)
        settings = await Settings.fetch(self.bot, interaction.guild)

        if settings.transcript_destinations:
            await Transcript.create(
                self.bot,
                interaction.guild,
                interaction.channel,
                ticket,
                settings.transcript_destinations,
            )

        channel = interaction.channel
        await settings.delete_open_ticket(channel.id)
        with suppress(HTTPException):
            await channel.send(
                embed=Embed(
                    description=(
                        f"{emojis.ticket.close} Ticket closed by "
                        f"{interaction.user.mention}. Deleting…"
                    ),
                    color=color.deny,
                )
            )
        with suppress(HTTPException):
            await channel.delete(
                reason=f"Closed by {interaction.user} ({interaction.user.id})"
            )

        with suppress(HTTPException):
            await _ephemeral(interaction, "Ticket closed.", followup=True)

    async def transcript_ticket(self, interaction: Interaction) -> None:
        if not interaction.guild or not isinstance(interaction.user, Member):
            await _ephemeral(interaction, "This can only be used in a server.")
            return
        if not isinstance(interaction.channel, TextChannel):
            await _ephemeral(
                interaction, "This can only be used inside a ticket channel."
            )
            return

        ticket = await self._fetch_open_ticket(interaction.channel.id)
        if not ticket:
            await _ephemeral(interaction, "This channel is not an open ticket.")
            return

        await interaction.response.defer(ephemeral=True)
        settings = await Settings.fetch(self.bot, interaction.guild)
        destinations = list(settings.transcript_destinations)

        transcript = await Transcript.build(
            self.bot,
            interaction.guild,
            interaction.channel,
            ticket,
            persist=True,
        )
        embed = Embed(
            title=f"Transcript - {interaction.channel.name}",
            description="Manual export (ticket still open).",
            color=color.base,
        )
        embed.set_footer(text=f"ID: {transcript.id}")

        await interaction.followup.send(
            embed=embed,
            file=transcript.as_file(interaction.channel.name),
            ephemeral=True,
        )

        if destinations:
            await Transcript.deliver(
                interaction.guild,
                ticket,
                transcript,
                destinations,
                channel_name=interaction.channel.name,
                description="manual transcript export (ticket still open)",
            )

    

    async def _add_opening_button(
        self,
        ctx,
        *,
        identifier: Optional[str],
        label: str,
        style: str = "green",
        emoji: Optional[str] = None,
        category: Optional[CategoryChannel] = None,
        topic: Optional[str] = None,
    ):
        style = (style or "green").lower()
        if style not in STYLE_MAP:
            return await ctx.warn("Style must be one of: blurple, grey, green, red.")

        settings = await Settings.fetch(self.bot, ctx.guild)
        message = await settings.fetch_message()
        if not message:
            return await ctx.warn(
                f"Set a panel first with `{ctx.clean_prefix}tc panel <message>`."
            )

        if not identifier:
            identifier = _make_identifier(label)
        else:
            identifier = identifier.lower().replace(" ", "-")[:32]

        
        if not emoji:
            emoji = getattr(emojis.ticket, "open", None) or None

        await settings.upsert_button(
            identifier,
            category_id=category.id if category else None,
            topic=topic,
            style=style,
            emoji=emoji,
            label=label[:80],
            update_all=True,
        )

        await self._refresh_panel(message, ctx.guild.id)
        shown = f"{emoji} " if emoji else ""
        return await ctx.success(
            f"Opening button **{shown}{label}** (`{identifier}`) added to the panel."
        )

    async def add_opening_button_from_modal(
        self,
        interaction: Interaction,
        *,
        label: str,
        emoji: Optional[str],
        style: str,
        identifier: Optional[str],
    ) -> None:
        if not interaction.guild or not isinstance(interaction.user, Member):
            await _ephemeral(interaction, "This can only be used in a server.")
            return

        style = (style or "green").lower()
        if style not in STYLE_MAP:
            await _ephemeral(
                interaction, "Style must be one of: blurple, grey, green, red."
            )
            return

        settings = await Settings.fetch(self.bot, interaction.guild)
        message = await settings.fetch_message()
        if not message:
            await _ephemeral(
                interaction,
                f"Set a panel first with {ctx.cmd('tc panel <message>')}.",
            )
            return

        if not identifier:
            identifier = _make_identifier(label)
        else:
            identifier = identifier.lower().replace(" ", "-")[:32]

        if not emoji:
            emoji = getattr(emojis.ticket, "open", None) or None

        await settings.upsert_button(
            identifier,
            style=style,
            emoji=emoji,
            label=label[:80],
            update_all=False,
        )
        await self._refresh_panel(message, interaction.guild.id)
        shown = f"{emoji} " if emoji else ""
        await _ephemeral(
            interaction,
            f"Opening button **{shown}{label}** (`{identifier}`) added.",
        )

    async def set_opening_button_emoji(
        self,
        interaction: Interaction,
        button_id: str,
        emoji: Optional[str],
    ) -> None:
        if not interaction.guild:
            await _ephemeral(interaction, "This can only be used in a server.")
            return

        settings = await Settings.fetch(self.bot, interaction.guild)
        result = await settings.update_button_emoji(button_id, emoji)
        if result == "UPDATE 0":
            await _ephemeral(interaction, f"No button `{button_id}` found.")
            return

        message = await settings.fetch_message()
        if message:
            await self._refresh_panel(message, interaction.guild.id)

        shown = emoji or "*(cleared)*"
        await _ephemeral(
            interaction,
            f"Updated emoji for `{button_id}` → {shown}",
        )

    async def _refresh_panel(self, message: Message, guild_id: int) -> None:
        """Rebuild the panel view from the database and edit the message."""
        
        try:
            interface = Interface.from_message(message)
            
            for child in list(interface.children):
                cid = getattr(child, "custom_id", None) or ""
                if str(cid).startswith("ticket.create"):
                    interface.remove_item(child)
            view: View = interface
        except Exception:
            view = View(timeout=None)

        settings = await Settings.fetch(self.bot, self.bot.get_guild(guild_id))
        if not settings:
            return
        buttons = await settings.fetch_buttons()
        for b in buttons:
            emoji = _parse_emoji(b.get("emoji"))
            view.add_item(
                Button(
                    style=STYLE_MAP.get(b["style"], ButtonStyle.success),
                    label=b["label"] or "Open Ticket",
                    emoji=emoji,
                    custom_id=f"ticket.create:{b['id']}",
                )
            )

        dropdowns = await settings.fetch_all_dropdowns()
        for d in dropdowns:
            opts = []
            for o in d["options"] or []:
                opts.append(
                    SelectOption(
                        label=o.get("label", "Option")[:100],
                        value=o.get("id", "opt"),
                        description=(o.get("description") or "")[:100] or None,
                        emoji=_parse_emoji(o.get("emoji")),
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


class _OpeningAddTrigger(View):
    """Tiny view that opens the add-button modal."""

    def __init__(self, cog: Tickets) -> None:
        super().__init__(timeout=120)
        self.cog = cog

    @discord.ui.button(
        label="Add opening button",
        style=ButtonStyle.success,
        emoji=_parse_emoji(getattr(emojis.ticket, "open", "🎫")),
    )
    async def add(
        self, interaction: Interaction, button: discord.ui.Button
    ) -> None:
        _ = button
        await interaction.response.send_modal(OpeningButtonAddModal(self.cog))


async def setup(bot) -> None:
    await bot.add_cog(Tickets(bot))
