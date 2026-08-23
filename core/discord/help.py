from __future__ import annotations

import contextlib
import inspect
import re
import time
from typing import TYPE_CHECKING, Any, Iterable, get_args, get_origin

import discord
from discord import Embed, Interaction, SelectOption, ui
from discord.ext import commands
from discord.ext.commands import Command, Group, Context as CommandsContext

from core.discord.package import Package
from core.discord.hybrid import command_display_name, family_root, family_help_name

from config import color, emojis, bot as bot_config
import asyncio
import aiohttp
from io import BytesIO
from colorthief import ColorThief




async def get_dominant_color(url: str, fallback: int = 0xE1D2DE) -> int:
    """Fetch image and return dominant color using colorthief."""
    if not url:
        return fallback
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url, timeout=8) as resp:
                if resp.status != 200:
                    return fallback
                data = await resp.read()

        def _extract():
            ct = ColorThief(BytesIO(data))
            r, g, b = ct.get_color(quality=1)

            if (r + g + b) < 80:
                r = min(r + 60, 255)
                g = min(g + 60, 255)
                b = min(b + 60, 255)
            return (r << 16) + (g << 8) + b

        return await asyncio.to_thread(_extract)
    except Exception:
        return fallback

async def get_bot_dominant_color(bot) -> int:
    if bot.user and bot.user.display_avatar:
        return await get_dominant_color(str(bot.user.display_avatar.url))
    return 0xE1D2DE



def _get_prefix(ctx: Context) -> str:
    """Get the current prefix for a context (guild/self/user prefix aware).

    Slash / hybrid interactions use ``/`` so Usage and Example lines match
    how the user invoked the command.
    """
    inv = getattr(ctx, "invoke_prefix", None)
    if callable(inv):
        pass
    if inv and not callable(inv):
        return str(inv)
    if getattr(ctx, "interaction", None) is not None:
        return "/"
    p = getattr(ctx, "clean_prefix", None) or getattr(ctx, "prefix", ",")
    if isinstance(p, (list, tuple)):
        p = p[0] if p else ","
    return str(p or ",")


if TYPE_CHECKING:
    from .ctx import Context
    from core.vain import Vain

_BLANK = "‎"
_HOME = "__home__"







_SKIP = frozenset({
    "self", "cls", "ctx", "context", "interaction", "inter",
    "args", "kwargs",
})
_PLACEHOLDER_DESCRIPTIONS = frozenset({"no description", "no description given"})
_USAGE_TOKENS = re.compile(r"\([^)]+\)|\[[^\]]+\]|<[^>]+>")
_FRAMEWORK_PARAM_NAMES = frozenset({
    "self", "cls", "ctx", "context", "interaction", "inter", "args", "kwargs",
})

_PERM_LABELS: dict[str, str] = {
    "moderate_members": "Warn Members",
    "manage_messages": "Manage Messages",
    "manage_channels": "Manage Channels",
    "manage_roles": "Manage Roles",
    "manage_guild": "Manage Guild",
    "manage_expressions": "Manage Expressions",
    "ban_members": "Ban Members",
    "kick_members": "Kick Members",
    "administrator": "Administrator",
}

_COG_MAP: dict[str, str] = {
    "Servers":       "Server",
    "Starboard":     "Server",
    "Autorole":      "Server",
    "Bump":          "Server",
    "BumpReminder":  "Server",
    "Reaction":      "Server",
    "Timers":        "Server",
    "Logs":          "Server",
    "Log":           "Server",
    "Tickets":       "Server",
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
    "Voicemaster":   "Server",
    "VoiceMaster":   "Server",
    "Antinuke":      "Security",
    "Antiraid":      "Security",
    "Moderation":    "Moderation",
    "Information":   "Information",
    "Fortnite":      "Information",
    "Snipe":         "Utility",
    "Utility":       "Utility",
    "AFK":           "Utility",
    "Afk":           "Utility",
    "Builders":      "Utility",
    "Away":          "Utility",
    "InviteTracker": "Utility",
    "Invitetracker": "Utility",
    "VanityCommands":"Server",
    "TagCommands":   "Server",
    "Vanity":        "Server",
    "Tag":           "Server",
    "Fun":         "Fun",
    "Roleplay":    "Roleplay",
    "Manipulation":"Fun",
    "Uwulock":     "Fun",
    
    "Misc":        "Fun",
    "Miscellaneous": "Miscellaneous",
    "Music":       "Music",
    "Soundcloud":  "Music",
    "Spotify":     "Music",
    "Socials":     "Social",
    "Roblox":      "Social",
    "Levels":      "Rewards",
    "Level":       "Rewards",
    "Leveling":    "Rewards",
    "Giveaway":    "Rewards",
    "Crypto":      "Crypto",
    "Lastfm":      "Last.fm",
    "Owner":       "Owner",
    "Jishaku":     "Owner",
}

_OWNER_COGS = frozenset({"Developer", "Jishaku", "Owner"})

_BLURBS: dict[str, str] = {
    "Server": "Prefixes, starboard, autorole, reactions, logs, tickets, voicemaster, and server setup.",
    "Security": "Antinuke, antiraid, and automod protection modules.",
    "Moderation": "Tools that help you moderate your server.",
    "Information": "User, guild, and bot lookups, avatars, banners, fortnite, and stats.",
    "Utility": "Snipes, reminders, AFK, invite tracker, and utility commands.",
    "Fun": "Games, memes, images, uwulock, and fun commands.",
    "Roleplay": "Hugs, kisses and other various roleplay commands.",
    "Miscellaneous": "Various useful commands that **don't** fit elsewhere.",
    "Music": "Queue, playback, Spotify, SoundCloud, and Lavalink controls.",
    "Social": "Twitch, YouTube, TikTok, Instagram, Roblox, and feed notifications.",
    "Rewards": "XP, levels, rank cards, giveaways, and reward systems.",
    "Crypto": "Cryptocurrency prices, charts, and market data.",
    "Last.fm": "Scrobbles, charts, covers, whoknows, and now playing.",
    "Owner": "Developer-only commands used to maintain vain.",
}

_ORDER: tuple[str, ...] = (
    "Server", "Security", "Moderation",
    "Information", "Utility", "Fun", "Roleplay", "Miscellaneous",
    "Music", "Social", "Rewards", "Crypto", "Last.fm", "Owner",
)


def _cog_key(cog: Package | None) -> str:
    if cog is None:
        return "Other"
    name = cog.qualified_name
    for sfx in ("Commands", "Events"):
        if name.endswith(sfx):
            return name[: -len(sfx)]
    return name


def _category(cog: Package | None) -> str:
    return _COG_MAP.get(_cog_key(cog), _cog_key(cog))


def is_owner_cog(cog: Package | None) -> bool:
    return cog is not None and (_cog_key(cog) in _OWNER_COGS or _category(cog) == "Owner")


def _hidden(cog: Package | None, *, owner: bool) -> bool:
    return is_owner_cog(cog) and not owner


def _cmd_hidden(cmd: Command, *, owner: bool) -> bool:
    return _hidden(cmd.cog, owner=owner)


def _fmt_commands(cmds: Iterable[Command], limit: int = 3900) -> str:
    names = sorted({c.qualified_name for c in cmds})
    if not names:
        return "*none*"
    parts: list[str] = []
    total = 0
    for i, n in enumerate(names):
        sep = 2 if parts else 0
        if total + sep + len(n) > limit:
            body = ", ".join(parts)
            return f"```\n{body}\n```\n*and {len(names) - i} more*"
        parts.append(n)
        total += sep + len(n)
    body = ", ".join(parts)
    return f"```\n{body}\n```"


def _visible_subs(grp: Group) -> list[Command]:
    """Walk a group tree and return leaf commands only (no intermediate groups)."""
    out: list[Command] = []

    def _walk(g: Group) -> None:
        for c in g.commands:
            if c.hidden:
                continue
            if isinstance(c, Group):
                
                if getattr(c, "invoke_without_command", False):
                    out.append(c)
                if c.commands:
                    _walk(c)
            else:
                out.append(c)

    _walk(grp)
    return out


def _is_invokable_group(cmd: Command) -> bool:
    """True when a Group can be run as a real command (not only a subcommand hub)."""
    return isinstance(cmd, Group) and bool(getattr(cmd, "invoke_without_command", False))


def _leaf_pages(root: Command) -> list[Command]:
    """Help pages for a group: main command first (if invokable), then leaves.

    Example: ``enablecommand`` → [enablecommand, enablecommand all, enablecommand list]
    so the parent action is documented, not only its subcommands.
    """
    if not isinstance(root, Group):
        return [root]

    pages: list[Command] = []
    
    if _is_invokable_group(root):
        pages.append(root)

    leaves = _visible_subs(root)
    seen = {id(p) for p in pages}
    for leaf in sorted(leaves, key=lambda c: command_display_name(c).lower()):
        if id(leaf) in seen:
            continue
        pages.append(leaf)
        seen.add(id(leaf))

    return pages or [root]


_LINKED_SUB_ALIASES = {
    "s": "statistics",
    "stats": "statistics",
    "lb": "leaderboard",
    "leader": "leaderboard",
}


def _linked_family_commands(
    bot: Vain,
    root_name: str,
    *,
    owner: bool,
) -> list[Command]:
    out: list[Command] = []
    for command in bot.walk_commands():
        if command.hidden or _cmd_hidden(command, owner=owner):
            continue
        if family_root(command) == root_name:
            out.append(command)
    return sorted(out, key=lambda c: command_display_name(c).lower())


def _find_linked_sub(root: Command, sub: str, bot: Vain) -> Command | None:
    sub_name = _LINKED_SUB_ALIASES.get(sub.lower(), sub.lower())
    for command in _linked_family_commands(bot, root.name, owner=False):
        help_name = family_help_name(command)
        if help_name:
            tail = help_name.lower().rsplit(" ", 1)[-1]
            if tail == sub_name or help_name.lower() == f"{root.name.lower()} {sub_name}":
                return command
        if command.name.lower() == sub_name or any(a.lower() == sub_name for a in command.aliases):
            return command
    return None


def _is_internal_param(name: str, param: Any = None) -> bool:
    """True for framework-only params that must never appear in help/syntax."""
    low = (name or "").lower().strip()
    if low in _SKIP:
        return True
    if low.startswith("_"):
        return True
    if param is None:
        return False
    ann = getattr(param, "annotation", inspect._empty)
    if ann is inspect._empty or ann is None:
        return False
    
    try:
        if ann in (CommandsContext, discord.Interaction):
            return True
        if inspect.isclass(ann) and issubclass(ann, (CommandsContext, discord.Interaction)):
            return True
    except TypeError:
        pass
    ann_name = (getattr(ann, "__name__", "") or str(ann)).lower()
    if any(tok in ann_name for tok in ("context", "interaction", "commands.context")):
        return True
    return False


def _param_items(cmd: Command) -> list[tuple[str, Any]]:
    """Return visible user-facing parameters, hiding ctx/interaction/self etc."""
    out: list[tuple[str, Any]] = []
    for name, param in cmd.clean_params.items():
        if _is_internal_param(name, param):
            continue
        out.append((name, param))
    return out


def _params(cmd: Command) -> list[str]:
    return [name.replace("_", " ") for name, _ in _param_items(cmd)]


def _aliases(cmd: Command) -> str:
    seen: set[str] = set()
    aliases: list[str] = []
    for alias in cmd.aliases:
        if not alias or alias in seen:
            continue
        seen.add(alias)
        aliases.append(alias)
    return ", ".join(aliases) if aliases else "n/a"


def _description(cmd: Command) -> str:
    def _norm(text: str) -> str:
        text = str(text or "").strip()
        while text.endswith("."):
            text = text[:-1].rstrip()
        text = text.replace("**", "")
        return text.lower() if text else ""

    if isinstance(cmd, Group):
        for value in (cmd.description, cmd.help, cmd.short_doc):
            text = _norm(value)
            if text:
                return text
        return f"use subcommands under {cmd.qualified_name}".lower()
    for value in (cmd.help, cmd.description, cmd.short_doc):
        text = _norm(value)
        if text:
            return text
    return f"run the {cmd.qualified_name} command".lower()


def _command_name_variants(cmd: Command) -> list[str]:
    """Primary name + aliases for a single command node (not full path)."""
    opts = [str(cmd.name or "").lower()]
    opts.extend(str(a).lower() for a in (cmd.aliases or []) if a)
    
    return list(dict.fromkeys(o for o in opts if o))


def _command_names(cmd: Command) -> tuple[str, ...]:
    """All invocable path strings for *cmd*, including parent-alias combos.

    So examples like ``,poj delete 10s`` match the command
    ``pingonjoin delete`` and are not rewritten to
    ``,pingonjoin delete poj delete 10s``.
    """
    from itertools import product

    names: list[str] = [
        command_display_name(cmd).lower(),
        cmd.qualified_name.lower(),
    ]
    
    names.extend(str(a).lower() for a in (cmd.aliases or []) if a)

    
    chain: list[Command] = []
    node: Command | None = cmd
    while node is not None:
        chain.append(node)
        node = getattr(node, "parent", None)
    chain.reverse()

    segment_opts = [_command_name_variants(c) for c in chain]
    if segment_opts and all(segment_opts):
        for combo in product(*segment_opts):
            names.append(" ".join(combo))

    return tuple(dict.fromkeys(n for n in names if n))


def _strip_prefix(value: str, prefix: str) -> str:
    cleaned = str(value or "").strip()
    if prefix and cleaned.startswith(prefix):
        cleaned = cleaned[len(prefix) :].strip()
    
    for fallback in (",", ";", "!", "."):
        if fallback and fallback != prefix and cleaned.startswith(fallback):
            cleaned = cleaned[len(fallback) :].strip()
            break
    return cleaned


def _cmd_example_attr(cmd: Command) -> str | None:
    """Read explicit example= from the command or original kwargs."""
    raw = getattr(cmd, "example", None)
    if raw is None:
        raw = (getattr(cmd, "__original_kwargs__", None) or {}).get("example")
    text = str(raw or "").strip()
    return text or None


def _has_user_params(cmd: Command) -> bool:
    """True when the command needs at least one user-facing argument."""
    return bool(_param_items(cmd))


def _requires_user_args(cmd: Command) -> bool:
    """True when at least one required user-facing parameter exists.

    Optional-only commands (and no-arg commands) do not need an Example line.
    """
    for _, param in _param_items(cmd):
        if getattr(param, "required", False):
            return True
    return False


def _annotation_labels(annotation: object) -> list[str]:
    if annotation is inspect._empty or annotation is None:
        return []
    if isinstance(annotation, commands.Greedy):
        return _annotation_labels(getattr(annotation, "converter", inspect._empty))
    origin = get_origin(annotation)
    if origin is not None:
        labels: list[str] = []
        for item in get_args(annotation):
            if item is type(None):
                continue
            for label in _annotation_labels(item):
                if label not in labels:
                    labels.append(label)
        return labels
    if annotation in (discord.Member, discord.User):
        return ["user"]
    if annotation is discord.Role:
        return ["role"]
    if annotation in (
        discord.TextChannel,
        discord.VoiceChannel,
        discord.StageChannel,
        discord.ForumChannel,
    ):
        return ["channel"]
    if annotation is discord.CategoryChannel:
        return ["category"]
    if annotation is discord.Thread:
        return ["thread"]
    if annotation is discord.Attachment:
        return ["attachment"]
    if annotation is discord.Message:
        return ["message"]
    if annotation in (discord.Emoji, discord.PartialEmoji):
        return ["emoji"]
    if annotation is discord.Guild:
        return ["server"]
    return []


def _usage_parameter_label(label: str, annotation: object = inspect._empty) -> str:
    raw = label.strip().strip("()[]<>")
    if not raw:
        return ""
    lowered = re.sub(r"\s+", " ", raw.replace("_", " ").strip().lower())
    choices = _annotation_labels(annotation)
    if choices:
        label_text = " or ".join(choices)
        if lowered in {"member", "user", "target", "role", "channel", "category", "thread", "message", "attachment", "emoji", "guild", "server"}:
            return label_text
        if lowered.endswith(" target"):
            return lowered.replace("target", label_text)
    replacements = {
        "guild": "server",
        "member/role": "role or user",
        "member or role": "role or user",
        "role/member": "role or user",
        "role or member": "role or user",
        "target": "user",
    }
    return replacements.get(lowered, lowered)


def _normalize_usage_and_example(
    raw_usage: str,
    *,
    prefix: str,
) -> tuple[str, str | None]:
    text = str(raw_usage or "").replace("```", "").strip()
    if not text:
        return "", None
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    if not lines:
        return "", None

    syntax = lines[0]
    for label in ("syntax:", "usage:"):
        if syntax.lower().startswith(label):
            syntax = syntax.split(":", 1)[1].strip()
            break

    example: str | None = None
    for line in lines[1:]:
        if line.lower().startswith("example:"):
            example = line.split(":", 1)[1].strip() or None
            break

    if example is None:
        match = re.search(r"example:\s*(.+)", syntax, re.IGNORECASE)
        if match:
            example = match.group(1).strip() or None
            syntax = syntax[: match.start()].strip()

    return _strip_prefix(syntax, prefix), _strip_prefix(example or "", prefix) or None


def _format_usage_token(label: str, *, required: bool) -> str:
    cleaned = label.strip()
    if not cleaned:
        return ""
    return f"<{cleaned}>" if required else f"[{cleaned}]"


def _derived_param_tokens(cmd: Command) -> list[str]:
    """Build usage tokens for user-facing parameters only (no command path)."""
    tokens: list[str] = []
    for name, param in _param_items(cmd):
        label = _usage_parameter_label(name, getattr(param, "annotation", inspect._empty))
        if not label:
            label = name.replace("_", " ")
        
        path_tail = command_display_name(cmd).lower().rsplit(" ", 1)[-1]
        if label.lower() == path_tail and not _annotation_labels(
            getattr(param, "annotation", inspect._empty)
        ):
            ann = getattr(param, "annotation", inspect._empty)
            ann_name = (getattr(ann, "__name__", "") or str(ann)).lower()
            if "embed" in ann_name or "script" in ann_name:
                label = "template"
            elif ann in (str, inspect._empty) or ann_name in {"str", "optional"}:
                label = "text"
        token = _format_usage_token(label, required=getattr(param, "required", False))
        if token:
            tokens.append(token)
    return tokens


def _derived_syntax(cmd: Command) -> str:
    suffix = " ".join(_derived_param_tokens(cmd))
    result = f"{command_display_name(cmd)} {suffix}".strip()
    return _strip_hidden_params_from_text(result)


def _looks_like_param_only(syntax: str) -> bool:
    """True when *syntax* is only argument tokens (no command path)."""
    text = (syntax or "").strip()
    if not text:
        return True
    
    return bool(re.match(r"^[\(\[<]", text))


def _syntax(cmd: Command, prefix: str) -> str:
    """Build ``{prefix}{qualified name} [params…]`` for help usage lines.

    Rules:
    - Prefer explicit ``usage=`` when present (params or full path).
    - Always show the real command path (``tag script``, never ``tag tag``).
    - Never strip bare path words like ``message`` / ``script`` / ``bot``.
    """
    usage, _ = _normalize_usage_and_example(str(cmd.usage or ""), prefix=str(prefix))
    usage = _strip_hidden_params_from_text(usage)
    name = command_display_name(cmd)

    if usage and _looks_like_param_only(usage):
        
        syntax = f"{name} {usage}".strip()
    elif usage:
        syntax = _collapse_duplicate_name(usage, cmd)
        lowered = syntax.lower()
        if not any(lowered == n or lowered.startswith(f"{n} ") for n in _command_names(cmd)):
            syntax = f"{name} {syntax}".strip()
            syntax = _collapse_duplicate_name(syntax, cmd)
    else:
        syntax = _derived_syntax(cmd)

    syntax = _strip_hidden_params_from_text(syntax)
    syntax = _collapse_duplicate_name(syntax, cmd)

    lowered = syntax.lower()
    if not any(lowered == n or lowered.startswith(f"{n} ") for n in _command_names(cmd)):
        syntax = f"{name} {syntax}".strip()
        syntax = _collapse_duplicate_name(syntax, cmd)

    if prefix and not syntax.startswith(prefix):
        syntax = f"{prefix}{syntax}"
    return syntax.strip()


def _strip_hidden_params_from_text(text: str) -> str:
    """Remove leaked framework param tokens from usage/example strings.

    Only strips **wrapped** parameter tokens like ``<ctx>``, ``[interaction]``,
    ``(self)``. Never strips bare path segments - words like ``message``,
    ``bot``, ``script`` are valid subcommand names
    (e.g. ``,tag script``, ``,invoke ban message``, ``,context bot``).
    """
    if not text:
        return text

    parts = text.split()
    cleaned = []
    for p in parts:
        stripped = p.strip("`.,:;")
        low = stripped.lower().strip("()[]<>")
        is_wrapped = (
            bool(stripped)
            and len(stripped) >= 2
            and stripped[0] in "<(["
            and stripped[-1] in ">)]"
        )
        
        if is_wrapped and low in _FRAMEWORK_PARAM_NAMES:
            continue
        cleaned.append(p)
    return " ".join(cleaned).strip()


def _token_to_example(token: str) -> str | None:
    raw = token.strip().strip("()[]<>")
    if not raw:
        return None
    
    raw = raw.lstrip(",;!.")
    if not raw:
        return None
    lowered = re.sub(r"\s+", " ", raw.replace("_", " ").strip().lower())
    if lowered.startswith("--"):
        return None
    if lowered in _FRAMEWORK_PARAM_NAMES:
        return None
    if "|" in lowered:
        lowered = lowered.split("|", 1)[0].strip()
    if " or " in lowered:
        lowered = lowered.split(" or ", 1)[0].strip()
    if lowered in {"args", "argument", "arguments", "value"}:
        return "example"
    if lowered.endswith(" id"):
        return "id"
    if lowered.endswith(" url"):
        return "url"
    if lowered.endswith(" reason"):
        return "reason"
    if lowered.endswith(" user") or lowered.endswith(" member"):
        return "user"
    if lowered.endswith(" channel"):
        return "channel"
    if lowered in {"channel", "user", "member", "role", "command", "module"}:
        return lowered if lowered != "member" else "user"
    return raw


def _strip_command_name(text: str, cmd: Command, prefix: str = "") -> str:
    """Remove prefix + command name from the start of a help string."""
    body = _strip_prefix(str(text or "").strip(), prefix)
    lowered = body.lower()
    for name in sorted(_command_names(cmd), key=len, reverse=True):
        if lowered == name:
            return ""
        if lowered.startswith(f"{name} "):
            return body[len(name) :].strip()
    return body


def _collapse_duplicate_name(text: str, cmd: Command) -> str:
    """Collapse 'cmd cmd rest' / alias-path doubles -> single path + rest."""
    raw = str(text or "").strip()
    
    for name in sorted(_command_names(cmd), key=len, reverse=True):
        nlow = name.lower()
        lowered = raw.lower()
        
        while lowered == f"{nlow} {nlow}" or lowered.startswith(f"{nlow} {nlow} "):
            raw = raw[len(name) :].lstrip()
            lowered = raw.lower()
    return raw


def _example_starts_with_command(raw: str, cmd: Command) -> bool:
    lowered = raw.lower().strip()
    for name in sorted(_command_names(cmd), key=len, reverse=True):
        if lowered == name or lowered.startswith(f"{name} "):
            return True
    return False


def _finalize_example(cmd: Command, raw: str, prefix: str) -> str | None:
    """Normalize an example string; return None when it is not useful."""
    if not raw:
        return None
    raw = _strip_hidden_params_from_text(raw)
    raw = _strip_prefix(raw, prefix)
    raw = _collapse_duplicate_name(raw, cmd)
    name = command_display_name(cmd)
    lowered = raw.lower()
    if not _example_starts_with_command(raw, cmd):
        
        
        raw = f"{name} {raw}".strip()
        raw = _collapse_duplicate_name(raw, cmd)
        lowered = raw.lower()

    if any(lowered == n for n in _command_names(cmd)):
        return None
    if prefix and not raw.startswith(prefix):
        raw = f"{prefix}{raw}"
    syntax = _syntax(cmd, prefix).strip()
    if raw.strip() == syntax:
        return None
    return raw.strip() or None


def _autogenerated_example(cmd: Command, syntax: str, prefix: str = "") -> str:
    
    if not _requires_user_args(cmd):
        return ""
    body = _strip_command_name(syntax, cmd, prefix=prefix)
    samples = [
        sample
        for sample in (_token_to_example(token) for token in _USAGE_TOKENS.findall(body))
        if sample
    ]
    if not samples and body:
        samples = [
            sample
            for sample in (_token_to_example(token) for token in body.split())
            if sample
        ]
    
    name_parts = set(command_display_name(cmd).lower().split())
    samples = [
        s for s in samples
        if s.lower() not in {"ctx", "interaction"} and s.lower() not in name_parts
    ]
    if not samples:
        return ""
    return f"{command_display_name(cmd)} {' '.join(samples)}"


def _example(cmd: Command, prefix: str) -> str | None:
    """Return a display example, or None when none should be shown.

    Prefer explicit ``example=``, then usage-line examples, then a light
    autogenerated sample when the command requires arguments.

    Commands that need no arguments (and have no useful explicit sample)
    only show Usage - never a duplicated bare command as Example.
    """
    raw = _cmd_example_attr(cmd)
    if raw:
        return _finalize_example(cmd, raw, str(prefix))

    _, usage_example = _normalize_usage_and_example(str(cmd.usage or ""), prefix=str(prefix))
    if usage_example:
        return _finalize_example(cmd, usage_example, str(prefix))

    
    if not _requires_user_args(cmd):
        return None

    auto = _autogenerated_example(cmd, _syntax(cmd, str(prefix)), prefix=str(prefix))
    if not auto:
        return None
    return _finalize_example(cmd, auto, str(prefix))


def _usage_params(cmd: Command, prefix: str) -> list[str]:
    usage, _ = _normalize_usage_and_example(str(cmd.usage or ""), prefix=str(prefix))
    if not usage:
        return []

    body = usage
    lowered = body.lower()
    for name in sorted(_command_names(cmd), key=len, reverse=True):
        if lowered == name:
            body = ""
            break
        if lowered.startswith(f"{name} "):
            body = body[len(name) :].strip()
            break

    params: list[str] = []
    for token in _USAGE_TOKENS.findall(body):
        label = token.strip().strip("()[]<>").replace("_", " ").strip().lower()
        if label and label not in _FRAMEWORK_PARAM_NAMES:
            params.append(label)
    return params


def _parameter_value(cmd: Command, prefix: str) -> str:
    if raw := _params(cmd):
        visible = [
            p for p in raw
            if p.lower().replace(" ", "") not in _FRAMEWORK_PARAM_NAMES
        ]
        if visible:
            return ", ".join(visible)
    if raw := _usage_params(cmd, prefix):
        visible = [
            p for p in raw
            if p.lower().replace(" ", "") not in _FRAMEWORK_PARAM_NAMES
        ]
        if visible:
            return ", ".join(visible)
    return "n/a"


def _usage_block(cmd: Command, prefix: str) -> str:
    block = [f"Usage: {_syntax(cmd, prefix)}"]
    if example := _example(cmd, prefix):
        block.append(f"Example: {example}")
    
    return "```ansi\n" + "\n".join(block) + "\n```"


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
            label = "Guild Owner"
        elif "has_permissions" in blob:
            try:
                for cell in (chk.__closure__ or []):
                    value = cell.cell_contents
                    if not isinstance(value, dict):
                        continue
                    if value.get("server_owner") or value.get("guild_owner"):
                        label = "Guild Owner"
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
        
        buckets = getattr(cmd, "_buckets", None)
        mapping = getattr(buckets, "_cooldown", None) if buckets is not None else None
        cooldown = mapping
    if cooldown is None:
        return None
    per = getattr(cooldown, "per", None)
    if per is None:
        return None
    try:
        per_f = float(per)
    except (TypeError, ValueError):
        return None
    if per_f.is_integer():
        label = f"{int(per_f)} seconds"
    else:
        label = f"{per_f:g} seconds"
    buckets = getattr(cmd, "_buckets", None)
    bucket_type = getattr(buckets, "type", None) if buckets is not None else None
    if bucket_type == commands.BucketType.guild:
        label += " per guild"
    elif bucket_type == commands.BucketType.user:
        label += " per user"
    return label


def _information(cmd: Command) -> dict[str, str]:
    info: dict[str, str] = {}
    raw_info = getattr(cmd, "information", {}) or {}
    for key, value in dict(raw_info).items():
        info[str(key)] = str(value)
    if cooldown := _cooldown_label(cmd):
        info["cooldown"] = cooldown
    if cmd.qualified_name.startswith("antinuke"):
        info["permissions"] = "Guild Owner"
    elif permissions := _permission_label(cmd):
        info["permissions"] = permissions
    return info


def _information_value(cmd: Command) -> str:
    info = _information(cmd)
    if not info:
        return "n/a"
    warning_emoji = emojis.warn
    cooldown_emoji = emojis.cooldown
    emoji_map = {
        "cooldown": cooldown_emoji,
        "permissions": warning_emoji,
    }
    return "\n".join(f"{emoji_map.get(key, warning_emoji)} {value}" for key, value in info.items())


def _module(cmd: Command) -> str:
    if cmd.cog:
        return _category(cmd.cog).lower()
    return "n/a"


def _detail_embed(
    cmd: Command,
    ctx: Context,
    *,
    group_title: bool = False,
    page_index: int | None = None,
    total_pages: int | None = None,
) -> Embed:
    prefix = _get_prefix(ctx)
    is_group = group_title or isinstance(cmd, Group)
    title = ("Group: " if is_group else "Command: ") + command_display_name(cmd)
    desc = _description(cmd)

    
    parts = []
    if desc:
        parts.append(desc)
    aliases = _aliases(cmd)
    if aliases and aliases != "n/a":
        parts.append(f"-# Aliases: {aliases}")
    params = _parameter_value(cmd, str(prefix))
    if params and params != "n/a":
        parts.append(f"-# Parameters: {params}")
    info = _information(cmd)
    if info:
        info_lines = []
        for k, v in info.items():
            info_lines.append(f"{k}: {v}")
        if info_lines:
            parts.append("-# " + " | ".join(info_lines))

    usage = _usage_block(cmd, str(prefix))
    if usage:
        parts.append(usage)

    e = Embed(
        title=title,
        description="\n".join(parts) if parts else desc,
    )
    
    display_name = getattr(ctx.author, "display_name", ctx.author.name)
    e.set_author(name=f"{display_name}", icon_url=ctx.author.display_avatar.url)

    module = _module(cmd)
    footer_bits = []
    if total_pages and page_index and total_pages > 1:
        footer_bits.append(f"Page {page_index}/{total_pages}")
    footer_bits.append(f"Module: {module}")
    e.set_footer(text=" • ".join(footer_bits))
    return e



async def _fetch_custom_aliases(ctx: Context, cmd: Command) -> tuple[list[str], list[str]]:
    """Guild + personal aliases that point at this command."""
    guild_aliases: list[str] = []
    self_aliases: list[str] = []
    qn = (cmd.qualified_name or cmd.name or "").lower()
    names = {qn}
    names.update(a.lower() for a in (cmd.aliases or []))
    db = getattr(getattr(ctx, "bot", None), "db", None)
    if db is None:
        return guild_aliases, self_aliases
    try:
        if ctx.guild is not None:
            rows = await db.fetch(
                "SELECT alias, command_name FROM aliases WHERE guild_id = $1",
                ctx.guild.id,
            )
            for r in rows or []:
                alias = str(r["alias"] if hasattr(r, "keys") else r[0]).strip().rstrip(",")
                target = (r["command_name"] if hasattr(r, "keys") else r[1] or "").lower().strip()
                if not alias:
                    continue
                if target in names:
                    if alias not in guild_aliases:
                        guild_aliases.append(alias)
        rows = await db.fetch(
            "SELECT name, invoke, command FROM selfaliases WHERE user_id = $1",
            ctx.author.id,
        )
        for r in rows or []:
            name = r["name"] if hasattr(r, "keys") else r[0]
            inv = (r["invoke"] if hasattr(r, "keys") else r[1] or "").lower()
            cmdn = (r["command"] if hasattr(r, "keys") else (r[2] if len(r) > 2 else "") or "").lower()
            if cmdn in names or inv in names:
                self_aliases.append(str(name))
    except Exception:
        pass
    return guild_aliases, self_aliases


def _detail_text(
    cmd: Command,
    ctx: Context,
    *,
    group_title: bool = False,
    page_info: str | None = None,
    **kwargs,
) -> str:
    """Minimal command/group detail text matching inspiration layout."""
    prefix = _get_prefix(ctx)
    
    is_grp = bool(group_title and isinstance(cmd, Group))
    name = command_display_name(cmd)
    desc = _description(cmd) or "no description provided"
    aliases = _aliases(cmd)
    if aliases == "n/a":
        aliases = "None"
    perm = _information(cmd).get("permissions") or "None"
    syntax = _strip_hidden_params_from_text(_syntax(cmd, prefix))
    ex = _example(cmd, prefix)
    if ex:
        ex = _strip_hidden_params_from_text(ex)

    kind_label = "group" if is_grp else "command"
    lines = [
        f"{emojis.approve} **{kind_label}:** `{name}`",
        "",
        f"> **{desc}**",
    ]

    alias_lines: list[str] = []
    guild_aliases = kwargs.get("guild_aliases") or []
    self_aliases = kwargs.get("self_aliases") or []
    alias_lines.append(f"> -# **aliases:** {aliases}")
    if guild_aliases:
        alias_lines.append(f"> -# **guild aliases:** {', '.join(guild_aliases)}")
    if self_aliases:
        alias_lines.append(f"> -# **your aliases:** {', '.join(self_aliases)}")
    alias_lines.append("> ")
    alias_lines.append(f"> -# **command permissions:** {perm}")
    lines.extend(alias_lines)

    usage_lines: list[str] = []
    usage_lines.append(f"-# **command usage**\n```{syntax}```")
    if ex and ex.strip() and ex.strip() != syntax.strip():
        usage_lines.append(f"-# **command example**\n```{ex}```")
    lines.extend(usage_lines)

    module = _module(cmd)
    if module != "n/a":
        module_label = next((k for k in _ORDER if k.lower() == module), module.title())
        footer = f"-# **category:** {module_label}"
    else:
        footer = "-# **category:** N/A"
    if page_info:
        footer += f" · {page_info}"
    lines.append(footer)
    return "\n".join(lines)


def _build_help_detail_container(
    cmd: Command,
    ctx: Context,
    *,
    group_title: bool = False,
    page_info: str | None = None,
    **kwargs,
) -> ui.Container:
    """Build a C2 container for command/group help with proper sectioning."""
    from config import color as _c

    prefix = _get_prefix(ctx)
    is_grp = bool(group_title and isinstance(cmd, Group))
    name = command_display_name(cmd)
    desc = _description(cmd) or "no description provided"
    aliases = _aliases(cmd)
    if aliases == "n/a":
        aliases = "None"
    perm = _information(cmd).get("permissions") or "None"
    syntax = _strip_hidden_params_from_text(_syntax(cmd, prefix))
    ex = _example(cmd, prefix)
    if ex:
        ex = _strip_hidden_params_from_text(ex)

    kind_label = "group" if is_grp else "command"
    container = ui.Container()
    for attr in ("accent_color", "accent_colour"):
        if hasattr(container, attr):
            with contextlib.suppress(Exception):
                setattr(container, attr, None)

    container.add_item(
        ui.TextDisplay(
            f"{emojis.approve} **{kind_label}:** `{name}`\n\n> **{desc}**"
        )
    )

    container.add_item(
        ui.Separator(visible=True, spacing=discord.SeparatorSpacing.small)
    )

    guild_aliases = kwargs.get("guild_aliases") or []
    self_aliases = kwargs.get("self_aliases") or []
    alias_parts = [f"> -# **aliases:** {aliases}"]
    if guild_aliases:
        alias_parts.append(f"> -# **guild aliases:** {', '.join(guild_aliases)}")
    if self_aliases:
        alias_parts.append(f"> -# **your aliases:** {', '.join(self_aliases)}")
    alias_parts.append(f"> -# **command permissions:** {perm}")
    container.add_item(ui.TextDisplay("\n".join(alias_parts)))

    container.add_item(
        ui.Separator(visible=True, spacing=discord.SeparatorSpacing.small)
    )

    usage_parts = [f"-# **command usage**: `{syntax}`"]
    if ex and ex.strip() and ex.strip() != syntax.strip():
        usage_parts.append(f"-# **command example:** `{ex}`")
    container.add_item(ui.TextDisplay("\n".join(usage_parts)))

    module = _module(cmd)
    if module != "n/a":
        module_label = next((k for k in _ORDER if k.lower() == module), module.title())
        footer_text = f"-# **category:** {module_label}"
    else:
        footer_text = "-# **category:** N/A"
    if page_info:
        footer_text += f" · {page_info}"
    container.add_item(
        ui.Separator(visible=True, spacing=discord.SeparatorSpacing.small)
    )
    container.add_item(ui.TextDisplay(footer_text))

    return container


async def _accent_color(bot: Vain) -> int | None:
    """Help menus are colorless C2 containers - no accent strip."""
    return None




def _home_text(ctx: Context) -> str:
    """Minimal home help page."""
    p = _get_prefix(ctx)
    bot = ctx.bot
    bot_name = bot.user.display_name if bot.user else "Vain"
    website = getattr(bot_config, "website", "https://vain.bot")
    support = getattr(bot_config, "support", "https://discord.gg/vains")
    return "\n".join(
        [
            f"### [{bot_name}]({website})",
            f"> Use `{p}help <command>` for help on a specific command.",
            f"> Parameters in `<...>` are required, `[...]` are optional.",
            "",
            f"> Join the [support server]({support}) for more support.",
        ]
    )


def _category_text(ctx: Context, label: str, cmds: list[Command]) -> str:
    prefix = _get_prefix(ctx)
    blurb = _BLURBS.get(label, f"{label} commands.")
    names = sorted({command_display_name(c) for c in cmds}, key=str.lower)
    body = ", ".join(f"{n}" for n in names) if names else "none"
    return "\n".join(
        [
            f"### {label}",
            f"> {blurb}",
            "",
            f"**Commands:**\n```\n{body}\n```",
            f"-# Use `{prefix}help <command>` for details.",
        ]
    )


def _brief_embed(cmd: Command, ctx: Context) -> Embed:
    prefix = _get_prefix(ctx)
    e = Embed(
        title=("Group Command: " if isinstance(cmd, Group) else "Command: ") + command_display_name(cmd),
        description=_description(cmd),
    )
    e.set_author(name=ctx.author.display_name, icon_url=ctx.author.display_avatar.url)
    e.add_field(name=_BLANK, value=_usage_block(cmd, str(prefix)), inline=False)
    return e


def _category_options(cats: dict[str, list[Command]]) -> list[SelectOption]:
    labels = [label for label in _ORDER if label in cats]
    labels += sorted(set(cats) - set(labels))
    opts = [
        SelectOption(
            label="Home",
            value=_HOME,
            description="Return to the main help menu.",
        )
    ]
    for label in labels[:24]:
        opts.append(
            SelectOption(
                label=label,
                value=label,
                description=(_BLURBS.get(label, f"{label} commands.")[:100]),
            )
        )
    return opts


class HelpMenu(ui.LayoutView):
    """Home + category browser using Components V2 LayoutView (select inside container)."""

    def __init__(self, ctx: Context, cats: dict[str, list[Command]], accent: int | None = None) -> None:
        super().__init__(timeout=300)
        self.ctx = ctx
        self.cats = cats
        self.accent = accent
        self.msg: discord.Message | None = None

        self.body = ui.TextDisplay(_home_text(ctx))
        self.container = ui.Container()
        self.container.add_item(self.body)

        self.select_row = ui.ActionRow()
        self.select = ui.Select(
            placeholder="Select a category...",
            min_values=1,
            max_values=1,
            options=_category_options(cats),
        )
        self.select.callback = self._on_select
        self.select_row.add_item(self.select)
        self.container.add_item(self.select_row)
        self.add_item(self.container)

    async def interaction_check(self, inter: Interaction) -> bool:
        if inter.user.id == self.ctx.author.id:
            return True
        await inter.response.send_message(
            embed=Embed(
                color=color.warn,
                description=(
                    f"{emojis.warn} {inter.user.mention}: "
                    f"Only {self.ctx.author.mention} can use this help menu!"
                ),
            ),
            ephemeral=True,
        )
        return False

    async def _on_select(self, inter: Interaction) -> None:
        value = self.select.values[0]
        if value == _HOME:
            self.body.content = _home_text(self.ctx)
        else:
            self.body.content = _category_text(self.ctx, value, self.cats.get(value, []))
        await inter.response.edit_message(view=self)

    async def on_timeout(self) -> None:

        if self.msg is None:
            return
        body = ui.TextDisplay(self.body.content)
        container = ui.Container()
        container.add_item(body)
        bare = ui.LayoutView(timeout=None)
        bare.add_item(container)
        with contextlib.suppress(discord.HTTPException):
            await self.msg.edit(view=bare)
        self.stop()

    async def start(self) -> discord.Message:
        kw: dict[str, Any] = {"view": self}
        if self.ctx.message and not self.ctx.interaction:
            kw["reference"] = self.ctx.message.to_reference(fail_if_not_exists=False)
            kw["allowed_mentions"] = discord.AllowedMentions.none()
        self.msg = await self.ctx.channel.send(**kw)
        return self.msg


class GroupHelpMenu(ui.LayoutView):
    """Group/family help - forward · delete · backward · search."""

    def __init__(
        self,
        ctx: Context,
        pages: list[Command],
        accent: int | None = None,
    ) -> None:
        super().__init__(timeout=300)
        self.ctx = ctx
        self.pages = pages or []
        self.index = 0
        self.accent = accent
        self.msg: discord.Message | None = None
        self._rebuild()

    def _page_info(self) -> str | None:
        if len(self.pages) <= 1:
            return None
        return f"page {self.index + 1} out of {len(self.pages)}"

    def _page_text(self) -> str:
        cmd = self.pages[self.index]
        is_shell = (
            isinstance(cmd, Group)
            and not getattr(cmd, "invoke_without_command", False)
        )
        cache = getattr(self, "_alias_cache", {}) or {}
        guild_a, self_a = cache.get(id(cmd), ([], []))
        return _detail_text(
            cmd,
            self.ctx,
            group_title=is_shell,
            page_info=self._page_info(),
            guild_aliases=guild_a,
            self_aliases=self_a,
        )

    def _cmd_label(self, cmd: Command) -> str:
        return command_display_name(cmd)

    def _cmd_desc(self, cmd: Command) -> str:
        doc = (cmd.short_doc or cmd.description or cmd.help or "…").strip()
        return (doc.splitlines()[0] if doc else "…")[:100]

    def _rebuild(self) -> None:
        from core.discord.views.paginate import build_pager_row

        self.clear_items()
        cache = getattr(self, "_alias_cache", {}) or {}
        guild_a, self_a = cache.get(id(self.pages[self.index]), ([], []))

        container = _build_help_detail_container(
            self.pages[self.index],
            self.ctx,
            group_title=isinstance(self.pages[self.index], Group)
            and not getattr(self.pages[self.index], "invoke_without_command", False),
            page_info=self._page_info(),
            guild_aliases=guild_a,
            self_aliases=self_a,
        )

        if len(self.pages) > 1:
            container.add_item(ui.Separator(visible=True))
            container.add_item(
                build_pager_row(
                    parent=self,
                    show_search=True,
                )
            )
        self.add_item(container)

    async def interaction_check(self, inter: Interaction) -> bool:
        if inter.user.id == self.ctx.author.id:
            return True
        await inter.response.send_message(
            embed=Embed(
                color=color.warn,
                description=(
                    f"{emojis.warn} {inter.user.mention}: "
                    f"Only {self.ctx.author.mention} can use this help menu!"
                ),
            ),
            ephemeral=True,
        )
        return False

    async def _prev(self, inter: Interaction) -> None:
        if not self.pages:
            if not inter.response.is_done():
                await inter.response.defer()
            return
        self.index = (self.index - 1) % len(self.pages)
        self._rebuild()
        await inter.response.edit_message(view=self)

    async def _next(self, inter: Interaction) -> None:
        if not self.pages:
            if not inter.response.is_done():
                await inter.response.defer()
            return
        self.index = (self.index + 1) % len(self.pages)
        self._rebuild()
        await inter.response.edit_message(view=self)

    async def _goto(self, inter: Interaction) -> None:
        from core.discord.views.paginate import _warning_embed

        total = len(self.pages)
        options: list[SelectOption] = []
        for i, cmd in enumerate(self.pages):
            options.append(
                SelectOption(
                    label=self._cmd_label(cmd)[:100],
                    value=str(i),
                    description=self._cmd_desc(cmd),
                )
            )

        async def on_pick(interaction: Interaction, value: str) -> None:
            try:
                idx = int(value)
            except ValueError:
                idx = 0
            if 0 <= idx < len(self.pages):
                self.index = idx
            self._rebuild()
            
            if not interaction.response.is_done():
                await interaction.response.defer()
            if self.msg is not None:
                with contextlib.suppress(discord.HTTPException):
                    await self.msg.edit(view=self)

        view = ui.LayoutView(timeout=self.timeout or 300)
        chunks = [options[i:i + 25] for i in range(0, len(options), 25)]
        for idx, chunk in enumerate(chunks):
            row = ui.ActionRow()
            start_num = idx * 25 + 1
            end_num = min((idx + 1) * 25, len(options))
            ph = f"select a command to jump to ({start_num}-{end_num})..."
            select = ui.Select(
                placeholder=ph,
                min_values=1,
                max_values=1,
                options=chunk,
            )

            async def _cb(interaction: Interaction, _sel: ui.Select = select) -> None:
                if interaction.user.id != self.ctx.author.id:
                    await interaction.response.send_message(
                        embed=_warning_embed(
                            interaction.user,
                            "these controls aren't for you.",
                        ),
                        ephemeral=True,
                    )
                    return
                value = _sel.values[0]
                await on_pick(interaction, value)

            select.callback = _cb
            row.add_item(select)
            view.add_item(row)

        await inter.response.send_message(view=view, ephemeral=True)

    async def _cancel(self, inter: Interaction) -> None:
        await inter.response.defer()
        if inter.message:
            with contextlib.suppress(discord.HTTPException):
                await inter.message.delete()
        
        if self.ctx.message and not self.ctx.interaction:
            with contextlib.suppress(discord.HTTPException):
                await self.ctx.message.delete()
        self.stop()

    async def on_timeout(self) -> None:
        if self.msg is None:
            return
        body = ui.TextDisplay(self._page_text())
        container = ui.Container()
        container.add_item(body)
        bare = ui.LayoutView(timeout=None)
        bare.add_item(container)
        with contextlib.suppress(discord.HTTPException):
            await self.msg.edit(view=bare)

    async def start(self) -> discord.Message:
        self._alias_cache = {}
        for cmd in self.pages:
            try:
                self._alias_cache[id(cmd)] = await _fetch_custom_aliases(self.ctx, cmd)
            except Exception:
                self._alias_cache[id(cmd)] = ([], [])
        self._rebuild()
        kw: dict[str, Any] = {"view": self}
        if self.ctx.message and not self.ctx.interaction:
            kw["reference"] = self.ctx.message.to_reference(fail_if_not_exists=False)
            kw["allowed_mentions"] = discord.AllowedMentions.none()
        self.msg = await self.ctx.channel.send(**kw)
        return self.msg


class CommandHelpMenu(ui.LayoutView):
    """Single non-group command help page (no pagination)."""

    def __init__(self, ctx: Context, cmd: Command, accent: int | None = None) -> None:
        super().__init__(timeout=180)
        self.ctx = ctx
        self.cmd = cmd
        self.msg: discord.Message | None = None
        container = _build_help_detail_container(cmd, ctx, group_title=False)
        self.add_item(container)

    async def start(self) -> discord.Message:
        guild_a, self_a = await _fetch_custom_aliases(self.ctx, self.cmd)
        if guild_a or self_a:
            self.clear_items()
            container = _build_help_detail_container(
                self.cmd,
                self.ctx,
                group_title=False,
                guild_aliases=guild_a,
                self_aliases=self_a,
            )
            self.add_item(container)
        kw: dict[str, Any] = {"view": self}
        if self.ctx.message and not self.ctx.interaction:
            kw["reference"] = self.ctx.message.to_reference(fail_if_not_exists=False)
            kw["allowed_mentions"] = discord.AllowedMentions.none()
        self.msg = await self.ctx.channel.send(**kw)
        return self.msg


class VainHelp(commands.HelpCommand):
    """Custom help UI registered as the bot's HelpCommand."""

    def __init__(self, **options: Any) -> None:
        super().__init__(
            command_attrs={
                "name": "help",
                "aliases": ["h", "commands"],
                "description": "Browse command help, categories, usage and examples.",
                "help": "Browse command help, categories, usage and examples.",
            },
            verify_checks=False,
            **options,
        )
        self._seen: dict[int, float] = {}

    def register(self, bot: Vain) -> None:
        """Legacy hook - bot already owns this instance as help_command."""
        bot._vain_help = self  # type: ignore[attr-defined]

    async def command_callback(
        self,
        ctx: CommandsContext,
        /,
        *,
        command: str | None = None,
    ) -> None:
        """Entry point for `,help` / `,h` / `,commands`."""
        await self.invoke(ctx, command)  # type: ignore[arg-type]

    async def send_bot_help(self, mapping: Any) -> None:
        await self.invoke(self.context, None)  # type: ignore[arg-type]

    async def send_command_help(self, command: Command) -> None:
        await self._send_cmd(self.context, command)  # type: ignore[arg-type]

    async def send_group_help(self, group: Group) -> None:
        owner = self.context.author.id in getattr(self.context.bot, "owners", ())
        await self._send_group(
            self.context,  # type: ignore[arg-type]
            group,
            targets=self._family_targets(self.context.bot, group, owner=owner),  # type: ignore[arg-type]
        )

    async def send_cog_help(self, cog: commands.Cog) -> None:
        await self._send_cog(self.context, cog)  # type: ignore[arg-type]

    async def send_error_message(self, error: str) -> None:
        destination = self.get_destination()
        with contextlib.suppress(Exception):
            await destination.send(error)

    async def invoke(self, ctx: Context, query: str | None = None) -> None:
        bot = ctx.bot
        owner = ctx.author.id in bot.owners

        if query is None:
            await self._send_home(ctx, bot, owner)
            return

        cmd = self._find(bot, query)
        if cmd is None:
            resolved = await self._resolve_alias_query(ctx, query)
            if resolved:
                cmd = self._find(bot, resolved)
        if cmd is None or _cmd_hidden(cmd, owner=owner):
            await self._not_found(ctx, query)
            return
        family = self._family_targets(bot, cmd, owner=owner)
        if isinstance(cmd, Group) or len(family) > 1:
            await self._send_group(ctx, cmd, targets=family)
        else:
            await self._send_cmd(ctx, cmd)

    async def _resolve_alias_query(self, ctx: Context, query: str) -> str | None:
        """Map guild/self alias names to the real command path for help."""
        q = (query or "").strip().lower().rstrip(",")
        if not q or not getattr(ctx, "bot", None):
            return None
        db = getattr(ctx.bot, "db", None)
        if db is None:
            return None
        root = q.split()[0]
        try:
            row = await db.fetchrow(
                "SELECT invoke FROM selfaliases WHERE user_id = $1 AND name = $2",
                ctx.author.id,
                root,
            )
            if row:
                inv = row["invoke"] if hasattr(row, "keys") else row[0]
                rest = q[len(root) :].lstrip()
                return f"{inv} {rest}".strip() if rest else str(inv)
            if ctx.guild is not None:
                row = await db.fetchrow(
                    """
                    SELECT command_name FROM aliases
                    WHERE guild_id = $1 AND lower(trim(both ',' from alias)) = $2
                    """,
                    ctx.guild.id,
                    root,
                )
                if row:
                    inv = row["command_name"] if hasattr(row, "keys") else row[0]
                    rest = q[len(root) :].lstrip()
                    return f"{inv} {rest}".strip() if rest else str(inv)
        except Exception:
            return None
        return None

    def _find(self, bot: Vain, query: str) -> Command | None:
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
            if isinstance(node, Group):
                found = next((s for s in node.commands if _match(part.lower(), s)), None)
                if not found:
                    return None
                node = found
            else:
                linked = _find_linked_sub(node, part, bot)
                if linked is None:
                    return None
                node = linked
        return node

    def _build_cats(self, bot: Vain, owner: bool) -> dict[str, list[Command]]:
        cats: dict[str, list[Command]] = {}
        seen: set[int] = set()
        for cmd in bot.walk_commands():
            if cmd.parent is not None:
                continue
            if cmd.hidden or _cmd_hidden(cmd, owner=owner):
                continue
            if family_root(cmd) is not None:
                continue
            ident = id(cmd)
            if ident in seen:
                continue
            seen.add(ident)
            cats.setdefault(_category(cmd.cog), []).append(cmd)
        return cats

    def _dedup(self, ctx: Context) -> bool:
        if not getattr(ctx, "message", None):
            return False
        now = time.monotonic()
        mid = ctx.message.id
        if now - self._seen.get(mid, 0) < 3.0:
            return True
        self._seen[mid] = now
        if len(self._seen) > 512:
            self._seen = {k: v for k, v in self._seen.items() if now - v < 3.0}
        return False

    async def _send(self, ctx: Context, embed: Embed, *, view: ui.View | None = None) -> discord.Message:
        
        embed.timestamp = None
        kw: dict[str, Any] = {}
        if ctx.message and not ctx.interaction:
            kw["reference"] = ctx.message.to_reference(fail_if_not_exists=False)
            kw["allowed_mentions"] = discord.AllowedMentions.none()
        return await ctx.send(embed=embed, view=view, **kw)

    async def _send_layout(self, ctx: Context, view: ui.LayoutView) -> discord.Message:
        kw: dict[str, Any] = {"view": view}
        if ctx.message and not ctx.interaction:
            kw["reference"] = ctx.message.to_reference(fail_if_not_exists=False)
            kw["allowed_mentions"] = discord.AllowedMentions.none()
        return await ctx.channel.send(**kw)

    async def _send_home(self, ctx: Context, bot: Vain, owner: bool) -> None:
        if self._dedup(ctx):
            return
        cats = self._build_cats(bot, owner)
        accent = await _accent_color(bot)
        menu = HelpMenu(ctx, cats, accent)
        try:
            menu.msg = await menu.start()
        except Exception:
            e = Embed(description=_home_text(ctx).replace("### ", ""))
            if bot.user:
                e.set_author(name=bot.user.display_name, icon_url=bot.user.display_avatar.url)
            await self._send(ctx, e)

    async def send_brief(self, ctx: Context, cmd: Command) -> discord.Message:
        """Used by ctx.send_help - always show full group pagination when applicable."""
        owner = ctx.author.id in ctx.bot.owners
        if isinstance(cmd, Group):
            await self._send_group(ctx, cmd, targets=self._family_targets(ctx.bot, cmd, owner=owner))
            return None  # type: ignore[return-value]
        await self._send_cmd(ctx, cmd)
        return None  # type: ignore[return-value]

    async def _send_cmd(self, ctx: Context, cmd: Command) -> None:
        accent = await _accent_color(ctx.bot)
        try:
            menu = CommandHelpMenu(ctx, cmd, accent)
            menu.msg = await menu.start()
        except Exception:
            await self._send(ctx, _detail_embed(cmd, ctx))

    def _family_targets(
        self,
        bot: Vain,
        root: Command,
        *,
        owner: bool,
    ) -> list[Command]:
        linked_root = family_root(root)
        if linked_root:
            parent = bot.get_command(linked_root)
            if parent is not None:
                root = parent

        
        if isinstance(root, Group):
            return _leaf_pages(root)

        linked = _linked_family_commands(bot, root.name, owner=owner)
        if linked:
            return [root] + [c for c in linked if c is not root]

        prefix = f"{root.qualified_name.lower()} "
        seen = {root.qualified_name}
        family = [root]
        candidates = root.cog.get_commands() if root.cog is not None else list(bot.walk_commands())
        for command in candidates:
            if command.qualified_name in seen:
                continue
            if command.hidden or _cmd_hidden(command, owner=owner):
                continue
            if isinstance(command, Group):
                continue
            if command.qualified_name.lower().startswith(prefix):
                seen.add(command.qualified_name)
                family.append(command)
        return family

    async def _send_group(self, ctx: Context, grp: Command, *, targets: list[Command] | None = None) -> None:
        owner = ctx.author.id in ctx.bot.owners
        pages = targets or self._family_targets(ctx.bot, grp, owner=owner)

        if isinstance(grp, Group):
            if not targets:
                pages = _leaf_pages(grp)
            else:
                
                kept: list[Command] = []
                for c in pages:
                    if isinstance(c, Group) and getattr(c, "commands", None):
                        if _is_invokable_group(c):
                            kept.append(c)
                        continue
                    kept.append(c)
                pages = kept or _leaf_pages(grp)
            if not pages:
                pages = _leaf_pages(grp)

        if not pages:
            await self._send_cmd(ctx, grp)
            return

        
        if len(pages) == 1 and not isinstance(pages[0], Group):
            await self._send_cmd(ctx, pages[0])
            return
        
        if len(pages) == 1:
            await self._send_cmd(ctx, pages[0])
            return

        accent = await _accent_color(ctx.bot)
        try:
            menu = GroupHelpMenu(ctx, pages, accent)
            menu.msg = await menu.start()
        except Exception:
            await self._send_cmd(ctx, pages[0])

    async def _send_cog(self, ctx: Context, cog: Package) -> None:
        cmds = [c for c in cog.get_commands() if not c.hidden]
        label = _category(cog)
        accent = await _accent_color(ctx.bot)
        text = _category_text(ctx, label, cmds)
        view = ui.LayoutView(timeout=180)
        container = ui.Container()
        container.add_item(ui.TextDisplay(text))
        view.add_item(container)
        try:
            await self._send_layout(ctx, view)
        except Exception:
            e = Embed(title=f"**{label} Commands**", description=_fmt_commands(cmds))
            await self._send(ctx, e)

    async def _not_found(self, ctx: Context, query: str) -> None:
        await ctx.warn(f"Command `{query}` does **not** exist")
