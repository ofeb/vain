from __future__ import annotations

import contextlib

import discord
from discord.ext.commands import group, CommandError

from core.discord.package import Package
from core.managers.permissions import has_permissions
from core.discord.views.embed import panel_embed


def label_line(label: str, value: str) -> str:
    return f"**{label}**: {value}"


class Thread(Package):
    """Commands to manage threads and forum posts."""

    async def _resolve_thread(self, ctx, thread: discord.Thread | None = None) -> discord.Thread:
        if thread is not None:
            return thread
        if isinstance(ctx.channel, discord.Thread):
            return ctx.channel
        raise CommandError("Provide a thread or run this inside a thread")

    @group(
        name="thread",
        aliases=["threads"],
        description="Commands to manage threads and forum posts",
        invoke_without_command=True,
    )
    async def thread(self, ctx):
        """thread group help"""
        return await ctx.send_help(ctx.command)

    @thread.command(
        name="lock",
        description="Lock a thread or forum post",
        example=",thread lock #thread spam",
    )
    @has_permissions(manage_threads=True)
    async def thread_lock(
        self,
        ctx,
        thread: discord.Thread = None,
        *,
        reason: str = "No reason provided",
    ):
        """lock a thread"""
        thread = await self._resolve_thread(ctx, thread)
        if thread.locked:
            return await ctx.warn(f"{thread.mention} is already **locked**")
        try:
            await thread.edit(locked=True, reason=f"thread lock by {ctx.author}: {reason}")
        except discord.Forbidden:
            return await ctx.fail("I don't have permission to lock this thread")
        except discord.HTTPException as e:
            return await ctx.fail(f"Failed to lock thread: {e}")
        return await ctx.success(f"Locked {thread.mention} — {reason}")

    @thread.command(
        name="unlock",
        description="Unlock a thread or forum post",
        example=",thread unlock #thread",
    )
    @has_permissions(manage_threads=True)
    async def thread_unlock(
        self,
        ctx,
        thread: discord.Thread = None,
        *,
        reason: str = "No reason provided",
    ):
        """unlock a thread"""
        thread = await self._resolve_thread(ctx, thread)
        if not thread.locked:
            return await ctx.warn(f"{thread.mention} is not **locked**")
        try:
            await thread.edit(locked=False, reason=f"thread unlock by {ctx.author}: {reason}")
        except discord.Forbidden:
            return await ctx.fail("I don't have permission to unlock this thread")
        except discord.HTTPException as e:
            return await ctx.fail(f"Failed to unlock thread: {e}")
        return await ctx.success(f"Unlocked {thread.mention} — {reason}")

    @thread.command(
        name="add",
        aliases=["invite"],
        description="Add a member to a private thread",
        example=",thread add #thread @member",
    )
    @has_permissions(manage_threads=True)
    async def thread_add(self, ctx, thread: discord.Thread, member: discord.Member):
        """add member to thread"""
        try:
            await thread.add_user(member)
        except discord.Forbidden:
            return await ctx.fail("I don't have permission to add members to this thread")
        except discord.HTTPException as e:
            return await ctx.fail(f"Failed to add member: {e}")
        return await ctx.success(f"Added {member.mention} to {thread.mention}")

    @thread.command(
        name="remove",
        aliases=["kick"],
        description="Remove a member from a private thread",
        example=",thread remove #thread @member",
    )
    @has_permissions(manage_threads=True)
    async def thread_remove(self, ctx, thread: discord.Thread, member: discord.Member):
        """remove member from thread"""
        try:
            await thread.remove_user(member)
        except discord.Forbidden:
            return await ctx.fail("I don't have permission to remove members from this thread")
        except discord.HTTPException as e:
            return await ctx.fail(f"Failed to remove member: {e}")
        return await ctx.success(f"Removed {member.mention} from {thread.mention}")

    @thread.command(
        name="rename",
        aliases=["name"],
        description="Rename a thread",
        example=",thread rename #thread new-name",
    )
    @has_permissions(manage_threads=True)
    async def thread_rename(self, ctx, thread: discord.Thread = None, *, new_name: str):
        """rename a thread"""
        thread = await self._resolve_thread(ctx, thread)
        name = new_name.strip()[:100]
        if not name:
            return await ctx.warn("Provide a new name")
        try:
            await thread.edit(name=name, reason=f"thread rename by {ctx.author}")
        except discord.Forbidden:
            return await ctx.fail("I don't have permission to rename this thread")
        except discord.HTTPException as e:
            return await ctx.fail(f"Failed to rename thread: {e}")
        return await ctx.success(f"Renamed thread to **{name}**")

    @thread.command(
        name="archive",
        description="Archive a thread",
    )
    @has_permissions(manage_threads=True)
    async def thread_archive(self, ctx, thread: discord.Thread = None):
        """archive a thread"""
        thread = await self._resolve_thread(ctx, thread)
        if thread.archived:
            return await ctx.warn(f"{thread.mention} is already **archived**")
        try:
            await thread.edit(archived=True, reason=f"thread archive by {ctx.author}")
        except discord.Forbidden:
            return await ctx.fail("I don't have permission to archive this thread")
        except discord.HTTPException as e:
            return await ctx.fail(f"Failed to archive thread: {e}")
        return await ctx.success(f"Archived {thread.mention}")

    @thread.command(
        name="unarchive",
        description="Unarchive a thread",
    )
    @has_permissions(manage_threads=True)
    async def thread_unarchive(self, ctx, thread: discord.Thread = None):
        """unarchive a thread"""
        thread = await self._resolve_thread(ctx, thread)
        if not thread.archived:
            return await ctx.warn(f"{thread.mention} is not **archived**")
        try:
            await thread.edit(archived=False, reason=f"thread unarchive by {ctx.author}")
        except discord.Forbidden:
            return await ctx.fail("I don't have permission to unarchive this thread")
        except discord.HTTPException as e:
            return await ctx.fail(f"Failed to unarchive thread: {e}")
        return await ctx.success(f"Unarchived {thread.mention}")

    @thread.command(
        name="watch",
        description="Join / follow a thread (bot watches it)",
    )
    @has_permissions(manage_channels=True)
    async def thread_watch(self, ctx, thread: discord.Thread = None):
        """watch a thread"""
        thread = await self._resolve_thread(ctx, thread)
        with contextlib.suppress(discord.HTTPException, discord.Forbidden):
            await thread.join()
        return await ctx.success(f"Now watching {thread.mention}")

    @thread.command(
        name="leave",
        description="Leave a watched thread",
    )
    @has_permissions(manage_channels=True)
    async def thread_leave(self, ctx, thread: discord.Thread = None):
        """leave a thread"""
        thread = await self._resolve_thread(ctx, thread)
        with contextlib.suppress(discord.HTTPException, discord.Forbidden):
            await thread.leave()
        return await ctx.success(f"Left {thread.mention}")
