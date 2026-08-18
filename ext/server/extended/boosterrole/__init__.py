from typing import Optional
import re
import contextlib
import discord
from discord.ext.commands import group, CommandError, ColourConverter as ColorConverter
from discord import Role, Color
from core.discord.package import Package
from core.tools.color import get_dominant_color
from core.tools.checks import is_booster
from core.discord.views.embed import c2
from config import color, emojis
import aiohttp
import asyncio
import random


def _confirm_embed(message: str) -> discord.Embed:
    return c2(
        message=message or "Are you sure you want to do this?",
        timestamp=False,
    )


class _ShareConfirmView(discord.ui.View):
    def __init__(self, ctx, *, member: discord.abc.User, timeout: float = 30.0):
        super().__init__(timeout=timeout)
        self.ctx = ctx
        self.member = member
        self.value: bool | None = None
        self.message: discord.Message | None = None

        self.clear_items()

        def _emoji(raw: str | None):
            if not raw:
                return None
            try:
                return discord.PartialEmoji.from_str(str(raw))
            except Exception:
                return None

        accept = discord.ui.Button(
            label="Accept",
            style=discord.ButtonStyle.success,
            emoji=_emoji(getattr(emojis, "approve", None)),
        )
        deny = discord.ui.Button(
            label="Deny",
            style=discord.ButtonStyle.danger,
            emoji=_emoji(getattr(emojis, "deny", None)),
        )
        accept.callback = self._accept
        deny.callback = self._deny
        self.add_item(accept)
        self.add_item(deny)

    async def interaction_check(self, inter: discord.Interaction) -> bool:
        if inter.user.id != self.member.id:
            await inter.response.send_message(
                f"Only {self.member.mention} can use this.",
                ephemeral=True,
            )
            return False
        return True

    async def _accept(self, inter: discord.Interaction) -> None:
        self.value = True
        await inter.response.defer()
        self.stop()

    async def _deny(self, inter: discord.Interaction) -> None:
        self.value = False
        await inter.response.defer()
        self.stop()

    async def on_timeout(self) -> None:
        self.value = False
        if self.message is not None:
            with contextlib.suppress(discord.HTTPException):
                await self.message.delete()

    async def prompt(self, message: str | None = None, *, embed: discord.Embed | None = None, delete_after: bool = True) -> bool:
        if embed is None:
            embed = _confirm_embed(message or "Are you sure you want to do this?")
        self.message = await self.ctx.send(embed=embed, view=self)
        await self.wait()
        if delete_after and self.message is not None:
            with contextlib.suppress(discord.HTTPException):
                await self.message.delete()
        return bool(self.value)


from core.managers.permissions import has_permissions


def _parse_hex_color(token: str) -> discord.Color | None:
    """Parse a hex colour token. Auto-prefixes #. Maps #000000 -> #000001."""
    if not token:
        return None
    raw = token.strip()
    # strip optional #
    h = raw[1:] if raw.startswith("#") else raw
    if not re.fullmatch(r"[0-9a-fA-F]{6}", h) and not re.fullmatch(r"[0-9a-fA-F]{3}", h):
        return None
    if len(h) == 3:
        h = "".join(c * 2 for c in h)
    value = int(h, 16)
    # Discord treats pure black (#000000) as the default / invisible colour
    if value == 0:
        value = 1
    return discord.Color(value)


def _parse_create_args(args: str) -> tuple[str | None, discord.Color | None, discord.Color | None]:
    """Parse `br create` args: 1–2 leading hex colours (comma optional) + optional name.

    Accepts forms like:
      - ``ff0000``
      - ``ff0000 coolname``
      - ``ff0000, 00ff00 coolname``
      - ``ff0000,00ff00 coolname``
      - ``#ff0000 #00ff00 cool name``
    """
    raw = (args or "").strip()
    if not raw:
        return None, None, None
    # normalise commas so "ff0000, 00ff00 name" splits cleanly
    normalised = raw.replace(",", " ")
    tokens = [t for t in normalised.split() if t]
    colors: list[discord.Color] = []
    while tokens and len(colors) < 2:
        col = _parse_hex_color(tokens[0])
        if col is None:
            break
        colors.append(col)
        tokens.pop(0)
    name = " ".join(tokens).strip() or None
    primary = colors[0] if colors else None
    secondary = colors[1] if len(colors) > 1 else None
    return name, primary, secondary


def _parse_modify_args(args: str) -> tuple[str | None, discord.Color | None, discord.Color | None]:
    """Parse `br modify` args: optional name + 1–2 trailing hex colours.

    Accepts forms like:
      - ``ff0000``
      - ``ff0000 00ff00``
      - ``cool name ff0000``
      - ``cool name ff0000 00ff00``
      - ``#000000 hi`` is NOT used here (create path); modify expects colours at the end.
    """
    tokens = (args or "").split()
    if not tokens:
        return None, None, None

    colors: list[discord.Color] = []
    # pull hex tokens from the end
    while tokens:
        col = _parse_hex_color(tokens[-1])
        if col is None:
            break
        colors.append(col)
        tokens.pop()
        if len(colors) >= 2:
            break
    colors.reverse()
    name = " ".join(tokens).strip() or None
    primary = colors[0] if colors else None
    secondary = colors[1] if len(colors) > 1 else None
    return name, primary, secondary


def _apply_role_colors(role: discord.Role, primary: discord.Color, secondary: discord.Color | None, *, reason: str):
    """Edit role colour, using gradient when secondary is provided and supported."""
    kwargs = {"reason": reason}
    if secondary is not None:
        # Prefer RoleColours / colours kwarg when available (boost level 3 gradient)
        RoleColours = getattr(discord, "RoleColours", None)
        if RoleColours is not None:
            try:
                return role.edit(
                    colours=RoleColours(primary=primary, secondary=secondary),
                    reason=reason,
                )
            except TypeError:
                pass
            except Exception:
                pass
        # Fallback kwargs used by some discord.py builds
        for kw in (
            {"colour": primary, "secondary_colour": secondary},
            {"color": primary, "secondary_color": secondary},
        ):
            try:
                return role.edit(**kw, reason=reason)
            except TypeError:
                continue
            except Exception:
                continue
    return role.edit(color=primary, reason=reason)


class BoosterroleCommands(Package):
    """Personal booster colour roles for your server boosters."""

    @group(
        name="boosterrole",
        aliases=["boostrole", "br"],
        description="Create and customize your personal booster color role (gradient: ,br create <hex>, <hex2> <name>)",
        example=",boosterrole create ff0000, 00ff00 coolname",
        extras={"checks": "Boosters Only"},
        invoke_without_command=True,
    )
    async def boosterrole(self, ctx):
        """redirect to create"""
        return await ctx.invoke(self.boosterrole_create)

    @boosterrole.command(
        name="create",
        aliases=["color", "colour"],
        description="Create your booster role — solid: <hex> [name] · gradient (boost lvl 3): <hex>, <hex2> [name]",
        example=",boosterrole create ff0000, 00ff00 coolname",
    )
    @is_booster()
    async def boosterrole_create(self, ctx, *, args: str = None):
        """create booster role

        Examples
        --------
        ,br create ff0000
        ,br create ff0000 coolname
        ,br create ff0000, 00ff00 coolname
        ,br create #ff0000 #00ff00 cool name
        """
        if not args or not str(args).strip():
            return await ctx.send_help(ctx.command)

        name, primary, secondary = _parse_create_args(str(args))
        if primary is None and name is None:
            return await ctx.send_help(ctx.command)

        # if first token wasn't a colour, treat whole string as name with default colour
        if primary is None and name is not None:
            primary = discord.Color(1)

        if name is not None:
            if len(name) > 32:
                raise CommandError(
                    "Name **can't** exceed **32** characters\n"
                    f"> -# **provided:** {len(name)} characters"
                )
            if len(name) < 2:
                raise CommandError(
                    "Name needs at least **2** characters\n"
                    f"> -# **provided:** {len(name)} character{'s' if len(name) != 1 else ''}"
                )

        if secondary is not None:
            if getattr(ctx.guild, "premium_tier", 0) < 3:
                raise CommandError(
                    "Gradient colours need **Server Boost Level 3**\n"
                    f"> -# **current level:** {ctx.guild.premium_tier}"
                )

        cfg = await self.db.fetchrow(
            """SELECT base_id, role_limit FROM booster_roles WHERE guild_id = $1""",
            ctx.guild.id,
        )
        pos = None
        if cfg:
            base = ctx.guild.get_role(cfg.base_id)
            pos = base.position - 1 if base and base.position > 1 else None
            if cfg.role_limit:
                count = await self.db.fetchval(
                    """SELECT COUNT(*) FROM custom_roles WHERE guild_id = $1""",
                    ctx.guild.id,
                )
                if count >= cfg.role_limit:
                    raise CommandError(
                        "Role limit reached\n"
                        f"> -# **limit:** {cfg.role_limit} · contact an admin to increase"
                    )

        existing_id = await self.db.fetchval(
            """SELECT role_id FROM custom_roles WHERE guild_id = $1 AND user_id = $2""",
            ctx.guild.id,
            ctx.author.id,
        )
        role = ctx.guild.get_role(existing_id) if existing_id else None
        role_name = name or (role.name if role else ctx.author.name)

        if not role:
            role = await ctx.guild.create_role(
                name=role_name,
                color=primary if primary is not None else discord.Color.default(),
                reason="booster role",
            )
            if pos:
                with contextlib.suppress(discord.HTTPException, discord.Forbidden):
                    await role.edit(position=pos)
            await self.db.execute(
                """INSERT INTO custom_roles (guild_id, user_id, role_id)
                   VALUES ($1, $2, $3)
                   ON CONFLICT (guild_id, user_id) DO UPDATE SET role_id = excluded.role_id""",
                ctx.guild.id,
                ctx.author.id,
                role.id,
            )
            with contextlib.suppress(discord.HTTPException, discord.Forbidden):
                await ctx.author.add_roles(role, reason="booster role assigned")

            if secondary is not None and primary is not None:
                await _apply_role_colors(
                    role, primary, secondary, reason=f"booster gradient by {ctx.author}"
                )
                return await ctx.success(
                    f"Created and assigned {role.mention}\n"
                    f"> -# **gradient:** `#{primary.value:06X}` → `#{secondary.value:06X}`"
                )
            color_label = (
                f"`#{primary.value:06X}`" if primary is not None else "`default`"
            )
            return await ctx.success(
                f"Created and assigned {role.mention}\n"
                f"> -# **color:** {color_label}"
            )

        # existing role — update
        edit_name = name if name is not None else None
        if secondary is not None and primary is not None:
            await _apply_role_colors(
                role, primary, secondary, reason=f"booster gradient by {ctx.author}"
            )
            if edit_name and role.name != edit_name:
                with contextlib.suppress(discord.HTTPException):
                    await role.edit(name=edit_name, reason="booster role")
            return await ctx.success(
                f"Updated your role\n"
                f"> -# **name:** `{role.name}`\n"
                f"> -# **gradient:** `#{primary.value:06X}` → `#{secondary.value:06X}`"
            )

        edit_kwargs: dict = {"reason": "booster role"}
        if edit_name:
            edit_kwargs["name"] = edit_name
        if primary is not None:
            edit_kwargs["color"] = primary
        if len(edit_kwargs) > 1:
            await role.edit(**edit_kwargs)
        bits = []
        if edit_name:
            bits.append(f"**name:** `{edit_name}`")
        if primary is not None:
            bits.append(f"**color:** `#{primary.value:06X}`")
        return await ctx.success(
            "Updated your role\n> -# " + (" · ".join(bits) if bits else "saved")
        )

    @boosterrole.command(
        name="dominant",
        aliases=["avatar", "pfp", "av"],
        description="Set your role color to your avatar's dominant color",
    )
    @is_booster()
    async def boosterrole_dominant(self, ctx):
        """auto color from avatar"""
        role_id = await self.db.fetchval(
            """SELECT role_id FROM custom_roles WHERE guild_id = $1 AND user_id = $2""",
            ctx.guild.id,
            ctx.author.id,
        )
        if not role_id:
            raise CommandError(
                "You don't have a booster role yet\n"
                f"> -# **create one with:** {ctx.cmd('boosterrole')}"
            )
        col = Color.from_str(await get_dominant_color(ctx.author) or "#303135")
        role = ctx.guild.get_role(role_id)
        if role:
            await role.edit(color=col, reason=f"dominant color set by {ctx.author}")
            return await ctx.success(
                f"Color updated to your avatar's dominant\n"
                f"> -# **color:** `{col}`"
            )
        raise CommandError(
            "Your role was deleted\n"
            f"> -# **create a new one with:** {ctx.cmd('boosterrole')}"
        )

    @boosterrole.command(
        name="random",
        aliases=["rand", "randomhex"],
        description="Set your role to a random hex color",
    )
    @is_booster()
    async def boosterrole_random(self, ctx):
        """randomize booster role color"""
        role_id = await self.db.fetchval(
            """SELECT role_id FROM custom_roles WHERE guild_id = $1 AND user_id = $2""",
            ctx.guild.id,
            ctx.author.id,
        )
        if not role_id:
            raise CommandError(
                "You don't have a booster role yet\n"
                f"> -# **create one with:** {ctx.cmd('boosterrole')}"
            )
        rand = random.randint(0, 0xFFFFFF)
        col = Color.from_str(f"#{rand:06X}")
        role = ctx.guild.get_role(role_id)
        if role:
            await role.edit(color=col, reason=f"random color by {ctx.author}")
            return await ctx.success(
                f"Color randomized\n"
                f"> -# **color:** `{col}`"
            )
        raise CommandError(
            "Your role was deleted\n"
            f"> -# **create a new one with:** {ctx.cmd('boosterrole')}"
        )

    @boosterrole.group(
        name="icon",
        aliases=["image", "img"],
        description="Set an icon for your booster role (emoji, URL, or attachment)",
        example=",boosterrole icon https://example.com/img.png",
        invoke_without_command=True,
    )
    @is_booster()
    async def boosterrole_icon(
        self,
        ctx,
        *,
        icon: Optional[str] = None,
    ):
        """set booster role icon"""
        if "role_icons" not in [f.lower() for f in ctx.guild.features]:
            raise CommandError(
                "This server doesn't have **Role Icons**\n"
                f"> -# **requires level 2 boost**"
            )

        role_id = await self.db.fetchval(
            """SELECT role_id FROM custom_roles WHERE guild_id = $1 AND user_id = $2""",
            ctx.guild.id,
            ctx.author.id,
        )
        if not role_id:
            raise CommandError(
                "You don't have a booster role yet\n"
                f"> -# **create one with:** {ctx.cmd('boosterrole')}"
            )
        role = ctx.guild.get_role(role_id)
        if not role:
            raise CommandError(
                "Your role was deleted\n"
                f"> -# **create a new one with:** {ctx.cmd('boosterrole')}"
            )

        resolved = await self._resolve_boosterrole_icon(ctx, icon)

        await role.edit(
            display_icon=resolved,
            reason=f"icon changed by {ctx.author}",
        )
        if resolved is not None:
            return await ctx.success(
                "Icon **updated**\n"
                f"> -# run `{ctx.clean_prefix}br icon remove` to **remove** it"
            )
        return await ctx.success(
            "Icon **removed**\n"
            f"> -# run `{ctx.clean_prefix}br icon <emoji/url>` to **set** a new one"
        )

    @boosterrole_icon.command(
        name="remove",
        aliases=["delete", "del", "rm"],
        description="Remove your booster role icon",
    )
    @is_booster()
    async def boosterrole_icon_remove(self, ctx):
        """remove booster role icon"""
        role_id = await self.db.fetchval(
            """SELECT role_id FROM custom_roles WHERE guild_id = $1 AND user_id = $2""",
            ctx.guild.id,
            ctx.author.id,
        )
        if not role_id:
            raise CommandError(
                "You don't have a booster role\n"
                f"> -# **create one with:** {ctx.cmd('boosterrole')}"
            )
        role = ctx.guild.get_role(role_id)
        if not role:
            raise CommandError(
                "Your role was deleted\n"
                f"> -# **create a new one with:** {ctx.cmd('boosterrole')}"
            )
        if not role.display_icon:
            raise CommandError(
                "Your role doesn't have an icon\n"
                f"> -# **set one with:** {ctx.cmd('boosterrole icon')}"
            )

        await role.edit(display_icon=None, reason=f"icon removed by {ctx.author}")
        return await ctx.success(
            "Icon **removed**\n"
            f"> -# run `{ctx.clean_prefix}br icon <emoji/url>` to **set** a new one"
        )

    async def _resolve_boosterrole_icon(
        self,
        ctx,
        source: str | None = None,
    ) -> bytes | str | None:
        """Resolve a booster role icon from emoji, URL, or attached image."""
        if ctx.message and ctx.message.attachments:
            attachment = ctx.message.attachments[0]
            content_type = (attachment.content_type or "").lower()
            filename = (attachment.filename or "").lower()
            is_image = content_type.startswith("image/") or filename.endswith(
                (".png", ".jpg", ".jpeg", ".gif", ".webp")
            )
            if not is_image:
                raise CommandError(
                    "Attached file must be an **image**\n"
                    f"> -# **accepted:** PNG, JPG, GIF, WEBP"
                )
            data = await attachment.read()
            if len(data) > 256 * 1024:
                raise CommandError(
                    "Image is too large\n"
                    f"> -# **limit:** 256 KB"
                )
            return data

        if not source:
            return None

        raw = source.strip()
        if not raw:
            return None

        try:
            partial = discord.PartialEmoji.from_str(raw)
        except Exception:
            partial = None

        if partial is not None and partial.is_custom_emoji() and partial.id:
            ext = "gif" if partial.animated else "png"
            cdn_url = f"https://cdn.discordapp.com/emojis/{partial.id}.{ext}?size=256&quality=lossless"
            try:
                timeout = aiohttp.ClientTimeout(total=15)
                async with aiohttp.ClientSession(timeout=timeout) as session:
                    async with session.get(cdn_url) as resp:
                        if resp.status != 200:
                            raise CommandError(
                                "Could not download that emoji\n"
                                f"> -# **try a different one or use a URL**"
                            )
                        data = await resp.read()
            except CommandError:
                raise
            except Exception as exc:
                raise CommandError(
                    "Could not download that emoji\n"
                    f"> -# **try a different one or use a URL**"
                ) from exc
            if len(data) > 256 * 1024:
                raise CommandError(
                    "Emoji is too large\n"
                    f"> -# **limit:** 256 KB"
                )
            return data

        if raw.startswith(("http://", "https://")):
            try:
                timeout = aiohttp.ClientTimeout(total=15)
                async with aiohttp.ClientSession(timeout=timeout) as session:
                    async with session.get(raw) as resp:
                        if resp.status != 200:
                            raise CommandError(
                                "Could not download that image\n"
                                f"> -# **check the URL and try again**"
                            )
                        content_type = (resp.headers.get("Content-Type") or "").lower()
                        if content_type and not content_type.startswith("image/"):
                            raise CommandError(
                                "URL must point to an **image**\n"
                                f"> -# **accepted:** PNG, JPG, GIF, WEBP"
                            )
                        data = await resp.read()
            except CommandError:
                raise
            except Exception as exc:
                raise CommandError(
                    "Could not download that image\n"
                    f"> -# **check the URL and try again**"
                ) from exc
            if len(data) > 256 * 1024:
                raise CommandError(
                    "Image is too large\n"
                    f"> -# **limit:** 256 KB"
                )
            return data

        if raw.startswith(("<@", "<#")):
            raise CommandError(
                "Please provide a **valid icon**\n"
                f"> -# **accepted:** custom emoji, unicode emoji, image URL, or attachment"
            )

        if len(raw) <= 16 and not raw.isascii():
            return raw
        if len(raw) <= 8 and all(
            ord(ch) > 127 or ch.isspace() or ch in "️‍" for ch in raw
        ):
            return raw

        raise CommandError(
            "Please provide a **valid icon**\n"
            f"> -# **accepted:** custom emoji, unicode emoji, image URL, or attachment"
        )

    @boosterrole.command(
        name="rename",
        aliases=["name"],
        description="Change the name of your booster role",
        example=",boosterrole rename richgang",
    )
    @is_booster()
    async def boosterrole_rename(self, ctx, *, name: str):
        """rename booster role"""
        if len(name) > 32:
            raise CommandError(
                "Name **can't** exceed **32** characters\n"
                f"> -# **provided:** {len(name)} characters"
            )
        if len(name) < 2:
            raise CommandError(
                "Name needs at least **2** characters\n"
                f"> -# **provided:** {len(name)} character{'s' if len(name) != 1 else ''}"
            )
        role_id = await self.db.fetchval(
            """SELECT role_id FROM custom_roles WHERE guild_id = $1 AND user_id = $2""",
            ctx.guild.id,
            ctx.author.id,
        )
        if not role_id:
            raise CommandError(
                "You don't have a booster role yet\n"
                f"> -# **create one with:** {ctx.cmd('boosterrole')}"
            )
        role = ctx.guild.get_role(role_id)
        if role:
            await role.edit(name=name, reason=f"renamed by {ctx.author}")
            return await ctx.success(
                f"Role renamed\n"
                f"> -# **name:** `{name}`"
            )
        raise CommandError(
            "Your role was deleted\n"
            f"> -# **create a new one with:** {ctx.cmd('boosterrole')}"
        )

    @boosterrole.command(
        name="modify",
        aliases=["edit", "update", "mod"],
        description="Modify your booster role — solid: <name> <hex> · gradient (boost lvl 3): <name> <hex> <hex2>",
        example=",boosterrole modify coolname ff0000 00ff00",
    )
    @is_booster()
    async def boosterrole_modify(self, ctx, *, args: str = None):
        """modify booster role name and/or colour(s)"""
        if not args or not args.strip():
            return await ctx.send_help(ctx.command)

        name, primary, secondary = _parse_modify_args(args)
        if not name and primary is None:
            raise CommandError(
                "Provide a **name** and/or **colour**\n"
                f"> -# **examples:** {ctx.cmd('br modify coolname ff0000')} · {ctx.cmd('br modify ff0000 00ff00')}"
            )

        if name is not None:
            if len(name) > 32:
                raise CommandError(
                    "Name **can't** exceed **32** characters\n"
                    f"> -# **provided:** {len(name)} characters"
                )
            if len(name) < 2:
                raise CommandError(
                    "Name needs at least **2** characters\n"
                    f"> -# **provided:** {len(name)} character{'s' if len(name) != 1 else ''}"
                )

        if secondary is not None and primary is not None:
            # gradient requires boost level 3
            if getattr(ctx.guild, "premium_tier", 0) < 3:
                raise CommandError(
                    "Gradient colours need **Server Boost Level 3**\n"
                    f"> -# **current level:** {ctx.guild.premium_tier}"
                )

        role_id = await self.db.fetchval(
            """SELECT role_id FROM custom_roles WHERE guild_id = $1 AND user_id = $2""",
            ctx.guild.id,
            ctx.author.id,
        )
        if not role_id:
            raise CommandError(
                "You don't have a booster role yet\n"
                f"> -# **create one with:** {ctx.cmd('boosterrole')}"
            )
        role = ctx.guild.get_role(role_id)
        if not role:
            raise CommandError(
                "Your role was deleted\n"
                f"> -# **create a new one with:** {ctx.cmd('boosterrole')}"
            )

        edit_kwargs: dict = {"reason": f"booster role modified by {ctx.author}"}
        if name is not None:
            edit_kwargs["name"] = name

        if primary is not None and secondary is not None:
            await _apply_role_colors(role, primary, secondary, reason=edit_kwargs["reason"])
            if name is not None and role.name != name:
                with contextlib.suppress(discord.HTTPException):
                    await role.edit(name=name, reason=edit_kwargs["reason"])
            return await ctx.success(
                f"Role updated\n"
                f"> -# **name:** `{role.name}`\n"
                f"> -# **gradient:** `#{primary.value:06X}` → `#{secondary.value:06X}`"
            )

        if primary is not None:
            edit_kwargs["color"] = primary
        if name is not None or primary is not None:
            await role.edit(**edit_kwargs)

        bits = []
        if name is not None:
            bits.append(f"**name:** `{name}`")
        if primary is not None:
            bits.append(f"**color:** `#{primary.value:06X}`")
        return await ctx.success(
            "Role updated\n> -# " + " · ".join(bits)
        )

    @boosterrole.command(
        name="remove",
        aliases=["delete", "del", "rm"],
        description="Delete your booster role",
    )
    @is_booster()
    async def boosterrole_remove(self, ctx):
        """delete your booster role"""
        role_id = await self.db.fetchval(
            """SELECT role_id FROM custom_roles WHERE guild_id = $1 AND user_id = $2""",
            ctx.guild.id,
            ctx.author.id,
        )
        if not role_id:
            raise CommandError(
                "You don't have a booster role set up\n"
                f"> -# **create one with:** {ctx.cmd('boosterrole')}"
            )
        role = ctx.guild.get_role(role_id)
        if role:
            await role.delete(reason=f"booster role removed by {ctx.author}")
        await self.db.execute(
            """DELETE FROM custom_roles WHERE guild_id = $1 AND user_id = $2""",
            ctx.guild.id,
            ctx.author.id,
        )
        return await ctx.success("Booster role deleted")

    @boosterrole.group(
        name="award",
        aliases=["reward"],
        description="Reward a member with a role when they boost",
        example=",boosterrole award @rich",
        invoke_without_command=True,
    )
    @has_permissions(manage_roles=True, manage_guild=True)
    async def boosterrole_award(self, ctx, *, role: Role):
        """set booster award role"""
        await self.db.execute(
            """INSERT INTO booster_roles (guild_id, award_id) VALUES($1, $2) ON CONFLICT(guild_id) DO UPDATE SET award_id = excluded.award_id""",
            ctx.guild.id,
            role.id,
        )
        for member in ctx.guild.premium_subscribers:
            if role not in member.roles:
                try:
                    await member.add_roles(role)
                except Exception:
                    pass
        return await ctx.success(
            f"Now awarding all boosters\n"
            f"> -# **role:** {role.mention}"
        )

    @boosterrole_award.command(
        name="view",
        aliases=["show"],
        description="View the current award role",
    )
    @has_permissions(manage_roles=True, manage_guild=True)
    async def boosterrole_award_view(self, ctx):
        """show boost award role"""
        role_id = await self.db.fetchval(
            """SELECT award_id FROM booster_roles WHERE guild_id = $1""",
            ctx.guild.id,
        )
        if not role_id:
            raise CommandError(
                "No award role set\n"
                f"> -# **set one with:** {ctx.cmd('boosterrole award <role>')}"
            )
        role = ctx.guild.get_role(role_id)
        return await ctx.success(
            f"Current award role\n"
            f"> -# **role:** {role.mention}\n"
            f"> -# **members:** {len(role.members)}"
        )

    @boosterrole_award.command(
        name="unset",
        aliases=["delete", "remove", "clear"],
        description="Remove the award role",
    )
    @has_permissions(manage_roles=True, manage_guild=True)
    async def boosterrole_award_unset(self, ctx):
        """clear boost award role"""
        try:
            await self.db.execute(
                """UPDATE booster_roles SET award_id = $1 WHERE guild_id = $2""",
                None,
                ctx.guild.id,
            )
        except Exception:
            raise CommandError(
                "No award role is set\n"
                f"> -# **set one with:** {ctx.cmd('boosterrole award <role>')}"
            )
        return await ctx.success(
            "Award role **removed**\n"
            f"> -# run `{ctx.clean_prefix}br award <role>` to **set** a new one"
        )

    @boosterrole.command(
        name="base",
        aliases=["set", "baseid"],
        description="Set the base role that booster roles are positioned under",
        example=",boosterrole base @brs",
    )
    @has_permissions(manage_guild=True)
    async def boosterrole_base(self, ctx, *, role: Role):
        """set booster role position"""
        if not role.is_assignable():
            raise CommandError(
                f"Cannot edit {role.mention}\n"
                f"> -# **role may be too high or managed**"
            )
        await self.db.execute(
            """INSERT INTO booster_roles (guild_id, base_id) VALUES($1, $2) ON CONFLICT(guild_id) DO UPDATE SET base_id = excluded.base_id""",
            ctx.guild.id,
            role.id,
        )
        dead_ids = []
        role_ids = [
            r.role_id
            for r in await self.db.fetch(
                """SELECT role_id FROM custom_roles WHERE guild_id = $1""", ctx.guild.id
            )
        ]
        for rid in role_ids:
            br = ctx.guild.get_role(rid)
            if br:
                await br.edit(
                    position=role.position - 1 if role.position > 1 else 1,
                    reason=f"base role changed by {ctx.author}",
                )
            else:
                dead_ids.append(rid)
        await self.db.execute(
            """DELETE FROM custom_roles WHERE guild_id = $1 AND role_id = ANY($2::BIGINT[])""",
            ctx.guild.id,
            dead_ids,
        )
        return await ctx.success(
            f"Base role set\n"
            f"> -# **role:** {role.mention}"
        )

    @boosterrole.command(
        name="limit",
        description="Set how many booster roles can exist (0 = unlimited)",
        example=",boosterrole limit 30",
    )
    @has_permissions(manage_guild=True)
    async def boosterrole_limit(self, ctx, limit: int):
        """set booster role cap"""
        if limit < 1:
            limit = None
        await self.db.execute(
            """INSERT INTO booster_roles (guild_id, role_limit) VALUES($1, $2) ON CONFLICT(guild_id) DO UPDATE SET role_limit = excluded.role_limit""",
            ctx.guild.id,
            limit,
        )
        if limit:
            return await ctx.success(
                f"Role cap **set**\n"
                f"> -# **limit:** {limit}"
            )
        return await ctx.success(
            "Role cap **removed**\n"
            f"> -# run `{ctx.clean_prefix}br limit <number>` to **set** a new one"
        )

    @boosterrole.command(
        name="cleanup",
        aliases=["clean", "prune", "purge", "truncate"],
        description="Clean up booster roles that have no members",
    )
    @has_permissions(manage_roles=True, manage_guild=True)
    async def boosterrole_cleanup(self, ctx):
        """clean stale booster roles"""
        entries = await self.db.fetch(
            """SELECT role_id, user_id FROM custom_roles WHERE guild_id = $1""",
            ctx.guild.id,
        )
        if not entries:
            raise CommandError(
                "No roles to clean up\n"
                f"> -# **all roles have active members**"
            )
        removed_ids = []
        for entry in entries:
            role = ctx.guild.get_role(entry.role_id)
            if role:
                if not ctx.guild.get_member(entry.user_id):
                    await role.delete(reason=f"cleanup by {ctx.author}")
                    removed_ids.append(entry.role_id)
            else:
                removed_ids.append(entry.role_id)
        await self.db.execute(
            """DELETE FROM custom_roles WHERE role_id = ANY($1::BIGINT[])""",
            removed_ids,
        )
        return await ctx.success(
            f"Cleanup complete\n"
            f"> -# **removed:** {len(removed_ids)}"
        )

    @boosterrole.command(
        name="list",
        aliases=["all", "view"],
        description="Show every booster role in this server",
    )
    @has_permissions(manage_guild=True)
    async def boosterrole_list(self, ctx):
        """show all boost roles"""
        all_roles = await self.db.fetch(
            """SELECT user_id, role_id FROM custom_roles WHERE guild_id = $1""",
            ctx.guild.id,
        )
        if not all_roles:
            raise CommandError(
                "No booster roles found\n"
                f"> -# **members can create with:** {ctx.cmd('boosterrole')}"
            )
        stale = [
            r for r in all_roles
            if not ctx.guild.get_member(r.user_id) or not ctx.guild.get_role(r.role_id)
        ]
        valid = [r for r in all_roles if ctx.guild.get_member(r.user_id)]
        lines = [
            f"> {ctx.guild.get_member(r.user_id).mention} — {ctx.guild.get_role(r.role_id).mention}"
            for r in valid
        ]
        if stale:
            asyncio.ensure_future(self._purge_roles(ctx, stale))
        return await ctx.success(
            f"All booster roles ({len(valid)})\n" + "\n".join(lines)
        )

    async def _purge_roles(self, ctx, records):
        """delete stale booster roles"""
        for rec in records:
            if r := ctx.guild.get_role(rec.role_id):
                try:
                    await r.delete(reason="booster role cleanup")
                except Exception:
                    pass
        await self.db.execute(
            """DELETE FROM custom_roles WHERE guild_id = $1 AND role_id = ANY($2::BIGINT[])""",
            ctx.guild.id,
            [r.role_id for r in records],
        )
        return True

    @boosterrole.group(
        name="share",
        description="Share your personal booster role with another member",
        invoke_without_command=True,
    )
    @is_booster()
    async def boosterrole_share(self, ctx, member: Optional[discord.Member] = None):
        """share booster role"""
        if member is None:
            return await ctx.send_help(ctx.command)

        if member.id == ctx.author.id:
            raise CommandError(
                "You **can't** share with yourself\n"
                f"> -# **usage:** {ctx.cmd('boosterrole share @user')}"
            )
        if member.bot:
            raise CommandError(
                "You **can't** share with a bot\n"
                f"> -# **usage:** {ctx.cmd('boosterrole share @user')}"
            )

        role_id = await self.db.fetchval(
            """SELECT role_id FROM custom_roles WHERE guild_id = $1 AND user_id = $2""",
            ctx.guild.id,
            ctx.author.id,
        )
        if not role_id:
            raise CommandError(
                "You don't have a booster role yet\n"
                f"> -# **create one with:** {ctx.cmd('boosterrole')}"
            )
        role = ctx.guild.get_role(role_id)
        if not role:
            raise CommandError(
                "Your role was deleted\n"
                f"> -# **create a new one with:** {ctx.cmd('boosterrole')}"
            )

        if role in member.roles:
            raise CommandError(
                f"{member.mention} already has this role\n"
                f"> -# **no action needed**"
            )

        view = _ShareConfirmView(ctx, member=member)
        confirmed = await view.prompt(
            f"{member.mention}, {ctx.author} wants to **share** their booster role **with you**!\n"
            f"> -# to **receive** their **booster role** they want to share, **press accept**\n"
            f"> -# if you **don't want** to receive their role, **press deny**",
            delete_after=False,
        )
        if not confirmed:
            return await ctx.warn(
                f"{member.mention} declined the share request"
            )

        await member.add_roles(role, reason=f"shared by {ctx.author}")
        return await ctx.success(
            f"Shared role\n"
            f"> -# **member:** {member.mention}\n"
            f"> -# **role:** {role.mention}"
        )

    @boosterrole_share.command(
        name="list",
        aliases=["members"],
        description="List everyone in a booster role",
    )
    @is_booster()
    async def boosterrole_share_list(self, ctx):
        """list shared role members"""
        role_id = await self.db.fetchval(
            """SELECT role_id FROM custom_roles WHERE guild_id = $1 AND user_id = $2""",
            ctx.guild.id,
            ctx.author.id,
        )
        if not role_id:
            raise CommandError(
                "You don't have a booster role\n"
                f"> -# **create one with:** {ctx.cmd('boosterrole')}"
            )
        role = ctx.guild.get_role(role_id)
        if not role:
            raise CommandError(
                "Your role was deleted\n"
                f"> -# **create a new one with:** {ctx.cmd('boosterrole')}"
            )

        members = [m.mention for m in role.members if m.id != ctx.author.id]
        if not members:
            return await ctx.warn(
                "No members in your shared role\n"
                f"> -# **share with:** {ctx.cmd('boosterrole share @user')}"
            )

        return await ctx.success(
            f"Shared members ({len(members)})\n"
            + "\n".join(f"> {m}" for m in members)
        )

    @boosterrole_share.command(
        name="remove",
        aliases=["kick"],
        description="Remove someone from your booster role",
    )
    @is_booster()
    async def boosterrole_share_remove(self, ctx, member: discord.Member):
        """remove shared member"""
        role_id = await self.db.fetchval(
            """SELECT role_id FROM custom_roles WHERE guild_id = $1 AND user_id = $2""",
            ctx.guild.id,
            ctx.author.id,
        )
        if not role_id:
            raise CommandError(
                "You don't have a booster role\n"
                f"> -# **create one with:** {ctx.cmd('boosterrole')}"
            )
        role = ctx.guild.get_role(role_id)
        if not role:
            raise CommandError(
                "Your role was deleted\n"
                f"> -# **create a new one with:** {ctx.cmd('boosterrole')}"
            )

        if role not in member.roles:
            raise CommandError(
                f"{member.mention} doesn't have your role\n"
                f"> -# **check with:** {ctx.cmd('boosterrole share list')}"
            )

        await member.remove_roles(role, reason=f"removed by {ctx.author}")
        return await ctx.success(
            f"Removed member\n"
            f"> -# **member:** {member.mention}"
        )

    @boosterrole_share.command(
        name="max",
        description="Set the maximum number of members allowed in a shared role",
    )
    @has_permissions(manage_guild=True)
    async def boosterrole_share_max(self, ctx, limit: int):
        """set max shared members"""
        if limit < 1:
            raise CommandError(
                "Limit must be at least **1**\n"
                f"> -# **provided:** {limit}"
            )
        await self.db.execute(
            """INSERT INTO booster_roles (guild_id, share_limit) VALUES($1, $2) ON CONFLICT(guild_id) DO UPDATE SET share_limit = excluded.share_limit""",
            ctx.guild.id,
            limit,
        )
        return await ctx.success(
            f"Share limit **set**\n"
            f"> -# **limit:** {limit}"
        )

    @boosterrole.command(
        name="toggle",
        description="Toggle the booster roles system in this server",
    )
    @has_permissions(manage_guild=True)
    async def boosterrole_toggle(self, ctx):
        """toggle booster roles"""
        current = await self.db.fetchval(
            """SELECT enabled FROM booster_roles WHERE guild_id = $1""",
            ctx.guild.id,
        )
        new_state = not current if current is not None else True
        await self.db.execute(
            """INSERT INTO booster_roles (guild_id, enabled) VALUES($1, $2) ON CONFLICT(guild_id) DO UPDATE SET enabled = excluded.enabled""",
            ctx.guild.id,
            new_state,
        )
        state_str = "enabled" if new_state else "disabled"
        action = "disable" if new_state else "enable"
        return await ctx.success(
            f"Booster roles **{state_str}**\n"
            f"> -# run `{ctx.clean_prefix}br toggle` to **{action}** it"
        )
