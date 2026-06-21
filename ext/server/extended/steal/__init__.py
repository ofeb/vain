from .steal import Steal

async def setup(bot):
    await bot.add_cog(Steal(bot))
