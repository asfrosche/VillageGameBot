# cogs/location_manager.py
import discord
from discord.ext import commands
import pycountry_convert as pc
from geopy.geocoders import Nominatim, ArcGIS
from geopy.exc import GeocoderUnavailable, GeocoderTimedOut, GeocoderServiceError
import asyncio
import logging
import requests
import functools

from utils.data_manager import save_json, load_json
from utils.map_generator import create_location_map, create_heatmap, map_to_bytes
from config import LOCATIONS_FILE, GEOCODER_USER_AGENT

import math
from datetime import datetime
import pytz
from timezonefinder import TimezoneFinder
import time

logger = logging.getLogger('LocationManager')
logger.setLevel(logging.INFO)
handler = logging.StreamHandler()
handler.setFormatter(logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s'))
logger.addHandler(handler)

LOCATION_HELP_COMMANDS = [
    ("📍 Location Management", [
        (".setloc <@user> <location>", "Set a user's location (Admin)"),
        (".remloc <@user/username>", "Remove a user's location by mention, ID, or username (Admin)"),
        (".mysetloc <location>", "Set your own location"),
        (".myremoveloc", "Remove your own location"),
    ]),
    ("🗺️ Maps", [
        (".mapp", "View the world map of registered users"),
        (".mapheat", "View the heatmap of registered users"),
    ]),
    ("🌎 Regions", [
        (".setcontinent <@user> <continent>", "Manually assign a continent to a user (Admin)"),
        (".listunknown", "List entries with Unknown continent (Admin)"),
    ]),
    ("⏰ Time Utilities", [
        (".localtime <@user>", "View another user's local time"),
        (".lt <@user>", "Alias for .localtime"),
        (".refreshtz", "Refresh timezones for all saved users (Admin)"),
    ]),
    ("📊 Information", [
        (".near <@user>", "Find nearby registered users"),
        (".locstats", "Show location statistics"),
        (".locations", "Show all locations split by continent"),
        (".locsnotset", "Show members who haven't set their location"),
    ]),
    ("🛠️ Moderator Tools", [
        (".forceremloc <username/ID>", "Force remove a location entry (works if user left)"),
        (".forceremoveloc", "Alias for .forceremloc"),
    ]),
]

class LocationManager(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.geolocator = Nominatim(user_agent=GEOCODER_USER_AGENT, timeout=10)
        self.fallback_geolocator = ArcGIS(user_agent=GEOCODER_USER_AGENT, timeout=10)
        
        self.tzfinder = TimezoneFinder()  
        self.map_cache = None
        self.map_cache_time = 0
        self.heat_cache = None
        self.heat_cache_time = 0

    def get_continent(self, country_name):
        if not country_name or country_name == "Unknown":
            return "Unknown"
        normalized = self._normalize_country(country_name)
        try:
            country_code = pc.country_name_to_country_alpha2(normalized)
            return pc.convert_continent_code_to_continent_name(
                pc.country_alpha2_to_continent_code(country_code)
            )
        except:
            try:
                import pycountry
                c = pycountry.countries.get(name=normalized)
                if c:
                    country_code = pc.country_alpha2_to_continent_code(c.alpha_2)
                    return pc.convert_continent_code_to_continent_name(country_code)
            except:
                pass
            return "Unknown"

    @staticmethod
    def _normalize_country(name):
        aliases = {
            "UK": "United Kingdom",
            "U.K.": "United Kingdom",
            "U K": "United Kingdom",
            "US": "United States",
            "U.S.": "United States",
            "U S": "United States",
            "U.S.A": "United States",
            "USA": "United States",
            "America": "United States",
            "The United States": "United States",
            "England": "United Kingdom",
            "Britain": "United Kingdom",
            "Scotland": "United Kingdom",
            "Wales": "United Kingdom",
            "Northern Ireland": "United Kingdom",
            "The Netherlands": "Netherlands",
            "Holland": "Netherlands",
            "Burma": "Myanmar",
            "DR Congo": "Congo",
            "D.R. Congo": "Congo",
            "DRC": "Congo",
            "Congo DRC": "Congo",
            "Democratic Republic of the Congo": "Congo",
            "Congo, Democratic Republic of the": "Congo",
            "Czechia": "Czech Republic",
            "Cabo Verde": "Cape Verde",
            "Eswatini": "Swaziland",
            "North Macedonia": "Macedonia",
            "Timor-Leste": "East Timor",
            "Bosnia": "Bosnia and Herzegovina",
            "Turkiye": "Turkey",
            "T\u00fcrkiye": "Turkey",
            "Antigua": "Antigua and Barbuda",
            "St Vincent": "Saint Vincent and the Grenadines",
            "St. Vincent": "Saint Vincent and the Grenadines",
            "Cote d Ivoire": "C\u00f4te d'Ivoire",
            "Cote d'Ivoire": "C\u00f4te d'Ivoire",
            "Ivory Coast": "C\u00f4te d'Ivoire",
            "Republic of Korea": "Korea, Republic of",
            "South Korea": "Korea, Republic of",
            "Democratic People's Republic of Korea": "Korea, Democratic People's Republic of",
            "North Korea": "Korea, Democratic People's Republic of",
            "Lao Peoples Democratic Republic": "Laos",
            "United Republic of Tanzania": "Tanzania, United Republic of",
            "Tanzania": "Tanzania, United Republic of",
            "Syrian Arab Republic": "Syria",
            "Islamic Republic of Iran": "Iran, Islamic Republic of",
            "Iran": "Iran, Islamic Republic of",
            "Russia": "Russian Federation",
            "Vietnam": "Viet Nam",
            "Laos": "Lao People's Democratic Republic",
            "Federated States of Micronesia": "Micronesia",
            "St Lucia": "Saint Lucia",
            "St. Lucia": "Saint Lucia",
            "St Kitts": "Saint Kitts and Nevis",
            "St. Kitts": "Saint Kitts and Nevis",

            "Lietuva": "Lithuania",
            "Espa\u00f1a": "Spain",
            "Italia": "Italy",
            "Deutschland": "Germany",
            "Nederland": "Netherlands",
            "Vi\u1ec7t Nam": "Viet Nam",
            "Pilipinas": "Philippines",
            "Suomi": "Finland",
            "Sverige": "Sweden",
            "Danmark": "Denmark",
            "Norge": "Norway",
            "Polska": "Poland",
            "\u010cesko": "Czech Republic",
            "Slovensko": "Slovakia",
            "Magyarorsz\u00e1g": "Hungary",
            "Rom\u00e2nia": "Romania",
            "Hrvatska": "Croatia",
            "Srpska": "Serbia",
            "Bulgaria": "Bulgaria",
            "\u0395\u03bb\u03bb\u03ac\u03b4\u03b1": "Greece",
            "T\u00fcrkiye": "Turkey",
            "\u4e2d\u56fd": "China",
            "\u65e5\u672c": "Japan",
            "\ub300\ud55c\ubbfc\uad6d": "Korea, Republic of",
            "Rossiya": "Russian Federation",
            "France": "France",
            "Belgique": "Belgium",
            "Belgi\u00eb": "Belgium",
            "Schweiz": "Switzerland",
            "Suisse": "Switzerland",
            "\u00d6sterreich": "Austria",
            "M\u00e9xico": "Mexico",
            "Brasil": "Brazil",

            "\u0645\u0635\u0631": "Egypt",
            "\u0627\u0644\u0633\u0639\u0648\u062f\u064a\u0629": "Saudi Arabia",
            "\u0627\u0644\u0639\u0631\u0627\u0642": "Iraq",
            "\u0627\u0644\u064a\u0645\u0646": "Yemen",
            "\u0627\u0644\u0643\u0648\u064a\u062a": "Kuwait",
            "\u0642\u0637\u0631": "Qatar",
            "\u0627\u0644\u0625\u0645\u0627\u0631\u0627\u062a": "United Arab Emirates",
            "\u0627\u0644\u0623\u0631\u062f\u0646": "Jordan",
            "\u0644\u0628\u0646\u0627\u0646": "Lebanon",
            "\u0641\u0644\u0633\u0637\u064a\u0646": "Palestine",
            "\u0633\u0648\u0631\u064a\u0627": "Syria",
            "\u0627\u0644\u0645\u063a\u0631\u0628": "Morocco",
            "\u0627\u0644\u062c\u0632\u0627\u0626\u0631": "Algeria",
            "\u062a\u0648\u0646\u0633": "Tunisia",
            "\u0644\u064a\u0628\u064a\u0627": "Libya",
            "\u0627\u0644\u0633\u0648\u062f\u0627\u0646": "Sudan",
        }
        return aliases.get(name, name)

    async def _geocode_with_retry(self, query, max_retries=3):
        for attempt in range(max_retries):
            try:
                logger.info(f"Geocoding attempt {attempt + 1}/{max_retries} for '{query}' using Nominatim (UA: {GEOCODER_USER_AGENT})")
                func = functools.partial(self.geolocator.geocode, query, addressdetails=True)
                loc = await self.bot.loop.run_in_executor(None, func)
                
                if loc:
                    logger.info(f"Nominatim success: {loc.address}")
                    return loc, "Nominatim"
                else:
                    logger.warning(f"Nominatim returned no result for '{query}'")
            
            except (GeocoderUnavailable, GeocoderTimedOut, GeocoderServiceError) as e:
                logger.error(f"Nominatim error on attempt {attempt + 1}: {e}")
                if attempt < max_retries - 1:
                    wait_time = 2 ** attempt
                    logger.info(f"Waiting {wait_time}s before retry...")
                    await asyncio.sleep(wait_time)
                else:
                    logger.warning("Nominatim failed all retries.")

        try:
            logger.info(f"Attempting fallback geocoder (ArcGIS) for '{query}'")
            func = functools.partial(self.fallback_geolocator.geocode, query)
            loc = await self.bot.loop.run_in_executor(None, func)
            
            if loc:
                logger.info(f"ArcGIS success: {loc.address}")
                return loc, "ArcGIS"
            else:
                logger.warning(f"ArcGIS returned no result for '{query}'")
        except Exception as e:
            logger.error(f"ArcGIS fallback failed: {e}")

        return None, None

    @commands.command()
    @commands.has_permissions(administrator=True)
    async def test_geocoder(self, ctx):
        """Test geocoder connectivity and settings"""
        status_msg = []
        status_msg.append(f"**User-Agent:** `{GEOCODER_USER_AGENT}`")
        
        try:
            headers = {'User-Agent': GEOCODER_USER_AGENT}
            start = time.time()
            resp = requests.get('https://nominatim.openstreetmap.org/search?q=London&format=json', headers=headers, timeout=5)
            latency = (time.time() - start) * 1000
            status_msg.append(f"**HTTP Connectivity:** ✅ {resp.status_code} ({latency:.0f}ms)")
            if resp.status_code != 200:
                status_msg.append(f"⚠️ HTTP Error: {resp.text[:100]}")
        except Exception as e:
            status_msg.append(f"**HTTP Connectivity:** ❌ Failed ({str(e)})")

        try:
            start = time.time()
            func = functools.partial(self.geolocator.geocode, "Paris")
            loc = await self.bot.loop.run_in_executor(None, func)
            latency = (time.time() - start) * 1000
            if loc:
                status_msg.append(f"**Nominatim (Geopy):** ✅ Success ({latency:.0f}ms)")
            else:
                status_msg.append(f"**Nominatim (Geopy):** ⚠️ No result found")
        except Exception as e:
            status_msg.append(f"**Nominatim (Geopy):** ❌ Error ({str(e)})")

        try:
            start = time.time()
            func = functools.partial(self.fallback_geolocator.geocode, "Berlin")
            loc = await self.bot.loop.run_in_executor(None, func)
            latency = (time.time() - start) * 1000
            if loc:
                status_msg.append(f"**ArcGIS (Fallback):** ✅ Success ({latency:.0f}ms)")
            else:
                status_msg.append(f"**ArcGIS (Fallback):** ⚠️ No result found")
        except Exception as e:
            status_msg.append(f"**ArcGIS (Fallback):** ❌ Error ({str(e)})")

        await ctx.send("\n".join(status_msg))

    @commands.command()
    @commands.has_permissions(administrator=True)
    async def setloc(self, ctx, member: discord.Member, *, location):
        """Set a user's location (Admin only)"""
        msg = await ctx.send(f"🔍 Searching for '{location}'...")
        
        loc, source = await self._geocode_with_retry(location)
        
        if not loc:
            await msg.edit(content="❌ Location not found or geocoding services unavailable.")
            return
            
        city = "Unknown"
        country = "Unknown"
        
        if source == "Nominatim":
            address = loc.raw.get('address', {})
            city = address.get('city', address.get('town', location))
            country = address.get('country', "Unknown")
        elif source == "ArcGIS":
            parts = [p.strip() for p in loc.address.split(",")]
            country = parts[-1] if len(parts) > 1 else "Unknown"
            if len(parts) >= 3:
                country = parts[-1]
                city = parts[-3]
            elif len(parts) == 2:
                country = parts[-1]
                city = parts[0]
            else:
                country = "Unknown"
                city = parts[0] if parts else location

        data = load_json(LOCATIONS_FILE)
        
        data[str(member.id)] = {
            "username": member.display_name,
            "city": city,
            "country": country,
            "continent": self.get_continent(country),
            "lat": loc.latitude,
            "lon": loc.longitude,
            "timezone": self.tzfinder.timezone_at(lat=loc.latitude, lng=loc.longitude) or "UTC"
        }

        save_json(LOCATIONS_FILE, data)
        await msg.edit(content=f"📍 Location set for {member.display_name} via {source}!")
    
    @commands.command()
    @commands.has_permissions(administrator=True)
    async def setcontinent(self, ctx, member: discord.Member, *, continent: str):
        """Manually set the continent for a user's location (Admin only)"""
        continent_map = {
            "NA": "North America", "north america": "North America",
            "SA": "South America", "south america": "South America",
            "EU": "Europe", "europe": "Europe",
            "asia": "Asia",
            "AF": "Africa", "africa": "Africa",
            "AU": "Australia", "australia": "Australia", "oceania": "Oceania", "OC": "Oceania",
            "AQ": "Antarctica", "antarctica": "Antarctica",
        }
        full = continent_map.get(continent, continent if continent[0].isupper() else continent.title())
        if full not in continent_map.values():
            valid = ", ".join(sorted(set(continent_map.values())))
            return await ctx.send(f"❌ Invalid continent. Valid: {valid}")

        data = load_json(LOCATIONS_FILE)
        uid = str(member.id)
        if uid not in data:
            return await ctx.send(f"⚠️ No location found for {member.display_name}.")

        data[uid]["continent"] = full
        save_json(LOCATIONS_FILE, data)
        await ctx.send(f"✅ Continent for {member.display_name} set to **{full}**.")

    @commands.command()
    @commands.has_permissions(administrator=True)
    async def listunknown(self, ctx):
        """List entries with Unknown continent"""
        data = load_json(LOCATIONS_FILE)
        unknowns = [(uid, info) for uid, info in data.items() if info.get("continent") == "Unknown"]
        if not unknowns:
            return await ctx.send("✅ No entries with Unknown continent.")

        lines = [f"**{len(unknowns)}** entries with Unknown continent:"]
        for uid, info in unknowns:
            name = info.get("username", "?")
            country = info.get("country", "?")
            lines.append(f"• **{name}** (ID: {uid}) — country: {country}")
        embed = discord.Embed(title="⚠️ Unknown Continents", description="\n".join(lines)[:4096], color=0xFEE75C)
        await ctx.send(embed=embed)

    @commands.command()
    @commands.has_permissions(administrator=True)
    async def remloc(self, ctx, *, query: str = None):
        """Remove a user's location by @mention, ID, or username (Admin only)"""
        data = load_json(LOCATIONS_FILE)

        if query is None and ctx.message.reference and isinstance(ctx.message.reference.resolved, discord.Message):
            replied = ctx.message.reference.resolved
            query = str(replied.author.id)

        if query is None:
            return await ctx.send("Usage: `.remloc <@user>` or `.remloc <username>` or reply to their message.")

        query = query.strip().strip("\"'")
        member = None
        try:
            member = await commands.MemberConverter().convert(ctx, query)
        except:
            pass

        if member:
            uid = str(member.id)
            if uid in data:
                name = data[uid].get("username", member.display_name)
                del data[uid]
                save_json(LOCATIONS_FILE, data)
                return await ctx.send(f"❌ Location removed for **{name}**!")
            else:
                return await ctx.send(f"⚠️ No location found for **{member.display_name}**.")

        matched = [(uid, info) for uid, info in data.items() if info.get("username", "").lower() == query.lower()]
        if not matched:
            return await ctx.send(f"⚠️ No location found for `{query}`.")
        if len(matched) > 1:
            lines = [f"Multiple matches for `{query}`:"] + [f"• **{info['username']}** (ID: {uid})" for uid, info in matched]
            return await ctx.send("\n".join(lines))
        uid, info = matched[0]
        name = info.get("username", uid)
        del data[uid]
        save_json(LOCATIONS_FILE, data)
        await ctx.send(f"❌ Location removed for **{name}** (ID: {uid}).")
    
    @commands.command()
    async def locations(self, ctx):
        """Show all locations split by continent with navigation buttons"""
        data = load_json(LOCATIONS_FILE)
        if not data:
            return await ctx.send("No locations set yet!")

        view = LocationsView(data, ctx.guild)
        first_cont, first_info = view.sorted_continents[0]
        embed = view._build_embed(first_cont, first_info)
        await ctx.send(embed=embed, view=view)

    @commands.command()
    async def locsnotset(self, ctx):
        """Show members who haven't set their location"""
        data = load_json(LOCATIONS_FILE)
        missing = [m for m in ctx.guild.members if not m.bot and str(m.id) not in data]
        if not missing:
            return await ctx.send("✅ All members have set their location!")

        lines = [f"**{len(missing)}** members haven't set their location:"]
        for m in missing:
            lines.append(f"• {m.mention} ({m.display_name})")
        embed = discord.Embed(
            title="📍 Missing Locations",
            description="\n".join(lines)[:4096],
            color=0xED4245
        )
        await ctx.send(embed=embed)

    @commands.command()
    async def mapp(self, ctx):
        """View the world map of registered users"""
        data = load_json(LOCATIONS_FILE)
        if not data:
            return await ctx.send("No locations set yet!")

        for uid, info in data.items():
            if "username" not in info:
                user = ctx.guild.get_member(int(uid))
                info["username"] = user.display_name if user else f"User-{uid}"

        if self.map_cache and (time.time() - self.map_cache_time < 600):
            return await ctx.send(
                content="**User Locations Map** (cached)\nDownload:",
                file=discord.File(self.map_cache, filename="user_map.html")
            )

        m = create_location_map(data)
        buf = map_to_bytes(m)

        self.map_cache = buf
        self.map_cache_time = time.time()

        await ctx.send(
            content="**User Locations Map**\nDownload:",
            file=discord.File(buf, filename="user_map.html")
        )

    @commands.command()
    async def mapheat(self, ctx):
        """Generate heatmap (Fast + Cached)"""
        data = load_json(LOCATIONS_FILE)
        if not data:
            return await ctx.send("No locations set yet!")

        if self.heat_cache and (time.time() - self.heat_cache_time < 600):
            return await ctx.send(
                content="**User Locations Heatmap** (cached)\nDownload:",
                file=discord.File(self.heat_cache, filename="heatmap.html")
            )

        m = create_heatmap(data)
        buf = map_to_bytes(m)

        self.heat_cache = buf
        self.heat_cache_time = time.time()

        await ctx.send(
            content="**User Locations Heatmap**\nDownload:",
            file=discord.File(buf, filename="heatmap.html")
        )

    @commands.command()
    async def mysetloc(self, ctx, *, location):
        """Set your own location"""
        msg = await ctx.send(f"🔍 Searching for '{location}'...")
        
        loc, source = await self._geocode_with_retry(location)
        
        if not loc:
            await msg.edit(content="❌ Location not found or geocoding services unavailable.")
            return

        city = "Unknown"
        country = "Unknown"
        
        if source == "Nominatim":
            address = loc.raw.get('address', {})
            city = address.get('city', address.get('town', location))
            country = address.get('country', "Unknown")
        elif source == "ArcGIS":
            parts = [p.strip() for p in loc.address.split(",")]
            if len(parts) >= 3:
                country = parts[-1]
                city = parts[-3]
            elif len(parts) == 2:
                country = parts[-1]
                city = parts[0]
            else:
                country = "Unknown"
                city = parts[0] if parts else location

        user_id = str(ctx.author.id)
        data = load_json(LOCATIONS_FILE)

        data[user_id] = {
            "username": ctx.author.display_name,
            "city": city,
            "country": country,
            "continent": self.get_continent(country),
            "lat": loc.latitude,
            "lon": loc.longitude,
            "timezone": self.tzfinder.timezone_at(lat=loc.latitude, lng=loc.longitude) or "UTC"
        }

        save_json(LOCATIONS_FILE, data)
        await msg.edit(content=f"📍 Your location has been set to {city}, {country}!")
    
    @commands.command()
    async def myremoveloc(self, ctx):
        """Remove your own location"""
        user_id = str(ctx.author.id)
        data = load_json(LOCATIONS_FILE)

        if user_id in data:
            del data[user_id]
            save_json(LOCATIONS_FILE, data)
            await ctx.send("📍 Your location has been removed.")
        else:
            await ctx.send("You don't have a location set.")

    def haversine(self, lat1, lon1, lat2, lon2):
        """Distance between two coordinates in km"""
        R = 6371
        lat1, lon1, lat2, lon2 = map(math.radians, [lat1, lon1, lat2, lon2])
        dlat = lat2 - lat1
        dlon = lon2 - lon1
        
        a = math.sin(dlat/2)**2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon/2)**2
        c = 2 * math.asin(math.sqrt(a))
        return R * c

    @commands.command()
    async def near(self, ctx, member: discord.Member = None):
        """Find the 5 closest members to you or another user"""
        target = member or ctx.author
        data = load_json(LOCATIONS_FILE)

        if str(target.id) not in data:
            return await ctx.send("⚠️ That user has no location set.")

        t_info = data[str(target.id)]
        t_lat, t_lon = t_info["lat"], t_info["lon"]

        distances = []
        for uid, info in data.items():
            if uid == str(target.id):
                continue
            dist = self.haversine(t_lat, t_lon, info["lat"], info["lon"])
            distances.append((uid, info, dist))

        if not distances:
            return await ctx.send("⚠️ Not enough users have set locations.")

        distances.sort(key=lambda x: x[2])
        top5 = distances[:5]

        embed = discord.Embed(
            title=f"🌍 Closest Members to {target.display_name}",
            color=0x5865F2
        )

        for uid, info, dist in top5:
            name = info.get("username", f"<@{uid}>")
            embed.add_field(
                name=f"<@{uid}> — {name}",
                value=f"{info['city']}, {info['country']} — **{dist:.1f} km**",
                inline=False
            )

        await ctx.send(embed=embed)

    @commands.command(name="localtime", aliases=["lt"])
    async def time(self, ctx, member: discord.Member = None):
        """Show local time for a user"""
        member = member or ctx.author
        data = load_json(LOCATIONS_FILE)

        if str(member.id) not in data:
            return await ctx.send("⚠️ That user has no location set.")

        tzname = data[str(member.id)].get("timezone", "UTC")

        try:
            tz = pytz.timezone(tzname)
        except:
            tz = pytz.timezone("UTC")

        now = datetime.now(tz)

        embed = discord.Embed(
            title=f"🕒 Local time for {member.display_name}",
            description=f"**{now.strftime('%Y-%m-%d %I:%M %p')}**\n({tzname})",
            color=0x5865F2
        )
        await ctx.send(embed=embed)

    @commands.command()
    async def locstats(self, ctx):
        """Show useful location statistics"""
        data = load_json(LOCATIONS_FILE)
        if not data:
            return await ctx.send("No locations set!")

        country_count = {}
        continent_count = {}
        city_count = {}
        unknown_country = 0
        unknown_continent = 0

        for info in data.values():
            country = info.get("country", "Unknown")
            continent = info.get("continent", "Unknown")
            city = info.get("city", "Unknown")

            country_count[country] = country_count.get(country, 0) + 1
            continent_count[continent] = continent_count.get(continent, 0) + 1
            city_count[city] = city_count.get(city, 0) + 1

            if country == "Unknown":
                unknown_country += 1
            if continent == "Unknown":
                unknown_continent += 1

        embed = discord.Embed(
            title="📊 Location Statistics",
            color=0x5865F2
        )

        embed.add_field(
            name="🌍 Top Countries",
            value="\n".join(
                f"**{c}** — {n}"
                for c, n in sorted(country_count.items(), key=lambda x: -x[1])[:10]
            ),
            inline=False
        )

        embed.add_field(
            name="🌎 Continents",
            value="\n".join(
                f"**{c}** — {n}"
                for c, n in sorted(continent_count.items(), key=lambda x: -x[1])
            ),
            inline=False
        )

        embed.add_field(
            name="🏙️ Top Cities",
            value="\n".join(
                f"**{c}** — {n}"
                for c, n in sorted(city_count.items(), key=lambda x: -x[1])[:10]
            ),
            inline=False
        )

        embed.add_field(
            name="⚠️ Data Issues",
            value=f"Unknown Country: **{unknown_country}**\nUnknown Continent: **{unknown_continent}**",
            inline=False
        )

        await ctx.send(embed=embed)

    @commands.command()
    @commands.has_permissions(administrator=True)
    async def refreshtz(self, ctx):
        """Refresh timezone for all saved users"""
        data = load_json(LOCATIONS_FILE)
        if not data:
            return await ctx.send("No locations saved.")

        updated = 0

        for uid, info in data.items():
            lat = info.get("lat")
            lon = info.get("lon")

            if lat is None or lon is None:
                continue

            tz = self.tzfinder.timezone_at(lat=lat, lng=lon)
            if tz is None:
                tz = self.tzfinder.closest_timezone_at(lat=lat, lng=lon)
            if tz is None:
                tz = "UTC"

            data[uid]["timezone"] = tz
            updated += 1

        save_json(LOCATIONS_FILE, data)
        await ctx.send(f"⏱ Refreshed timezones for **{updated}** users!")

    @commands.command(aliases=["forceremoveloc"])
    @commands.has_permissions(administrator=True)
    async def forceremloc(self, ctx, *, query: str):
        """Force remove a location entry by username (works even if user left the server)"""
        data = load_json(LOCATIONS_FILE)
        query = query.strip().strip("\"'")

        matched = [(uid, info) for uid, info in data.items() if uid == query]
        if not matched:
            matched = [(uid, info) for uid, info in data.items() if info.get("username", "").lower() == query.lower()]

        if not matched:
            return await ctx.send(f"⚠️ No location found for `{query}`.")

        if len(matched) > 1:
            lines = [f"Multiple matches for `{query}`:"] + [f"• **{info['username']}** (ID: {uid})" for uid, info in matched]
            return await ctx.send("\n".join(lines))

        uid, info = matched[0]
        name = info.get("username", uid)
        del data[uid]
        save_json(LOCATIONS_FILE, data)

        await ctx.send(f"🗑️ Removed location for **{name}** (ID: {uid}).")

    @commands.command(name="lochelp", aliases=["hloc"])
    async def lochelp(self, ctx):
        """Show all location commands"""
        embed = discord.Embed(
            title="🗺️ Location Commands",
            description="Location tracking, maps, timezone utilities, and proximity tools.",
            color=0x5865F2
        )
        for section, cmds in LOCATION_HELP_COMMANDS:
            lines = []
            for cmd, desc in cmds:
                lines.append(f"**{cmd}**\n{desc}")
            embed.add_field(name=section, value="\n".join(lines), inline=False)
        embed.set_footer(text="Location System Help")
        await ctx.send(embed=embed)


CONTINENT_SHORT = {
    "North America": "NA",
    "South America": "SA",
    "Europe": "EU",
    "Asia": "Asia",
    "Africa": "AF",
    "Australia": "AU",
    "Oceania": "OC",
    "Antarctica": "AQ",
}

class LocationsView(discord.ui.View):
    def __init__(self, data, guild, timeout=180):
        super().__init__(timeout=timeout)
        self.data = data
        self.guild = guild
        self._build_continents()
        self._add_buttons()

    def _build_continents(self):
        cont_data = {}
        for uid, info in self.data.items():
            cont = info.get("continent", "Unknown")
            country = info.get("country", "Unknown")
            city = info.get("city", "Unknown")

            member = self.guild.get_member(int(uid))
            global_name = member.name if member else info.get("username", f"User-{uid}")

            cont_data.setdefault(cont, {"countries": {}, "count": 0})
            cont_data[cont]["countries"].setdefault(country, {})
            cont_data[cont]["countries"][country].setdefault(city, [])
            cont_data[cont]["countries"][country][city].append(f"<@{uid}> ({global_name})")
            cont_data[cont]["count"] += 1

        self.sorted_continents = sorted(cont_data.items(), key=lambda x: -x[1]["count"])

    def _add_buttons(self):
        placed = 0
        for cont, info in self.sorted_continents:
            if placed >= 6:
                break
            if cont == "Unknown":
                continue
            short = CONTINENT_SHORT.get(cont, cont[:3].upper())
            label = f"{short} ({info['count']})"
            btn = discord.ui.Button(label=label, style=discord.ButtonStyle.secondary, row=placed // 3)
            btn.callback = self._make_callback(cont, info)
            self.add_item(btn)
            placed += 1

        for cont, info in self.sorted_continents:
            if cont == "Unknown":
                btn = discord.ui.Button(label=f"❓ Unknown ({info['count']})", style=discord.ButtonStyle.danger, row=2)
                btn.callback = self._make_callback(cont, info)
                self.add_item(btn)
                break

    def _make_callback(self, cont, info):
        async def callback(interaction: discord.Interaction):
            embed = self._build_embed(cont, info)
            if cont == "Unknown":
                view = UnknownContinentView(self.data, self.guild, self, cont, info)
            else:
                view = self
            await interaction.response.edit_message(embed=embed, view=view)
        return callback

    def _build_embed(self, cont, info):
        short = CONTINENT_SHORT.get(cont, cont)
        color = 0xFEE75C if cont == "Unknown" else 0x5865F2
        embed = discord.Embed(title=f"🌍 {short} — {cont}", color=color)
        if not info["countries"]:
            embed.description = "✅ All unknown entries have been assigned!"
            return embed
        lines = []
        for country, cities in info["countries"].items():
            lines.append(f"🌐 **{country}**")
            for city, users in cities.items():
                lines.append(f"• **{city}** — {', '.join(users)}")
            lines.append("")
        text = "\n".join(lines)[:1024]
        embed.add_field(name=f"📍 {info['count']} user{'s' if info['count'] > 1 else ''}", value=text or "*No locations*", inline=False)
        return embed


class UnknownContinentView(discord.ui.View):
    def __init__(self, data, guild, parent, cont, info):
        super().__init__(timeout=180)
        self.data = data
        self.guild = guild
        self.parent = parent
        self.cont = cont
        self.info = info
        self.selected_country = None

        countries = list(info["countries"].keys())
        self.country_select = discord.ui.Select(
            placeholder="Select a country to fix...",
            options=[discord.SelectOption(label=c[:100], value=c) for c in countries],
            row=0
        )
        self.country_select.callback = self._on_country_select
        self.add_item(self.country_select)

        self.continent_select = discord.ui.Select(
            placeholder="Then pick a continent...",
            options=[
                discord.SelectOption(label="North America (NA)", value="North America", emoji="🌎"),
                discord.SelectOption(label="South America (SA)", value="South America", emoji="🌎"),
                discord.SelectOption(label="Europe (EU)", value="Europe", emoji="🌍"),
                discord.SelectOption(label="Asia", value="Asia", emoji="🌏"),
                discord.SelectOption(label="Africa (AF)", value="Africa", emoji="🌍"),
                discord.SelectOption(label="Oceania (OC)", value="Oceania", emoji="🌏"),
            ],
            row=1,
            disabled=True
        )
        self.continent_select.callback = self._on_continent_select
        self.add_item(self.continent_select)

        back = discord.ui.Button(label="↩ Back", style=discord.ButtonStyle.danger, row=4)
        back.callback = self._back_callback()
        self.add_item(back)

    async def _on_country_select(self, interaction: discord.Interaction):
        self.selected_country = interaction.data["values"][0]
        self.continent_select.disabled = False
        self.continent_select.placeholder = f"Continent for {self.selected_country[:50]}"
        await interaction.response.edit_message(view=self)

    async def _on_continent_select(self, interaction: discord.Interaction):
        continent = interaction.data["values"][0]
        country = self.selected_country

        for uid, info in self.data.items():
            if info.get("country") == country:
                info["continent"] = continent
        from utils.data_manager import save_json
        from config import LOCATIONS_FILE
        save_json(LOCATIONS_FILE, self.data)

        self.parent._build_continents()
        self.info = dict(self.parent.sorted_continents).get("Unknown", {"countries": {}, "count": 0})

        embed = self.parent._build_embed(self.cont, self.info)

        if self.info["countries"]:
            self.country_select.options = [discord.SelectOption(label=c[:100], value=c) for c in self.info["countries"].keys()]
            self.continent_select.disabled = True
            self.continent_select.placeholder = "Then pick a continent..."
            await interaction.response.edit_message(content=f"✅ **{country}** → **{continent}**", embed=embed, view=self)
        else:
            await interaction.response.edit_message(content=f"✅ **{country}** → **{continent}**\n🎉 All unknown entries fixed!", embed=embed, view=self.parent)

    def _back_callback(self):
        async def callback(interaction: discord.Interaction):
            first_cont, first_info = self.parent.sorted_continents[0]
            embed = self.parent._build_embed(first_cont, first_info)
            await interaction.response.edit_message(embed=embed, view=self.parent)
        return callback
