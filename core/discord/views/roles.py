"""role assignment select menu view.
shows a dropdown of roles users can self assign.
use RoleSelectView with a list of roles"""

import discord
from discord.ext.commands import Context
from typing import List

from core.managers.values import color, emojis




def compose(*parts: str) -> str:
    return "\n".join(part for part in parts if part)

def body(*lines: str) -> str:
    return "\n".join(f"> {line}" for line in lines if line)

def caption(text: str) -> str:
    return f"-# {text}"

def aesthetic_embed(
    *,
    color: int,
    message: str,
    title: str | None = None,
    footer: str | None = None,
    author: str | None = None,
    timestamp: bool = True,
) -> discord.Embed:
    description = compose(
        body(message),
        caption(footer) if footer else None,
    )
    embed = discord.Embed(color=color, description=description)
    if title:
        embed.title = title
    if author:
        embed.set_author(name=author)
    if timestamp:
        embed.timestamp = discord.utils.utcnow()
    return embed

def reply_embed(
    *,
    color: int,
    message: str,
    subtitle: str | None = None,
) -> discord.Embed:
    return aesthetic_embed(color=color, message=message, footer=subtitle, timestamp=False)



class RoleSelectView(discord.ui.View):
    """dropdown select menu for self roles"""

    def __init__(self, ctx: Context, roles: List[discord.Role], placeholder: str = "pick a role"):
        super().__init__(timeout=60.0)
        self.ctx = ctx
        options = [discord.SelectOption(label=r.name, value=str(r.id)) for r in roles[:25]]
        self.select = discord.ui.Select(placeholder=placeholder, options=options, min_values=0, max_values=len(options))
        self.select.callback = self._callback
        self.add_item(self.select)

    async def interaction_check(self, inter: discord.Interaction) -> bool:
        if inter.user.id != self.ctx.author.id:
            await inter.response.send_message(
                embed=reply_embed(
                    color=color.warn,
                    message=(
                        f"{emojis.warn} {inter.user.mention}: "
                        f"Only {self.ctx.author.mention} can use this!"
                    ),
                ),
                ephemeral=True,
            )
            return False
        return True

    async def _callback(self, inter: discord.Interaction):
        selected_ids = {int(v) for v in self.select.values}
        member = inter.guild.get_member(inter.user.id)
        added, removed = [], []
        for r in inter.guild.roles:
            if str(r.id) in [o.value for o in self.select.options]:
                if r.id in selected_ids and r not in member.roles:
                    await member.add_roles(r, reason="self role")
                    added.append(r.name)
                elif r.id not in selected_ids and r in member.roles:
                    await member.remove_roles(r, reason="self role")
                    removed.append(r.name)
        parts = []
        if added:
            parts.append("added: " + ", ".join(added))
        if removed:
            parts.append("removed: " + ", ".join(removed))
        await inter.response.send_message(", ".join(parts) or "no changes", ephemeral=True)
