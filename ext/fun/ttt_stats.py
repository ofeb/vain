from __future__ import annotations

from typing import TYPE_CHECKING, Any

import discord

from config import color

from core.discord.views.embed import compose, body

if TYPE_CHECKING:
    from core.vain import Vain

def is_group_chat(channel: discord.abc.MessageableChannel | None) -> bool:
    if channel is None:
        return False
    if isinstance(channel, discord.GroupChannel):
        return True
    channel_type = getattr(channel, "type", None)
    if channel_type == discord.ChannelType.group:
        return True
    group_dm = getattr(discord.ChannelType, "group_dm", None)
    if group_dm is not None and channel_type == group_dm:
        return True
    if isinstance(channel, discord.DMChannel):
        recipients = getattr(channel, "recipients", None) or []
        if len(recipients) > 1:
            return True
    return False

def is_direct_message(channel: discord.abc.MessageableChannel | None) -> bool:
    if channel is None:
        return False
    if isinstance(channel, discord.DMChannel) and not is_group_chat(channel):
        return True
    return getattr(channel, "type", None) == discord.ChannelType.private

def scope_ids(
    channel: discord.abc.MessageableChannel | None,
    guild: discord.Guild | None,
) -> tuple[int | None, int | None]:
    """return guild_id and group channel_id for stat storage."""
    if channel is None:
        return (guild.id if guild else None, None)
    if guild is not None and not is_group_chat(channel):
        return guild.id, None
    if is_group_chat(channel) or (guild is None and not is_direct_message(channel)):
        return None, channel.id
    return None, None

def group_channel_id(channel: discord.abc.MessageableChannel | None) -> int | None:
    _guild_id, channel_id = scope_ids(channel, None)
    return channel_id

def guild_scope_id(
    channel: discord.abc.MessageableChannel | None,
    guild: discord.Guild | None,
) -> int | None:
    guild_id, _channel_id = scope_ids(channel, guild)
    return guild_id

async def _bump_global(db: Any, user_id: int, column: str) -> None:
    await db.execute(
        f"""
        INSERT INTO tictactoe (user_id, {column}) VALUES ($1, 1)
        ON CONFLICT (user_id) DO UPDATE SET {column} = tictactoe.{column} + 1
        """,
        user_id,
    )

async def _bump_guild(db: Any, guild_id: int, user_id: int, column: str) -> None:
    await db.execute(
        f"""
        INSERT INTO tictactoe_guild (guild_id, user_id, {column}) VALUES ($1, $2, 1)
        ON CONFLICT (guild_id, user_id) DO UPDATE SET {column} = tictactoe_guild.{column} + 1
        """,
        guild_id,
        user_id,
    )

async def _bump_channel(db: Any, channel_id: int, user_id: int, column: str) -> None:
    await db.execute(
        f"""
        INSERT INTO tictactoe_channel (channel_id, user_id, {column}) VALUES ($1, $2, 1)
        ON CONFLICT (channel_id, user_id) DO UPDATE SET {column} = tictactoe_channel.{column} + 1
        """,
        channel_id,
        user_id,
    )

async def _bump(
    db: Any,
    *,
    guild_id: int | None,
    channel_id: int | None,
    user_id: int,
    column: str,
    count_bot: bool = False,
    bot_id: int | None = None,
) -> None:
    if not count_bot and bot_id is not None and user_id == bot_id:
        return
    await _bump_global(db, user_id, column)
    if guild_id is not None:
        await _bump_guild(db, guild_id, user_id, column)
    if channel_id is not None:
        await _bump_channel(db, channel_id, user_id, column)

async def record_ttt_game(
    bot: Vain,
    *,
    guild_id: int | None,
    channel_id: int | None,
    player_x_id: int,
    player_o_id: int | None,
    vs_me: bool,
    winner: str,
) -> None:
    db = bot.db
    bot_id = bot.user.id if bot.user else None

    if winner == "tie":
        await _bump(
            db,
            guild_id=guild_id,
            channel_id=channel_id,
            user_id=player_x_id,
            column="ties",
            bot_id=bot_id,
        )
        if not vs_me and player_o_id:
            await _bump(
                db,
                guild_id=guild_id,
                channel_id=channel_id,
                user_id=player_o_id,
                column="ties",
                bot_id=bot_id,
            )
        if vs_me and channel_id and bot_id:
            await _bump_channel(db, channel_id, bot_id, "ties")
        return

    if vs_me:
        if winner == "O" and bot_id:
            await _bump(
                db,
                guild_id=guild_id,
                channel_id=channel_id,
                user_id=player_x_id,
                column="losses",
                bot_id=bot_id,
            )
            if channel_id:
                await _bump_channel(db, channel_id, bot_id, "wins")
            elif guild_id:
                await _bump_guild(db, guild_id, bot_id, "wins")
            return
        if winner == "X":
            await _bump(
                db,
                guild_id=guild_id,
                channel_id=channel_id,
                user_id=player_x_id,
                column="wins",
                bot_id=bot_id,
            )
            if channel_id and bot_id:
                await _bump_channel(db, channel_id, bot_id, "losses")
            elif guild_id and bot_id:
                await _bump_guild(db, guild_id, bot_id, "losses")
            return

    winner_id = player_x_id if winner == "X" else player_o_id
    loser_id = player_o_id if winner == "X" else player_x_id

    if winner_id:
        await _bump(
            db,
            guild_id=guild_id,
            channel_id=channel_id,
            user_id=winner_id,
            column="wins",
            count_bot=channel_id is not None,
            bot_id=bot_id,
        )
    if loser_id:
        await _bump(
            db,
            guild_id=guild_id,
            channel_id=channel_id,
            user_id=loser_id,
            column="losses",
            count_bot=channel_id is not None,
            bot_id=bot_id,
        )

async def fetch_ttt_stats(db: Any, user_id: int) -> dict[str, int]:
    row = await db.fetchrow(
        "SELECT wins, losses, ties FROM tictactoe WHERE user_id = $1",
        user_id,
    )
    if not row:
        return {"wins": 0, "losses": 0, "ties": 0}
    return {
        "wins": int(row["wins"] or 0),
        "losses": int(row["losses"] or 0),
        "ties": int(row["ties"] or 0),
    }

async def fetch_ttt_leaderboard(
    db: Any,
    *,
    guild_id: int | None = None,
    channel_id: int | None = None,
    limit: int = 30,
) -> list[dict[str, int]]:
    if channel_id is not None:
        rows = await db.fetch(
            """
            SELECT user_id, wins
            FROM tictactoe_channel
            WHERE channel_id = $1 AND wins > 0
            ORDER BY wins DESC
            LIMIT $2
            """,
            channel_id,
            limit,
            cached=False,
        )
    elif guild_id is None:
        rows = await db.fetch(
            """
            SELECT user_id, wins
            FROM tictactoe
            WHERE wins > 0
            ORDER BY wins DESC
            LIMIT $1
            """,
            limit,
            cached=False,
        )
    else:
        rows = await db.fetch(
            """
            SELECT user_id, wins
            FROM tictactoe_guild
            WHERE guild_id = $1 AND wins > 0
            ORDER BY wins DESC
            LIMIT $2
            """,
            guild_id,
            limit,
            cached=False,
        )
    return [{"user_id": int(row["user_id"]), "wins": int(row["wins"] or 0)} for row in rows]

def default_leaderboard_scope(channel: discord.abc.MessageableChannel | None) -> str:
    if is_group_chat(channel):
        return "group"
    if isinstance(channel, discord.abc.GuildChannel):
        return "guild"
    if channel is not None and getattr(channel, "guild", None) is None and not is_direct_message(channel):
        return "group"
    return "global"

async def leaderboard_rows(
    db: Any,
    channel: discord.abc.MessageableChannel | None,
    guild: discord.Guild | None,
    *,
    scope: str,
) -> list[dict[str, int]]:
    guild_id, channel_id = scope_ids(channel, guild)
    if scope == "group":
        if channel_id is None:
            return []
        return await fetch_ttt_leaderboard(db, channel_id=channel_id)
    if scope == "guild":
        if guild_id is None:
            return []
        return await fetch_ttt_leaderboard(db, guild_id=guild_id)
    return await fetch_ttt_leaderboard(db)

async def user_display(bot: Vain, user_id: int) -> str:
    if bot.user and user_id == bot.user.id:
        return f"{bot.user.display_name}#0"
    user = bot.get_user(user_id)
    if user is None:
        try:
            user = await bot.fetch_user(user_id)
        except discord.HTTPException:
            user = None
    if user is None:
        return "Unknown user#0"
    if user.discriminator and user.discriminator != "0":
        return f"{user.name}#{user.discriminator}"
    return f"{user.display_name}#0"

def build_stats_embed(author: discord.User, stats: dict[str, int]) -> discord.Embed:
    wins = stats["wins"]
    losses = stats["losses"]
    ties = stats["ties"]
    matches = wins + losses + ties
    ratio = round(wins / matches, 2) if matches else 0
    embed = discord.Embed(
        title="Tic-Tac-Toe Statistics",
        color=color.base,
        description=compose(
            body(
                f"**Wins**: {wins}",
                f"**Losses**: {losses}",
                f"**Matches**: {matches}",
                f"**Ratio**: {ratio}",
            ),
        ),
    )
    embed.set_author(name=author.display_name, icon_url=author.display_avatar.url)
    return embed

async def build_leaderboard_pages(
    bot: Vain,
    *,
    rows: list[dict[str, int]],
    author: discord.User,
    title: str = "Most Tic-Tac-Toe wins",
    per_page: int = 10,
) -> list[discord.Embed]:
    if not rows:
        embed = discord.Embed(
            title=title,
            color=color.base,
            description=compose(body("No statistics recorded yet.")),
        )
        embed.set_author(name=author.display_name, icon_url=author.display_avatar.url)
        return [embed]

    total_pages = max(1, (len(rows) + per_page - 1) // per_page)
    pages: list[discord.Embed] = []
    for index in range(0, len(rows), per_page):
        chunk = rows[index : index + per_page]
        page_num = index // per_page + 1
        lines: list[str] = []
        for offset, row in enumerate(chunk, start=index + 1):
            name = await user_display(bot, row["user_id"])
            wins = f"{row['wins']:,}"
            lines.append(f"`{offset}` **{name}** - `{wins}` wins")
        embed = discord.Embed(
            title=title,
            color=color.base,
            description=compose(body(*lines)),
        )
        embed.set_author(name=author.display_name, icon_url=author.display_avatar.url)
        embed.set_footer(text=f"Page {page_num}/{total_pages} ({len(rows)} {'entry' if len(rows) == 1 else 'entries'})")
        pages.append(embed)
    return pages
