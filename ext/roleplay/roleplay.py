from __future__ import annotations

import contextlib
import uuid
from io import BytesIO
from typing import TYPE_CHECKING, Optional

import discord
from discord import app_commands
from discord.ext import commands
from PIL import Image

from core.discord.package import Package
from core.discord.ctx import Context
from core.discord.hybrid import hybrid, describe, command
from core.tools.human.text import ordinal

from .media import fetch_action_gif

if TYPE_CHECKING:
    from core.vain import Vain


def _extract_dominant_color(gif_bytes: bytes) -> int | None:
    try:
        with Image.open(BytesIO(gif_bytes)) as img:
            img = img.convert("RGB").resize((1, 1))
            r, g, b = img.getpixel((0, 0))
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
    "happy": "**is happy with**",
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

BACK_ACTIONS: frozenset[str] = frozenset({
    "punch", "slap", "kick", "pat", "hug", "kiss",
    "bite", "poke", "smack", "pinch",
})

PAST_TENSE: dict[str, str] = {
    "punch": "Punched",
    "slap": "Slapped",
    "kick": "Kicked",
    "pat": "Patted",
    "hug": "Hugged",
    "kiss": "Kissed",
    "bite": "Bit",
    "poke": "Poked",
    "smack": "Smacked",
    "pinch": "Pinched",
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
        if interaction.user.id != self.target_id:
            return await interaction.response.send_message(
                "Only the target can use this button!", ephemeral=True
            )

        for item in self.children:
            item.disabled = True
            item.label = f"{PAST_TENSE.get(self.action, self.action.title())} back"
        await interaction.response.edit_message(view=self)

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
        embed = discord.Embed(
            color=embed_color,
            description=(
                f"{interaction.user.mention} {ACTION_MAP[self.action].format(mention)} "
                f"for the **{ordinal(total)}** time!"
            ),
        )
        embed.set_image(url="attachment://action.gif")

        await interaction.followup.send(
            file=attachment, embed=embed,
            reference=interaction.message,
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
        gif_bytes = await fetch_action_gif(action)
        attachment = discord.File(BytesIO(gif_bytes), filename="action.gif")

        total = await self._record(action, ctx.author.id, target.id)
        mention = target.mention if target != ctx.author else "themselves"

        embed_color = _extract_dominant_color(gif_bytes) or self.bot.color
        embed = discord.Embed(
            color=embed_color,
            description=(
                f"{ctx.author.mention} {ACTION_MAP[action].format(mention)} "
                f"for the **{ordinal(total)}** time!"
            ),
        )
        embed.set_image(url="attachment://action.gif")

        view = None
        if action in BACK_ACTIONS and target != ctx.author:
            view = RoleplayBackView(action, ctx.author.id, target.id)

        return await ctx.send(file=attachment, embed=embed, view=view)

    @hybrid(
        name="roleplay",
        description="Perform a roleplay action with another member",
        example=",roleplay punch @user",
        guilds=True,
        dms=True,
        groupchats=True,
    )
    @describe(
        action="Roleplay action (punch, hug, kiss, etc.)",
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
    async def action(self, ctx: Context, *, member: Optional[discord.User] = None):
        return await self._perform_action(ctx, name, member)

    action.__name__ = name
    action.__qualname__ = f"RoleplayCommands.{name}"

    return command(
        name=name,
        description=f"Roleplay: {name}",
        example=f",{name} @user",
    )(action)


for _name in ROLEPLAY_ACTIONS:
    if _name in PREFIX_ACTION_SKIP:
        continue
    setattr(RoleplayCommands, _name, _make_prefix_action(_name))


async def setup(bot: Vain):
    await bot.add_cog(RoleplayCommands(bot))
