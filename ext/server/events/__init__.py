from __future__ import annotations

from core.discord.package import Package

from ..extended.autoresponder.events import AutoresponderEvents
from ..extended.autorole.events import AutoroleEvents
from ..extended.boost.events import BoostEvents
from ..extended.filter.events import FilterEvents
from ..extended.goodbye.events import GoodbyeEvents
from ..extended.imgonly.events import ImgonlyEvents
from ..extended.settings.events import SettingsEvents
from ..extended.stickymessage.events import StickymessageEvents
from ..extended.suggest.events import SuggestEvents
from ..extended.welcome.events import WelcomeEvents


class ServerEvents(
    WelcomeEvents,
    GoodbyeEvents,
    AutoroleEvents,
    AutoresponderEvents,
    StickymessageEvents,
    SuggestEvents,
    SettingsEvents,
    BoostEvents,
    FilterEvents,
    ImgonlyEvents,
    Package,
):
    """Server-wide event listeners."""
