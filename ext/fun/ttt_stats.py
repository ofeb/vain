from __future__ import annotations

from typing import TYPE_CHECKING, Any

import discord

if TYPE_CHECKING:
    from core.bleed import Bleed


def is_group_chat(channel: discord.abc.MessageableChannel | None) -> bool:
    if channel is None:
        return False
    if isinstance(channel, discord.GroupChannel):
        return True
    channel_type = getattr(channel, "type", None)
    return channel_type in {
        discord.ChannelType.group,
        getattr(discord.ChannelType, "group_dm", None),
    }


def group_channel_id(channel: discord.abc.MessageableChannel | None) -> int | None:
    return channel.id if is_group_chat(channel) else None


def guild_scope_id(
    channel: discord.abc.MessageableChannel | None,
    guild: discord.Guild | None,
) -> int | None:
    if guild is None or is_group_chat(channel):
        return None
    return guild.id


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
    bot: Bleed,
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
        )
    return [{"user_id": int(row["user_id"]), "wins": int(row["wins"] or 0)} for row in rows]


def default_leaderboard_scope(channel: discord.abc.MessageableChannel | None) -> str:
    if is_group_chat(channel):
        return "group"
    if isinstance(channel, discord.abc.GuildChannel):
        return "guild"
    return "global"


async def user_display(bot: Bleed, user_id: int) -> str:
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
        description=(
            f"**Wins**: {wins}\n"
            f"**Losses**: {losses}\n"
            f"**Matches**: {matches}\n"
            f"**Ratio**: {ratio}"
        ),
    )
    embed.set_author(name=author.display_name, icon_url=author.display_avatar.url)
    return embed


async def build_leaderboard_pages(
    bot: Bleed,
    *,
    rows: list[dict[str, int]],
    author: discord.User,
    title: str = "Most Tic-Tac-Toe wins",
    per_page: int = 10,
) -> list[discord.Embed]:
    if not rows:
        embed = discord.Embed(
            title=title,
            description="No statistics recorded yet.",
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
        embed = discord.Embed(title=title, description="\n".join(lines))
        embed.set_author(name=author.display_name, icon_url=author.display_avatar.url)
        embed.set_footer(text=f"Page {page_num}/{total_pages} ({len(rows)} {'entry' if len(rows) == 1 else 'entries'})")
        pages.append(embed)
    return pages
