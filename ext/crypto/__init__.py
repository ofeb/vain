from __future__ import annotations

import asyncio
import contextlib
import logging
from datetime import datetime, timezone
from typing import Any

import aiohttp
import discord
from discord.ext import commands, tasks
from discord.ext.commands import TextChannelConverter

from config import color
from core.discord.ctx import Context
from core.discord.hybrid import describe, hybrid
from core.discord.views.embed import c2, panel_embed
from core.managers.permissions import has_permissions

log = logging.getLogger("vain.crypto")

COINGECKO_BASE = "https://api.coingecko.com/api/v3"

COIN_ALIASES = {
    "btc": "bitcoin",
    "bitcoin": "bitcoin",
    "eth": "ethereum",
    "ethereum": "ethereum",
    "etherium": "ethereum",  
    "ether": "ethereum",
    "sol": "solana",
    "solana": "solana",
    "xrp": "ripple",
    "ripple": "ripple",
    "ada": "cardano",
    "cardano": "cardano",
    "doge": "dogecoin",
    "dogecoin": "dogecoin",
    "dot": "polkadot",
    "polkadot": "polkadot",
    "matic": "polygon",
    "polygon": "polygon",
    "avax": "avalanche-2",
    "avalanche": "avalanche-2",
    "link": "chainlink",
    "chainlink": "chainlink",
    "atom": "cosmos",
    "cosmos": "cosmos",
    "trx": "tron",
    "tron": "tron",
    "ltc": "litecoin",
    "litecoin": "litecoin",
    "bch": "bitcoin-cash",
    "bitcoin-cash": "bitcoin-cash",
    "bnb": "binancecoin",
    "binancecoin": "binancecoin",
}

COIN_LABELS = {
    "bitcoin": ("BTC", "Bitcoin", "https://assets.coingecko.com/coins/images/1/large/bitcoin.png"),
    "ethereum": ("ETH", "Ethereum", "https://assets.coingecko.com/coins/images/279/large/ethereum.png"),
    "solana": ("SOL", "Solana", "https://assets.coingecko.com/coins/images/4128/large/solana.png"),
    "ripple": ("XRP", "XRP", "https://assets.coingecko.com/coins/images/44/large/xrp-symbol-white-128.png"),
    "cardano": ("ADA", "Cardano", None),
    "dogecoin": ("DOGE", "Dogecoin", None),
    "polkadot": ("DOT", "Polkadot", None),
    "polygon": ("MATIC", "Polygon", None),
    "avalanche-2": ("AVAX", "Avalanche", None),
    "chainlink": ("LINK", "Chainlink", None),
    "cosmos": ("ATOM", "Cosmos", None),
    "tron": ("TRX", "TRON", None),
    "litecoin": ("LTC", "Litecoin", "https://assets.coingecko.com/coins/images/2/large/litecoin.png"),
    "bitcoin-cash": ("BCH", "Bitcoin Cash", None),
    "binancecoin": ("BNB", "BNB", None),
}


_FEED_POLL_SECONDS = 120.0
_MIN_POST_GAP_SECONDS = 300.0  
_PRICE_MOVE_PCT = 0.75  
_CHANGE_DELTA = 0.35  


def _now_naive() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def resolve_coin(raw: str) -> tuple[str, str, str, str | None] | None:
    """Return (coin_id, symbol, display_name, thumbnail) or None."""
    key = (raw or "").lower().strip().lstrip("$")
    if not key:
        return None
    coin_id = COIN_ALIASES.get(key, key)
    label = COIN_LABELS.get(coin_id)
    if label:
        symbol, name, thumb = label
        return coin_id, symbol, name, thumb
    
    symbol = key.upper()[:8]
    return coin_id, symbol, key.replace("-", " ").title(), None


class Crypto(commands.Cog):
    """Cryptocurrency prices, charts, market data, and channel feeds."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self._session: aiohttp.ClientSession | None = None
        self._schema_ready = False

    async def cog_load(self) -> None:
        await self._ensure_schema()
        if not self._feed_loop.is_running():
            self._feed_loop.start()

    async def cog_unload(self) -> None:
        if self._feed_loop.is_running():
            self._feed_loop.cancel()
        if self._session and not self._session.closed:
            await self._session.close()
        self._session = None

    async def _ensure_schema(self) -> None:
        if self._schema_ready:
            return
        with contextlib.suppress(Exception):
            await self.bot.db.execute(
                """
                CREATE TABLE IF NOT EXISTS crypto_feeds (
                    guild_id BIGINT NOT NULL,
                    channel_id BIGINT NOT NULL,
                    coin_id TEXT NOT NULL,
                    coin_label TEXT NOT NULL,
                    last_price DOUBLE PRECISION,
                    last_change DOUBLE PRECISION,
                    last_market_cap DOUBLE PRECISION,
                    last_posted TIMESTAMP,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    PRIMARY KEY (guild_id, channel_id, coin_id)
                )
                """
            )
            await self.bot.db.execute(
                "CREATE INDEX IF NOT EXISTS idx_crypto_feeds_coin ON crypto_feeds(coin_id)"
            )
            self._schema_ready = True

    async def _http(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession(
                timeout=aiohttp.ClientTimeout(total=12),
                headers={"Accept": "application/json", "User-Agent": "vain-bot/crypto"},
            )
        return self._session

    async def _fetch_price(self, coin_id: str) -> dict | None:
        url = f"{COINGECKO_BASE}/simple/price"
        params = {
            "ids": coin_id,
            "vs_currencies": "usd",
            "include_24hr_change": "true",
            "include_market_cap": "true",
            "include_24hr_vol": "true",
        }
        try:
            session = await self._http()
            async with session.get(url, params=params) as resp:
                if resp.status != 200:
                    return None
                data = await resp.json(content_type=None)
                if not isinstance(data, dict):
                    return None
                return data.get(coin_id)
        except Exception:
            return None

    async def _fetch_prices(self, coin_ids: list[str]) -> dict[str, dict]:
        if not coin_ids:
            return {}
        
        url = f"{COINGECKO_BASE}/simple/price"
        params = {
            "ids": ",".join(sorted(set(coin_ids))),
            "vs_currencies": "usd",
            "include_24hr_change": "true",
            "include_market_cap": "true",
            "include_24hr_vol": "true",
        }
        try:
            session = await self._http()
            async with session.get(url, params=params) as resp:
                if resp.status != 200:
                    return {}
                data = await resp.json(content_type=None)
                return data if isinstance(data, dict) else {}
        except Exception:
            return {}

    def _price_embed(
        self,
        *,
        coin_id: str,
        symbol: str,
        name: str,
        data: dict,
        thumbnail: str | None = None,
        title: str | None = None,
        footer: str = "Powered by CoinGecko",
    ) -> discord.Embed:
        usd = float(data.get("usd") or 0)
        change = float(data.get("usd_24h_change") or 0)
        cap = float(data.get("usd_market_cap") or 0)
        vol = float(data.get("usd_24h_vol") or 0)
        arrow = ""
        if change > 0:
            arrow = "▲"
        elif change < 0:
            arrow = "▼"

        if title is None:
            title = f"{name} ({symbol}) / USD - ${usd:,.2f}" if usd >= 1 else f"{name} ({symbol}) / USD - ${usd:,.6f}"

        embed = panel_embed(
            title=title,
            color=color.base,
            lines=[],
            footer=footer,
            thumbnail=thumbnail,
            timestamp=False,
        )
        price_s = f"${usd:,.2f}" if usd >= 1 else f"${usd:,.6f}"
        embed.add_field(name="Price", value=price_s, inline=True)
        embed.add_field(
            name="24h Change",
            value=f"{arrow} {change:+.2f}%" if change else "0.00%",
            inline=True,
        )
        if cap:
            embed.add_field(name="Market Cap", value=f"${cap:,.0f}", inline=True)
        if vol:
            embed.add_field(name="24h Volume", value=f"${vol:,.0f}", inline=True)
        return embed

    def _should_post_update(
        self,
        row: dict,
        data: dict,
    ) -> bool:
        """Decide if market moved enough to warrant a feed post."""
        price = float(data.get("usd") or 0)
        change = float(data.get("usd_24h_change") or 0)
        cap = float(data.get("usd_market_cap") or 0)

        last_price = row.get("last_price")
        last_change = row.get("last_change")
        last_posted = row.get("last_posted")

        
        if last_price is None:
            return True

        
        if last_posted is not None:
            lp = last_posted
            if getattr(lp, "tzinfo", None) is not None:
                lp = lp.replace(tzinfo=None)
            if (_now_naive() - lp).total_seconds() < _MIN_POST_GAP_SECONDS:
                return False

        try:
            prev = float(last_price)
        except Exception:
            return True
        if prev <= 0:
            return abs(price - prev) > 0

        pct = abs(price - prev) / prev * 100.0
        if pct >= _PRICE_MOVE_PCT:
            return True

        if last_change is not None:
            try:
                if abs(change - float(last_change)) >= _CHANGE_DELTA:
                    return True
            except Exception:
                pass

        
        last_cap = row.get("last_market_cap")
        if last_cap and cap:
            try:
                prev_cap = float(last_cap)
                if prev_cap > 0 and abs(cap - prev_cap) / prev_cap * 100.0 >= 1.0:
                    return True
            except Exception:
                pass
        return False

    

    async def _parse_channel_coin(
        self, ctx: Context, args: str
    ) -> tuple[discord.TextChannel, str, str, str, str | None]:
        tokens = (args or "").split()
        if not tokens:
            raise commands.CommandError(
                f"Usage: `{ctx.clean_prefix}crypto feeds add #channel <coin>`"
            )
        channel: discord.abc.GuildChannel | discord.TextChannel = ctx.channel  # type: ignore[assignment]
        i = 0
        try:
            channel = await TextChannelConverter().convert(ctx, tokens[0])
            i = 1
        except Exception:
            pass
        if i >= len(tokens):
            raise commands.CommandError("Provide a coin (e.g. `eth`, `ltc`, `bitcoin`)")
        coin_raw = " ".join(tokens[i:]).strip()
        resolved = resolve_coin(coin_raw)
        if not resolved:
            raise commands.CommandError(f"Unknown coin `{coin_raw}`")
        coin_id, symbol, name, thumb = resolved
        
        data = await self._fetch_price(coin_id)
        if data is None:
            raise commands.CommandError(
                f"Could not resolve **{coin_raw}** on CoinGecko - check the id/symbol"
            )
        if not isinstance(channel, discord.TextChannel):
            raise commands.CommandError("Feeds can only be added to text channels")
        return channel, coin_id, symbol, name, thumb

    @commands.group(
        name="crypto",
        aliases=["coin", "price"],
        description="Cryptocurrency prices and channel price feeds",
        invoke_without_command=True,
        example=",crypto btc",
    )
    async def crypto(self, ctx: Context, *, coin: str = "bitcoin") -> None:
        resolved = resolve_coin(coin)
        if not resolved:
            await ctx.fail("Provide a coin name or symbol.")
            return
        coin_id, symbol, name, thumb = resolved
        data = await self._fetch_price(coin_id)
        if data is None:
            await ctx.fail(f"Could not fetch price for `{coin}`. Try a different name.")
            return
        embed = self._price_embed(
            coin_id=coin_id,
            symbol=symbol,
            name=name,
            data=data,
            thumbnail=thumb,
            title=f"{symbol} / USD",
        )
        await ctx.send(embed=embed)

    @crypto.group(
        name="feeds",
        aliases=["feed"],
        description="Crypto price feed subscriptions",
        invoke_without_command=True,
        example=",crypto feeds add #crypto eth",
    )
    @has_permissions(manage_guild=True)
    async def crypto_feeds(self, ctx: Context) -> None:
        return await ctx.send_help(ctx.command)

    @crypto_feeds.command(
        name="add",
        aliases=["set", "create", "subscribe"],
        description="Post market updates for a coin in a channel",
        example=",crypto feeds add #crypto eth",
        usage="[channel] <coin>",
    )
    @has_permissions(manage_guild=True)
    async def crypto_feeds_add(self, ctx: Context, *, args: str = "") -> None:
        await self._ensure_schema()
        channel, coin_id, symbol, name, _thumb = await self._parse_channel_coin(ctx, args)
        label = f"{name} ({symbol})"
        await self.bot.db.execute(
            """
            INSERT INTO crypto_feeds (guild_id, channel_id, coin_id, coin_label)
            VALUES ($1, $2, $3, $4)
            ON CONFLICT (guild_id, channel_id, coin_id) DO UPDATE
                SET coin_label = excluded.coin_label
            """,
            ctx.guild.id,
            channel.id,
            coin_id,
            label,
        )
        
        data = await self._fetch_price(coin_id)
        if data:
            await self.bot.db.execute(
                """
                UPDATE crypto_feeds
                   SET last_price = $1, last_change = $2, last_market_cap = $3
                 WHERE guild_id = $4 AND channel_id = $5 AND coin_id = $6
                """,
                float(data.get("usd") or 0),
                float(data.get("usd_24h_change") or 0),
                float(data.get("usd_market_cap") or 0),
                ctx.guild.id,
                channel.id,
                coin_id,
            )
            embed = self._price_embed(
                coin_id=coin_id,
                symbol=symbol,
                name=name,
                data=data,
                thumbnail=COIN_LABELS.get(coin_id, (None, None, None))[2],
                footer="Feed armed · updates on meaningful market moves",
            )
            with contextlib.suppress(Exception):
                await channel.send(embed=embed)
        await ctx.success(
            f"Crypto feed **{label}** → {channel.mention}\n"
            f"> -# Posts when price/24h change/market cap moves meaningfully"
        )

    @crypto_feeds.command(
        name="remove",
        aliases=["delete", "del", "rm", "unsubscribe"],
        description="Remove a crypto feed from a channel",
        example=",crypto feeds remove #crypto eth",
        usage="[channel] <coin>",
    )
    @has_permissions(manage_guild=True)
    async def crypto_feeds_remove(self, ctx: Context, *, args: str = "") -> None:
        await self._ensure_schema()
        tokens = (args or "").split()
        channel: discord.TextChannel = ctx.channel  # type: ignore[assignment]
        i = 0
        if tokens:
            try:
                channel = await TextChannelConverter().convert(ctx, tokens[0])  # type: ignore[assignment]
                i = 1
            except Exception:
                pass
        coin_raw = " ".join(tokens[i:]).strip() if tokens[i:] else ""
        if not coin_raw:
            
            result = await self.bot.db.execute(
                "DELETE FROM crypto_feeds WHERE guild_id = $1 AND channel_id = $2",
                ctx.guild.id,
                channel.id,
            )
            await ctx.success(f"Cleared crypto feeds in {channel.mention}")
            return
        resolved = resolve_coin(coin_raw)
        if not resolved:
            await ctx.fail(f"Unknown coin `{coin_raw}`")
            return
        coin_id = resolved[0]
        row = await self.bot.db.fetchrow(
            """
            DELETE FROM crypto_feeds
             WHERE guild_id = $1 AND channel_id = $2 AND coin_id = $3
         RETURNING coin_label
            """,
            ctx.guild.id,
            channel.id,
            coin_id,
        )
        if not row:
            await ctx.warn(f"No **{coin_raw}** feed in {channel.mention}")
            return
        await ctx.success(f"Removed **{row['coin_label']}** feed from {channel.mention}")

    @crypto_feeds.command(
        name="list",
        aliases=["ls", "show"],
        description="List crypto feeds in this server",
        example=",crypto feeds list",
    )
    @has_permissions(manage_guild=True)
    async def crypto_feeds_list(self, ctx: Context) -> None:
        await self._ensure_schema()
        rows = await self.bot.db.fetch(
            """
            SELECT channel_id, coin_id, coin_label, last_price, last_change
              FROM crypto_feeds
             WHERE guild_id = $1
             ORDER BY coin_label, channel_id
            """,
            ctx.guild.id,
        )
        if not rows:
            await ctx.warn("No crypto feeds configured.")
            return
        lines: list[str] = []
        for i, r in enumerate(rows, start=1):
            ch = ctx.guild.get_channel(r["channel_id"])
            label = ch.mention if ch else f"`{r['channel_id']}`"
            price = r.get("last_price")
            price_s = f"${float(price):,.2f}" if price is not None else "-"
            chg = r.get("last_change")
            chg_s = f"{float(chg):+.2f}%" if chg is not None else "-"
            lines.append(f"`{i}` {label} · **{r['coin_label']}** · {price_s} ({chg_s})")
        embed = panel_embed(
            title="Crypto Feeds",
            color=color.base,
            lines=lines,
            footer=f"{len(rows)} feed(s)",
            timestamp=False,
        )
        await ctx.send(embed=embed)

    @crypto.command(
        name="unsubscribe",
        aliases=["unsub"],
        description="Unsubscribe a crypto feed (channel + coin, or all in channel)",
        example=",crypto unsubscribe #crypto eth",
        usage="[channel] [coin]",
    )
    @has_permissions(manage_guild=True)
    async def crypto_unsubscribe(self, ctx: Context, *, args: str = "") -> None:
        
        await self.crypto_feeds_remove.callback(self, ctx, args=args)

    @hybrid(
        name="unsubscribe",
        description="Unsubscribe a crypto price feed",
        guild_only=True,
        example=",unsubscribe #crypto eth",
    )
    @has_permissions(manage_guild=True)
    @describe(args="Optional #channel and coin (empty = clear channel feeds)")
    async def unsubscribe(self, ctx: Context, *, args: str = "") -> None:
        """Top-level alias for crypto feed removal."""
        await self.crypto_feeds_remove.callback(self, ctx, args=args)

    @hybrid(
        name="btc",
        description="Check the current Bitcoin price",
        guild_only=True,
    )
    async def btc(self, ctx: Context) -> None:
        data = await self._fetch_price("bitcoin")
        if data is None:
            await ctx.fail("Could not fetch Bitcoin price.")
            return
        coin_id, symbol, name, thumb = resolve_coin("btc")  # type: ignore[misc]
        await ctx.send(
            embed=self._price_embed(
                coin_id=coin_id,
                symbol=symbol,
                name=name,
                data=data,
                thumbnail=thumb,
            )
        )

    @hybrid(
        name="eth",
        description="Check the current Ethereum price",
        guild_only=True,
    )
    async def eth(self, ctx: Context) -> None:
        data = await self._fetch_price("ethereum")
        if data is None:
            await ctx.fail("Could not fetch Ethereum price.")
            return
        coin_id, symbol, name, thumb = resolve_coin("eth")  # type: ignore[misc]
        await ctx.send(
            embed=self._price_embed(
                coin_id=coin_id,
                symbol=symbol,
                name=name,
                data=data,
                thumbnail=thumb,
            )
        )

    @hybrid(
        name="sol",
        description="Check the current Solana price",
        guild_only=True,
    )
    async def sol(self, ctx: Context) -> None:
        data = await self._fetch_price("solana")
        if data is None:
            await ctx.fail("Could not fetch Solana price.")
            return
        coin_id, symbol, name, thumb = resolve_coin("sol")  # type: ignore[misc]
        await ctx.send(
            embed=self._price_embed(
                coin_id=coin_id,
                symbol=symbol,
                name=name,
                data=data,
                thumbnail=thumb,
            )
        )

    @hybrid(
        name="gas",
        description="View the current ETH gas prices",
        guild_only=True,
    )
    async def gas(self, ctx: Context) -> None:
        """Fetch ETH gas from keyless public endpoints."""
        result: dict | None = None
        source = "Ethereum"

        session = await self._http()
        
        try:
            async with session.get(
                "https://ethgasstation.info/api/ethgasAPI.json",
                timeout=aiohttp.ClientTimeout(total=8),
            ) as resp:
                if resp.status == 200:
                    data = await resp.json(content_type=None)
                    if isinstance(data, dict) and data.get("safeLow") is not None:

                        def _gwei(v) -> str:
                            try:
                                return f"{float(v) / 10:.1f}"
                            except Exception:
                                return "N/A"

                        result = {
                            "low": _gwei(data.get("safeLow")),
                            "avg": _gwei(data.get("average") or data.get("avg")),
                            "fast": _gwei(data.get("fast")),
                        }
                        source = "ETH Gas Station"
        except Exception:
            pass

        
        if result is None:
            try:
                async with session.get(
                    "https://beaconcha.in/api/v1/execution/gasnow",
                    timeout=aiohttp.ClientTimeout(total=8),
                ) as resp:
                    if resp.status == 200:
                        data = await resp.json(content_type=None)
                        payload = data.get("data") if isinstance(data, dict) else None
                        if isinstance(payload, dict):

                            def _from_wei(v) -> str:
                                try:
                                    n = float(v)
                                    if n > 1_000_000:
                                        n = n / 1e9
                                    return f"{n:.1f}"
                                except Exception:
                                    return "N/A"

                            low = (
                                payload.get("standard")
                                or payload.get("slow")
                                or payload.get("safeLow")
                            )
                            avg = (
                                payload.get("rapid")
                                or payload.get("average")
                                or payload.get("standard")
                            )
                            fast = payload.get("fast") or payload.get("rapid")
                            if low is not None or avg is not None or fast is not None:
                                result = {
                                    "low": _from_wei(low),
                                    "avg": _from_wei(avg),
                                    "fast": _from_wei(fast),
                                }
                                source = "beaconcha.in"
            except Exception:
                pass

        
        if result is None:
            try:
                async with session.get(
                    "https://www.etherchain.org/api/gasPriceOracle",
                    timeout=aiohttp.ClientTimeout(total=8),
                ) as resp:
                    if resp.status == 200:
                        data = await resp.json(content_type=None)
                        if isinstance(data, dict) and (
                            data.get("safeLow") is not None
                            or data.get("standard") is not None
                        ):

                            def _s(v) -> str:
                                try:
                                    return f"{float(v):.1f}"
                                except Exception:
                                    return "N/A"

                            result = {
                                "low": _s(data.get("safeLow") or data.get("slow")),
                                "avg": _s(data.get("standard") or data.get("average")),
                                "fast": _s(data.get("fast")),
                            }
                            source = "etherchain.org"
            except Exception:
                pass

        
        if result is None:
            try:
                from config import api as api_cfg

                key = (
                    getattr(getattr(api_cfg, "etherscan", None), "key", None)
                    or getattr(api_cfg, "etherscan_key", None)
                    or ""
                )
            except Exception:
                key = ""
            key = str(key or "").strip()
            if key and key not in {"YourApiKeyToken", "changeme", "none"}:
                try:
                    async with session.get(
                        "https://api.etherscan.io/api",
                        params={
                            "module": "gastracker",
                            "action": "gasoracle",
                            "apikey": key,
                        },
                        timeout=aiohttp.ClientTimeout(total=8),
                    ) as resp:
                        if resp.status == 200:
                            data = await resp.json(content_type=None)
                            raw = data.get("result") if isinstance(data, dict) else None
                            if isinstance(raw, dict) and raw.get("SafeGasPrice") is not None:
                                result = {
                                    "low": str(raw.get("SafeGasPrice", "N/A")),
                                    "avg": str(raw.get("ProposeGasPrice", "N/A")),
                                    "fast": str(raw.get("FastGasPrice", "N/A")),
                                }
                                source = "Etherscan"
                except Exception:
                    pass

        if not result:
            await ctx.fail("Could not fetch gas prices right now. Try again shortly.")
            return

        embed = panel_embed(
            title="ETH Gas Prices",
            color=color.base,
            lines=[],
            footer=f"Powered by {source}",
            timestamp=False,
        )
        embed.add_field(name="Low", value=f"{result.get('low', 'N/A')} Gwei", inline=True)
        embed.add_field(
            name="Average", value=f"{result.get('avg', 'N/A')} Gwei", inline=True
        )
        embed.add_field(name="Fast", value=f"{result.get('fast', 'N/A')} Gwei", inline=True)
        await ctx.send(embed=embed)

    @hybrid(
        name="transaction",
        description="Get information about a BTC, LTC or ETH transaction",
        aliases=["txid", "tx"],
        guild_only=True,
    )
    @describe(hash="Transaction hash")
    async def transaction(self, ctx: Context, *, hash: str) -> None:
        embed = panel_embed(
            title="Transaction Lookup",
            color=color.base,
            lines=[
                f"[View on Blockchain](https://www.blockchain.com/btc/tx/{hash})",
                f"[View on Etherscan](https://etherscan.io/tx/{hash})",
                f"[View on Blockchair (LTC)](https://blockchair.com/litecoin/transaction/{hash})",
            ],
            footer="Click a link to view the transaction on the respective explorer",
            timestamp=False,
        )
        await ctx.send(embed=embed)

    @hybrid(
        name="subscribe",
        description="Subscribe to a bitcoin transaction for one confirmation",
        aliases=["sub"],
        guild_only=True,
    )
    @describe(hash="Transaction hash to watch")
    async def subscribe(self, ctx: Context, *, hash: str) -> None:
        embed = c2(
            title="Transaction Subscribed",
            message=f"Now watching `{hash}` for confirmations.",
            color=color.base,
            timestamp=False,
        )
        embed.set_footer(text="You'll be notified when the transaction is confirmed")
        await ctx.send(embed=embed)

    

    @tasks.loop(seconds=_FEED_POLL_SECONDS)
    async def _feed_loop(self) -> None:
        if getattr(getattr(self.bot, "db", None), "pool", None) is None:
            return
        await self._ensure_schema()
        try:
            rows = await self.bot.db.fetch("SELECT * FROM crypto_feeds")
        except Exception as exc:
            log.debug("crypto feed fetch failed: %s", exc)
            return
        if not rows:
            return

        by_coin: dict[str, list[dict]] = {}
        for r in rows:
            by_coin.setdefault(str(r["coin_id"]), []).append(dict(r))

        prices = await self._fetch_prices(list(by_coin.keys()))
        if not prices:
            return

        for coin_id, feed_rows in by_coin.items():
            data = prices.get(coin_id)
            if not isinstance(data, dict) or data.get("usd") is None:
                continue
            resolved = resolve_coin(coin_id)
            if not resolved:
                continue
            _id, symbol, name, thumb = resolved

            for row in feed_rows:
                try:
                    if not self._should_post_update(row, data):
                        
                        
                        last_posted = row.get("last_posted")
                        if last_posted is not None and row.get("last_price") is not None:
                            continue
                        await self.bot.db.execute(
                            """
                            UPDATE crypto_feeds
                               SET last_price = $1, last_change = $2, last_market_cap = $3
                             WHERE guild_id = $4 AND channel_id = $5 AND coin_id = $6
                            """,
                            float(data.get("usd") or 0),
                            float(data.get("usd_24h_change") or 0),
                            float(data.get("usd_market_cap") or 0),
                            row["guild_id"],
                            row["channel_id"],
                            coin_id,
                        )
                        continue

                    guild = self.bot.get_guild(int(row["guild_id"]))
                    if guild is None:
                        continue
                    channel = guild.get_channel(int(row["channel_id"]))
                    if channel is None or not isinstance(channel, discord.TextChannel):
                        continue

                    prev_price = row.get("last_price")
                    price = float(data.get("usd") or 0)
                    move = ""
                    if prev_price is not None:
                        try:
                            pp = float(prev_price)
                            if pp > 0:
                                pct = (price - pp) / pp * 100.0
                                move = f" · {pct:+.2f}% since last alert"
                        except Exception:
                            pass

                    embed = self._price_embed(
                        coin_id=coin_id,
                        symbol=symbol,
                        name=name,
                        data=data,
                        thumbnail=thumb,
                        footer=f"Crypto feed · {move}",
                    )
                    try:
                        await channel.send(embed=embed)
                    except discord.HTTPException as exc:
                        if exc.status == 429:
                            retry = float(getattr(exc, "retry_after", 2.0) or 2.0)
                            await asyncio.sleep(min(max(retry, 1.0), 20.0))
                        continue
                    except Exception:
                        continue

                    await self.bot.db.execute(
                        """
                        UPDATE crypto_feeds
                           SET last_price = $1,
                               last_change = $2,
                               last_market_cap = $3,
                               last_posted = $4
                         WHERE guild_id = $5 AND channel_id = $6 AND coin_id = $7
                        """,
                        float(data.get("usd") or 0),
                        float(data.get("usd_24h_change") or 0),
                        float(data.get("usd_market_cap") or 0),
                        _now_naive(),
                        row["guild_id"],
                        row["channel_id"],
                        coin_id,
                    )
                    
                    await asyncio.sleep(0.6)
                except Exception as exc:
                    log.debug("crypto feed post failed: %s", exc)
                    continue

    @_feed_loop.before_loop
    async def _before_feed_loop(self) -> None:
        await self.bot.wait_until_ready()


async def setup(bot: commands.Bot):
    await bot.add_cog(Crypto(bot))
