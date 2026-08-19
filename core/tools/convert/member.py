"""member / user converter with smart name matching.

Tries id / mention first (never name-match a snowflake), then smart
username / display-name / nick matching via regex token scoring
(``own`` → decorative nicks, partials, etc.).

Fuzzy closest-match is disabled for members - it was resolving
``nafim0509`` to unrelated users.
"""

from __future__ import annotations

import re
from typing import Sequence

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


def _user_names(user: discord.User | discord.abc.User) -> list[str | None]:
    names: list[str | None] = [
        getattr(user, "name", None),
        getattr(user, "display_name", None),
        getattr(user, "global_name", None),
    ]
    disc = getattr(user, "discriminator", None)
    if disc and disc != "0" and getattr(user, "name", None):
        names.append(f"{user.name}#{disc}")
    return names


def _extract_user_id(text: str) -> int | None:
    raw = clean_query(text)
    m = _MENTION_RE.search(str(text or ""))
    if m:
        return int(m.group(1))
    if _ID_RE.match(raw):
        return int(raw)
    stripped = str(text or "").strip("<@!>")
    if _ID_RE.match(stripped):
        return int(stripped)
    return None


def _user_label(user: discord.abc.User) -> str:
    return f"{user} (`{user.id}`)"


async def resolve_member(ctx: Context, arg: str) -> discord.Member:
    """Resolve *arg* to a guild Member. Raises CommandError on failure."""
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

    text = str(arg).strip()
    raw = clean_query(text)
    user_id = _extract_user_id(text)

    if user_id is not None:
        member = ctx.guild.get_member(user_id)
        if member is not None:
            return member
        try:
            return await ctx.guild.fetch_member(user_id)
        except discord.HTTPException:
            pass
        raise CommandError(f"**can't** find member **{arg}**")

    member = regex_find(
        raw or text,
        ctx.guild.members,
        names_of=_member_names,
        fuzzy=False,
    )
    if member is not None:
        return member

    raise CommandError(f"**can't** find member **{arg}**")


async def resolve_user(
    ctx: Context,
    arg: str,
    *,
    extra_users: Sequence[discord.User | discord.abc.User] | None = None,
) -> tuple[int, str]:
    """Resolve *arg* to ``(user_id, display_label)``.

    Order:
      1. Mention / raw snowflake → force that ID (guild member, else fetch_user)
      2. Guild members via regex name scoring (username, display_name, nick, global_name)
      3. *extra_users* (e.g. users who previously had notes) via same scoring
      4. Bot user cache via same scoring

    Never fuzzy-matches a snowflake to a different person.
    """
    if isinstance(arg, (discord.Member, discord.User)):
        label = str(arg)
        if ctx.guild:
            member = ctx.guild.get_member(arg.id)
            if member is not None:
                label = str(member)
        return arg.id, label

    text = str(arg or "").strip()
    if not text:
        raise CommandError("provide a user mention, id, or name")

    raw = clean_query(text)
    user_id = _extract_user_id(text)

    if user_id is not None:
        if ctx.guild:
            member = ctx.guild.get_member(user_id)
            if member is not None:
                return member.id, str(member)
            try:
                member = await ctx.guild.fetch_member(user_id)
                return member.id, str(member)
            except (discord.NotFound, discord.HTTPException):
                pass

        bot = getattr(ctx, "bot", None) or getattr(ctx, "_bot", None)
        if bot is not None:
            cached = bot.get_user(user_id)
            if cached is not None:
                return cached.id, _user_label(cached)
            try:
                user = await bot.fetch_user(user_id)
                return user.id, _user_label(user)
            except (discord.NotFound, discord.HTTPException):
                pass
        return user_id, f"<@{user_id}>"

    if ctx.guild:
        member = regex_find(
            raw or text,
            ctx.guild.members,
            names_of=_member_names,
            fuzzy=False,
        )
        if member is not None:
            return member.id, str(member)

    if extra_users:
        hit = regex_find(
            raw or text,
            list(extra_users),
            names_of=_user_names,
            fuzzy=False,
        )
        if hit is not None:
            return hit.id, _user_label(hit)

    bot = getattr(ctx, "bot", None) or getattr(ctx, "_bot", None)
    if bot is not None and getattr(bot, "users", None):
        hit = regex_find(
            raw or text,
            list(bot.users),
            names_of=_user_names,
            fuzzy=False,
        )
        if hit is not None:
            label = str(hit)
            if ctx.guild:
                member = ctx.guild.get_member(hit.id)
                if member is not None:
                    label = str(member)
            return hit.id, label

    raise CommandError(f"**can't** find user **{arg}**")


class MemberConvert(Converter):
    """convert string to guild Member"""

    async def convert(self, ctx: Context, arg: str) -> discord.Member:
        return await resolve_member(ctx, arg)


class UserConvert(Converter):
    """convert string to User (works offline via ID; name match uses guild + cache)"""

    async def convert(self, ctx: Context, arg: str) -> discord.User:
        uid, _label = await resolve_user(ctx, arg)
        bot = ctx.bot
        user = bot.get_user(uid)
        if user is not None:
            return user
        try:
            return await bot.fetch_user(uid)
        except (discord.NotFound, discord.HTTPException) as exc:
            raise CommandError(f"**can't** find user **{arg}**") from exc
