from __future__ import annotations

import contextlib
import time
from typing import TYPE_CHECKING, Any, Iterable

import discord
from discord import Embed, Interaction, SelectOption, ui
from discord.ext import commands
from discord.ext.commands import Command, Group

if TYPE_CHECKING:
    from .ctx import Context

_BLANK = "‎"
_HOME = "__home__"
_SKIP = frozenset({"self", "cls", "flags"})

_COG_MAP: dict[str, str] = {
    "Servers":       "Server",
    "Starboard":     "Server",
    "Clownboard":    "Server",
    "Autorole":      "Server",
    "Bump":          "Server",
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
    "Music":       "Music",
    "Soundcloud":  "Music",
    "Spotify":     "Music",
    "Socials":     "Social",
    "Levels":      "Rewards",
    "Giveaway":    "Rewards",
    "Crypto":      "Rewards",
    "Lastfm":      "Last.fm",
    "Owner":       "Owner",
    "Jishaku":     "Owner",
}

_OWNER_COGS = frozenset({"Developer", "Jishaku"})

_BLURBS: dict[str, str] = {
    "Server": "prefixes starboard autorole reactions timers logs and server setup",
    "Security": "antinuke antiraid and automod protection modules",
    "Moderation": "tools that help you moderate your server",
    "Information": "user guild bot lookups avatars banners and stats",
    "Utility": "snipes reminders afk quotes and voicemaster utilities",
    "Fun": "games memes roleplay images quotes and fun commands",
    "Music": "queue playback spotify soundcloud and lavalink controls",
    "Social": "twitch youtube tiktok instagram and feed notifications",
    "Rewards": "xp levels giveaways crypto tickers and reward systems",
    "Last.fm": "scrobble charts covers whoknows and now playing",
    "Owner": "owner tools reload jishaku and bot management",
}

_ORDER: tuple[str, ...] = (
    "Server", "Security", "Moderation",
    "Information", "Utility", "Fun",
    "Music", "Social", "Rewards", "Last.fm", "Owner",
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
            if isinstance(c, Group) and c.commands:
                _walk(c)
            else:
                out.append(c)

    _walk(grp)
    return out


def _params(cmd: Command) -> list[str]:
    return [n.replace("_", ", ") for n in cmd.clean_params if n not in _SKIP]


def _aliases(cmd: Command) -> str:
    a = [x for x in cmd.aliases if x]
    return ", ".join(a) if a else "n/a"


def _usage(cmd: Command, prefix: str) -> str:
    base = f"{prefix}{cmd.qualified_name}"
    if cmd.usage:
        base = f"{base} {cmd.usage}"
    else:
        p = " ".join(f"({n})" for n in _params(cmd))
        if p:
            base = f"{base} {p}"
    ex = getattr(cmd, "example", None) or ""
    if ex:
        if not ex.startswith(prefix):
            ex = f"{prefix}{ex.lstrip(',')}"
        return f"```Syntax: {base}\nExample: {ex}```"
    return f"```Syntax: {base}```"


def _perm_info(cmd: Command) -> str:
    lines: list[str] = []
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
                    c = cell.cell_contents
                    if isinstance(c, dict):
                        for perm, on in c.items():
                            if on and perm != "send_messages" and perm not in seen:
                                seen.add(perm)
                                lines.append(f"> {perm.replace('_', ' ').title()}")
            except Exception:
                pass
            continue
        else:
            continue
        if label not in seen:
            seen.add(label)
            lines.append(f"> {label}")
    return "\n".join(lines) if lines else "n/a"


def _module(cmd: Command) -> str:
    return _category(cmd.cog).lower() if cmd.cog else "other"


def _footer(*, index: int, total: int, module: str) -> str:
    word = "entry" if total == 1 else "entries"
    return f"Page {index}/{total} ({total} {word}) · Module: {module}"


def _cmd_embed(cmd: Command, ctx: Context, *, index: int, total: int) -> Embed:
    prefix = getattr(ctx, "clean_prefix", None) or ctx.prefix or ";"
    if isinstance(prefix, list):
        prefix = prefix[0] if prefix else ";"
    title = ("Group: " if isinstance(cmd, Group) else "Command: ") + cmd.qualified_name
    desc = cmd.description or cmd.help or "no description"
    e = Embed(title=title, description=desc, color=ctx.bot.color)
    e.set_author(name=ctx.author.display_name, icon_url=ctx.author.display_avatar.url)
    e.add_field(name="**Aliases**", value=_aliases(cmd), inline=True)
    e.add_field(name="**Parameters**", value=", ".join(_params(cmd)) or "n/a", inline=True)
    e.add_field(name="**Permissions**", value=_perm_info(cmd), inline=True)
    e.add_field(name="**Usage**", value=_usage(cmd, str(prefix)), inline=False)
    e.set_footer(text=_footer(index=index, total=total, module=_module(cmd)))
    return e


class _Select(ui.Select):
    def __init__(self, view: HelpView) -> None:
        opts: list[SelectOption] = [
            SelectOption(label="Overview", value=_HOME, description="back to the main page"),
        ]
        labels = [l for l in _ORDER if l in view.cats]
        labels += sorted(set(view.cats) - set(labels))
        for label in labels[:24]:
            opts.append(SelectOption(
                label=label, value=label,
                description=_BLURBS.get(label, f"{label} commands")[:100],
            ))
        super().__init__(placeholder="pick a category ...", min_values=1, max_values=1, options=opts)
        self._v = view

    async def callback(self, inter: Interaction) -> None:
        e = self._v.home if self.values[0] == _HOME else self._v.cat_embed(self.values[0])
        await inter.response.edit_message(embed=e, view=self._v)


class HelpView(ui.View):
    """interactive category select help view"""

    def __init__(self, ctx: Context, cats: dict[str, list[Command]], home: Embed) -> None:
        super().__init__(timeout=180)
        self.ctx = ctx
        self.cats = cats
        self.home = home
        self.msg: discord.Message | None = None
        self.add_item(_Select(self))

    async def interaction_check(self, inter: Interaction) -> bool:
        if inter.user.id == self.ctx.author.id:
            return True
        await inter.response.send_message("not yours", ephemeral=True)
        return False

    def cat_embed(self, label: str) -> Embed:
        e = Embed(
            title=f"**{label} Commands**",
            description=_fmt_commands(self.cats[label]),
            color=self.ctx.bot.color,
        )
        e.set_author(name=self.ctx.author.display_name, icon_url=self.ctx.author.display_avatar.url)
        if self.ctx.bot.user:
            e.set_thumbnail(url=self.ctx.bot.user.display_avatar.url)
        return e

    async def on_timeout(self) -> None:
        for item in self.children:
            item.disabled = True
        if self.msg:
            with contextlib.suppress(discord.HTTPException):
                await self.msg.edit(view=self)


class BleedHelp:
    """help command handler with category select ui.
    registers as a prefix command on the bot.
    invoke via ctx or slash interaction"""

    def __init__(self) -> None:
        self.ctx: Context = None  # type: ignore[assignment]
        self._seen: dict[int, float] = {}

    def register(self, bot: commands.Bot) -> None:
        """attach help prefix command to bot"""
        @bot.command(name="help", aliases=["h", "commands"], description="view command help")
        async def _help(ctx: Context, *, command: str | None = None) -> None:
            await self.invoke(ctx, command)

    async def invoke(self, ctx: Context, query: str | None = None) -> None:
        """entry point for help from prefix or slash"""
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
        parts = query.strip().split()
        if not parts:
            return None

        def _match(name: str, c: Command) -> bool:
            return c.name.lower() == name or any(a.lower() == name for a in c.aliases)

        node: Command | None = None
        for c in bot.walk_commands():
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
        e.set_author(name=self.ctx.author.display_name, icon_url=self.ctx.author.display_avatar.url)
        if self.ctx.bot.user:
            e.set_thumbnail(url=self.ctx.bot.user.display_avatar.url)
        return e

    def _home_embed(self) -> Embed:
        p = self._prefix()
        e = self._base_embed()
        e.add_field(name=_BLANK, value=(
            f"> Use `{p}help <command>` for help on a specific command.\n"
            f"> Parameters in `(...)` are required, `[...]` are optional."
        ), inline=False)
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
        home = self._home_embed()
        view = HelpView(self.ctx, cats, home)
        view.msg = await self._send(home, view=view)

    async def _send_cmd(self, cmd: Command) -> None:
        e = _cmd_embed(cmd, self.ctx, index=1, total=1)
        await self._send(e)

    async def _send_group(self, grp: Group) -> None:
        targets = [grp] + _visible_subs(grp)
        total = len(targets)
        embeds = [_cmd_embed(t, self.ctx, index=i, total=total) for i, t in enumerate(targets, 1)]
        if total == 1:
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
            description=f"no command named **`{query}`**\nuse `{p}help` to browse all commands",
        )
        await self._send(e)


