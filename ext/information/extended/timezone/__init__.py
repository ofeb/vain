from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

import pytz
from discord import Member
from discord.ext.commands import has_permissions

from core.discord.package import Package
from core.discord.hybrid import hybrid, describe
from core.discord.views.embed import c2


COUNTRY_TO_TZ: dict[str, str] = {
    "afghanistan": "Asia/Kabul",
    "albania": "Europe/Tirane",
    "algeria": "Africa/Algiers",
    "andorra": "Europe/Andorra",
    "angola": "Africa/Luanda",
    "antigua": "America/Antigua",
    "argentina": "America/Argentina/Buenos_Aires",
    "armenia": "Asia/Yerevan",
    "australia": "Australia/Sydney",
    "austria": "Europe/Vienna",
    "azerbaijan": "Asia/Baku",
    "bahamas": "America/Nassau",
    "bahrain": "Asia/Bahrain",
    "bangladesh": "Asia/Dhaka",
    "barbados": "America/Barbados",
    "belarus": "Europe/Minsk",
    "belgium": "Europe/Brussels",
    "belize": "America/Belize",
    "benin": "Africa/Porto-Novo",
    "bhutan": "Asia/Thimphu",
    "bolivia": "America/La_Paz",
    "bosnia": "Europe/Sarajevo",
    "botswana": "Africa/Gaborone",
    "brazil": "America/Sao_Paulo",
    "brunei": "Asia/Brunei",
    "bulgaria": "Europe/Sofia",
    "burkina": "Africa/Ouagadougou",
    "burundi": "Africa/Bujumbura",
    "cambodia": "Asia/Phnom_Penh",
    "cameroon": "Africa/Douala",
    "canada": "America/Toronto",
    "cape verde": "Atlantic/Cape_Verde",
    "caribbean": "America/Barbados",
    "chad": "Africa/Ndjamena",
    "chile": "America/Santiago",
    "china": "Asia/Shanghai",
    "colombia": "America/Bogota",
    "comoros": "Indian/Comoro",
    "congo": "Africa/Brazzaville",
    "costa rica": "America/Costa_Rica",
    "croatia": "Europe/Zagreb",
    "cuba": "America/Havana",
    "cyprus": "Asia/Nicosia",
    "czech": "Europe/Prague",
    "czechia": "Europe/Prague",
    "denmark": "Europe/Copenhagen",
    "djibouti": "Africa/Djibouti",
    "dominica": "America/Dominica",
    "dominican": "America/Santo_Domingo",
    "east timor": "Asia/Dili",
    "ecuador": "America/Guayaquil",
    "egypt": "Africa/Cairo",
    "el salvador": "America/El_Salvador",
    "england": "Europe/London",
    "equatorial guinea": "Africa/Malabo",
    "eritrea": "Africa/Asmara",
    "estonia": "Europe/Tallinn",
    "eswatini": "Africa/Mbabane",
    "ethiopia": "Africa/Addis_Ababa",
    "fiji": "Pacific/Fiji",
    "finland": "Europe/Helsinki",
    "france": "Europe/Paris",
    "gabon": "Africa/Libreville",
    "gambia": "Africa/Banjul",
    "georgia": "Asia/Tbilisi",
    "germany": "Europe/Berlin",
    "ghana": "Africa/Accra",
    "greece": "Europe/Athens",
    "grenada": "America/Grenada",
    "guatemala": "America/Guatemala",
    "guinea": "Africa/Conakry",
    "guinea-bissau": "Africa/Bissau",
    "guyana": "America/Guyana",
    "haiti": "America/Port-au-Prince",
    "honduras": "America/Tegucigalpa",
    "hungary": "Europe/Budapest",
    "iceland": "Atlantic/Reykjavik",
    "india": "Asia/Kolkata",
    "indonesia": "Asia/Jakarta",
    "iran": "Asia/Tehran",
    "iraq": "Asia/Baghdad",
    "ireland": "Europe/Dublin",
    "israel": "Asia/Jerusalem",
    "italy": "Europe/Rome",
    "ivory coast": "Africa/Abidjan",
    "jamaica": "America/Jamaica",
    "japan": "Asia/Tokyo",
    "jordan": "Asia/Amman",
    "kazakhstan": "Asia/Almaty",
    "kenya": "Africa/Nairobi",
    "kiribati": "Pacific/Tarawa",
    "kosovo": "Europe/Belgrade",
    "kuwait": "Asia/Kuwait",
    "kyrgyzstan": "Asia/Bishkek",
    "laos": "Asia/Vientiane",
    "latvia": "Europe/Riga",
    "lebanon": "Asia/Beirut",
    "lesotho": "Africa/Maseru",
    "liberia": "Africa/Monrovia",
    "libya": "Africa/Tripoli",
    "liechtenstein": "Europe/Vaduz",
    "lithuania": "Europe/Vilnius",
    "luxembourg": "Europe/Luxembourg",
    "madagascar": "Indian/Antananarivo",
    "malawi": "Africa/Blantyre",
    "malaysia": "Asia/Kuala_Lumpur",
    "maldives": "Indian/Maldives",
    "mali": "Africa/Bamako",
    "malta": "Europe/Malta",
    "mauritania": "Africa/Nouakchott",
    "mauritius": "Indian/Mauritius",
    "mexico": "America/Mexico_City",
    "moldova": "Europe/Chisinau",
    "monaco": "Europe/Monaco",
    "mongolia": "Asia/Ulaanbaatar",
    "montenegro": "Europe/Podgorica",
    "morocco": "Africa/Casablanca",
    "mozambique": "Africa/Maputo",
    "myanmar": "Asia/Yangon",
    "namibia": "Africa/Windhoek",
    "nauru": "Pacific/Nauru",
    "nepal": "Asia/Kathmandu",
    "netherlands": "Europe/Amsterdam",
    "new zealand": "Pacific/Auckland",
    "nicaragua": "America/Managua",
    "niger": "Africa/Niamey",
    "nigeria": "Africa/Lagos",
    "north korea": "Asia/Pyongyang",
    "north macedonia": "Europe/Skopje",
    "norway": "Europe/Oslo",
    "oman": "Asia/Muscat",
    "pakistan": "Asia/Karachi",
    "palau": "Pacific/Palau",
    "palestine": "Asia/Gaza",
    "panama": "America/Panama",
    "papua new guinea": "Pacific/Port_Moresby",
    "paraguay": "America/Asuncion",
    "peru": "America/Lima",
    "philippines": "Asia/Manila",
    "poland": "Europe/Warsaw",
    "portugal": "Europe/Lisbon",
    "qatar": "Asia/Qatar",
    "romania": "Europe/Bucharest",
    "russia": "Europe/Moscow",
    "rwanda": "Africa/Kigali",
    "saint kitts": "America/St_Kitts",
    "saint lucia": "America/St_Lucia",
    "saint vincent": "America/St_Vincent",
    "samoa": "Pacific/Apia",
    "san marino": "Europe/San_Marino",
    "sao tome": "Africa/Sao_Tome",
    "saudi arabia": "Asia/Riyadh",
    "scotland": "Europe/London",
    "senegal": "Africa/Dakar",
    "serbia": "Europe/Belgrade",
    "seychelles": "Indian/Mahe",
    "sierra leone": "Africa/Freetown",
    "singapore": "Asia/Singapore",
    "slovakia": "Europe/Bratislava",
    "slovenia": "Europe/Ljubljana",
    "solomon islands": "Pacific/Guadalcanal",
    "somalia": "Africa/Mogadishu",
    "south africa": "Africa/Johannesburg",
    "south korea": "Asia/Seoul",
    "south sudan": "Africa/Juba",
    "spain": "Europe/Madrid",
    "sri lanka": "Asia/Colombo",
    "sudan": "Africa/Khartoum",
    "suriname": "America/Paramaribo",
    "sweden": "Europe/Stockholm",
    "switzerland": "Europe/Zurich",
    "syria": "Asia/Damascus",
    "taiwan": "Asia/Taipei",
    "tajikistan": "Asia/Dushanbe",
    "tanzania": "Africa/Dar_es_Salaam",
    "thailand": "Asia/Bangkok",
    "togo": "Africa/Lome",
    "tonga": "Pacific/Tongatapu",
    "trinidad": "America/Port_of_Spain",
    "tunisia": "Africa/Tunis",
    "turkey": "Europe/Istanbul",
    "turkmenistan": "Asia/Ashgabat",
    "tuvalu": "Pacific/Funafuti",
    "uganda": "Africa/Kampala",
    "ukraine": "Europe/Kiev",
    "united arab emirates": "Asia/Dubai",
    "uae": "Asia/Dubai",
    "united kingdom": "Europe/London",
    "uk": "Europe/London",
    "united states": "America/New_York",
    "us": "America/New_York",
    "usa": "America/New_York",
    "uruguay": "America/Montevideo",
    "uzbekistan": "Asia/Tashkent",
    "vanuatu": "Pacific/Efate",
    "vatican": "Europe/Vatican",
    "venezuela": "America/Caracas",
    "vietnam": "Asia/Ho_Chi_Minh",
    "wales": "Europe/London",
    "yemen": "Asia/Aden",
    "zambia": "Africa/Lusaka",
    "zimbabwe": "Africa/Harare",
}


def _resolve_timezone(raw: str) -> Optional[str]:
    """Resolve a user-provided string to an IANA timezone.

    Tries in order:
    1. Direct pytz lookup (e.g. "Europe/Dublin")
    2. Case-insensitive country name lookup
    3. Partial / fuzzy match on country names
    """
    s = raw.strip()
    if not s:
        return None

    try:
        tz = pytz.timezone(s)
        return str(tz)
    except pytz.exceptions.UnknownTimeZoneError:
        pass

    lower = s.lower()
    if lower in COUNTRY_TO_TZ:
        resolved = COUNTRY_TO_TZ[lower]
        try:
            pytz.timezone(resolved)
            return resolved
        except pytz.exceptions.UnknownTimeZoneError:
            pass

    matches = [
        (country, tz)
        for country, tz in COUNTRY_TO_TZ.items()
        if lower in country or country in lower
    ]
    if len(matches) == 1:
        return matches[0][1]

    return None


def _time_period(hour: int) -> str:
    if 0 <= hour < 6:
        return "early morning"
    elif 6 <= hour < 12:
        return "morning"
    elif 12 <= hour < 17:
        return "afternoon"
    elif 17 <= hour < 21:
        return "evening"
    else:
        return "night"


def _get_guild_id(ctx) -> int:
    """Get a suitable guild ID for database storage.
    
    In DMs, returns 0 (global storage).
    In group chats, returns the channel ID.
    In servers, returns the guild ID.
    """
    if ctx.guild is None:
        
        return getattr(ctx, 'channel', None) and ctx.channel.id or 0
    return ctx.guild.id


class Timezone(Package):
    """timezone management"""

    def __init__(self, bot):
        self.bot = bot

    @hybrid(
        name="timezone",
        aliases=["tz"],
        description="View your current time or somebody elses",
        group=True,
    )
    @describe(member="The user to check timezone for")
    async def timezone(self, ctx, member: Optional[Member] = None):
        """view timezone"""
        target = member or ctx.author
        guild_id = _get_guild_id(ctx)
        
        tz = await self.bot.db.fetchval(
            "SELECT timezone FROM users WHERE user_id = $1 AND guild_id = $2",
            target.id, guild_id
        )

        if not tz:
            if target.id == ctx.author.id:
                return await ctx.warn("You have not set your timezone\n> -# **set one with:** `,timezone set`")
            return await ctx.warn(
                f"**{target.display_name}** has not set their timezone"
            )

        try:
            user_tz = pytz.timezone(tz)
            current_time = datetime.now(user_tz)
            hour = current_time.hour
            period = _time_period(hour)
            time_str = current_time.strftime("%I:%M").lstrip("0")
            day_str = current_time.strftime("%A").lower()
            if target.id == ctx.author.id:
                msg = f"Your time is **{time_str}** **{day_str}** **{period}**"
            else:
                msg = f"**{target.display_name}'s** time is **{time_str}** **{day_str}** **{period}**"
            await ctx.send(
                embed=c2(
                    message=msg,
                    timestamp=False,
                )
            )
        except pytz.exceptions.UnknownTimeZoneError:
            return await ctx.fail(
                f"Invalid timezone stored for {target.mention}\n"
                f"> -# **zone:** `{tz}` · ask them to reset with `,timezone set`"
            )

    @timezone.command(
        name="set",
        description="Set your timezone",
    )
    async def timezone_set(self, ctx, *, location: str):
        """set timezone"""
        resolved = _resolve_timezone(location)
        if not resolved:
            return await ctx.fail(
                "Please provide a **valid timezone**\n"
                f"> -# **example:** `Europe/Dublin` or a country like `Ireland`"
            )

        guild_id = _get_guild_id(ctx)
        await self.bot.db.execute(
            "INSERT INTO users (user_id, guild_id, timezone) VALUES($1, $2, $3) "
            "ON CONFLICT(user_id, guild_id) DO UPDATE SET timezone = excluded.timezone",
            ctx.author.id, guild_id, resolved
        )
        await ctx.success(
            f"**your** timezone has been set\n"
            f"> -# **location:** {resolved}"
        )

    @timezone.command(
        name="remove",
        aliases=["delete", "del", "reset", "clear"],
        description="Remove your timezone",
    )
    async def timezone_remove(self, ctx):
        """remove timezone"""
        guild_id = _get_guild_id(ctx)
        result = await self.bot.db.execute(
            "UPDATE users SET timezone = NULL WHERE user_id = $1 AND guild_id = $2",
            ctx.author.id, guild_id
        )
        if result == "UPDATE 0":
            return await ctx.warn(
                "You have no timezone set\n"
                f"> -# **set one with:** `,timezone set`"
            )
        await ctx.send(
            embed=c2(
                message=f"**{ctx.author.display_name}'s** timezone removed",
                timestamp=False,
            )
        )

    @timezone.command(
        name="compare",
        description="Compare your time with another member",
    )
    async def timezone_compare(self, ctx, member: Member):
        """compare timezones"""
        if member.id == ctx.author.id:
            return await ctx.warn(
                "You cannot compare with yourself\n"
                f"> -# **usage:** `,timezone compare @user`"
            )

        guild_id = _get_guild_id(ctx)
        
        my_tz_name = await self.bot.db.fetchval(
            "SELECT timezone FROM users WHERE user_id = $1 AND guild_id = $2",
            ctx.author.id, guild_id
        )
        their_tz_name = await self.bot.db.fetchval(
            "SELECT timezone FROM users WHERE user_id = $1 AND guild_id = $2",
            member.id, guild_id
        )

        if not my_tz_name:
            return await ctx.fail(
                "You haven't set your timezone yet\n"
                f"> -# **set one with:** `,timezone set`"
            )
        if not their_tz_name:
            return await ctx.fail(
                f"{member.mention} hasn't set their timezone\n"
                f"> -# **ask them to use:** `,timezone set`"
            )

        try:
            my_tz = pytz.timezone(my_tz_name)
            their_tz = pytz.timezone(their_tz_name)
        except pytz.exceptions.UnknownTimeZoneError:
            return await ctx.fail(
                "One of the stored timezones is invalid\n"
                f"> -# **re-set with:** `,timezone set`"
            )

        my_time = datetime.now(my_tz)
        their_time = datetime.now(their_tz)

        my_period = _time_period(my_time.hour)
        their_period = _time_period(their_time.hour)
        my_str = my_time.strftime("%I:%M").lstrip("0")
        their_str = their_time.strftime("%I:%M").lstrip("0")

        diff_hours = (their_time.utcoffset().total_seconds() - my_time.utcoffset().total_seconds()) / 3600
        if diff_hours == 0:
            diff_str = "same timezone"
        elif diff_hours > 0:
            diff_str = f"+{diff_hours:.1f}h ahead"
        else:
            diff_str = f"{diff_hours:.1f}h behind"

        await ctx.send(
            embed=c2(
                message=(
                    f"**{ctx.author.display_name}** ↔ **{member.display_name}**\n"
                    f"> -# **you:** {my_str} {my_period} ({my_tz_name})\n"
                    f"> -# **them:** {their_str} {their_period} ({their_tz_name})\n"
                    f"> -# **difference:** {diff_str}"
                ),
                timestamp=False,
            )
        )

    @timezone.command(
        name="list",
        description="View a list of every member's timezone",
    )
    async def timezone_list(self, ctx):
        """list all timezones"""
        guild_id = _get_guild_id(ctx)
        
        timezones = await self.bot.db.fetch(
            "SELECT user_id, timezone FROM users WHERE guild_id = $1 AND timezone IS NOT NULL",
            guild_id
        )

        if not timezones:
            return await ctx.warn(
                "No timezones set in this server\n"
                f"> -# **set yours with:** `,timezone set`"
            )

        lines = []
        for tz in timezones:
            
            member = None
            if ctx.guild:
                member = ctx.guild.get_member(tz['user_id'])
            if member:
                try:
                    user_tz = pytz.timezone(tz['timezone'])
                    current_time = datetime.now(user_tz)
                    period = _time_period(current_time.hour)
                    time_str = current_time.strftime("%I:%M").lstrip("0")
                    lines.append(
                        f"> {member.mention} — {time_str} {period} ({tz['timezone']})"
                    )
                except pytz.exceptions.UnknownTimeZoneError:
                    lines.append(f"> {member.mention} — invalid ({tz['timezone']})")

        await ctx.send(
            embed=c2(
                message=f"**all timezones**\n" + "\n".join(lines),
                timestamp=False,
            )
        )
