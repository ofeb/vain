from __future__ import annotations

import contextlib
import re

import discord
from discord.ext import commands
from discord.ext.commands import CommandError, cooldown, group

from core.discord.package import Package
from core.tools.convert import MemberConvert, RoleConvert, StatusConvert

from core.managers.permissions import has_permissions

from core.discord.views.embed import compose, body, caption, c2
from .settings import Settings

DEFAULT_UPVOTE = "\u2705"
DEFAULT_DOWNVOTE = "\u274c"
SUGGEST_SEPARATOR = " • "
CUSTOM_EMOJI_RE = re.compile(r"^<a?:[A-Za-z0-9_~]{2,32}:[0-9]{15,25}>$")

def _status_label(status: str) -> str:
    labels = {
        "pending": "Pending",
        "pending_review": "Pending Review",
        "in_consideration": f"Pending{SUGGEST_SEPARATOR}In Consideration",
        "in_progress": "In Progress",
        "approved": "Approved",
        "denied": "Denied",
    }
    return labels.get(status, "Pending")

class SuggestCommands(Package):
    """suggestion management with public and review flows."""

    async def cog_load(self) -> None:
        await self._ensure_schema()

    async def _ensure_schema(self) -> None:
        if not self.db.pool:
            return
        await Settings.ensure_schema(self.bot)

    async def _get_settings(self, guild_id: int) -> dict:
        await self._ensure_schema()
        return await Settings.fetch_settings(self.bot, guild_id)

    async def _set_settings(self, guild_id: int, **fields) -> None:
        await Settings.set_settings(self.bot, guild_id, **fields)

    async def _next_suggestion_id(self, guild_id: int) -> int:
        await self._ensure_schema()
        return await Settings.next_suggestion_id(self.bot, guild_id)

    async def _insert_suggestion(
        self,
        guild_id: int,
        suggestion_id: int,
        author_id: int,
        content: str,
        status: str,
    ) -> None:
        await Settings.insert_suggestion(
            self.bot,
            guild_id,
            suggestion_id,
            author_id,
            content,
            status,
        )

    async def _get_suggestion(self, guild_id: int, suggestion_id: int):
        return await Settings.get_suggestion(self.bot, guild_id, suggestion_id)

    async def _get_suggestion_by_message(self, guild_id: int, message_id: int):
        return await Settings.get_suggestion_by_message(self.bot, guild_id, message_id)

    async def _set_suggestion_fields(self, guild_id: int, suggestion_id: int, **fields) -> None:
        await Settings.set_suggestion_fields(self.bot, guild_id, suggestion_id, **fields)

    async def _set_vote(self, guild_id: int, suggestion_id: int, user_id: int, vote: str) -> None:
        await Settings.set_vote(self.bot, guild_id, suggestion_id, user_id, vote)

    async def _remove_vote(self, guild_id: int, suggestion_id: int, user_id: int, vote: str) -> None:
        await Settings.remove_vote(self.bot, guild_id, suggestion_id, user_id, vote)

    async def _toggle_ignored_entry(
        self,
        guild_id: int,
        target_id: int,
        target_type: str,
        added_by: int,
    ) -> bool:
        return await Settings.toggle_ignored_entry(
            self.bot,
            guild_id,
            target_id,
            target_type,
            added_by,
        )

    async def _list_ignored_entries(self, guild_id: int):
        return await Settings.list_ignored_entries(self.bot, guild_id)

    async def _is_ignored(self, member: discord.Member) -> bool:
        role_ids = [role.id for role in member.roles if not role.is_default()]
        return await Settings.is_ignored(
            self.bot,
            member.guild.id,
            member.id,
            role_ids,
        )

    async def _resolve_channel(
        self,
        guild: discord.Guild,
        channel_id: int | None,
    ) -> discord.TextChannel | None:
        if not channel_id:
            return None

        channel = guild.get_channel(channel_id)
        if isinstance(channel, discord.TextChannel):
            return channel

        with contextlib.suppress(discord.HTTPException):
            fetched = await guild.fetch_channel(channel_id)
            if isinstance(fetched, discord.TextChannel):
                return fetched
        return None

    async def _resolve_message(
        self,
        guild: discord.Guild,
        channel_id: int | None,
        message_id: int | None,
    ) -> tuple[discord.TextChannel | None, discord.Message | None]:
        channel = await self._resolve_channel(guild, channel_id)
        if not channel or not message_id:
            return channel, None

        with contextlib.suppress(discord.HTTPException, discord.NotFound):
            return channel, await channel.fetch_message(message_id)
        return channel, None

    async def _resolve_member_or_role(self, ctx, raw: str):
        query = (raw or "").strip()
        if not query:
            return None

        with contextlib.suppress(CommandError):
            return await MemberConvert().convert(ctx, query)
        with contextlib.suppress(CommandError):
            return await RoleConvert().convert(ctx, query)
        return None

    async def _is_staff_member(self, guild: discord.Guild, member: discord.Member) -> bool:
        if member.id == guild.owner_id:
            return True
        if member.guild_permissions.manage_guild:
            return True

        staff_roles = set(await self.db.list_staff_roles(guild.id))
        return any(role.id in staff_roles for role in member.roles)

    async def _require_staff(self, ctx) -> bool:
        if await self._is_staff_member(ctx.guild, ctx.author):
            return True
        await ctx.warn("You're missing **staff permissions** for this command")
        return False

    def _normalize_emoji(self, guild: discord.Guild, value: str) -> tuple[str | None, str | None]:
        token = (value or "").strip()
        if not token:
            return None, "missing emoji"
        if " " in token:
            return None, "emoji values **can't** contain spaces"
        if CUSTOM_EMOJI_RE.match(token):
            emoji = discord.PartialEmoji.from_str(token)
            if not emoji.id:
                return None, "provide a **valid emoji**"
            if guild.get_emoji(emoji.id) is None:
                return None, "i **can't** use that custom emoji in this server"
            return str(emoji), None
        return token, None

    async def _resolve_author(
        self,
        guild: discord.Guild,
        user_id: int,
    ) -> tuple[str, str | None]:
        member = guild.get_member(user_id)
        if member:
            return member.display_name, member.display_avatar.url

        user = self.bot.get_user(user_id)
        if not user:
            with contextlib.suppress(discord.HTTPException):
                user = await self.bot.fetch_user(user_id)
        if user:
            return str(user), user.display_avatar.url
        return f"user {user_id}", None

    def _suggestion_footer(self, row) -> str:
        return (
            f"Suggestion ID: {row['suggestion_id']}"
            f"{SUGGEST_SEPARATOR}"
            f"{_status_label(str(row['status']))}"
        )

    def _message_jump_url(
        self,
        guild_id: int,
        channel_id: int | None,
        message_id: int | None,
    ) -> str | None:
        if not channel_id or not message_id:
            return None
        return f"https://discord.com/channels/{guild_id}/{channel_id}/{message_id}"

    async def _build_public_embed(self, guild: discord.Guild, row) -> discord.Embed:
        content = str(row["content"]).strip()
        embed = discord.Embed(
            color=self.color,
            description=compose(
                body(*content.splitlines()) if content else "",
                caption(self._suggestion_footer(row)),
            ),
            timestamp=discord.utils.utcnow(),
        )
        author_name, author_icon = await self._resolve_author(guild, int(row["author_id"]))
        if author_icon:
            embed.set_author(name=author_name, icon_url=author_icon)
        else:
            embed.set_author(name=author_name)
        return embed

    async def _build_review_embed(self, guild: discord.Guild, row) -> discord.Embed:
        embed = await self._build_public_embed(guild, row)
        member = guild.get_member(int(row["author_id"]))
        embed.add_field(
            name="Submitted By",
            value=body(member.mention if member else f"<@{row['author_id']}>"),
            inline=False,
        )
        public_link = self._message_jump_url(guild.id, row["channel_id"], row["message_id"])
        if public_link:
            embed.add_field(
                name="Public Message",
                value=body(f"[jump to message]({public_link})"),
                inline=False,
            )
        return embed

    def _thread_name(self, row) -> str:
        content = " ".join(str(row["content"]).split()).strip()
        if not content:
            return f"suggestion {row['suggestion_id']}"
        trimmed = content[:90].rstrip()
        if len(content) > 90:
            trimmed = f"{trimmed}..."
        return trimmed[:100] or f"suggestion {row['suggestion_id']}"

    async def _create_suggestion_thread(self, message: discord.Message, row) -> int | None:
        if not isinstance(message.channel, discord.TextChannel):
            return None

        me = message.guild.me if message.guild else None
        perms = message.channel.permissions_for(me) if me else None
        if not perms or not perms.create_public_threads:
            return None

        with contextlib.suppress(discord.HTTPException, discord.Forbidden):
            thread = await message.create_thread(
                name=self._thread_name(row),
                reason=f"suggestion {row['suggestion_id']} thread",
            )
            return thread.id
        return None

    async def _post_public_suggestion(
        self,
        guild: discord.Guild,
        row,
        settings: dict,
    ) -> tuple[int | None, int | None]:
        channel = await self._resolve_channel(guild, settings.get("channel_id"))
        if not channel:
            return None, None

        embed = await self._build_public_embed(guild, row)
        try:
            message = await channel.send(
                embed=embed,
                allowed_mentions=discord.AllowedMentions.none(),
            )
        except discord.HTTPException:
            return None, None

        upvote = settings.get("upvote_emoji") or DEFAULT_UPVOTE
        downvote = settings.get("downvote_emoji") or DEFAULT_DOWNVOTE
        with contextlib.suppress(discord.HTTPException):
            await message.add_reaction(upvote)
        with contextlib.suppress(discord.HTTPException):
            await message.add_reaction(downvote)

        thread_id = None
        if settings.get("threads_enabled"):
            thread_id = await self._create_suggestion_thread(message, row)
        return message.id, thread_id

    async def _post_review_suggestion(
        self,
        guild: discord.Guild,
        row,
        settings: dict,
    ) -> int | None:
        channel = await self._resolve_channel(guild, settings.get("review_channel_id"))
        if not channel:
            return None

        embed = await self._build_review_embed(guild, row)
        try:
            message = await channel.send(
                embed=embed,
                allowed_mentions=discord.AllowedMentions.none(),
            )
        except discord.HTTPException:
            return None
        return message.id

    async def _sync_public_message(self, guild: discord.Guild, row) -> None:
        channel, message = await self._resolve_message(guild, row["channel_id"], row["message_id"])
        if not channel or not message:
            await self._set_suggestion_fields(
                guild.id,
                int(row["suggestion_id"]),
                channel_id=None,
                message_id=None,
                thread_id=None,
            )
            return

        embed = await self._build_public_embed(guild, row)
        with contextlib.suppress(discord.HTTPException):
            await message.edit(
                embed=embed,
                allowed_mentions=discord.AllowedMentions.none(),
            )

    async def _sync_review_message(self, guild: discord.Guild, row) -> None:
        channel, message = await self._resolve_message(
            guild,
            row["review_channel_id"],
            row["review_message_id"],
        )
        if not channel or not message:
            await self._set_suggestion_fields(
                guild.id,
                int(row["suggestion_id"]),
                review_channel_id=None,
                review_message_id=None,
            )
            return

        embed = await self._build_review_embed(guild, row)
        with contextlib.suppress(discord.HTTPException):
            await message.edit(
                embed=embed,
                allowed_mentions=discord.AllowedMentions.none(),
            )

    async def _set_status(self, ctx, suggestion_id: int, status: str) -> None:
        if suggestion_id <= 0:
            await ctx.warn("suggestion id must be a positive number")
            return

        row = await self._get_suggestion(ctx.guild.id, suggestion_id)
        if not row:
            await ctx.warn("suggestion not found")
            return

        previous_status = str(row["status"])
        publish_on_approve = status == "approved" and not row["message_id"]
        if previous_status == status and not publish_on_approve:
            await ctx.warn(
                f"suggestion **#{suggestion_id}** is already marked as **{_status_label(status)}**"
            )
            return

        await self._set_suggestion_fields(ctx.guild.id, suggestion_id, status=status)
        row = await self._get_suggestion(ctx.guild.id, suggestion_id)
        settings = await self._get_settings(ctx.guild.id)

        if status == "approved" and row and not row["message_id"]:
            channel = await self._resolve_channel(ctx.guild, settings.get("channel_id"))
            if not channel:
                await self._set_suggestion_fields(ctx.guild.id, suggestion_id, status=previous_status)
                await ctx.warn("suggestions channel is not configured")
                return

            message_id, thread_id = await self._post_public_suggestion(ctx.guild, row, settings)
            if not message_id:
                await self._set_suggestion_fields(ctx.guild.id, suggestion_id, status=previous_status)
                await ctx.warn("i was unable to publish this suggestion")
                return

            await self._set_suggestion_fields(
                ctx.guild.id,
                suggestion_id,
                channel_id=channel.id,
                message_id=message_id,
                thread_id=thread_id,
            )
            row = await self._get_suggestion(ctx.guild.id, suggestion_id)

        if row and row["message_id"]:
            await self._sync_public_message(ctx.guild, row)
        if row and row["review_message_id"]:
            await self._sync_review_message(ctx.guild, row)

        public_link = self._message_jump_url(
            ctx.guild.id,
            int(row["channel_id"]) if row and row["channel_id"] else None,
            int(row["message_id"]) if row and row["message_id"] else None,
        )
        review_link = self._message_jump_url(
            ctx.guild.id,
            int(row["review_channel_id"]) if row and row["review_channel_id"] else None,
            int(row["review_message_id"]) if row and row["review_message_id"] else None,
        )

        lines = [
            f"updated suggestion **#{suggestion_id}** to **{_status_label(status)}**"
        ]
        if public_link:
            lines.append(f"public message: [open]({public_link})")
        if review_link:
            lines.append(f"review message: [open]({review_link})")
        await ctx.success("\n".join(lines))

    async def _send_staff_reply(self, guild: discord.Guild, row, comment: str) -> bool:
        thread_id = int(row["thread_id"]) if row["thread_id"] else None
        if thread_id:
            thread = guild.get_channel(thread_id)
            if thread is None:
                with contextlib.suppress(discord.HTTPException, discord.NotFound):
                    thread = await guild.fetch_channel(thread_id)
            if isinstance(thread, discord.Thread):
                with contextlib.suppress(discord.HTTPException):
                    await thread.send(comment, allowed_mentions=discord.AllowedMentions.none())
                    return True

        for channel_id, message_id in (
            (row["review_channel_id"], row["review_message_id"]),
            (row["channel_id"], row["message_id"]),
        ):
            channel, message = await self._resolve_message(guild, channel_id, message_id)
            if not channel or not message:
                continue
            with contextlib.suppress(discord.HTTPException):
                await message.reply(
                    comment,
                    mention_author=False,
                    allowed_mentions=discord.AllowedMentions.none(),
                )
                return True
        return False

    async def suggest_reaction_add(self, payload: discord.RawReactionActionEvent) -> None:
        if not payload.guild_id or not payload.user_id:
            return
        if self.bot.user and payload.user_id == self.bot.user.id:
            return

        row = await self._get_suggestion_by_message(payload.guild_id, payload.message_id)
        if not row or int(row["message_id"] or 0) != payload.message_id:
            return

        settings = await self._get_settings(payload.guild_id)
        upvote = settings.get("upvote_emoji") or DEFAULT_UPVOTE
        downvote = settings.get("downvote_emoji") or DEFAULT_DOWNVOTE
        emoji_value = str(payload.emoji)

        if emoji_value == upvote:
            vote = "up"
            opposite = downvote
        elif emoji_value == downvote:
            vote = "down"
            opposite = upvote
        else:
            return

        await self._set_vote(payload.guild_id, int(row["suggestion_id"]), payload.user_id, vote)

        guild = self.bot.get_guild(payload.guild_id)
        if not guild:
            return
        member = guild.get_member(payload.user_id)
        if not member:
            with contextlib.suppress(discord.HTTPException):
                member = await guild.fetch_member(payload.user_id)
        if not member:
            return

        channel = guild.get_channel(int(row["channel_id"])) if row["channel_id"] else None
        if not isinstance(channel, discord.TextChannel):
            return

        with contextlib.suppress(discord.HTTPException, discord.NotFound):
            await channel.get_partial_message(payload.message_id).remove_reaction(opposite, member)

    async def suggest_reaction_remove(self, payload: discord.RawReactionActionEvent) -> None:
        if not payload.guild_id or not payload.user_id:
            return
        if self.bot.user and payload.user_id == self.bot.user.id:
            return

        row = await self._get_suggestion_by_message(payload.guild_id, payload.message_id)
        if not row or int(row["message_id"] or 0) != payload.message_id:
            return

        settings = await self._get_settings(payload.guild_id)
        emoji_value = str(payload.emoji)
        upvote = settings.get("upvote_emoji") or DEFAULT_UPVOTE
        downvote = settings.get("downvote_emoji") or DEFAULT_DOWNVOTE
        if emoji_value == upvote:
            await self._remove_vote(payload.guild_id, int(row["suggestion_id"]), payload.user_id, "up")
        elif emoji_value == downvote:
            await self._remove_vote(payload.guild_id, int(row["suggestion_id"]), payload.user_id, "down")

    @group(
        name="suggest",
        aliases=["suggestions", "suggestion"],
        description="submit suggestions and manage suggestion flow",
        invoke_without_command=True,
    )
    @cooldown(1, 15, commands.BucketType.user)
    async def suggest(self, ctx, *, suggestion: str | None = None):
        """submit a suggestion."""
        if suggestion is None:
            return await ctx.send_help(ctx.command)

        content = suggestion.strip()
        if not content:
            raise CommandError("suggestion **can't** be empty")

        settings = await self._get_settings(ctx.guild.id)
        if not settings.get("enabled"):
            raise CommandError("suggestions are currently locked")
        if not settings.get("channel_id"):
            raise CommandError("no suggestions channel is configured")
        if settings.get("review_enabled") and not settings.get("review_channel_id"):
            raise CommandError("no suggestion review channel is configured")
        if await self._is_ignored(ctx.author):
            raise CommandError("you **can't** submit suggestions in this server")

        status = "pending_review" if settings.get("review_enabled") else "pending"
        suggestion_id = await self._next_suggestion_id(ctx.guild.id)
        await self._insert_suggestion(
            ctx.guild.id,
            suggestion_id,
            ctx.author.id,
            content,
            status,
        )

        row = await self._get_suggestion(ctx.guild.id, suggestion_id)
        if settings.get("review_enabled"):
            review_message_id = await self._post_review_suggestion(ctx.guild, row, settings)
            if review_message_id:
                await self._set_suggestion_fields(
                    ctx.guild.id,
                    suggestion_id,
                    review_channel_id=settings.get("review_channel_id"),
                    review_message_id=review_message_id,
                )
            await ctx.success(
                f"submitted suggestion **#{suggestion_id}** for staff review"
            )
            return

        message_id, thread_id = await self._post_public_suggestion(ctx.guild, row, settings)
        if not message_id:
            raise CommandError("i couldnt post your suggestion")
        await self._set_suggestion_fields(
            ctx.guild.id,
            suggestion_id,
            channel_id=settings.get("channel_id"),
            message_id=message_id,
            thread_id=thread_id,
        )
        await ctx.success(f"submitted suggestion **#{suggestion_id}**")

    @suggest.command(
        name="progress",
        aliases=["working"],
        description="mark a suggestion as in progress",
    )
    async def suggest_progress(self, ctx, suggestion_id: int):
        if not await self._require_staff(ctx):
            return
        await self._set_status(ctx, suggestion_id, "in_progress")

    @suggest.command(
        name="approve",
        description="approve a suggestion",
    )
    async def suggest_approve(self, ctx, suggestion_id: int):
        if not await self._require_staff(ctx):
            return
        await self._set_status(ctx, suggestion_id, "approved")

    @suggest.command(
        name="consider",
        description="mark a suggestion as under consideration",
    )
    async def suggest_consider(self, ctx, suggestion_id: int):
        if not await self._require_staff(ctx):
            return
        await self._set_status(ctx, suggestion_id, "in_consideration")

    @suggest.command(
        name="set",
        aliases=["channel"],
        description="set the suggestions channel (defaults to current channel)",
        usage="[channel]",
    )
    @has_permissions(manage_channels=True)
    async def suggest_set(self, ctx, channel: discord.TextChannel = None):
        channel = channel or (
            ctx.channel if isinstance(ctx.channel, discord.TextChannel) else None
        )
        if channel is None:
            return await ctx.warn("Provide a **text channel** (or run this in one)")
        await self._set_settings(ctx.guild.id, channel_id=channel.id)
        await ctx.success(f"suggestions channel set to {channel.mention}")

    @suggest.command(
        name="unlock",
        aliases=["enable", "on"],
        description="unlock suggestions",
    )
    @has_permissions(manage_channels=True)
    async def suggest_unlock(self, ctx):
        settings = await self._get_settings(ctx.guild.id)
        if not settings.get("channel_id"):
            raise CommandError("set a suggestions channel first")
        await self._set_settings(ctx.guild.id, enabled=True)
        await ctx.success("suggestions are now unlocked")

    @suggest.command(
        name="reply",
        description="reply to a suggestion as staff",
    )
    async def suggest_reply(self, ctx, suggestion_id: int, *, comment: str):
        if not await self._require_staff(ctx):
            return
        row = await self._get_suggestion(ctx.guild.id, suggestion_id)
        if not row:
            raise CommandError("suggestion not found")
        if not await self._send_staff_reply(ctx.guild, row, comment.strip()):
            raise CommandError("i couldnt find anywhere to post that reply")
        await ctx.success(f"posted a reply for suggestion **#{suggestion_id}**")

    @suggest.command(
        name="config",
        aliases=["configuration"],
        description="view suggestion settings",
    )
    @has_permissions(manage_channels=True)
    async def suggest_config(self, ctx):
        settings = await self._get_settings(ctx.guild.id)
        ignored = await self._list_ignored_entries(ctx.guild.id)
        suggestion_channel = await self._resolve_channel(ctx.guild, settings.get("channel_id"))
        review_channel = await self._resolve_channel(ctx.guild, settings.get("review_channel_id"))

        embed = c2(
            color=self.color,
            title="Suggestion settings",
            message="",
        )
        embed.add_field(
            name="General",
            value=body(
                f"**State:** {'unlocked' if settings.get('enabled') else 'locked'}",
                f"**Channel:** {suggestion_channel.mention if suggestion_channel else 'not set'}",
                f"**Review:** {'enabled' if settings.get('review_enabled') else 'disabled'}",
                f"**Review Channel:** {review_channel.mention if review_channel else 'not set'}",
            ),
            inline=False,
        )
        embed.add_field(
            name="Options",
            value=body(
                f"**Threads:** {'enabled' if settings.get('threads_enabled') else 'disabled'}",
                f"**Upvote:** {settings.get('upvote_emoji') or DEFAULT_UPVOTE}",
                f"**Downvote:** {settings.get('downvote_emoji') or DEFAULT_DOWNVOTE}",
                f"**Ignored Entries:** {len(ignored)}",
            ),
            inline=False,
        )
        await ctx.send(embed=embed)

    @suggest.command(
        name="threads",
        aliases=["thread"],
        description="toggle suggestion threads",
    )
    @has_permissions(manage_channels=True)
    async def suggest_threads(self, ctx, setting: StatusConvert):
        await self._set_settings(ctx.guild.id, threads_enabled=setting)
        await ctx.success(
            f"suggestion threads {'enabled' if setting else 'disabled'}"
        )

    @suggest.command(
        name="reactions",
        description="set suggestion reaction emoji",
    )
    @has_permissions(manage_channels=True)
    async def suggest_reactions(self, ctx, upvote: str, downvote: str):
        upvote_emoji, upvote_error = self._normalize_emoji(ctx.guild, upvote)
        if upvote_error:
            raise CommandError(upvote_error)

        downvote_emoji, downvote_error = self._normalize_emoji(ctx.guild, downvote)
        if downvote_error:
            raise CommandError(downvote_error)

        await self._set_settings(
            ctx.guild.id,
            upvote_emoji=upvote_emoji,
            downvote_emoji=downvote_emoji,
        )
        await ctx.success(f"suggestion reactions updated to {upvote_emoji} / {downvote_emoji}")

    @suggest.group(
        name="ignore",
        description="ignore a member or role from suggestions",
        invoke_without_command=True,
    )
    @has_permissions(manage_channels=True)
    async def suggest_ignore(self, ctx, *, target: str | None = None):
        if target is None:
            return await ctx.send_help(ctx.command)

        resolved = await self._resolve_member_or_role(ctx, target)
        if not resolved:
            raise CommandError("**can't** find that member or role")

        target_type = "role" if isinstance(resolved, discord.Role) else "member"
        enabled = await self._toggle_ignored_entry(
            ctx.guild.id,
            resolved.id,
            target_type,
            ctx.author.id,
        )

        if enabled:
            await ctx.success(f"now ignoring **{resolved}** from suggestions")
        else:
            await ctx.success(f"no longer ignoring **{resolved}** from suggestions")

    @suggest_ignore.command(
        name="list",
        description="view ignored suggestion entries",
    )
    @has_permissions(manage_channels=True)
    async def suggest_ignore_list(self, ctx):
        entries = await self._list_ignored_entries(ctx.guild.id)
        if not entries:
            raise CommandError("nothing is ignored from suggestions")

        lines = []
        for entry in entries:
            if entry["target_type"] == "role":
                role = ctx.guild.get_role(int(entry["target_id"]))
                label = role.mention if role else f"deleted role (`{entry['target_id']}`)"
            else:
                member = ctx.guild.get_member(int(entry["target_id"]))
                label = member.mention if member else f"unknown member (`{entry['target_id']}`)"
            lines.append(f"**{entry['target_type']}**: {label}")

        embed = c2(
            color=self.color,
            title="Ignored Suggestions",
            message="",
        )
        await ctx.paginate(embed, lines)

    @suggest.command(
        name="deny",
        aliases=["decline"],
        description="deny a suggestion",
    )
    async def suggest_deny(self, ctx, suggestion_id: int):
        if not await self._require_staff(ctx):
            return
        await self._set_status(ctx, suggestion_id, "denied")

    @suggest.command(
        name="lock",
        aliases=["disable", "off"],
        description="lock suggestions",
    )
    @has_permissions(manage_channels=True)
    async def suggest_lock(self, ctx):
        await self._set_settings(ctx.guild.id, enabled=False)
        await ctx.success("suggestions are now locked")

    @suggest.group(
        name="review",
        description="manage suggestion review mode",
        invoke_without_command=True,
    )
    @has_permissions(manage_channels=True)
    async def suggest_review(self, ctx, setting: StatusConvert | None = None):
        if setting is None:
            return await ctx.send_help(ctx.command)

        await self._set_settings(ctx.guild.id, review_enabled=setting)
        await ctx.success(
            f"suggestion review {'enabled' if setting else 'disabled'}"
        )

    @suggest_review.command(
        name="channel",
        description="set the suggestion review channel (defaults to current channel)",
        usage="[channel]",
    )
    @has_permissions(manage_channels=True)
    async def suggest_review_channel(self, ctx, channel: discord.TextChannel = None):
        channel = channel or (
            ctx.channel if isinstance(ctx.channel, discord.TextChannel) else None
        )
        if channel is None:
            return await ctx.warn("Provide a **text channel** (or run this in one)")
        await self._set_settings(ctx.guild.id, review_channel_id=channel.id)
        await ctx.success(f"suggestion review channel set to {channel.mention}")

    @suggest.command(
        name="reset",
        aliases=["pending"],
        description="reset a suggestion to pending",
    )
    async def suggest_reset(self, ctx, suggestion_id: int):
        if not await self._require_staff(ctx):
            return
        settings = await self._get_settings(ctx.guild.id)
        status = "pending_review" if settings.get("review_enabled") else "pending"
        await self._set_status(ctx, suggestion_id, status)
