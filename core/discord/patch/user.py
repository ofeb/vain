"""patches User and Member with badge helpers.
reads public flags and maps them to emoji config values.
import early to activate"""

import discord


def _badges(self, as_str: bool = False, delim: str = " "):
    badges = []
    flag_emojis = {}
    for name, active in self.public_flags:
        if active and (e := flag_emojis.get(name)):
            badges.append(e)
    return delim.join(badges) if as_str else badges

discord.User.badges = _badges
discord.Member.badges = _badges
