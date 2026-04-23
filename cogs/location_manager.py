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

# Configure logging
logger = logging.getLogger('LocationManager')
logger.setLevel(logging.INFO)
handler = logging.StreamHandler()
handler.setFormatter(logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s'))
logger.addHandler(handler)

class LocationManager(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        # Primary geocoder
        self.geolocator = Nominatim(user_agent=GEOCODER_USER_AGENT, timeout=10)
        # Fallback geocoder
        self.fallback_geolocator = ArcGIS(user_agent=GEOCODER_USER_AGENT, timeout=10)
        
        self.tzfinder = TimezoneFinder()  
        self.map_cache = None
        self.map_cache_time = 0
        self.heat_cache = None
        self.heat_cache_time = 0

    def get_continent(self, country_name):
        try:
            country_code = pc.country_name_to_country_alpha2(country_name)
            return pc.convert_continent_code_to_continent_name(
                pc.country_alpha2_to_continent_code(country_code)
            )
        except:
            return "Unknown"

    async def _geocode_with_retry(self, query, max_retries=3):
        """
        Geocode with exponential backoff retry logic and fallback.
        """
        # Try Primary (Nominatim)
        for attempt in range(max_retries):
            try:
                logger.info(f"Geocoding attempt {attempt + 1}/{max_retries} for '{query}' using Nominatim (UA: {GEOCODER_USER_AGENT})")
                # Run blocking geocode call in executor
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
                    wait_time = 2 ** attempt  # 1s, 2s, 4s
                    logger.info(f"Waiting {wait_time}s before retry...")
                    await asyncio.sleep(wait_time)
                else:
                    logger.warning("Nominatim failed all retries.")

        # Try Fallback (ArcGIS)
        try:
            logger.info(f"Attempting fallback geocoder (ArcGIS) for '{query}'")
            func = functools.partial(self.fallback_geolocator.geocode, query)
            loc = await self.bot.loop.run_in_executor(None, func)
            
            if loc:
                logger.info(f"ArcGIS success: {loc.address}")
                # ArcGIS structure is different, normalize it slightly if needed
                # For basic lat/lon it's compatible. Address details might differ.
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
        
        # 1. Direct HTTP Test
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

        # 2. Geopy Wrapper Test
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

        # 3. Fallback Test
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
            
        # Extract address details
        # Note: ArcGIS raw data structure is different from Nominatim
        # We try to adapt best effort
        city = "Unknown"
        country = "Unknown"
        
        if source == "Nominatim":
            address = loc.raw.get('address', {})
            city = address.get('city', address.get('town', location))
            country = address.get('country', "Unknown")
        elif source == "ArcGIS":
            # ArcGIS address is usually a single formatted string
            # We can try to parse or just use the whole string as city equivalent for display
            parts = loc.address.split(',')
            country = parts[-1].strip() if len(parts) > 0 else "Unknown"
            city = parts[0].strip() if len(parts) > 0 else location

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
    async def remloc(self, ctx, member: discord.Member):
        """Remove a user's location (Admin only)"""
        data = load_json(LOCATIONS_FILE)
        if str(member.id) in data:
            del data[str(member.id)]
            save_json(LOCATIONS_FILE, data)
            await ctx.send(f"❌ Location removed for {member.display_name}!")
        else:
            await ctx.send(f"⚠️ No location found for {member.display_name}.")
    
    @commands.command()
    async def locations(self, ctx):
        """Show all locations grouped by continent and country (Fast)"""
        data = load_json(LOCATIONS_FILE)
        if not data:
            return await ctx.send("No locations set yet!")

        # continent → country → city → users
        continents = {}
        for uid, info in data.items():
            cont = info["continent"]
            country = info["country"]
            city = info["city"]

            continents.setdefault(cont, {})
            continents[cont].setdefault(country, {})
            continents[cont][country].setdefault(city, [])
            continents[cont][country][city].append(f"<@{uid}>")

        embed = discord.Embed(title="🌍 User Locations", color=0x00ff00)

        # Compact, efficient formatting
        for cont, countries in continents.items():
            lines = []
            for country, cities in countries.items():
                lines.append(f"🌐 **{country}**")
                for city, users in cities.items():
                    lines.append(f"• **{city}** — {', '.join(users)}")
                lines.append("")  # spacing

            text = "\n".join(lines)[:1024]
            embed.add_field(name=f"🌏 {cont}", value=text, inline=False)

        await ctx.send(embed=embed)

    @commands.command()
    async def mapp(self, ctx):
        data = load_json(LOCATIONS_FILE)
        if not data:
            return await ctx.send("No locations set yet!")

        # Fix missing usernames
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

        # Use cache for 10 minutes
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

        # Extract address details
        city = "Unknown"
        country = "Unknown"
        
        if source == "Nominatim":
            address = loc.raw.get('address', {})
            city = address.get('city', address.get('town', location))
            country = address.get('country', "Unknown")
        elif source == "ArcGIS":
            parts = loc.address.split(',')
            country = parts[-1].strip() if len(parts) > 0 else "Unknown"
            city = parts[0].strip() if len(parts) > 0 else location

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
            color=0x00ffcc
        )

        for uid, info, dist in top5:
            embed.add_field(
                name=f"<@{uid}>",
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
            color=0x33aa33
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
            color=0x3498db
        )

        # Top 10 countries
        embed.add_field(
            name="🌍 Top Countries",
            value="\n".join(
                f"**{c}** — {n}"
                for c, n in sorted(country_count.items(), key=lambda x: -x[1])[:10]
            ),
            inline=False
        )

        # All continents
        embed.add_field(
            name="🌎 Continents",
            value="\n".join(
                f"**{c}** — {n}"
                for c, n in sorted(continent_count.items(), key=lambda x: -x[1])
            ),
            inline=False
        )

        # Top 10 cities
        embed.add_field(
            name="🏙️ Top Cities",
            value="\n".join(
                f"**{c}** — {n}"
                for c, n in sorted(city_count.items(), key=lambda x: -x[1])[:10]
            ),
            inline=False
        )

        # Missing data
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

            # Recalculate timezone using improved logic
            tz = self.tzfinder.timezone_at(lat=lat, lng=lon)
            if tz is None:
                tz = self.tzfinder.closest_timezone_at(lat=lat, lng=lon)
            if tz is None:
                tz = "UTC"

            data[uid]["timezone"] = tz
            updated += 1

        save_json(LOCATIONS_FILE, data)
        await ctx.send(f"⏱ Refreshed timezones for **{updated}** users!")

    @commands.command()
    @commands.has_permissions(administrator=True)
    async def forceremloc(self, ctx, user_id: int):
        """Force remove a location entry using a user ID (works even if user left the server)"""
        data = load_json(LOCATIONS_FILE)
        user_id = str(user_id)

        if user_id not in data:
            return await ctx.send("⚠️ No location stored for that user ID.")

        del data[user_id]
        save_json(LOCATIONS_FILE, data)

        await ctx.send(f"🗑️ Forced removal complete for user ID `{user_id}`.")