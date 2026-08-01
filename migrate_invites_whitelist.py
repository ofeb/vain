"""one-off migration: add whitelist column to moderation.invites on existing dbs"""

import asyncio

import asyncpg

from config import database


async def main() -> None:
    conn = await asyncpg.connect(database.dsn2)
    try:
        await conn.execute(
            "ALTER TABLE moderation.invites ADD COLUMN IF NOT EXISTS whitelist TEXT[] NOT NULL DEFAULT ARRAY[]::TEXT[]"
        )
        exists = await conn.fetchval(
            "SELECT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema = 'moderation' AND table_name = 'invites' AND column_name = 'whitelist')"
        )
    finally:
        await conn.close()
    print(f"migrated moderation.invites.whitelist (present={exists})")


if __name__ == "__main__":
    asyncio.run(main())
