"""toggle state converter for prefix commands."""

from discord.ext.commands import CommandError, Context, Converter


class StatusConvert(Converter):
    """convert common on/off strings to bool."""

    async def convert(self, ctx: Context, argument: str) -> bool:
        value = argument.lower().strip()
        if value in {"enable", "true", "yes", "on"}:
            return True
        if value in {"disable", "false", "none", "null", "off", "no"}:
            return False
        raise CommandError("Please specify **yes** or **no**")
