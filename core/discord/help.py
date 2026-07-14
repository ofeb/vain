from __future__ import annotations

import contextlib
import inspect
import re
import time
from typing import TYPE_CHECKING, Any, Iterable, get_args, get_origin

import discord
from discord import Embed, Interaction, SelectOption, ui, MessageFlags
from discord.ext import commands
from discord.ext.commands import Command, Group

from core.discord.package import Package
from core.discord.hybrid import command_display_name, family_root, family_help_name

from core.managers.values import color, emojis
from core.tools.aesthetic import get_bot_dominant_color, get_dominant_color

if TYPE_CHECKING:
    from .ctx import Context
    from core.vain import Vain

_BLANK = "‎"
_HOME = "__home__"
_SKIP = frozenset({"self", "cls", "flags"})
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
    out: list[Command] = []

    def _walk(g: Group) -> None:
        for c in g.commands:
            if c.hidden:
                continue
            if isinstance(c, Group):
                if c.invoke_without_command:
                    out.append(c)
                if c.commands:
                    _walk(c)
            else:
                out.append(c)

    _walk(grp)
    return out


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


def _param_items(cmd: Command) -> list[tuple[str, Any]]:
    return [(name, param) for name, param in cmd.clean_params.items() if name not in _SKIP]


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
    # Prefer real decorator metadata. No bad placeholder fallbacks.
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
    return cleaned


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
    return f"{command_display_name(cmd)} {suffix}".strip()


def _syntax(cmd: Command, prefix: str) -> str:
    usage, _ = _normalize_usage_and_example(str(cmd.usage or ""), prefix=str(prefix))
    syntax = usage or _derived_syntax(cmd)
    lowered = syntax.lower()
    if any(lowered == name or lowered.startswith(f"{name} ") for name in _command_names(cmd)):
        return syntax
    return f"{command_display_name(cmd)} {syntax}".strip()


def _token_to_example(token: str) -> str | None:
    raw = token.strip().strip("()[]<>")
    if not raw:
        return None
    lowered = re.sub(r"\s+", " ", raw.replace("_", " ").strip().lower())
    if lowered.startswith("--"):
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
    return f"{command_display_name(cmd)} {' '.join(samples)}"


def _example(cmd: Command, prefix: str) -> str | None:
    # Strongly prefer real example= from decorator. Minimal auto only as last resort.
    raw = _strip_prefix(str(getattr(cmd, "example", None) or ""), str(prefix))
    if raw:
        lowered = raw.lower()
        if any(lowered == name or lowered.startswith(f"{name} ") for name in _command_names(cmd)):
            return raw
        return f"{command_display_name(cmd)} {raw}".strip()
    # fallback to usage example if provided in usage
    _, usage_example = _normalize_usage_and_example(str(cmd.usage or ""), prefix=str(prefix))
    if usage_example:
        return usage_example
    return None  # no bad placeholders


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
        if label:
            params.append(label)
    return params


def _parameter_value(cmd: Command, prefix: str) -> str:
    if params := _params(cmd):
        return ", ".join(params)
    if params := _usage_params(cmd, prefix):
        return ", ".join(params)
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
    prefix = getattr(ctx, "clean_prefix", None) or ctx.prefix or ";"
    if isinstance(prefix, list):
        prefix = prefix[0] if prefix else ";"
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

    try:
        dom = ctx.bot.loop.run_until_complete(get_bot_dominant_color(ctx.bot))
    except Exception:
        dom = ctx.bot.color
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


def _build_v2_detail(cmd: Command, ctx: Context, *, page_info: str | None = None) -> list:
    """Build v2 Container help matching the desired aesthetic style (inspired by examples)."""
    prefix = getattr(ctx, "clean_prefix", None) or ctx.prefix or ";"
    if isinstance(prefix, list):
        prefix = prefix[0] if prefix else ";"
    is_grp = isinstance(cmd, Group)
    name = command_display_name(cmd)
    desc = _description(cmd) or "No description provided."
    aliases = _aliases(cmd)
    if aliases == "n/a":
        aliases = "None"
    perm = _information(cmd).get("permissions") or "None"
    syntax = _syntax(cmd, prefix)
    ex = _example(cmd, prefix) or f"{prefix}{name}"

    try:
        accent = ctx.bot.loop.run_until_complete(get_bot_dominant_color(ctx.bot))
    except Exception:
        accent = 0x2b2d31  # nice dark

    # Build the exact style content the user wants
    content_lines = []
    if is_grp:
        content_lines.append(f"### Group: `{name}`")
    else:
        content_lines.append(f"### Command: `{name}`")
    content_lines.append(f"> {desc}")
    content_lines.append("")
    content_lines.append(f"**Aliases:** {aliases}")
    content_lines.append(f"**Permissions:** {perm}")
    content_lines.append("```yaml")
    content_lines.append(f"Syntax: {syntax}")
    if ex and ex != name:
        content_lines.append(f"Example: {ex}")
    content_lines.append("```")
    footer = f"-# Module: {_module(cmd)}"
    if page_info:
        footer += f" · {page_info}"
    content_lines.append(footer)

    c = ui.Container(accent_colour=accent)
    c.add_item(ui.TextDisplay("\n".join(content_lines)))
    return [c]


def _brief_embed(cmd: Command, ctx: Context) -> Embed:
    prefix = getattr(ctx, "clean_prefix", None) or ctx.prefix or ";"
    if isinstance(prefix, list):
        prefix = prefix[0] if prefix else ";"
    e = Embed(
        color=ctx.bot.color,
        title=("Group Command: " if isinstance(cmd, Group) else "Command: ") + command_display_name(cmd),
        description=_description(cmd),
    )
    e.set_author(name=ctx.author.display_name, icon_url=ctx.author.display_avatar.url)
    e.add_field(name=_BLANK, value=_usage_block(cmd, str(prefix)), inline=False)
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
            # send home as v2
            try:
                await inter.response.edit_message(components=[ui.Container(accent_colour=0x2b2d31).add_item(ui.TextDisplay("**Help Home** - use the select or `help <cmd>`"))], view=self._v)
            except:
                pass
            return
        comps = self._v.cat_embed(self.values[0])
        try:
            await inter.response.edit_message(components=comps, view=self._v)
        except Exception:
            # fallback
            await inter.response.edit_message(content="Category view updated. Use help <command>.", view=self._v)


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

    def cat_embed(self, label: str) -> list:
        """Return v2 components for category list (inspired by examples, original)."""
        prefix = getattr(self.ctx, "clean_prefix", None) or self.ctx.prefix or ";"
        if isinstance(prefix, list):
            prefix = prefix[0] if prefix else ";"
        try:
            accent = self.ctx.bot.loop.run_until_complete(get_bot_dominant_color(self.ctx.bot))
        except Exception:
            accent = 0x2b2d31

        cmds_text = _fmt_commands(self.cats.get(label, []), limit=1500).replace("```", "").replace("\n", " ")
        content = f"### {label} Commands\n{cmds_text}\n\n-# Use `{prefix}help <command>` for details"

        c = ui.Container(accent_colour=accent)
        c.add_item(ui.TextDisplay(content))
        return [c]

    def _home_embed(self) -> Embed:
        p = getattr(self.ctx, "clean_prefix", None) or self.ctx.prefix or ";"
        if isinstance(p, list):
            p = p[0] if p else ";"
        lines = [
            f"> Use `{p}help <command>` for a specific command.",
            f"> Use `{p}help <category>` to list commands in a module.",
            "",
            "-# ( ) required  [ ] optional",
        ]
        e = Embed(color=self.ctx.bot.color, description="\n".join(lines))
        if self.ctx.bot.user:
            e.set_author(name=self.ctx.bot.user.display_name, icon_url=self.ctx.bot.user.display_avatar.url)
        return e

    async def on_timeout(self) -> None:
        for item in self.children:
            item.disabled = True
        if self.msg:
            with contextlib.suppress(discord.HTTPException):
                await self.msg.edit(view=self)


class VainHelp:
    def __init__(self) -> None:
        self.ctx: Context = None
        self._seen: dict[int, float] = {}

    def register(self, bot: Vain) -> None:
        @bot.command(
            name="help",
            aliases=["h", "commands"],
            description="Browse command help, categories, syntax and examples. Use help <cmd> or help <category>",
            example=",help purge",
        )
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
        family = self._family_targets(bot, cmd, owner=owner)
        if isinstance(cmd, Group) or len(family) > 1:
            await self._send_group(cmd, targets=family)
        else:
            await self._send_cmd(cmd)

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

    def _prefix(self) -> str:
        p = getattr(self.ctx, "clean_prefix", None) or self.ctx.prefix or ";"
        return p[0] if isinstance(p, list) else str(p)

    def _base_embed(self, *, title: str | None = None, description: str | None = None) -> Embed:
        e = Embed(title=title, description=description, color=self.ctx.bot.color)
        if self.ctx.bot.user:
            e.set_author(name=self.ctx.bot.user.display_name, icon_url=self.ctx.bot.user.display_avatar.url)
        return e

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

    async def _send_v2(self, components: list) -> discord.Message:
        ctx = self.ctx
        kw: dict[str, Any] = {"components": components, "flags": MessageFlags.components_v2}
        if ctx.message and not ctx.interaction:
            kw["reference"] = ctx.message.to_reference(fail_if_not_exists=False)
            kw["allowed_mentions"] = discord.AllowedMentions.none()
        return await ctx.send(**kw)

    async def _send_home(self, bot: Vain, owner: bool) -> None:
        if self._dedup():
            return
        cats = self._build_cats(bot, owner)
        
        try:
            accent = bot.loop.run_until_complete(get_bot_dominant_color(bot))
        except Exception:
            accent = 0x2b2d31

        # Rich minimal home inspired by the provided examples (original, not 1:1)
        home_lines = []
        home_lines.append("### Help")
        home_lines.append("-# An all-in-one bot. Browse with the menu or `help <command>`.")
        home_lines.append("")
        home_lines.append("**Popular categories:** " + " • ".join([f"`{c}`" for c in list(cats.keys())[:10]]))
        home_lines.append("")
        home_lines.append("-# `[...]` optional  `<...>` required  •  Select a category below")

        c = ui.Container(accent_colour=accent)
        c.add_item(ui.TextDisplay("\n".join(home_lines)))

        view = HelpView(self.ctx, cats)
        # Send v2 content + view (view components will be added for category select)
        try:
            view.msg = await self.ctx.send(components=[c], view=view)
            return
        except Exception:
            # safe fallback to classic
            view.msg = await self._send(view.home, view=view)

    async def send_brief(self, ctx: Context, cmd: Command) -> discord.Message:
        self.ctx = ctx
        return await self._send(_brief_embed(cmd, ctx))

    async def _send_cmd(self, cmd: Command) -> None:
        try:
            comps = _build_v2_detail(cmd, self.ctx)
            await self._send_v2(comps)
        except Exception:
            # fallback to nice embed with dom color
            await self._send(_detail_embed(cmd, self.ctx))

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
            return [root] + _visible_subs(root)

        linked = _linked_family_commands(bot, root.name, owner=owner)
        if linked:
            return [root] + linked

        prefix = f"{root.qualified_name.lower()} "
        seen = {root.qualified_name}
        family = [root]
        candidates = root.cog.get_commands() if root.cog is not None else list(bot.walk_commands())
        for command in candidates:
            if command.qualified_name in seen:
                continue
            if command.hidden or _cmd_hidden(command, owner=owner):
                continue
            if command.qualified_name.lower().startswith(prefix):
                seen.add(command.qualified_name)
                family.append(command)
        return family

    async def _send_group(self, grp: Command, *, targets: list[Command] | None = None) -> None:
        owner = self.ctx.author.id in self.ctx.bot.owners
        targets = targets or self._family_targets(self.ctx.bot, grp, owner=owner)
        subs = sorted(
            [t for t in targets if t is not grp],
            key=lambda c: command_display_name(c).lower(),
        )
        if not isinstance(grp, Group) and len(targets) > 1:
            subs.insert(0, grp)
        if not subs:
            await self._send(_detail_embed(grp, self.ctx))
            return
        total = len(subs)
        embeds = []
        for index, sub in enumerate(subs, start=1):
            e = _detail_embed(
                sub,
                self.ctx,
                group_title=True,
                page_index=index if total > 1 else None,
                total_pages=total if total > 1 else None,
            )
            e.title = "Group Command: " + command_display_name(grp)
            embeds.append(e)
        if len(embeds) == 1:
            try:
                await self._send_v2(_build_v2_detail(grp, self.ctx))
            except Exception:
                await self._send(embeds[0])
        else:
            await self.ctx.paginate(embeds)

    async def _send_cog(self, cog: Package) -> None:
        cmds = [c for c in cog.get_commands() if not c.hidden]
        label = _category(cog)
        try:
            accent = self.ctx.bot.loop.run_until_complete(get_bot_dominant_color(self.ctx.bot))
        except Exception:
            accent = 0x2b2d31
        content = f"### {label} Commands\n" + _fmt_commands(cmds).replace('```', '').replace('\n', ' ') + "\n\n-# Use `help <command>` for details"
        c = ui.Container(accent_colour=accent)
        c.add_item(ui.TextDisplay(content))
        await self._send_v2([c])

    async def _not_found(self, query: str) -> None:
        await self.ctx.warn(f"Command `{query}` does **not** exist")
