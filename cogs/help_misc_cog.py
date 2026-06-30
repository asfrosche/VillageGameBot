import os
import re
import random
import wcwidth
import discord
import asyncio
import datetime
from datetime import datetime
from discord.ext import commands
from discord import AllowedMentions
from discord.ui import Select, View, Button
from cogs.data_utils import load_guild_data, save_guild_data
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


COMMAND_INDEX = [
    (".setup <num>", "Setup roles, channels & categories", "Setup", ["init", "configure", "server", "channel"]),
    (".roleset <key> @role", "Assign a role for the bot", "Setup", ["config", "permission"]),
    (".channelset <key> #ch", "Assign a channel for the bot", "Setup", ["config", "channel"]),
    (".categoryset <key> <name>", "Assign a category", "Setup", ["config", "category"]),
    (".houseprefix <pfx>", "Set house name prefix", "Setup", ["house", "naming", "prefix"]),
    (".knockduration <sec>", "Set knock timeout duration", "Setup", ["knock", "timeout", "timer"]),
    (".maxpinh <num>", "Max players per house", "Setup", ["house", "limit", "capacity"]),
    (".refuseresponse 1/2/3", "Knock refuse behavior", "Setup", ["knock", "refuse", "behaviour"]),
    (".settings", "View current settings", "Setup", ["config", "view", "current"]),
    (".resetdb", "Reset all setup", "Setup", ["clear", "wipe", "reset"]),
    (".showwhispersender", "Show/hide whisper sender", "Setup", ["whisper", "toggle", "anonymous"]),
    (".ajifempty", "Auto-join if house is empty", "Setup", ["auto", "join", "empty"]),
    (".ajknockexpire", "Auto-join when knock expires", "Setup", ["auto", "join", "expire"]),
    (".deadcount", "Deads count for AJ/MaxPlayers", "Setup", ["dead", "autojoin", "count"]),
    (".altcount", "Alts count for AJ/MaxPlayers", "Setup", ["alt", "autojoin", "count"]),
    (".showdeadsonrefuse", "Show deads on knock refuse", "Setup", ["dead", "refuse", "show"]),
    (".showaltsonrefuse", "Show alts on knock refuse", "Setup", ["alt", "refuse", "show"]),
    (".candeadsinteract", "Deads can open/refuse", "Setup", ["dead", "interact", "open", "refuse"]),
    (".canaltsinteract", "Alts can open/refuse", "Setup", ["alt", "interact", "open", "refuse"]),
    (".move <#>", "Move player to house (leaves current)", "Moving", ["move", "house", "relocate"]),
    (".renmove #House", "Move to renamed house", "Moving", ["move", "renamed", "house"]),
    (".add <#>", "Add player to house (keeps current)", "Moving", ["add", "house", "join"]),
    (".remove <#>", "Remove player from house", "Moving", ["remove", "house", "kick"]),
    (".knock <#>", "Knock on a house door", "Moving", ["knock", "door", "enter"]),
    (".pendingknock / .showknocks", "True/False if any knock is pending + oldest age", "Moving", ["knock", "pending", "status"]),
    (".renknock #House", "Knock on renamed house", "Moving", ["knock", "renamed", "house"]),
    (".pcadd #PC", "Add player to PC/renamed house", "Moving", ["pc", "add", "private"]),
    (".pcremove #PC", "Remove from PC/renamed house", "Moving", ["pc", "remove", "private"]),
    (".addhere #RC", "Add RC's player to this channel", "Moving", ["rc", "add", "channel"]),
    (".home", "Bring the player home", "Home", ["home", "return", "location"]),
    (".home return", "Bring all players home", "Home", ["home", "all", "return"]),
    (".owner", "List house owners", "Home", ["owner", "house", "list"]),
    (".home initialize", "Assign RC + house to alive players", "Home", ["home", "init", "assign", "admin"]),
    (".home setup", "Move sponsors to their player's house", "Home", ["home", "sponsor", "admin"]),
    (".home set @player #house", "Set a player's home", "Home", ["home", "set", "admin"]),
    (".home mset", "Auto-set all current locations as home", "Home", ["home", "auto", "mass", "admin"]),
    (".home list", "List all players' homes", "Home", ["home", "list", "admin"]),
    (".home delete @player", "Make a player homeless", "Home", ["home", "delete", "remove", "admin"]),
    (".rolechat initialize", "Assign RCs only (no houses)", "Home", ["rc", "rolechat", "init", "admin"]),
    (".rolechat check", "List all RCs and their players", "Home", ["rc", "rolechat", "list", "admin"]),
    (".destroy #house", "Move to inaccessible, remove members, announce", "Handling", ["destroy", "house", "delete"]),
    (".fdestroy #house", "Force destroy instantly", "Handling", ["destroy", "force", "instant"]),
    (".decay #house", "Move to inaccessible, narrate in map", "Handling", ["decay", "house", "inactive"]),
    (".rebuild #house", "Rebuild a destroyed house", "Handling", ["rebuild", "restore", "house"]),
    (".decayinactive", "List/decay houses with 24h inactivity", "Handling", ["decay", "inactive", "idle"]),
    (".setowner #PC #RC", "Set a player as PC owner", "Handling", ["owner", "pc", "set"]),
    (".end #PC", "Remove all but the owner from a PC", "Handling", ["pc", "end", "clear", "owner"]),
    (".newpc Public/Private <name> #RC", "Create a PC", "Handling", ["pc", "create", "new", "private"]),
    (".close #PC", "Move PC to Old PCs, remove members", "Handling", ["pc", "close", "archive"]),
    (".public #ch", "Make channel public", "Handling", ["public", "channel", "visibility"]),
    (".private #ch", "Make channel private", "Handling", ["private", "channel", "visibility"]),
    (".channels", "Visual map of all PCs", "Handling", ["map", "pc", "visual", "channels"]),
    (".publicmap", "Map of public channels only", "Handling", ["map", "public", "channels"]),
    (".privatemap", "Map of private channels only", "Handling", ["map", "private", "channels"]),
    (".estatehelp", "Estate map functions help", "Handling", ["estate", "map", "help"]),
    (".estate init #ch", "Init/update estate map", "Handling", ["estate", "init", "map"]),
    (".info #ch", "Show channel info", "Infos", ["info", "channel", "details"]),
    (".info add #ch <text>", "Add info to a channel", "Infos", ["info", "add", "note"]),
    (".info remove #ch <n>", "Remove info by number", "Infos", ["info", "remove", "delete"]),
    (".info reset", "Reset all infos", "Infos", ["info", "reset", "clear"]),
    (".preset", "Add/remove/edit presets with optional ability category", "Presets", ["preset", "ability", "template"]),
    (".ospreset", "View/reorder/remove all presets", "Presets", ["preset", "os", "admin", "manage"]),
    (".ospresetsort", "Reorder preset display categories", "Presets", ["preset", "sort", "order", "admin"]),
    (".vote @player", "Vote or change your vote", "Voting", ["vote", "cast", "change"]),
    (".abstain", "Abstain from voting", "Voting", ["abstain", "skip", "vote"]),
    (".manipulate @target @vote", "Manipulate a player's vote", "Voting", ["manipulate", "control", "force"]),
    (".removevote @player", "Remove a player's vote", "Voting", ["remove", "vote", "clear"]),
    (".skipnight <min_votes>", "Start skip-night vote", "Voting", ["skip", "night", "vote"]),
    (".votelist", "Show all current votes", "Voting", ["vote", "list", "current"]),
    (".resetvotes", "Reset all votes", "Voting", ["reset", "vote", "clear"]),
    (".votehistory/vh [mode]", "Scan vote history", "Voting", ["history", "vote", "log"]),
    (".voteinrc true/false", "Enable voting in RoleChats", "Voting", ["rc", "rolechat", "vote", "toggle"]),
    (".accuse @player #RC", "Accuse (costs 2 tokens, creates channel)", "Nominations", ["accuse", "nominate", "token"]),
    (".intervene #nom-ch", "Pay 1 token to speak in nomination", "Nominations", ["intervene", "speak", "token"]),
    (".voten #nom-ch yes/no", "Vote guilty or not guilty", "Nominations", ["vote", "guilty", "not", "nomination"]),
    (".tokens", "Check your token balance", "Nominations", ["token", "balance", "check"]),
    (".addtokens @user <qty>", "Add tokens", "Nominations", ["token", "add", "admin"]),
    (".removetokens @user <qty>", "Remove tokens", "Nominations", ["token", "remove", "admin"]),
    (".showvotesn #nom-ch", "View nomination votes", "Nominations", ["vote", "show", "nomination", "admin"]),
    (".stopvotes #nom-ch", "Stop nomination (locks channel)", "Nominations", ["stop", "lock", "nomination", "admin"]),
    (".resumevotes #nom-ch", "Resume nomination", "Nominations", ["resume", "unlock", "nomination", "admin"]),
    (".clearvotes", "Clear all nomination votes", "Nominations", ["clear", "vote", "nomination", "admin"]),
    (".playerlist", "List alive members", "Lists", ["player", "alive", "list"]),
    (".sponsorlist", "List sponsor members", "Lists", ["sponsor", "list"]),
    (".houselist", "List visitable houses", "Lists", ["house", "list", "visitable"]),
    (".deadlist", "List dead players and their roles", "Lists", ["dead", "list", "role"]),
    (".setuphouselist", "Init houselist from existing houses", "Lists", ["house", "list", "init", "admin"]),
    (".houselistadd #house", "Add a house to the list", "Lists", ["house", "list", "add", "admin"]),
    (".houselistremove #house", "Remove a house from list", "Lists", ["house", "list", "remove", "admin"]),
    (".deadlist add @player <team> <role>", "Add to deadlist", "Lists", ["dead", "list", "add", "admin"]),
    (".deadlist remove @player", "Remove from deadlist", "Lists", ["dead", "list", "remove", "admin"]),
    (".settarget <channel_id>", "Set target channel (ID, not mention)", "Send Role", ["target", "channel", "set"]),
    (".sendrole/sr <players>", "Reply to a msg, sends role to target", "Send Role", ["send", "role", "forward"]),
    (".teamroll <n1> \"msg1\" <n2> \"msg2\" ...", "Randomly assigns quoted roles (Admin)", "Send Role", ["team", "roll", "random", "assign", "admin"]),
    (".day", "Unlock all day channels", "Utility", ["day", "unlock", "phase"]),
    (".night", "Lock all day channels", "Utility", ["night", "lock", "phase"]),
    (".broom", "Delete replied-to messages (logs kept)", "Utility", ["broom", "delete", "clean", "message"]),
    (".log", "Log message range (count/source/send)", "Utility", ["log", "message", "export"]),
    (".housecheck [hours]", "List quiet houses", "Utility", ["house", "quiet", "check", "inactive"]),
    (".whisper #RC <msg>", "Send anonymous whisper", "Utility", ["whisper", "anonymous", "message"]),
    (".switch", "Toggle Player/Sponsor role", "Utility", ["switch", "role", "toggle", "sponsor"]),
    (".dead", "Move RC to Dead category", "Utility", ["dead", "rc", "move"]),
    (".deadrole", "Mark dead, remove house, pin corpse", "Utility", ["dead", "role", "mark", "corpse"]),
    (".deadc", "Move RC to Dead (admin)", "Utility", ["dead", "rc", "admin"]),
    (".addrole @role @users...", "Give role to members", "Utility", ["role", "add", "give", "admin"]),
    (".removerole <role> <member>", "Remove role (admin)", "Utility", ["role", "remove", "admin"]),
    (".addcategoryperms @role <cat> <perm>", "R=Read, S=Send", "Utility", ["perm", "category", "read", "send", "admin"]),
    (".addchannelperms @role #ch <perm>", "R=Read, S=Send", "Utility", ["perm", "channel", "read", "send", "admin"]),
    (".endgame", "Unlock all channels post-game", "Utility", ["game", "end", "unlock", "admin"]),
    (".statss", "Message counts by role priority", "Utility", ["stats", "message", "count", "admin"]),
    (".setmessagetracking", "Enable/disable tracking", "Utility", ["tracking", "message", "toggle", "admin"]),
    (".start_tracking", "Start message tracking", "Utility", ["tracking", "start", "admin"]),
    (".stop_tracking", "Stop/pause tracking", "Utility", ["tracking", "stop", "pause", "admin"]),
    (".reset_tracking", "Reset message counts", "Utility", ["tracking", "reset", "admin"]),
    (".autovisits", "Toggle auto-visit system", "Utility", ["auto", "visit", "toggle"]),
    (".autorcset", "Set RC for auto-visit", "Utility", ["auto", "rc", "visit", "set"]),
    (".autorcadd @user", "Add user to auto-visit", "Utility", ["auto", "visit", "add", "user"]),
    (".autorcreset", "Reset all auto-visit configs", "Utility", ["auto", "visit", "reset"]),
    (".autoknock", "Toggle auto-knock", "Utility", ["auto", "knock", "toggle"]),
    (".automove", "Toggle auto-move", "Utility", ["auto", "move", "toggle"]),
    (".autostealth", "Toggle stealth mode for auto-visits", "Utility", ["auto", "stealth", "toggle"]),
    (".help [category]", "Show this help menu", "Other", ["help", "menu", "command"]),
    (".who #ch", "List players in a channel", "Other", ["who", "list", "players", "channel"]),
    (".where #RC", "Show a player's current location", "Other", ["where", "location", "find"]),
    (".map", "Show the game map", "Other", ["map", "game", "overview"]),
    (".role /.firstpinned", "Show first pinned in RC", "Other", ["role", "pinned", "first", "pin"]),
    (".roll @role <n>", "Random players from a role", "Other", ["roll", "random", "pick"]),
    (".ping", "Bot online check", "Other", ["ping", "bot", "online", "check"]),
    (".ding", "Dong!", "Other", ["ding", "fun", "easter"]),
    (".narrate #ch <msg>", "Send narration to channels", "Other", ["narrate", "announce", "admin"]),
    (".narration/.n <text>", "Storybook embed (admin, pings)", "Other", ["narration", "story", "embed", "admin"]),
    (".anarration/.na <text>", "Silent narration (admin)", "Other", ["narration", "silent", "admin"]),
    (".narrationcolor", "Pick embed color (admin)", "Other", ["narration", "color", "embed", "admin"]),
    (".dice <n>", "Roll 1-N", "Other", ["dice", "roll", "random", "number"]),
    (".dice <opt1> <opt2> ...", "Random pick from options", "Other", ["dice", "choose", "pick", "random"]),
    (".loc", "Show all houses and occupants", "Other", ["loc", "location", "houses", "occupants"]),
    (".gettag <link>", "Get mentioned users from a message", "Other", ["tag", "mention", "get"]),
    (".timer <time> [tag] [#ch]", "Set a timer", "Other", ["timer", "remind", "countdown"]),
    (".deletechannel", "Delete this channel (admin)", "Other", ["delete", "channel", "admin"]),
    (".deletecategory", "Delete this category (admin)", "Other", ["delete", "category", "admin"]),
    (".timestamp <DD-MM> <HH:MM>", "Gen timestamp with timezone picker", "Other", ["timestamp", "time", "timezone", "convert"]),
    (".time", "Get sent time of replied-to message", "Other", ["time", "message", "sent"]),
    (".dropitem", "Drop interactive item (see docs)", "Other", ["drop", "item", "interactive"]),
    (".revive", "Revive dead players (admin)", "Other", ["revive", "dead", "resurrect", "admin"]),
    (".setupmeetupmatrix", "Toggle automated meetup tracking", "Meetup Matrix", ["meetup", "tracking", "toggle", "admin"]),
    (".setphase day/night", "Trigger phase change (admin)", "Meetup Matrix", ["phase", "day", "night", "change", "admin"]),
    (".forcemeet @p1 @p2", "Force a meetup record (admin)", "Meetup Matrix", ["meet", "force", "record", "admin"]),
    (".allmeets @player", "Show who they've met this phase", "Meetup Matrix", ["meet", "list", "phase"]),
    (".meetupmatrix", "Show full meetup matrix", "Meetup Matrix", ["meetup", "matrix", "grid"]),
    (".meeting", "Request a meeting (max 5 players)", "Meetup Matrix", ["meeting", "request", "schedule"]),
    (".endmeeting", "End your active meeting", "Meetup Matrix", ["meeting", "end", "stop"]),
    (".checkcooldown [@user]", "Check meeting cooldown", "Meetup Matrix", ["meeting", "cooldown", "check"]),
    (".meetingenable", "Enable/disable the meeting system", "Meetup Matrix", ["meeting", "enable", "toggle", "admin"]),
    (".setmeetingchannel #ch", "Set request channel", "Meetup Matrix", ["meeting", "channel", "set", "admin"]),
    (".setmeetingtargetguild <id>", "Set meeting server", "Meetup Matrix", ["meeting", "guild", "server", "admin"]),
    (".setmeetingcategory <cat>", "Set meeting category", "Meetup Matrix", ["meeting", "category", "set", "admin"]),
    (".meetingconfig", "Show current config", "Meetup Matrix", ["meeting", "config", "show", "admin"]),
    (".blockmeeting @user", "Block user from meetings", "Meetup Matrix", ["meeting", "block", "ban", "admin"]),
    (".unblockmeeting @user", "Unblock user", "Meetup Matrix", ["meeting", "unblock", "admin"]),
    (".removecooldown @user", "Remove cooldown", "Meetup Matrix", ["meeting", "cooldown", "remove", "admin"]),
    (".forcemeeting @u1 @u2 ...", "Create forced meeting", "Meetup Matrix", ["meeting", "force", "admin"]),
    (".listblocked", "List blocked users", "Meetup Matrix", ["blocked", "list", "admin"]),
    (".listcooldowns", "List users on cooldown", "Meetup Matrix", ["cooldown", "list", "admin"]),
    (".cancelmeeting", "Cancel pending meeting", "Meetup Matrix", ["meeting", "cancel", "admin"]),
    (".meetingstats", "Show meeting statistics", "Meetup Matrix", ["meeting", "stats", "statistics"]),
    (".bal /.balance", "Show RC balance", "Economy", ["balance", "money", "coins", "rc"]),
    (".shop", "View shop with interactive buttons", "Economy", ["shop", "store", "buy", "items"]),
    (".buy <item> [qty]", "Buy from shop (to RC inventory)", "Economy", ["buy", "purchase", "shop"]),
    (".sell /.sell-item <item>", "Sell for 50% refund", "Economy", ["sell", "refund", "item"]),
    (".inv /.inventory [#ch]", "View RC inventory", "Economy", ["inventory", "items", "rc"]),
    (".give @user <amt>", "Give RC coins (in houses)", "Economy", ["give", "coins", "transfer"]),
    (".give-money @user <amt>", "Transfer from wallet", "Economy", ["money", "transfer", "wallet"]),
    (".use <item>", "Use an item from inventory", "Economy", ["use", "item", "activate"]),
    (".additem <price> <name>", "Add new shop item", "Economy", ["item", "add", "shop", "admin"]),
    (".removeitem /.rmitem #ch <item> [qty]", "Remove from RC", "Economy", ["item", "remove", "rc", "admin"]),
    (".edititem <field> <name> <val>", "Edit shop item", "Economy", ["item", "edit", "shop", "admin"]),
    (".delitem <name>", "Delete item from shop", "Economy", ["item", "delete", "shop", "admin"]),
    (".addmoney #ch <amt>", "Add coins to RC", "Economy", ["money", "add", "coins", "rc", "admin"]),
    (".removemoney #ch <amt>", "Remove coins from RC", "Economy", ["money", "remove", "coins", "rc", "admin"]),
    (".add-money-role @role <amt>", "Add wallet coins by role", "Economy", ["money", "role", "wallet", "admin"]),
    (".additemrole @role <item> <qty>", "Give items by role", "Economy", ["item", "role", "give", "admin"]),
    (".reseteconomy [amt]", "Reset all balances", "Economy", ["economy", "reset", "balance", "admin"]),
    (".clearinventory", "Clear all inventories", "Economy", ["inventory", "clear", "admin"]),
    (".collect", "Add collect amt to every RC", "Economy", ["collect", "money", "rc", "admin"]),
    (".setcollect <val>", "Set collect amount (max 10k)", "Economy", ["collect", "amount", "set", "admin"]),
    (".leaderboard /.lb /.top [n]", "Richest RCs", "Economy", ["leaderboard", "top", "richest", "rcs"]),
    (".mysetloc <location>", "Set your location", "Location", ["location", "set", "timezone"]),
    (".myremoveloc", "Remove your location", "Location", ["location", "remove", "clear"]),
    (".localtime /.lt [@user]", "View local time", "Location", ["time", "local", "timezone"]),
    (".near [@user]", "Find 5 closest members", "Location", ["near", "close", "proximity"]),
    (".locations", "Browse all locations by continent", "Location", ["locations", "browse", "continent"]),
    (".locstats", "Location statistics", "Location", ["location", "stats", "statistics"]),
    (".lochelp /.hloc", "Detailed location help", "Location", ["location", "help"]),
    (".whentime @u1 @u2 ...", "See time for multiple users", "Location", ["time", "multiple", "when"]),
    (".setloc @user <location>", "Set a user's location", "Location", ["location", "set", "admin"]),
    (".remloc @user", "Remove a user's location", "Location", ["location", "remove", "admin"]),
    (".setcontinent @user <cont>", "Assign continent", "Location", ["continent", "set", "admin"]),
    (".listunknown", "List users with unknown continent", "Location", ["unknown", "continent", "list", "admin"]),
    (".refreshtz", "Refresh all timezones", "Location", ["timezone", "refresh", "admin"]),
    (".forceremloc /.forceremoveloc <name/id>", "Force remove", "Location", ["location", "force", "remove", "admin"]),
    (".test_geocoder", "Test geocoder connectivity", "Location", ["geocoder", "test", "admin"]),
    (".mapp", "World map of registered users", "Location", ["map", "world", "users"]),
    (".mapheat", "Heatmap of registered users", "Location", ["heatmap", "density", "map"]),
    (".locsnotset", "Members who haven't set location", "Location", ["location", "not", "set", "missing"]),
    (".dashboard", "Open the role dashboard", "Dashboard", ["dashboard", "role", "ui"]),
    (".dashboardtoggle", "Enable/disable dashboard", "Dashboard", ["dashboard", "toggle", "admin"]),
    (".setrole @role", "Set dashboard role", "Dashboard", ["dashboard", "role", "set", "admin"]),
    (".addpassiveability <name> <desc>", "Add passive ability", "Dashboard", ["ability", "passive", "add", "admin"]),
    (".removepassiveability <name>", "Remove passive", "Dashboard", ["ability", "passive", "remove", "admin"]),
    (".addactiveability <name> <desc> <uses>", "Add active ability", "Dashboard", ["ability", "active", "add", "admin"]),
    (".removeactiveability <name>", "Remove active", "Dashboard", ["ability", "active", "remove", "admin"]),
    (".vb", "View your vote balance", "Dashboard", ["vote", "balance", "vb"]),
    (".checkvb [@user]", "Check vote balance", "Dashboard", ["vote", "balance", "check"]),
    (".setvisits @user <amt>", "Set visit count", "Dashboard", ["visit", "set", "admin"]),
    (".addvisits @user <amt>", "Add visits", "Dashboard", ["visit", "add", "admin"]),
    (".removevisits @user <amt>", "Remove visits", "Dashboard", ["visit", "remove", "admin"]),
    (".actionlog [@user]", "View action log", "Dashboard", ["action", "log", "audit"]),
    (".setboard", "Set up the OS info board", "Dashboard", ["board", "info", "os", "admin"]),
    (".setinfophase <phase>", "Set current phase info", "Dashboard", ["phase", "info", "set", "admin"]),
    (".addcard", "Add an info card", "Dashboard", ["card", "info", "add", "admin"]),
    (".refreshcards", "Refresh all info cards", "Dashboard", ["card", "refresh", "info", "admin"]),
    (".startgame /.sg <slots> @host <name>", "Start a lobby", "Game Manager", ["game", "start", "lobby", "admin"]),
    (".addplayer /.ap <slot> @player [name]", "Fill a slot", "Game Manager", ["player", "add", "slot", "admin"]),
    (".removeplayer /.rp <slot> [name]", "Remove from slot", "Game Manager", ["player", "remove", "slot", "admin"]),
    (".closegame /.cg [name]", "Close & archive game", "Game Manager", ["game", "close", "archive", "admin"]),
    (".stats [@player]", "View player statistics", "Library & Stats", ["stats", "player", "statistics"]),
    (".winrate", "Winrate stats by team", "Library & Stats", ["winrate", "stats", "team"]),
    (".relations [@user]", "Allies and nemeses", "Library & Stats", ["relations", "ally", "nemesis"]),
    (".lib", "Browse the game library", "Library & Stats", ["library", "browse", "games"]),
    (".lib add", "Add a new game", "Library & Stats", ["library", "add", "game", "admin"]),
    (".lib summary", "Summary of all games", "Library & Stats", ["library", "summary", "overview"]),
    (".lib edit <#> <field> <val>", "Edit a game field", "Library & Stats", ["library", "edit", "admin"]),
    (".lib delete <#>", "Delete a game", "Library & Stats", ["library", "delete", "admin"]),
    (".lib deletegame <#>", "Delete a game (alt)", "Library & Stats", ["library", "delete", "admin"]),
    (".lib setwin <#> <team>", "Set winning team", "Library & Stats", ["library", "win", "set", "admin"]),
    (".lib search <term>", "Search by name or player", "Library & Stats", ["library", "search", "find"]),
    (".lib idsearch <id>", "Search by game ID", "Library & Stats", ["library", "search", "id"]),
    (".lib migrateaccount", "Move stats to new account", "Library & Stats", ["library", "migrate", "account"]),
    (".lib mergeaccount", "Merge two accounts' stats", "Library & Stats", ["library", "merge", "account"]),
    (".lib syncname", "Sync display name", "Library & Stats", ["library", "sync", "name"]),
    (".lib bulksyncnames", "Bulk sync all names", "Library & Stats", ["library", "sync", "bulk", "admin"]),
    (".lib help", "Show library help", "Library & Stats", ["library", "help"]),
    (".libit help", "Italian library help", "Library & Stats", ["library", "italian", "help"]),
    (".missingids", "Games with missing player IDs", "Library & Stats", ["missing", "ids", "players", "admin"]),
    (".auxbattle /.aux", "Main Aux Battle command", "Games", ["aux", "battle", "tournament"]),
    (".auxbattle signup", "Sign up for Aux Battle", "Games", ["aux", "signup", "register"]),
    (".auxbattle opensignup", "Open signups (admin)", "Games", ["aux", "signup", "open", "admin"]),
    (".auxbattle closesignup", "Close signups (admin)", "Games", ["aux", "signup", "close", "admin"]),
    (".auxbattle bracket", "View bracket", "Games", ["aux", "bracket", "view"]),
    (".auxbattle reset", "Reset tournament (admin)", "Games", ["aux", "reset", "admin"]),
    (".auxbattle start", "Start tournament (admin)", "Games", ["aux", "start", "admin"]),
    (".auxbattle submit", "Submit battle entry", "Games", ["aux", "submit", "entry"]),
    (".senet help", "Show Senet rules", "Games", ["senet", "rules", "help"]),
    (".senet challenge / sfida @user", "Challenge someone to Senet", "Games", ["senet", "challenge", "duel"]),
    (".senet accept / accetta @user", "Accept a Senet challenge", "Games", ["senet", "accept", "duel"]),
    (".senet roll / lancia", "Roll the dice in Senet", "Games", ["senet", "roll", "dice"]),
    (".senet move / muovi <piece>", "Move a piece in Senet", "Games", ["senet", "move", "piece"]),
    (".senet skip / passo", "Skip your turn in Senet", "Games", ["senet", "skip", "pass"]),
    (".senet status / board", "View the Senet board", "Games", ["senet", "board", "status"]),
    (".senet forfeit / abbandona", "Forfeit the Senet game", "Games", ["senet", "forfeit", "quit"]),
    (".senet rules / regole", "Show the Senet rules", "Games", ["senet", "rules", "regole"]),
    (".birthdays", "List all registered birthdays", "Birthdays", ["birthday", "list", "all"]),
    (".nextbirthdays", "Upcoming birthdays", "Birthdays", ["birthday", "upcoming", "next"]),
    (".helpbday", "Birthday help", "Birthdays", ["birthday", "help"]),
    (".birthday add @user MM-DD", "Add/set a birthday for a user", "Birthdays", ["birthday", "add", "set", "admin"]),
    (".birthday remove @user", "Remove a user's birthday", "Birthdays", ["birthday", "remove", "delete", "admin"]),
    (".bdaystatus", "Check birthday loop status", "Birthdays", ["birthday", "status", "admin"]),
    (".testbday @user", "Test birthday announcement", "Birthdays", ["birthday", "test", "admin"]),
    (".calendar", "English Village Games schedule", "Calendar", ["calendar", "schedule", "english"]),
    (".calendario", "Italian Village Games schedule", "Calendar", ["calendar", "schedule", "italian"]),
    (".vgintro /.vgi", "Village Games intro (EN)", "Calendar", ["intro", "village", "games", "english"]),
    (".vgintro_it /.vgii", "Village Games intro (IT)", "Calendar", ["intro", "village", "games", "italian"]),
    (".draftstart @u1 @u2 ...", "Start a snake draft (admin)", "Draft", ["draft", "start", "snake", "admin"]),
    (".prepick", "Manage your prepicks (max 2)", "Draft", ["draft", "prepick", "pick"]),
    (".draftboard", "Show all teams", "Draft", ["draft", "board", "teams"]),
    (".myteam", "Show your team", "Draft", ["draft", "team", "my"]),
    (".team @user", "Show a user's team with fantasy points", "Draft", ["draft", "team", "fantasy"]),
    (".forcepick <name>", "Force a pick for the current user (admin)", "Draft", ["draft", "force", "pick", "admin"]),
    (".undo", "Undo the most recent pick (admin)", "Draft", ["draft", "undo", "admin"]),
    (".pause", "Pause the draft (admin)", "Draft", ["draft", "pause", "admin"]),
    (".resume", "Resume the draft (admin)", "Draft", ["draft", "resume", "admin"]),
    (".enddraft", "End the draft (admin)", "Draft", ["draft", "end", "admin"]),
    (".draftpoints", "Live fantasy points leaderboard", "Draft", ["draft", "points", "leaderboard"]),
    (".standings", "Standings with avg & best points", "Draft", ["draft", "standings", "rankings"]),
    (".player <name> / .pp", "Look up FIFA fantasy points", "Draft", ["player", "fantasy", "fifa", "points"]),
    (".playerpoints <name>", "FIFA player detail", "Draft", ["player", "points", "detail", "fifa"]),
    (".scoutingboard", "Scouting bonus leaderboard", "Draft", ["scouting", "ownership", "leaderboard"]),
    (".topplayers [N]", "Top N drafted players by points", "Draft", ["top", "players", "rankings"]),
    (".teamvalue @user", "Point breakdown per player on a team", "Draft", ["team", "value", "breakdown"]),
    (".refreshpoints", "Fetch fresh FIFA data (admin)", "Draft", ["fifa", "refresh", "data", "admin"]),
    (".matches [filter] / .matchinfo", "Group standings, tiebreakers & matches via dropdown, or filter by team name", "Draft", ["matches", "results", "fixtures", "standings", "groups"]),
    (".trending [position] / .form", "Players with best form rating", "Draft", ["trending", "form", "players"]),
    (".differentials [N] / .diff", "Best differential picks", "Draft", ["differential", "diff", "value"]),
    (".simulate / .sim / .fsim", "Simulate tournament (ELO/players/dynamic/tactical/match state)", "Draft", ["simulate", "sim", "fsim", "tournament"]),
    (".fsim detailed", "Head-to-head Monte Carlo analysis", "Draft", ["simulate", "detailed", "head", "head"]),
    (".simhelp / .sim help", "Simulation model descriptions (V1-V5)", "Draft", ["simulate", "help", "models"]),
]


COMMON_TIMEZONES = [
    ("UTC", "UTC", "🌐"),
    ("US Eastern", "America/New_York", "🇺🇸"),
    ("US Central", "America/Chicago", "🇺🇸"),
    ("US Mountain", "America/Denver", "🇺🇸"),
    ("US Pacific", "America/Los_Angeles", "🇺🇸"),
    ("Hawaii", "Pacific/Honolulu", "🌺"),
    ("Brazil", "America/Sao_Paulo", "🇧🇷"),
    ("Mexico", "America/Mexico_City", "🇲🇽"),
    ("UK/Ireland", "Europe/London", "🇬🇧"),
    ("Central Europe", "Europe/Paris", "🇪🇺"),
    ("Eastern Europe", "Europe/Bucharest", "🇪🇺"),
    ("Moscow", "Europe/Moscow", "🇷🇺"),
    ("India", "Asia/Kolkata", "🇮🇳"),
    ("China", "Asia/Shanghai", "🇨🇳"),
    ("Japan/Korea", "Asia/Tokyo", "🇯🇵"),
    ("Singapore", "Asia/Singapore", "🇸🇬"),
    ("Dubai", "Asia/Dubai", "🇦🇪"),
    ("Australia Eastern", "Australia/Sydney", "🇦🇺"),
    ("Australia Western", "Australia/Perth", "🇦🇺"),
    ("New Zealand", "Pacific/Auckland", "🇳🇿"),
    ("South Africa", "Africa/Johannesburg", "🇿🇦"),
    ("Cairo", "Africa/Cairo", "🇪🇬"),
]


class TimezoneSelectView(discord.ui.View):
    def __init__(self, user_id: int, dt: datetime):
        super().__init__()
        self.user_id = user_id
        self.dt = dt

    @discord.ui.select(
        placeholder="🌍 Pick a timezone...",
        options=[
            discord.SelectOption(label=label, value=value, emoji=emoji)
            for label, value, emoji in COMMON_TIMEZONES
        ] + [discord.SelectOption(label="Custom...", value="__custom__", emoji="✏️")]
    )
    async def tz_select(self, interaction: discord.Interaction, select: discord.ui.Select):
        if interaction.user.id != self.user_id:
            return                     await interaction.response.send_message("Not your menu.", ephemeral=True)

        value = select.values[0]
        if value == "__custom__":
            await interaction.response.edit_message(
                content="✏️ Use `.timestamp DD-MM HH:MM <timezone>` for a timezone not in the list.",
                view=None,
            )
            return

        try:
            tz = ZoneInfo(value)
        except ZoneInfoNotFoundError:
            await interaction.response.edit_message(
                content="❌ Invalid timezone. Please try again.",
                view=None,
            )
            return
        dt_local = self.dt.replace(tzinfo=tz)
        ts = int(dt_local.timestamp())

        embed = discord.Embed(title="🕐 Discord Timestamps", color=0xff3fb9)
        embed.add_field(name="Relative", value=f"`<t:{ts}:R>` → <t:{ts}:R>", inline=False)
        embed.add_field(name="Full", value=f"`<t:{ts}:F>` → <t:{ts}:F>", inline=False)
        embed.add_field(name="Date Only", value=f"`<t:{ts}:D>` → <t:{ts}:D>", inline=True)
        embed.add_field(name="Time Only", value=f"`<t:{ts}:t>` → <t:{ts}:t>", inline=True)
        embed.add_field(name="Long Time", value=f"`<t:{ts}:T>` → <t:{ts}:T>", inline=True)
        embed.set_footer(text=f"{dt_local.strftime('%d-%m %H:%M')} {value}")

        await interaction.response.edit_message(content=None, embed=embed, view=None)


class ConfirmDeleteView(discord.ui.View):
    def __init__(self, ctx):
        super().__init__(timeout=30)
        self.ctx = ctx
        self.confirmed = False
        self.message = None

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.ctx.author.id:
            await interaction.response.send_message("This confirmation isn't for you.", ephemeral=True)
            return False
        return True

    @discord.ui.button(label="✔ Yes", style=discord.ButtonStyle.green)
    async def confirm_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.confirmed = True
        self.stop()
        await interaction.response.edit_message(content="Deleting...", embed=None, view=None)

    @discord.ui.button(label="❌ No", style=discord.ButtonStyle.red)
    async def cancel_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.stop()
        await interaction.response.edit_message(content="Cancelled.", embed=None, view=None)

    async def on_timeout(self):
        for child in self.children:
            child.disabled = True
        try:
            await self.message.edit(content="Confirmation timed out.", embed=None, view=None)
        except Exception:
            pass


class Other(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @commands.command()
    async def who(self, ctx, channel: discord.TextChannel = None):
        guild_data = load_guild_data(ctx.guild.id)
        if guild_data:
            alive_role = discord.utils.get(ctx.guild.roles, name=guild_data["alive_role_name"])
            alt_role = discord.utils.get(ctx.guild.roles, name=guild_data["alt_role_name"])
            dead_role = discord.utils.get(ctx.guild.roles, name=guild_data["dead_role_name"])
            if channel:
                perms = channel.permissions_for(ctx.author)
                if not ctx.author.guild_permissions.administrator and not perms.read_messages:
                    await ctx.send("You don't have enough perms to use this command")
                    return
            else:
                channel = ctx.channel
            members = channel.members
            embed = discord.Embed(title=f"{channel.name} Members:", color=0xff3fb9, timestamp=datetime.now())
            embed.set_footer(text="Village Game")
            alive_list = []
            dead_list = []
            alt_list = []
            for member in members:
                permissions = channel.permissions_for(member)
                if permissions.send_messages:
                    if alive_role in member.roles:
                        alive_list.append(f"{member.mention} `[{member.display_name}]`")
                    if dead_role in member.roles:
                        dead_list.append(f"{member.mention} `[{member.display_name}]`")
                    if alt_role in member.roles:
                        alt_list.append(f"{member.mention} `[{member.display_name}]`")
            if alive_list:
                embed.add_field(name=f'{alive_role.name}:', value="\n".join(alive_list), inline=False)
            if alt_list:
                embed.add_field(name=f'{alt_role.name}:', value="\n".join(alt_list), inline=False)
            if dead_list:
                embed.add_field(name=f'{dead_role.name}:', value="\n".join(dead_list), inline=False)
            await ctx.send(embed=embed)
        else:
            await ctx.send('Guild data not loaded.')

    @commands.command()
    async def where(self, ctx, channel: discord.TextChannel = None):
        guild_data = load_guild_data(ctx.guild.id)
        if not guild_data:
            await ctx.send("Guild data not loaded")
            return
        spectator_role = discord.utils.get(ctx.guild.roles, name=guild_data["spectator_role_name"])
        if ctx.author.guild_permissions.administrator or spectator_role in ctx.author.roles:
            if channel is None:
                channel = ctx.channel
            alive_role = discord.utils.get(ctx.guild.roles, name=guild_data["alive_role_name"])
            dead_role = discord.utils.get(ctx.guild.roles, name=guild_data["dead_role_name"])
            alt_role = discord.utils.get(ctx.guild.roles, name=guild_data["alt_role_name"])
            category_houses = discord.utils.get(ctx.guild.categories, name=guild_data["houses_category_name"])
            category_pcs = discord.utils.get(ctx.guild.categories, name=guild_data["privc_category_name"])
            category_publc = discord.utils.get(ctx.guild.categories, name=guild_data["publc_category_name"])
            members = channel.members
            for member in members:
                if alive_role in member.roles or dead_role in member.roles or alt_role in member.roles:
                    embed = discord.Embed(title=f"{member.mention} Location:", color=0xff3fb9, timestamp=datetime.now())
                    embed.set_footer(text="Village Game")
                    houses_list = []
                    if category_houses:
                        for house in category_houses.channels:
                            permissions = house.permissions_for(member)
                            if permissions.send_messages:
                                houses_list.append(house.mention)
                    pcs_list = []
                    if category_pcs:
                        for pc in category_pcs.channels:
                            permissions = pc.permissions_for(member)
                            if permissions.send_messages:
                                pcs_list.append(pc.mention)
                    publc_list = []
                    if category_publc:
                        for pubc in category_publc.channels:
                            permissions = pubc.permissions_for(member)
                            if permissions.send_messages:
                                publc_list.append(pubc.mention)
                    if houses_list:
                        embed.add_field(name="🏠 Houses:", value="\n".join(houses_list), inline=False)
                    if pcs_list:
                        embed.add_field(name="👤 Private Chats:", value="\n".join(pcs_list), inline=False)
                    if publc_list:
                        embed.add_field(name="🏟️ Public Channels:", value="\n".join(publc_list), inline=False)
                    await ctx.send(embed=embed)
                    break
        else:
            await ctx.send("You don't have enough perms to use this command")

    @commands.command()
    async def loc(self, ctx):
        guild_data = load_guild_data(ctx.guild.id)
        if not guild_data:
            await ctx.send("Guild data not loaded.")
            return
        spectator_role = discord.utils.get(ctx.guild.roles, name=guild_data["spectator_role_name"])
        if not ctx.author.guild_permissions.administrator and not spectator_role in ctx.author.roles:
            await ctx.send("You don't have enough perms to use this command.")
            return
        alive_role = discord.utils.get(ctx.guild.roles, name=guild_data["alive_role_name"])
        alt_role = discord.utils.get(ctx.guild.roles, name=guild_data["alt_role_name"])
        dead_role = discord.utils.get(ctx.guild.roles, name=guild_data["dead_role_name"])
        houses_category = discord.utils.get(ctx.guild.categories, name=guild_data["houses_category_name"])
        if not houses_category:
            await ctx.send("Houses category not found.")
            return
        embed = discord.Embed(title="Everyone Location:", color=0xff3fb9, timestamp=datetime.now())
        embed.set_footer(text="Village Game")
        content_nempty = ""
        content_empty = ""
        for channel in houses_category.channels:
            players = []
            for member in channel.members:
                if alive_role in member.roles or alt_role in member.roles or dead_role in member.roles:
                    permissions = channel.permissions_for(member)
                    if permissions.send_messages:
                        players.append(member.display_name)
            if players:
                content_nempty += f"{channel.name}\n"
                content_nempty += "\n".join(players) + "\n\n"
            else:
                content_empty += f"{channel.name}\n"
        embed.add_field(name="Non Empty Houses:", value=content_nempty, inline=False)
        embed.add_field(name="Empty Houses:", value=content_empty, inline=False)
        await ctx.send(embed=embed)

    @commands.command(aliases=["t"])
    async def timer(self, ctx, tempo: str, tag: str = None, channel: discord.TextChannel = None):
        channel = channel or ctx.channel
        pattern = re.compile(r"^(?:(?P<hours>\d+)h)?(?:(?P<minutes>\d+)m)?(?:(?P<seconds>\d+)s)?$")
        match = pattern.match(tempo)
        if not match or not any(match.groups()):
            await ctx.send("Invalid format. Example: 1h2m10s")
            return
        time_dict = {k: int(v) if v else 0 for k, v in match.groupdict().items()}
        total_seconds = time_dict['hours'] * 3600 + time_dict['minutes'] * 60 + time_dict['seconds']
        if total_seconds <= 0:
            await ctx.send("Time value must be greater than 0")
            return
        time_parts = []
        if time_dict['hours']:
            time_parts.append(f"{time_dict['hours']}h")
        if time_dict['minutes']:
            time_parts.append(f"{time_dict['minutes']}m")
        if time_dict['seconds']:
            time_parts.append(f"{time_dict['seconds']}s")
        display_time = " ".join(time_parts)
        await ctx.send(f"⏳ Timer set for {display_time}!")
        await asyncio.sleep(total_seconds)
        message = f"⏰ Time's up!"
        if tag == "tag":
            message += f" {ctx.author.mention}"
        await channel.send(message)

    @commands.command()
    async def roll(self, ctx, role_name: str, num_users: str = "1", tag: str = None):
        guild_data = load_guild_data(ctx.guild.id)

        role = discord.utils.get(ctx.guild.roles, name=role_name)
        if not role:
            role = discord.utils.find(lambda r: r.name.lower() == role_name.lower(), ctx.guild.roles)
        if not role:
            role = discord.utils.find(lambda r: role_name.lower() in r.name.lower(), ctx.guild.roles)
        if not role:
            raise commands.BadArgument(f"Role '{role_name}' not found.")

        alt_role = discord.utils.get(ctx.guild.roles, name=guild_data["alt_role_name"])
        if role == alt_role and not ctx.author.guild_permissions.administrator:
            await ctx.send("You don't have enough perms to roll for alts.")
            return
        if role.id == ctx.guild.id and not ctx.author.guild_permissions.administrator:
            await ctx.send("You don't have enough perms to roll for everyone.")
            return

        members_in_role = [member for member in ctx.guild.members if role in member.roles]

        if num_users.lower() == "all":
            num_users_val = len(members_in_role)
        else:
            try:
                num_users_val = int(num_users)
            except ValueError:
                await ctx.send("Insert a valid number or `all`.")
                return

        if num_users_val <= 0:
            await ctx.send('Insert a valid number')
            return
        if len(members_in_role) < num_users_val:
            await ctx.send(f"Not enough members with {role.mention} role", allowed_mentions=discord.AllowedMentions.none())
            return

        random_users = random.sample(members_in_role, num_users_val)

        use_mention = tag and tag.lower() == 'tag'
        if use_mention and not ctx.author.guild_permissions.administrator:
            await ctx.send("You don't have enough perms to use this command")
            return
        if tag and tag.lower() != 'tag':
            await ctx.send(f'{tag} is not a valid argument')
            return

        if use_mention:
            desc = "\n".join(f"`{i}.` {user.mention}" for i, user in enumerate(random_users, 1))
            if len(desc) > 4000:
                desc = desc[:3997] + "..."
        else:
            n = len(random_users)
            col = 1
            if n > 10:
                col = 2
            if n > 20:
                col = 3
            if n > 30:
                col = 4

            SAFE_WIDTH = 78
            if col > 1:
                max_name = max(6, (SAFE_WIDTH // col) - 2)
            else:
                max_name = 40

            names = []
            for user in random_users:
                name = user.display_name
                if wcwidth.wcswidth(name) > max_name:
                    while name and wcwidth.wcswidth(name) > max_name - 3:
                        name = name[:-1]
                    name += "..."
                names.append(name)

            col_widths = [0] * col
            for i, name in enumerate(names):
                c = i % col
                w = wcwidth.wcswidth(name)
                if w > col_widths[c]:
                    col_widths[c] = w
            col_widths = [w + 2 for w in col_widths]

            lines = []
            for i in range(0, n, col):
                row_names = names[i:i + col]
                parts = []
                for c, name in enumerate(row_names):
                    pad = col_widths[c] - wcwidth.wcswidth(name)
                    parts.append(name + " " * pad)
                lines.append("".join(parts))

            grid = "\n".join(lines)
            if len(grid) > 4086:
                grid = grid[:4083] + "..."
            desc = "```\n" + grid + "\n```"

        embed = discord.Embed(
            title=f"🎲 {role.name}",
            description=desc,
            color=role.color if role.color.value else 0xff3fb9,
        )
        embed.set_footer(text=f"Rolled {num_users_val} / {len(members_in_role)} members")
        await ctx.send(embed=embed)

    @commands.command()
    async def narrate(self, ctx, *, message: str):
        if ctx.author.guild_permissions.administrator:
            cleaned_message = re.sub(r'<#\d+>', '', message)
            text_channels = ctx.message.channel_mentions
            target_desc = ""
            if not text_channels:
                guild_data = load_guild_data(ctx.guild.id)
                rc_category = discord.utils.get(ctx.guild.categories, name=guild_data["rc_category_name"])
                alt_category = discord.utils.get(ctx.guild.categories, name=guild_data["alt_category_name"])
                count = len(rc_category.text_channels) if rc_category else 0
                count += len(alt_category.text_channels) if alt_category else 0
                target_desc = f"all **{count}** RoleChats"
            else:
                target_desc = f"{len(text_channels)} channel(s): " + ", ".join(ch.mention for ch in text_channels)
            await ctx.send(
                f"This will send the narration to {target_desc}.\n"
                f"Reply with **yes** to confirm, anything else to cancel.\n"
                f"*(If you meant to narrate an ability, use `.narration` instead)*"
            )
            def check(m):
                return m.author == ctx.author and m.channel == ctx.channel
            try:
                response = await self.bot.wait_for("message", timeout=30, check=check)
            except asyncio.TimeoutError:
                return await ctx.send("Action cancelled (timeout).")
            if response.content.lower() != "yes":
                return await ctx.send("Action cancelled.")
            if not text_channels:
                guild_data = load_guild_data(ctx.guild.id)
                rc_category = discord.utils.get(ctx.guild.categories, name=guild_data["rc_category_name"])
                alt_category = discord.utils.get(ctx.guild.categories, name=guild_data["alt_category_name"])
                if rc_category:
                    for channel in rc_category.text_channels:
                        await channel.send(cleaned_message)
                if alt_category:
                    for c in alt_category.text_channels:
                        await c.send(cleaned_message)
            else:
                for channel in text_channels:
                    await channel.send(cleaned_message)
            await ctx.send('Done')
        else:
            await ctx.send("You don't have enough perms to use this command")

    def _get_referenced_houses(self, guild_data, ctx, text):
        houses = []
        houselist = guild_data.get("houselist") or []
        if not isinstance(houselist, list):
            houselist = []
        if ctx.channel and ctx.channel.name in houselist:
            houses.append(ctx.channel.name)
        for cid in re.findall(r"<#(\d+)>", text):
            ch = ctx.guild.get_channel(int(cid))
            if ch and ch.name in houselist:
                houses.append(ch.name)
        text_lower = text.lower()
        for h in houselist:
            if h.lower() in text_lower:
                if h not in houses:
                    houses.append(h)
        return houses

    async def _send_narration(self, ctx, text, ping_roles=True):
        text = re.sub(r'@(everyone|here)', '@\u200b\\1', text)
        def _replace_role(m):
            r = ctx.guild.get_role(int(m.group(1)))
            return f'@\u200b{r.name if r else "deleted-role"}'
        text = re.sub(r'<@&(\d+)>', _replace_role, text)

        guild_data = load_guild_data(ctx.guild.id)
        color = guild_data.get("narration_color", 0xdc143c) if guild_data else 0xdc143c

        ping_parts = []
        if ping_roles and guild_data:
            alive_role = discord.utils.get(ctx.guild.roles, name=guild_data["alive_role_name"])
            sponsor_role = discord.utils.get(ctx.guild.roles, name=guild_data["sponsor_role_name"])
            if alive_role:
                ping_parts.append(alive_role.mention)
            if sponsor_role:
                ping_parts.append(sponsor_role.mention)

        embeds = []
        max_desc = 4096
        while text:
            chunk = text[:max_desc]
            text = text[max_desc:]
            embed = discord.Embed(description=chunk, color=color)
            embed.set_author(name=ctx.author.display_name, icon_url=ctx.author.display_avatar.url)
            embeds.append(embed)

        try:
            for i, e in enumerate(embeds):
                content = " ".join(ping_parts) if ping_parts and i == 0 else None
                await ctx.send(content=content, embed=e)
        except discord.Forbidden:
            await ctx.send("I don't have permission to send embeds here.")
            return
        except Exception as e:
            print(f"[Narration] Error sending embed: {e}")
            await ctx.send("An error occurred while sending the narration.")
            return

        try:
            await ctx.message.delete(delay=3)
        except (discord.Forbidden, discord.HTTPException):
            pass

        prefix = ctx.prefix if isinstance(ctx.prefix, str) else (ctx.clean_prefix if hasattr(ctx, 'clean_prefix') else '.')
        original_text = ctx.message.content[len(prefix) + len(ctx.invoked_with or ""):].strip()

        try:
            log_dir = os.path.join("data", "narration_logs")
            os.makedirs(log_dir, exist_ok=True)
            log_path = os.path.join(log_dir, f"{ctx.guild.id}.log")
            ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            location = f"#{ctx.channel.name}" if ctx.channel else "unknown"
            with open(log_path, "a", encoding="utf-8") as f:
                f.write(f"[{ts}] {ctx.author.display_name} ({ctx.author.id}) in {location}: {original_text}\n")
        except Exception as e:
            print(f"[Narration] Failed to write log: {e}")

        if guild_data:
            houses = self._get_referenced_houses(guild_data, ctx, original_text)
            house_str = ", ".join(f"`{h}`" for h in houses) if houses else None
            msg_link = f"https://discord.com/channels/{ctx.guild.id}/{ctx.channel.id}/{ctx.message.id}"

            log_ch_name = guild_data.get("narration_log_channel_name") or "✍️│commentary"
            log_ch = discord.utils.get(ctx.guild.channels, name=log_ch_name)
            if not log_ch:
                import unicodedata
                norm = unicodedata.normalize("NFC", log_ch_name)
                log_ch = next((c for c in ctx.guild.channels if unicodedata.normalize("NFC", c.name) == norm), None)
            if log_ch:
                try:
                    parts = [f"**{ctx.author.display_name}** in {ctx.channel.mention}"]
                    if house_str:
                        parts.append(f"📪 {house_str}")
                    parts.append(f"[Jump]({msg_link})")
                    header = " — ".join(parts)
                    for e in embeds:
                        await log_ch.send(content=header, embed=e)
                        header = None
                except (discord.Forbidden, discord.HTTPException):
                    pass

    @commands.command(aliases=["n"])
    async def narration(self, ctx, *, text: str = None):
        """Send a storybook-style narration embed (admin only). Pings @Alive and @Sponsor."""
        if not ctx.author.guild_permissions.administrator:
            return await ctx.send("You don't have enough perms to use this command")
        if text is None:
            embed = discord.Embed(
                title="📖 Narration",
                description="Usage: `.narration <text>`\nSend a storybook-style narration embed (admin only).\nAlias: `.n`\n\nAdmins can pick the embed color with `.narrationcolor`",
                color=0xff3fb9
            )
            embed.add_field(name="Example", value="`.narration The detective quietly watched from the shadows.`", inline=False)
            return await ctx.send(embed=embed)
        await self._send_narration(ctx, text, ping_roles=True)

    @commands.command(aliases=["na"])
    async def anarration(self, ctx, *, text: str = None):
        """Send a narration embed without pinging roles (admin only)."""
        if not ctx.author.guild_permissions.administrator:
            return await ctx.send("You don't have enough perms to use this command")
        if text is None:
            embed = discord.Embed(
                title="📖 Narration (silent)",
                description="Usage: `.anarration <text>`\nSend a narration embed without pinging anyone.\nAlias: `.na`\n\nSame as `.narration` but no role ping.",
                color=0xff3fb9
            )
            embed.add_field(name="Example", value="`.anarration The wind howled through the empty streets.`", inline=False)
            return await ctx.send(embed=embed)
        await self._send_narration(ctx, text, ping_roles=False)

    @commands.command(name="narrationcolor")
    async def narrationcolor(self, ctx):
        """Pick a narration embed color from presets (admin only)."""
        if not ctx.author.guild_permissions.administrator:
            return await ctx.send("You don't have enough perms to use this command")
        guild_data = load_guild_data(ctx.guild.id)
        current = guild_data.get("narration_color", 0xdc143c) if guild_data else 0xdc143c
        embed = discord.Embed(
            title="🎨 Narration Color",
            description="Choose a color below:",
            color=current,
        )
        embed.set_footer(text="Current color shown above")
        view = NarrationColorView(ctx)
        msg = await ctx.send(embed=embed, view=view)
        view.message = msg
        await view.wait()

    @commands.command()
    async def revive(self, ctx):
        """Revive dead players in this RC channel (admin only)."""
        if not ctx.author.guild_permissions.administrator:
            return await ctx.send("You don't have enough perms to use this command")
        guild_data = load_guild_data(ctx.guild.id)
        if not guild_data:
            return await ctx.send("Guild data not loaded.")
        rc_category = discord.utils.get(ctx.guild.categories, name=guild_data["rc_category_name"])
        dead_rc_category = discord.utils.get(ctx.guild.categories, name=guild_data["dead_rc_category_name"])
        if ctx.channel.category not in [rc_category, dead_rc_category]:
            return await ctx.send("This command only works in RoleChat (RC) channels.")
        dead_role = discord.utils.get(ctx.guild.roles, name=guild_data["dead_role_name"])
        if not dead_role:
            return await ctx.send("Dead role not found on this server.")
        dead_members = [m for m in ctx.channel.members if dead_role in m.roles]
        if not dead_members:
            return await ctx.send("No players with the Dead role in this channel.")
        view = ReviveView(ctx, guild_data, dead_members)
        embed = discord.Embed(description="Select players to revive:", color=0xDC143C)
        msg = await ctx.send(embed=embed, view=view)
        view.message = msg
        await view.wait()

    @commands.command()
    async def deletechannel(self, ctx):
        if ctx.author.guild_permissions.administrator:
            view = ConfirmDeleteView(ctx)
            embed = discord.Embed(description="Are you sure you want to delete this channel?", color=0xff0000)
            msg = await ctx.send(embed=embed, view=view)
            view.message = msg
            await view.wait()
            if view.confirmed:
                await ctx.channel.delete()
        else:
            await ctx.send("You don't have enough perms to use this command")

    @commands.command()
    async def deletecategory(self, ctx):
        if ctx.author.guild_permissions.administrator:
            if ctx.channel.category:
                category = ctx.channel.category
                view = ConfirmDeleteView(ctx)
                embed = discord.Embed(description=f"Are you sure you want to delete the category **{category.name}** and all its channels?", color=0xff0000)
                msg = await ctx.send(embed=embed, view=view)
                view.message = msg
                await view.wait()
                if view.confirmed:
                    for channel in category.channels:
                        await channel.delete()
                    await category.delete()
            else:
                await ctx.send("This channel doesn't have a category")
        else:
            await ctx.send("You don't have enough perms to use this command")

    @commands.command(aliases=["ts"])
    async def timestamp(self, ctx, date_str: str = None, time_str: str = None):
        """Generate Discord timestamps that show in everyone's local time.
        
        Usage: .timestamp DD-MM HH:MM
        Example: .timestamp 25-12 14:30
        
        Year is assumed to be {datetime.now().year}.
        After submitting, pick a timezone from the dropdown.
        """
        if date_str is None or time_str is None:
            await ctx.send("❌ Usage: `.timestamp DD-MM HH:MM` — e.g. `.timestamp 25-12 14:30`\nThen pick a timezone from the dropdown.")
            return

        try:
            dt = datetime.strptime(f"{date_str} {time_str}", "%d-%m %H:%M")
            dt = dt.replace(year=datetime.now().year)
        except ValueError:
            await ctx.send("❌ Wrong format. Use `.timestamp DD-MM HH:MM` (e.g. `.timestamp 25-12 14:30`) then pick a timezone from the dropdown.")
            return

        view = TimezoneSelectView(ctx.author.id, dt)
        await ctx.send("🌍 **Select a timezone:**", view=view)

    @commands.command()
    async def time(self, ctx):
        if ctx.message.reference:
            replied_message = await ctx.channel.fetch_message(ctx.message.reference.message_id)
            timestamp = replied_message.created_at
            discord_timestamp = f"<t:{int(timestamp.timestamp())}:T>"
            await ctx.send(f"The message was sent at: {discord_timestamp}")
        else:
            await ctx.send("You need to reply to a message to use this command.")

    @commands.command()
    async def gettag(self, ctx, *, arg=None):
        msg = None
        if ctx.message.reference:
            msg = await ctx.channel.fetch_message(ctx.message.reference.message_id)
        elif arg:
            m = re.search(r'/channels/\d+/(\d+)/(\d+)', arg)
            if m:
                channel_id, message_id = map(int, m.groups())
                chan = self.bot.get_channel(channel_id) or await self.bot.fetch_channel(channel_id)
                msg = await chan.fetch_message(message_id)
            else:
                try:
                    msg = await ctx.channel.fetch_message(int(arg))
                except Exception:
                    await ctx.reply("Invalid message ID or link.", mention_author=False)
                    return
        else:
            await ctx.reply("Please reply to a message or provide its ID/link.", mention_author=False)
            return
        mentions = msg.mentions
        if not mentions:
            return await ctx.reply("No user mentions found in that message.", mention_author=False)
        mention_list = ' '.join(user.mention for user in mentions)
        await ctx.send(mention_list, allowed_mentions=AllowedMentions(users=False, roles=False))
        
    @commands.command(name="firstpin", aliases=["role"])
    async def firstpin(self, ctx, channel: discord.TextChannel = None):
        guild_data = load_guild_data(ctx.guild.id)
        if not guild_data:
            await ctx.send("Guild data not loaded")
            return
        spectator_role = discord.utils.get(ctx.guild.roles, name=guild_data["spectator_role_name"])
        if not ctx.author.guild_permissions.administrator and channel:
            if not spectator_role in ctx.author.roles:
                await ctx.send("You do not have permission to use this command.")
                return
        if channel is None:
            channel = ctx.channel
        pins = await channel.pins()
        if not pins:
            await ctx.send("No pinned messages were found in that channel.")
            return
        first_pin = pins[-1]
        embed = discord.Embed(title="First Pinned Message", description=first_pin.content or "*[No content]*", color=0xff3fb9, timestamp=datetime.now())
        embed.add_field(name=" ", value=f"[Jump to the message!]({first_pin.jump_url})", inline=False)
        embed.set_footer(text="Village Game")
        await ctx.send(embed=embed)
            
    @commands.command()
    async def ping(self, ctx):
        await ctx.send('Pong')

    @commands.command()
    async def ding(self, ctx):
        await ctx.send("Dong! ||MF||")

    @commands.command()
    async def dice(self, ctx, *args):
        if not args:
            await ctx.send("Usage: `.dice <number>` to roll 1-N, or `.dice <option1> <option2> ...` to pick randomly.")
            return
        if len(args) == 1:
            try:
                n = int(args[0])
            except ValueError:
                await ctx.send(f"`{args[0]}` is not a valid number. Usage: `.dice <number>` or `.dice <opt1> <opt2> ...`")
                return
            if n < 1:
                await ctx.send(f"Number must be 1 or higher. Usage: `.dice <number>`")
                return
            result = random.randint(1, n)
            await ctx.send(f"🎲 You rolled a **{result}** (1–{n})!")
        else:
            choice = random.choice(args)
            await ctx.send(f"🎲 I picked: **{choice}**")


    @commands.command()
    async def goat(self, ctx):
        if ctx.author.id == 388776401668538368 or ctx.author.id == 450772749829537793:
            message = await ctx.send('# 🚨 ATTENTION EVERYONE 🚨\nPlease pause your regularly scheduled mediocrity.\nWe’re here to honor the one they tried to contain—but never could.\n\n💥🔥 THE UNDISPUTED LEGEND 🔥💥\n🎖️ MVP of MVPs\n🏆 Winner of Winners\n📜 So decorated, the awards had to be printed in landscape mode\n🥇 Made Heartside rewrite its policy to fit all his wins\n👑 The reason "balance" nerfs exist\n\n# GALAMT — THE ABSOLUTE GOAT\n\nToo powerful to play as a contestant—now only allowed as a sponsor. Because Some OS dont Like him \nWhy? Because every time he plays, the game breaks.\nOverseers are forced to nerf him constantly, or the meta collapses.\n\nHe won 2 times as the evil team with just a 1% chance of victory.\nStatistically impossible.\nGalamt just called it "a Tuesday."\n\n🕯️ Founder of ECG – Evil Cult Graveyard\nIt started as a meme cult during a social deduction match…\nAnd somehow, it’s still active.\nHe didn’t plan to make history—history followed him.\n\nThat look?\n✔️ “I didn’t ask for this power.”\n✔️ “I logged in for fun and broke the leaderboard.”\n✔️ “This isn’t a bug. It’s legacy.”\n\n**#Galamt**\n**#ECG**\n**#TooPowerful**\n**#SponsorOnly**\n**#LionOfTheMeta**')
            await message.delete(delay=60)

    @commands.command()
    async def help2(self, ctx, category: str = None):
        """Show additional command categories."""
        if category is not None:
            category = category.lower()
            extra_categories = {
                "meetupmatrix": self.help_meetupmatrix,
                "economy": self.help_economy,
                "location": self.help_location,
                "dashboard": self.help_dashboard,
                "gamemanager": self.help_gamemanager,
                "library": self.help_library,
                "games": self.help_games,
                "birthdays": self.help_birthdays,
                "calendar": self.help_calendar,
            }
            if category in extra_categories:
                self._in_help2 = True
                await extra_categories[category](ctx)
                return
        self._in_help2 = True
        embed = discord.Embed(title="📂 Extended Command Categories", color=0xff3fb9)
        embed.add_field(name="📊 - Meetings & Meetup Matrix", value="21 Commands\n`.help2 meetupmatrix`", inline=True)
        embed.add_field(name="💰 - Economy", value="18 Commands\n`.help2 economy`", inline=True)
        embed.add_field(name="📍 - Location", value="18 Commands\n`.help2 location`", inline=True)
        embed.add_field(name="🎮 - Dashboard & Info", value="17 Commands\n`.help2 dashboard`", inline=True)
        embed.add_field(name="🎲 - Game Manager", value="4 Commands\n`.help2 gamemanager`", inline=True)
        embed.add_field(name="📚 - Library & Stats", value="19 Commands\n`.help2 library`", inline=True)
        embed.add_field(name="⚔️ - Games (Aux, Senet)", value="18 Commands\n`.help2 games`", inline=True)
        embed.add_field(name="🎂 - Birthdays", value="6 Commands\n`.help2 birthdays`", inline=True)
        embed.add_field(name="📅 - Calendar & Intro", value="4 Commands\n`.help2 calendar`", inline=True)
        embed.set_footer(text="Village Game • Use `.help2 {category}` for details")
        await self.send_help_page(ctx, embed, self.help2)

    @commands.command(name="searchhelp", aliases=["sh"])
    async def searchhelp(self, ctx, *, keyword: str):
        """Search all commands by keyword or regex pattern."""
        if not keyword:
            return await ctx.send(
                "Usage: `.searchhelp <keyword>` or `.sh <keyword>`\n"
                "Searches command names, descriptions, and tags. Supports regex.\n"
                "Example: `.sh private` — finds all commands about private channels"
            )

        try:
            pattern = re.compile(keyword, re.IGNORECASE)
        except re.error:
            return await ctx.send(f"❌ Invalid regex: `{keyword}`")

        matches = []
        seen = set()
        for cmd, desc, cat, tags in COMMAND_INDEX:
            searchable = f"{cmd} {desc} {' '.join(tags)}"
            if pattern.search(searchable):
                key = (cmd, cat)
                if key not in seen:
                    seen.add(key)
                    matches.append((cmd, desc, cat))

        if not matches:
            return await ctx.send(f"❌ No commands found matching `{keyword}`.")

        matches.sort(key=lambda x: (x[2], x[0]))

        embed = discord.Embed(
            title=f"🔍 Search results for `{keyword}`",
            description=f"Found **{len(matches)}** matching command{'s' if len(matches) != 1 else ''}",
            color=0xff3fb9
        )

        current_cat = None
        lines = []
        for cmd, desc, cat in matches:
            if cat != current_cat:
                if lines:
                    embed.add_field(name=f"📁 {current_cat}", value="\n".join(lines), inline=False)
                current_cat = cat
                lines = []
            lines.append(f"**`{cmd}`** ─ {desc}")
        if lines:
            embed.add_field(name=f"📁 {current_cat}", value="\n".join(lines), inline=False)

        embed.set_footer(text="Village Game • Use `.help <category>` for the full category")
        await ctx.send(embed=embed)

    @commands.command()
    async def help(self, ctx, category: str = None):
        self._in_help2 = False
        if category is None:
            await self.help_homepage(ctx)
        else:
            category = category.lower()
            categories = {
                "setup": self.help_setup,
                "moving": self.help_moving,
                "home": self.help_home,
                "handling": self.help_handling,
                "infos": self.help_infos,
                "presets": self.help_presets,
                "voting": self.help_voting,
                "nominations": self.help_nominations,
                "lists": self.help_lists,
                "sendrole": self.help_sendrole,
                "utility": self.help_utility,
                "other": self.help_other,
                "meetupmatrix": self.help_meetupmatrix,
                "economy": self.help_economy,
                "location": self.help_location,
                "dashboard": self.help_dashboard,
                "gamemanager": self.help_gamemanager,
                "library": self.help_library,
                "games": self.help_games,
                "birthdays": self.help_birthdays,
                "calendar": self.help_calendar,
                "draft": self.help_draft,
                "botc": self.help_botc,
            }
            if category in categories:
                await categories[category](ctx)
            else:
                await ctx.send(f"{category} is not a valid category")

    async def send_help_page(self, ctx, embed, _help_method=None, options=None):
        if options is None:
            in_help2 = getattr(self, '_in_help2', False)
            if in_help2:
                options = [
                    discord.SelectOption(label="📊 - Meetings & Meetup Matrix", value="meetupmatrix", description="Get all 'Meetings & Meetup Matrix' commands"),
                    discord.SelectOption(label="💰 - Economy", value="economy", description="Get all 'Economy' commands"),
                    discord.SelectOption(label="📍 - Location", value="location", description="Get all 'Location' commands"),
                    discord.SelectOption(label="🎮 - Dashboard & Info", value="dashboard", description="Get all 'Dashboard & OS Info' commands"),
                    discord.SelectOption(label="🎲 - Game Manager", value="gamemanager", description="Get all 'Game Manager' commands"),
                    discord.SelectOption(label="📚 - Library & Stats", value="library", description="Get all 'Library & Stats' commands"),
                    discord.SelectOption(label="⚔️ - Games (Aux, Senet)", value="games", description="Get all 'Games' commands"),
                    discord.SelectOption(label="🎂 - Birthdays", value="birthdays", description="Get all 'Birthday' commands"),
                    discord.SelectOption(label="📅 - Calendar & Intro", value="calendar", description="Get all 'Calendar & Intro' commands"),
                ]
                route_fn = lambda cat: self.help2(ctx, category=cat)
            else:
                options = [
                    discord.SelectOption(label="🏗️ - Setup", value="setup", description="Get all 'Setup' commands"),
                    discord.SelectOption(label="👟 - Moving", value="moving", description="Get all 'Moving' commands"),
                    discord.SelectOption(label="🏡 - Home", value="home", description="Get all 'Home' commands"),
                    discord.SelectOption(label="🔓 - Houses and PCs handling", value="handling", description="Get all 'Handling' commands"),
                    discord.SelectOption(label="📜 - Infos", value="infos", description="Get all 'Infos' commands"),
                    discord.SelectOption(label="🎟️ - Presets", value="presets", description="Get all 'Presets' commands"),
                    discord.SelectOption(label="🗳️ - Voting", value="voting", description="Get all 'Voting' commands"),
                    discord.SelectOption(label="👉 - Nominations", value="nominations", description="Get all 'Nominations' commands"),
                    discord.SelectOption(label="📄 - Lists", value="lists", description="Get all 'Lists' commands"),
                    discord.SelectOption(label="↪ - Send Role", value="sendrole", description="Get all 'Send Role' commands"),
                    discord.SelectOption(label="⚙️ - Utility", value="utility", description="Get all 'Utility' commands"),
                    discord.SelectOption(label="👽 - Other", value="other", description="Get all 'Other' commands"),
                    discord.SelectOption(label="🐦 - BOTC", value="botc", description="Get all 'Blood on the Clocktower' commands"),
                ]
                route_fn = lambda cat: self.help(ctx, category=cat)
        else:
            route_fn = lambda cat: self.help2(ctx, category=cat)
        select = Select(
            placeholder="Choose an option",
            options=options,
        )
        view = View()
        view.add_item(select)
        if isinstance(ctx, discord.Interaction):
            await ctx.response.send_message(embed=embed, view=view)
            message = await ctx.original_response()
        else:
            message = await ctx.send(embed=embed, view=view)
        async def on_select(interaction):
            if interaction.message.id == message.id:
                await message.delete()
                category = interaction.data["values"][0]
                await route_fn(category)
        select.callback = on_select

    async def help_homepage(self, ctx):
        embedh = discord.Embed(title="Village Game - Commands list", color=0xff3fb9)
        embedh.add_field(name="🏗️ - Setup", value="19 Commands\n`.help setup`", inline=True)
        embedh.add_field(name="👟 - Moving", value="9 Commands\n`.help moving`", inline=True)
        embedh.add_field(name="🏡 - Home", value="12 Commands\n`.help home`", inline=True)
        embedh.add_field(name="🔓 - Houses and PCs handling", value="16 Commands\n`.help handling`", inline=True)
        embedh.add_field(name="📜 - Infos", value="4 Commands\n`.help infos`", inline=True)
        embedh.add_field(name="🎟️ - Presets", value="3 Commands\n`.help presets`", inline=True)
        embedh.add_field(name="🗳️ - Voting", value="7 Commands\n`.help voting`", inline=True)
        embedh.add_field(name="👉 - Nominations", value="10 Commands\n`.help nominations`", inline=True)
        embedh.add_field(name="📄 - Lists", value="9 Commands\n`.help lists`", inline=True)
        embedh.add_field(name="↪ - Send Role", value="2 Commands\n`.help sendrole`", inline=True)
        embedh.add_field(name="⚙️ - Utility", value="21 Commands\n`.help utility`", inline=True)
        embedh.add_field(name="👽 - Other", value="22 Commands\n`.help other`", inline=True)
        embedh.add_field(name="🏆 - Draft", value="20 Commands\n`.help draft`", inline=True)
        embedh.add_field(name="🐦 - Blood on the Clocktower", value="All Commands\n`.help botc`", inline=True)
        embedh.set_footer(text="Village Game • You can also use `.help {category}` to select the category")
        await self.send_help_page(ctx, embedh, self.help_homepage)

    async def help_setup(self, ctx):
        embeds = discord.Embed(title="🏗️ - Setup commands", description="19 Commands", color=0xff3fb9)
        embeds.add_field(name="Core Setup", value=(
            "**`.setup <num>`** ─ Setup roles, channels & categories\n"
            "**`.roleset <key> @role`** ─ Assign a role for the bot\n"
            "**`.channelset <key> #ch`** ─ Assign a channel for the bot\n"
            "**`.categoryset <key> <name>`** ─ Assign a category\n"
            "━━━━━━━━━━━━━━━━\n"
            "**`.houseprefix <pfx>`** ─ Set house name prefix\n"
            "**`.knockduration <sec>`** ─ Set knock timeout duration\n"
            "**`.maxpinh <num>`** ─ Max players per house\n"
            "**`.refuseresponse 1/2/3`** ─ Knock refuse behavior\n"
            "━━━━━━━━━━━━━━━━\n"
            "**`.settings`** ─ View current settings\n"
            "**`.resetdb`** ─ Reset all setup"
        ), inline=False)
        embeds.add_field(name="Toggles & Flags", value=(
            "**`.showwhispersender`** ─ Show/hide whisper sender\n"
            "**`.ajifempty`** ─ Auto-join if house is empty\n"
            "**`.ajknockexpire`** ─ Auto-join when knock expires\n"
            "**`.deadcount`** ─ Deads count for AJ/MaxPlayers\n"
            "**`.altcount`** ─ Alts count for AJ/MaxPlayers\n"
            "━━━━━━━━━━━━━━━━\n"
            "**`.showdeadsonrefuse`** ─ Show deads on knock refuse\n"
            "**`.showaltsonrefuse`** ─ Show alts on knock refuse\n"
            "**`.candeadsinteract`** ─ Deads can open/refuse\n"
            "**`.canaltsinteract`** ─ Alts can open/refuse\n"
            "━━━━━━━━━━━━━━━━\n"
            "Set UnbelievaBot replies with `!edititem reply`:\n"
            "Fireworks → `fireworks` / Whisper → `whisper` / Move in → `move in`"
        ), inline=False)
        embeds.set_footer(text="Village Game • All listed commands need the prefix `.` to work")
        await self.send_help_page(ctx, embeds, self.help_setup)

    async def help_moving(self, ctx):
        embedm = discord.Embed(title="👟 - Moving commands", description='Add "stealth" after any command to suppress join/leave narrations. Add "read" after add/move/renmove/pcadd for read-only access.', color=0xff3fb9)
        embedm.add_field(name="Move & Knock", value=(
            "**`.move <#>`** ─ Move player to house (leaves current)\n"
            "**`.renmove #House`** ─ Move to renamed house\n"
            "**`.add <#>`** ─ Add player to house (keeps current)\n"
            "**`.remove <#>`** ─ Remove player from house\n"
            "━━━━━━━━━━━━━━━━\n"
            "**`.knock <#>`** ─ Knock on a house door\n"
            "  *Open* ─ Knocker joins (leaves current)\n"
            "  *Refuse* ─ Knocker sees occupants\n"
            "  *Expires* ─ OS notified in RC\n"
            "**`.pendingknock`** / `.showknocks` ─ True/False if any knock is pending + oldest age\n"
            "**`.renknock #House`** ─ Knock on renamed house"
        ), inline=False)
        embedm.add_field(name="PC & Misc", value=(
            "**`.pcadd #PC`** ─ Add player to PC/renamed house\n"
            "**`.pcremove #PC`** ─ Remove from PC/renamed house\n"
            "**`.addhere #RC`** ─ Add RC's player to this channel"
        ), inline=False)
        embedm.set_footer(text="Village Game • All listed commands need the prefix `.` to work")
        await self.send_help_page(ctx, embedm, self.help_moving)

    async def help_home(self, ctx):
        embedh = discord.Embed(title="🏡 - Home commands", description="12 commands", color=0xff3fb9)
        embedh.add_field(name="Player Commands", value=(
            "**`.home`** ─ Bring the player home\n"
            "**`.home return`** ─ Bring all players home\n"
            "**`.owner`** ─ List house owners"
        ), inline=False)
        embedh.add_field(name="Admin Commands", value=(
            "**`.home initialize`** ─ Assign RC + house to alive players\n"
            "**`.home setup`** ─ Move sponsors to their player's house\n"
            "**`.home set @player #house`** ─ Set a player's home\n"
            "**`.home mset`** ─ Auto-set all current locations as home\n"
            "**`.home list`** ─ List all players' homes\n"
            "**`.home delete @player`** ─ Make a player homeless\n"
            "━━━━━━━━━━━━━━━━\n"
            "**`.rolechat initialize`** ─ Assign RCs only (no houses)\n"
            "**`.rolechat check`** ─ List all RCs and their players"
        ), inline=False)
        embedh.set_footer(text="Village Game • All listed commands need the prefix `.` to work")
        await self.send_help_page(ctx, embedh, self.help_home)

    async def help_handling(self, ctx):
        embedhan = discord.Embed(title="🔓 - Houses and PCs handling", description="16 commands", color=0xff3fb9)
        embedhan.add_field(name="Houses", value=(
            "**`.destroy #house`** ─ Move to inaccessible, remove members, announce\n"
            "**`.fdestroy #house`** ─ Force destroy instantly\n"
            "**`.decay #house`** ─ Move to inaccessible, narrate in map\n"
            "**`.rebuild #house`** ─ Rebuild a destroyed house\n"
            "**`.decayinactive`** ─ List/decay houses with 24h inactivity\n"
            "━━━━━━━━━━━━━━━━\n"
            "**`.setowner #PC #RC`** ─ Set a player as PC owner\n"
            "**`.end #PC`** ─ Remove all but the owner from a PC"
        ), inline=False)
        embedhan.add_field(name="PCs & Maps", value=(
            "**`.newpc Public/Private <name> #RC`** ─ Create a PC\n"
            "**`.close #PC`** ─ Move PC to Old PCs, remove members\n"
            "**`.public #ch`** ─ Make channel public\n"
            "**`.private #ch`** ─ Make channel private\n"
            "━━━━━━━━━━━━━━━━\n"
            "**`.channels`** ─ Visual map of all PCs\n"
            "**`.publicmap`** ─ Map of public channels only\n"
            "**`.privatemap`** ─ Map of private channels only\n"
            "**`.estatehelp`** ─ Estate map functions help\n"
            "**`.estate init #ch`** ─ Init/update estate map"
        ), inline=False)
        embedhan.set_footer(text="Village Game • All listed commands need the prefix `.` to work")
        await self.send_help_page(ctx, embedhan, self.help_handling)

    async def help_infos(self, ctx):
        embedinf = discord.Embed(title="📜 - Infos", description="4 commands", color=0xff3fb9)
        embedinf.add_field(name="Commands", value=(
            "**`.info #ch`** ─ Show channel info\n"
            "**`.info add #ch <text>`** ─ Add info to a channel\n"
            "**`.info remove #ch <n>`** ─ Remove info by number\n"
            "**`.info reset`** ─ Reset all infos"
        ), inline=False)
        embedinf.set_footer(text="Village Game • All listed commands need the prefix `.` to work")
        await self.send_help_page(ctx, embedinf, self.help_infos)

    async def help_presets(self, ctx):
        embedpres = discord.Embed(title="🎟️ - Presets", description="3 commands", color=0xff3fb9)
        embedpres.add_field(name="Player Commands", value=(
            "**`.preset`** ─ Add/remove/edit presets with optional ability category\n"
            "  Categories: Lethal, Curing, Manipulation (Control, Redirect), Manipulation (Other), Blocking, Transportation and Comms, Information, Other"
        ), inline=False)
        embedpres.add_field(name="Admin Commands", value=(
            "**`.ospreset`** ─ View/reorder/remove all presets\n"
            "**`.ospresetsort`** ─ Reorder preset display categories"
        ), inline=False)
        embedpres.set_footer(text="Village Game • All listed commands need the prefix `.` to work")
        await self.send_help_page(ctx, embedpres, self.help_presets)

    async def help_voting(self, ctx):
        embedv = discord.Embed(title="🗳️ - Voting commands", description="9 commands", color=0xff3fb9)
        embedv.add_field(name="Voting", value=(
            "**`.vote @player`** ─ Vote or change your vote\n"
            "**`.abstain`** ─ Abstain from voting\n"
            "**`.manipulate @target @vote`** ─ Manipulate a player's vote\n"
            "**`.removevote @player`** ─ Remove a player's vote\n"
            "**`.skipnight <min_votes>`** ─ Start skip-night vote\n"
            "━━━━━━━━━━━━━━━━\n"
            "**`.votelist`** ─ Show all current votes\n"
            "**`.resetvotes`** ─ Reset all votes\n"
            "**`.votehistory/vh [mode]`** ─ Scan vote history\n"
            "  ─ `grouped` ─ Group by target\n"
            "  ─ `range` ─ Reply to end message or send ID/link"
        ), inline=False)
        embedv.add_field(name="Voting in RCs", value=(
            "**`.voteinrc true/false`** ─ Enable voting in RoleChats\n\n"
            "When enabled, players vote in their RC. Append the session channel "
            "(e.g. `#lynch-session-1`) to specify vote type; defaults to "
            "#lynch-session-1 if omitted."
        ), inline=False)
        embedv.set_footer(text="Village Game • All listed commands need the prefix `.` to work")
        await self.send_help_page(ctx, embedv, self.help_voting)

    async def help_nominations(self, ctx):
        embedn = discord.Embed(title="👉 - Nominations commands", description="10 commands", color=0xff3fb9)
        embedn.add_field(name="Setup", value=(
            "Create a nominations category, then:\n"
            "**`.categoryset Nominations <name>`** ─ Register the category"
        ), inline=False)
        embedn.add_field(name="Player Commands", value=(
            "**`.accuse @player #RC`** ─ Accuse (costs 2 tokens, creates channel)\n"
            "**`.intervene #nom-ch`** ─ Pay 1 token to speak in nomination\n"
            "**`.voten #nom-ch yes/no`** ─ Vote guilty or not guilty\n"
            "**`.tokens`** ─ Check your token balance"
        ), inline=False)
        embedn.add_field(name="Admin Commands", value=(
            "**`.addtokens @user <qty>`** ─ Add tokens\n"
            "**`.removetokens @user <qty>`** ─ Remove tokens\n"
            "**`.showvotesn #nom-ch`** ─ View nomination votes\n"
            "**`.stopvotes #nom-ch`** ─ Stop nomination (locks channel)\n"
            "**`.resumevotes #nom-ch`** ─ Resume nomination\n"
            "**`.clearvotes`** ─ Clear all nomination votes"
        ), inline=False)
        embedn.set_footer(text="Village Game • All listed commands need the prefix `.` to work")
        await self.send_help_page(ctx, embedn, self.help_nominations)

    async def help_lists(self, ctx):
        embedu = discord.Embed(title="📄 - Lists", description="9 commands", color=0xff3fb9)
        embedu.add_field(name="Player Lists", value=(
            "**`.playerlist`** ─ List alive members\n"
            "**`.sponsorlist`** ─ List sponsor members\n"
            "**`.houselist`** ─ List visitable houses\n"
            "**`.deadlist`** ─ List dead players and their roles"
        ), inline=False)
        embedu.add_field(name="Admin Commands", value=(
            "**`.setuphouselist`** ─ Init houselist from existing houses\n"
            "**`.houselistadd #house`** ─ Add a house to the list\n"
            "**`.houselistremove #house`** ─ Remove a house from list\n"
            "━━━━━━━━━━━━━━━━\n"
            "**`.deadlist add @player <team> <role>`** ─ Add to deadlist\n"
            "**`.deadlist remove @player`** ─ Remove from deadlist"
        ), inline=False)
        embedu.set_footer(text="Village Game • All listed commands need the prefix `.` to work")
        await self.send_help_page(ctx, embedu, self.help_lists)

    async def help_sendrole(self, ctx):
        embedsendrole = discord.Embed(title="↪ - Send Role", description="3 commands", color=0xff3fb9)
        embedsendrole.add_field(name="Send Role", value=(
            "**`.settarget <channel_id>`** ─ Set target channel (ID, not mention)\n"
            "**`.sendrole/sr <players>`** ─ Reply to a msg, sends role to target\n"
            "  Optionally append player names: `Played by <players>`"
        ), inline=False)
        embedsendrole.add_field(name="Team Roll", value=(
            "**`.teamroll <n1> \"msg1\" <n2> \"msg2\" ...`** ─ (Admin)\n"
            "Randomly assigns quoted roles to `n` RC channels. "
            "Missing channels auto-created (max 50).\n"
            "Example: `.teamroll 3 \"Evil team\" 3 \"Village team\"`"
        ), inline=False)
        embedsendrole.set_footer(text="Village Game • All listed commands need the prefix `.` to work")
        await self.send_help_page(ctx, embedsendrole, self.help_sendrole)

    async def help_utility(self, ctx):
        embedu = discord.Embed(title="⚙️ - Utility", description="28 commands", color=0xff3fb9)
        embedu.add_field(name="General", value=(
            "**`.day`** ─ Unlock all day channels\n"
            "**`.night`** ─ Lock all day channels\n"
            "**`.broom`** ─ Delete replied-to messages (logs kept)\n"
            "**`.log`** ─ Log message range (count/source/send)\n"
            "**`.housecheck [hours]`** ─ List quiet houses\n"
            "━━━━━━━━━━━━━━━━\n"
            "**`.whisper #RC <msg>`** ─ Send anonymous whisper\n"
            "**`.switch`** ─ Toggle Player/Sponsor role"
        ), inline=False)
        embedu.add_field(name="Player Status", value=(
            "**`.dead`** ─ Move RC to Dead category\n"
            "**`.deadrole`** ─ Mark dead, remove house, pin corpse\n"
            "**`.deadc`** ─ Move RC to Dead (admin)"
        ), inline=False)
        embedu.add_field(name="Admin — Roles & Perms", value=(
            "**`.addrole @role @users...`** ─ Give role to members\n"
            "**`.removerole <role> <member>`** ─ Remove role (admin)\n"
            "━━━━━━━━━━━━━━━━\n"
            "**`.addcategoryperms @role <cat> <perm>`** ─ R=Read, S=Send\n"
            "**`.addchannelperms @role #ch <perm>`** ─ R=Read, S=Send"
        ), inline=False)
        embedu.add_field(name="Admin — Game & Tracking", value=(
            "**`.endgame`** ─ Unlock all channels post-game\n"
            "**`.statss`** ─ Message counts by role priority\n"
            "━━━━━━━━━━━━━━━━\n"
            "**`.setmessagetracking`** ─ Enable/disable tracking\n"
            "**`.start_tracking`** ─ Start message tracking\n"
            "**`.stop_tracking`** ─ Stop/pause tracking\n"
            "**`.reset_tracking`** ─ Reset message counts"
        ), inline=False)
        embedu.add_field(name="Auto-Visit", value=(
            "**`.autovisits`** ─ Toggle auto-visit system\n"
            "**`.autorcset`** ─ Set RC for auto-visit\n"
            "**`.autorcadd @user`** ─ Add user to auto-visit\n"
            "**`.autorcreset`** ─ Reset all auto-visit configs\n"
            "**`.autoknock`** ─ Toggle auto-knock\n"
            "**`.automove`** ─ Toggle auto-move\n"
            "**`.autostealth`** ─ Toggle stealth mode for auto-visits"
        ), inline=False)
        embedu.set_footer(text="Village Game • All listed commands need the prefix `.` to work")
        await self.send_help_page(ctx, embedu, self.help_utility)

    async def help_other(self, ctx):
        embedo = discord.Embed(title="👽 - Other", description="22 commands", color=0xff3fb9)
        embedo.add_field(name="General", value=(
            "**`.help`** ─ Show this menu\n"
            "**`.who #ch`** ─ List players in a channel\n"
            "**`.where #RC`** ─ Show a player's current location\n"
            "**`.map`** ─ Show the game map\n"
            "**`.role`/`.firstpinned`** ─ Show first pinned in RC\n"
            "**`.roll @role <n>`** ─ Random players from a role\n"
            "━━━━━━━━━━━━━━━━\n"
            "**`.ping`** ─ Bot online check\n"
            "**`.ding`** ─ Dong!"
        ), inline=False)
        embedo.add_field(name="Narration", value=(
            "**`.narrate #ch <msg>`** ─ Send narration to channels\n"
            "**`.narration`/`.n <text>`** ─ Storybook embed (admin, pings)\n"
            "**`.anarration`/`.na <text>`** ─ Silent narration (admin)\n"
            "**`.narrationcolor`** ─ Pick embed color (admin)"
        ), inline=False)
        embedo.add_field(name="Fun & Utilities", value=(
            "**`.dice <n>`** ─ Roll 1–N\n"
            "**`.dice <opt1> <opt2> ...`** ─ Random pick\n"
            "**`.loc`** ─ Show all houses and occupants\n"
            "**`.gettag <link>`** ─ Get mentioned users from a message\n"
            "**`.timer <time> [tag] [#ch]`** ─ Set a timer (1h2m10s)\n"
            "━━━━━━━━━━━━━━━━\n"
            "**`.deletechannel`** ─ Delete this channel (admin)\n"
            "**`.deletecategory`** ─ Delete this category (admin)\n"
            "**`.timestamp <DD-MM> <HH:MM>`** ─ Gen timestamp with timezone picker\n"
            "**`.time`** ─ Get sent time of replied-to message\n"
            "**`.dropitem`** ─ Drop interactive item (see docs)\n"
            "**`.revive`** ─ Revive dead players (admin)"
        ), inline=False)
        embedo.set_footer(text="Village Game • All listed commands need the prefix `.` to work")
        await self.send_help_page(ctx, embedo, self.help_other)

    async def help_meetupmatrix(self, ctx):
        embedm = discord.Embed(title="📊 - Meetings & Meetup Matrix", description="21 commands", color=0xff3fb9)
        embedm.add_field(name="Meetup Matrix", value=(
            "**`.setupmeetupmatrix`** ─ Toggle automated meetup tracking\n"
            "**`.setphase day/night`** ─ Trigger phase change (admin)\n"
            "**`.forcemeet @p1 @p2`** ─ Force a meetup record (admin)\n"
            "━━━━━━━━━━━━━━━━\n"
            "**`.allmeets @player`** ─ Show who they've met this phase\n"
            "**`.meetupmatrix`** ─ Show full meetup matrix"
        ), inline=False)
        embedm.add_field(name="Meeting — Player", value=(
            "**`.meeting`** ─ Request a meeting (max 5 players)\n"
            "**`.endmeeting`** ─ End your active meeting\n"
            "**`.checkcooldown [@user]`** ─ Check meeting cooldown"
        ), inline=False)
        embedm.add_field(name="Meeting — Admin", value=(
            "**`.meetingenable`** ─ Enable/disable the meeting system\n"
            "**`.setmeetingchannel #ch`** ─ Set request channel\n"
            "**`.setmeetingtargetguild <id>`** ─ Set meeting server\n"
            "**`.setmeetingcategory <cat>`** ─ Set meeting category\n"
            "**`.meetingconfig`** ─ Show current config\n"
            "━━━━━━━━━━━━━━━━\n"
            "**`.blockmeeting @user`** ─ Block user from meetings\n"
            "**`.unblockmeeting @user`** ─ Unblock user\n"
            "**`.removecooldown @user`** ─ Remove cooldown\n"
            "**`.forcemeeting @u1 @u2 ...`** ─ Create forced meeting\n"
            "**`.listblocked`** ─ List blocked users\n"
            "**`.listcooldowns`** ─ List users on cooldown\n"
            "**`.cancelmeeting`** ─ Cancel pending meeting\n"
            "**`.meetingstats`** ─ Show meeting statistics"
        ), inline=False)
        embedm.set_footer(text="Village Game • All listed commands need the prefix `.` to work")
        await self.send_help_page(ctx, embedm, self.help_meetupmatrix)

    async def help_economy(self, ctx):
        embede = discord.Embed(title="💰 - Economy commands", description="18 commands", color=0xff3fb9)
        embede.add_field(name="Player Commands", value=(
            "**`.bal`/`.balance`** ─ Show RC balance\n"
            "**`.shop`** ─ View shop with interactive buttons\n"
            "**`.buy <item> [qty]`** ─ Buy from shop (to RC inventory)\n"
            "**`.sell`/`.sell-item <item>`** ─ Sell for 50% refund\n"
            "**`.inv`/`.inventory [#ch]`** ─ View RC inventory\n"
            "**`.give @user <amt>`** ─ Give RC coins (in houses)\n"
            "**`.give-money @user <amt>`** ─ Transfer from wallet\n"
            "**`.use <item>`** ─ Use an item from inventory"
        ), inline=False)
        embede.add_field(name="Admin Commands", value=(
            "**`.additem <price> <name>`** ─ Add new shop item\n"
            "**`.removeitem`/`.rmitem #ch <item> [qty]`** ─ Remove from RC\n"
            "**`.edititem <field> <name> <val>`** ─ Edit shop item\n"
            "**`.delitem <name>`** ─ Delete item from shop\n"
            "━━━━━━━━━━━━━━━━\n"
            "**`.addmoney #ch <amt>`** ─ Add coins to RC\n"
            "**`.removemoney #ch <amt>`** ─ Remove coins from RC\n"
            "**`.add-money-role @role <amt>`** ─ Add wallet coins by role\n"
            "**`.additemrole @role <item> <qty>`** ─ Give items by role\n"
            "━━━━━━━━━━━━━━━━\n"
            "**`.reseteconomy [amt]`** ─ Reset all balances\n"
            "**`.clearinventory`** ─ Clear all inventories\n"
            "**`.collect`** ─ Add collect amt to every RC\n"
            "**`.setcollect <val>`** ─ Set collect amount (max 10k)\n"
            "**`.leaderboard`/`.lb`/`.top [n]`** ─ Richiest RCs"
        ), inline=False)
        embede.add_field(name="Shop Items", value=(
            "🎆 **Fireworks** ─ Reveal your position in announcements\n"
            "👟 **Shoes** ─ Extra visit grant\n"
            "✉ **Whisper** ─ Send anonymous private message\n"
            "🧹 **Broom** ─ Clear recent messages in a channel\n"
            "📜 **Will** ─ Notify OS to pin your last will\n"
            "🔭 **Peep Hole** ─ See who knocks on your target house"
        ), inline=False)
        embede.set_footer(text="Village Game • All listed commands need the prefix `.` to work")
        await self.send_help_page(ctx, embede, self.help_economy)

    async def help_location(self, ctx):
        embed = discord.Embed(title="📍 Location commands", description="18 commands", color=0xff3fb9)
        embed.add_field(name="User Commands", value=(
            "**`.mysetloc <location>`** ─ Set your location\n"
            "**`.myremoveloc`** ─ Remove your location\n"
            "**`.localtime`/`.lt [@user]`** ─ View local time\n"
            "**`.near [@user]`** ─ Find 5 closest members\n"
            "**`.locations`** ─ Browse all locations by continent\n"
            "**`.locstats`** ─ Location statistics\n"
            "**`.lochelp`/`.hloc`** ─ Detailed location help\n"
            "**`.whentime @u1 @u2 ...`** ─ See time for multiple users"
        ), inline=False)
        embed.add_field(name="Admin Commands", value=(
            "**`.setloc @user <location>`** ─ Set a user's location\n"
            "**`.remloc @user`** ─ Remove a user's location\n"
            "**`.setcontinent @user <cont>`** ─ Assign continent\n"
            "**`.listunknown`** ─ List users with unknown continent\n"
            "**`.refreshtz`** ─ Refresh all timezones\n"
            "**`.forceremloc`/`.forceremoveloc <name/id>`** ─ Force remove\n"
            "**`.test_geocoder`** ─ Test geocoder connectivity"
        ), inline=False)
        embed.add_field(name="Maps", value=(
            "**`.mapp`** ─ World map of registered users\n"
            "**`.mapheat`** ─ Heatmap of registered users\n"
            "**`.locsnotset`** ─ Members who haven't set location"
        ), inline=False)
        embed.set_footer(text="Village Game • All listed commands need the prefix `.` to work")
        await self.send_help_page(ctx, embed, self.help_location)

    async def help_dashboard(self, ctx):
        embed = discord.Embed(title="🎮 Dashboard & OS Info commands", description="17 commands", color=0xff3fb9)
        embed.add_field(name="Dashboard", value=(
            "**`.dashboard`** ─ Open the role dashboard\n"
            "**`.dashboardtoggle`** ─ Enable/disable dashboard\n"
            "**`.setrole @role`** ─ Set dashboard role\n"
            "━━━━━━━━━━━━━━━━\n"
            "**`.addpassiveability <name> <desc>`** ─ Add passive ability\n"
            "**`.removepassiveability <name>`** ─ Remove passive\n"
            "**`.addactiveability <name> <desc> <uses>`** ─ Add active ability\n"
            "**`.removeactiveability <name>`** ─ Remove active\n"
            "━━━━━━━━━━━━━━━━\n"
            "**`.vb`** ─ View your vote balance\n"
            "**`.checkvb [@user]`** ─ Check vote balance\n"
            "**`.setvisits @user <amt>`** ─ Set visit count\n"
            "**`.addvisits @user <amt>`** ─ Add visits\n"
            "**`.removevisits @user <amt>`** ─ Remove visits\n"
            "**`.actionlog [@user]`** ─ View action log"
        ), inline=False)
        embed.add_field(name="OS Info", value=(
            "**`.setboard`** ─ Set up the OS info board\n"
            "**`.setinfophase <phase>`** ─ Set current phase info\n"
            "**`.addcard`** ─ Add an info card\n"
            "**`.refreshcards`** ─ Refresh all info cards"
        ), inline=False)
        embed.set_footer(text="Village Game • All listed commands need the prefix `.` to work")
        await self.send_help_page(ctx, embed, self.help_dashboard)

    async def help_gamemanager(self, ctx):
        embed = discord.Embed(title="🎲 Game Manager commands", description="4 commands", color=0xff3fb9)
        embed.add_field(name="Commands", value=(
            "**`.startgame`/`.sg <slots> @host <name>`** ─ Start a lobby\n"
            "**`.addplayer`/`.ap <slot> @player [name]`** ─ Fill a slot\n"
            "**`.removeplayer`/`.rp <slot> [name]`** ─ Remove from slot\n"
            "**`.closegame`/`.cg [name]`** ─ Close & archive game"
        ), inline=False)
        embed.set_footer(text="Village Game • All listed commands need the prefix `.` to work")
        await self.send_help_page(ctx, embed, self.help_gamemanager)

    async def help_library(self, ctx):
        embed = discord.Embed(title="📚 Library & Stats commands", description="19 commands", color=0xff3fb9)
        embed.add_field(name="Stats", value=(
            "**`.stats [@player]`** ─ View player statistics\n"
            "**`.winrate`** ─ Winrate stats by team\n"
            "**`.relations [@user]`** ─ Allies and nemeses"
        ), inline=False)
        embed.add_field(name="Library — Browse & Manage", value=(
            "**`.lib`** ─ Browse the game library\n"
            "**`.lib add`** ─ Add a new game\n"
            "**`.lib summary`** ─ Summary of all games\n"
            "**`.lib edit <#> <field> <val>`** ─ Edit a game field\n"
            "**`.lib delete <#>`** ─ Delete a game\n"
            "**`.lib deletegame <#>`** ─ Delete a game\n"
            "**`.lib setwin <#> <team>`** ─ Set winning team\n"
            "**`.lib search <term>`** ─ Search by name or player\n"
            "**`.lib idsearch <id>`** ─ Search by game ID"
        ), inline=False)
        embed.add_field(name="Library — Account & Help", value=(
            "**`.lib migrateaccount`** ─ Move stats to new account\n"
            "**`.lib mergeaccount`** ─ Merge two accounts' stats\n"
            "**`.lib syncname`** ─ Sync display name\n"
            "**`.lib bulksyncnames`** ─ Bulk sync all names\n"
            "**`.lib help`** ─ Show library help\n"
            "**`.libit help`** ─ Italian library help\n"
            "**`.missingids`** ─ Games with missing player IDs"
        ), inline=False)
        embed.set_footer(text="Village Game • All listed commands need the prefix `.` to work")
        await self.send_help_page(ctx, embed, self.help_library)

    async def help_games(self, ctx):
        embed = discord.Embed(title="⚔️ Games (Aux Battle & Senet)", description="18 commands", color=0xff3fb9)
        embed.add_field(name="🎯 Aux Battle", value=(
            "**`.auxbattle`/`.aux`** ─ Main command (subcommands below)\n"
            "━━━━━━━━━━━━━━━━\n"
            "**`.auxbattle signup`** ─ Sign up\n"
            "**`.auxbattle opensignup`** ─ Open signups (admin)\n"
            "**`.auxbattle closesignup`** ─ Close signups (admin)\n"
            "**`.auxbattle bracket`** ─ View bracket\n"
            "**`.auxbattle reset`** ─ Reset tournament (admin)\n"
            "**`.auxbattle start`** ─ Start tournament (admin)\n"
            "**`.auxbattle submit`** ─ Submit battle entry"
        ), inline=False)
        embed.add_field(name="🎲 Senet", value=(
            "**`.senet help`** ─ Show rules\n"
            "**`.senet challenge`/`sfida @user`** ─ Challenge someone\n"
            "**`.senet accept`/`accetta @user`** ─ Accept a challenge\n"
            "━━━━━━━━━━━━━━━━\n"
            "**`.senet roll`/`lancia`** ─ Roll the dice\n"
            "**`.senet move`/`muovi <piece>`** ─ Move a piece\n"
            "**`.senet skip`/`passo`** ─ Skip your turn\n"
            "**`.senet status`/`board`** ─ View the board\n"
            "**`.senet forfeit`/`abbandona`** ─ Forfeit the game\n"
            "**`.senet rules`/`regole`** ─ Show the rules"
        ), inline=False)
        embed.set_footer(text="Village Game • All listed commands need the prefix `.` to work")
        await self.send_help_page(ctx, embed, self.help_games)

    async def help_birthdays(self, ctx):
        embed = discord.Embed(title="🎂 Birthday commands", description="6 commands", color=0xff3fb9)
        embed.add_field(name="Player Commands", value=(
            "**`.birthdays`** ─ List all registered birthdays\n"
            "**`.nextbirthdays`** ─ Upcoming birthdays\n"
            "**`.helpbday`** ─ Birthday help"
        ), inline=False)
        embed.add_field(name="Admin Commands", value=(
            "**`.birthday add @user MM-DD`** ─ Add/set a birthday for a user\n"
            "**`.birthday remove @user`** ─ Remove a user's birthday\n"
            "**`.bdaystatus`** ─ Check birthday loop status\n"
            "**`.testbday @user`** ─ Test birthday announcement"
        ), inline=False)
        embed.set_footer(text="Village Game • All listed commands need the prefix `.` to work")
        await self.send_help_page(ctx, embed, self.help_birthdays)

    async def help_calendar(self, ctx):
        embed = discord.Embed(title="📅 Calendar & Intro commands", description="4 commands", color=0xff3fb9)
        embed.add_field(name="Commands", value=(
            "**`.calendar`** ─ English Village Games schedule\n"
            "**`.calendario`** ─ Italian Village Games schedule\n"
            "**`.vgintro`/`.vgi`** ─ Village Games intro (EN)\n"
            "**`.vgintro_it`/`.vgii`** ─ Village Games intro (IT)"
        ), inline=False)
        embed.set_footer(text="Village Game • All listed commands need the prefix `.` to work")
        await self.send_help_page(ctx, embed, self.help_calendar)

    async def help_draft(self, ctx):
        embed = discord.Embed(title="🏆 Draft commands", description="21 commands", color=0xff3fb9)
        embed.add_field(name="Draft Commands", value=(
            "**.draftstart @u1 @u2 ...** ─ Start a snake draft (admin)\n"
            "**.prepick** ─ Manage your prepicks (max 2)\n"
            "**.draftboard** ─ Show all teams\n"
            "**.myteam** ─ Show your team\n"
            "**.team @user** ─ Show a user's team with fantasy points\n"
            "**.forcepick <name>** ─ Force a pick for the current user (admin)\n"
            "**.undo** ─ Undo the most recent pick (admin)\n"
            "**.pause** ─ Pause the draft (admin)\n"
            "**.resume** ─ Resume the draft (admin)\n"
            "**.enddraft** ─ End the draft (admin)"
        ), inline=False)
        embed.add_field(name="Points Commands", value=(
            "**.draftpoints** ─ Live fantasy points leaderboard for all teams\n"
            "**.standings** ─ Standings with avg & best points\n"
            "**.player <name>** / **.pp** ─ Look up a player's FIFA fantasy points\n"
            "**.playerpoints <name>** ─ Same as .player with more detail\n"
            "**.scoutingboard** ─ Scouting bonus leaderboard (ownership % at scoring time)\n"
            "**.topplayers [N]** ─ Top N drafted players by points (default 10)\n"
            "**.teamvalue @user** ─ Point breakdown per player on a team\n"
            "**.refreshpoints** ─ Fetch fresh FIFA data & save to cache (admin)"
        ), inline=False)
        embed.add_field(name="Match Analytics", value=(
            "**.matches [filter]** / **.matchinfo** ─ Group standings & tiebreakers via dropdown, or filter by team\n"
            "**.trending [position]** / **.form** ─ Players with best form rating\n"
            "**.differentials [N]** / **.diff** ─ Best differential picks (high pts, low ownership)"
        ), inline=False)
        embed.add_field(name="Simulation — Tournament", value=(
            "**.simulate** / **.sim** / **.fsim** [version] [mode] [debug]\n"
            "  Versions: **v1** (ELO), **v2** (players), **v3** (dynamic), **v4** (tactical), **v5** (match state)\n"
            "  Modes: **fast** (default), **animated** (goal-by-goal)\n"
            "  Flags: **debug** (V4/V5 tactical breakdown)\n"
            "  `Ex: .fsim v5` — comprehensive output with V1-V5 insights\n"
            "  `Ex: .fsim v5 animated`"
        ), inline=False)
        embed.add_field(name="Simulation — Head-to-Head", value=(
            "**.fsim detailed** <version> <Team A> <Team B> [knockout] [N]\n"
            "  Monte Carlo analysis between two specific teams.\n"
            "  N = simulations (default 100).\n"
            "  `Ex: .fsim detailed v4 France Spain`\n"
            "  `Ex: .fsim detailed v4 France Spain knockout 10000`"
        ), inline=False)
        embed.add_field(name="Simulation — Help & Reference", value=(
            "**.simhelp** / **.sim help** — Full V1-V5 model descriptions\n"
            "**.simulate v1** — Historical ELO/PELE ratings\n"
            "**.simulate v2** — FC26 player attributes + formations\n"
            "**.simulate v3** — Chemistry, form, momentum, leadership\n"
            "**.simulate v4** — Tactics, managers, styles, contexts\n"
            "**.simulate v5** — Comprehensive: V1 Elo + V2 squads + V3 dynamics + V4 tactics + V5 match state"
        ), inline=False)
        embed.set_footer(text="Village Game • All listed commands need the prefix `.` to work")
        await self.send_help_page(ctx, embed, self.help_draft)

    async def help_botc(self, ctx):
        try:
            from BOTC.cogs.help import _build_help_embed
            embed = _build_help_embed()
        except ImportError:
            embed = discord.Embed(title="🐦 Blood on the Clocktower", color=0x008080)
            embed.description = "See `.botchelp` for all BOTC commands."
        await self.send_help_page(ctx, embed, self.help_botc)


class NarrationColorView(discord.ui.View):
    COLOR_OPTIONS = [
        ("Crimson", 0xDC143C),
        ("Dark Red", 0x8B0000),
        ("Orange", 0xFF8C00),
        ("Gold", 0xDAA520),
        ("Forest Green", 0x228B22),
        ("Teal", 0x008080),
        ("Steel Blue", 0x4682B4),
        ("Royal Blue", 0x4169E1),
        ("Purple", 0x800080),
        ("Magenta", 0xC71585),
    ]

    def __init__(self, ctx: commands.Context):
        super().__init__(timeout=60)
        self.ctx = ctx
        for i, (name, val) in enumerate(self.COLOR_OPTIONS):
            btn = Button(label=name, style=discord.ButtonStyle.primary, row=i // 5)
            btn.callback = self._make_pick_callback(val)
            self.add_item(btn)

    def _make_pick_callback(self, color: int):
        async def callback(interaction: discord.Interaction):
            await self._on_pick(interaction, color)
        return callback

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.ctx.author.id:
            await interaction.response.send_message("This isn't for you.", ephemeral=True)
            return False
        return True

    async def _on_pick(self, interaction: discord.Interaction, color: int):
        self.stop()
        guild_data = load_guild_data(self.ctx.guild.id)
        if guild_data:
            guild_data["narration_color"] = color
            save_guild_data(self.ctx.guild.id, guild_data)
        embed = discord.Embed(
            description=f"Narration color set to **#{color:06X}**",
            color=color,
        )
        await interaction.response.edit_message(embed=embed, view=None)

    async def on_timeout(self):
        for child in self.children:
            child.disabled = True
        try:
            await self.message.edit(content="Colour picker timed out.", embed=None, view=None)
        except Exception:
            pass


class ReviveView(discord.ui.View):
    def __init__(self, ctx, guild_data, dead_members):
        super().__init__(timeout=120)
        self.ctx = ctx
        self.guild_data = guild_data
        self.dead_members = dead_members
        self.selected_players = []
        self.alive_player = None
        self.house_choice = None
        self.house_channel = None
        self.message = None
        self._build_stage1()

    def _build_stage1(self):
        self.clear_items()
        options = [discord.SelectOption(label=m.display_name, value=str(m.id)) for m in self.dead_members]
        select = discord.ui.Select(placeholder="Select players to revive...", min_values=1, max_values=len(options), options=options)
        select.callback = self._on_stage1
        self.add_item(select)

    async def _on_stage1(self, interaction):
        if interaction.user.id != self.ctx.author.id:
            return await interaction.response.send_message("This isn't for you.", ephemeral=True)
        self.selected_players = [self.ctx.guild.get_member(int(v)) for v in interaction.data["values"]]
        self.selected_players = [m for m in self.selected_players if m]
        if not self.selected_players:
            return await interaction.response.send_message("Select at least one player.", ephemeral=True)
        self._build_stage2()
        embed = discord.Embed(
            description=f"**{len(self.selected_players)} players selected.**\nNow pick who gets the **Alive** role:",
            color=0x00DAE9
        )
        await interaction.response.edit_message(embed=embed, view=self)

    def _build_stage2(self):
        self.clear_items()
        options = [discord.SelectOption(label=m.display_name, value=str(m.id)) for m in self.selected_players]
        select = discord.ui.Select(placeholder="Pick the Alive player...", min_values=1, max_values=1, options=options)
        select.callback = self._on_stage2
        self.add_item(select)

    async def _on_stage2(self, interaction):
        if interaction.user.id != self.ctx.author.id:
            return await interaction.response.send_message("This isn't for you.", ephemeral=True)
        member_id = int(interaction.data["values"][0])
        self.alive_player = self.ctx.guild.get_member(member_id)
        if not self.alive_player:
            return await interaction.response.send_message("Player not found.", ephemeral=True)
        self._build_stage3()
        embed = discord.Embed(
            description=f"**{self.alive_player.display_name}** will be revived as **Alive**.\n"
                        f"{len(self.selected_players) - 1} other(s) will become **Sponsor**.\n\nNow choose the house:",
            color=0xDC143C
        )
        await interaction.response.edit_message(embed=embed, view=self)

    def _build_stage3(self):
        self.clear_items()
        options = [
            discord.SelectOption(label="Restore previous house", value="restore", description="Use the house they lived in before death"),
            discord.SelectOption(label="Assign random house", value="random", description="Pick a random available house"),
            discord.SelectOption(label="Let me specify", value="specify", description="I'll type the channel"),
        ]
        select = discord.ui.Select(placeholder="Choose house assignment...", min_values=1, max_values=1, options=options)
        select.callback = self._on_stage3
        self.add_item(select)

    async def _on_stage3(self, interaction):
        if interaction.user.id != self.ctx.author.id:
            return await interaction.response.send_message("This isn't for you.", ephemeral=True)
        self.house_choice = interaction.data["values"][0]

        if self.house_choice == "specify":
            await interaction.response.edit_message(content="Mention the house channel now (e.g. #house-1):", embed=None, view=None)
            def check(m):
                return m.author == self.ctx.author and m.channel == self.ctx.channel and m.mentions
            try:
                reply = await self.ctx.bot.wait_for("message", timeout=60, check=check)
                self.house_channel = reply.mentions[0]
                await reply.delete()
            except asyncio.TimeoutError:
                await self.ctx.send("Timed out. Revive cancelled.")
                return
            await self._execute()
            return

        if self.house_choice == "restore":
            stored = self.guild_data.get("current_houses", {}).get(str(self.alive_player.id), [])
            if stored:
                ch = self.ctx.guild.get_channel(stored[0])
                if ch and ch.category and ch.category.name == self.guild_data.get("houses_category_name"):
                    self.house_channel = ch

        if not self.house_channel:
            houselist = self.guild_data.get("houselist") or []
            if not isinstance(houselist, list):
                houselist = []
            houses_category = discord.utils.get(self.ctx.guild.categories, name=self.guild_data["houses_category_name"])
            if houses_category and houselist:
                occupied = set(self.guild_data.get("member_homes", {}).values())
                valid = [ch for ch in houses_category.channels if ch.name in houselist and ch.id not in occupied]
                if valid:
                    self.house_channel = random.choice(valid)

        await interaction.response.edit_message(view=None)
        await self._execute()

    async def _execute(self):
        guild = self.ctx.guild
        guild_data = self.guild_data
        alive_role = discord.utils.get(guild.roles, name=guild_data["alive_role_name"])
        sponsor_role = discord.utils.get(guild.roles, name=guild_data["sponsor_role_name"])
        dead_role = discord.utils.get(guild.roles, name=guild_data["dead_role_name"])
        rc_category = discord.utils.get(guild.categories, name=guild_data["rc_category_name"])
        dead_rc_category = discord.utils.get(guild.categories, name=guild_data["dead_rc_category_name"])

        sponsors = [m for m in self.selected_players if m.id != self.alive_player.id]

        for member in self.selected_players:
            if dead_role:
                await member.remove_roles(dead_role)

        if alive_role and self.alive_player:
            await self.alive_player.add_roles(alive_role)

        if sponsor_role:
            for sp in sponsors:
                await sp.add_roles(sponsor_role)

        if dead_rc_category and self.ctx.channel.category == dead_rc_category and rc_category:
            await self.ctx.channel.edit(category=rc_category)

        if self.house_channel:
            guild_data["member_homes"][str(self.alive_player.id)] = self.house_channel.id
            save_guild_data(guild.id, guild_data)

        embed = discord.Embed(
            title="Revival Complete",
            description=f"**Alive:** {self.alive_player.mention}\n"
                        f"**Sponsors:** {' '.join(s.mention for s in sponsors) if sponsors else 'None'}\n"
                        f"**House:** {self.house_channel.mention if self.house_channel else 'Not assigned'}",
            color=0x00DAE9
        )
        await self.ctx.send(embed=embed)
        self.stop()