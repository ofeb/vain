"""member converter with smart name matching.

Tries id / mention / username, then smart display-name matching
(``own`` → decorative nicks, partials, etc.).
"""

from __future__ import annotations

import re

import discord
from discord.ext.commands import CommandError, Context, Converter

from .regex import clean_query, regex_find

_MENTION_RE = re.compile(r"<@!?(\d{15,22})>")
_ID_RE = re.compile(r"^\d{15,22}$")


def _member_names(member: discord.Member) -> list[str | None]:
    names: list[str | None] = [
        member.name,
        member.display_name,
        getattr(member, "global_name", None),
        getattr(member, "nick", None),
    ]
    
    if getattr(member, "discriminator", None) and member.discriminator != "0":
        names.append(f"{member.name}#{member.discriminator}")
    return names


class MemberConvert(Converter):
    """convert string to guild Member"""

    async def convert(self, ctx: Context, arg: str) -> discord.Member:
        if ctx.guild is None:
            raise CommandError("this command can only be used in a server")
        if isinstance(arg, discord.Member):
            return arg
        if isinstance(arg, discord.User):
            member = ctx.guild.get_member(arg.id)
            if member is not None:
                return member
            try:
                return await ctx.guild.fetch_member(arg.id)
            except discord.HTTPException as exc:
                raise CommandError(f"**can't** find member **{arg}**") from exc

        raw = clean_query(str(arg))
        text = str(arg).strip()

        
        user_id: int | None = None
        m = _MENTION_RE.search(text)
        if m:
            user_id = int(m.group(1))
        elif _ID_RE.match(raw):
            user_id = int(raw)
        else:
            stripped = text.strip("<@!>")
            if _ID_RE.match(stripped):
                user_id = int(stripped)

        if user_id is not None:
            member = ctx.guild.get_member(user_id)
            if member is not None:
                return member
            try:
                return await ctx.guild.fetch_member(user_id)
            except discord.HTTPException:
                pass

        
        member = regex_find(
            raw or text,
            ctx.guild.members,
            names_of=_member_names,
            fuzzy=True,
        )
        if member is not None:
            return member

        raise CommandError(f"**can't** find member **{arg}**")
