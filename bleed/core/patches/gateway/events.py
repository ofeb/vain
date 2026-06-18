"""gateway event hooks.
registers listeners that run before cog listeners.
handles global checks like blacklists and maintenance"""

from discord.ext import commands


class GatewayEvents(commands.Cog):
    """global pre-processing event handlers.
    intercepts all messages before command processing.
    checks blacklist and disabled modules"""

    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @commands.Cog.listener()
    async def on_message(self, message):
        if message.author.bot:
            return
        if not message.guild:
            return
        if await self.bot.db.fetchrow(
            "SELECT 1 FROM blacklist WHERE user_id = $1", message.author.id
        ):
            return
        await self.bot.process_commands(message)

async def setup(bot: commands.Bot):
    await bot.add_cog(GatewayEvents(bot))
