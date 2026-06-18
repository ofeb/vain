"""custom exception types for the bot.
raised in commands and caught by error handler.
import what you need from here"""

from discord.ext.commands import CommandError


class RolePosition(CommandError):
    """role hierarchy position error"""
    def __init__(self, msg: str = "role is too high up"):
        super().__init__(msg)


class Ratelimited(CommandError):
    """user hit a ratelimit"""
    def __init__(self, retry_after: float):
        self.retry_after = retry_after
        super().__init__(f"slow down, try again in {retry_after:.1f}s")


class BlacklistError(CommandError):
    """user or guild is blacklisted"""
    def __init__(self, obj: str = "user"):
        super().__init__(f"this {obj} is blacklisted")


class NotPremium(CommandError):
    """feature requires premium"""
    def __init__(self):
        super().__init__("this feature requires premium")


class SilencedUser(CommandError):
    """user is silenced in this guild"""
    def __init__(self):
        super().__init__("you are silenced in this server")


class MissingSetup(CommandError):
    """cog feature not set up yet"""
    def __init__(self, feature: str):
        super().__init__(f"{feature} hasnt been set up yet")


class MaxEntries(CommandError):
    """table row limit reached"""
    def __init__(self, table: str, limit: int):
        super().__init__(f"cant add more than {limit} {table}s")
