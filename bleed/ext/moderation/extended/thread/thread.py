from discord.ext.commands import group, has_permissions

from core.discord.package import Package


class Thread(Package):
    """thread management"""

    @group(
        name="thread",
        description="Commands to manage threads and forum posts",
        invoke_without_command=True,
    )
    async def thread(self, ctx):
        """thread group help"""
        return await ctx.send_help(ctx.command)

    @thread.command(
        name="unlock",
        description="Unlock a thread or forum post",
    )
    @has_permissions(manage_threads=True)
    async def thread_unlock(self, ctx, thread, *, reason):
        """unlock a thread"""
        pass

    @thread.command(
        name="add",
        description="No description given",
    )
    @has_permissions(manage_threads=True)
    async def thread_add(self, ctx, thread, member):
        """add member to thread"""
        pass

    @thread.command(
        name="lock",
        description="Lock a thread or forum post",
    )
    @has_permissions(manage_threads=True)
    async def thread_lock(self, ctx, thread, *, reason):
        """lock a thread"""
        pass

    @thread.command(
        name="remove",
        description="No description given",
    )
    @has_permissions(manage_threads=True)
    async def thread_remove(self, ctx, thread, member):
        """remove member from thread"""
        pass

    @thread.command(
        name="watch",
        description="No description given",
    )
    @has_permissions(manage_channels=True)
    async def thread_watch(self, ctx, thread):
        """watch a thread"""
        pass

    @thread.command(
        name="watch list",
        description="No description given",
    )
    @has_permissions(manage_channels=True)
    async def thread_watch_list(self, ctx):
        """list watched threads"""
        pass

    @thread.command(
        name="rename",
        description="No description given",
    )
    @has_permissions(manage_threads=True)
    async def thread_rename(self, ctx, thread, *, new_name):
        """rename a thread"""
        pass
