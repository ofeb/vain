from discord.ext.commands import group

from core.discord.package import Package


class Purge(Package):
    """purge management"""

    @group(
        name="purge",
        description="Deletes the specified amount of messages from the current channel",
        invoke_without_command=True,
    )
    async def purge(self, ctx, member, search):
        """purge messages"""
        pass

    @purge.command(
        name="startswith",
        description="Purge messages that start with a given substring",
    )
    async def purge_startswith(self, ctx, *, substring):
        """purge messages starting with substring"""
        pass

    @purge.command(
        name="embeds",
        description="Purge embeds from chat",
    )
    async def purge_embeds(self, ctx, search):
        """purge embeds"""
        pass

    @purge.command(
        name="files",
        description="Purge files/attachments from chat",
    )
    async def purge_files(self, ctx, search):
        """purge files"""
        pass

    @purge.command(
        name="images",
        description="Purge images (including links) from chat",
    )
    async def purge_images(self, ctx, search):
        """purge images"""
        pass

    @purge.command(
        name="contains",
        description="Purges messages containing given substring",
    )
    async def purge_contains(self, ctx, *, substring):
        """purge messages containing substring"""
        pass

    @purge.command(
        name="before",
        description="Purge messages before a given message ID",
    )
    async def purge_before(self, ctx, messagelink):
        """purge messages before message"""
        pass

    @purge.command(
        name="bots",
        description="Purge messages from bots in chat",
    )
    async def purge_bots(self, ctx, search):
        """purge bot messages"""
        pass

    @purge.command(
        name="after",
        description="Purge messages after a given message ID",
    )
    async def purge_after(self, ctx, messagelink):
        """purge messages after message"""
        pass

    @purge.command(
        name="webhooks",
        description="Purge messages from webhooks in chat",
    )
    async def purge_webhooks(self, ctx, search):
        """purge webhook messages"""
        pass

    @purge.command(
        name="between",
        description="Purge between two messages",
    )
    async def purge_between(self, ctx, start_id, finish_id):
        """purge messages between two messages"""
        pass

    @purge.command(
        name="links",
        description="Purge messages containing links",
    )
    async def purge_links(self, ctx, search):
        """purge messages with links"""
        pass

    @purge.command(
        name="activity",
        description="Purge activity messages from chat",
    )
    async def purge_activity(self, ctx, search):
        """purge activity messages"""
        pass

    @purge.command(
        name="humans",
        description="Purge messages from humans in chat",
    )
    async def purge_humans(self, ctx, search):
        """purge human messages"""
        pass

    @purge.command(
        name="endswith",
        description="Purge messages that ends with a given substring",
    )
    async def purge_endswith(self, ctx, *, substring):
        """purge messages ending with substring"""
        pass

    @purge.command(
        name="reactions",
        description="Purge reactions from messages in chat",
    )
    async def purge_reactions(self, ctx, search):
        """purge reactions"""
        pass

    @purge.command(
        name="stickers",
        description="Purge stickers from chat",
    )
    async def purge_stickers(self, ctx, search):
        """purge stickers"""
        pass

    @purge.command(
        name="mentions",
        description="Purge mentions for a member from chat",
    )
    async def purge_mentions(self, ctx, member, search):
        """purge mentions"""
        pass

    @purge.command(
        name="emoji",
        description="Purge emojis from chat",
    )
    async def purge_emoji(self, ctx, search):
        """purge emojis"""
        pass

    @purge.command(
        name="emotes",
        description="Purge emotes from chat",
    )
    async def purge_emotes(self, ctx, search):
        """purge emotes"""
        pass

    @purge.command(
        name="upto",
        description="Purge messages up to a message link",
    )
    async def purge_upto(self, ctx, messagelink):
        """purge messages up to message"""
        pass
