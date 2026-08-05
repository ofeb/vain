"""patches discord Message with helpers.
adds to_dict serialization shortcut to messages.
import early to activate on all messages"""

import discord


def _to_dict(self) -> dict:
    return {
        "id": self.id,
        "content": self.content,
        "author": {"id": self.author.id, "name": str(self.author)},
        "channel_id": self.channel.id,
        "guild_id": self.guild.id if self.guild else None,
        "embeds": [e.to_dict() for e in self.embeds],
        "attachments": [a.url for a in self.attachments],
        "created_at": self.created_at.isoformat(),
    }

discord.Message.to_dict = _to_dict
