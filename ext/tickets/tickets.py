from __future__ import annotations
import io
import json
import re
from typing import TYPE_CHECKING
import discord
from discord.ext import commands
from core.discord.ctx import Context
from core.discord.hybrid import group
from core.discord.package import Package
from core.managers.permissions import has_permissions
from core.managers.values import color
from .views import TicketControlView, TicketFormModal, TicketOpenView
if TYPE_CHECKING:
    from core.bleed import Bleed
DEFAULT_PANEL_SCRIPT = (
    "{embed}$v{title: Support Tickets}$v"
    "{description: Click a button below to open a ticket with our staff team.}$v"
    "{color: #2B2D31}"
)

class Tickets(Package):
    """ticket panel and lifecycle management"""
    async def cog_load(self) -> None:
        self.bot.add_view(TicketControlView(self))
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
    async def _settings(self, guild_id: int) -> dict:
        row = await self.db.fetchrow(
            "SELECT * FROM ticket_settings WHERE guild_id = $1",
            guild_id,
        )
        if row:
            return dict(row)
        await self.db.execute("INSERT INTO ticket_settings (guild_id) VALUES ($1) ON CONFLICT DO NOTHING", guild_id)
        row = await self.db.fetchrow("SELECT * FROM ticket_settings WHERE guild_id = $1", guild_id)
        return dict(row or {"guild_id": guild_id})
    async def _is_staff(self, member: discord.Member, settings: dict, extra_roles: list[int] | None = None) -> bool:
        if member.guild_permissions.manage_channels:
            return True
        role_ids = set(settings.get("support_role_ids") or [])
        if extra_roles:
            role_ids.update(extra_roles)
        return any(role.id in role_ids for role in member.roles)
    async def _render_panel_embed(self, guild: discord.Guild, script: str | None) -> discord.Embed:
        if script and script != DEFAULT_PANEL_SCRIPT:
            try:
                from core.tools.embed import parse
                payload = await parse(script, sendable=True)
                embed = payload.get("embed")
                if embed:
                    return embed
            except Exception:
                pass
        return discord.Embed(
            title="Support Tickets",
            description="Click a button below to open a ticket.",
            color=color.base,
        )
    async def _send_panel_message(self, guild: discord.Guild, panel: dict, options: list[dict]) -> discord.Message:
        channel = guild.get_channel(int(panel["channel_id"]))
        if not channel or not isinstance(channel, discord.TextChannel):
            raise commands.CommandError("Panel channel is missing or invalid.")
        embed = await self._render_panel_embed(guild, panel.get("embed_script"))
        view = TicketOpenView(self, int(panel["id"]), options, panel.get("panel_type") or "buttons")
        message = await channel.send(embed=embed, view=view)
        self.bot.add_view(view, message_id=message.id)
        await self.db.execute(
            "UPDATE ticket_panels SET message_id = $2 WHERE id = $1",
            panel["id"],
            message.id,
        )
        return message
    async def open_ticket(self, interaction: discord.Interaction, panel_id: int, option_id: int) -> None:
        if not interaction.guild or not isinstance(interaction.user, discord.Member):
            return
        settings = await self._settings(interaction.guild.id)
        if interaction.user.id in (settings.get("blacklist_user_ids") or []):
            await interaction.response.send_message("You are **blacklisted** from opening tickets.", ephemeral=True)
            return
        option = await self.db.fetchrow(
            "SELECT * FROM ticket_options WHERE id = $1 AND panel_id = $2 AND active = TRUE",
            option_id,
            panel_id,
        )
        if not option:
            await interaction.response.send_message("That ticket option is unavailable.", ephemeral=True)
            return
        open_count = await self.db.fetchval(
            "SELECT COUNT(*) FROM tickets WHERE guild_id = $1 AND user_id = $2 AND status = 'open'",
            interaction.guild.id,
            interaction.user.id,
        )
        max_open = int(settings.get("max_open_per_user") or 1)
        if open_count >= max_open:
            await interaction.response.send_message(
                f"You already have **{open_count}** open ticket(s). Close one before opening another.",
                ephemeral=True,
            )
            return
        if option.get("form_id"):
            form = await self.db.fetchrow(
                "SELECT questions FROM ticket_forms WHERE id = $1 AND guild_id = $2",
                option["form_id"],
                interaction.guild.id,
            )
            questions = form["questions"] if form else []
            if isinstance(questions, str):
                questions = json.loads(questions)
            if questions:
                await interaction.response.send_modal(
                    TicketFormModal(self, panel_id, option_id, questions)
                )
                return
        await interaction.response.defer(ephemeral=True)
        await self.create_ticket_channel(interaction, panel_id, option_id, None)
    async def create_ticket_channel(
        self,
        interaction: discord.Interaction,
        panel_id: int,
        option_id: int,
        answers: dict | None,
    ) -> None:
        assert interaction.guild and isinstance(interaction.user, discord.Member)
        settings = await self._settings(interaction.guild.id)
        option = await self.db.fetchrow("SELECT * FROM ticket_options WHERE id = $1", option_id)
        panel = await self.db.fetchrow("SELECT * FROM ticket_panels WHERE id = $1", panel_id)
        if not option or not panel:
            if interaction.response.is_done():
                await interaction.followup.send("Ticket option no longer exists.", ephemeral=True)
            else:
                await interaction.response.send_message("Ticket option no longer exists.", ephemeral=True)
            return
        category_id = option.get("category_id") or settings.get("category_id")
        category = interaction.guild.get_channel(int(category_id)) if category_id else None
        name_format = settings.get("channel_name_format") or "ticket-{user}"
        channel_name = (
            name_format.replace("{user}", interaction.user.name.lower())
            .replace("{id}", str(interaction.user.id))
            .replace("{option}", str(option.get("name") or "ticket"))
        )
        channel_name = re.sub(r"[^a-z0-9-]", "-", channel_name.lower())[:100]
        overwrites = {
            interaction.guild.default_role: discord.PermissionOverwrite(view_channel=False),
            interaction.user: discord.PermissionOverwrite(
                view_channel=True,
                send_messages=True,
                attach_files=True,
                embed_links=True,
                read_message_history=True,
            ),
            interaction.guild.me: discord.PermissionOverwrite(
                view_channel=True,
                send_messages=True,
                manage_channels=True,
                manage_messages=True,
            ),
        }
        role_ids = list(settings.get("support_role_ids") or []) + list(option.get("support_role_ids") or [])
        for role_id in set(role_ids):
            role = interaction.guild.get_role(int(role_id))
            if role:
                overwrites[role] = discord.PermissionOverwrite(
                    view_channel=True,
                    send_messages=True,
                    read_message_history=True,
                )
        channel = await interaction.guild.create_text_channel(
            name=channel_name or f"ticket-{interaction.user.id}",
            category=category if isinstance(category, discord.CategoryChannel) else None,
            overwrites=overwrites,
            reason=f"Ticket opened by {interaction.user}",
        )
        ticket_id = await self.db.fetchval(
            """
            INSERT INTO tickets (guild_id, channel_id, user_id, option_id, panel_id, form_answers, status)
            VALUES ($1, $2, $3, $4, $5, $6::jsonb, 'open')
            RETURNING id
            """,
            interaction.guild.id,
            channel.id,
            interaction.user.id,
            option_id,
            panel_id,
            json.dumps(answers or {}),
        )
        greeting = settings.get("greeting_message") or (
            f"{interaction.user.mention}, thanks for opening a ticket.\n"
            f"**Type:** {option.get('label') or option.get('name')}\n"
            "A staff member will be with you shortly."
        )
        if answers:
            answer_lines = "\n".join(f"**{key}:** {value}" for key, value in answers.items())
            greeting += f"\n\n**Responses**\n{answer_lines}"
        embed = discord.Embed(description=greeting, color=color.base)
        embed.set_author(name=str(option.get("label") or option.get("name")))
        view = TicketControlView(self)
        self.bot.add_view(view)
        await channel.send(content=interaction.user.mention, embed=embed, view=view)
        if interaction.response.is_done():
            await interaction.followup.send(f"Created {channel.mention}", ephemeral=True)
        else:
            await interaction.response.send_message(f"Created {channel.mention}", ephemeral=True)
        log_channel_id = settings.get("log_channel_id")
        if log_channel_id:
            log_channel = interaction.guild.get_channel(int(log_channel_id))
            if isinstance(log_channel, discord.TextChannel):
                log_embed = discord.Embed(
                    title="Ticket Opened",
                    description=f"{interaction.user.mention} opened **{option.get('label')}** in {channel.mention}",
                    color=color.base,
                    timestamp=discord.utils.utcnow(),
                )
                await log_channel.send(embed=log_embed)
    async def _ticket_row(self, channel_id: int) -> dict | None:
        row = await self.db.fetchrow("SELECT * FROM tickets WHERE channel_id = $1", channel_id)
        return dict(row) if row else None
    async def claim_ticket(self, interaction: discord.Interaction) -> None:
        if not interaction.guild or not isinstance(interaction.user, discord.Member) or not interaction.channel:
            return
        ticket = await self.db.fetchrow(
            "SELECT * FROM tickets WHERE channel_id = $1",
            interaction.channel.id,
        )
        if not ticket:
            await interaction.response.send_message("Ticket not found.", ephemeral=True)
            return
        settings = await self._settings(interaction.guild.id)
        if not settings.get("claim_enabled", True):
            await interaction.response.send_message("Claiming is disabled.", ephemeral=True)
            return
        if not await self._is_staff(interaction.user, settings):
            await interaction.response.send_message("You cannot claim this ticket.", ephemeral=True)
            return
        if ticket["claimed_by"]:
            await interaction.response.send_message(
                f"Already claimed by <@{ticket['claimed_by']}>.",
                ephemeral=True,
            )
            return
        await self.db.execute(
            "UPDATE tickets SET claimed_by = $2 WHERE id = $1",
            ticket["id"],
            interaction.user.id,
        )
        channel = interaction.guild.get_channel(int(ticket["channel_id"]))
        if isinstance(channel, discord.TextChannel):
            await channel.send(f"{interaction.user.mention} claimed this ticket.")
        await interaction.response.send_message("You claimed this ticket.", ephemeral=True)
    async def close_ticket(self, interaction: discord.Interaction) -> None:
        if not interaction.guild or not isinstance(interaction.user, discord.Member) or not interaction.channel:
            return
        ticket = await self.db.fetchrow(
            "SELECT * FROM tickets WHERE channel_id = $1",
            interaction.channel.id,
        )
        if not ticket:
            await interaction.response.send_message("Ticket not found.", ephemeral=True)
            return
        settings = await self._settings(interaction.guild.id)
        is_owner = interaction.user.id == ticket["user_id"]
        is_staff = await self._is_staff(interaction.user, settings)
        if not is_staff and not (is_owner and settings.get("creator_can_close", True)):
            await interaction.response.send_message("You cannot close this ticket.", ephemeral=True)
            return
        channel = interaction.guild.get_channel(int(ticket["channel_id"]))
        if not isinstance(channel, discord.TextChannel):
            await interaction.response.send_message("Ticket channel is gone.", ephemeral=True)
            return
        member = interaction.guild.get_member(int(ticket["user_id"]))
        if member:
            await channel.set_permissions(member, send_messages=False)
        await self.db.execute(
            "UPDATE tickets SET status = 'closed', closed_at = NOW(), closed_by = $2 WHERE id = $1",
            ticket["id"],
            interaction.user.id,
        )
        close_message = settings.get("close_message") or "This ticket has been closed."
        await channel.send(embed=discord.Embed(description=close_message, color=color.base))
        await interaction.response.send_message("Ticket closed.", ephemeral=True)
    async def delete_ticket(self, interaction: discord.Interaction) -> None:
        if not interaction.guild or not isinstance(interaction.user, discord.Member) or not interaction.channel:
            return
        ticket = await self.db.fetchrow(
            "SELECT * FROM tickets WHERE channel_id = $1",
            interaction.channel.id,
        )
        if not ticket:
            await interaction.response.send_message("Ticket not found.", ephemeral=True)
            return
        settings = await self._settings(interaction.guild.id)
        if not await self._is_staff(interaction.user, settings):
            await interaction.response.send_message("You cannot delete this ticket.", ephemeral=True)
            return
        channel = interaction.guild.get_channel(int(ticket["channel_id"]))
        transcript = ""
        if isinstance(channel, discord.TextChannel):
            lines = []
            async for message in channel.history(limit=500, oldest_first=True):
                lines.append(f"[{message.created_at:%Y-%m-%d %H:%M}] {message.author}: {message.content}")
            transcript = "\n".join(lines) or "No messages."
            transcript_channel_id = settings.get("transcript_channel_id") or settings.get("log_channel_id")
            if transcript_channel_id:
                log_channel = interaction.guild.get_channel(int(transcript_channel_id))
                if isinstance(log_channel, discord.TextChannel):
                    file = discord.File(
                        io.BytesIO(transcript.encode("utf-8")),
                        filename=f"ticket-{ticket['id']}.txt",
                    )
                    await log_channel.send(
                        content=f"Transcript for ticket **#{ticket['id']}** closed by {interaction.user.mention}",
                        file=file,
                    )
            await channel.delete(reason=f"Ticket deleted by {interaction.user}")
        await self.db.execute("DELETE FROM tickets WHERE id = $1", ticket["id"])
        if interaction.response.is_done():
            await interaction.followup.send("Ticket deleted.", ephemeral=True)
        else:
            await interaction.response.send_message("Ticket deleted.", ephemeral=True)
    @group(name="tickets", aliases=["ticket"], invoke_without_command=True, guild_only=True)
    @has_permissions(manage_guild=True)
    async def tickets(self, ctx: Context) -> None:
        if ctx.invoked_subcommand is None:
            await ctx.send_help(ctx.command)
    @tickets.command(name="setup")
    async def tickets_setup(
        self,
        ctx: Context,
        category: discord.CategoryChannel,
        log_channel: discord.TextChannel = None,
    ) -> None:
        await self.db.execute(
            """
            INSERT INTO ticket_settings (guild_id, category_id, log_channel_id)
            VALUES ($1, $2, $3)
            ON CONFLICT (guild_id)
            DO UPDATE SET category_id = EXCLUDED.category_id, log_channel_id = COALESCE(EXCLUDED.log_channel_id, ticket_settings.log_channel_id)
            """,
            ctx.guild.id,
            category.id,
            log_channel.id if log_channel else None,
        )
        await ctx.success(f"Ticket system configured with category {category.mention}.")
    @tickets.group(name="panels", invoke_without_command=True)
    async def tickets_panels(self, ctx: Context) -> None:
        if ctx.invoked_subcommand is None:
            await ctx.send_help(ctx.command)
    @tickets_panels.command(name="add")
    async def tickets_panels_add(
        self,
        ctx: Context,
        name: str,
        channel: discord.TextChannel,
        panel_type: str = "buttons",
    ) -> None:
        panel_type = panel_type.lower()
        if panel_type not in {"buttons", "dropdown"}:
            return await ctx.fail("Panel type must be `buttons` or `dropdown`.")
        row = await self.db.fetchrow(
            """
            INSERT INTO ticket_panels (guild_id, name, channel_id, panel_type, embed_script)
            VALUES ($1, $2, $3, $4, $5)
            RETURNING *
            """,
            ctx.guild.id,
            name.lower(),
            channel.id,
            panel_type,
            DEFAULT_PANEL_SCRIPT,
        )
        await self._send_panel_message(ctx.guild, dict(row), [])
        await ctx.success(f"Created panel **`{name}`** in {channel.mention}. Add options with `tickets options add`.")
    @tickets_panels.command(name="list")
    async def tickets_panels_list(self, ctx: Context) -> None:
        rows = await self.db.fetch(
            "SELECT name, channel_id, panel_type, message_id FROM ticket_panels WHERE guild_id = $1 ORDER BY name",
            ctx.guild.id,
        )
        if not rows:
            return await ctx.fail("No ticket panels configured.")
        lines = [
            f"**`{row['name']}`** — <#{row['channel_id']}> ({row['panel_type']})"
            + (f" • [message](https://discord.com/channels/{ctx.guild.id}/{row['channel_id']}/{row['message_id']})" if row["message_id"] else "")
            for row in rows
        ]
        await ctx.send(embed=discord.Embed(title="Ticket Panels", description="\n".join(lines), color=color.base))
    @tickets_panels.command(name="remove", aliases=["delete"])
    async def tickets_panels_remove(self, ctx: Context, name: str) -> None:
        row = await self.db.fetchrow(
            "DELETE FROM ticket_panels WHERE guild_id = $1 AND name = $2 RETURNING message_id, channel_id",
            ctx.guild.id,
            name.lower(),
        )
        if not row:
            return await ctx.fail(f"No panel named **`{name}`**.")
        if row["message_id"]:
            channel = ctx.guild.get_channel(int(row["channel_id"]))
            if isinstance(channel, discord.TextChannel):
                with discord.utils.suppress(discord.HTTPException):
                    message = await channel.fetch_message(int(row["message_id"]))
                    await message.delete()
        await ctx.success(f"Removed panel **`{name}`**.")
    @tickets.command(name="resend")
    async def tickets_resend(self, ctx: Context, name: str) -> None:
        panel = await self.db.fetchrow(
            "SELECT * FROM ticket_panels WHERE guild_id = $1 AND name = $2",
            ctx.guild.id,
            name.lower(),
        )
        if not panel:
            return await ctx.fail(f"No panel named **`{name}`**.")
        options = await self.db.fetch(
            "SELECT * FROM ticket_options WHERE panel_id = $1 AND active = TRUE ORDER BY position, id",
            panel["id"],
        )
        if not options:
            return await ctx.fail("That panel has no active options.")
        if panel["message_id"]:
            channel = ctx.guild.get_channel(int(panel["channel_id"]))
            if isinstance(channel, discord.TextChannel):
                with discord.utils.suppress(discord.HTTPException):
                    message = await channel.fetch_message(int(panel["message_id"]))
                    await message.delete()
        await self._send_panel_message(ctx.guild, dict(panel), [dict(row) for row in options])
        await ctx.success(f"Resent panel **`{name}`**.")
    @tickets.group(name="options", invoke_without_command=True)
    async def tickets_options(self, ctx: Context) -> None:
        if ctx.invoked_subcommand is None:
            await ctx.send_help(ctx.command)
    @tickets_options.command(name="add")
    async def tickets_options_add(
        self,
        ctx: Context,
        panel: str,
        name: str,
        label: str,
        emoji: str = None,
        *,
        description: str = None,
    ) -> None:
        panel_row = await self.db.fetchrow(
            "SELECT id FROM ticket_panels WHERE guild_id = $1 AND name = $2",
            ctx.guild.id,
            panel.lower(),
        )
        if not panel_row:
            return await ctx.fail(f"No panel named **`{panel}`**.")
        await self.db.execute(
            """
            INSERT INTO ticket_options (guild_id, panel_id, name, label, emoji, description)
            VALUES ($1, $2, $3, $4, $5, $6)
            """,
            ctx.guild.id,
            panel_row["id"],
            name.lower(),
            label,
            emoji,
            description,
        )
        await self.tickets_resend(ctx, panel)
    @tickets_options.command(name="remove", aliases=["delete"])
    async def tickets_options_remove(self, ctx: Context, panel: str, name: str) -> None:
        panel_row = await self.db.fetchrow(
            "SELECT id FROM ticket_panels WHERE guild_id = $1 AND name = $2",
            ctx.guild.id,
            panel.lower(),
        )
        if not panel_row:
            return await ctx.fail(f"No panel named **`{panel}`**.")
        result = await self.db.execute(
            "DELETE FROM ticket_options WHERE panel_id = $1 AND name = $2",
            panel_row["id"],
            name.lower(),
        )
        if result == "DELETE 0":
            return await ctx.fail(f"No option named **`{name}`** on that panel.")
        await self.tickets_resend(ctx, panel)
    @tickets_options.command(name="list")
    async def tickets_options_list(self, ctx: Context, panel: str) -> None:
        panel_row = await self.db.fetchrow(
            "SELECT id FROM ticket_panels WHERE guild_id = $1 AND name = $2",
            ctx.guild.id,
            panel.lower(),
        )
        if not panel_row:
            return await ctx.fail(f"No panel named **`{panel}`**.")
        rows = await self.db.fetch(
            "SELECT name, label, emoji, description, active FROM ticket_options WHERE panel_id = $1 ORDER BY position, id",
            panel_row["id"],
        )
        if not rows:
            return await ctx.fail("That panel has no options.")
        lines = [
            f"**`{row['name']}`** — {row['label']}"
            + (f" {row['emoji']}" if row['emoji'] else "")
            + (" `(inactive)`" if not row["active"] else "")
            for row in rows
        ]
        await ctx.send(embed=discord.Embed(title=f"Options for {panel}", description="\n".join(lines), color=color.base))
    @tickets.group(name="forms", invoke_without_command=True)
    async def tickets_forms(self, ctx: Context) -> None:
        if ctx.invoked_subcommand is None:
            await ctx.send_help(ctx.command)
    @tickets_forms.command(name="create", aliases=["add"])
    async def tickets_forms_create(self, ctx: Context, name: str, *, questions: str) -> None:
        parsed = []
        for index, question in enumerate(questions.split(";"), start=1):
            label = question.strip()
            if not label:
                continue
            parsed.append({"key": f"q{index}", "label": label, "required": True})
        if not parsed:
            return await ctx.fail("Provide at least one question separated by `;`.")
        await self.db.execute(
            """
            INSERT INTO ticket_forms (guild_id, name, questions)
            VALUES ($1, $2, $3::jsonb)
            ON CONFLICT (guild_id, name)
            DO UPDATE SET questions = EXCLUDED.questions
            """,
            ctx.guild.id,
            name.lower(),
            json.dumps(parsed),
        )
        await ctx.success(f"Saved form **`{name}`** with **{len(parsed)}** question(s).")
    @tickets_forms.command(name="list")
    async def tickets_forms_list(self, ctx: Context) -> None:
        rows = await self.db.fetch(
            "SELECT name, questions FROM ticket_forms WHERE guild_id = $1 ORDER BY name",
            ctx.guild.id,
        )
        if not rows:
            return await ctx.fail("No ticket forms saved.")
        lines = []
        for row in rows:
            questions = row["questions"]
            if isinstance(questions, str):
                questions = json.loads(questions)
            lines.append(f"**`{row['name']}`** — {len(questions)} question(s)")
        await ctx.send(embed=discord.Embed(title="Ticket Forms", description="\n".join(lines), color=color.base))
    @tickets_forms.command(name="remove", aliases=["delete"])
    async def tickets_forms_remove(self, ctx: Context, name: str) -> None:
        result = await self.db.execute(
            "DELETE FROM ticket_forms WHERE guild_id = $1 AND name = $2",
            ctx.guild.id,
            name.lower(),
        )
        if result == "DELETE 0":
            return await ctx.fail(f"No form named **`{name}`**.")
        await ctx.success(f"Removed form **`{name}`**.")
    @tickets.command(name="claim")
    async def tickets_claim(self, ctx: Context) -> None:
        ticket = await self._ticket_row(ctx.channel.id)
        if not ticket:
            return await ctx.fail("This is not a ticket channel.")
        interaction = _FakeInteraction(ctx)
        await self.claim_ticket(interaction)
    @tickets.command(name="close")
    async def tickets_close(self, ctx: Context, *, reason: str = None) -> None:
        ticket = await self._ticket_row(ctx.channel.id)
        if not ticket:
            return await ctx.fail("This is not a ticket channel.")
        interaction = _FakeInteraction(ctx)
        await self.close_ticket(interaction)
        if reason:
            await ctx.channel.send(f"**Reason:** {reason}")
    @tickets.command(name="reopen")
    async def tickets_reopen(self, ctx: Context) -> None:
        ticket = await self._ticket_row(ctx.channel.id)
        if not ticket:
            return await ctx.fail("This is not a ticket channel.")
        settings = await self._settings(ctx.guild.id)
        if not await self._is_staff(ctx.author, settings):
            return await ctx.fail("You cannot reopen this ticket.")
        member = ctx.guild.get_member(int(ticket["user_id"]))
        if member:
            await ctx.channel.set_permissions(
                member,
                view_channel=True,
                send_messages=True,
                attach_files=True,
                embed_links=True,
                read_message_history=True,
            )
        await self.db.execute(
            "UPDATE tickets SET status = 'open', closed_at = NULL, closed_by = NULL WHERE id = $1",
            ticket["id"],
        )
        await ctx.success("Reopened this ticket.")
    @tickets.command(name="delete")
    async def tickets_delete(self, ctx: Context) -> None:
        ticket = await self._ticket_row(ctx.channel.id)
        if not ticket:
            return await ctx.fail("This is not a ticket channel.")
        interaction = _FakeInteraction(ctx)
        await self.delete_ticket(interaction)
    @tickets.command(name="add")
    async def tickets_add(self, ctx: Context, member: discord.Member) -> None:
        ticket = await self._ticket_row(ctx.channel.id)
        if not ticket:
            return await ctx.fail("This is not a ticket channel.")
        await ctx.channel.set_permissions(
            member,
            view_channel=True,
            send_messages=True,
            read_message_history=True,
        )
        await ctx.success(f"Added {member.mention} to this ticket.")
    @tickets.command(name="remove")
    async def tickets_remove(self, ctx: Context, member: discord.Member) -> None:
        ticket = await self._ticket_row(ctx.channel.id)
        if not ticket:
            return await ctx.fail("This is not a ticket channel.")
        await ctx.channel.set_permissions(member, overwrite=None)
        await ctx.success(f"Removed {member.mention} from this ticket.")
    @tickets.group(name="blacklist", invoke_without_command=True)
    async def tickets_blacklist(self, ctx: Context, member: discord.Member = None) -> None:
        if member is None:
            return await ctx.send_help(ctx.command)
        settings = await self._settings(ctx.guild.id)
        ids = list(settings.get("blacklist_user_ids") or [])
        if member.id in ids:
            return await ctx.fail(f"{member.mention} is already blacklisted.")
        ids.append(member.id)
        await self.db.execute(
            "UPDATE ticket_settings SET blacklist_user_ids = $2 WHERE guild_id = $1",
            ctx.guild.id,
            ids,
        )
        await ctx.success(f"Blacklisted {member.mention} from opening tickets.")
    @tickets_blacklist.command(name="remove")
    async def tickets_blacklist_remove(self, ctx: Context, member: discord.Member) -> None:
        settings = await self._settings(ctx.guild.id)
        ids = [value for value in (settings.get("blacklist_user_ids") or []) if value != member.id]
        await self.db.execute(
            "UPDATE ticket_settings SET blacklist_user_ids = $2 WHERE guild_id = $1",
            ctx.guild.id,
            ids,
        )
        await ctx.success(f"Removed {member.mention} from the ticket blacklist.")
    @tickets_blacklist.command(name="list")
    async def tickets_blacklist_list(self, ctx: Context) -> None:
        settings = await self._settings(ctx.guild.id)
        ids = settings.get("blacklist_user_ids") or []
        if not ids:
            return await ctx.fail("No users are blacklisted from tickets.")
        await ctx.send(embed=discord.Embed(
            title="Ticket Blacklist",
            description=" ".join(f"<@{user_id}>" for user_id in ids),
            color=color.base,
        ))
    @tickets.command(name="support")
    async def tickets_support(self, ctx: Context, *roles: discord.Role) -> None:
        if not roles:
            return await ctx.fail("Mention at least one support role.")
        await self.db.execute(
            """
            INSERT INTO ticket_settings (guild_id, support_role_ids)
            VALUES ($1, $2)
            ON CONFLICT (guild_id)
            DO UPDATE SET support_role_ids = EXCLUDED.support_role_ids
            """,
            ctx.guild.id,
            [role.id for role in roles],
        )
        await ctx.success("Updated ticket support roles.")

class _FakeInteraction:
    def __init__(self, ctx: Context) -> None:
        self.guild = ctx.guild
        self.user = ctx.author
        self.channel = ctx.channel
        self.response = self
        self._ctx = ctx
        self._done = False
    def is_done(self) -> bool:
        return self._done
    async def send_message(self, content: str, *, ephemeral: bool = False) -> None:
        self._done = True
        if ephemeral:
            await self._ctx.send(content, delete_after=10)
        else:
            await self._ctx.send(content)
    async def defer(self, *, ephemeral: bool = False) -> None:
        self._done = True

async def setup(bot: Bleed) -> None:
    await bot.add_cog(Tickets(bot))
