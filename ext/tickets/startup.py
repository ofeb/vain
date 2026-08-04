"""
Ticket system startup helper.
Call `await sync_ticket_schema(bot)` from your bot's setup_hook or on_ready
if you want an explicit sync outside of the cog_load path.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

logger = logging.getLogger("tickets.startup")


async def sync_ticket_schema(bot: Any) -> None:
    """
    Ensure the tickets schema and all tables exist.
    Safe to call multiple times – uses IF NOT EXISTS throughout.
    """
    schema_file = Path(__file__).with_name("schema.sql")
    if not schema_file.exists():
        logger.error("schema.sql not found next to startup.py")
        return

    sql = schema_file.read_text(encoding="utf-8")
    statements = [s.strip() for s in sql.split(";") if s.strip()]

    async with bot.db.acquire() as conn:
        for stmt in statements:
            try:
                await conn.execute(stmt)
            except Exception as exc:
                # log but continue – partial schema is still useful
                logger.warning("Schema statement failed: %s\n%s", exc, stmt[:120])

    logger.info("Ticket database schema synchronized (%d statements)", len(statements))


async def setup(bot: Any) -> None:
    """Optional: can be loaded as a tiny extension that only syncs schema."""
    await sync_ticket_schema(bot)
