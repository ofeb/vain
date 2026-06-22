from __future__ import annotations

import json

import discord

from core.discord.package import Package

from .views import TicketOpenView


class TicketsEvents:
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

