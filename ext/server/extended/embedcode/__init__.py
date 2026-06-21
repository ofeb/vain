from .embedcode import Embedcode

async def setup(bot):
    await bot.add_cog(Embedcode(bot))
