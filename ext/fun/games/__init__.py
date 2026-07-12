from __future__ import annotations

import asyncio
import contextlib
import random
from typing import TYPE_CHECKING, Optional

import discord

from core.managers.values import color
from .connect4_board import render_connect4_board

if TYPE_CHECKING:
    from core.bleed import Bleed
    from core.discord.ctx import Context

INACTIVITY_SECONDS = 180
START_TIMEOUT_SECONDS = 30
RPS_EMOJI = {"rock": "🪨", "paper": "📄", "scissors": "✂️"}
RPS_BEATS = {"rock": "scissors", "paper": "rock", "scissors": "paper"}
ZWSP = "\u200b"
BOT_NAME = "vain"
BOT_OPPONENT = "Me"


def _is_bot_opponent(user: discord.User, bot: Bleed) -> bool:
    return user.bot and user.id == bot.user.id


def _opponent_label(user: discord.User, bot: Bleed) -> str:
    return BOT_OPPONENT if _is_bot_opponent(user, bot) else user.display_name


def _bot_win_status() -> str:
    return f"**{BOT_OPPONENT}** wins!"


def _bot_thinking_line(*, emoji: str) -> str:
    return f"{emoji} **{BOT_NAME}** is thinking..."


async def _warn_interaction(ctx: "Context", interaction: discord.Interaction, message: str) -> None:
    emoji = await ctx._get_emoji("warn")
    color_value = await ctx._get_color("warn")
    embed = discord.Embed(
        color=color_value,
        description=f"{emoji} {interaction.user.mention}: {message}",
    )
    await interaction.response.send_message(embed=embed, ephemeral=True)


async def _resolve_user(
    ctx: "Context",
    user: discord.User | discord.Member | int,
) -> discord.User:
    if isinstance(user, discord.User):
        return user
    return await ctx.bot.fetch_user(int(user))


async def _validate_opponent(ctx: "Context", opponent: discord.User) -> str | None:
    if opponent.id == ctx.author.id:
        return "You can't play against yourself."
    if opponent.bot and opponent.id != ctx.bot.user.id:
        return "You can't play against a bot."

    # slash member pickers already scope to the current conversation
    if ctx.interaction is not None and ctx.guild is None:
        return None

    channel = ctx.channel
    if isinstance(channel, discord.DMChannel):
        if channel.recipient is None or opponent.id != channel.recipient.id:
            return "That member isn't in this conversation."
    elif isinstance(channel, discord.GroupChannel):
        allowed = {user.id for user in channel.recipients}
        allowed.add(ctx.author.id)
        if opponent.id not in allowed:
            return "That member isn't in this group."
    elif ctx.guild is not None:
        if ctx.guild.get_member(opponent.id) is None:
            try:
                await ctx.guild.fetch_member(opponent.id)
            except discord.HTTPException:
                return "That member isn't in this server."
    return None


def _rps_winner(a: str, b: str) -> int:
    if a == b:
        return 0
    if RPS_BEATS[a] == b:
        return 1
    return 2


async def _end_game(message: discord.Message | None, text: str) -> None:
    if message is None:
        return
    with contextlib.suppress(discord.HTTPException, discord.Forbidden):
        if message.embeds:
            embed = message.embeds[0].copy()
            embed.description = text
            embed.set_footer(text="Game ended")
            await message.edit(embed=embed, view=None)
        else:
            await message.edit(content=text, view=None)


class RPSView(discord.ui.View):
    def __init__(
        self,
        *,
        ctx: "Context",
        player1: discord.User,
        player2: discord.User,
        rounds: int,
        bot: Bleed,
    ) -> None:
        super().__init__(timeout=INACTIVITY_SECONDS)
        self.ctx = ctx
        self.player1 = player1
        self.player2 = player2
        self.rounds = max(1, min(3, rounds))
        self.bot = bot
        self.choices: dict[int, str] = {}
        self.scores = {player1.id: 0, player2.id: 0}
        self.current_round = 1
        self.message: discord.Message | None = None
        self.finished = False

    @property
    def _vs_bot(self) -> bool:
        return _is_bot_opponent(self.player2, self.bot)

    def _p2_display(self) -> str:
        return _opponent_label(self.player2, self.bot)

    def _waiting_text(self) -> str:
        p1_done = self.player1.id in self.choices
        p2_done = self.player2.id in self.choices
        p2 = f"**{self._p2_display()}**" if self._vs_bot else self.player2.mention
        if not p1_done and not p2_done:
            return f"Waiting for {self.player1.mention} and {p2} to make their choice"
        if not p1_done:
            return f"Waiting for {self.player1.mention}"
        if not p2_done:
            return f"Waiting for {p2}"
        return "Revealing choices..."

    def _embed(self) -> discord.Embed:
        if self.finished:
            p1s = self.scores[self.player1.id]
            p2s = self.scores[self.player2.id]
            if p1s > p2s:
                winner = self.player1.mention
            elif p2s > p1s:
                winner = _bot_win_status() if self._vs_bot else self.player2.mention
            else:
                winner = "Nobody"
            p2_score = f"**{self._p2_display()}**" if self._vs_bot else self.player2.mention
            desc = (
                f"**Final score**\n"
                f"{self.player1.mention}: **{p1s}** — **{p2s}** :{p2_score}\n"
                f"**Winner:** {winner}"
            )
        else:
            desc = self._waiting_text()
            if self.current_round > 1:
                desc = f"**Round {self.current_round}/{self.rounds}**\n{desc}"
        embed = discord.Embed(title="Rock Paper Scissors", description=desc, color=color.base)
        if not self.finished:
            embed.set_footer(text=f"Round {self.current_round} of {self.rounds}")
        return embed

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id not in (self.player1.id, self.player2.id):
            await _warn_interaction(self.ctx, interaction, "You are not in this game.")
            return False
        if interaction.user.id in self.choices:
            await _warn_interaction(self.ctx, interaction, "You already picked.")
            return False
        return True

    @discord.ui.button(label="Rock", style=discord.ButtonStyle.secondary, custom_id="rps:rock")
    async def rock(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        await self._pick(interaction, "rock")

    @discord.ui.button(label="Paper", style=discord.ButtonStyle.secondary, custom_id="rps:paper")
    async def paper(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        await self._pick(interaction, "paper")

    @discord.ui.button(label="Scissors", style=discord.ButtonStyle.secondary, custom_id="rps:scissors")
    async def scissors(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        await self._pick(interaction, "scissors")

    async def _pick(self, interaction: discord.Interaction, choice: str) -> None:
        self.choices[interaction.user.id] = choice
        if self.player2.bot and interaction.user.id == self.player1.id:
            counter = {"rock": "paper", "paper": "scissors", "scissors": "rock"}
            self.choices[self.player2.id] = counter[choice]
        await interaction.response.defer()
        if len(self.choices) < 2:
            if self.message:
                await self.message.edit(embed=self._embed(), view=self)
            return
        await self._resolve_round()

    async def _resolve_round(self) -> None:
        c1 = self.choices[self.player1.id]
        c2 = self.choices[self.player2.id]
        result = _rps_winner(c1, c2)
        if result == 1:
            self.scores[self.player1.id] += 1
        elif result == 2:
            self.scores[self.player2.id] += 1

        round_text = (
            f"{RPS_EMOJI[c1]} {self.player1.display_name}: **{c1.title()}**\n"
            f"{RPS_EMOJI[c2]} {self._p2_display()}: **{c2.title()}**\n"
        )
        if result == 0:
            round_text += "**Round tie!**"
        elif result == 1:
            round_text += f"**{self.player1.display_name}** wins the round!"
        elif self._vs_bot:
            round_text += "**I** win the round!"
        else:
            round_text += f"**{self.player2.display_name}** wins the round!"

        self.choices.clear()
        needed = (self.rounds // 2) + 1
        if self.scores[self.player1.id] >= needed or self.scores[self.player2.id] >= needed or self.current_round >= self.rounds:
            self.finished = True
            self.stop()
            for child in self.children:
                child.disabled = True
            embed = self._embed()
            embed.description = round_text + "\n\n" + (embed.description or "")
        else:
            self.current_round += 1
            embed = discord.Embed(
                title="Rock Paper Scissors",
                description=round_text + f"\n\n**Round {self.current_round}/{self.rounds}**\n{self._waiting_text()}",
                color=color.base,
            )
            embed.set_footer(text=f"Round {self.current_round} of {self.rounds}")

        if self.message:
            await self.message.edit(embed=embed, view=None if self.finished else self)

    async def on_timeout(self) -> None:
        if self.finished:
            return
        self.stop()
        for child in self.children:
            child.disabled = True
        p2 = f"**{self._p2_display()}**" if self._vs_bot else self.player2.mention
        await _end_game(
            self.message,
            f"Rock paper scissors between {self.player1.mention} and {p2} ended due to inactivity.",
        )


class TicTacToeButton(discord.ui.Button["TicTacToeView"]):
    def __init__(self, x: int, y: int) -> None:
        super().__init__(style=discord.ButtonStyle.secondary, label=ZWSP, row=y, custom_id=f"ttt:{x}:{y}")
        self.x = x
        self.y = y

    def refresh(self, board: list[list[str]]) -> None:
        cell = board[self.y][self.x]
        if cell == "X":
            self.label = "X"
            self.style = discord.ButtonStyle.danger
            self.disabled = True
        elif cell == "O":
            self.label = "O"
            self.style = discord.ButtonStyle.success
            self.disabled = True
        else:
            self.label = ZWSP
            self.style = discord.ButtonStyle.secondary
            self.disabled = False

    async def callback(self, interaction: discord.Interaction) -> None:
        view = self.view
        if view is None or not isinstance(view, TicTacToeView):
            return
        if not await view.interaction_check(interaction):
            return
        await view.handle_click(interaction, self.x, self.y)


class TicTacToeView(discord.ui.View):
    def __init__(
        self,
        *,
        ctx: "Context",
        player_x: discord.User,
        player_o: discord.User | None,
        vs_me: bool,
        bot: Bleed,
    ) -> None:
        super().__init__(timeout=INACTIVITY_SECONDS)
        self.ctx = ctx
        self.player_x = player_x
        self.player_o = player_o
        self.vs_me = vs_me
        self.bot = bot
        self.board = [["", "", ""] for _ in range(3)]
        self.turn = "X"
        self.message: discord.Message | None = None
        self.finished = False
        self._started = False
        self._start_timer: asyncio.Task | None = asyncio.create_task(self._start_timeout())
        for y in range(3):
            for x in range(3):
                self.add_item(TicTacToeButton(x, y))

    def _player_o_name(self) -> str:
        if self.vs_me:
            return BOT_OPPONENT
        return self.player_o.display_name if self.player_o else "opponent"

    def _header(self) -> str:
        return f"**{self.player_x.display_name}** vs **{self._player_o_name()}**"

    def _turn_emoji(self) -> str:
        return "❌" if self.turn == "X" else "⭕"

    def _current_player(self) -> discord.User | None:
        if self.turn == "X":
            return self.player_x
        return None if self.vs_me else self.player_o

    def _content(self, *, status: str = "", starting: bool = False) -> str:
        lines = [self._header(), ""]
        if status:
            lines.append(status)
        elif starting:
            lines.append(f"⏰ You have **{START_TIMEOUT_SECONDS} seconds** to start!")
            lines.append(f"❌ {self.player_x.mention}, make your first move.")
        elif not self.finished:
            current = self._current_player()
            if current:
                lines.append(f"{self._turn_emoji()} {current.mention}, your turn.")
            elif self.vs_me and self.turn == "O":
                lines.append(_bot_thinking_line(emoji="⭕"))
        return "\n".join(lines)

    def _check_winner(self) -> str | None:
        lines = self.board + [
            [self.board[i][j] for i in range(3)] for j in range(3)
        ] + [
            [self.board[i][i] for i in range(3)],
            [self.board[i][2 - i] for i in range(3)],
        ]
        for line in lines:
            if line[0] and line.count(line[0]) == 3:
                return line[0]
        if all(cell for row in self.board for cell in row):
            return "tie"
        return None

    async def _record_stats(self, winner: str) -> None:
        import logging

        from ext.fun.ttt_stats import record_ttt_game, scope_ids

        log = logging.getLogger("bleed.ttt")
        channel = self.message.channel if self.message else self.ctx.channel
        guild = getattr(channel, "guild", None) or self.ctx.guild
        guild_id, channel_id = scope_ids(channel, guild)
        player_o_id = self.bot.user.id if self.vs_me else (self.player_o.id if self.player_o else None)
        try:
            await record_ttt_game(
                self.bot,
                guild_id=guild_id,
                channel_id=channel_id,
                player_x_id=self.player_x.id,
                player_o_id=player_o_id,
                vs_me=self.vs_me,
                winner=winner,
            )
        except Exception:
            log.exception(
                "failed to record ttt stats (guild=%s channel=%s winner=%s)",
                guild_id,
                channel_id,
                winner,
            )

    def _sync_buttons(self) -> None:
        for child in self.children:
            if isinstance(child, TicTacToeButton):
                child.refresh(self.board)

    def _cancel_start_timer(self) -> None:
        if self._start_timer and not self._start_timer.done():
            self._start_timer.cancel()
        self._start_timer = None

    async def _start_timeout(self) -> None:
        try:
            await asyncio.sleep(START_TIMEOUT_SECONDS)
        except asyncio.CancelledError:
            return
        if self._started or self.finished:
            return
        self.finished = True
        self.stop()
        for child in self.children:
            child.disabled = True
        await _end_game(
            self.message,
            f"{self._header()}\n\nGame cancelled — no move in {START_TIMEOUT_SECONDS} seconds.",
        )

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if self.finished:
            await _warn_interaction(self.ctx, interaction, "This game is over.")
            return False
        if self.vs_me:
            if self.turn == "X" and interaction.user.id != self.player_x.id:
                await _warn_interaction(self.ctx, interaction, "It's not your turn.")
                return False
        else:
            current = self._current_player()
            if current is None or interaction.user.id != current.id:
                await _warn_interaction(self.ctx, interaction, "It's not your turn.")
                return False
        return True

    async def handle_click(self, interaction: discord.Interaction, x: int, y: int) -> None:
        if self.board[y][x]:
            await _warn_interaction(self.ctx, interaction, "That cell is taken.")
            return

        if not self._started:
            self._started = True
            self._cancel_start_timer()

        self.board[y][x] = self.turn
        winner = self._check_winner()
        if winner:
            self.finished = True
            self._cancel_start_timer()
            self.stop()
            await self._record_stats(winner)
            if winner == "tie":
                status = "It's a **tie**!"
            elif winner == "X":
                status = f"**{self.player_x.mention}** wins!"
            else:
                if self.vs_me:
                    status = _bot_win_status()
                else:
                    status = f"**{self.player_o.mention}** wins!"
            self._sync_buttons()
            for child in self.children:
                child.disabled = True
            await interaction.response.edit_message(content=self._content(status=status), view=self)
            return

        self.turn = "O" if self.turn == "X" else "X"
        self._sync_buttons()

        if self.vs_me and self.turn == "O":
            await interaction.response.edit_message(content=self._content(), view=self)
            await self._me_move()
            winner = self._check_winner()
            if winner:
                self.finished = True
                self.stop()
                await self._record_stats(winner)
                if winner == "tie":
                    status = "It's a **tie**!"
                elif winner == "O":
                    status = _bot_win_status() if self.vs_me else f"**{self.player_o.mention}** wins!"
                else:
                    status = f"**{self.player_x.mention}** wins!"
                for child in self.children:
                    child.disabled = True
                if self.message:
                    await self.message.edit(content=self._content(status=status), view=self)
                return
            self.turn = "X"
            self._sync_buttons()
            if self.message:
                await self.message.edit(content=self._content(), view=self)
            return

        await interaction.response.edit_message(content=self._content(), view=self)

    async def _me_move(self) -> None:
        empty = [(x, y) for y in range(3) for x in range(3) if not self.board[y][x]]
        if not empty:
            return
        best_score = float("-inf")
        best: tuple[int, int] | None = None
        for x, y in empty:
            self.board[y][x] = "O"
            score = self._minimax(False, 0)
            self.board[y][x] = ""
            if score > best_score:
                best_score = score
                best = (x, y)
        if best is None:
            x, y = random.choice(empty)
        else:
            x, y = best
        self.board[y][x] = "O"
        self._sync_buttons()

    def _minimax(self, is_max: bool, depth: int) -> int:
        winner = self._check_winner()
        if winner == "O":
            return 10 - depth
        if winner == "X":
            return depth - 10
        if winner == "tie":
            return 0
        empty = [(x, y) for y in range(3) for x in range(3) if not self.board[y][x]]
        if is_max:
            best = float("-inf")
            for x, y in empty:
                self.board[y][x] = "O"
                best = max(best, self._minimax(False, depth + 1))
                self.board[y][x] = ""
            return best
        best = float("inf")
        for x, y in empty:
            self.board[y][x] = "X"
            best = min(best, self._minimax(True, depth + 1))
            self.board[y][x] = ""
        return best

    async def on_timeout(self) -> None:
        if self.finished:
            return
        self._cancel_start_timer()
        self.stop()
        for child in self.children:
            child.disabled = True
        await _end_game(
            self.message,
            f"{self._header()}\n\nGame ended due to inactivity.",
        )


class Connect4Button(discord.ui.Button["Connect4View"]):
    def __init__(self, column: int) -> None:
        super().__init__(
            style=discord.ButtonStyle.secondary,
            label=str(column + 1),
            row=column // 3,
            custom_id=f"c4:{column}",
        )
        self.column = column

    async def callback(self, interaction: discord.Interaction) -> None:
        view = self.view
        if view is None or not isinstance(view, Connect4View):
            return
        if not await view.interaction_check(interaction):
            return
        await view.play_column(interaction, self.column)


class Connect4View(discord.ui.View):
    ROWS = 6
    COLS = 7

    def __init__(
        self,
        *,
        ctx: "Context",
        player1: discord.User,
        player2: discord.User,
        bot: Bleed,
        vs_me: bool = False,
    ) -> None:
        super().__init__(timeout=INACTIVITY_SECONDS)
        self.ctx = ctx
        self.player1 = player1
        self.player2 = player2
        self.bot = bot
        self.vs_me = vs_me
        self.board = [[0] * self.COLS for _ in range(self.ROWS)]
        self.turn = 1
        self.message: discord.Message | None = None
        self.finished = False
        self._last_move: tuple[int, int] | None = None
        for col in range(self.COLS):
            self.add_item(Connect4Button(col))

    def _current_player(self) -> discord.User:
        return self.player1 if self.turn == 1 else self.player2

    def _embed(self, *, status: str = "") -> discord.Embed:
        p2_name = BOT_OPPONENT if self.vs_me else self.player2.display_name
        embed = discord.Embed(
            title="Connect Four",
            description=f"**{self.player1.display_name}** vs **{p2_name}**",
            color=color.base,
        )
        if status:
            embed.add_field(name="Result", value=status, inline=False)
        elif not self.finished:
            if self.vs_me and self.turn == 2:
                embed.add_field(name="Turn", value=_bot_thinking_line(emoji="🟡"), inline=False)
            else:
                marker = "🔴" if self.turn == 1 else "🟡"
                embed.add_field(
                    name="Turn",
                    value=f"{marker} {self._current_player().mention}, pick a column.",
                    inline=False,
                )
        embed.set_image(url="attachment://connect4.jpg")
        return embed

    def _attachment(self) -> discord.File:
        buf = render_connect4_board(self.board, last_move=self._last_move)
        return discord.File(buf, filename="connect4.jpg")

    async def _edit_board(
        self,
        interaction: discord.Interaction | None,
        *,
        status: str = "",
    ) -> None:
        embed = self._embed(status=status)
        file = self._attachment()
        view = None if self.finished else self
        if interaction is not None and interaction.response.is_done():
            if self.message:
                await self.message.edit(embed=embed, attachments=[file], view=view)
        elif interaction is not None:
            await interaction.response.edit_message(embed=embed, attachments=[file], view=view)
        elif self.message:
            await self.message.edit(embed=embed, attachments=[file], view=view)

    def _drop(self, column: int, player: int) -> int | None:
        for row in range(self.ROWS - 1, -1, -1):
            if self.board[row][column] == 0:
                self.board[row][column] = player
                return row
        return None

    def _check_win(self, row: int, col: int, player: int) -> bool:
        directions = [(0, 1), (1, 0), (1, 1), (1, -1)]
        for dr, dc in directions:
            count = 1
            for sign in (1, -1):
                r, c = row + dr * sign, col + dc * sign
                while 0 <= r < self.ROWS and 0 <= c < self.COLS and self.board[r][c] == player:
                    count += 1
                    r += dr * sign
                    c += dc * sign
            if count >= 4:
                return True
        return False

    def _board_full(self) -> bool:
        return all(self.board[0][c] != 0 for c in range(self.COLS))

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if self.finished:
            await _warn_interaction(self.ctx, interaction, "This game is over.")
            return False
        if self.vs_me:
            if interaction.user.id != self.player1.id:
                await _warn_interaction(self.ctx, interaction, "You are not in this game.")
                return False
            if self.turn != 1:
                await _warn_interaction(self.ctx, interaction, f"Wait for **{BOT_NAME}**.")
                return False
            return True
        if interaction.user.id not in (self.player1.id, self.player2.id):
            await _warn_interaction(self.ctx, interaction, "You are not in this game.")
            return False
        if interaction.user.id != self._current_player().id:
            await _warn_interaction(self.ctx, interaction, "It's not your turn.")
            return False
        return True

    def _valid_columns(self) -> list[int]:
        return [c for c in range(self.COLS) if self.board[0][c] == 0]

    def _win_at(self, row: int, col: int, player: int) -> bool:
        directions = [(0, 1), (1, 0), (1, 1), (1, -1)]
        for dr, dc in directions:
            count = 1
            for sign in (1, -1):
                r, c = row + dr * sign, col + dc * sign
                while 0 <= r < self.ROWS and 0 <= c < self.COLS and self.board[r][c] == player:
                    count += 1
                    r += dr * sign
                    c += dc * sign
            if count >= 4:
                return True
        return False

    def _me_column(self) -> int:
        valid = self._valid_columns()
        if not valid:
            return 0
        for col in valid:
            row = self._drop(col, 2)
            if row is not None and self._win_at(row, col, 2):
                self.board[row][col] = 0
                return col
            if row is not None:
                self.board[row][col] = 0
        for col in valid:
            row = self._drop(col, 1)
            if row is not None and self._win_at(row, col, 1):
                self.board[row][col] = 0
                return col
            if row is not None:
                self.board[row][col] = 0
        for col in (3, 2, 4, 1, 5, 0, 6):
            if col in valid:
                return col
        return valid[0]

    async def _after_move(self, interaction: discord.Interaction, *, status: str = "") -> None:
        if status:
            self.finished = True
            self.stop()
            for child in self.children:
                child.disabled = True
            await self._edit_board(interaction, status=status)
            return
        if self._board_full():
            self.finished = True
            self.stop()
            for child in self.children:
                child.disabled = True
            await self._edit_board(interaction, status="It's a **tie**!")
            return
        self.turn = 2 if self.turn == 1 else 1
        if self.vs_me and self.turn == 2 and not self.finished:
            await self._edit_board(interaction)
            col = self._me_column()
            row = self._drop(col, 2)
            if row is None:
                return
            self._last_move = (row, col)
            if self._win_at(row, col, 2):
                self.finished = True
                self.stop()
                for child in self.children:
                    child.disabled = True
                await self._edit_board(None, status=_bot_win_status())
                return
            if self._board_full():
                self.finished = True
                self.stop()
                for child in self.children:
                    child.disabled = True
                await self._edit_board(None, status="It's a **tie**!")
                return
            self.turn = 1
            await self._edit_board(None)
            return
        await self._edit_board(interaction)

    async def play_column(self, interaction: discord.Interaction, column: int) -> None:
        row = self._drop(column, self.turn)
        if row is None:
            await _warn_interaction(self.ctx, interaction, "That column is full.")
            return

        self._last_move = (row, column)
        player = self._current_player()
        if self._check_win(row, column, self.turn):
            winner = _bot_win_status() if self.vs_me and self.turn == 2 else f"{player.mention} wins!"
            await self._after_move(interaction, status=winner)
            return

        await self._after_move(interaction)

    async def on_timeout(self) -> None:
        if self.finished:
            return
        self.stop()
        for child in self.children:
            child.disabled = True
        p2 = BOT_OPPONENT if self.vs_me else self.player2.display_name
        await _end_game(
            self.message,
            f"**{self.player1.display_name}** vs **{p2}**\n\nGame ended due to inactivity.",
        )


async def start_rps(
    ctx: "Context",
    *,
    opponent: discord.User | None,
    rounds: int = 1,
    vs_me: bool = False,
) -> None:
    if vs_me or opponent is None:
        opponent = ctx.bot.user
        vs_me = True
    else:
        opponent = await _resolve_user(ctx, opponent)
        if err := await _validate_opponent(ctx, opponent):
            return await ctx.warn(err)

    view = RPSView(ctx=ctx, player1=ctx.author, player2=opponent, rounds=rounds, bot=ctx.bot)
    msg = await ctx.send(embed=view._embed(), view=view)
    view.message = msg


async def start_ttt(
    ctx: "Context",
    *,
    opponent: Optional[discord.User],
    vs_me: bool,
) -> None:
    if vs_me or opponent is None:
        vs_me = True
        opponent = None
    else:
        opponent = await _resolve_user(ctx, opponent)
        if err := await _validate_opponent(ctx, opponent):
            return await ctx.warn(err)

    view = TicTacToeView(
        ctx=ctx,
        player_x=ctx.author,
        player_o=opponent if not vs_me else None,
        vs_me=vs_me,
        bot=ctx.bot,
    )
    msg = await ctx.send(content=view._content(starting=True), view=view)
    view.message = msg


async def start_connect4(
    ctx: "Context",
    *,
    opponent: discord.User | None,
    vs_me: bool = False,
) -> None:
    if vs_me or opponent is None:
        vs_me = True
        opponent = ctx.bot.user
    else:
        opponent = await _resolve_user(ctx, opponent)
        if err := await _validate_opponent(ctx, opponent):
            return await ctx.warn(err)

    view = Connect4View(
        ctx=ctx,
        player1=ctx.author,
        player2=opponent,
        bot=ctx.bot,
        vs_me=vs_me,
    )
    msg = await ctx.send(embed=view._embed(), file=view._attachment(), view=view)
    view.message = msg
