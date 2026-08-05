"""gateway event patches and dispatchers.
events.py hooks into discord gateway events.
dispatch.py routes events to registered handlers"""

from . import events, dispatch

__all__ = ["events", "dispatch"]
