from __future__ import annotations

import contextlib
import time
from typing import TYPE_CHECKING, Any, Iterable

import discord
from discord import Embed, Interaction, SelectOption, ui
from discord.ext import commands
from discord.ext.commands import Command, Group

from core.managers.values import emojis

if TYPE_CHECKING:
    from .ctx import Context

_BLANK = "‎"
_HOME = "__home__"
_SKIP = frozenset({"self", "cls", "flags"})

_PERM_LABELS: dict[str, str] = {
    "moderate_members": "Warn Members",
    "manage_messages": "Manage Messages",
    "manage_channels": "Manage Channels",
    "manage_roles": "Manage Roles",
    "manage_guild": "Manage Server",
    "manage_expressions": "Manage Expressions",
    "ban_members": "Ban Members",
    "kick_members": "Kick Members",
    "administrator": "Administrator",
}

_COG_MAP: dict[str, str] = {
    "Servers":       "Server",
    "Starboard":     "Server",
    "Clownboard":    "Server",
    "Autorole":      "Server",
    "Bump":          "Server",
    "BumpReminder":  "Server",
    "Reaction":      "Server",
    "Timers":        "Server",
    "Logs":          "Server",
    "Counters":      "Server",
    "Webhook":       "Server",
    "Prefix":        "Server",
    "Boosterrole":   "Server",
    "Welcome":       "Server",
    "Goodbye":       "Server",
    "Alias":         "Server",
    "Stickymessage": "Server",
    "Customize":     "Server",
    "Pagination":    "Server",
    "Command":       "Server",
    "Event":         "Server",
    "Module":        "Server",
    "Ignore":        "Server",
    "Autoresponder": "Server",
    "Imgonly":       "Server",
    "Filter":        "Server",
    "Pin":           "Server",
    "Set":           "Server",
    "Badge":         "Server",
    "Settings":      "Server",
    "Reposter":      "Server",
    "Suggest":       "Server",
    "Invoke":        "Server",
    "Antinuke":      "Security",
    "Antiraid":      "Security",
    "Moderation":    "Moderation",
    "Information":   "Information",
    "Snipe":         "Utility",
    "Voicemaster":   "Utility",
    "Fun":         "Fun",
    "Roleplay":    "Fun",
    "Manipulation":"Fun",
    "Misc":        "Fun",
    "Miscellaneous": "Miscellaneous",
    "Music":       "Music",
    "Soundcloud":  "Music",
    "Spotify":     "Music",
    "Socials":     "Social",
    "Levels":      "Rewards",
    "Level":       "Rewards",
    "Giveaway":    "Rewards",
    "Crypto":      "Crypto",
    "Lastfm":      "Last.fm",
    "Owner":       "Owner",
    "Jishaku":     "Owner",
}

_OWNER_COGS = frozenset({"Developer", "Jishaku", "Owner"})

_CAT_EMOJIS: dict[str, str] = {
    "Home": "\U0001f3e0",
    "Server": "\U0001f4e1",
    "Security": "\U0001f6e1\ufe0f",
    "Moderation": "\U0001f6ae",
    "Information": "\U0001f4ca",
    "Utility": "\U0001f527",
    "Fun": "\U0001f3b2",
    "Miscellaneous": "\U0001f4ac",
    "Music": "\U0001f3b5",
    "Social": "\U0001f4e3",
    "Rewards": "\U0001f3c6",
    "Crypto": "\U0001fa99",
    "Last.fm": "\U0001f3b6",
    "Owner": "\U0001f512",
}

_BLURBS: dict[str, str] = {
    "Server": "Prefixes, starboard, autorole, reactions, logs, and server setup.",
    "Security": "Antinuke, antiraid, and automod protection modules.",
    "Moderation": "Tools that help you moderate your server.",
    "Information": "User, guild, and bot lookups, avatars, banners, and stats.",
    "Utility": "Snipes, reminders, AFK, quotes, and voicemaster utilities.",
    "Fun": "Games, memes, roleplay, images, and fun commands.",
    "Miscellaneous": "Various useful commands that don't fit elsewhere.",
    "Music": "Queue, playback, Spotify, SoundCloud, and Lavalink controls.",
    "Social": "Twitch, YouTube, TikTok, Instagram, and feed notifications.",
    "Rewards": "XP, levels, giveaways, and reward systems.",
    "Crypto": "Cryptocurrency prices, charts, and market data.",
    "Last.fm": "Scrobbles, charts, covers, whoknows, and now playing.",
    "Owner": "Developer-only commands used to maintain bleed.",
}

_ORDER: tuple[str, ...] = (
    "Server", "Security", "Moderation",
    "Information", "Utility", "Fun", "Miscellaneous",
    "Music", "Social", "Rewards", "Crypto", "Last.fm", "Owner",
)


def _cog_key(cog: commands.Cog | None) -> str:
    if cog is None:
        return "Other"
    name = cog.qualified_name
    for sfx in ("Commands", "Events"):
        if name.endswith(sfx):
            return name[: -len(sfx)]
    return name


def _category(cog: commands.Cog | None) -> str:
    return _COG_MAP.get(_cog_key(cog), _cog_key(cog))


def is_owner_cog(cog: commands.Cog | None) -> bool:
    return cog is not None and (_cog_key(cog) in _OWNER_COGS or _category(cog) == "Owner")


def _hidden(cog: commands.Cog | None, *, owner: bool) -> bool:
    return is_owner_cog(cog) and not owner


def _cmd_hidden(cmd: Command, *, owner: bool) -> bool:
    return _hidden(cmd.cog, owner=owner)


def _fmt_commands(cmds: Iterable[Command], limit: int = 3900) -> str:
    names = sorted({c.qualified_name for c in cmds})
    if not names:
        return "`none`"
    parts: list[str] = []
    total = 0
    for i, n in enumerate(names):
        piece = f"`{n}`"
        sep = 2 if parts else 0
        if total + sep + len(piece) > limit:
            body = ", ".join(parts)
            return f"{body}\n*and {len(names) - i} more*"
        parts.append(piece)
        total += sep + len(piece)
    return ", ".join(parts)


def _visible_subs(grp: Group) -> list[Command]:
    out: list[Command] = []

    def _walk(g: Group) -> None:
        for c in g.commands:
            if c.hidden:
                continue
            out.append(c)
            if isinstance(c, Group) and c.commands:
                _walk(c)

    _walk(grp)
    return out


def _param_items(cmd: Command) -> list[tuple[str, Any]]:
    return [(name, param) for name, param in cmd.clean_params.items() if name not in _SKIP]


def _params(cmd: Command) -> list[str]:
    return [name.replace("_", " ") for name, _ in _param_items(cmd)]


def _aliases(cmd: Command) -> str:
    a = [x for x in cmd.aliases if x]
    return ", ".join(a) if a else "none"


def _syntax(cmd: Command, prefix: str) -> str:
    usage = (cmd.usage or "").strip()
    if usage:
        return f"{prefix}{cmd.qualified_name} {usage}".rstrip()
    tokens: list[str] = []
    for name, param in _param_items(cmd):
        label = name.replace("_", " ")
        if getattr(param, "required", False):
            tokens.append(f"({label})")
        else:
            tokens.append(f"[{label}]")
    suffix = " ".join(tokens)
    return f"{prefix}{cmd.qualified_name} {suffix}".rstrip()


def _example(cmd: Command, prefix: str) -> str | None:
    raw = (getattr(cmd, "example", None) or "").strip()
    if not raw:
        return None
    if raw.startswith(prefix):
        return raw
    if raw.startswith(cmd.qualified_name):
        return f"{prefix}{raw}"
    return f"{prefix}{cmd.qualified_name} {raw}".rstrip()


def _usage_block(cmd: Command, prefix: str) -> str:
    block = [f"Syntax: {_syntax(cmd, prefix)}"]
    if example := _example(cmd, prefix):
        block.append(f"Example: {example}")
    return "```\n" + "\n".join(block) + "```"


def _permission_label(cmd: Command) -> str | None:
    labels: list[str] = []
    seen: set[str] = set()
    for chk in cmd.checks:
        q = getattr(chk, "__qualname__", "") or ""
        n = getattr(chk, "__name__", "") or ""
        blob = f"{q} {n}"
        if "is_owner" in blob:
            label = "Bot Owner"
        elif "trusted" in blob or "guild_owner" in blob:
            label = "Server Owner"
        elif "has_permissions" in blob:
            try:
                for cell in (chk.__closure__ or []):
                    value = cell.cell_contents
                    if not isinstance(value, dict):
                        continue
                    if value.get("server_owner") or value.get("guild_owner"):
                        label = "Server Owner"
                        if label not in seen:
                            seen.add(label)
                            labels.append(label)
                    perms = [
                        _PERM_LABELS.get(perm, perm.replace("_", " ").title())
                        for perm, enabled in value.items()
                        if enabled and perm not in {"send_messages", "server_owner", "guild_owner"}
                    ]
                    if perms:
                        label = " & ".join(perms)
                        if label not in seen:
                            seen.add(label)
                            labels.append(label)
            except Exception:
                pass
            continue
        else:
            continue
        if label not in seen:
            seen.add(label)
            labels.append(label)
    return labels[0] if labels else None


def _cooldown_label(cmd: Command) -> str | None:
    cooldown = getattr(cmd, "cooldown", None)
    if cooldown is None:
        return None
    per = getattr(cooldown, "per", None)
    if per is None:
        return None
    if float(per).is_integer():
        return f"{int(per)} seconds"
    return f"{per:g} seconds"


def _information(cmd: Command) -> dict[str, str]:
    info: dict[str, str] = {}
    raw_info = getattr(cmd, "information", {}) or {}
    for key, value in dict(raw_info).items():
        info[str(key)] = str(value)
    if cooldown := _cooldown_label(cmd):
        info["cooldown"] = cooldown
    if cmd.qualified_name.startswith("antinuke"):
        info["permissions"] = "Server Owner"
    elif permissions := _permission_label(cmd):
        info["permissions"] = permissions
    return info


def _information_value(cmd: Command) -> str:
    info = _information(cmd)
    if not info:
        return "N/A"
    warning_emoji = emojis.warn
    cooldown_emoji = emojis.cooldown
    emoji_map = {
        "cooldown": cooldown_emoji,
        "permissions": warning_emoji,
    }
    return "\n".join(f"{emoji_map.get(key, warning_emoji)} {value}" for key, value in info.items())


def _module(cmd: Command) -> str:
    return cmd.cog_name.lower() if cmd.cog_name else "N/A"


def _detail_embed(cmd: Command, ctx: Context) -> Embed:
    prefix = getattr(ctx, "clean_prefix", None) or ctx.prefix or ";"
    if isinstance(prefix, list):
        prefix = prefix[0] if prefix else ";"
    title = ("Group Command: " if isinstance(cmd, Group) else "Command: ") + cmd.qualified_name
    desc = cmd.help or cmd.description or "No description given"
    e = Embed(title=title, description=desc, color=ctx.bot.color)
    e.set_author(name=ctx.author.display_name, icon_url=ctx.author.display_avatar.url)
    e.add_field(name="Aliases", value=_aliases(cmd) if _aliases(cmd) != "none" else "none", inline=True)
    e.add_field(name="Parameters", value=", ".join(_params(cmd)) or "none", inline=True)
    e.add_field(name="Information", value=_information_value(cmd), inline=True)
    e.add_field(name="Usage", value=_usage_block(cmd, str(prefix)), inline=False)
    e.set_footer(text=f"Module: {_module(cmd)}")
    return e


def _brief_embed(cmd: Command, ctx: Context) -> Embed:
    prefix = getattr(ctx, "clean_prefix", None) or ctx.prefix or ";"
    if isinstance(prefix, list):
        prefix = prefix[0] if prefix else ";"
    desc = cmd.short_doc or cmd.help or cmd.description or ""
    usage = _usage_block(cmd, str(prefix))
    description = f"{desc}\n{usage}" if desc else usage
    e = Embed(
        color=ctx.bot.color,
        title="Command: " + cmd.qualified_name,
        description=description,
    )
    e.set_author(name=ctx.author.display_name, icon_url=ctx.author.display_avatar.url)
    return e


class _CategorySelect(ui.Select):
    def __init__(self, view: HelpView) -> None:
        opts: list[SelectOption] = []
        labels = [l for l in _ORDER if l in view.cats]
        labels += sorted(set(view.cats) - set(labels))

        opts.append(SelectOption(
            label="Home",
            value=_HOME,
            description="Return to the main help menu.",
        ))

        for label in labels[:24]:
            opts.append(SelectOption(
                label=label,
                value=label,
                description=_BLURBS.get(label, f"{label} commands."),
            ))

        super().__init__(
            placeholder="Select a category...",
            min_values=1,
            max_values=1,
            options=opts,
        )
        self._v = view

    async def callback(self, inter: Interaction) -> None:
        if self.values[0] == _HOME:
            embed = self._v.home
        else:
            embed = self._v.cat_embed(self.values[0])
        await inter.response.edit_message(embed=embed, view=self._v)


class HelpView(ui.View):
    def __init__(self, ctx: Context, cats: dict[str, list[Command]]) -> None:
        super().__init__(timeout=180)
        self.ctx = ctx
        self.cats = cats
        self.home = self._home_embed()
        self.msg: discord.Message | None = None
        self.add_item(_CategorySelect(self))

    async def interaction_check(self, inter: Interaction) -> bool:
        if inter.user.id == self.ctx.author.id:
            return True
        await inter.response.send_message("not yours", ephemeral=True)
        return False

    def cat_embed(self, label: str) -> Embed:
        prefix = getattr(self.ctx, "clean_prefix", None) or self.ctx.prefix or ";"
        if isinstance(prefix, list):
            prefix = prefix[0] if prefix else ";"
        emoji = _CAT_EMOJIS.get(label, "")
        title = f"{emoji} {label} Commands" if emoji else f"**{label} Commands**"
        e = Embed(
            title=title,
            description=_fmt_commands(self.cats[label]),
            color=self.ctx.bot.color,
        )
        if self.ctx.bot.user:
            e.set_author(name=self.ctx.bot.user.display_name, icon_url=self.ctx.bot.user.display_avatar.url)
        return e

    def _home_embed(self) -> Embed:
        p = getattr(self.ctx, "clean_prefix", None) or self.ctx.prefix or ";"
        if isinstance(p, list):
            p = p[0] if p else ";"
        e = Embed(
            color=self.ctx.bot.color,
            description=(
                f"> Use `{p}help <command>` for help on a specific command.\n"
                f"> Parameters in `(...)` are required, `[...]` are optional.\n\n"
                f"> Join the [support server](https://discord.gg/bleed) for more support."
            ),
        )
        if self.ctx.bot.user:
            e.set_author(name=self.ctx.bot.user.display_name, icon_url=self.ctx.bot.user.display_avatar.url)
        return e

    async def on_timeout(self) -> None:
        for item in self.children:
            item.disabled = True
        if self.msg:
            with contextlib.suppress(discord.HTTPException):
                await self.msg.edit(view=self)


class BleedHelp:
    def __init__(self) -> None:
        self.ctx: Context = None
        self._seen: dict[int, float] = {}

    def register(self, bot: commands.Bot) -> None:
        @bot.command(name="help", aliases=["h", "commands"], description="view command help")
        async def _help(ctx: Context, *, command: str | None = None) -> None:
            await self.invoke(ctx, command)

    async def invoke(self, ctx: Context, query: str | None = None) -> None:
        self.ctx = ctx
        bot = ctx.bot
        owner = ctx.author.id in bot.owners

        if query is None:
            await self._send_home(bot, owner)
            return

        cog = bot.get_cog(query)
        if cog is not None:
            if _hidden(cog, owner=owner):
                await self._not_found(query)
                return
            await self._send_cog(cog)
            return

        cmd = self._find(bot, query)
        if cmd is None or _cmd_hidden(cmd, owner=owner):
            await self._not_found(query)
            return
        if isinstance(cmd, Group):
            await self._send_group(cmd)
        else:
            await self._send_cmd(cmd)

    def _find(self, bot: commands.Bot, query: str) -> Command | None:
        direct = bot.get_command(query.strip())
        if direct is not None:
            return direct
        parts = query.strip().split()
        if not parts:
            return None

        def _match(name: str, c: Command) -> bool:
            return c.name.lower() == name or any(a.lower() == name for a in c.aliases)

        node: Command | None = None
        for c in bot.commands:
            if _match(parts[0].lower(), c):
                node = c
                break
        if node is None:
            return None
        for part in parts[1:]:
            if not isinstance(node, Group):
                return None
            found = next((s for s in node.commands if _match(part.lower(), s)), None)
            if not found:
                return None
            node = found
        return node

    def _prefix(self) -> str:
        p = getattr(self.ctx, "clean_prefix", None) or self.ctx.prefix or ";"
        return p[0] if isinstance(p, list) else str(p)

    def _base_embed(self, *, title: str | None = None, description: str | None = None) -> Embed:
        e = Embed(title=title, description=description, color=self.ctx.bot.color)
        if self.ctx.bot.user:
            e.set_author(name=self.ctx.bot.user.display_name, icon_url=self.ctx.bot.user.display_avatar.url)
        return e

    def _build_cats(self, bot: commands.Bot, owner: bool) -> dict[str, list[Command]]:
        cats: dict[str, list[Command]] = {}
        for cog in bot.cogs.values():
            if _hidden(cog, owner=owner):
                continue
            cmds = [c for c in cog.get_commands() if not c.hidden]
            if cmds:
                cats.setdefault(_category(cog), []).extend(cmds)
        return cats

    def _dedup(self) -> bool:
        if not self.ctx.message:
            return False
        now = time.monotonic()
        mid = self.ctx.message.id
        if now - self._seen.get(mid, 0) < 3.0:
            return True
        self._seen[mid] = now
        if len(self._seen) > 512:
            self._seen = {k: v for k, v in self._seen.items() if now - v < 3.0}
        return False

    async def _send(self, embed: Embed, *, view: ui.View | None = None) -> discord.Message:
        ctx = self.ctx
        kw: dict[str, Any] = {}
        if ctx.message and not ctx.interaction:
            kw["reference"] = ctx.message.to_reference(fail_if_not_exists=False)
            kw["allowed_mentions"] = discord.AllowedMentions.none()
        return await ctx.send(embed=embed, view=view, **kw)

    async def _send_home(self, bot: commands.Bot, owner: bool) -> None:
        if self._dedup():
            return
        cats = self._build_cats(bot, owner)
        view = HelpView(self.ctx, cats)
        view.msg = await self._send(view.home, view=view)

    async def send_brief(self, ctx: Context, cmd: Command) -> discord.Message:
        self.ctx = ctx
        return await self._send(_brief_embed(cmd, ctx))

    async def _send_cmd(self, cmd: Command) -> None:
        await self._send(_detail_embed(cmd, self.ctx))

    async def _send_group(self, grp: Group) -> None:
        targets = [grp] + _visible_subs(grp)
        embeds = [_detail_embed(target, self.ctx) for target in targets]
        if len(embeds) == 1:
            await self._send(embeds[0])
        else:
            await self.ctx.paginate(embeds)

    async def _send_cog(self, cog: commands.Cog) -> None:
        cmds = [c for c in cog.get_commands() if not c.hidden]
        e = self._base_embed(title=f"**{_category(cog)} Commands**", description=_fmt_commands(cmds))
        await self._send(e)

    async def _not_found(self, query: str) -> None:
        p = self._prefix()
        e = self._base_embed(
            title="not found",
            description=f"no command named **`{query}`**\nuse `{p}help` or https://bleed.bot/commands to browse for commands",
        )
        await self._send(e)
