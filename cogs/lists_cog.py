import discord
import datetime
import random
from datetime import datetime
from discord.ext import commands
from cogs.data_utils import load_guild_data, save_guild_data, add_player, remove_player, get_team_players

def _normalize_team(team: str):
    """Normalize a team input to a canonical name.

    Returns one of: village, evil, neutral, rk, corrupted.
    Returns None if the team input is not recognized.
    """
    if not team:
        return None
    t = team.strip().lower()
    if t in ["vill", "village", "v", "good"]:
        return "village"
    if t in ["evil", "e", "bad"]:
        return "evil"
    if t in ["neutral", "n", "solo", "s"]:
        return "neutral"
    if t in ["rk", "r", "lms"]:
        return "rk"
    if t in ["corrupted", "corr", "unk", "?", "???", "c"]:
        return "corrupted"
    return None


_DEADLIST_USAGE = {
    "add": (
        "❌ **Usage:** `.deadlist add @player <team> <role>`\n"
        "**Example:** `.deadlist add @Marr(Vacs) Village Doctor`\n\n"
        "**Teams:** village (vill/v/good) • evil (e/bad) • neutral (n/solo/s) • rk (r/lms) • corrupted (corr/unk/?/c)\n"
        "All three arguments are required."
    ),
    "edit": (
        "❌ **Usage:** `.deadlist edit @player <team> <role>`\n"
        "**Example:** `.deadlist edit @Marr(Vacs) Evil Wolf`\n\n"
        "Updates an existing deadlist entry."
    ),
}


def _deadlist_usage(action: str) -> str:
    """Return a helpful usage message for a given deadlist action."""
    return _DEADLIST_USAGE.get(
        action,
        "❌ **Usage:** `.deadlist add @player <team> <role>` | `.deadlist remove @player` | `.deadlist edit @player <team> <role>`",
    )


    def _resolve_name_to_id(self, ctx, player_str: str) -> int | None:
        """Resolve a player string to a Discord user ID.

        Handles discord.Member mentions (<@id>, <@!id>), raw user IDs, and plain text.
        Returns the member's id if resolved, otherwise None.
        """
        if not player_str:
            return None
        raw = player_str.strip()
        if raw.startswith("<@") and raw.endswith(">"):
            raw = raw.lstrip("<!@").rstrip(">")
        try:
            member = ctx.guild.get_member(int(raw))
            if member is not None:
                return member.id
        except (ValueError, TypeError):
            pass
        return None

    def _get_role_from_deadlist(self, player_name: str, guild_id: int) -> tuple[str, str] | None:
        """Return (team, role) for a player name from the deadlist, or None."""
        teams = ["village", "evil", "neutral", "rk", "corrupted"]
        for t in teams:
            results = get_team_players(t, guild_id)
            for row in results:
                if row[0].lower() == player_name.lower():
                    return (t, row[1])
        return None


def _resolve_player_name(ctx, player_str: str) -> str:
    """Resolve a player string to a display_name.

    Handles discord.Member mentions (<@id>, <@!id>), raw user IDs, and plain text.
    Returns the member's display_name if resolved, otherwise the raw string.
    """
    if not player_str:
        return player_str
    raw = player_str.strip()
    if raw.startswith("<@") and raw.endswith(">"):
        raw = raw.lstrip("<!@").rstrip(">")
    try:
        member = ctx.guild.get_member(int(raw))
        if member is not None:
            return member.display_name
    except (ValueError, TypeError):
        pass
    return player_str


class Lists(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @commands.command(aliases=["p"])
    async def playerlist(self, ctx, format: str = None):
        """List all alive members in the server."""
        guild_data = load_guild_data(ctx.guild.id)
        if not guild_data:
            await ctx.send("Guild data not loaded.")
            return
        alive_role_name = guild_data.get("alive_role_name")
        if not alive_role_name:
            await ctx.send("Alive role name not found in configuration.")
            return
        alive_role = discord.utils.get(ctx.guild.roles, name=alive_role_name)
        if not alive_role:
            await ctx.send("Alive role not found in this server.")
            return
        alive_members = [m for m in ctx.guild.members if alive_role in m.roles and not m.bot]
        alive_members = sorted(alive_members, key=lambda m: m.display_name.lower())
        if format in ["mention", "tag"]:
            playerlist = "\n".join(m.mention for m in alive_members) or "*None*"
        else:
            playerlist = "\n".join(m.display_name for m in alive_members) or "*None*"
        embed = discord.Embed(title="Alive Player List", description=playerlist, color=0xff3fb9, timestamp=datetime.now())
        embed.set_footer(text=f"Village Game • {len(alive_members)} alive players in total")
        await ctx.send(embed=embed)

    @commands.command()
    async def sponsorlist(self, ctx, format: str = None):
        """List all sponsor members."""
        guild_data = load_guild_data(ctx.guild.id)
        if not guild_data:
            await ctx.send("Guild data not loaded")
            return
        sponsor_role = discord.utils.get(ctx.guild.roles, name=guild_data.get("sponsor_role_name"))
        if not sponsor_role:
            await ctx.send("Sponsor role not found in this server.")
            return
        sponsor_members = [m for m in ctx.guild.members if sponsor_role in m.roles and not m.bot]
        sponsor_members = sorted(sponsor_members, key=lambda m: m.display_name.lower())
        if format in ["mention", "tag"]:
            sponsor_playerlist = "\n".join(m.mention for m in sponsor_members) or "*None*"
        else:
            sponsor_playerlist = "\n".join(m.display_name for m in sponsor_members) or "*None*"
        embed = discord.Embed(title="Sponsors List", description=sponsor_playerlist, color=0xff3fb9, timestamp=datetime.now())
        embed.set_footer(text=f"Village Game • {len(sponsor_members)} sponsors in total")
        await ctx.send(embed=embed)

    @commands.command()
    async def setuphouselist(self, ctx):
        """Initialize the house list from existing house channels (admin only)."""
        if ctx.author.guild_permissions.administrator:
            guild_data = load_guild_data(ctx.guild.id)
            if guild_data:
                guild_data["houselist"] = []
                houses_category_name = guild_data.get("houses_category_name")
                houses_category = discord.utils.get(ctx.guild.categories, name=houses_category_name)
                if houses_category is not None:
                    for channel in houses_category.channels:
                        guild_data["houselist"].append(channel.name)
                    save_guild_data(ctx.guild.id, guild_data)
                    await ctx.send("House list setup successfully.")
                else:
                    await ctx.send(f'Category "{houses_category_name}" not found.')
            else:
                await ctx.send("Guild data not loaded.")
        else:
            await ctx.send("You don't have enough permissions to use this command.")

    @commands.command()
    async def houselistadd(self, ctx, house: discord.TextChannel = None):
        """Add a house to the visitable house list (admin only)."""
        if ctx.author.guild_permissions.administrator:
            guild_data = load_guild_data(ctx.guild.id)
            if guild_data:
                if house is None:
                    house = ctx.channel
                if house:
                    house_prefix = guild_data["house_prefix"]
                    house_name = house.name
                    house_number = int(house_name.replace(house_prefix, ""))
                    guild_data["houselist"] = [h for h in guild_data["houselist"] if int(h.replace(house_prefix, "")) != house_number]
                    guild_data["houselist"].append(house_name)
                    guild_data["houselist"].sort(key=lambda x: int(x.replace(house_prefix, "")))
                else:
                    await ctx.channel.send("Channel not found")
                save_guild_data(ctx.guild.id, guild_data)
                await ctx.channel.send(f"{house.mention} added succesfully in house list")
            else:
                await ctx.send("Guild data not loaded.")
        else:
            await ctx.send("You don't have enough permissions to use this command.")

    @commands.command()
    async def houselistremove(self, ctx, house: discord.TextChannel = None):
        """Remove a house from the visitable house list (admin only)."""
        if ctx.author.guild_permissions.administrator:
            guild_data = load_guild_data(ctx.guild.id)
            if guild_data:
                if house is None:
                    house = ctx.channel
                if house.name in guild_data["houselist"]:
                    guild_data["houselist"].remove(house.name)
                else:
                    await ctx.channel.send(f"{house.menion} not found in house list")
                save_guild_data(ctx.guild.id, guild_data)
                await ctx.channel.send(f"{house.mention} removed succesfully from house list")
            else:
                await ctx.send("Guild data not loaded.")
        else:
            await ctx.send("You don't have enough permissions to use this command.")

    @commands.command(aliases=["hl"])
    async def houselist(self, ctx):
        """Show all currently visitable houses."""
        guild_data = load_guild_data(ctx.guild.id)
        if "houselist" in guild_data:
            houses = guild_data["houselist"]
            houses_list_str = "\n".join(houses)
            embed = discord.Embed(title=f"Visitable houses:", description=houses_list_str, color=0xff3fb9, timestamp=datetime.now())
            embed.set_footer(text=f"Village Game • {len(houses)} visitable houses in total")
            await ctx.send(embed=embed)
        else:
            await ctx.send(f"House list not found")

    @commands.command(aliases=["rh"])
    async def rollhouses(self, ctx, num_houses: str = "1"):
        """Randomly select one or more houses from the houselist."""
        guild_data = load_guild_data(ctx.guild.id)
        if not guild_data:
            await ctx.send("Guild data not loaded.")
            return

        houselist = guild_data.get("houselist", [])
        if not houselist:
            await ctx.send("No registered houses in the server.")
            return

        if num_houses.lower() == "all":
            num = len(houselist)
        else:
            try:
                num = int(num_houses)
            except ValueError:
                await ctx.send("Insert a valid number or `all`.")
                return

        if num <= 0:
            await ctx.send("Insert a valid number.")
            return
        if len(houselist) < num:
            await ctx.send(f"Not enough houses in the houselist (only {len(houselist)} available).")
            return

        picked = random.sample(houselist, num)

        if num == 1:
            embed = discord.Embed(
                title="🎲 House",
                description=f"**{picked[0]}**",
                color=0xff3fb9,
            )
            embed.set_footer(text=f"Rolled 1 / {len(houselist)} houses")
        else:
            houses_str = "\n".join(f"`{i}.` **{h}**" for i, h in enumerate(picked, 1))
            embed = discord.Embed(
                title=f"🎲 Houses",
                description=houses_str,
                color=0xff3fb9,
            )
            embed.set_footer(text=f"Rolled {num} / {len(houselist)} houses")

        await ctx.send(embed=embed)

    @commands.command(aliases=["d"])
    async def deadlist(self, ctx, action: str = None, player: str = None, team: str = None, slot: int = None, *, role: str = None):
        """Show list of dead players along with their roles. Use .deadlist add @player <team> <role> [slot] to assign a slot."""
        if action is None:
            embed = discord.Embed(title="Deadlist", color=0xff3fb9, timestamp=datetime.now())
            embed.set_footer(text="Village Game")
            teams = ["village", "evil", "neutral", "rk", "corrupted"]
            for t in teams:
                results = get_team_players(t, ctx.guild.id)
                if results:
                    team_list = "\n".join([f"**{row[0]}** - {row[1]}" for row in results])
                    embed.add_field(name=f"**{t.capitalize()}**", value=team_list, inline=False)
            await ctx.send(embed=embed)
        elif action == "add":
            if not ctx.author.guild_permissions.administrator:
                await ctx.send("You don't have enough permissions to use this command.")
                return
            if player and team and role:
                canonical = _normalize_team(team)
                if canonical is None:
                    await ctx.send(
                        "❌ Invalid team. Use Village, Evil, Neutral, Rk or Corrupted.\n"
                        "**Teams:** village (vill/v/good) • evil (e/bad) • neutral (n/solo/s) • rk (r/lms) • corrupted (corr/unk/?/c)"
                    )
                    return
                add_player(player, canonical, role, ctx.guild.id)
                if slot is not None:
                    guild_data = load_guild_data(ctx.guild.id)
                    player_slots = guild_data.setdefault("player_slots", {})
                    mentions = ctx.message.mentions
                    if mentions:
                        player_slots[str(mentions[0].id)] = slot
                    else:
                        player_id = self._resolve_name_to_id(ctx, player)
                        if player_id:
                            player_slots[str(player_id)] = slot
                    save_guild_data(ctx.guild.id, guild_data)
                await ctx.send(f"{player} added to Deadlist" + (f" (Slot {slot})" if slot else ""))
            else:
                await ctx.send(_deadlist_usage("add"))
        elif action == "remove":
            if not ctx.author.guild_permissions.administrator:
                await ctx.send("You don't have enough permissions to use this command.")
                return
            if player:
                resolved = _resolve_player_name(ctx, player)
                deleted = remove_player(resolved, ctx.guild.id)
                if deleted:
                    await ctx.send(f"{resolved} removed from Deadlist.")
                else:
                    await ctx.send(f"No deadlist entry found for {resolved}.")
            else:
                await ctx.send("No player specified.")
        elif action == 'edit':
            if not ctx.author.guild_permissions.administrator:
                await ctx.send("You don't have enough permissions to use this command.")
                return
            if player and team and role:
                resolved = _resolve_player_name(ctx, player)
                remove_player(resolved, ctx.guild.id)
                canonical = _normalize_team(team)
                if canonical is None:
                    await ctx.send("Invalid team. Use Village, Evil, Neutral, Rk or Corrupted.")
                    return
                add_player(resolved, canonical, role, ctx.guild.id)
                if slot is not None:
                    guild_data = load_guild_data(ctx.guild.id)
                    player_slots = guild_data.setdefault("player_slots", {})
                    mentions = ctx.message.mentions
                    if mentions:
                        player_slots[str(mentions[0].id)] = slot
                    else:
                        player_id = self._resolve_name_to_id(ctx, player)
                        if player_id:
                            player_slots[str(player_id)] = slot
                    save_guild_data(ctx.guild.id, guild_data)
                await ctx.send(f"{resolved} edited in deadlist." + (f" (Slot {slot})" if slot else ""))
            else:
                await ctx.send("You have to fill all inputs: player, team, role.")

    @commands.command(name="roleslots")
    async def roleslots(self, ctx):
        """Show all players organized by team slot. Admin only."""
        if not ctx.author.guild_permissions.administrator:
            await ctx.send("You don't have enough permissions to use this command.")
            return
        guild_data = load_guild_data(ctx.guild.id)
        if not guild_data:
            await ctx.send("Guild data not loaded.")
            return
        player_slots = guild_data.get("player_slots", {})
        slot_players: dict[int, list[tuple]] = {1: [], 2: [], 3: [], 4: [], 5: []}
        unassigned = []
        for player_id_str, slot in player_slots.items():
            member = ctx.guild.get_member(int(player_id_str))
            if member:
                name = member.display_name
            else:
                name = f"Unknown ({player_id_str})"
            role_info = self._get_role_from_deadlist(name, ctx.guild.id)
            if role_info:
                team, role = role_info
                entry = (name, role, team)
            else:
                entry = (name, "Unknown", "Unknown")
            if slot in slot_players:
                slot_players[slot].append(entry)
            else:
                unassigned.append(entry)
        slot_names = {
            1: "The Vanguard",
            2: "The Protectors",
            3: "The Shadows",
            4: "Slot 4",
            5: "Slot 5",
        }
        embed = discord.Embed(title="🎴 Role Slots", color=0xff3fb9, timestamp=datetime.now())
        embed.set_footer(text="Village Game")
        for slot_num in range(1, 6):
            players = slot_players[slot_num]
            if players:
                lines = [f"• **{p[0]}** — {p[1]} ({p[2].capitalize()})" for p in players]
                embed.add_field(name=f"Slot {slot_num} — {slot_names[slot_num]}", value="\n".join(lines), inline=False)
            else:
                embed.add_field(name=f"Slot {slot_num} — {slot_names[slot_num]}", value="*[Empty]*", inline=False)
        if unassigned:
            lines = [f"• **{p[0]}** — {p[1]} ({p[2].capitalize()})" for p in unassigned]
            embed.add_field(name="[Unassigned]", value="\n".join(lines), inline=False)
        await ctx.send(embed=embed)

    @commands.command(name='map')
    async def map_command(self, ctx):
        """Show the game map overview."""
        guild_data = load_guild_data(ctx.guild.id)
        if not guild_data:
            await ctx.send("Guild data not loaded.")
            return
        map_channel = discord.utils.get(ctx.guild.channels, name=guild_data["map_channel_name"])
        if not map_channel:
            await ctx.send("Map channel not found")
            return
        pinned_messages = await map_channel.pins()
        if not pinned_messages:
            await ctx.send(f"There are no pinned messages in {map_channel.mention}")
            return
        first_pinned = pinned_messages[0]
        image_url = None
        if first_pinned.attachments:
            for att in first_pinned.attachments:
                if att.content_type and att.content_type.startswith('image/'):
                    image_url = att.url
                    break
                fname = att.filename.lower()
                if fname.endswith(('.png', '.jpg', '.jpeg', '.gif', '.webp', '.bmp')):
                    image_url = att.url
                    break
        if image_url is None and first_pinned.embeds:
            for embed in first_pinned.embeds:
                if embed.image and embed.image.url:
                    image_url = embed.image.url
                    break
                if embed.thumbnail and embed.thumbnail.url:
                    image_url = embed.thumbnail.url
                    break
        if image_url is None:
            await ctx.send(f"First pinned message in {map_channel.mention} isn't a picture")
            return
        embed = discord.Embed(title="Map", description=f"{map_channel.mention}", color=0xff3fb9, timestamp=datetime.now())
        embed.set_image(url=image_url)
        embed.set_footer(text="Village Game")
        await ctx.send(embed=embed)