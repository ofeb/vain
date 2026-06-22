from __future__ import annotations

from core.discord.package import Package

from .extended.autoresponder.events import AutoresponderEvents
from .extended.boost.events import BoostEvents
from .extended.goodbye.events import GoodbyeEvents
from .extended.pagination.events import PaginationEvents
from .extended.settings.events import SettingsEvents
from .extended.stickymessage.events import StickymessageEvents
from .extended.suggest.events import SuggestEvents
from .extended.welcome.events import WelcomeEvents


class ServerEvents(
    WelcomeEvents,
    GoodbyeEvents,
    AutoresponderEvents,
    StickymessageEvents,
    PaginationEvents,
    SuggestEvents,
    SettingsEvents,
    BoostEvents,
    Package,
):
    """Server-wide event listeners."""
