from discord.ext.commands import Cog
from .webhook import WebhookCommands


class Webhook(WebhookCommands, Cog):
    """webhook cog"""


async def setup(bot):
    """load webhook cog"""
    await bot.add_cog(Webhook(bot))
