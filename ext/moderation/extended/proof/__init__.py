from discord.ext.commands import Cog
from .proof import Proof


class Proof(Proof, Cog):
    """proof cog"""


async def setup(bot):
    """load proof cog"""
    await bot.add_cog(Proof(bot))
