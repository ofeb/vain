from discord.ext.commands import group

from core.discord.package import Package


class Remind(Package):
    """reminder management"""

    @group(
        name="remind",
        description="Get reminders for a duration set about whatever you choose",
        invoke_without_command=True,
    )
    async def remind(self, ctx, *, reminder):
        """set a reminder"""
        pass

    @remind.command(
        name="remove",
        description="Remove a reminder",
    )
    async def remind_remove(self, ctx, id):
        """remove a reminder"""
        pass

    @remind.command(
        name="list",
        description="View a list of your reminders",
    )
    async def remind_list(self, ctx):
        """list reminders"""
        pass
