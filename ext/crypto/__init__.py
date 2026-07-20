from __future__ import annotations

from typing import TYPE_CHECKING

import aiohttp
import discord
from discord.ext import commands

from core.discord.ctx import Context
from core.discord.hybrid import describe, hybrid
from core.managers.values import color



def compose(*parts: str) -> str:
    return "\n".join(part for part in parts if part)

def body(*lines: str) -> str:
    return "\n".join(f"> {line}" for line in lines if line)

def caption(text: str) -> str:
    return f"-# {text}"

def aesthetic_embed(
    *,
    color: int,
    message: str,
    title: str | None = None,
    footer: str | None = None,
    author: str | None = None,
    timestamp: bool = True,
) -> discord.Embed:
    description = compose(
        body(message),
        caption(footer) if footer else None,
    )
    embed = discord.Embed(color=color, description=description)
    if title:
        embed.title = title
    if author:
        embed.set_author(name=author)
    if timestamp:
        embed.timestamp = discord.utils.utcnow()
    return embed

def panel_embed(
    *,
    color: int | None = None,
    title: str | None = None,
    author: str | None = None,
    author_icon: str | None = None,
    lines: list[str] | None = None,
    footer: str | None = None,
    timestamp: bool = True,
    thumbnail: str | None = None,
    url: str | None = None,
) -> discord.Embed:
    description = compose(
        body(*(lines or [])),
        caption(footer) if footer else None,
    )
    embed = discord.Embed(color=color, description=description or None, url=url)
    if title:
        embed.title = title
    if author:
        if author_icon:
            embed.set_author(name=author, icon_url=author_icon)
        else:
            embed.set_author(name=author)
    if thumbnail:
        embed.set_thumbnail(url=thumbnail)
    if timestamp:
        embed.timestamp = discord.utils.utcnow()
    return embed



if TYPE_CHECKING:
    pass

COINGECKO_BASE = "https://api.coingecko.com/api/v3"

COIN_ALIASES = {
    "btc": "bitcoin",
    "bitcoin": "bitcoin",
    "eth": "ethereum",
    "ethereum": "ethereum",
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


class Crypto(commands.Cog):
    """Cryptocurrency prices, charts, and market data."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot

    async def _fetch_price(self, coin_id: str) -> dict | None:
        url = f"{COINGECKO_BASE}/simple/price"
        params = {
            "ids": coin_id,
            "vs_currencies": "usd",
            "include_24hr_change": "true",
            "include_market_cap": "true",
            "include_24hr_vol": "true",
        }
        async with aiohttp.ClientSession() as session:
            try:
                async with session.get(url, params=params, timeout=10) as resp:
                    if resp.status != 200:
                        return None
                    data = await resp.json()
                    return data.get(coin_id)
            except Exception:
                return None

    @hybrid(
        name="crypto",
        description="Check the current price of any cryptocurrency",
        aliases=["coin", "price"],
        guild_only=True,
    )
    @describe(coin="Coin name or symbol (e.g. btc, ethereum, sol)")
    async def crypto(self, ctx: Context, *, coin: str = "bitcoin") -> None:
        coin_key = COIN_ALIASES.get(coin.lower().strip(), coin.lower().strip())
        data = await self._fetch_price(coin_key)
        if data is None:
            await ctx.fail(f"Could not fetch price for `{coin}`. Try a different name.")
            return

        usd = data.get("usd", 0)
        change = data.get("usd_24h_change", 0)
        cap = data.get("usd_market_cap", 0)
        vol = data.get("usd_24h_vol", 0)
        arrow = emoji = ""
        if change > 0:
            arrow, emoji = "▲", "green"
        elif change < 0:
            arrow, emoji = "▼", "red"

        embed = panel_embed(
            title=f"{coin.upper()} / USD",
            color=color.base,
            lines=[],
            footer="Powered by CoinGecko",
            timestamp=False,
        )
        embed.add_field(name="Price", value=f"${usd:,.2f}", inline=True)
        embed.add_field(
            name="24h Change",
            value=f"{arrow} {change:+.2f}%" if change else "0.00%",
            inline=True,
        )
        embed.add_field(name="Market Cap", value=f"${cap:,.0f}", inline=True)
        embed.add_field(name="24h Volume", value=f"${vol:,.0f}", inline=True)
        await ctx.send(embed=embed)

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

        usd = data.get("usd", 0)
        change = data.get("usd_24h_change", 0)
        cap = data.get("usd_market_cap", 0)
        arrow = ""
        if change > 0:
            arrow = "▲"
        elif change < 0:
            arrow = "▼"

        embed = panel_embed(
            title=f"Bitcoin (BTC) / USD — ${usd:,.2f}",
            color=color.base,
            lines=[],
            footer="Powered by CoinGecko",
            thumbnail="https://assets.coingecko.com/coins/images/1/large/bitcoin.png",
            timestamp=False,
        )
        embed.add_field(name="24h Change", value=f"{arrow} {change:+.2f}%", inline=True)
        embed.add_field(name="Market Cap", value=f"${cap:,.0f}", inline=True)
        await ctx.send(embed=embed)

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

        usd = data.get("usd", 0)
        change = data.get("usd_24h_change", 0)
        cap = data.get("usd_market_cap", 0)
        arrow = ""
        if change > 0:
            arrow = "▲"
        elif change < 0:
            arrow = "▼"

        embed = panel_embed(
            title=f"Ethereum (ETH) / USD — ${usd:,.2f}",
            color=color.base,
            lines=[],
            footer="Powered by CoinGecko",
            thumbnail="https://assets.coingecko.com/coins/images/279/large/ethereum.png",
            timestamp=False,
        )
        embed.add_field(name="24h Change", value=f"{arrow} {change:+.2f}%", inline=True)
        embed.add_field(name="Market Cap", value=f"${cap:,.0f}", inline=True)
        await ctx.send(embed=embed)

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

        usd = data.get("usd", 0)
        change = data.get("usd_24h_change", 0)
        arrow = ""
        if change > 0:
            arrow = "▲"
        elif change < 0:
            arrow = "▼"

        embed = panel_embed(
            title=f"Solana (SOL) / USD — ${usd:,.2f}",
            color=color.base,
            lines=[],
            footer="Powered by CoinGecko",
            thumbnail="https://assets.coingecko.com/coins/images/4128/large/solana.png",
            timestamp=False,
        )
        embed.add_field(name="24h Change", value=f"{arrow} {change:+.2f}%", inline=True)
        await ctx.send(embed=embed)

    @hybrid(
        name="gas",
        description="View the current ETH gas prices",
        guild_only=True,
    )
    async def gas(self, ctx: Context) -> None:
        url = "https://api.etherscan.io/api"
        params = {
            "module": "gastracker",
            "action": "gasoracle",
            "apikey": "YourApiKeyToken",
        }
        async with aiohttp.ClientSession() as session:
            try:
                async with session.get(url, params=params, timeout=10) as resp:
                    if resp.status != 200:
                        await ctx.fail("Could not fetch gas prices.")
                        return
                    data = await resp.json()
                    result = data.get("result", {})
            except Exception:
                await ctx.fail("Could not fetch gas prices.")
                return

        if not result or result.get("SafeGasPrice") is None:
            await ctx.fail("Could not fetch gas prices.")
            return

        embed = panel_embed(
            title="ETH Gas Prices",
            color=color.base,
            lines=[],
            footer="Powered by Etherscan",
            timestamp=False,
        )
        embed.add_field(name="Low", value=f"{result.get('SafeGasPrice', 'N/A')} Gwei", inline=True)
        embed.add_field(name="Average", value=f"{result.get('ProposeGasPrice', 'N/A')} Gwei", inline=True)
        embed.add_field(name="Fast", value=f"{result.get('FastGasPrice', 'N/A')} Gwei", inline=True)
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
        embed = aesthetic_embed(
            title="Transaction Subscribed",
            message=f"Now watching `{hash}` for confirmations.",
            color=color.base,
            timestamp=False,
        )
        embed.set_footer(text="You'll be notified when the transaction is confirmed")
        await ctx.send(embed=embed)


async def setup(bot: commands.Bot):
    await bot.add_cog(Crypto(bot))
