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

from core.managers.values import color, emojis, bot as bot_config
from core.tools.aesthetic import get_bot_dominant_color


def _get_prefix(ctx: Context) -> str:
    """Get the current prefix for a context (guild/self/user prefix aware)."""
    p = getattr(ctx, "clean_prefix", None) or getattr(ctx, "prefix", ",")
    if isinstance(p, list):
        p = p[0] if p else ","
    return p


if TYPE_CHECKING:
    from .ctx import Context
    from core.vain import Vain

_BLANK = "‎"
_HOME = "__home__"
# Parameter names that must never appear in help syntax/examples.
# Note: "context" is a real command name — only skip when it is a *param* name
# (handled by annotation checks below), not when it appears in a command path.
_SKIP = frozenset({
    "self", "cls", "ctx", "interaction", "inter",
    "message", "flags", "bot", "args", "kwargs",
})
_PLACEHOLDER_DESCRIPTIONS = frozenset({"no description", "no description given"})
_USAGE_TOKENS = re.compile(r"\([^)]+\)|\[[^\]]+\]|<[^>]+>")

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
    "Clownboard":    "Server",
    "Autorole":      "Server",
    "Bump":          "Server",
    "BumpReminder":  "Server",
    "Reaction":      "Server",
    "Timers":        "Server",
    "Logs":          "Logs",
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

_BLURBS: dict[str, str] = {
    "Server": "Prefixes, starboard, autorole, reactions, logs, and server setup.",
    "Security": "Antinuke, antiraid, and automod protection modules.",
    "Moderation": "Tools that help you moderate your server.",
    "Information": "User, guild, and bot lookups, avatars, banners, and stats.",
    "Utility": "Snipes, reminders, AFK, quotes, and voicemaster utilities.",
    "Fun": "Games, memes, roleplay, images, and fun commands.",
    "Miscellaneous": "Various useful commands that **don't** fit elsewhere.",
    "Music": "Queue, playback, Spotify, SoundCloud, and Lavalink controls.",
    "Social": "Twitch, YouTube, TikTok, Instagram, and feed notifications.",
    "Rewards": "XP, levels, giveaways, and reward systems.",
    "Crypto": "Cryptocurrency prices, charts, and market data.",
    "Last.fm": "Scrobbles, charts, covers, whoknows, and now playing.",
    "Owner": "Developer-only commands used to maintain vain.",
    "Logs": "Set up logging for your community events.",
}

_ORDER: tuple[str, ...] = (
    "Server", "Security", "Moderation", "Logs",
    "Information", "Utility", "Fun", "Miscellaneous",
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
                # Do not add intermediate groups as pages — expand to leaves
                if c.commands:
                    _walk(c)
            else:
                out.append(c)

    _walk(grp)
    return out


def _leaf_pages(root: Command) -> list[Command]:
    """Pages for help: leaf commands under a group, or the command itself."""
    if isinstance(root, Group):
        leaves = _visible_subs(root)
        if leaves:
            return sorted(leaves, key=lambda c: command_display_name(c).lower())
        # Group with no children — show the group shell once
        return [root]
    return [root]


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
    # Direct type matches
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
    
    if isinstance(cmd, Group):
        for value in (cmd.description, cmd.help, cmd.short_doc):
            text = str(value or "").strip()
            if text:
                return text[:1].upper() + text[1:]
        return f"Use subcommands under {cmd.qualified_name}"
    for value in (cmd.help, cmd.description, cmd.short_doc):
        text = str(value or "").strip()
        if text:
            return text[:1].upper() + text[1:]
    return f"Run the {cmd.qualified_name} command"


def _command_names(cmd: Command) -> tuple[str, ...]:
    names = [command_display_name(cmd).lower(), cmd.qualified_name.lower()]
    names.extend(alias.lower() for alias in cmd.aliases if alias)
    return tuple(dict.fromkeys(names))


def _strip_prefix(value: str, prefix: str) -> str:
    cleaned = str(value or "").strip()
    if prefix and cleaned.startswith(prefix):
        cleaned = cleaned[len(prefix) :].strip()
    return cleaned


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
    if syntax.lower().startswith("syntax:"):
        syntax = syntax.split(":", 1)[1].strip()

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


def _derived_syntax(cmd: Command) -> str:
    tokens: list[str] = []
    for name, param in _param_items(cmd):
        label = _usage_parameter_label(name, getattr(param, "annotation", inspect._empty))
        if not label:
            label = name.replace("_", " ")
        token = _format_usage_token(label, required=getattr(param, "required", False))
        if token:
            tokens.append(token)
    suffix = " ".join(tokens)
    result = f"{command_display_name(cmd)} {suffix}".strip()
    return _strip_hidden_params_from_text(result)


def _syntax(cmd: Command, prefix: str) -> str:
    usage, _ = _normalize_usage_and_example(str(cmd.usage or ""), prefix=str(prefix))
    syntax = usage or _derived_syntax(cmd)
    syntax = _strip_hidden_params_from_text(syntax)
    name = command_display_name(cmd)
    lowered = syntax.lower()
    nlow = name.lower()
    
    while f"{nlow} {nlow}" in lowered or lowered.startswith(f"{nlow} {nlow} "):
        syntax = re.sub(re.escape(name) + r"\s+" + re.escape(name), name, syntax, count=1, flags=re.I)
        lowered = syntax.lower()
    if any(lowered == n or lowered.startswith(f"{n} ") for n in _command_names(cmd)):
        pass
    else:
        
        syntax = f"{name} {syntax}".strip()
    if prefix and not syntax.startswith(prefix):
        syntax = f"{prefix}{syntax}"
    return syntax.strip()


def _strip_hidden_params_from_text(text: str) -> str:
    """Remove leaked framework param tokens from syntax/example strings.

    Only strips true injected-param names (``ctx``, ``interaction``, …).
    Does **not** strip the word ``context`` alone — that is a real command name
    (``,context color list``).
    """
    if not text:
        return text
    # bare param names only — never "context" (command group name)
    hidden = {
        "ctx", "interaction", "inter", "self", "cls",
        "message", "bot", "args", "kwargs",
    }
    parts = text.split()
    cleaned = []
    for p in parts:
        # strip wrappers: <ctx>, [interaction], (self), `ctx`
        low = p.lower().strip("`.,:;()[]<>")
        if low in hidden:
            continue
        cleaned.append(p)
    return " ".join(cleaned).strip()


def _token_to_example(token: str) -> str | None:
    raw = token.strip().strip("()[]<>")
    if not raw:
        return None
    lowered = re.sub(r"\s+", " ", raw.replace("_", " ").strip().lower())
    if lowered.startswith("--"):
        return None
    if lowered in {"ctx", "interaction", "self", "cls", "message", "bot"}:
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
    return raw


def _autogenerated_example(cmd: Command, syntax: str) -> str:
    body = syntax.strip()
    lowered = body.lower()
    for name in sorted(_command_names(cmd), key=len, reverse=True):
        if lowered == name:
            body = ""
            break
        if lowered.startswith(f"{name} "):
            body = body[len(name) :].strip()
            break

    samples = [sample for sample in (_token_to_example(token) for token in _USAGE_TOKENS.findall(body)) if sample]
    if not samples and body:
        samples = [sample for sample in (_token_to_example(token) for token in body.split()) if sample]
    if not samples:
        return command_display_name(cmd)
    
    samples = [s for s in samples if s.lower() not in {"ctx", "interaction"}]
    return f"{command_display_name(cmd)} {' '.join(samples)}" if samples else command_display_name(cmd)


def _example(cmd: Command, prefix: str) -> str | None:
    """Return a display example, or None when none should be shown.

    Prefer explicit ``example=``, then usage-line examples, then a light
    autogenerated sample. Never return the bare syntax as an "example".
    """
    raw = _strip_prefix(str(getattr(cmd, "example", None) or ""), str(prefix))
    if raw:
        raw = _strip_hidden_params_from_text(raw)
        
        name = command_display_name(cmd)
        lowered = raw.lower()
        nlow = name.lower()
        while lowered.startswith(f"{nlow} {nlow}"):
            raw = raw[len(name) :].lstrip()
            lowered = raw.lower()
        if not any(lowered == n or lowered.startswith(f"{n} ") for n in _command_names(cmd)):
            raw = f"{name} {raw}".strip()
        if prefix and not raw.startswith(prefix):
            raw = f"{prefix}{raw}"
        return raw.strip() or None

    _, usage_example = _normalize_usage_and_example(str(cmd.usage or ""), prefix=str(prefix))
    if usage_example:
        ue = _strip_hidden_params_from_text(usage_example)
        if prefix and not ue.startswith(prefix):
            ue = f"{prefix}{ue}"
        return ue or None

    
    auto = _autogenerated_example(cmd, _syntax(cmd, prefix))
    if not auto:
        return None
    auto = _strip_hidden_params_from_text(auto)
    if prefix and not auto.startswith(prefix):
        auto = f"{prefix}{auto}"
    
    if auto.strip() == _syntax(cmd, prefix).strip():
        return None
    return auto.strip()


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
    hidden = {"ctx", "interaction", "self", "cls", "message"}
    for token in _USAGE_TOKENS.findall(body):
        label = token.strip().strip("()[]<>").replace("_", " ").strip().lower()
        if label and label not in hidden:
            params.append(label)
    return params


def _parameter_value(cmd: Command, prefix: str) -> str:
    
    hidden = {"ctx", "interaction", "self", "cls", "message"}
    if raw := _params(cmd):
        visible = [p for p in raw if p.lower().replace(" ", "") not in hidden]
        if visible:
            return ", ".join(visible)
    if raw := _usage_params(cmd, prefix):
        visible = [p for p in raw if p.lower().replace(" ", "") not in hidden]
        if visible:
            return ", ".join(visible)
    return "n/a"


def _usage_block(cmd: Command, prefix: str) -> str:
    block = [f"Syntax: {_syntax(cmd, prefix)}"]
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
        label = f"{int(per)} seconds"
    else:
        label = f"{per:g} seconds"
    buckets = getattr(cmd, "_buckets", ())
    if any(getattr(bucket, "type", None) == commands.BucketType.guild for bucket in buckets):
        label += " per guild"
    elif any(getattr(bucket, "type", None) == commands.BucketType.user for bucket in buckets):
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
        info["permissions"] = "Server Owner"
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

    dom = getattr(ctx.bot, "color", 0x5865F2)
    try:
        loop = ctx.bot.loop
        if loop and not loop.is_running():
            dom = loop.run_until_complete(get_bot_dominant_color(ctx.bot))
    except Exception:
        pass
    e = Embed(
        title=title,
        description="\n".join(parts) if parts else desc,
        color=dom,
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


def _detail_text(
    cmd: Command,
    ctx: Context,
    *,
    group_title: bool = False,
    page_info: str | None = None,
) -> str:
    """Minimal command/group detail text matching inspiration layout."""
    prefix = _get_prefix(ctx)
    
    is_grp = bool(group_title and isinstance(cmd, Group))
    name = command_display_name(cmd)
    desc = _description(cmd) or "No description provided."
    aliases = _aliases(cmd)
    if aliases == "n/a":
        aliases = "None"
    perm = _information(cmd).get("permissions") or "None"
    syntax = _strip_hidden_params_from_text(_syntax(cmd, prefix))
    ex = _example(cmd, prefix)
    if ex:
        ex = _strip_hidden_params_from_text(ex)

    lines = [
        f"### {'Group' if is_grp else 'Command'}: `{name}`",
        f"> {desc}",
        "",
        f"**Aliases:** {aliases}",
        f"**Permissions:** {perm}",
        "```yaml",
        f"Syntax: {syntax}",
    ]
    
    if ex and ex.strip() and ex.strip() != syntax.strip():
        lines.append(f"Example: {ex}")
    lines.append("```")
    module = _module(cmd)
    if module != "n/a":
        module_label = next((k for k in _ORDER if k.lower() == module), module.title())
        footer = f"-# Module: {module_label}"
    else:
        footer = "-# Module: N/A"
    if page_info:
        footer += f" · {page_info}"
    lines.append(footer)
    return "\n".join(lines)


async def _accent_color(bot: Vain) -> int:
    try:
        return await get_bot_dominant_color(bot)
    except Exception:
        return getattr(bot, "color", None) or 0x5865F2


def _home_text(ctx: Context) -> str:
    """Minimal home help page."""
    p = _get_prefix(ctx)
    bot = ctx.bot
    bot_name = bot.user.display_name if bot.user else "Vain"
    website = getattr(bot_config, "website", "https://vain.bot")
    support = getattr(bot_config, "support", "https://discord.gg/vainbot")
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
        color=ctx.bot.color,
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

    def __init__(self, ctx: Context, cats: dict[str, list[Command]], accent: int) -> None:
        super().__init__(timeout=180)
        self.ctx = ctx
        self.cats = cats
        self.accent = accent
        self.msg: discord.Message | None = None

        self.body = ui.TextDisplay(_home_text(ctx))
        self.container = ui.Container(accent_colour=accent)
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
                    "You're not the **author** of this embed!"
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
        # Drop the select menu on timeout
        if self.msg is None:
            return
        body = ui.TextDisplay(self.body.content)
        container = ui.Container(accent_colour=self.accent)
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
    """Group/family help with prev/next/cancel buttons inside the V2 container."""

    def __init__(
        self,
        ctx: Context,
        pages: list[Command],
        accent: int,
    ) -> None:
        super().__init__(timeout=180)
        self.ctx = ctx
        self.pages = pages or []
        self.index = 0
        self.accent = accent
        self.msg: discord.Message | None = None

        self.body = ui.TextDisplay(self._page_text())
        self.container = ui.Container(accent_colour=accent)
        self.container.add_item(self.body)

        if len(self.pages) > 1:
            self.btn_row = ui.ActionRow()
            self.prev_btn = ui.Button(
                style=discord.ButtonStyle.secondary,
                emoji=discord.PartialEmoji.from_str(emojis.paginator.previous),
            )
            self.next_btn = ui.Button(
                style=discord.ButtonStyle.secondary,
                emoji=discord.PartialEmoji.from_str(emojis.paginator.next),
            )
            self.cancel_btn = ui.Button(
                style=discord.ButtonStyle.danger,
                emoji=discord.PartialEmoji.from_str(emojis.paginator.cancel),
            )
            self.prev_btn.callback = self._prev
            self.next_btn.callback = self._next
            self.cancel_btn.callback = self._cancel
            self.btn_row.add_item(self.prev_btn)
            self.btn_row.add_item(self.next_btn)
            self.btn_row.add_item(self.cancel_btn)
            self.container.add_item(self.btn_row)
            self._sync_buttons()

        self.add_item(self.container)

    def _page_info(self) -> str | None:
        if len(self.pages) <= 1:
            return None
        return f"Page {self.index + 1}/{len(self.pages)}"

    def _page_text(self) -> str:
        cmd = self.pages[self.index]
        # Paginated family help pages are leaf commands → always "Command:"
        # (Group: only if we somehow still have a shell with no children)
        is_shell = isinstance(cmd, Group) and not list(getattr(cmd, "commands", []) or [])
        return _detail_text(
            cmd,
            self.ctx,
            group_title=is_shell,
            page_info=self._page_info(),
        )

    def _sync_buttons(self) -> None:
        if len(self.pages) <= 1:
            return
        self.prev_btn.disabled = self.index <= 0
        self.next_btn.disabled = self.index >= len(self.pages) - 1

    async def interaction_check(self, inter: Interaction) -> bool:
        if inter.user.id == self.ctx.author.id:
            return True
        await inter.response.send_message(
            embed=Embed(
                color=color.warn,
                description=(
                    f"{emojis.warn} {inter.user.mention}: "
                    "You're not the **author** of this help!"
                ),
            ),
            ephemeral=True,
        )
        return False

    async def _prev(self, inter: Interaction) -> None:
        if self.index > 0:
            self.index -= 1
        self.body.content = self._page_text()
        self._sync_buttons()
        await inter.response.edit_message(view=self)

    async def _next(self, inter: Interaction) -> None:
        if self.index < len(self.pages) - 1:
            self.index += 1
        self.body.content = self._page_text()
        self._sync_buttons()
        await inter.response.edit_message(view=self)

    async def _cancel(self, inter: Interaction) -> None:
        await inter.response.defer()
        if inter.message:
            with contextlib.suppress(discord.HTTPException):
                await inter.message.delete()
        self.stop()

    async def on_timeout(self) -> None:
        # Drop buttons entirely on timeout (help only — not roleplay/pagination)
        if self.msg is None:
            return
        body = ui.TextDisplay(self._page_text())
        container = ui.Container(accent_colour=self.accent)
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


class CommandHelpMenu(ui.LayoutView):
    """Single non-group command help page (no pagination)."""

    def __init__(self, ctx: Context, cmd: Command, accent: int) -> None:
        super().__init__(timeout=180)
        self.ctx = ctx
        self.msg: discord.Message | None = None
        body = ui.TextDisplay(_detail_text(cmd, ctx, group_title=False))
        container = ui.Container(accent_colour=accent)
        container.add_item(body)
        self.add_item(container)

    async def start(self) -> discord.Message:
        kw: dict[str, Any] = {"view": self}
        if self.ctx.message and not self.ctx.interaction:
            kw["reference"] = self.ctx.message.to_reference(fail_if_not_exists=False)
            kw["allowed_mentions"] = discord.AllowedMentions.none()
        self.msg = await self.ctx.channel.send(**kw)
        return self.msg


class VainHelp:
    def __init__(self) -> None:
        
        self._seen: dict[int, float] = {}

    def register(self, bot: Vain) -> None:
        @bot.command(
            name="help",
            aliases=["h", "commands"],
            description="Browse command help, categories, syntax and examples.",
            example="help purge",
        )
        async def _help(ctx: Context, *, command: str | None = None) -> None:
            await self.invoke(ctx, command)

    async def invoke(self, ctx: Context, query: str | None = None) -> None:
        bot = ctx.bot
        owner = ctx.author.id in bot.owners

        if query is None:
            await self._send_home(ctx, bot, owner)
            return

        cmd = self._find(bot, query)
        if cmd is None or _cmd_hidden(cmd, owner=owner):
            await self._not_found(ctx, query)
            return
        family = self._family_targets(bot, cmd, owner=owner)
        if isinstance(cmd, Group) or len(family) > 1:
            await self._send_group(ctx, cmd, targets=family)
        else:
            await self._send_cmd(ctx, cmd)

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
        for cog in bot.cogs.values():
            if _hidden(cog, owner=owner):
                continue
            cmds = [
                c for c in cog.get_commands()
                if not c.hidden and family_root(c) is None
            ]
            if cmds:
                cats.setdefault(_category(cog), []).extend(cmds)
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
            
            e = Embed(color=accent, description=_home_text(ctx).replace("### ", ""))
            if bot.user:
                e.set_author(name=bot.user.display_name, icon_url=bot.user.display_avatar.url)
            await self._send(ctx, e)

    async def send_brief(self, ctx: Context, cmd: Command) -> discord.Message:
        """Used by ctx.send_help — always show full group pagination when applicable."""
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

        # Groups → leaf subcommands only (never empty intermediate group shells)
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
        # Guarantee leaves only
        if isinstance(grp, Group):
            pages = _leaf_pages(grp) if not targets else [
                c for c in pages if not isinstance(c, Group) or not getattr(c, "commands", None)
            ]
            if not pages:
                pages = _leaf_pages(grp)

        if not pages:
            await self._send_cmd(ctx, grp)
            return

        if len(pages) == 1 and not isinstance(pages[0], Group):
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
        container = ui.Container(accent_colour=accent)
        container.add_item(ui.TextDisplay(text))
        view.add_item(container)
        try:
            await self._send_layout(ctx, view)
        except Exception:
            e = Embed(title=f"**{label} Commands**", description=_fmt_commands(cmds), color=accent)
            await self._send(ctx, e)

    async def _not_found(self, ctx: Context, query: str) -> None:
        await ctx.warn(f"Command `{query}` does **not** exist")
