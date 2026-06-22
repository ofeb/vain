from __future__ import annotations

import random
from typing import TYPE_CHECKING, Optional

import discord

from core.managers.values import color

if TYPE_CHECKING:
    from core.bleed import Bleed
    from core.discord.ctx import Context

INACTIVITY_SECONDS = 180
RPS_EMOJI = {"rock": "🪨", "paper": "📄", "scissors": "✂️"}
RPS_BEATS = {"rock": "scissors", "paper": "rock", "scissors": "paper"}


def _rps_winner(a: str, b: str) -> int:
    if a == b:
        return 0
    if RPS_BEATS[a] == b:
        return 1
    return 2


async def _inactive_warning(ctx: "Context", label: str, message: discord.Message | None = None) -> None:
    target = message or ctx.message
    with discord.utils.suppress(discord.HTTPException):
        if target:
            await target.delete()
    await ctx.warn(label, delete_after=180)


class RPSView(discord.ui.View):
    def __init__(
        self,
        *,
        player1: discord.User,
        player2: discord.User,
        rounds: int,
        bot: Bleed,
    ) -> None:
        super().__init__(timeout=INACTIVITY_SECONDS)
        self.player1 = player1
        self.player2 = player2
        self.rounds = max(1, min(3, rounds))
        self.bot = bot
        self.choices: dict[int, str] = {}
        self.scores = {player1.id: 0, player2.id: 0}
        self.current_round = 1
        self.message: discord.Message | None = None
        self.finished = False

    def _waiting_text(self) -> str:
        p1_done = self.player1.id in self.choices
        p2_done = self.player2.id in self.choices
        if not p1_done and not p2_done:
            return f"Waiting for {self.player1.mention} and {self.player2.mention} to make their choice"
        if not p1_done:
            return f"Waiting for {self.player1.mention}"
        if not p2_done:
            return f"Waiting for {self.player2.mention}"
        return "Revealing choices..."

    def _embed(self) -> discord.Embed:
        if self.finished:
            p1s = self.scores[self.player1.id]
            p2s = self.scores[self.player2.id]
            if p1s > p2s:
                winner = self.player1.mention
            elif p2s > p1s:
                winner = self.player2.mention
            else:
                winner = "Nobody"
            desc = (
                f"**Final score**\n"
                f"{self.player1.mention}: **{p1s}** — **{p2s}** :{self.player2.mention}\n"
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
            await interaction.response.send_message("You are not in this game.", ephemeral=True)
            return False
        if interaction.user.id in self.choices:
            await interaction.response.send_message("You already picked.", ephemeral=True)
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
            f"{RPS_EMOJI[c2]} {self.player2.display_name}: **{c2.title()}**\n"
        )
        if result == 0:
            round_text += "**Round tie!**"
        elif result == 1:
            round_text += f"**{self.player1.display_name}** wins the round!"
        else:
            round_text += f"**{self.player2.display_name}** wins the round!"

        self.choices.clear()
        needed = (self.rounds // 2) + 1
        if self.scores[self.player1.id] >= needed or self.scores[self.player2.id] >= needed or self.current_round >= self.rounds:
            self.finished = True
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
        for child in self.children:
            child.disabled = True
        if self.message:
            with discord.utils.suppress(discord.HTTPException):
                await self.message.delete()


class TicTacToeButton(discord.ui.Button["TicTacToeView"]):
    def __init__(self, x: int, y: int) -> None:
        super().__init__(style=discord.ButtonStyle.secondary, label="\u200b", row=y, custom_id=f"ttt:{x}:{y}")
        self.x = x
        self.y = y

    def refresh(self, board: list[list[str]]) -> None:
        cell = board[self.y][self.x]
        if cell == "X":
            self.label = "❌"
            self.disabled = True
        elif cell == "O":
            self.label = "⭕"
            self.disabled = True
        else:
            self.label = "\u200b"
            self.disabled = False

    async def callback(self) -> None:
        view = self.view
        if view is None or not isinstance(view, TicTacToeView):
            return
        if not await view.interaction_check(self.interaction):
            return
        await view.handle_click(self.interaction, self.x, self.y)


class TicTacToeView(discord.ui.View):
    def __init__(
        self,
        *,
        ctx: "Context",
        player_x: discord.User,
        player_o: discord.User | None,
        vs_ai: bool,
        bot: Bleed,
    ) -> None:
        super().__init__(timeout=INACTIVITY_SECONDS)
        self.ctx = ctx
        self.player_x = player_x
        self.player_o = player_o
        self.vs_ai = vs_ai
        self.bot = bot
        self.board = [["", "", ""] for _ in range(3)]
        self.turn = "X"
        self.message: discord.Message | None = None
        self.finished = False
        for y in range(3):
            for x in range(3):
                self.add_item(TicTacToeButton(x, y))

    def _opponent_label(self) -> str:
        if self.vs_ai:
            return "**AI**"
        return self.player_o.mention if self.player_o else "opponent"

    def _current_player(self) -> discord.User | None:
        if self.turn == "X":
            return self.player_x
        return None if self.vs_ai else self.player_o

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

    def _embed(self, status: str = "") -> discord.Embed:
        desc = f"**{self.player_x.mention}** (❌) vs {self._opponent_label()} (⭕)"
        if status:
            desc += f"\n\n{status}"
        elif not self.finished:
            current = self._current_player()
            if current:
                desc += f"\n\n{current.mention}, your turn"
            elif self.vs_ai:
                desc += "\n\n**AI** is thinking..."
        return discord.Embed(title="Tic-Tac-Toe", description=desc, color=color.base)

    def _sync_buttons(self) -> None:
        for child in self.children:
            if isinstance(child, TicTacToeButton):
                child.refresh(self.board)

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if self.finished:
            await interaction.response.send_message("This game is over.", ephemeral=True)
            return False
        if self.vs_ai:
            if self.turn == "X" and interaction.user.id != self.player_x.id:
                await interaction.response.send_message("It's not your turn.", ephemeral=True)
                return False
        else:
            current = self._current_player()
            if current is None or interaction.user.id != current.id:
                await interaction.response.send_message("It's not your turn.", ephemeral=True)
                return False
        return True

    async def handle_click(self, interaction: discord.Interaction, x: int, y: int) -> None:
        if self.board[y][x]:
            await interaction.response.send_message("That cell is taken.", ephemeral=True)
            return
        self.board[y][x] = self.turn
        winner = self._check_winner()
        if winner:
            self.finished = True
            if winner == "tie":
                status = "It's a **tie**!"
            elif winner == "X":
                status = f"**{self.player_x.mention}** wins!"
            else:
                status = f"**{self._opponent_label()}** wins!"
            self._sync_buttons()
            for child in self.children:
                child.disabled = True
            await interaction.response.edit_message(embed=self._embed(status), view=self)
            return

        self.turn = "O" if self.turn == "X" else "X"
        self._sync_buttons()

        if self.vs_ai and self.turn == "O":
            await interaction.response.defer()
            await self._ai_move()
            winner = self._check_winner()
            if winner:
                self.finished = True
                if winner == "tie":
                    status = "It's a **tie**!"
                elif winner == "O":
                    status = "**AI** wins!"
                else:
                    status = f"**{self.player_x.mention}** wins!"
                for child in self.children:
                    child.disabled = True
                if self.message:
                    await self.message.edit(embed=self._embed(status), view=self)
                return
            self.turn = "X"
            self._sync_buttons()
            if self.message:
                await self.message.edit(embed=self._embed(), view=self)
            return

        await interaction.response.edit_message(embed=self._embed(), view=self)

    async def _ai_move(self) -> None:
        empty = [(x, y) for y in range(3) for x in range(3) if not self.board[y][x]]
        if not empty:
            return
        for mark in ("O", "X"):
            for x, y in empty:
                self.board[y][x] = mark
                if self._check_winner() == mark:
                    self.board[y][x] = ""
                    if mark == "O":
                        self.board[y][x] = "O"
                        return
                self.board[y][x] = ""
        if (1, 1) in empty:
            self.board[1][1] = "O"
            return
        x, y = random.choice(empty)
        self.board[y][x] = "O"

    async def on_timeout(self) -> None:
        for child in self.children:
            child.disabled = True
        p2 = self._opponent_label()
        await _inactive_warning(
            self.ctx,
            f"Stopped the tic-tac-toe game between {self.player_x.mention} and {p2} due to inactivity.",
            self.message,
        )


class Connect4Button(discord.ui.Button["Connect4View"]):
    def __init__(self, column: int) -> None:
        super().__init__(
            style=discord.ButtonStyle.primary,
            label=str(column + 1),
            row=0,
            custom_id=f"c4:{column}",
        )
        self.column = column

    async def callback(self) -> None:
        view = self.view
        if view is None or not isinstance(view, Connect4View):
            return
        if not await view.interaction_check(self.interaction):
            return
        await view.play_column(self.interaction, self.column)


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
    ) -> None:
        super().__init__(timeout=INACTIVITY_SECONDS)
        self.ctx = ctx
        self.player1 = player1
        self.player2 = player2
        self.bot = bot
        self.board = [[0] * self.COLS for _ in range(self.ROWS)]
        self.turn = 1
        self.message: discord.Message | None = None
        self.finished = False
        for col in range(self.COLS):
            self.add_item(Connect4Button(col))

    def _piece(self, cell: int) -> str:
        if cell == 1:
            return "🔴"
        if cell == 2:
            return "🟡"
        return "⬛"

    def _board_text(self) -> str:
        lines = []
        for row in self.board:
            lines.append("".join(self._piece(c) for c in row))
        lines.append("".join("⬜" for _ in range(self.COLS)))
        return "\n".join(lines)

    def _current_player(self) -> discord.User:
        return self.player1 if self.turn == 1 else self.player2

    def _embed(self, status: str = "") -> discord.Embed:
        desc = (
            f"{self.player1.mention} 🔴 vs {self.player2.mention} 🟡\n\n"
            f"{self._board_text()}"
        )
        if status:
            desc += f"\n\n{status}"
        elif not self.finished:
            desc += f"\n\n{self._current_player().mention}, your turn"
        return discord.Embed(title="Connect Four", description=desc, color=color.base)

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
            await interaction.response.send_message("This game is over.", ephemeral=True)
            return False
        if interaction.user.id not in (self.player1.id, self.player2.id):
            await interaction.response.send_message("You are not in this game.", ephemeral=True)
            return False
        if interaction.user.id != self._current_player().id:
            await interaction.response.send_message("It's not your turn.", ephemeral=True)
            return False
        return True

    async def play_column(self, interaction: discord.Interaction, column: int) -> None:
        row = self._drop(column, self.turn)
        if row is None:
            await interaction.response.send_message("That column is full.", ephemeral=True)
            return

        player = self._current_player()
        if self._check_win(row, column, self.turn):
            self.finished = True
            for child in self.children:
                child.disabled = True
            await interaction.response.edit_message(
                embed=self._embed(f"**{player.mention}** wins!"),
                view=self,
            )
            return

        if self._board_full():
            self.finished = True
            for child in self.children:
                child.disabled = True
            await interaction.response.edit_message(embed=self._embed("It's a **tie**!"), view=self)
            return

        self.turn = 2 if self.turn == 1 else 1
        await interaction.response.edit_message(embed=self._embed(), view=self)

    async def on_timeout(self) -> None:
        for child in self.children:
            child.disabled = True
        await _inactive_warning(
            self.ctx,
            f"Stopped the connect four game between {self.player1.mention} and {self.player2.mention} due to inactivity.",
            self.message,
        )


async def start_rps(ctx: "Context", *, opponent: discord.Member, rounds: int = 1) -> None:
    if opponent.bot:
        return await ctx.fail("You can't play against a bot.")
    if opponent.id == ctx.author.id:
        return await ctx.fail("You can't play against yourself.")

    view = RPSView(player1=ctx.author, player2=opponent, rounds=rounds, bot=ctx.bot)
    msg = await ctx.send(embed=view._embed(), view=view)
    view.message = msg


async def start_ttt(
    ctx: "Context",
    *,
    opponent: Optional[discord.Member],
    vs_ai: bool,
) -> None:
    if not vs_ai:
        if opponent is None:
            return await ctx.fail("Mention an opponent or play against the AI.")
        if opponent.bot:
            return await ctx.fail("You can't play against a bot.")
        if opponent.id == ctx.author.id:
            return await ctx.fail("You can't play against yourself.")

    view = TicTacToeView(
        ctx=ctx,
        player_x=ctx.author,
        player_o=opponent if not vs_ai else None,
        vs_ai=vs_ai,
        bot=ctx.bot,
    )
    msg = await ctx.send(embed=view._embed(f"{ctx.author.mention}, your turn"), view=view)
    view.message = msg


async def start_connect4(ctx: "Context", *, opponent: discord.Member) -> None:
    if opponent.bot:
        return await ctx.fail("You can't play against a bot.")
    if opponent.id == ctx.author.id:
        return await ctx.fail("You can't play against yourself.")

    view = Connect4View(ctx=ctx, player1=ctx.author, player2=opponent, bot=ctx.bot)
    msg = await ctx.send(embed=view._embed(f"{ctx.author.mention}, your turn"), view=view)
    view.message = msg
