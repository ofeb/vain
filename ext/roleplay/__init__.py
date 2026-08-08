from __future__ import annotations

import contextlib
from io import BytesIO
from typing import TYPE_CHECKING, Optional

import discord
from discord import app_commands
from discord.ext import commands
from colorthief import ColorThief

from core.discord.package import Package
from core.discord.ctx import Context
from core.discord.hybrid import hybrid, describe, command
from core.tools.human.text import ordinal

from .proper.media import fetch_action_gif

from core.discord.views.embed import reply_embed

if TYPE_CHECKING:
    from core.vain import Vain

def _extract_dominant_color(gif_bytes: bytes) -> int | None:
    try:
        ct = ColorThief(BytesIO(gif_bytes))
        r, g, b = ct.get_color(quality=1)
        return (r << 16) | (g << 8) | b
    except Exception:
        return None

ACTION_MAP = {
    "hug": "**hugs** {}",
    "kiss": "**kisses** {}",
    "pat": "**pats** {}",
    "poke": "**pokes** {}",
    "slap": "**slaps** {}",
    "bite": "**bites** {}",
    "kick": "**kicks** {}",
    "punch": "**punches** {}",
    "headpat": "**headpats** {}",
    "tickle": "**tickles** {}",
    "highfive": "**highfives** {}",
    "shrug": "**shrugs** {}",
    "wave": "**waves** {}",
    "blush": "**blushes** {}",
    "cry": "**cries** {}",
    "laugh": "**laughs** {}",
    "airkiss": "**air kisses** {}",
    "angrystare": "**angrily stares at** {}",
    "bleh": "**blehs at** {}",
    "brofist": "**brofists** {}",
    "celebrate": "**celebrates with** {}",
    "cheers": "**stares angrily at** {}",
    "clap": "**claps for** {}",
    "confused": "**is confused at** {}",
    "cool": "**is cooling with** {}",
    "cuddle": "**cuddles with** {}",
    "dance": "**dances with** {}",
    "drool": "**drools at** {}",
    "evillaugh": "**laughs evilly at** {}",
    "facepalm": "**face palmes** {}",
    "handhold": "**holds hands with** {}",
    "happy": "**is happy with** {}",
    "headbang": "**bangs their head at** {}",
    "huh": "**missed what** {} **said**",
    "lick": "**licks** {}",
    "love": "**gives love and affection to** {}",
    "mad": "**is mad at** {}",
    "nervous": "**gets nervous around** {}",
    "no": "**says no to** {}",
    "nom": "**nibbles** {}",
    "nosebleed": "**nosebleeds at** {}",
    "nuzzle": "**nuzzles** {}",
    "nyah": "**nyahhh's** {}",
    "peek": "**peeks** {}",
    "pinch": "**pinches** {}",
    "pout": "**pouts at** {}",
    "roll": "**has a temper tantrum because of** {}",
    "run": "**runs to** {}",
    "sad": "**is sad because of** {}",
    "scared": "**is scared of** {}",
    "shout": "**shouts at** {}",
    "shy": "**gets shy around** {}",
    "sigh": "**sighs at** {}",
    "sip": "**sips** {}",
    "sleep": "**sleeps with** {}",
    "slowclap": "**slowly claps at** {}",
    "smack": "**smacks** {}",
    "smile": "**smiles at** {}",
    "smug": "**smugs at** {}",
    "sneeze": "**sneezes on** {}",
    "sorry": "**is sorry to** {}",
    "stare": "**stares at** {}",
    "surprised": "**is surprised by** {}",
    "sweat": "**sweats around** {}",
    "thumbsup": "**gives a thumbs up to** {}",
    "tired": "**gets tired around** {}",
    "wink": "**winks at** {}",
    "woah": "**gasps at** {}",
    "yawn": "**yawns at** {}",
    "yay": "**gets excited around** {}",
    "yes": "**says yes to** {}",
}

ROLEPLAY_ACTIONS: tuple[str, ...] = tuple(ACTION_MAP.keys())
PREFIX_ACTION_SKIP: frozenset[str] = frozenset({"kick", "roll"})

BACK_ACTIONS: frozenset[str] = frozenset(ACTION_MAP.keys())

PAST_TENSE: dict[str, str] = {
    "hug": "Hugged",
    "kiss": "Kissed",
    "pat": "Patted",
    "poke": "Poked",
    "slap": "Slapped",
    "bite": "Bit",
    "kick": "Kicked",
    "punch": "Punched",
    "headpat": "Headpatted",
    "tickle": "Tickled",
    "highfive": "Highfived",
    "shrug": "Shrugged",
    "wave": "Waved",
    "blush": "Blushed",
    "cry": "Cried",
    "laugh": "Laughed",
    "airkiss": "Air kissed",
    "angrystare": "Angrily stared at",
    "bleh": "Bleh'd at",
    "brofist": "Brofisted",
    "celebrate": "Celebrated with",
    "cheers": "Stared angrily at",
    "clap": "Clapped for",
    "confused": "Was confused at",
    "cool": "Cooled with",
    "cuddle": "Cuddled with",
    "dance": "Danced with",
    "drool": "Drooled at",
    "evillaugh": "Laughed evilly at",
    "facepalm": "Face palmed",
    "handhold": "Held hands with",
    "happy": "Was happy with",
    "headbang": "Banged their head at",
    "huh": "Missed what",
    "lick": "Licked",
    "love": "Gave love to",
    "mad": "Was mad at",
    "nervous": "Got nervous around",
    "no": "Said no to",
    "nom": "Nibbled",
    "nosebleed": "Nosebleeded at",
    "nuzzle": "Nuzzled",
    "nyah": "Nyahhh'd",
    "peek": "Peeked",
    "pinch": "Pinched",
    "pout": "Pouted at",
    "roll": "Had a tantrum at",
    "run": "Ran to",
    "sad": "Was sad because of",
    "scared": "Was scared of",
    "shout": "Shouted at",
    "shy": "Got shy around",
    "sigh": "Sighed at",
    "sip": "Sipped",
    "sleep": "Slept with",
    "slowclap": "Slowly clapped at",
    "smack": "Smacked",
    "smile": "Smiled at",
    "smug": "Smugged at",
    "sneeze": "Sneezed on",
    "sorry": "Was sorry to",
    "stare": "Stared at",
    "surprised": "Was surprised by",
    "sweat": "Sweated around",
    "thumbsup": "Gave a thumbs up to",
    "tired": "Got tired around",
    "wink": "Winked at",
    "woah": "Gasped at",
    "yawn": "Yawned at",
    "yay": "Got excited around",
    "yes": "Said yes to",
}

class RoleplayBackView(discord.ui.View):
    def __init__(self, action: str, original_author_id: int, target_id: int):
        super().__init__(timeout=300)
        self.action = action
        self.original_author_id = original_author_id
        self.target_id = target_id

        btn = discord.ui.Button(
            label=f"{action.title()} back",
            style=discord.ButtonStyle.secondary,
        )
        btn.callback = self._back_callback
        self.add_item(btn)

    async def _back_callback(self, interaction: discord.Interaction):
        import traceback as _tb

        if interaction.user.id != self.target_id:
            return await interaction.warning(
                f"Only <@{self.target_id}> can use this button!"
            )

        for item in self.children:
            item.disabled = True
            item.label = f"{PAST_TENSE.get(self.action, self.action.title())} back"
        await interaction.response.edit_message(view=self)

        try:
            gif_bytes = await fetch_action_gif(self.action)
            attachment = discord.File(BytesIO(gif_bytes), filename="action.gif")

            bot = interaction.client
            target_user = await bot.fetch_user(self.original_author_id)
            mention = target_user.mention

            total = await bot.db.fetchval(
                """
                INSERT INTO roleplay.actions (action, giver, receiver, amount)
                    VALUES ($1, $2, $3, 1)
                ON CONFLICT (action, giver, receiver)
                    DO UPDATE SET amount = roleplay.actions.amount + 1
                RETURNING amount
                """,
                self.action,
                interaction.user.id,
                self.original_author_id,
                cached=False,
            )

            embed_color = _extract_dominant_color(gif_bytes) or bot.color
            embed = reply_embed(
                color=embed_color,
                message=(
                    f"{interaction.user.mention} {ACTION_MAP[self.action].format(mention)} "
                    f"for the **{ordinal(total)}** time!"
                ),
            )
            embed.color = embed_color
            embed.set_image(url="attachment://action.gif")

            
            await interaction.followup.send(file=attachment, embed=embed)
        except Exception as exc:
            tb_text = "".join(_tb.format_exception(type(exc), exc, exc.__traceback__))
            with contextlib.suppress(discord.HTTPException):
                await interaction.warning(
                    f"```\n{tb_text[:1800]}\n```"
                )

    async def on_timeout(self):
        for item in self.children:
            item.disabled = True
        if self.message:
            with contextlib.suppress(discord.HTTPException):
                await self.message.edit(view=self)

class RoleplayCommands(Package):
    """Themed member-to-member reaction commands."""

    async def _record(self, action: str, giver_id: int, receiver_id: int) -> int:
        return await self.db.fetchval(
            """
            INSERT INTO roleplay.actions (action, giver, receiver, amount)
                VALUES ($1, $2, $3, 1)
            ON CONFLICT (action, giver, receiver)
                DO UPDATE SET amount = roleplay.actions.amount + 1
            RETURNING amount
            """,
            action,
            giver_id,
            receiver_id,
            cached=False,
        )

    async def _perform_action(
        self,
        ctx: Context,
        action: str,
        member: discord.User | None = None,
    ) -> discord.Message:
        action = action.lower().strip()
        if action not in ACTION_MAP:
            raise commands.CommandError(
                f"Unknown roleplay action `{action}`. "
                f"Use one of: {', '.join(f'`{name}`' for name in list(ROLEPLAY_ACTIONS)[:12])}..."
            )

        target = member or ctx.author
        try:
            gif_bytes = await fetch_action_gif(action)
        except Exception as exc:
            raise commands.CommandError(
                f"Could not fetch a GIF for **{action}** right now. Try again later."
            ) from exc
        attachment = discord.File(BytesIO(gif_bytes), filename="action.gif")

        total = await self._record(action, ctx.author.id, target.id)
        mention = target.mention if target != ctx.author else "themselves"

        embed_color = _extract_dominant_color(gif_bytes) or self.bot.color
        embed = reply_embed(
            color=embed_color,
            message=(
                f"{ctx.author.mention} {ACTION_MAP[action].format(mention)} "
                f"for the **{ordinal(total)}** time!"
            ),
        )
        embed.color = embed_color
        embed.set_image(url="attachment://action.gif")

        view = None
        if action in BACK_ACTIONS and target != ctx.author:
            view = RoleplayBackView(action, ctx.author.id, target.id)

        
        msg = await ctx.send(
            file=attachment,
            embed=embed,
            view=view,
            raw_embed=True,
        )
        if view is not None:
            view.message = msg
        return msg

    @hybrid(
        name="roleplay",
        description="roleplay with another user",
        example=",roleplay punch @user",
        guilds=True,
        dms=True,
        groupchats=True,
    )
    @describe(
        action="Roleplay action to use",
        member="Member to roleplay with",
    )
    async def roleplay(
        self,
        ctx: Context,
        action: str,
        member: Optional[discord.User] = None,
    ) -> discord.Message:
        return await self._perform_action(ctx, action, member)

    @roleplay.autocomplete("action")
    async def roleplay_action_autocomplete(
        self,
        interaction: discord.Interaction,
        current: str,
    ) -> list[app_commands.Choice[str]]:
        needle = (current or "").lower()
        matches = [
            name
            for name in ROLEPLAY_ACTIONS
            if needle in name
        ][:25]
        return [app_commands.Choice(name=name, value=name) for name in matches]

def _make_prefix_action(name: str):
    """Prefix-only roleplay action (,slap / ,highfive). Slash uses /roleplay only."""

    @command(
        name=name,
        description=f"Roleplay: {name}",
        example=f",{name} @user",
    )
    async def action(self, ctx: Context, member: Optional[discord.User] = None):
        return await self._perform_action(ctx, name, member)

    action.__name__ = name
    action.__qualname__ = f"RoleplayCommands.{name}"

    return action

for _name in ROLEPLAY_ACTIONS:
    if _name in PREFIX_ACTION_SKIP:
        continue
    setattr(RoleplayCommands, _name, _make_prefix_action(_name))

from core.discord.mixin import _Meta
from core.discord.package import Package

from .events import RoleplayEvents

class Roleplay(
    RoleplayCommands,
    RoleplayEvents,
    Package,
    metaclass=_Meta,
):
    def __init__(self, bot):
        Package.__init__(self, bot)

async def setup(bot: Vain) -> None:
    await bot.add_cog(Roleplay(bot))

