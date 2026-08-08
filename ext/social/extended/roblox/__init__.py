from __future__ import annotations

import contextlib
from typing import Any

import aiohttp
import discord

from core.discord.ctx import Context
from core.discord.hybrid import describe, hybrid
from core.discord.package import Package
from core.discord.views.embed import panel_embed


_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/122.0.0.0 Safari/537.36"
)


class Roblox(Package):
    """Roblox lookups via keyless public APIs (help category: Social)."""

    async def _get_json(
        self,
        session: aiohttp.ClientSession,
        url: str,
        *,
        params: dict | None = None,
        method: str = "GET",
        json_body: dict | None = None,
    ) -> Any | None:
        headers = {"User-Agent": _UA, "Accept": "application/json"}
        try:
            timeout = aiohttp.ClientTimeout(total=12)
            if method.upper() == "POST":
                async with session.post(
                    url,
                    params=params,
                    json=json_body,
                    headers=headers,
                    timeout=timeout,
                ) as resp:
                    if resp.status >= 400:
                        return None
                    return await resp.json(content_type=None)
            async with session.get(
                url, params=params, headers=headers, timeout=timeout
            ) as resp:
                if resp.status >= 400:
                    return None
                return await resp.json(content_type=None)
        except Exception:
            return None

    async def _resolve_user(
        self, session: aiohttp.ClientSession, username: str
    ) -> dict[str, Any] | None:
        name = (username or "").strip().lstrip("@")
        if not name:
            return None

        data = await self._get_json(
            session,
            "https://users.roblox.com/v1/usernames/users",
            method="POST",
            json_body={"usernames": [name], "excludeBannedUsers": False},
        )
        if isinstance(data, dict):
            rows = data.get("data") or []
            if rows:
                row = rows[0]
                uid = row.get("id")
                if uid:
                    detail = await self._get_json(
                        session, f"https://users.roblox.com/v1/users/{uid}"
                    )
                    if isinstance(detail, dict) and detail.get("id"):
                        return detail
                    return {
                        "id": uid,
                        "name": row.get("name") or name,
                        "displayName": row.get("displayName")
                        or row.get("name")
                        or name,
                        "description": "",
                        "created": row.get("created") or "Unknown",
                    }

        data = await self._get_json(
            session,
            "https://users.roblox.com/v1/users/search",
            params={"keyword": name, "limit": 10},
        )
        if isinstance(data, dict):
            rows = data.get("data") or []
            for row in rows:
                if str(row.get("name") or "").lower() == name.lower():
                    uid = row.get("id")
                    if not uid:
                        continue
                    detail = await self._get_json(
                        session, f"https://users.roblox.com/v1/users/{uid}"
                    )
                    if isinstance(detail, dict) and detail.get("id"):
                        return detail
                    return row
            if rows:
                return rows[0]
        return None

    async def _avatar_url(
        self, session: aiohttp.ClientSession, user_id: int
    ) -> str | None:
        data = await self._get_json(
            session,
            "https://thumbnails.roblox.com/v1/users/avatar-headshot",
            params={
                "userIds": str(user_id),
                "size": "420x420",
                "format": "Png",
                "isCircular": "false",
            },
        )
        if isinstance(data, dict):
            rows = data.get("data") or []
            if rows and rows[0].get("imageUrl"):
                return str(rows[0]["imageUrl"])
        return (
            "https://www.roblox.com/headshot-thumbnail/image?"
            f"userId={user_id}&width=420&height=420&format=png"
        )

    def _profile_embed(self, user: dict[str, Any], avatar: str | None) -> discord.Embed:
        uid = user.get("id")
        name = user.get("name") or "Unknown"
        display = user.get("displayName") or name
        desc = (user.get("description") or "").strip()
        from core.tools.human import human_date

        created = human_date(user.get("created"), fallback="Unknown")
        e = panel_embed(
            title=f"{display} (@{name})",
            color=self.color,
            lines=[
                f"**ID:** `{uid}`",
                f"**Created:** {created}",
                (
                    f"**Profile:** [roblox.com/users/{uid}/profile]"
                    f"(https://www.roblox.com/users/{uid}/profile)"
                ),
            ],
            timestamp=False,
        )
        if desc:
            e.add_field(name="Bio", value=desc[:1024], inline=False)
        if avatar:
            with contextlib.suppress(Exception):
                e.set_thumbnail(url=avatar)
        return e

    @hybrid(
        name="roblox",
        aliases=("rbx", "rblx"),
        description="Roblox profile and item lookups",
        invoke_without_command=True,
        example=",roblox builderman",
        group=True,
        guilds=True,
        dms=True,
        groupchats=True,
    )
    @describe(username="Roblox username")
    async def roblox(self, ctx: Context, *, username: str | None = None):
        """Get a Roblox profile by username."""
        if not username:
            return await ctx.send_help(ctx.command)
        async with aiohttp.ClientSession() as session:
            user = await self._resolve_user(session, username)
            if not user or not user.get("id"):
                return await ctx.warn(f"Roblox user **{username}** not found")
            avatar = await self._avatar_url(session, int(user["id"]))
            await ctx.send(embed=self._profile_embed(user, avatar))

    @roblox.command(
        name="user",
        aliases=("profile", "lookup", "get"),
        description="Get profile information for a Roblox username",
        example=",roblox user builderman",
    )
    @describe(username="Roblox username")
    async def roblox_user(self, ctx: Context, *, username: str):
        await ctx.invoke(self.roblox, username=username)

    @roblox.command(
        name="id",
        aliases=("userid",),
        description="Look up a Roblox user by numeric ID",
        example=",roblox id 1",
    )
    @describe(user_id="Roblox numeric user ID")
    async def roblox_id(self, ctx: Context, user_id: int):
        async with aiohttp.ClientSession() as session:
            data = await self._get_json(
                session, f"https://users.roblox.com/v1/users/{user_id}"
            )
            if not isinstance(data, dict) or not data.get("id"):
                return await ctx.warn(f"No Roblox user with id `{user_id}`")
            avatar = await self._avatar_url(session, int(data["id"]))
            await ctx.send(embed=self._profile_embed(data, avatar))

    @roblox.command(
        name="friends",
        description="Show a user's public friend / follower counts",
        example=",roblox friends builderman",
    )
    @describe(username="Roblox username")
    async def roblox_friends(self, ctx: Context, *, username: str):
        async with aiohttp.ClientSession() as session:
            user = await self._resolve_user(session, username)
            if not user or not user.get("id"):
                return await ctx.warn(f"Roblox user **{username}** not found")
            uid = int(user["id"])
            friends = await self._get_json(
                session, f"https://friends.roblox.com/v1/users/{uid}/friends/count"
            )
            followers = await self._get_json(
                session, f"https://friends.roblox.com/v1/users/{uid}/followers/count"
            )
            following = await self._get_json(
                session, f"https://friends.roblox.com/v1/users/{uid}/followings/count"
            )
            f_count = friends.get("count") if isinstance(friends, dict) else "N/A"
            fo_count = followers.get("count") if isinstance(followers, dict) else "N/A"
            g_count = following.get("count") if isinstance(following, dict) else "N/A"
            e = panel_embed(
                title=f"{user.get('displayName') or user.get('name')} - Social",
                color=self.color,
                lines=[
                    f"**Friends:** {f_count}",
                    f"**Followers:** {fo_count}",
                    f"**Following:** {g_count}",
                ],
                timestamp=False,
            )
            await ctx.send(embed=e)

    @roblox.command(
        name="inventory",
        aliases=("collectibles", "limiteds"),
        description="List public collectibles for a user (if inventory is public)",
        example=",roblox inventory builderman",
    )
    @describe(username="Roblox username")
    async def roblox_inventory(self, ctx: Context, *, username: str):
        async with aiohttp.ClientSession() as session:
            user = await self._resolve_user(session, username)
            if not user or not user.get("id"):
                return await ctx.warn(f"Roblox user **{username}** not found")  # type: ignore[attr-defined]
            uid = int(user["id"])
            data = await self._get_json(
                session,
                f"https://inventory.roblox.com/v1/users/{uid}/assets/collectibles",
                params={"limit": 25, "sortOrder": "Asc"},
            )
            if not isinstance(data, dict):
                return await ctx.warn(  # type: ignore[attr-defined]
                    "Couldn't load inventory (private or rate-limited)"
                )
            rows = data.get("data") or []
            if not rows:
                return await ctx.warn("No public collectibles found")  # type: ignore[attr-defined]
            lines: list[str] = []
            for item in rows[:15]:
                name = item.get("name") or "Item"
                rap = item.get("recentAveragePrice")
                asset = item.get("assetId") or item.get("userAssetId")
                rap_s = f"{rap:,} R$" if isinstance(rap, int) else "N/A"
                if asset:
                    lines.append(f"**{name}** - RAP {rap_s} · `{asset}`")
                else:
                    lines.append(f"**{name}** - RAP {rap_s}")
            e = panel_embed(
                title=f"{user.get('name')}'s Collectibles",
                color=self.color,
                lines=lines,
                footer=f"{len(rows)} shown (public only)",
                timestamp=False,
            )
            await ctx.send(embed=e)

    @roblox.command(
        name="item",
        aliases=("catalog", "search"),
        description="Search the Roblox catalog for an item",
        example=",roblox item dominus",
    )
    @describe(query="Item name or keyword")
    async def roblox_item(self, ctx: Context, *, query: str):
        q = (query or "").strip()
        if not q:
            return await ctx.warn("Provide a search query")  # type: ignore[attr-defined]
        async with aiohttp.ClientSession() as session:
            data = await self._get_json(
                session,
                "https://catalog.roblox.com/v1/search/items",
                params={"keyword": q, "limit": 10, "category": "All"},
            )
            items: list[dict] = []
            if isinstance(data, dict):
                items = list(data.get("data") or [])

            detail_ids = [
                it.get("id")
                for it in items
                if isinstance(it, dict) and it.get("id") and not it.get("name")
            ]
            if detail_ids:
                details = await self._get_json(
                    session,
                    "https://catalog.roblox.com/v1/catalog/items/details",
                    method="POST",
                    json_body={
                        "items": [
                            {"id": i, "itemType": "Asset"} for i in detail_ids[:10]
                        ]
                    },
                )
                if isinstance(details, dict) and details.get("data"):
                    items = list(details["data"])

            if not items:
                data2 = await self._get_json(
                    session,
                    "https://catalog.roblox.com/v2/search/items/details",
                    params={"keyword": q, "limit": 10},
                )
                if isinstance(data2, dict):
                    items = list(data2.get("data") or [])

            if not items:
                return await ctx.warn(f"No catalog items found for **{q}**")  # type: ignore[attr-defined]

            lines: list[str] = []
            for item in items[:8]:
                name = item.get("name") or f"Item {item.get('id')}"
                price = item.get("price")
                if price is None:
                    price = item.get("lowestPrice")
                if price in (0, None) and item.get("priceStatus") == "Free":
                    price_s = "Free"
                elif isinstance(price, int):
                    price_s = f"{price:,} R$"
                else:
                    price_s = str(price or "N/A")
                iid = item.get("id") or item.get("itemId")
                link = (
                    f"https://www.roblox.com/catalog/{iid}/"
                    if iid
                    else "https://www.roblox.com/catalog"
                )
                lines.append(f"**[{name}]({link})** - {price_s}")

            e = panel_embed(
                title=f"{q}",
                color=self.color,
                lines=lines,
                footer="Roblox catalog (public)",
                timestamp=False,
            )
            await ctx.send(embed=e)

    @roblox.command(
        name="game",
        aliases=("place", "experience"),
        description="Look up a Roblox experience by name or place id",
        example=",roblox game adopt me",
    )
    @describe(query="Game name or place id")
    async def roblox_game(self, ctx: Context, *, query: str):
        q = (query or "").strip()
        if not q:
            return await ctx.warn("Provide a game name or place id")  # type: ignore[attr-defined]

        async with aiohttp.ClientSession() as session:
            place_id: int | None = int(q) if q.isdigit() else None
            universe_id: int | None = None
            place_name: str | None = None

            if place_id is None:
                data = await self._get_json(
                    session,
                    "https://apis.roblox.com/search-api/omni-search",
                    params={
                        "searchQuery": q,
                        "pageToken": "",
                        "sessionId": "vain-bot",
                    },
                )
                if isinstance(data, dict):
                    for group in data.get("searchResults") or []:
                        for content in group.get("contents") or []:
                            ctype = str(content.get("contentType") or "")
                            if ctype.lower() in {"game", "place", "experience"}:
                                place_id = (
                                    content.get("placeId")
                                    or content.get("rootPlaceId")
                                    or content.get("contentId")
                                )
                                universe_id = content.get("universeId")
                                place_name = content.get("name") or content.get(
                                    "username"
                                )
                                if place_id:
                                    break
                        if place_id:
                            break

            if not place_id and not universe_id:
                return await ctx.warn(f"No experience found for **{q}**")  # type: ignore[attr-defined]

            if universe_id is None and place_id:
                mapped = await self._get_json(
                    session,
                    f"https://apis.roblox.com/universes/v1/places/{place_id}/universe",
                )
                if isinstance(mapped, dict):
                    universe_id = mapped.get("universeId")

            if universe_id is None and place_id:
                place = await self._get_json(
                    session,
                    "https://games.roblox.com/v1/games/multiget-place-details",
                    params={"placeIds": str(place_id)},
                )
                if isinstance(place, list) and place:
                    universe_id = place[0].get("universeId")
                    place_name = place[0].get("name") or place_name
                elif isinstance(place, dict) and place.get("data"):
                    universe_id = place["data"][0].get("universeId")
                    place_name = place["data"][0].get("name") or place_name

            if not universe_id:
                return await ctx.warn("Found a place but couldn't resolve universe")  # type: ignore[attr-defined]

            gdata = await self._get_json(
                session,
                "https://games.roblox.com/v1/games",
                params={"universeIds": str(universe_id)},
            )
            if not isinstance(gdata, dict) or not gdata.get("data"):
                return await ctx.warn("Couldn't load experience details")  # type: ignore[attr-defined]

            game_info = gdata["data"][0]
            name = game_info.get("name") or place_name or q
            playing = game_info.get("playing")
            visits = game_info.get("visits")
            favs = game_info.get("favoritedCount")
            creator = (game_info.get("creator") or {}).get("name") or "Unknown"
            root = game_info.get("rootPlaceId") or place_id
            desc = (game_info.get("description") or "").strip()

            def _fmt(v: Any) -> str:
                return f"{v:,}" if isinstance(v, int) else str(v if v is not None else "N/A")

            lines = [
                f"**Creator:** {creator}",
                f"**Playing:** {_fmt(playing)}",
                f"**Visits:** {_fmt(visits)}",
                f"**Favorites:** {_fmt(favs)}",
                f"**Link:** [Open experience](https://www.roblox.com/games/{root}/)",
            ]
            e = panel_embed(
                title=name,
                color=self.color,
                lines=lines,
                footer=f"Universe {universe_id} · Place {root}",
                timestamp=False,
            )
            if desc:
                e.add_field(name="Description", value=desc[:1024], inline=False)
            await ctx.send(embed=e)

    @roblox.command(
        name="check",
        aliases=("owns",),
        description="Check if a user owns an asset (public inventories only)",
        example=",roblox check builderman 102611803",
    )
    @describe(username="Roblox username", asset_id="Asset ID to check")
    async def roblox_check(
        self, ctx: Context, username: str, asset_id: int
    ):
        async with aiohttp.ClientSession() as session:
            user = await self._resolve_user(session, username)
            if not user or not user.get("id"):
                return await ctx.warn(f"Roblox user **{username}** not found")  # type: ignore[attr-defined]
            uid = int(user["id"])
            owned = False
            data = await self._get_json(
                session,
                f"https://inventory.roblox.com/v1/users/{uid}/items/Asset/{asset_id}",
            )
            if isinstance(data, dict):
                owned = bool(data.get("data"))
            if not owned:
                own = await self._get_json(
                    session,
                    f"https://inventory.roblox.com/v1/users/{uid}/items/Asset/{asset_id}/is-owned",
                )
                if isinstance(own, bool):
                    owned = own
                elif isinstance(own, dict) and "isOwned" in own:
                    owned = bool(own.get("isOwned"))
            name = user.get("name") or username
            if owned:
                return await ctx.success(f"**{name}** owns asset `{asset_id}`")  # type: ignore[attr-defined]
            return await ctx.warn(  # type: ignore[attr-defined]
                f"**{name}** does not own asset `{asset_id}` (or inventory is private)"
            )

    @roblox.command(
        name="devex",
        description="Convert Robux to approximate USD via historical DevEx rate",
        example=",roblox devex 100000",
    )
    @describe(robux="Amount of Robux")
    async def roblox_devex(self, ctx: Context, robux: int):
        if robux < 0:
            return await ctx.warn("Robux must be positive")  # type: ignore[attr-defined]
        rate = 0.0035
        usd = robux * rate
        e = panel_embed(
            title="DevEx Estimate",
            color=self.color,
            lines=[
                f"**Robux:** {robux:,}",
                f"**Rate:** ${rate} / Robux",
                f"**USD:** ${usd:,.2f}",
            ],
            footer="Estimate only - not a live DevEx quote",
            timestamp=False,
        )
        await ctx.send(embed=e)



