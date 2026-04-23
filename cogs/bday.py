import discord
from discord.ext import commands, tasks
from datetime import datetime, date
from collections import defaultdict
from cogs.data_utils import load_guild_data, save_guild_data

# ========= CONFIG =========
BIRTHDAY_CHANNEL_ID = 1074546613973954582   # 😎│mod-chat
CREATOR_ROLE_ID = 1074546728952414248       # creator role
CHECK_INTERVAL_MINUTES = 360
# ==========================


class Birthday(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @commands.Cog.listener()
    async def on_ready(self):
        if not self.birthday_check.is_running():
            print("[Birthday] Starting check loop from on_ready...")
            self.birthday_check.start()

    def cog_unload(self):
        self.birthday_check.cancel()

    # ======================================================
    # AUTOMATIC CHECK
    # ======================================================
    @tasks.loop(minutes=CHECK_INTERVAL_MINUTES)
    async def birthday_check(self):
        print(f"[Birthday] Starting check at {datetime.utcnow()}")
        for guild in self.bot.guilds:
            guild_data = load_guild_data(guild.id)
            if not guild_data:
                continue

            birthdays = guild_data.get("birthdays", {})
            if not birthdays:
                continue

            channel = guild.get_channel(BIRTHDAY_CHANNEL_ID)
            if not channel:
                try:
                    channel = await self.bot.fetch_channel(BIRTHDAY_CHANNEL_ID)
                except Exception as e:
                    print(f"[Birthday] Could not find channel {BIRTHDAY_CHANNEL_ID} in {guild.name}: {e}")
                    continue

            creator_role = guild.get_role(CREATOR_ROLE_ID)
            if not creator_role:
                print(f"[Birthday] Could not find role {CREATOR_ROLE_ID} in {guild.name}")
                continue

            today = datetime.utcnow().date()
            wished = guild_data.setdefault("birthday_wished", {})
            wished.setdefault(str(today), [])

            for user_id, mmdd in birthdays.items():
                if user_id in wished[str(today)]:
                    continue

                member = guild.get_member(int(user_id))
                if not member:
                    try:
                        member = await guild.fetch_member(int(user_id))
                    except Exception:
                        continue

                # always wish early (UTC-based reminder)
                if today.strftime("%m-%d") == mmdd:
                    upcoming = await self._next_birthdays(guild, guild_data)

                    message = (
                        f"{creator_role.mention} It's {member.mention}'s birthday! 🎂\n\n"
                        f"**Here are the next 5 birthdays:**\n"
                        f"{self._format_next_birthdays(upcoming)}"
                    )

                    await channel.send(message)
                    wished[str(today)].append(user_id)
                    print(f"[Birthday] Wished {member.display_name} in {guild.name}")

            guild_data["birthday_wished"] = wished
            save_guild_data(guild.id, guild_data)

    @birthday_check.before_loop
    async def before_birthday_check(self):
        await self.bot.wait_until_ready()

    # ======================================================
    # COMMANDS
    # ======================================================

    @commands.command(name="birthday")
    async def birthday(self, ctx, action: str = None, member: discord.Member = None, date_str: str = None):
        """
        .birthday add @user MM-DD   (admin)
        .birthday remove @user     (admin)
        """
        guild_data = load_guild_data(ctx.guild.id)
        if not guild_data:
            await ctx.send("Guild data not loaded.")
            return

        birthdays = guild_data.setdefault("birthdays", {})

        # ---------- ADD (ADMIN) ----------
        if action == "add":
            if not ctx.author.guild_permissions.administrator:
                await ctx.send("Admins only.")
                return
            if not member or not date_str:
                await ctx.send("Usage: `.birthday add @user MM-DD`")
                return
            if not self._valid_date(date_str):
                await ctx.send("Invalid date format. Use `MM-DD`.")
                return

            birthdays[str(member.id)] = date_str
            save_guild_data(ctx.guild.id, guild_data)
            await ctx.send(f"🎂 Birthday saved for **{member.display_name}** on `{date_str}`.")
            return

        # ---------- REMOVE (ADMIN) ----------
        if action == "remove":
            if not ctx.author.guild_permissions.administrator:
                await ctx.send("Admins only.")
                return
            if not member:
                await ctx.send("Usage: `.birthday remove @user`")
                return

            uid = str(member.id)
            if uid not in birthdays:
                await ctx.send("No birthday found for that user.")
                return

            del birthdays[uid]
            save_guild_data(ctx.guild.id, guild_data)
            await ctx.send(f"🗑 Birthday removed for **{member.display_name}**.")
            return

        await ctx.send(
            "Usage:\n"
            "`.birthday add @user MM-DD` (admin)\n"
            "`.birthday remove @user` (admin)\n"
            "`.testbday @user` (admin)\n"
            "`.bdaystatus` (admin)"
        )

    @commands.command(name="bdaystatus")
    @commands.has_permissions(administrator=True)
    async def bdaystatus(self, ctx):
        """Check if the birthday cron job is running."""
        is_running = self.birthday_check.is_running()
        
        if is_running:
            next_run = self.birthday_check.next_iteration
            if next_run:
                next_run_str = discord.utils.format_dt(next_run, style="R")
                await ctx.send(f"✅ The birthday reminder loop is currently **running**.\n⏳ Next check: {next_run_str} (Interval: {CHECK_INTERVAL_MINUTES} minutes)")
            else:
                await ctx.send(f"✅ The birthday reminder loop is currently **running**.\n⏳ Next check: Unknown (Interval: {CHECK_INTERVAL_MINUTES} minutes)")
        else:
            await ctx.send("❌ The birthday reminder loop is **NOT** running.")
            
    @commands.command(name="testbday")
    @commands.has_permissions(administrator=True)
    async def testbday(self, ctx, member: discord.Member = None):
        """Manually trigger a birthday wish for testing."""
        guild_data = load_guild_data(ctx.guild.id)
        if not guild_data:
            await ctx.send("Guild data not loaded.")
            return

        target_member = member or ctx.author
        
        channel = ctx.guild.get_channel(BIRTHDAY_CHANNEL_ID)
        if not channel:
            try:
                channel = await self.bot.fetch_channel(BIRTHDAY_CHANNEL_ID)
            except Exception as e:
                await ctx.send(f"❌ Could not find birthday channel `{BIRTHDAY_CHANNEL_ID}`: {e}")
                return

        creator_role = ctx.guild.get_role(CREATOR_ROLE_ID)
        if not creator_role:
            await ctx.send(f"❌ Could not find birthday role `{CREATOR_ROLE_ID}`.")
            return

        upcoming = await self._next_birthdays(ctx.guild, guild_data)

        message = (
            f"{creator_role.mention} It's {target_member.mention}'s birthday! 🎂\n\n"
            f"**Here are the next 5 birthdays:**\n"
            f"{self._format_next_birthdays(upcoming)}"
        )

        await channel.send(message)
        await ctx.send(f"✅ Birthday reminder test sent for **{target_member.display_name}** to {channel.mention}.")

    # ======================================================
    # NEXT 5 BIRTHDAYS
    # ======================================================
    @commands.command(name="nextbirthdays")
    @commands.has_permissions(administrator=True)
    async def nextbirthdays(self, ctx):
        guild_data = load_guild_data(ctx.guild.id)
        if not guild_data:
            await ctx.send("No birthday data found.")
            return

        upcoming = await self._next_birthdays(ctx.guild, guild_data)
        if not upcoming:
            await ctx.send("No upcoming birthdays.")
            return

        creator_role = ctx.guild.get_role(CREATOR_ROLE_ID)

        await ctx.send(
            #f"{creator_role.mention}\n\n"
            f"**Here are the next 5 birthdays:**\n"
            f"{self._format_next_birthdays(upcoming)}"
        )

    # ======================================================
    # LIST (ADMIN)
    # ======================================================
    @commands.command(name="birthdays")
    @commands.has_permissions(administrator=True)
    async def birthdays(self, ctx):
        guild_data = load_guild_data(ctx.guild.id)
        birthdays = guild_data.get("birthdays", {})

        if not birthdays:
            await ctx.send("No birthdays registered.")
            return

        lines = []
        for uid, mmdd in sorted(birthdays.items(), key=lambda x: x[1]):
            member = ctx.guild.get_member(int(uid))
            if member:
                lines.append(f"{mmdd} — {member.display_name}")

        await ctx.send("🎂 **Birthdays:**\n" + "\n".join(lines))

    # ======================================================
    # HELP
    # ======================================================
    @commands.command(name="helpbday")
    async def helpbday(self, ctx):
        embed = discord.Embed(
            title="🎂 Birthday Commands",
            color=0xffc0cb,
            description=(
                "**Admin Commands**\n"
                "`.birthday add @user MM-DD`\n"
                "`.birthday remove @user`\n"
                "`.birthdays`\n"
                "`.nextbirthdays`\n"
                "`.testbday @user`\n\n"
                "**Notes**\n"
                "• Dates must be `MM-DD`\n"
                "• Birthdays are wished early (UTC)\n"
                "• One message per user per year"
            )
        )
        await ctx.send(embed=embed)

    # ======================================================
    # UTILS
    # ======================================================
    def _valid_date(self, date_str: str) -> bool:
        try:
            datetime.strptime(date_str, "%m-%d")
            return True
        except Exception:
            return False

    async def _next_birthdays(self, guild, guild_data, count=5):
        today = datetime.utcnow().date()
        birthdays = guild_data.get("birthdays", {})

        upcoming = []

        for uid, mmdd in birthdays.items():
            try:
                month, day = map(int, mmdd.split("-"))
                try:
                    bday = date(today.year, month, day)
                except ValueError:  # Leap year handling (Feb 29)
                    bday = date(today.year, month, day - 1) # Fallback to Feb 28 if not leap year
                
                if bday < today:
                    try:
                        bday = date(today.year + 1, month, day)
                    except ValueError:
                        bday = date(today.year + 1, month, day - 1)

                member = guild.get_member(int(uid))
                if not member:
                    try:
                        member = await guild.fetch_member(int(uid))
                    except Exception:
                        continue
                
                if member:
                    upcoming.append((bday, member))
            except Exception:
                continue

        upcoming.sort(key=lambda x: x[0])
        return upcoming[:count]

    def _format_next_birthdays(self, upcoming):
        if not upcoming:
            return "No upcoming birthdays."

        return "\n".join(
            f"• {d.strftime('%b %d')} — {member.mention}"
            for d, member in upcoming
        )


async def setup(bot):
    await bot.add_cog(Birthday(bot))
