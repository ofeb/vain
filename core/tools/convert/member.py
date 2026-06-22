"""member converter with fuzzy name matching.
tries id mention username then fuzzy display name.
raises CommandError if no match found"""

from __future__ import annotations

from typing import Annotated

from discord.ext.commands import Converter, CommandError, Context
from fast_string_match import closest_match
import discord


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
            except discord.HTTPException:
                raise CommandError(f"cant find member **{arg}**")
        try:
            user_id = int(str(arg).strip("<@!>"))
            member = ctx.guild.get_member(user_id)
            if member is not None:
                return member
            try:
                return await ctx.guild.fetch_member(user_id)
            except discord.HTTPException:
                pass
        except (ValueError, TypeError):
            pass
        arg_low = str(arg).lower()
        for m in ctx.guild.members:
            if m.name.lower() == arg_low or m.display_name.lower() == arg_low:
                return m
        names = [m.display_name for m in ctx.guild.members]
        if match := closest_match(arg_low, names):
            return discord.utils.get(ctx.guild.members, display_name=match)
        raise CommandError(f"cant find member **{arg}**")


class OptionalMember(Converter):
    """optional member/user in guilds, group chats, and dms (prefix commands only)"""

    _EMPTY = frozenset({"", "0", "none", "me", "bot"})

    @staticmethod
    def _channel_users(ctx: Context) -> list[discord.User]:
        channel = ctx.channel
        if isinstance(channel, discord.GroupChannel):
            return [
                recipient
                for recipient in channel.recipients
                if recipient.id != ctx.author.id and not recipient.bot
            ]
        if isinstance(channel, discord.DMChannel) and channel.recipient:
            if channel.recipient.bot or channel.recipient.id == ctx.author.id:
                return []
            return [channel.recipient]
        return []

    @classmethod
    def _resolve_user(cls, ctx: Context, arg: str) -> discord.User | None:
        candidates = cls._channel_users(ctx)
        if not candidates:
            return None
        arg_low = arg.lower()
        for user in candidates:
            if user.name.lower() == arg_low or user.display_name.lower() == arg_low:
                return user
        names = [user.display_name for user in candidates]
        if match := closest_match(arg_low, names):
            return discord.utils.get(candidates, display_name=match)
        return None

    async def convert(
        self,
        ctx: Context,
        arg: str | discord.Member | discord.User | None,
    ) -> discord.Member | discord.User | None:
        if arg is None:
            return None
        if isinstance(arg, (discord.Member, discord.User)):
            if isinstance(arg, discord.Member):
                return arg
            if ctx.guild is not None:
                member = ctx.guild.get_member(arg.id)
                if member is not None:
                    return member
                try:
                    return await ctx.guild.fetch_member(arg.id)
                except discord.HTTPException:
                    raise CommandError(f"cant find member **{arg}**")
            return arg
        cleaned = str(arg).strip()
        if cleaned.lower() in self._EMPTY:
            return None
        try:
            user_id = int(cleaned.strip("<@!>"))
            if ctx.guild is not None:
                member = ctx.guild.get_member(user_id)
                if member is not None:
                    return member
                try:
                    return await ctx.guild.fetch_member(user_id)
                except discord.HTTPException:
                    pass
            return await ctx.bot.fetch_user(user_id)
        except (ValueError, TypeError):
            pass
        if ctx.guild is not None:
            return await MemberConvert().convert(ctx, cleaned)
        if user := self._resolve_user(ctx, cleaned):
            return user
        raise CommandError(f"cant find member **{arg}**")


# Slash: inner User type → Discord's native member picker (avatars, status, mentions).
# Prefix: OptionalMember converter for text/mentions/fuzzy names.
OptionalMemberParam = Annotated[discord.User | None, OptionalMember()]
