from __future__ import annotations

from io import BytesIO
from typing import TYPE_CHECKING, Optional

import discord
from discord import app_commands
from discord.ext import commands

from core.discord.package import Package
from core.discord.ctx import Context
from core.discord.autocomplete import guild_member_choices
from core.discord.hybrid import hybrid, describe, command
from core.tools.human.text import ordinal

from .media import fetch_action_gif

if TYPE_CHECKING:
    from core.bleed import Bleed


def toggled(status: bool) -> str:
    return "enabled" if status else "disabled"


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
    "tickle": "**tickle** {}",
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
PREFIX_ACTION_SKIP: frozenset[str] = frozenset({"kick"})


class RoleplayCommands(Package):
    @hybrid(
        name="roleplay",
        description="Perform a roleplay action with another member",
    )
    @describe(
        action="Roleplay action (punch, hug, kiss, etc.)",
        member="Member to roleplay with",
    )
    async def roleplay(
        self,
        ctx,
        action: str,
        member: Optional[discord.User] = None,
    ):
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

    async def _perform_action(
        self,
        ctx: Context,
        action: str,
        member: discord.User | None = None,
    ):
        action = action.lower().strip()
        if action not in ACTION_MAP:
            raise commands.CommandError(
                f"Unknown roleplay action `{action}`. "
                f"Use one of: {', '.join(f'`{name}`' for name in list(ROLEPLAY_ACTIONS)[:12])}..."
            )

        target = member or ctx.author
        gif_bytes = await fetch_action_gif(action)
        attachment = discord.File(BytesIO(gif_bytes), filename="action.gif")

        if ctx.guild is not None:
            total = await self.db.fetchval(
                """
                INSERT INTO roleplay.actions (action, giver, receiver, amount)
                    VALUES ($1, $2, $3, 1)
                ON CONFLICT (action, giver, receiver)
                    DO UPDATE SET amount = roleplay.actions.amount + 1
                RETURNING amount
                """,
                action,
                ctx.author.id,
                target.id,
            )
        else:
            total = 1
        mention = target.mention if target != ctx.author else "themselves"

        embed = discord.Embed(
            color=self.bot.color,
            description=(
                f"{ctx.author.mention} {ACTION_MAP[action].format(mention)} "
                f"for the **{ordinal(total)}** time!"
            ),
        )
        embed.set_image(url="attachment://action.gif")
        return await ctx.send(file=attachment, embed=embed)


def _make_prefix_action(name: str):
    @hybrid(name=name)
    @describe(member="Member to roleplay with")
    async def action(self, ctx, member: Optional[discord.User] = None):
        return await self._perform_action(ctx, name, member)

    @action.autocomplete("member")
    async def member_autocomplete(self, interaction: discord.Interaction, current: str):
        return await guild_member_choices(interaction, current)

    action.__name__ = name
    action.__qualname__ = f"RoleplayCommands.{name}"
    member_autocomplete.__name__ = f"{name}_member_autocomplete"
    member_autocomplete.__qualname__ = f"RoleplayCommands.{name}_member_autocomplete"
    return action


for _name in ROLEPLAY_ACTIONS:
    if _name in PREFIX_ACTION_SKIP:
        continue
    setattr(RoleplayCommands, _name, _make_prefix_action(_name))


async def setup(bot: Bleed):
    await bot.add_cog(RoleplayCommands(bot))
