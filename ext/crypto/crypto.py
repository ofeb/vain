from __future__ import annotations

from typing import TYPE_CHECKING

import aiohttp
import discord
from discord.ext import commands

from core.discord.ctx import Context
from core.discord.hybrid import describe, hybrid
from core.managers.values import color

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

        embed = discord.Embed(
            title=f"{coin.upper()} / USD",
            color=color.base,
        )
        embed.add_field(name="Price", value=f"${usd:,.2f}", inline=True)
        embed.add_field(
            name="24h Change",
            value=f"{arrow} {change:+.2f}%" if change else "0.00%",
            inline=True,
        )
        embed.add_field(name="Market Cap", value=f"${cap:,.0f}", inline=True)
        embed.add_field(name="24h Volume", value=f"${vol:,.0f}", inline=True)
        embed.set_footer(text="Powered by CoinGecko")
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

        embed = discord.Embed(
            title=f"Bitcoin (BTC) / USD — ${usd:,.2f}",
            color=color.base,
        )
        embed.add_field(name="24h Change", value=f"{arrow} {change:+.2f}%", inline=True)
        embed.add_field(name="Market Cap", value=f"${cap:,.0f}", inline=True)
        embed.set_thumbnail(url="https://assets.coingecko.com/coins/images/1/large/bitcoin.png")
        embed.set_footer(text="Powered by CoinGecko")
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

        embed = discord.Embed(
            title=f"Ethereum (ETH) / USD — ${usd:,.2f}",
            color=color.base,
        )
        embed.add_field(name="24h Change", value=f"{arrow} {change:+.2f}%", inline=True)
        embed.add_field(name="Market Cap", value=f"${cap:,.0f}", inline=True)
        embed.set_thumbnail(url="https://assets.coingecko.com/coins/images/279/large/ethereum.png")
        embed.set_footer(text="Powered by CoinGecko")
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

        embed = discord.Embed(
            title=f"Solana (SOL) / USD — ${usd:,.2f}",
            color=color.base,
        )
        embed.add_field(name="24h Change", value=f"{arrow} {change:+.2f}%", inline=True)
        embed.set_thumbnail(url="https://assets.coingecko.com/coins/images/4128/large/solana.png")
        embed.set_footer(text="Powered by CoinGecko")
        await ctx.send(embed=embed)


async def setup(bot: commands.Bot):
    await bot.add_cog(Crypto(bot))
