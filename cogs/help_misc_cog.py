import os
import re
import html
import random
import difflib
import wcwidth
from utils.discord_safe import category_family, chunk_fields
import discord
import aiohttp
import asyncio
import datetime
from datetime import datetime
from discord.ext import commands
from discord import AllowedMentions
from discord.ui import Select, View, Button
from cogs.data_utils import load_guild_data, save_guild_data
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
from utils.paths import DATA_DIR


HELP_CATEGORIES = {
    "setup", "moving", "home", "handling", "infos", "presets", "voting",
    "nominations", "lists", "utility", "other", "botc", "surveillance",
    "analytics", "status", "economy", "meetupmatrix",
}
HELP2_CATEGORIES = {
    "location", "dashboard", "gamemanager", "library", "games", "auction",
    "birthdays", "calendar", "sticky", "sendrole",
}


def _chunk_lines(lines, cap=1024):
    """Group lines into field values of at most *cap* characters (long single lines are split)."""
    return chunk_fields(list(lines), cap)


def _embed_pages(title, footer_text, groups, color):
    pages = []
    fields = []
    total_len = 0

    def flush():
        nonlocal fields, total_len
        if not fields:
            return
        embed = discord.Embed(title=title, color=color, timestamp=datetime.now())
        embed.set_footer(text=footer_text)
        for name, value in fields:
            embed.add_field(name=name, value=value, inline=False)
        pages.append(embed)
        fields = []
        total_len = 0

    for label, lines in groups:
        for idx, value in enumerate(_chunk_lines(lines)):
            name = label if idx == 0 else f"{label.rstrip(':')} (part {idx + 1}):"
            field_len = len(name) + len(value) + 16
            if len(fields) >= 25 or total_len + field_len > 5500:
                flush()
            fields.append((name, value))
            total_len += field_len
    flush()
    return pages


MAX_EMBED_DESC = 4096
MAX_FIELD_NAME = 256
MAX_FIELD_VALUE = 1024
MAX_EMBED_CHARS = 6000


def _truncate(text, limit, marker="\n\n*… Output truncated. Use `.firstpin 1` to view a single message.*"):
    """Cut text to limit, preferring a clean break near the end so little room is wasted."""
    if len(text) <= limit:
        return text
    room = max(limit - len(marker), 0)
    cut = text[:room].rstrip()
    # Only accept a line/word break that sits near the end of the budget,
    # otherwise the embed would stop far short of the room it was given.
    threshold = room * 0.8
    boundary = cut.rfind("\n")
    if boundary < threshold:
        boundary = cut.rfind(" ")
    if boundary < threshold:
        boundary = room
    return cut[:boundary].rstrip() + marker


def _embed_chunks(embeds, max_embeds=10, max_chars=6000):
    """Group embeds into as few messages as Discord's per-message limits allow."""
    chunks = []
    current = []
    current_chars = 0
    for embed in embeds:
        size = len(embed)
        if current and (len(current) >= max_embeds or current_chars + size > max_chars):
            chunks.append(current)
            current = []
            current_chars = 0
        current.append(embed)
        current_chars += size
    if current:
        chunks.append(current)
    return chunks


INTERACTION_GIFS = {
    "poke": [
        "https://tenor.com/view/nekone-utawarerumono-poke-anime-gif-26470052",
        "https://tenor.com/view/poking-screen-poke-pokes-poking-poke-screen-gif-11084141349623928344",
        "https://tenor.com/view/poke-eyes-gif-12619607009147797210",
        "https://tenor.com/view/marin-kitagawa-kitagawa-giggle-love-anime-gif-16415664153773123078",
        "https://tenor.com/view/anime-poke-gif-8531096320778102788",
        "https://tenor.com/view/boop-anime-poke-mad-gif-16935420",
        "https://tenor.com/view/boop-poke-anime-cute-gif-16935454",
        "https://tenor.com/view/yonomori-kobeni-anime-girl-poke-cheek-kobeni-mikakunin-de-shinkoukei-gif-9593787201996879155",
        "https://tenor.com/view/boop-poke-gif-22382916",
        "https://tenor.com/view/highschool-dxd-anime-poke-pokeing-gif-23242564",
        "https://tenor.com/view/boop-rascal-does-not-dream-of-bunny-girl-senpai-anime-touch-nose-poke-gif-17682170",
        "https://tenor.com/view/point-anime-poke-gif-17113067",
        "https://tenor.com/view/poke-anime-gif-13062234263843120326",
        "https://tenor.com/view/my-deer-friend-nokotan-noko-gif-13644573839223951462",
        "https://tenor.com/view/poke-gif-19326797",
        "https://tenor.com/view/poke-the-bear-angry-gif-26844893",
        "https://tenor.com/view/tkthao219-bunny-rabbit-gif-22168506",
        "https://tenor.com/view/mochi-poke-poke-cute-cat-cat-cartoon-gif-310352913820334743",
        "https://tenor.com/view/poke-cute-sleepy-wake-up-hey-you-gif-14322931",
        "https://tenor.com/view/cute-annoying-poke-couple-bunny-gif-14647363090995704310",
    ],
    "pat": [
        "https://tenor.com/view/tsumiki-anime-waifu-miia-neko-gif-27055340",
        "https://tenor.com/view/pat-pat-anime-anime-pat-pat-cosmic-princess-kaguya-iroha-cutie-baby-gif-13718927594949096538",
        "https://tenor.com/view/kobayashi-dragon-maid-kanna-kamui-kanna-gif-4487183595152594707",
        "https://tenor.com/view/frieren-pat-frieren-pat-pat-frieren-pat-pat-gif-16450085803075970062",
        "https://tenor.com/view/pat-pat-gif-27638431",
        "https://tenor.com/view/headpat-comforting-gif-17155758397973400424",
        "https://tenor.com/view/shiro-anime-no-game-no-life-headpat-cute-gif-17317343567086759130",
        "https://tenor.com/view/anime-pat-gif-22001971",
        "https://tenor.com/view/pat-pat-pat-anime-girl-pat-anime-girl-gif-gif-9912105134255577569",
        "https://tenor.com/view/mai-sakurajima-sakuta-anime-pat-gif-22595893",
        "https://tenor.com/view/anime-pat-anime-gif-26506449",
        "https://tenor.com/view/headpats-anime-headpat-headpats-anime-chibi-gif-16550181993246603720",
        "https://tenor.com/view/clannad-anime-anime-girl-head-pat-good-girl-gif-9592662185233931869",
        "https://tenor.com/view/nekopara-vanilla-cat-girl-head-pat-gif-650742815674383074",
        "https://tenor.com/view/konohana-kitan-yuzu-headpat-anime-pat-gif-1995447864617839542",
        "https://tenor.com/view/patpat-gif-24636459",
        "https://tenor.com/view/thuongthuong-gif-1068228798904543626",
        "https://tenor.com/view/cat-pat-pat-gato-gatinho-kitty-gif-1043380680712787840",
        "https://tenor.com/view/pat-duck-cute-love-sparkle-gif-16328031",
        "https://tenor.com/view/sadness-sad-kitty-cat-pat-pat-meow-meow-gif-17938305558576565629",
    ],
    "hug": [
        "https://tenor.com/view/hug-anime-comfy-cute-gif-5299348585618231224",
        "https://tenor.com/view/anime-anime-hug-anime-boy-anime-girl-gif-7244423311549892217",
        "https://tenor.com/view/hug-love-anime-gif-8183148795245625994",
        "https://tenor.com/view/anime-hug-gif-14794426129399232107",
        "https://tenor.com/view/horimiya-hug-anime-miyamura-hori-gif-20848980",
        "https://tenor.com/view/hugtrip-gif-2490966530865073004",
        "https://tenor.com/view/hug-gif-26359154",
        "https://tenor.com/view/cuddle-bed-hug-bed-anime-anime-hug-gif-8314924890104257587",
        "https://tenor.com/view/hug-k-on-teto-sagrada-gif-14420937574950184822",
        "https://tenor.com/view/kanna-kamui-give-a-hug-gif-10775448422433807163",
        "https://tenor.com/view/hugs-gif-16204475217460758568",
        "https://tenor.com/view/hug-gif-4334405360982857072",
        "https://tenor.com/view/hugging-gif-6353720017538202613",
        "https://tenor.com/view/horimiya-hori-miyamura-gif-6944457256172224561",
        "https://tenor.com/view/oshi-no-ko-aqua-akane-hug-anime-hug-gif-8320852771448643180",
        "https://tenor.com/view/schitts-creek-david-rose-alexis-rose-hugs-hugging-gif-23706078",
        "https://tenor.com/view/cat-gif-6892218099699146160",
        "https://tenor.com/view/miss-you-gif-7307606366743938279",
        "https://tenor.com/view/tkthao219-bubududu-panda-gif-22343387",
        "https://tenor.com/view/couple-hugs-boy-hugging-girl-gif-13767421397200238709",
    ],
    "slap": [
        "https://tenor.com/view/anime-kaguya-sama-kaguya-shinomiya-slap-slapping-gif-8212906941276691404",
        "https://tenor.com/view/slap-slapping-yae-miko-chibi-yae-genshin-impact-gif-14573828462376627039",
        "https://tenor.com/view/girl-slap-anime-mad-student-gif-17423278",
        "https://tenor.com/view/anime-slap-mad-gif-16057834",
        "https://tenor.com/view/slap-handa-seishuu-naru-kotoishi-barakamon-anime-barakamon-gif-5509136",
        "https://tenor.com/view/no-angry-anime-slap-gif-7355956",
        "https://tenor.com/view/boy-slap-girl-anime-gif-6921254811684530096",
        "https://tenor.com/view/slap-jjk-nicevagg-anime-gif-22368283",
        "https://tenor.com/view/chikku-neesan-girl-hit-wall-stfu-anime-girl-smack-gif-17078255",
        "https://tenor.com/view/yuzuki-mizusaka-nonoka-komiya-celestial-method-sora-no-method-anime-slap-gif-26485601",
        "https://tenor.com/view/slap-slapping-call-of-the-night-yofukashi-no-uta-nazuna-nanakusa-gif-14212836341310937869",
        "https://tenor.com/view/anime-chika-fujiwara-slap-slapping-harisen-gif-18043240",
        "https://tenor.com/view/anime-toradora-ryuji-taiga-slap-gif-16919174636897443220",
        "https://tenor.com/view/slap-anime-girl-anime-gif-16992074182247359639",
        "https://tenor.com/view/anime-slap-gif-24278310",
        "https://tenor.com/view/slap-gif-26123394",
        "https://tenor.com/view/peach-goma-peach-and-goma-peach-peach-cat-slap-gif-26865200",
        "https://tenor.com/view/slap-slaps-enough-stop-stop-it-gif-13025908752997150429",
        "https://tenor.com/view/jagyasini-singh-do-you-need-vitamin-slap-slap-slapping-slap-meme-gif-8382734432187924811",
        "https://tenor.com/view/slap-face-gif-7991356173427238776",
    ],
    "kill": [
        "https://tenor.com/view/die-kill-kills-you-anime-gif-23910501",
        "https://tenor.com/view/yandere-tagged-knife-anime-gif-16524623",
        "https://tenor.com/view/falling-from-window-anime-death-dropkick-gif-18770900",
        "https://tenor.com/view/yumeko-mirai-nikki-anime-knife-gif-25152104",
        "https://tenor.com/view/2s-gif-23585902",
        "https://tenor.com/view/anime-gif-26383556",
        "https://tenor.com/view/yandere-bloopakill-knife-dangerous-gif-13390617426499031065",
        "https://tenor.com/view/katana-anime-8bit-gif-26096099",
        "https://tenor.com/view/chainsaw-evil-laugh-gif-26012440",
        "https://tenor.com/view/bleach-anime-ichigo-kick-fight-gif-18957478",
        "https://tenor.com/view/kill-gif-26478068",
        "https://tenor.com/view/esdeath-akame-ga-kill-gif-26225772",
        "https://tenor.com/view/akame-ga-kill-gif-26884269",
        "https://tenor.com/view/akame-pink-pfp-gif-8460099571599710431",
        "https://tenor.com/view/eucliwood-hellscythe-is-this-a-zombie-kore-wa-zombie-desuka-anime-anime-waifu-gif-24749636",
        "https://tenor.com/view/kill-gif-7836150005251650243",
        "https://tenor.com/view/rabbit-sticker-bunny-sticker-shooting-gun-shooting-gun-gif-26487737",
        "https://tenor.com/view/pengu-pudgy-penguin-pudgypenguins-knife-gif-2887622356907368259",
        "https://tenor.com/view/matmot-matmotgif-reaction-smile-cartoon-gif-6095664922065357452",
        "https://tenor.com/view/yungviral-gif-18033858609494320219",
    ],
    "kiss": [
        "https://tenor.com/view/kiss-gentle-kiss-anime-kiss-gentle-anime-kiss-gif-10550883246321102858",
        "https://tenor.com/view/kiss-gif-2768132236962548601",
        "https://tenor.com/view/kiss-anime-couple-kiss-anime-couple-anime-gif-14386257619920860170",
        "https://tenor.com/view/kiss-josee-anime-gif-26581761",
        "https://tenor.com/view/taiga-aisaka-ryuuji-takasu-aisaka-taiga-takasu-ryuuji-taiga-kiss-gif-14296171118038755935",
        "https://tenor.com/view/shirayuki-zen-kiss-anime-kiss-anime-couple-gif-gif-27520373",
        "https://tenor.com/view/anime-anime-kiss-love-gif-2187039208590998809",
        "https://tenor.com/view/anime-kiss-gif-14128267361195048504",
        "https://tenor.com/view/kiss-him-gif-6469108198636795149",
        "https://tenor.com/view/kiss-love-gif-16938490043241978829",
        "https://tenor.com/view/kissme-hon-anime-gif-16673710045813165646",
        "https://tenor.com/view/kiss-anime-anime-girl-blush-anime-girl-2-kissing-gif-11129237452451356840",
        "https://tenor.com/view/couple-kiss-passion-gif-14595913819685611037",
        "https://tenor.com/view/besos-gif-6180200097750952521",
        "https://tenor.com/view/kiss-lip-kiss-hug-kiss-kiss-kiss-sending-kisses-gif-3205895451106484105",
        "https://tenor.com/view/bear-blowakiss-love-hearts-kissing-gif-16158903236209431619",
        "https://tenor.com/view/cosytales-cute-kawaii-adorable-lovers-gif-11278828254163470784",
        "https://tenor.com/view/cheek-kiss-cheeks-kissing-cheek-kissing-love-gif-4259560615051180157",
        "https://tenor.com/view/cat-cute-sweet-gif-4736403030433414453",
        "https://tenor.com/view/dudu-bubu-dudu-kiss-bubu-crashing-to-the-walls-i-like-cute-couples-funny-gif-16407283704699471471",
    ],
    "dance": [
        "https://tenor.com/view/kakashi-dancing-naruto-anime-meme-gif-20691646",
        "https://tenor.com/view/happy-dance-dancing-anime-girl-gif-5699276185411794439",
        "https://tenor.com/view/anime-girl-dancing-hakari-dance-lonely-gif-13337816897041770339",
        "https://tenor.com/view/bocchi-the-rock-bocchi-bocchi-dance-anime-dance-anime-cute-dance-gif-8640564821222907754",
        "https://tenor.com/view/dance-gif-12046390263636064509",
        "https://tenor.com/view/evangelion-neon-genesis-evangelion-gif-1251291685974598497",
        "https://tenor.com/view/chainsaw-man-dance-chainsaw-man-anime-gif-26903148",
        "https://tenor.com/view/deal-with-it-trailblazer-honkai-star-rail-dancing-dance-gif-3020397715460894213",
        "https://tenor.com/view/cute-dance-gif-10310485452175495509",
        "https://tenor.com/view/happy-holidays-gif-2946506647643920769",
        "https://tenor.com/view/cool-verycute-cute-dancing-cyte-dancing-gif-18419613755250334503",
        "https://tenor.com/view/sparkle-lonely-lonely-dance-lonely-lonely-dance-chibi-gif-14506696327820781252",
        "https://tenor.com/view/sheen-gif-11503506469982527610",
        "https://tenor.com/view/good-night-gif-2030152775311029167",
        "https://tenor.com/view/marmot-ai-marmot-dance-animal-animal-dance-gif-17488437489161922450",
        "https://tenor.com/view/claire-dancing-baby-sunglasses-toddler-gif-16263996862542136105",
        "https://tenor.com/view/dance-desacatao-gif-4763670583671661800",
        "https://tenor.com/view/cowboy-dancing-kid-spagetti-legs-dance-gif-7038044923520317292",
        "https://tenor.com/view/silly-cat-kitten-gif-12239801577603428952",
        "https://tenor.com/view/shiba-dance-meme-dog-funny-gif-16363840026393230719",
    ],
    "wave": [
        "https://tenor.com/view/laid-back-camp-nadeshiko-kagamihara-wave-anime-gif-14395014036606108394",
        "https://tenor.com/view/anime-bye-bye-maki-wave-soredemo-ayumu-wa-yosetekuru-when-will-ayumu-make-his-move-gif-26195508",
        "https://tenor.com/view/anime-wave-hatsune-miku-gif-22384247",
        "https://tenor.com/view/fern-frieren-beyond-journey%27s-end-season-2-anime-girl-gif-13647920306909544011",
        "https://tenor.com/view/sailor-moon-rei-hino-sailor-mars-fast-hand-wave-anime-gif-1279063740737499555",
        "https://tenor.com/view/anime-waves-hi-gif-25928708",
        "https://tenor.com/view/anime-gif-18288690896653517146",
        "https://tenor.com/view/hello-hello-wave-waving-wave-anime-wave-gif-5241959545903110447",
        "https://tenor.com/view/bay-anime-bye-anime-bya-anime-anime-hola-anime-gif-20374982",
        "https://tenor.com/view/lucky-star-wave-hello-gif-3561948478976684501",
        "https://tenor.com/view/wind-breaker-wind-breaker-togame-anime-wave-anime-hello-togame-jo-gif-8582759802918432362",
        "https://tenor.com/view/keai-cute-gif-13201974045211134059",
        "https://tenor.com/view/seal-seal-waving-wave-waving-sea-lion-gif-16088027112700753598",
        "https://tenor.com/view/qoobee-hi-hello-wave-gif-25562895",
        "https://tenor.com/view/hi-good-afternoon-good-care-rabbit-hand-waves-gif-14148706483768650372",
        "https://tenor.com/view/creature-creature-wave-critter-wave-hello-gif-16718033248734905264",
        "https://tenor.com/view/waving-joy-lizard-hi-there-well-hello-there-gif-15622233555234689915",
        "https://tenor.com/view/happy-dance-wave-gif-25283702",
        "https://tenor.com/view/hand-wave-nommie-cut-the-rope-hi-hello-gif-27287856",
        "https://tenor.com/view/forrest-gump-wave-hello-hi-sup-gif-16159238468026206620",
    ],
}

INTERACTION_LINES = {
    "poke": [
        "{user} pokes {target} 👉",
        "{user} pokes {target}! Boop!",
        "{user} boops {target} 👉",
        "{user} pokes {target} playfully",
    ],
    "pat": [
        "{user} pats {target} 🫳",
        "{user} gives {target} a pat 🫳",
        "{user} headpats {target} 🫳",
        "{user} pats {target} gently",
    ],
    "hug": [
        "{user} hugs {target} 🫂",
        "{user} gives {target} a big hug 🫂",
        "{user} wraps {target} in a hug 🫂",
        "{user} hugs {target} tightly",
    ],
    "slap": [
        "{user} slaps {target} ✋",
        "{user} slaps {target} hard ✋",
        "{user} sends a slap {target}'s way ✋",
        "{user} slaps {target} across the room",
    ],
    "kill": [
        "{user} kills {target} 💀",
        "{user} eliminates {target} 💀",
        "{user} takes {target} out 💀",
        "{user} ends {target} 💀",
    ],
    "kiss": [
        "{user} kisses {target} 💋",
        "{user} gives {target} a kiss 💋",
        "{user} plants a kiss on {target}'s cheek 💋",
        "{user} kisses {target} gently 💋",
    ],
    "dance": [
        "{user} dances with {target} 🕺",
        "{user} pulls {target} into a dance 💃",
        "{user} and {target} dance together 💃",
        "{user} makes {target} dance 🕺",
    ],
    "wave": [
        "{user} waves at {target} 👋",
        "{user} waves hello to {target} 👋",
        "{user} gives {target} a friendly wave 👋",
        "{user} waves at {target} excitedly 👋",
    ],
}


async def _choose_interaction_gif(pool, is_valid=None):
    """Pick a random GIF from the pool, skipping any that fail the is_valid check."""
    ordered = list(pool)
    random.shuffle(ordered)
    for url in ordered:
        if is_valid is None:
            return url
        try:
            result = is_valid(url)
            if asyncio.iscoroutine(result):
                result = await result
            ok = bool(result)
        except Exception:
            ok = False
        if ok:
            return url
    return None


COMMAND_INDEX = [
    (".setup <houses> <rcs>", "Setup roles, channels & categories (houses and RoleChats, can differ)", "Setup", ["init", "configure", "server", "channel"]),
    (".setupguide", "Two-page guide to setting up a game, with example commands", "Setup", ["guide", "tutorial", "steps", "how", "setup"]),
    (".roleset <key> @role", "Assign a role for the bot", "Setup", ["config", "permission"]),
    (".channelset <key> #ch", "Assign a channel (mention, ID or name)", "Setup", ["config", "channel"]),
    (".addch <text>", "Append text to the current channel name (admin)", "Setup", ["channel", "rename", "append", "add", "admin"]),
    (".addch rename <name> [#channel]", "Fully rename a channel, optionally a different one (admin)", "Setup", ["channel", "rename", "add", "admin"]),
    (".channelstats", "List all categories with channel counts (admin)", "Setup", ["category", "channels", "list", "admin"]),
    (".categoryset <key> <name>", "Assign a category", "Setup", ["config", "category"]),
    (".houseprefix <pfx>", "Set house name prefix", "Setup", ["house", "naming", "prefix"]),
    (".knockduration <sec>", "Set knock timeout duration", "Setup", ["knock", "timeout", "timer"]),
    (".maxpinh <num>", "Max players per house", "Setup", ["house", "limit", "capacity"]),
    (".refuseresponse 1/2/3", "Knock refuse behavior: 1=show players, 2=show count, 3=no info", "Setup", ["knock", "refuse", "behaviour"]),
    (".settings", "View current settings", "Setup", ["config", "view", "current"]),
    (".resetdb", "Reset all setup", "Setup", ["clear", "wipe", "reset"]),
    (".stealemoji <emoji>", "Copy a custom emoji from another server into this one (animated & static)", "Setup", ["emoji", "copy", "steal", "server"]),
    (".showwhispersender", "Show/hide whisper sender", "Setup", ["whisper", "toggle", "anonymous"]),
    (".ajifempty", "Auto-join if house is empty", "Setup", ["auto", "join", "empty"]),
    (".ajknockexpire", "Auto-join when knock expires", "Setup", ["auto", "join", "expire"]),
    (".deadcount", "Deads count for Auto-Join/MaxPlayers", "Setup", ["dead", "autojoin", "count"]),
    (".altcount", "Alts count for Auto-Join/MaxPlayers", "Setup", ["alt", "autojoin", "count"]),
    (".showdeadsonrefuse", "Show deads on knock refuse", "Setup", ["dead", "refuse", "show"]),
    (".showaltsonrefuse", "Show alts on knock refuse", "Setup", ["alt", "refuse", "show"]),
    (".candeadsinteract", "Deads can open/refuse", "Setup", ["dead", "interact", "open", "refuse"]),
    (".canaltsinteract", "Alts can open/refuse", "Setup", ["alt", "interact", "open", "refuse"]),
    (".autopincorpse", "Auto pin corpse messages in houses", "Setup", ["corpse", "pin", "toggle", "dead"]),
    (".settime <event>", "Set daily game time via dropdowns (dayend/lynchend/presetend)", "Setup", ["time", "daily", "schedule", "set"]),
    (".times", "Show configured daily game times", "Setup", ["time", "daily", "schedule", "next"]),
    (".move <#|name>", "Move to a house. Players send a request that Overseers approve; admins act directly", "Moving", ["move", "house", "relocate", "request"]),
    (".renmove #House", "Move to renamed house", "Moving", ["move", "renamed", "house"]),
    (".add <#>", "Add player to house (keeps current)", "Moving", ["add", "house", "join"]),
    (".remove <#>", "Remove player from house", "Moving", ["remove", "house", "kick"]),
    (".knock <#|name>", "Knock on a house. Players send a request that Overseers approve; admins act directly", "Moving", ["knock", "door", "enter", "request"]),
    (".pendingknock / .showknocks [restart]", "True/False if any knock is pending + oldest age (restart = scan all servers, owners only)", "Moving", ["knock", "pending", "status"]),
    (".renknock #House", "Knock on renamed house", "Moving", ["knock", "renamed", "house"]),
    (".pcadd #PC", "Add player to PC/renamed house", "Moving", ["pc", "add", "private"]),
    (".pcremove #PC", "Remove from PC/renamed house", "Moving", ["pc", "remove", "private"]),
    (".addhere #RC", "Add RC's player to this channel", "Moving", ["rc", "add", "channel"]),
    (".addspons @sponsor #rc", "Add a sponsor directly to a rolechat (admin)", "Moving", ["sponsor", "rc", "rolechat", "add", "admin"]),
    (".movehouse #src #dest", "Bulk-move all residents from one house to another", "Moving", ["movehouse", "bulk", "move", "relocate"]),
    (".pportal #a #b [N]", "Place a two-way portal between two houses (alive players get N uses each; omit N for unlimited)", "Moving", ["portal", "pportal", "teleport", "travel", "link"]),
    (".follow @player [stealth]", "Make players in this RC follow @target", "Surveillance", ["follow", "track", "stalk", "move"]),
    (".unfollow @player", "Stop following @player", "Surveillance", ["unfollow", "stop", "track"]),
    (".followlist", "Show all active follow pairs", "Surveillance", ["follow", "list", "pairs"]),
    (".unfollowall", "Clear all follow pairs in this server", "Surveillance", ["unfollow", "clear", "all"]),
    (".track @player", "Watch a player's location live", "Surveillance", ["track", "watch", "location"]),
    (".untrack", "Stop watching the tracked player", "Surveillance", ["untrack", "stop", "watch"]),
    (".stalk @player", "Silently watch a player's house", "Surveillance", ["stalk", "peek", "read", "watch"]),
    (".unstalk @player", "Stop stalking a specific player", "Surveillance", ["unstalk", "stop", "read"]),
    (".unstalkall", "Stop stalking all players", "Surveillance", ["unstalk", "clear", "all"]),
    (".stalklist", "Show all active stalk relationships", "Surveillance", ["stalk", "list", "peek"]),
    (".home", "Bring the player home", "Home", ["home", "return", "location"]),
    (".home stealth", "Bring the player home silently (no join/leave messages)", "Home", ["home", "stealth", "silent", "admin"]),
    (".home return", "Bring all players home", "Home", ["home", "all", "return"]),
    (".leaveonlyhomes", "Remove all players in this RC from houses (not PCs)", "Home", ["leave", "houses", "remove", "rc"]),
    (".owner", "List house owners", "Home", ["owner", "house", "list"]),
    (".owned", "In a Role Chat: show the house(s) owned by the player(s) there", "Home", ["owned", "owner", "house", "myhouses"]),
    (".whorc [@player]", "Show the RoleChats you can send in, and who is in each (staff can check another player)", "Home", ["whorc", "rolechat", "who", "send"]),
    (".home initialize", "Assign RC to each alive player; structured: each player gets their own house (extra players share from the start)", "Home", ["home", "init", "assign", "admin", "structured"]),
    (".home initstagger", "Assign RC to each alive player; staggered: players dealt randomly across the existing houses", "Home", ["home", "init", "stagger", "random", "admin"]),
    (".home setup", "Move sponsors to their player's house", "Home", ["home", "sponsor", "admin"]),
    (".home set @player #house", "Set a player's home", "Home", ["home", "set", "admin"]),
    (".home mset", "Auto-set all current locations as home", "Home", ["home", "auto", "mass", "admin"]),
    (".home list", "List all players' homes", "Home", ["home", "list", "admin"]),
    (".home delete @player", "Make a player homeless", "Home", ["home", "delete", "remove", "admin"]),
    (".rolechat initialize", "Rebuild RCs — one alive player per RC, clearing old ones", "Home", ["rc", "rolechat", "init", "admin"]),
    (".rolechat list", "List all RCs and their players + sponsors (alias: lynch)", "Home", ["rc", "rolechat", "check", "list", "lynch", "admin"]),
    (".destroy #house", "Move to inaccessible, remove members, announce", "Handling", ["destroy", "house", "delete"]),
    (".fdestroy #house", "Force destroy instantly", "Handling", ["destroy", "force", "instant"]),
    (".decay #house", "Move to inaccessible, narrate in map", "Handling", ["decay", "house", "inactive"]),
    (".rebuild #house", "Rebuild a destroyed house", "Handling", ["rebuild", "restore", "house"]),
    (".decayinactive", "List/decay houses with 24h inactivity", "Handling", ["decay", "inactive", "idle"]),
    (".setowner #PC #RC", "Set a player as PC owner", "Handling", ["owner", "pc", "set"]),
    (".end #PC", "Remove all but the owner from a PC", "Handling", ["pc", "end", "clear", "owner"]),
    (".newpc Public/Private <name> #RC", "Create a PC", "Handling", ["pc", "create", "new", "private"]),
    (".mergepc #PC1 #PC2 [name]", "Merge two PCs into a new private channel", "Handling", ["pc", "merge", "combine", "private"]),
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
    (".preset", "Add, remove, or edit ability presets (interactive menu)", "Presets", ["preset", "ability", "template"]),
    (".ospreset", "View/reorder/remove all presets", "Presets", ["preset", "os", "admin", "manage"]),
    (".ospresetsort", "Reorder preset display categories", "Presets", ["preset", "sort", "order", "admin"]),
    (".ospresetcategories", "Add or remove custom preset categories", "Presets", ["preset", "category", "custom", "admin"]),
    (".vote @player", "Vote or change your vote", "Voting", ["vote", "cast", "change"]),
    (".patibolo @player", "Start a public execution vote (admin/Overseer)", "Voting", ["execution", "patibolo", "vote", "gallows", "execute"]),
    (".abstain", "Abstain from voting", "Voting", ["abstain", "skip", "vote"]),
    (".manipulate @target @vote", "Force @target's vote to @vote (admin)", "Voting", ["manipulate", "control", "force"]),
    (".removevote @player", "Remove a player's vote", "Voting", ["remove", "vote", "clear"]),
    (".remvote @player", "Remove all votes by/on player (all sessions)", "Voting", ["remvote", "remove", "vote", "clear", "all"]),
    (".skipnight <min_votes> [text]", "Start skip-night vote (custom title optional)", "Voting", ["skip", "night", "vote"]),
    (".skipnightvoters <message_id>", "Show voters on a skip-night vote (admin)", "Voting", ["skipnight", "voters", "admin"]),
    (".pick [cap=#] [time=1m] <Title>, <Option> ...", "Start anonymous multi-option vote in this channel (Overseer)", "Voting", ["pick", "vote", "poll", "anon", "skipvote"]),
    (".pickvoters <message_id>", "Reveal who voted on a pick poll (admin)", "Voting", ["pickvoters", "pick", "voters", "reveal", "admin"]),
    (".votelist", "Show all current votes", "Voting", ["vote", "list", "current"]),
    (".resetvotes", "Reset all votes", "Voting", ["reset", "vote", "clear"]),
    (".votehistory/vh [mode]", "Scan vote history (tracks .remvote/.removevote/.manipulate) — modes: grouped or range", "Voting", ["history", "vote", "log", "remvote"]),
    (".voteinrc true/false", "Enable voting in RoleChats", "Voting", ["rc", "rolechat", "vote", "toggle"]),
    (".updatevotes / .uv [#ch]", "Guide to refresh the votecount for a session via .vh (admin)", "Voting", ["updatevotes", "refresh", "votecount", "vh"]),
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
    (".rollhouses / .rh <num>", "Randomly select N visitable houses", "Lists", ["house", "roll", "random", "pick"]),
    (".rollhouse [#house] <num|all>", "Roll random alive members from a house", "Lists", ["house", "roll", "random", "alive"]),
    (".deadlist add @player <team> <role>", "Add to deadlist", "Lists", ["dead", "list", "add", "admin"]),
    (".deadlist remove @player", "Remove from deadlist", "Lists", ["dead", "list", "remove", "admin"]),
    (".deadlist edit @player <team> <role>", "Edit deadlist entry", "Lists", ["dead", "list", "edit", "admin"]),
    (".settarget <channel_id>", "Set target channel (ID, not mention)", "Send Role", ["target", "channel", "set"]),
    (".sendrole/sr <players>", "Reply to a msg to forward it to the target channel (admin)", "Send Role", ["send", "role", "forward"]),
    (".teamroll <n1> \"msg1\" <n2> \"msg2\" ...", "Randomly assigns quoted roles (Admin)", "Send Role", ["team", "roll", "random", "assign", "admin"]),
    (".dl", "Reply to a link to download the media and send it here", "Download", ["download", "media", "link", "yt-dlp"]),
    (".mdl", "Reply to a link to download its audio as an MP3", "Download", ["download", "mp3", "audio", "music", "yt-dlp"]),
    (".dsplit <N>", "Download and split a video into N equal parts (no number = minimum parts that fit)", "Download", ["download", "split", "parts", "video"]),
    (".dclip <start> [end] [N]", "Reply to a link to clip a timestamp range (optionally split into N parts)", "Download", ["download", "clip", "cut", "timestamp", "trim", "split"]),
    (".day", "Unlock all day channels", "Utility", ["day", "unlock", "phase"]),
    (".night", "Lock all day channels", "Utility", ["night", "lock", "phase"]),
    (".daywf", "Unlock the Future region's day channels", "Utility", ["day", "future", "unlock", "phase"]),
    (".nightwf", "Lock the Future region's day channels", "Utility", ["night", "future", "lock", "phase"]),
    (".daywp", "Unlock the Past region's day channels", "Utility", ["day", "past", "unlock", "phase"]),
    (".nightwp", "Lock the Past region's day channels", "Utility", ["night", "past", "lock", "phase"]),
    (".broom", "Delete replied-to messages (logs kept)", "Utility", ["broom", "delete", "clean", "message"]),
    (".actionstats", "View action completion counters", "Utility", ["actions", "stats", "log", "donestats"]),
    (".autoroleadd @role", "Add auto-visit allocation to all RC channels with this role", "Moving", ["auto", "visit", "role", "allocation"]),
    (".firstpin [count] [#channel]", "Show the oldest pinned message(s) as embeds", "Utility", ["pin", "first", "oldest"]),
    (".rename <name> [#channel]", "Rename a channel (admin)", "Setup", ["rename", "channel", "admin"]),
    (".execution @player", "Start a public execution vote for a player (admin)", "Voting", ["execution", "gallows", "vote", "admin"]),
    (".help2", "Show additional command categories", "Other", ["help", "categories"]),
    (".fmbot", "Show Last.fm bot commands by category", "Other", ["fmbot", "lastfm"]),
    (".pins", "Reorder or delete pinned messages (Manage Messages)", "Utility", ["pin", "pins", "reorder", "manage"]),
    (".unpinall [#channel]", "Remove every pin from a channel after confirming", "Utility", ["pin", "unpin", "unpinall", "clear"]),
    (".fbroom", "Force-delete messages including pinned (logs kept)", "Utility", ["fbroom", "force", "broom", "delete", "pinned"]),
    (".log", "Export messages to file: .log <count> [#source] [#destination]", "Utility", ["log", "message", "export"]),
    (".housecheck [hours]", "List quiet houses (default 24h)", "Utility", ["house", "quiet", "check", "inactive"]),
    (".whisper #RC <msg>", "Send anonymous whisper", "Utility", ["whisper", "anonymous", "message"]),
    (".switch", "Toggle Player/Sponsor role", "Utility", ["switch", "role", "toggle", "sponsor"]),
    (".dead", "Move your RC to Dead category (use in RC)", "Utility", ["dead", "rc", "move"]),
    (".deadrole", "Mark dead, remove house, pin corpse (use in RC)", "Utility", ["dead", "role", "mark", "corpse"]),
    (".deadc", "Move RC to Dead (admin)", "Utility", ["dead", "rc", "admin"]),
    (".corpselist", "List all corpse locations (admin)", "Utility", ["corpse", "list", "dead", "locations"]),
    (".kill @player [killer]", "Log kill attribution (overseer only). Or reply to a 'was moved to dead' message in overseer-discussion with the killer/way", "Utility", ["kill", "log", "overseer", "reply"]),
    (".kills [@player] [#channel]", "View kill log (admin only, ephemeral)", "Utility", ["kill", "log", "view", "ephemeral"]),
    (".killremove <number>", "Remove a kill log entry by .kills number (admin only)", "Utility", ["kill", "log", "remove", "delete", "edit"]),
    (".addrole @role @users...", "Give role to members", "Utility", ["role", "add", "give", "admin"]),
    (".removerole <role> <member...>", "Remove role from members (admin)", "Utility", ["role", "remove", "admin"]),
    (".addcategoryperms @role <cat> <perm>", "R=Read, S=Send", "Utility", ["perm", "category", "read", "send", "admin"]),
    (".addchannelperms @role #ch <perm>", "R=Read, S=Send", "Utility", ["perm", "channel", "read", "send", "admin"]),
    (".endgame", "Unlock all channels post-game", "Utility", ["game", "end", "unlock", "admin"]),
    (".statss", "Show message counts for day discussion, grouped by role (admin)", "Utility", ["stats", "message", "count", "admin"]),
    (".serverstats", "Show server-wide counts; `lap <label>` saves (with confirmation), `laps` lists, `total` combines all (admin)", "Utility", ["stats", "server", "message", "count", "lap", "admin"]),
    (".resetservstats", "Reset server-wide message counts; `true` also clears laps", "Utility", ["tracking", "server", "reset", "admin"]),
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
    (".where #RC", "Show a player's current location (staff only, needs confirmation)", "Other", ["where", "location", "find"]),
    (".housewho [#house|#RC]", "Show your house and who is inside it", "Other", ["housewho", "hw", "house", "who", "location"]),
    (".map", "Show the game map", "Other", ["map", "game", "overview"]),
    (".role", "Show the registered role package (paginated; role card excluded)", "Other", ["role", "package", "pinned", "first", "card"]),
    (".role register <1-4> <role name>", "Register pinned messages as a Role Package", "Other", ["role", "package", "register"]),
    (".role registercard [message_id]", "Register a Role Card message", "Other", ["role", "card", "register"]),
    (".role card", "Show the registered Role Card (images included)", "Other", ["role", "card", "image"]),
    (".role regteam [1-5] [@player] [@sponsor]", "Set team slot: 1=Village 2=Evil 3=Rk 4=Neutral 5=Bonus; player/sponsor optional", "Other", ["role", "team", "slot", "regteam"]),
    (".role check [#channel]", "Check package completeness (admin check other channels)", "Other", ["role", "check", "package", "completeness"]),
    (".role list", "List all RCs and their package status (admin)", "Other", ["role", "list", "rcs", "admin"]),
    (".setlogserver <channel_id>", "Set the channel where role archives are posted (bot must be in that server)", "Other", ["setlogserver", "log", "server", "archive"]),
    (".role help", "Explain the Role Package workflow", "Other", ["role", "package", "help", "guide", "how"]),
    ("`/reveal`", "Reveal Role Card ephemerally (overseer/admin, slash only)", "Other", ["reveal", "card", "ephemeral"]),
    (".firstmsg [#ch]", "Show first message in current channel (#ch needs admin)", "Other", ["first", "message", "jump", "oldest"]),
    (".roll @role <n>", "Random players from a role", "Other", ["roll", "random", "pick"]),
    (".ping", "Bot online check", "Other", ["ping", "bot", "online", "check"]),
    (".ding", "Dong!", "Other", ["ding", "fun", "easter"]),
    (".avatar [@member]", "Show your avatar (or another member's)", "Other", ["avatar", "pfp", "picture", "profile"]),
    (".line / .banner [lines] [title]", "Draw a clean divider banner between text (admin)", "Other", ["line", "banner", "divider", "separator", "gap"]),
    (".askos <question>", "Ask the Overseers from an RC, Dead RC or Alt (Alive/Sponsor/Alt/Dead)", "Other", ["ask", "overseer", "question", "osq", "askoverseer"]),
    (".narrate #ch <msg>", "Send narration to channels", "Other", ["narrate", "announce", "admin"]),
    (".narration/.n <text>", "Storybook embed (admin, pings)", "Other", ["narration", "story", "embed", "admin"]),
    (".np <text>", "Storybook embed, no pin (admin)", "Other", ["narration", "story", "embed", "admin", "nopin"]),
    (".react <1-10 | word>", "React to a replied message (admin/OS)", "Other", ["react", "reaction", "emoji", "admin"]),
    (".anarration/.na <text>", "Silent narration (admin)", "Other", ["narration", "silent", "admin"]),
    (".narrationcolor", "Pick embed color (admin)", "Other", ["narration", "color", "embed", "admin"]),
    (".dice <n>", "Roll 1-N", "Other", ["dice", "roll", "random", "number"]),
    (".dice <opt1>, <opt2>, ...", "Random pick from options (comma or space separated)", "Other", ["dice", "choose", "pick", "random"]),
    (".opoke @user", "Poke someone with an anime GIF", "Other", ["poke", "fun", "interaction"]),
    (".opat @user", "Pat someone with an anime GIF", "Other", ["pat", "fun", "interaction"]),
    (".ohug @user", "Hug someone with an anime GIF", "Other", ["hug", "fun", "interaction"]),
    (".oslap @user", "Slap someone with an anime GIF", "Other", ["slap", "fun", "interaction"]),
    (".okill @user", "Kill someone with an anime GIF", "Other", ["kill", "fun", "interaction"]),
    (".okiss @user", "Kiss someone with an anime GIF", "Other", ["kiss", "fun", "interaction"]),
    (".odance @user", "Dance with someone with an anime GIF", "Other", ["dance", "fun", "interaction"]),
    (".owave @user", "Wave at someone with an anime GIF", "Other", ["wave", "fun", "interaction"]),
    (".loc", "Show all houses and occupants (admin)", "Other", ["loc", "location", "houses", "occupants", "admin"]),
    (".gettag <link>", "Get mentioned users from a message", "Other", ["tag", "mention", "get"]),
    (".timer <time> [tag] [#ch]", "Set a timer", "Other", ["timer", "remind", "countdown"]),
    (".deletechannel", "Delete this channel (admin)", "Other", ["delete", "channel", "admin"]),
    (".deletecategory [category]", "Delete a category and all its channels (admin)", "Other", ["delete", "category", "delcat", "admin"]),
    (".timestamp <DD-MM> <HH:MM>", "Gen timestamp with timezone picker", "Other", ["timestamp", "time", "timezone", "convert"]),
    (".time", "Get sent time of replied-to message", "Other", ["time", "message", "sent"]),
    (".dropitem", "Drop interactive item (see docs)", "Other", ["drop", "item", "interactive"]),
    (".revive", "Revive dead players (interactive, admin)", "Other", ["revive", "dead", "resurrect", "admin"]),
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
    (".setmeetingtargetguild <id>", "Set meeting server (Discord guild ID)", "Meetup Matrix", ["meeting", "guild", "server", "admin"]),
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
    (".buy <item> [qty]", "Buy from shop (to RC inventory, default qty=1)", "Economy", ["buy", "purchase", "shop"]),
    (".sell /.sell-item <item>", "Sell for 50% refund", "Economy", ["sell", "refund", "item"]),
    (".inv /.inventory [#ch]", "View RC inventory", "Economy", ["inventory", "items", "rc"]),
    (".give @user <amt | item [qty|all]>", "Give RC coins, or items to a player in the same house", "Economy", ["give", "coins", "items", "gift", "transfer"]),
    (".give-money @user <amt>", "Transfer RC coins to another player", "Economy", ["money", "transfer", "rc"]),
    (".use <item>", "Use an item from inventory", "Economy", ["use", "item", "activate"]),
    (".additem <name> <price> [desc] [stock]", "Add new shop item (emoji first, no numbers in name — quote it if needed; trailing number = stock)", "Economy", ["item", "add", "shop", "admin"]),
    (".updatestock <item> <stock>", "Set item stock (0 = unlimited)", "Economy", ["item", "stock", "shop", "admin"]),
    (".removeitem /.rmitem #ch <item> [qty]", "Remove from RC", "Economy", ["item", "remove", "rc", "admin"]),
    (".edititem <field> <name> <val>", "Edit shop item (field: price/name/description/stock)", "Economy", ["item", "edit", "shop", "admin"]),
    (".delitem <name>", "Delete item from shop", "Economy", ["item", "delete", "shop", "admin"]),
    (".addmoney #ch <amt>", "Add coins to RC", "Economy", ["money", "add", "coins", "rc", "admin"]),
    (".removemoney #ch <amt>", "Remove coins from RC", "Economy", ["money", "remove", "coins", "rc", "admin"]),
    (".add-money-role @role <amt>", "Add RC coins by role", "Economy", ["money", "role", "rc", "admin"]),
    (".remove-money-role @role <amt>", "Remove RC coins by role", "Economy", ["money", "role", "remove", "rc", "admin"]),
    (".additemrole @role <item> <qty>", "Give items by role", "Economy", ["item", "role", "give", "admin"]),
    (".giveitem @player <item> [qty]", "Give items to player (admin)", "Economy", ["item", "give", "admin"]),
    (".removeitemplayer @player <item> [qty]", "Remove items from player (admin)", "Economy", ["item", "remove", "admin", "rip"]),
    (".trade @player <item> [qty]", "Trade items with another player (in houses)", "Economy", ["item", "trade", "transfer", "give"]),
    (".sellshop on|off", "Admin: turn shop selling on or off", "Economy", ["sell", "shop", "toggle", "admin"]),
    (".reseteconomy [amt]", "Reset all balances (default 0)", "Economy", ["economy", "reset", "balance", "admin"]),
    (".clearinventory", "Clear all inventories", "Economy", ["inventory", "clear", "admin"]),
    (".collect", "Add set collect amount to every RC's balance (use .setcollect first)", "Economy", ["collect", "money", "rc", "admin"]),
    (".setcollect <val>", "Set collect amount (max 10k)", "Economy", ["collect", "amount", "set", "admin"]),
    (".leaderboard /.lb /.top [n]", "Richest RCs (default top 10)", "Economy", ["leaderboard", "top", "richest", "rcs"]),
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
    (".dashboard", "Open the interactive role dashboard", "Dashboard", ["dashboard", "role", "ui"]),
    (".dashboardtoggle", "Enable/disable dashboard", "Dashboard", ["dashboard", "toggle", "admin"]),
    (".setrole @role", "Set dashboard role", "Dashboard", ["dashboard", "role", "set", "admin"]),
    (".addpassiveability <name> <desc>", "Add passive ability", "Dashboard", ["ability", "passive", "add", "admin"]),
    (".removepassiveability <name>", "Remove passive", "Dashboard", ["ability", "passive", "remove", "admin"]),
    (".addactiveability <name> <desc> <uses>", "Add active ability (uses = max uses per game)", "Dashboard", ["ability", "active", "add", "admin"]),
    (".removeactiveability <name>", "Remove active", "Dashboard", ["ability", "active", "remove", "admin"]),
    (".vb", "Toggle visit blocking for a RoleChat (admin)", "Dashboard", ["visit", "block", "vb", "admin"]),
    (".checkvb #channel", "Check if visit blocking is active for a RoleChat (admin)", "Dashboard", ["visit", "block", "check", "admin"]),
    (".lockhouse #house", "Lock a house (blocks moves/knocks)", "Dashboard", ["house", "lock", "admin"]),
    (".unlockhouse #house", "Unlock a previously locked house", "Dashboard", ["house", "unlock", "admin"]),
    (".setvisits @user <amt>", "Set visit count", "Dashboard", ["visit", "set", "admin"]),
    (".addvisits @user <amt>", "Add visits", "Dashboard", ["visit", "add", "admin"]),
    (".removevisits @user <amt>", "Remove visits", "Dashboard", ["visit", "remove", "admin"]),
    (".actionlog [@user]", "View action log", "Dashboard", ["action", "log", "audit"]),
    (".setboard", "Set up the OS info board", "Dashboard", ["board", "info", "os", "admin"]),
    (".setinfophase <phase>", "Set phase info: day/night + number", "Dashboard", ["phase", "info", "set", "admin"]),
    (".addcard", "Add an info card", "Dashboard", ["card", "info", "add", "admin"]),
    (".refreshcards", "Refresh all info cards", "Dashboard", ["card", "refresh", "info", "admin"]),
    (".statuss [#channel] [key] [value]", "View/edit player status (overseer)", "Dashboard", ["status", "player", "overseer"]),
    (".unlockability #channel <ab_id> <name> <cat> <uses> <desc>", "Unlock ability for Mr. House (overseer)", "Dashboard", ["ability", "unlock", "mr", "house", "overseer"]),
    (".startgame /.sg <slots> @host <name>", "Start a lobby", "Game Manager", ["game", "start", "lobby", "admin"]),
    (".addplayer /.ap <slot> @player [name]", "Fill a slot", "Game Manager", ["player", "add", "slot", "admin"]),
    (".removeplayer /.rp <slot> [name]", "Remove from slot", "Game Manager", ["player", "remove", "slot", "admin"]),
    (".closegame /.cg [name]", "Close & archive game", "Game Manager", ["game", "close", "archive", "admin"]),
    (".stats [@player]", "View player statistics", "Library & Stats", ["stats", "player", "statistics"]),
    (".statsos <name or @ping>", "Overseer stats & team winrates", "Library & Stats", ["stats", "overseer", "host", "winrate"]),
    (".winrate", "Winrate stats by team", "Library & Stats", ["winrate", "stats", "team"]),
    (".relations [@user]", "Allies and nemeses (+ games played together for @user)", "Library & Stats", ["relations", "ally", "nemesis", "together"]),
    (".lib", "Browse the game library", "Library & Stats", ["library", "browse", "games"]),
    (".lib add", "Add a new game", "Library & Stats", ["library", "add", "game", "admin"]),
    (".lib summary", "Summary of all games", "Library & Stats", ["library", "summary", "overview"]),
    (".lib edit <#> <field> <val>", "Edit a game field (e.g. name, team, winner, host)", "Library & Stats", ["library", "edit", "admin"]),
    (".lib delete <#>", "Delete a game", "Library & Stats", ["library", "delete", "admin"]),
    (".lib deletegame <#>", "Delete a game (alt)", "Library & Stats", ["library", "delete", "admin"]),
    (".lib remove host @player", "Remove a host from this game", "Library & Stats", ["library", "remove", "host"]),
    (".lib setwin <#> <team>", "Set winning team", "Library & Stats", ["library", "win", "set", "admin"]),
    (".lib search <term>", "Search by name or player", "Library & Stats", ["library", "search", "find"]),
    (".lib searchdisc <query>", "Search role descriptions & text", "Library & Stats", ["library", "search", "description", "text", "disc"]),
    (".gamesearch <conds>", "Search past games by team stats, outcomes & role counts (Win/Lose, >/< %, VillageCount, Players)", "Library & Stats", ["game", "search", "stats", "outcome", "win", "lose", "percent", "count", "players"]),
    (".gamesearchn <conds>", "Search games with percentages excluding Neutral roles (counts unchanged)", "Library & Stats", ["game", "search", "stats", "no", "neutral", "percent", "win", "count"]),
    (".publishroles", "Build role publishing draft (clean packages only)", "Library & Stats", ["roles", "publish", "archive"]),
    (".resolveplayers", "Show unresolved Role Package players", "Library & Stats", ["roles", "resolve", "players"]),
    (".resolveplayer #channel @player", "Resolve a Role Chat player", "Library & Stats", ["roles", "resolve", "player"]),
    (".resolvesponsor #channel @sponsor", "Choose the Library Sponsor", "Library & Stats", ["roles", "resolve", "sponsor"]),
    (".reviewroles", "Review the role publishing draft", "Library & Stats", ["roles", "review", "publish"]),
    (".reviewteams", "Review role teams in the publishing draft (add `alive` for only alive players)", "Library & Stats", ["roles", "teams", "review", "alive"]),
    (".ps", "Randomized players & sponsors list (no team info)", "Library & Stats", ["players", "sponsors", "review", "list", "random"]),
    (".playerspons", "Alias of `.ps` — randomized players & sponsors list (no team info)", "Library & Stats", ["players", "sponsors", "list", "random"]),
    (".approvepublish", "Approve and publish the role archive", "Library & Stats", ["roles", "approve", "publish"]),
    (".libimport", "Import the approved draft into the library", "Library & Stats", ["library", "import", "roles"]),
    (".libitimport", "Import approved draft into Italian library", "Library & Stats", ["library", "import", "italian", "roles"]),
    (".lib searchos <name or @ping>", "Search games by overseer", "Library & Stats", ["library", "search", "overseer", "host"]),
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
    (".auc", "Blind auction board & status", "Auction", ["auction", "bid", "blind", "auctionhouse", "help2"]),
    (".auc start <item> <dur> [sealed|visible]", "Open a blind auction (alive players)", "Auction", ["auction", "start", "blind", "open"]),
    (".auc bid <amount>", "Place a sealed bid (or use the board button)", "Auction", ["auction", "bid", "sealed", "blind"]),
    (".auc extend <dur>", "Add time to the current auction (Overseer)", "Auction", ["auction", "extend", "time", "overseer"]),
    (".auc close", "End the auction early (Overseer)", "Auction", ["auction", "close", "overseer", "end"]),
    (".auc cancel", "Void the current auction (Overseer)", "Auction", ["auction", "cancel", "overseer", "void"]),
    (".auc alias <player>", "Reveal a player's auction alias (Overseer)", "Auction", ["auction", "alias", "reveal", "investigate", "overseer"]),
    (".aucset", "Configure the auction system (admin)", "Auction", ["auction", "config", "settings", "admin"]),
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
    (".soldiers", "Soldiers strategy game — use `.soldiers help` for subcommands", "Games", ["soldiers", "strategy", "game"]),
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
    (".analytics", "Interactive match analytics, trends and visualizations", "Analytics", ["analytics", "match", "trends", "stats", "fifa"]),
    (".analyticsreset", "Reset analytics data (admin)", "Analytics", ["analytics", "reset", "admin"]),
    (".analyticsexport", "Export analytics data to markdown file", "Analytics", ["analytics", "export", "download", "backup"]),
    (".failures [command]", "Show command error leaderboard", "Analytics", ["failures", "error", "leaderboard", "stats"]),
    (".searchhelp / .sh <kw>", "Search commands by keyword", "Other", ["search", "find", "keyword", "help"]),
    (".libit", "Browse the Italian game library", "Library & Stats", ["library", "italian", "browse", "libit"]),
    (".libit add", "Add a new game (IT)", "Library & Stats", ["library", "italian", "add", "admin"]),
    (".libit summary", "Summary of all games (IT)", "Library & Stats", ["library", "italian", "summary"]),
    (".libit edit <#> <field> <val>", "Edit a game field (IT) — e.g. name, team, winner", "Library & Stats", ["library", "italian", "edit", "admin"]),
    (".libit delete <#>", "Delete a game (IT)", "Library & Stats", ["library", "italian", "delete", "admin"]),
    (".libit deletegame <#>", "Delete a game alt (IT)", "Library & Stats", ["library", "italian", "delete", "admin"]),
    (".libit setwin <#> <team>", "Set winning team (IT)", "Library & Stats", ["library", "italian", "win", "admin"]),
    (".libit search <term>", "Search by name or player (IT)", "Library & Stats", ["library", "italian", "search"]),
    (".libit idsearch <id>", "Search by game ID (IT)", "Library & Stats", ["library", "italian", "id"]),
    (".libit migrateaccount", "Move stats to new account (IT)", "Library & Stats", ["library", "italian", "migrate"]),
    (".libit mergeaccount", "Merge two accounts' stats (IT)", "Library & Stats", ["library", "italian", "merge"]),
    (".libit syncname", "Sync display name (IT)", "Library & Stats", ["library", "italian", "sync"]),
    (".libit bulksyncnames", "Bulk sync all names (IT)", "Library & Stats", ["library", "italian", "bulk", "admin"]),
    (".statsit [@player]", "View player statistics (IT)", "Library & Stats", ["stats", "italian", "player"]),
    (".winrateit", "Winrate stats by team (IT)", "Library & Stats", ["winrate", "italian", "team"]),
    (".relationsit [@user]", "Allies and nemeses (IT)", "Library & Stats", ["relations", "italian", "ally"]),
    (".missingidsit", "Games with missing player IDs (IT)", "Library & Stats", ["missing", "ids", "italian", "admin"]),
    (".badnamesit", "List bad/unnamed players (IT)", "Library & Stats", ["bad", "names", "italian", "admin"]),
    (".removebadnameit <name>", "Remove a bad name (IT)", "Library & Stats", ["remove", "bad", "name", "italian", "admin"]),
    ("/status", "Open Status Manager for this channel (admin)", "Status", ["status", "moderator", "track", "protection", "roleblock", "stealth", "immunity", "untargetable"]),
    (".status clear", "Clear all statuses for this channel (admin)", "Status", ["status", "clear", "remove", "admin"]),
    (".statuslist", "Show all channels with active statuses (admin)", "Status", ["status", "list", "overview", "moderator"]),
    (".statuspanel", "Post or refresh the interactive Online/AFK member status panel", "Status", ["status", "panel", "online", "afk"]),
    (".sticky [#ch]", "Show sticky message status for a channel", "Sticky", ["sticky", "pin", "status"]),
    (".sticky set [#ch] <text>", "Set a sticky message for a channel (admin)", "Sticky", ["sticky", "set", "pin", "admin"]),
    (".sticky remove [#ch]", "Remove a sticky message (admin)", "Sticky", ["sticky", "remove", "delete", "admin"]),
    (".sticky cooldown [#ch] <sec>", "Set sticky refresh cooldown, min 10s (admin)", "Sticky", ["sticky", "cooldown", "refresh", "admin"]),
    (".sticky list", "List all sticky messages in this server (admin)", "Sticky", ["sticky", "list", "overview", "admin"]),
]


def _utc_offset_str(tz_name: str) -> str:
    try:
        offset = datetime.datetime.now(ZoneInfo(tz_name)).utcoffset()
        total_seconds = int(offset.total_seconds())
        hours, remainder = divmod(abs(total_seconds), 3600)
        minutes = remainder // 60
        sign = "+" if total_seconds >= 0 else "-"
        if minutes:
            return f"(UTC{sign}{hours}:{minutes:02d})"
        return f"(UTC{sign}{hours})"
    except Exception:
        return ""


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
            discord.SelectOption(
                label=f"{name} {_utc_offset_str(tz)}",
                value=tz,
                emoji=emoji,
            )
            for name, tz, emoji in COMMON_TIMEZONES
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


def find_category(guild, query: str):
    """Find a category by ID, exact name or partial name.

    Returns ``(category, error)`` — exactly one of the two is set.
    """
    query = (query or "").strip().strip("#")
    if not query:
        return None, "Give me a category name or ID."

    if query.isdigit():
        category = discord.utils.get(guild.categories, id=int(query))
        if category:
            return category, None

    lowered = query.lower()
    exact = [c for c in guild.categories if c.name.lower() == lowered]
    if exact:
        return exact[0], None

    partial = [c for c in guild.categories if lowered in c.name.lower()]
    if len(partial) > 1:
        names = "\n".join(f"• `{c.name}`" for c in partial[:10])
        return None, (
            f"Multiple categories match `{query}`:\n{names}\n"
            "Use the exact name or the category ID."
        )
    if partial:
        return partial[0], None

    return None, f"I couldn't find a category called `{query}`."


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


# ── .fmbot command reference ───────────────────────────────────────
# Each category has "sections": a list of {name, cmds} dicts.
# name=None means no section header.  cmds are (command, desc) tuples.
# Aliases are shown compactly:  ",command ,alias" · description

_FMBOT_COMMANDS = {
    # ── Row 1 ─────────────────────────────────────────────────────
    "getting-started": {
        "name": "Getting Started", "emoji": "🚀",
        "sections": [
            {"name": "Now Playing", "cmds": [
                (",fm", "Latest 1–2 scrobbles"),
                (",recent ,r", "Latest plays"),
            ]},
            {"name": "Top Charts", "cmds": [
                (",topartists ,ta", "Top artists over time"),
                (",topalbums ,tab", "Top albums over time"),
                (",toptracks ,tt", "Top tracks over time"),
            ]},
            {"name": None, "cmds": [
                (",chart ,c", "Visual chart of top albums"),
                (",artistchart ,ac", "Visual chart of top artists"),
                (",whoknows ,wk", "Who in server listens to an artist"),
                (",taste ,t", "Compare your taste with someone"),
                (",update ,u", "Refresh your cached scrobbles"),
            ]},
        ],
    },
    "albums": {
        "name": "Albums", "emoji": "💿",
        "sections": [
            {"name": None, "cmds": [
                (",album ,ab", "Album info (current or search)"),
                (",albumplays ,abp", "Your playcount for an album"),
                (",albumtracks ,abt", "Tracks in an album"),
                (",cover ,co", "Show album cover art"),
            ]},
            {"name": "Charts", "cmds": [
                (",chart ,c", "Chart of top albums over time"),
                (",albumsoftheyear ,aoty", "Albums from a specific year"),
                (",topalbums ,tab", "Top albums over time"),
            ]},
            {"name": "Server", "cmds": [
                (",whoknowsalbum ,wa", "Who in server listened to album"),
                (",globalwhoknowsalbum ,gwa", "Who globally listened to album"),
                (",serveralbums", "Top albums for everyone in server"),
            ]},
        ],
    },
    "artists": {
        "name": "Artists", "emoji": "🎤",
        "sections": [
            {"name": None, "cmds": [
                (",artist ,a", "Artist info (current or search)"),
                (",artistplays ,ap", "Your playcount for an artist"),
                (",artistoverview ,ao", "Overview of an artist"),
                (",artisttracks ,at", "Top tracks for an artist"),
                (",artistalbums ,aa", "Top albums for an artist"),
                (",artistpace ,apc", "Estimate when you'll reach X plays"),
                (",affinity ,aff", "Users with similar music taste"),
            ]},
            {"name": "Charts & Discovery", "cmds": [
                (",artistchart ,ac", "Chart of top artists over time"),
                (",topartists ,ta", "Top artists over time"),
                (",taste ,t", "Compare your taste with someone"),
                (",iceberg ,ice", "Iceberg based on artist popularity"),
            ]},
            {"name": "Server", "cmds": [
                (",whoknows ,wk", "Who in server listened to artist"),
                (",globalwhoknows ,gw", "Who globally listened to artist"),
                (",serverartists", "Top artists for everyone in server"),
            ]},
        ],
    },
    "plays": {
        "name": "Plays", "emoji": "▶️",
        "sections": [
            {"name": "History", "cmds": [
                (",fm", "Latest 1–2 scrobbles"),
                (",recent ,r", "Latest plays"),
                (",search ,sr", "Search your stored library"),
                (",plays ,p", "Total scrobble count for time period"),
            ]},
            {"name": "Streaks & Milestones", "cmds": [
                (",streak ,str", "Track/album/artist streak"),
                (",streakhistory ,strs", "Past streaks"),
                (",milestone ,ms", "Latest scrobble milestones"),
            ]},
            {"name": None, "cmds": [
                (",overview ,o", "Top track/album/artist for last few days"),
                (",pace ,pc", "Estimate when you'll reach X plays"),
                (",year", "Year overview"),
                (",recap", "All commands for a timeframe in one recap"),
                (",scrobbleleaderboard ,sblb", "Most plays in server"),
                (",timeleaderboard ,tlb", "Most listening time in server"),
            ]},
        ],
    },
    "tracks": {
        "name": "Tracks", "emoji": "🎵",
        "sections": [
            {"name": None, "cmds": [
                (",track ,tr", "Track info (current or search)"),
                (",trackplays ,tp", "Your playcount for a track"),
                (",trackdetails ,td", "Metadata for a track"),
                (",receipt ,rcpt", "Track receipt (Receiptify style)"),
            ]},
            {"name": "Charts", "cmds": [
                (",toptracks ,tt", "Top tracks over time"),
            ]},
            {"name": "Server", "cmds": [
                (",whoknowstrack ,wt", "Who in server listened to track"),
                (",globalwhoknowstrack ,gwt", "Who globally listened to track"),
                (",servertracks", "Top tracks for everyone in server"),
            ]},
            {"name": "Loved Tracks", "cmds": [
                (",love ,l", "Add track to loved tracks"),
                (",unlove ,ul", "Remove track from loved tracks"),
                (",loved ,lt", "Display loved tracks"),
            ]},
            {"name": None, "cmds": [
                (",scrobble ,sb", "Scrobble a track on Last.fm"),
            ]},
        ],
    },

    # ── Row 2 ─────────────────────────────────────────────────────
    "music-services": {
        "name": "Music Services", "emoji": "🔗",
        "sections": [
            {"name": "Links", "cmds": [
                (",genius ,gen", "Genius link for a track"),
                (",applemusic ,am", "Apple Music link for a track"),
                (",spotify ,sp", "Spotify link for a track"),
                (",spotifyalbum ,spab", "Spotify link for an album"),
                (",spotifyartist ,spa", "Spotify link for an artist"),
                (",youtube ,yt", "YouTube link for a track"),
            ]},
            {"name": "Remote", "cmds": [
                (",remote ,rc", "Open Spotify remote panel"),
                (",play", "Play/resume track on Spotify"),
                (",queue ,q", "Queue a track on Spotify"),
                (",pause", "Pause Spotify playback"),
                (",skip ,rs", "Skip to next track"),
                (",previous ,prev", "Go back to previous track"),
                (",rclike ,rl", "Like a track on Spotify"),
                (",rcunlike ,rcul", "Unlike a track on Spotify"),
            ]},
        ],
    },
    "more": {
        "name": "More", "emoji": "🌐",
        "sections": [
            {"name": "🌍 Countries", "cmds": [
                (",topcountries ,tc", "Top countries over time period"),
                (",country ,from", "Country info or top artists"),
                (",countrychart ,cc", "Map of your top artist locations"),
            ]},
            {"name": "👑 Crowns", "cmds": [
                (",crowns ,cws", "Your top crowns or crowns for a user"),
                (",crown ,cw", "Who holds crown, head-to-head battle"),
                (",crownleaderboard ,cwlb", "Users with most crowns in server"),
            ]},
            {"name": "⭐ Featured", "cmds": [
                (",featured ,feat", "Currently featured user/album"),
                (",featuredlog ,fl", "Featured history"),
            ]},
            {"name": "🏷️ Genres", "cmds": [
                (",topgenres ,tg", "Top genres over time period"),
                (",genre ,g", "Genre info or top artists for genre"),
                (",whoknowsgenre ,wg", "Who in server listened to genre"),
                (",servergenres", "Top genres for everyone in server"),
            ]},
            {"name": "🔄 Updating", "cmds": [
                (",update ,u", "Refresh your playcount cache"),
                (",refreshmembers", "Refresh server member cache"),
            ]},
        ],
    },
    "games": {
        "name": "Games", "emoji": "🎮",
        "sections": [
            {"name": None, "cmds": [
                (",jumble ,j", "Guess jumbled artist names"),
                (",pixel ,px", "Guess album from pixelated cover"),
            ]},
        ],
    },
    "misc": {
        "name": "Misc", "emoji": "📦",
        "sections": [
            {"name": None, "cmds": [
                (",judge", "AI judges your music taste"),
                (",rateyourmusic ,rym", "Toggle RateYourMusic album links"),
                (",info", "Show bot information and links"),
                (",status", "Get bot status information"),
                (",eurovision ,ev", "Eurovision Song Contest info"),
                (",remove", "Delete all your data from .fmbot"),
            ]},
        ],
    },
}

_FMBOT_CAT_ROWS = [
    ["getting-started", "albums", "artists", "plays", "tracks"],
    ["music-services", "more", "games", "misc"],
]


class FMBotView(View):
    def __init__(self, author_id: int):
        super().__init__(timeout=120)
        self.author_id = author_id
        self.message: discord.Message | None = None
        self.current_cat = "getting-started"
        self._rebuild()

    def _rebuild(self):
        self.clear_items()
        for row_idx, keys in enumerate(_FMBOT_CAT_ROWS):
            for key in keys:
                cat = _FMBOT_COMMANDS[key]
                btn = Button(
                    label=cat["name"],
                    emoji=cat["emoji"],
                    style=(
                        discord.ButtonStyle.success
                        if key == self.current_cat
                        else discord.ButtonStyle.secondary
                    ),
                    row=row_idx,
                )
                btn.callback = self._cat_cb(key)
                self.add_item(btn)

    def _cat_cb(self, key):
        async def cb(interaction):
            if interaction.user.id != self.author_id:
                return await interaction.response.send_message("Not your menu.", ephemeral=True)
            if key == self.current_cat:
                return await interaction.response.defer()
            self.current_cat = key
            self._rebuild()
            await interaction.response.edit_message(embed=self._embed(), view=self)
        return cb

    def _embed(self) -> discord.Embed:
        cat = _FMBOT_COMMANDS[self.current_cat]
        lines: list[str] = []
        for sec in cat["sections"]:
            if sec["name"]:
                lines.append(f"**{sec['name']}**")
            for cmd, desc in sec["cmds"]:
                lines.append(f"`{cmd}` · {desc}")
            lines.append("")
        desc = "\n".join(lines).rstrip()
        embed = discord.Embed(
            title=f"{cat['emoji']} {cat['name']} — .fmbot Commands",
            description=desc,
            color=0x1DB954,
        )
        embed.set_footer(text="Prefix is comma (,) for all fmbot commands")
        return embed

    async def on_timeout(self):
        for child in self.children:
            child.disabled = True
        if self.message:
            try:
                await self.message.edit(view=self)
            except Exception:
                pass


# ── Player-facing help reference ───────────────────────────────────
# .phelp (.playerhelp) shows ONLY commands regular players can use.
# Categories group related commands; each entry is (command, short desc)
# where command is shown with its alias(es):  ",cmd ,alias"
# .phelp (.playerhelp) shows ONLY commands regular players can use,
# as one flat list. Each entry is (command, short desc) where command is
# shown with its alias(es):  ",cmd ,alias"
_PLAYER_COMMANDS = [
    (".help", "Show the full command menu"),
    (".phelp ,playerhelp", "This player command menu"),
    (".help economy", "All economy & shop commands"),
    (".help library", "All library & stats commands"),
    (".who #ch", "List players in a channel by role"),
    (".where", "Check your location in your RoleChat (outside a RoleChat: admin-only, reply `yes`)"),
    (".where #RC", "Check a player's location (staff only, reply `yes`)"),
    (".housewho [#house|#RC]", "Show your house and who is inside it"),
    (".owner", "List the owners of the current house"),
    (".p ,playerlist", "List all alive players"),
    (".map", "Show the game map"),
    (".times", "Show daily game times"),
    (".playerlist ,p", "List all alive members"),
    (".sponsorlist", "List all sponsor members"),
    (".houselist ,hl", "List visitable houses"),
    (".rollhouses ,rh", "Pick random houses from the list"),
    (".rollhouse [#house] <num|all>", "Roll random alive members from a house"),
    (".deadlist ,d", "Show dead players & their roles"),
    (".vote @user", "Cast or change your vote"),
    (".v ,votelist", "Show all current votes"),
    (".abstain", "Abstain from the vote"),
    (".dice <n|opts>", "Roll 1–N or pick from options"),
    (".roll @role <n>", "Pick random players from a role"),
    (".timer ,t <time>", "Set a countdown timer"),
    (".timestamp ,ts", "Generate a Discord timestamp"),
    (".time", "Show the time of a replied message"),
    (".gettag <link>", "Get mentioned users from a message"),
    (".ping", "Check the bot is online"),
    (".ding", "Dong!"),
    (".vgintro ,vgi", "Village Games intro (EN)"),
    (".vgintro_it ,vgii", "Village Games intro (IT)"),
]


class PlayerHelpView(View):
    def __init__(self, author_id: int):
        super().__init__(timeout=120)
        self.author_id = author_id
        self.message: discord.Message | None = None

    def _embed(self) -> discord.Embed:
        lines = [f"`{cmd}` · {desc}" for cmd, desc in _PLAYER_COMMANDS]
        embed = discord.Embed(
            title="🧭 Village Game — What can I do as a player?",
            description="\n".join(lines),
            color=0xff3fb9,
        )
        embed.set_footer(text="Prefix is . for all commands • see `.help` for the full list")
        return embed


class Other(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self._http_session = None
        self._tenor_media_cache = {}
        for _cmd in self.get_commands():
            if _cmd.name in ("opoke", "opat", "ohug", "oslap", "okill", "okiss", "odance", "owave"):
                _cmd.error(self._interaction_error)

    @commands.Cog.listener()
    async def on_command_error(self, ctx, error):
        """Suggest a correction when a misspelled command is attempted."""
        if not isinstance(error, commands.CommandNotFound) or ctx.author.bot:
            return
        suggestions = self._suggest_commands(ctx.invoked_with)
        if not suggestions:
            return
        prefix = ctx.prefix or "."
        if len(suggestions) == 1:
            await ctx.send(f"Did you mean **`{prefix}{suggestions[0]}`**?")
        else:
            listed = ", ".join(f"`{prefix}{name}`" for name in suggestions)
            await ctx.send(f"Did you mean one of: {listed}?")

    def _suggest_commands(self, attempted):
        """Fuzzy-match an attempted command against all known commands/aliases."""
        if not attempted:
            return []
        attempted_l = attempted.lower()
        candidates = {}
        for command in self.bot.walk_commands():
            for name in {command.name, *command.aliases}:
                candidates.setdefault(name.lower(), command.qualified_name)
        cutoff = 0.6 if len(attempted_l) > 4 else 0.75
        matches = difflib.get_close_matches(attempted_l, list(candidates.keys()), n=3, cutoff=cutoff)
        results = []
        for match in matches:
            if match == attempted_l:
                continue
            if match[0] != attempted_l[0]:
                ratio = difflib.SequenceMatcher(None, attempted_l, match).ratio()
                if ratio < 0.9:
                    continue
            display = candidates[match]
            if display not in results:
                results.append(display)
        return results

    @commands.command()
    async def who(self, ctx, channel: discord.TextChannel = None):
        """List all members in a channel grouped by role (Alive, Sponsor, Alt, Dead)."""
        guild_data = load_guild_data(ctx.guild.id)
        if guild_data:
            alive_role = discord.utils.get(ctx.guild.roles, name=guild_data.get("alive_role_name", ""))
            sponsor_role = discord.utils.get(ctx.guild.roles, name=guild_data.get("sponsor_role_name", ""))
            alt_role = discord.utils.get(ctx.guild.roles, name=guild_data.get("alt_role_name", ""))
            dead_role = discord.utils.get(ctx.guild.roles, name=guild_data.get("dead_role_name", ""))
            if channel:
                perms = channel.permissions_for(ctx.author)
                if not ctx.author.guild_permissions.administrator and not perms.read_messages:
                    await ctx.send("You don't have enough perms to use this command")
                    return
            else:
                channel = ctx.channel
            members = channel.members
            alive_list = []
            sponsor_list = []
            dead_list = []
            alt_list = []
            for member in members:
                permissions = channel.permissions_for(member)
                if permissions.send_messages:
                    if alive_role in member.roles:
                        alive_list.append(f"{member.mention} `[{member.display_name}]`")
                    if sponsor_role in member.roles:
                        sponsor_list.append(f"{member.mention} `[{member.display_name}]`")
                    if dead_role in member.roles:
                        dead_list.append(f"{member.mention} `[{member.display_name}]`")
                    if alt_role in member.roles:
                        alt_list.append(f"{member.mention} `[{member.display_name}]`")
            if alive_list or sponsor_list or alt_list or dead_list:
                alive_label = alive_role.name if alive_role else guild_data.get("alive_role_name") or "Alive"
                sponsor_label = sponsor_role.name if sponsor_role else guild_data.get("sponsor_role_name") or "Sponsor"
                dead_label = dead_role.name if dead_role else guild_data.get("dead_role_name") or "Dead"
                alt_label = alt_role.name if alt_role else guild_data.get("alt_role_name") or "Alt"
                pages = _embed_pages(
                    f"{channel.name} Members:",
                    "Village Game",
                    [
                        (f"{alive_label}:", alive_list),
                        (f"{sponsor_label}:", sponsor_list),
                        (f"{alt_label}:", alt_list),
                        (f"{dead_label}:", dead_list),
                    ],
                    0xff3fb9,
                )
                for i in range(0, len(pages), 10):
                    await ctx.send(embeds=pages[i:i + 10])
                return
            missing = [
                f"`{label}`" for role, label in (
                    (alive_role, guild_data.get("alive_role_name") or "Alive"),
                    (sponsor_role, guild_data.get("sponsor_role_name") or "Sponsor"),
                    (dead_role, guild_data.get("dead_role_name") or "Dead"),
                    (alt_role, guild_data.get("alt_role_name") or "Alt"),
                ) if role is None
            ]
            if missing:
                await ctx.send(
                    f"No players found in **{channel.name}**, and these configured roles do not exist "
                    f"in this server: {', '.join(missing)}. Check the role names in your setup."
                )
            else:
                await ctx.send(
                    f"No players found in **{channel.name}** — nobody here can send messages while "
                    "holding the Alive, Sponsor, Alt, or Dead role."
                )
        else:
            await ctx.send('Guild data not loaded.')

    @commands.command()
    async def where(self, ctx, channel: discord.TextChannel = None):
        """Show the current location (houses, PCs, public channels) of a player in an RC.

        Inside a Role Chat this is a self-check, so your own location needs no confirmation.
        Listing anyone else's location — via `.where #rc` or from outside a Role Chat — asks
        you to reply `yes` first, because it reveals other players' locations.
        """
        guild_data = load_guild_data(ctx.guild.id)
        if not guild_data:
            await ctx.send("Guild data not loaded")
            return

        spectator_role = discord.utils.get(ctx.guild.roles, name=guild_data.get("spectator_role_name", ""))
        alive_role = discord.utils.get(ctx.guild.roles, name=guild_data.get("alive_role_name", ""))
        dead_role = discord.utils.get(ctx.guild.roles, name=guild_data.get("dead_role_name", ""))
        alt_role = discord.utils.get(ctx.guild.roles, name=guild_data.get("alt_role_name", ""))
        sponsor_role = discord.utils.get(ctx.guild.roles, name=guild_data.get("sponsor_role_name", ""))
        rc_cat = discord.utils.get(ctx.guild.categories, name=guild_data.get("rc_category_name"))
        dead_rc = discord.utils.get(ctx.guild.categories, name=guild_data.get("dead_rc_category_name"))
        alt_cat = discord.utils.get(ctx.guild.categories, name=guild_data.get("alt_category_name"))

        is_admin = ctx.author.guild_permissions.administrator
        is_staff = is_admin or spectator_role in ctx.author.roles
        in_player_channel = ctx.channel.category in (rc_cat, dead_rc, alt_cat)

        category_houses = discord.utils.get(ctx.guild.categories, name=guild_data.get("houses_category_name", ""))
        privc_base = guild_data.get("privc_category_name", "") or ""
        publc_base = guild_data.get("publc_category_name", "") or ""
        category_pcs_list = category_family(ctx.guild.categories, privc_base)
        category_publc_list = category_family(ctx.guild.categories, publc_base)

        # Validate setup before choosing a branch, so a renamed role or category reports the
        # real problem instead of a misleading "not enough perms".
        player_roles = tuple(r for r in (alive_role, dead_role, alt_role, sponsor_role) if r is not None)
        # Sponsors may run .where, but they are staff/observer accounts rather than villagers,
        # so they are not listed as players in the results.
        listed_roles = tuple(r for r in (alive_role, dead_role, alt_role) if r is not None)
        if not player_roles:
            await ctx.send(
                "None of the configured player roles (Alive, Dead, Alt, Sponsor) exist in this "
                "server. Check the role names in your setup."
            )
            return
        if category_houses is None and not category_pcs_list and not category_publc_list:
            await ctx.send(
                "No house, private chat, or public channel category is configured in this server."
            )
            return

        if all(c is None for c in (rc_cat, dead_rc, alt_cat)):
            await ctx.send(
                "None of the configured player channel categories (RC, dead RC, Alt RC) exist in "
                "this server. Check the category names in your setup."
            )
            return

        self_check = False
        if channel is not None:
            # Staff-only, and only ever pointed at a Role Chat.
            if not is_staff:
                await ctx.send("You don't have enough perms to use this command")
                return
            if channel.category not in (rc_cat, dead_rc, alt_cat):
                await ctx.send(
                    f"{channel.mention} is not a Role Chat — `.where` only reports locations for "
                    "Role Chat channels."
                )
                return
            members = channel.members
        elif in_player_channel:
            # Inside a Role Chat this is a self-check only: your own location, nothing else.
            if any(r in ctx.author.roles for r in player_roles):
                members = [ctx.author]
                self_check = True
            elif is_admin:
                # Admins can still inspect the Role Chat they're standing in. That reveals other
                # players, so it goes through the `proceed` gate below like any other bulk share.
                members = ctx.channel.members
            else:
                await ctx.send(
                    "You don't hold a player role (Alive, Sponsor, Dead or Alt) in this server, "
                    "so I can't show your location."
                )
                return
        elif is_admin:
            # Outside a Role Chat this is admin-only, and still gated behind `proceed`.
            members = ctx.channel.members
        else:
            await ctx.send(
                "`.where` only works inside a Role Chat. Outside one it is admin-only, because it "
                "shares other players' locations."
            )
            return
        max_reports = 5
        results = []
        seen = set()
        for member in members:
            if member.id in seen:
                continue
            seen.add(member.id)
            # Sponsors are staff/observer accounts rather than villagers, so they are only ever
            # reported as a lone fallback (see the tier order below), never mixed into the
            # living-player listing.
            has_player_role = any(r in member.roles for r in listed_roles)
            is_sponsor = sponsor_role is not None and sponsor_role in member.roles
            if not has_player_role and not is_sponsor and member.id != ctx.author.id:
                continue
            houses_list = []
            if category_houses:
                for house in category_houses.channels:
                    permissions = house.permissions_for(member)
                    if permissions.send_messages:
                        houses_list.append(house.mention)
            pcs_list = []
            for cat_pc in category_pcs_list:
                for pc in cat_pc.channels:
                    permissions = pc.permissions_for(member)
                    if permissions.send_messages:
                        pcs_list.append(pc.mention)
            publc_list = []
            for cat_pub in category_publc_list:
                for pubc in cat_pub.channels:
                    permissions = pubc.permissions_for(member)
                    if permissions.send_messages:
                        publc_list.append(pubc.mention)
            groups = []
            if houses_list:
                groups.append(("🏠 Houses:", houses_list))
            if pcs_list:
                groups.append(("👤 Private Chats:", pcs_list))
            if publc_list:
                groups.append(("🏟️ Public Channels:", publc_list))
            if not groups:
                continue
            results.append((member, groups, (tuple(houses_list), tuple(pcs_list), tuple(publc_list))))

        # Report the first tier that has anyone in it: alive players, else a single sponsor,
        # else the dead, else alts. Sponsors are a fallback and only one is ever shown.
        def members_with(role):
            if role is None:
                return []
            return [r for r in results if role in r[0].roles]

        if self_check:
            selected = [(m, g, k) for m, g, k in results if m.id == ctx.author.id]
        else:
            selected = []
            for tier in (alive_role, sponsor_role, dead_role, alt_role):
                found = members_with(tier)
                if tier is sponsor_role and found:
                    found = found[:1]  # a single sponsor, however many exist
                if found:
                    selected = found
                    break

        # Players sharing an identical location get one combined embed instead of one each,
        # so a shared house/PC doesn't repeat the same channels four times over.
        grouped = {}
        order = []
        for member, member_groups, key in selected:
            if key not in grouped:
                grouped[key] = {"members": [], "groups": member_groups}
                order.append(key)
            grouped[key]["members"].append(member)

        total_players = sum(len(grouped[key]["members"]) for key in order)
        entries = []
        for key in order:
            grp = grouped[key]
            group_members = grp["members"]
            # Name, not mention: a mention renders as the user's profile card, which makes
            # the title unreadable in the embed list.
            title = f"{' & '.join(m.display_name for m in group_members)} Location:"
            entries.append((group_members, _embed_pages(title, "Village Game", grp["groups"], 0xff3fb9)))

        shown = entries[:max_reports]
        shown_players = sum(len(members) for members, _ in shown)
        omitted = max(0, total_players - shown_players)
        results = shown
        if not results:
            if self_check:
                await ctx.send(
                    "You are not currently in any house, private chat, or public channel you can see."
                )
            else:
                await ctx.send("None of the players in that channel have a location right now.")
            return

        # Confirmation is required whenever the result reaches outside the caller's own RC.
        # No gate: a bare `.where` inside a Role Chat (a player's self-check, or an admin
        # checking the RC they are standing in), and any result that is only the caller.
        # Gated: an explicit `.where #rc` — it reports on a *different* channel's players,
        # even when typed from inside an RC — and a bare `.where` outside a Role Chat.
        is_self_only = len(results) == 1 and results[0][0] == [ctx.author]
        if not is_self_only and (not in_player_channel or channel is not None):
            names = ", ".join(member.mention for group_members, _ in results for member in group_members)
            more = f" (+{omitted} more not shown)" if omitted else ""
            await ctx.send(
                f"⚠️ **This is sensitive** — it will show the current location of "
                f"**{shown_players}** player(s){more}: {names}\n"
                "Players only ever see their own location; viewing other players' locations "
                "needs this confirmation.\n"
                "Reply **yes** within 30 seconds to continue, or anything else to cancel."
            )

            def check(m):
                return m.author == ctx.author and m.channel == ctx.channel

            try:
                response = await self.bot.wait_for("message", timeout=30, check=check)
            except asyncio.TimeoutError:
                return await ctx.send("Timed out. No locations were shared.")
            if response.content.strip().lower() not in ("yes", "proceed"):
                return await ctx.send("Cancelled. No locations were shared.")

        embeds = []
        for _, pages in results:
            embeds.extend(pages)
        if omitted:
            # Folded into the last embed (not a field — that could exceed the 25-field cap)
            # so the command still answers in a single message.
            embeds[-1].description = f"_{omitted} more player(s) not shown (limit {max_reports})._"
        for chunk in _embed_chunks(embeds):
            await ctx.send(embeds=chunk)

    @commands.command(aliases=["hw", "wherewho", "whowhere"])
    async def housewho(self, ctx, target: discord.TextChannel = None):
        """Show your house and who is inside it."""
        guild_data = load_guild_data(ctx.guild.id)
        if not guild_data:
            await ctx.send("Guild data not loaded")
            return

        rc_cat = discord.utils.get(ctx.guild.categories, name=guild_data.get("rc_category_name"))
        dead_rc = discord.utils.get(ctx.guild.categories, name=guild_data.get("dead_rc_category_name"))
        alt_cat = discord.utils.get(ctx.guild.categories, name=guild_data.get("alt_category_name"))
        houses_category = discord.utils.get(ctx.guild.categories, name=guild_data.get("houses_category_name", ""))
        is_admin = ctx.author.guild_permissions.administrator

        in_player_channel = ctx.channel.category in (rc_cat, dead_rc, alt_cat) if ctx.channel and ctx.channel.category else False

        if not houses_category:
            await ctx.send("Houses category not found.")
            return

        if target is None:
            if not in_player_channel:
                await ctx.send("`.housewho` can only be used in Role Chat, Alt, or Dead RC channels.")
                return
            lookup_members = [m for m in ctx.channel.members if not m.bot]
            if not lookup_members:
                await ctx.send("No players found.")
                return
            member_houses = {}
            for member in lookup_members:
                house = self._housewho_house_of(houses_category, member)
                if house is not None:
                    member_houses[member.id] = house
            if not member_houses:
                await ctx.send("None of those players are currently in any house.")
                return
            house_to_members = {}
            for mid, house in member_houses.items():
                house_to_members.setdefault(house.id, {"house": house, "members": []})
            for member in lookup_members:
                if member.id in member_houses:
                    house_to_members[member_houses[member.id].id]["members"].append(member)
            for hid, data in house_to_members.items():
                await self._housewho_show_house(ctx, data["house"], guild_data)
            return

        if not is_admin:
            await ctx.send("You don't have enough perms to use this command")
            return

        if target.category in (rc_cat, dead_rc, alt_cat):
            lookup_members = [m for m in target.members if not m.bot]
            if not lookup_members:
                await ctx.send("No players found.")
                return
            member_houses = {}
            for member in lookup_members:
                house = self._housewho_house_of(houses_category, member)
                if house is not None:
                    member_houses[member.id] = house
            if not member_houses:
                await ctx.send("None of those players are currently in any house.")
                return
            house_to_members = {}
            for mid, house in member_houses.items():
                house_to_members.setdefault(house.id, {"house": house, "members": []})
            for member in lookup_members:
                if member.id in member_houses:
                    house_to_members[member_houses[member.id].id]["members"].append(member)
            names = ", ".join(m.display_name for h in house_to_members for m in house_to_members[h]["members"])
            await ctx.send(
                f"⚠️ **This is sensitive** — it will show the house and members for {names}.\n"
                "Reply **yes** within 30 seconds to continue, or anything else to cancel."
            )
            def check(m):
                return m.author == ctx.author and m.channel == ctx.channel
            try:
                response = await self.bot.wait_for("message", timeout=30, check=check)
            except asyncio.TimeoutError:
                return await ctx.send("Timed out.")
            if response.content.strip().lower() not in ("yes", "proceed"):
                return await ctx.send("Cancelled.")
            for hid, data in house_to_members.items():
                await self._housewho_show_house(ctx, data["house"], guild_data)
            return
        elif target.category == houses_category and isinstance(target, discord.TextChannel):
            await ctx.send(
                f"⚠️ **This is sensitive** — it will show all members in {target.mention}.\n"
                "Reply **yes** within 30 seconds to continue, or anything else to cancel."
            )
            def check(m):
                return m.author == ctx.author and m.channel == ctx.channel
            try:
                response = await self.bot.wait_for("message", timeout=30, check=check)
            except asyncio.TimeoutError:
                return await ctx.send("Timed out.")
            if response.content.strip().lower() not in ("yes", "proceed"):
                return await ctx.send("Cancelled.")
            return await self._housewho_show_house(ctx, target, guild_data)
        else:
            await ctx.send("Target must be a Role Chat, Alt, Dead RC, or a house channel.")
            return

    @staticmethod
    def _housewho_house_of(houses_category, member):
        """The house the player can send messages in right now (the same rule .trade and .give use)."""
        return next(
            (c for c in houses_category.channels
             if isinstance(c, discord.TextChannel) and c.permissions_for(member).send_messages),
            None,
        )

    @staticmethod
    def _housewho_residents(ctx, house):
        """Everyone who can send messages in this house, excluding bots."""
        return [m for m in ctx.guild.members if not m.bot and house.permissions_for(m).send_messages]

    async def _housewho_show_house(self, ctx, house_channel, guild_data, members=None):
        alive_role = discord.utils.get(ctx.guild.roles, name=guild_data.get("alive_role_name", ""))
        sponsor_role = discord.utils.get(ctx.guild.roles, name=guild_data.get("sponsor_role_name", ""))
        alt_role = discord.utils.get(ctx.guild.roles, name=guild_data.get("alt_role_name", ""))
        dead_role = discord.utils.get(ctx.guild.roles, name=guild_data.get("dead_role_name", ""))

        if members is None:
            members = self._housewho_residents(ctx, house_channel)

        alive_list = []
        sponsor_list = []
        dead_list = []
        alt_list = []
        for member in members:
            if alive_role in member.roles:
                alive_list.append(f"`[{member.display_name}]`")
            elif sponsor_role in member.roles:
                sponsor_list.append(f"`[{member.display_name}]`")
            elif dead_role in member.roles:
                dead_list.append(f"`[{member.display_name}]`")
            elif alt_role in member.roles:
                alt_list.append(f"`[{member.display_name}]`")

        alive_label = alive_role.name if alive_role else guild_data.get("alive_role_name") or "Alive"
        sponsor_label = sponsor_role.name if sponsor_role else guild_data.get("sponsor_role_name") or "Sponsor"
        dead_label = dead_role.name if dead_role else guild_data.get("dead_role_name") or "Dead"
        alt_label = alt_role.name if alt_role else guild_data.get("alt_role_name") or "Alt"

        pages = _embed_pages(
            f"{house_channel.name} — Members:",
            "Village Game",
            [
                (f"{alive_label}:", alive_list),
                (f"{sponsor_label}:", sponsor_list),
                (f"{alt_label}:", alt_list),
                (f"{dead_label}:", dead_list),
            ],
            0xff3fb9,
        )
        for i in range(0, len(pages), 10):
            await ctx.send(embeds=pages[i:i + 10])

    @commands.command()
    async def loc(self, ctx):
        """Show all houses and their current occupants."""
        guild_data = load_guild_data(ctx.guild.id)
        if not guild_data:
            await ctx.send("Guild data not loaded.")
            return
        if not ctx.author.guild_permissions.administrator:
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
            everyone_perms = channel.permissions_for(ctx.guild.default_role)
            if everyone_perms.read_messages:
                content_empty += f"{channel.name}\n\n"
                continue
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
                content_empty += f"{channel.name}\n\n"
        embed.add_field(name="Non Empty Houses:", value=content_nempty, inline=False)
        embed.add_field(name="Empty Houses:", value=content_empty, inline=False)
        await ctx.send(embed=embed)

    @commands.command(aliases=["t"])
    async def timer(self, ctx, tempo: str, tag: str = None, channel: discord.TextChannel = None):
        """Set a countdown timer with optional tag and target channel."""
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
        """Randomly select members from a specified role."""
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
        """Send a message to specified channels or all RoleChats as narration."""
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

    async def _send_narration(self, ctx, text, ping_roles=True, pin=True):
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

        sent_messages = []
        try:
            for i, e in enumerate(embeds):
                content = " ".join(ping_parts) if ping_parts and i == 0 else None
                msg = await ctx.send(content=content, embed=e)
                sent_messages.append(msg)
        except discord.Forbidden:
            await ctx.send("I don't have permission to send embeds here.")
            return
        except Exception as e:
            print(f"[Narration] Error sending embed: {e}")
            await ctx.send("An error occurred while sending the narration.")
            return

        if sent_messages and pin:
            try:
                await sent_messages[0].pin()
                await asyncio.sleep(0.5)
                async for recent in ctx.channel.history(limit=3, after=sent_messages[0].created_at):
                    if recent.type == discord.MessageType.pins_add:
                        await recent.delete()
            except (discord.Forbidden, discord.HTTPException):
                pass

        try:
            await ctx.message.delete(delay=3)
        except (discord.Forbidden, discord.HTTPException):
            pass

        prefix = ctx.prefix if isinstance(ctx.prefix, str) else (ctx.clean_prefix if hasattr(ctx, 'clean_prefix') else '.')
        original_text = ctx.message.content[len(prefix) + len(ctx.invoked_with or ""):].strip()

        try:
            log_dir = os.path.join(DATA_DIR, "narration_logs")
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

    @commands.command(name="np")
    async def np_narration(self, ctx, *, text: str = None):
        """Send a narration embed without pinning it (admin only). Pings @Alive and @Sponsor."""
        if not ctx.author.guild_permissions.administrator:
            return await ctx.send("You don't have enough perms to use this command")
        if text is None:
            embed = discord.Embed(
                title="📖 Narration (no pin)",
                description="Usage: `.np <text>`\nSend a storybook-style narration embed without pinning it (admin only).\nPings @Alive and @Sponsor.\n\nSame as `.n` but the message is not pinned.",
                color=0xff3fb9
            )
            embed.add_field(name="Example", value="`.np The detective quietly watched from the shadows.`", inline=False)
            return await ctx.send(embed=embed)
        await self._send_narration(ctx, text, ping_roles=True, pin=False)

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
        """Delete the current channel after confirmation (admin only)."""
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

    @commands.command(aliases=["delcategory", "delcat"])
    async def deletecategory(self, ctx, *, category: str = None):
        """Delete a category and all of its channels (admin only).

        Usage: `.deletecategory [category name or ID]`
        Without an argument it deletes the category this channel is in.
        """
        if not ctx.author.guild_permissions.administrator:
            return await ctx.send("You don't have enough perms to use this command")

        if category is None:
            target = ctx.channel.category
            if target is None:
                return await ctx.send(
                    "This channel doesn't have a category. "
                    "Give me a category name or ID instead: `.deletecategory ROLES`"
                )
        else:
            target, error = find_category(ctx.guild, category)
            if error:
                return await ctx.send(error)

        channel_count = len(target.channels)
        view = ConfirmDeleteView(ctx)
        embed = discord.Embed(
            title="⚠️ Delete category",
            description=(
                f"Are you sure you want to delete **{target.name}** and its "
                f"**{channel_count}** channel(s)?\nThis can't be undone."
            ),
            color=0xff0000,
        )
        msg = await ctx.send(embed=embed, view=view)
        view.message = msg
        await view.wait()
        if not view.confirmed:
            return

        failed = []
        for channel in list(target.channels):
            try:
                await channel.delete()
            except (discord.Forbidden, discord.HTTPException):
                failed.append(channel.name)
        try:
            await target.delete()
        except (discord.Forbidden, discord.HTTPException):
            failed.append(f"category “{target.name}”")

        if failed:
            try:
                await ctx.send(
                    "⚠️ Couldn't delete: " + ", ".join(f"`{name}`" for name in failed)
                )
            except (discord.Forbidden, discord.HTTPException):
                pass

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
        """Show the sent time of a replied-to message as a Discord timestamp."""
        if ctx.message.reference:
            replied_message = await ctx.channel.fetch_message(ctx.message.reference.message_id)
            timestamp = replied_message.created_at
            discord_timestamp = f"<t:{int(timestamp.timestamp())}:T>"
            await ctx.send(f"The message was sent at: {discord_timestamp}")
        else:
            await ctx.send("You need to reply to a message to use this command.")

    @commands.command()
    async def gettag(self, ctx, *, arg=None):
        """Extract mentioned users from a replied-to message or message link."""
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
        mentions = list(msg.mentions)
        # Discord excludes mentions inside embeds from Message.mentions, so scan
        # embed text (description, fields, author, footer) for <@id> patterns.
        embed_parts = []
        for embed in msg.embeds:
            if embed.description:
                embed_parts.append(embed.description)
            if embed.author and embed.author.name:
                embed_parts.append(embed.author.name)
            for field in embed.fields:
                embed_parts.append(field.name)
                embed_parts.append(field.value)
            if embed.footer and embed.footer.text:
                embed_parts.append(embed.footer.text)
        if embed_parts:
            seen_ids = {user.id for user in mentions}
            for uid in re.findall(r'<@!?(\d+)>', '\n'.join(embed_parts)):
                uid = int(uid)
                if uid in seen_ids:
                    continue
                seen_ids.add(uid)
                user = ctx.guild.get_member(uid) or self.bot.get_user(uid)
                if user is None:
                    try:
                        user = await self.bot.fetch_user(uid)
                    except discord.HTTPException:
                        continue
                mentions.append(user)
        if not mentions:
            return await ctx.reply("No user mentions found in that message.", mention_author=False)
        mention_list = ' '.join(user.mention for user in mentions)
        await ctx.send(mention_list, allowed_mentions=AllowedMentions(users=False, roles=False))
        
    @staticmethod
    def _pin_section(index, message, total):
        """Render one pinned message as a labelled block for the merged embed."""
        author = getattr(message, "author", None)
        name = getattr(author, "display_name", None) or getattr(author, "name", None) or "Unknown"
        created = getattr(message, "created_at", None)
        stamp = f" · <t:{int(created.timestamp())}:f>" if created else ""
        if total > 1:
            heading = f"**{index}. {name}**{stamp}"
        else:
            heading = f"**{name}**{stamp}"
        body = (getattr(message, "content", "") or "").strip() or "*[No content]*"
        attachments = getattr(message, "attachments", None) or []
        links = [a.url for a in attachments if getattr(a, "url", None)]
        if links:
            body = f"{body}\n{' '.join(links)}"
        return f"{heading}\n{body}"

    @commands.command(name="firstpin")
    async def firstpin(self, ctx, count: int = 1, channel: discord.TextChannel = None):
        """Show the oldest pinned message(s) in a channel merged into one embed.

        Pass a number to merge the first N pinned messages, e.g. `.firstpin 3`.
        The embed grows with the merged length and is truncated to fit Discord's limits.
        """
        if count < 1 or count > 10:
            await ctx.send("Please choose a number between 1 and 10.")
            return
        guild_data = load_guild_data(ctx.guild.id)
        if not guild_data:
            await ctx.send("Guild data not loaded")
            return
        if channel is None:
            channel = ctx.channel
        if not ctx.author.guild_permissions.administrator:
            role_names = (
                guild_data.get("alive_role_name"),
                guild_data.get("dead_role_name"),
                guild_data.get("alt_role_name"),
            )
            player_candidates = []
            for member in channel.members:
                if member.bot or member.guild_permissions.administrator:
                    continue
                if not any(
                    role_name and discord.utils.get(ctx.guild.roles, name=role_name) in member.roles
                    for role_name in role_names
                ):
                    continue
                if channel.permissions_for(member).send_messages:
                    player_candidates.append(member)
            if len(player_candidates) != 1 or player_candidates[0].id != ctx.author.id:
                await ctx.send("You can only view your own Role Chat role.")
                return
        pins = await channel.pins()
        if not pins:
            await ctx.send("No pinned messages were found in that channel.")
            return
        # channel.pins() returns newest-pinned first; show the oldest pins in
        # chronological (oldest-first) order so .firstpin reads naturally.
        selected = list(reversed(pins[-count:]))
        title = "First Pinned Message" if len(selected) == 1 else f"First {len(selected)} Pinned Messages"
        separator = "\n\n" + "─" * 20 + "\n\n"
        sections = [self._pin_section(index, message, len(selected)) for index, message in enumerate(selected, start=1)]
        description = _truncate(separator.join(sections), MAX_EMBED_DESC)
        footer = "Village Game"
        links = "\n".join(
            f"[{index}. Jump to the message!]({message.jump_url})"
            for index, message in enumerate(selected, start=1)
        )
        # Keep the whole embed under Discord's 6000-char budget, footer included.
        budget = MAX_EMBED_CHARS - len(title) - len(description) - len(footer)
        if len(links) > budget:
            links = _truncate(links, max(budget, 0))
        embed = discord.Embed(title=title, description=description, color=0xff3fb9, timestamp=datetime.now())
        if links:
            embed.add_field(name=" ", value=links[:MAX_FIELD_VALUE], inline=False)
        embed.set_footer(text=footer)
        await ctx.send(embed=embed)

            
    @commands.command(name="firstmsg")
    async def firstmsg(self, ctx, channel: discord.TextChannel = None):
        """Show the first message in a channel. Optional #channel requires admin."""
        if channel is None:
            channel = ctx.channel
        elif not ctx.author.guild_permissions.administrator:
            await ctx.send("❌ Only server admins can specify a channel.")
            return

        first = None
        async for message in channel.history(limit=1, oldest_first=True):
            first = message
            break
        if first is None:
            await ctx.send("No messages were found in that channel.")
            return

        embed = discord.Embed(
            title="First Message",
            description=first.content or "*[No content]*",
            color=0xff3fb9,
            timestamp=datetime.now(),
        )
        embed.add_field(name="Author", value=f"<@{first.author.id}>", inline=False)
        embed.add_field(name=" ", value=f"[Jump to the message!]({first.jump_url})", inline=False)
        embed.set_footer(text="Village Game")
        await ctx.send(embed=embed)

    @commands.command()
    async def ping(self, ctx):
        """Check if the bot is online and responsive."""
        await ctx.send('Pong')

    @commands.command()
    async def ding(self, ctx):
        """Fun easter egg command that replies with "Dong!"."""
        await ctx.send("Dong! ||MF||")

    @commands.command()
    async def avatar(self, ctx, member: discord.Member = None):
        """Show your own avatar, or another member's. Usage: .avatar [@member]"""
        target = member or ctx.author
        colour = getattr(target, "color", None)
        embed = discord.Embed(
            title=f"{target.display_name}'s Avatar",
            color=colour.value if colour is not None and colour.value else 0xff3fb9,
        )
        embed.set_image(url=target.display_avatar.url)
        embed.set_footer(
            text=f"Requested by {ctx.author.display_name}",
            icon_url=ctx.author.display_avatar.url,
        )
        await ctx.send(embed=embed)

    @commands.command(aliases=["banner"])
    async def line(self, ctx, *args):
        """Draw a clean banner line to separate text. Admin only.

        Usage:
          .line                 → single divider line
          .line <n>             → stack n divider lines (bigger gap)
          .line <text>          → single line with a centered title
          .line <n> <text>      → n divider lines with the title in the middle
                                  (odd n: title on the middle line;
                                   even n: title centered in the middle gap)
        """
        if not ctx.author.guild_permissions.administrator:
            await ctx.send("❌ Only server admins can use this command.")
            return

        count = 1
        title = None
        if args:
            first = args[0]
            if first.isdigit():
                count = min(int(first), 15)
                rest = args[1:]
            else:
                rest = args
            if rest:
                title = " ".join(rest).strip()
        if count < 1:
            count = 1

        full = "━" * 36
        flanked = f"━━ ✦ **{title}** ✦ ━━" if title else full
        if title:
            rows = [full] * count
            if count % 2 == 1:
                rows[count // 2] = flanked
            else:
                rows.insert(count // 2, flanked)
        else:
            rows = [full] * count
        message = "\n".join(rows)
        try:
            await ctx.message.delete()
        except (discord.Forbidden, discord.NotFound):
            pass
        await ctx.send(message)

    @commands.command()
    async def dice(self, ctx, *args):
        """Roll a random number (1-N) or pick randomly from given options."""
        def embed(text):
            # Replies go in an embed because mentions inside embeds never ping
            # (@everyone, @here, and role mentions are safe there).
            return discord.Embed(description=text, color=0xff3fb9)
        if not args:
            await ctx.send(embed=embed("Usage: `.dice <number>` to roll 1-N, or `.dice <option1> <option2> ...` to pick randomly."))
            return
        if len(args) == 1:
            try:
                n = int(args[0])
            except ValueError:
                await ctx.send(embed=embed(f"`{args[0]}` is not a valid number. Usage: `.dice <number>` or `.dice <opt1>, <opt2>, ...`"))
                return
            if n < 1:
                await ctx.send(embed=embed("Number must be 1 or higher. Usage: `.dice <number>`"))
                return
            result = random.randint(1, n)
            await ctx.send(embed=embed(f"🎲 You rolled a **{result}** (1–{n})!"))
        else:
            raw = " ".join(args)
            if "," in raw:
                options = [o.strip() for o in raw.split(",") if o.strip()]
            else:
                options = list(args)
            if not options:
                await ctx.send(embed=embed("No valid options provided."))
                return
            choice = random.choice(options)
            await ctx.send(embed=embed(f"🎲 I picked: **{choice}**"))

    @commands.command()
    async def opoke(self, ctx, target: discord.Member = None):
        """Poke someone with an anime GIF."""
        await self.perform_interaction(ctx, target, "poke")

    @commands.command()
    async def opat(self, ctx, target: discord.Member = None):
        """Pat someone with an anime GIF."""
        await self.perform_interaction(ctx, target, "pat")

    @commands.command()
    async def ohug(self, ctx, target: discord.Member = None):
        """Hug someone with an anime GIF."""
        await self.perform_interaction(ctx, target, "hug")

    @commands.command()
    async def oslap(self, ctx, target: discord.Member = None):
        """Slap someone with an anime GIF."""
        await self.perform_interaction(ctx, target, "slap")

    @commands.command()
    async def okill(self, ctx, target: discord.Member = None):
        """Kill someone with an anime GIF."""
        await self.perform_interaction(ctx, target, "kill")

    @commands.command()
    async def okiss(self, ctx, target: discord.Member = None):
        """Kiss someone with an anime GIF."""
        await self.perform_interaction(ctx, target, "kiss")

    @commands.command()
    async def odance(self, ctx, target: discord.Member = None):
        """Dance with someone with an anime GIF."""
        await self.perform_interaction(ctx, target, "dance")

    @commands.command()
    async def owave(self, ctx, target: discord.Member = None):
        """Wave at someone with an anime GIF."""
        await self.perform_interaction(ctx, target, "wave")

    async def perform_interaction(self, ctx, target, interaction_type):
        """Shared handler for the .o interaction commands (poke, pat, hug, slap, kill)."""
        actor = ctx.author
        if target is None:
            await ctx.send(f"❌ You need to mention someone. Example: `.{ctx.invoked_with} @user`")
            return
        if target.bot:
            await ctx.send("❌ You can't do that to a bot!")
            return
        if target.id == actor.id:
            await ctx.send("❌ You can't do that to yourself!")
            return

        lines = INTERACTION_LINES.get(interaction_type) or [f"{{user}} {interaction_type}s {{target}}"]
        text_line = random.choice(lines).format(user=actor.mention, target=target.mention)
        pool = INTERACTION_GIFS.get(interaction_type) or []

        gif = None
        if pool:
            gif = await _choose_interaction_gif(pool, self._gif_is_valid)
            if gif is None:
                gif = random.choice(pool)

        content = text_line
        media = None
        if gif:
            media = await self._resolve_tenor_media(gif)
            if media is None:
                content = f"{text_line}\n{gif}"

        sent_text = False
        try:
            if media:
                await ctx.send(text_line)
                sent_text = True
                await ctx.send(media)
            else:
                await ctx.send(content)
                sent_text = True
        except (discord.HTTPException, discord.Forbidden):
            if not sent_text:
                await ctx.send(text_line)

    async def _gif_is_valid(self, url):
        """Check that a GIF URL is reachable and points at an image or image-ready page."""
        try:
            session = self._get_http_session()
            async with session.head(url, timeout=aiohttp.ClientTimeout(total=5), allow_redirects=True) as resp:
                ct = resp.headers.get("Content-Type", "").lower()
                if resp.status == 200 and ("image" in ct or "text/html" in ct):
                    return True
        except (aiohttp.ClientError, asyncio.TimeoutError):
            pass
        return False

    async def _resolve_tenor_media(self, url):
        """Resolve a tenor.com/view link to its direct media URL (cached)."""
        if url in self._tenor_media_cache:
            return self._tenor_media_cache[url]
        media = None
        page = ""
        try:
            session = self._get_http_session()
            async with session.get(
                url,
                timeout=aiohttp.ClientTimeout(total=8),
                allow_redirects=True,
                headers={"User-Agent": "Mozilla/5.0"},
            ) as resp:
                if resp.status == 200:
                    page = await resp.text()
            img = None
            vid = None
            mi = re.search(r'property="og:image"\s+content="([^"]+)"', page)
            if not mi:
                mi = re.search(r'content="([^"]+)"\s+property="og:image"', page)
            if mi:
                img = self._normalize_tenor_media(html.unescape(mi.group(1)))
            mv = re.search(r'property="og:video:secure_url"\s+content="([^"]+)"', page)
            if mv:
                vid = self._normalize_tenor_media(html.unescape(mv.group(1)))
            if img and img.lower().endswith(".gif"):
                media = img
            else:
                media = vid or img
        except (aiohttp.ClientError, asyncio.TimeoutError):
            media = None
        self._tenor_media_cache[url] = media
        return media

    @staticmethod
    def _normalize_tenor_media(media):
        """Rewrite media1.tenor.com/m/KEY/name.gif into the fetchable media.tenor.com/KEY/name.gif."""
        m = re.search(r'^https?://media\d?\.tenor\.com/[^/]*/([A-Za-z0-9_-]+/[^/?#"]+)$', media)
        return f"https://media.tenor.com/{m.group(1)}" if m else media

    def _get_http_session(self):
        if self._http_session is None or self._http_session.closed:
            self._http_session = aiohttp.ClientSession()
        return self._http_session

    async def _interaction_error(self, ctx, error):
        if isinstance(error, commands.BadArgument):
            await ctx.send("❌ That user wasn't found. Mention someone like `.{0} @user`.".format(ctx.invoked_with or "o"))
        elif isinstance(error, commands.MissingRequiredArgument):
            await ctx.send("❌ You need to mention someone. Example: `.{0} @user`.".format(ctx.invoked_with or "o"))

    @commands.command()
    async def goat(self, ctx):
        """🐐"""
        if ctx.author.id == 388776401668538368 or ctx.author.id == 450772749829537793:
            message = await ctx.send('# 🚨 ATTENTION EVERYONE 🚨\nPlease pause your regularly scheduled mediocrity.\nWe’re here to honor the one they tried to contain—but never could.\n\n💥🔥 THE UNDISPUTED LEGEND 🔥💥\n🎖️ MVP of MVPs\n🏆 Winner of Winners\n📜 So decorated, the awards had to be printed in landscape mode\n🥇 Made Heartside rewrite its policy to fit all his wins\n👑 The reason "balance" nerfs exist\n\n# GALAMT — THE ABSOLUTE GOAT\n\nToo powerful to play as a contestant—now only allowed as a sponsor. Because Some OS dont Like him \nWhy? Because every time he plays, the game breaks.\nOverseers are forced to nerf him constantly, or the meta collapses.\n\nHe won 2 times as the evil team with just a 1% chance of victory.\nStatistically impossible.\nGalamt just called it "a Tuesday."\n\n🕯️ Founder of ECG – Evil Cult Graveyard\nIt started as a meme cult during a social deduction match…\nAnd somehow, it’s still active.\nHe didn’t plan to make history—history followed him.\n\nThat look?\n✔️ “I didn’t ask for this power.”\n✔️ “I logged in for fun and broke the leaderboard.”\n✔️ “This isn’t a bug. It’s legacy.”\n\n**#Galamt**\n**#ECG**\n**#TooPowerful**\n**#SponsorOnly**\n**#LionOfTheMeta**')
            await message.delete(delay=60)

    @commands.command()
    async def help2(self, ctx, category: str = None):
        """Show additional command categories."""
        if category is not None:
            category = category.lower()
            extra_categories = {
                "location": self.help_location,
                "dashboard": self.help_dashboard,
                "gamemanager": self.help_gamemanager,
                "library": self.help_library,
                "games": self.help_games,
                "auction": self.help_auction,
                "birthdays": self.help_birthdays,
                "calendar": self.help_calendar,
                "sticky": self.help_sticky,
                "sendrole": self.help_sendrole,
                "download": self.help_download,
            }
            if category in extra_categories:
                self._in_help2 = True
                await extra_categories[category](ctx)
                return
            if category in HELP_CATEGORIES:
                await ctx.send(f"`{category}` is a `.help` category → use `.help {category}`")
                return
        self._in_help2 = True
        embed = discord.Embed(title="📂 Extended Command Categories", color=0xff3fb9)
        embed.add_field(name="📍 - Location", value="18 Commands\n`.help2 location`", inline=True)
        embed.add_field(name="🎮 - Dashboard & Info", value="17 Commands\n`.help2 dashboard`", inline=True)
        embed.add_field(name="🎲 - Game Manager", value="4 Commands\n`.help2 gamemanager`", inline=True)
        embed.add_field(name="📚 - Library & Stats", value="21 Commands\n`.help2 library`", inline=True)
        embed.add_field(name="⚔️ - Games (Aux, Senet, Soldiers)", value="19 Commands\n`.help2 games`", inline=True)
        embed.add_field(name="🔨 - Blind Auction", value="8 Commands\n`.help2 auction`", inline=True)
        embed.add_field(name="🎂 - Birthdays", value="6 Commands\n`.help2 birthdays`", inline=True)
        embed.add_field(name="📅 - Calendar & Intro", value="4 Commands\n`.help2 calendar`", inline=True)
        embed.add_field(name="📌 - Sticky", value="5 Commands\n`.help2 sticky`", inline=True)
        embed.add_field(name="↪ - Send Role", value="3 Commands\n`.help2 sendrole`", inline=True)
        embed.add_field(name="⬇️ - Downloads", value="4 Commands\n`.help2 download`", inline=True)
        embed.set_footer(text="Village Game • Use `.help2 {category}` for details • `.sh <kw>` to search commands")
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

        groups = []
        current_cat = None
        lines = []
        for cmd, desc, cat in matches:
            if cat != current_cat:
                if lines:
                    groups.append((f"📁 {current_cat}", lines))
                current_cat = cat
                lines = []
            lines.append(f"**`{cmd}`** ─ {desc}")
        if lines:
            groups.append((f"📁 {current_cat}", lines))

        pages = _embed_pages(
            f"🔍 Search results for `{keyword}`",
            "Village Game • Use `.help <category>` for the full category",
            groups,
            0xff3fb9,
        )
        pages[0].description = f"Found **{len(matches)}** matching command{'s' if len(matches) != 1 else ''}"
        for page in pages:
            await ctx.send(embed=page)

    @commands.command(name="fmbot")
    async def fmbot(self, ctx):
        """Show all .fmbot (Last.fm) commands organized by category."""
        view = FMBotView(author_id=ctx.author.id)
        msg = await ctx.send(embed=view._embed(), view=view)
        view.message = msg

    @commands.command(name="phelp", aliases=["playerhelp"])
    async def phelp(self, ctx):
        """Show commands regular players can use."""
        view = PlayerHelpView(author_id=ctx.author.id)
        msg = await ctx.send(embed=view._embed(), view=view)
        view.message = msg

    @commands.command()
    async def help(self, ctx, category: str = None):
        """Show the help homepage, or the commands for one category."""
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
                "utility": self.help_utility,
                "other": self.help_other,
                "meetupmatrix": self.help_meetupmatrix,
                "economy": self.help_economy,
                "botc": self.help_botc,
                "surveillance": self.help_surveillance,
                "analytics": self.help_analytics,
                "status": self.help_status,
            }
            if category in categories:
                await categories[category](ctx)
            elif category in HELP2_CATEGORIES:
                await ctx.send(f"`{category}` is a `.help2` category → use `.help2 {category}`")
            else:
                await ctx.send(f"{category} is not a valid category")

    async def send_help_page(self, ctx, embed, _help_method=None, options=None):
        if options is None:
            in_help2 = getattr(self, '_in_help2', False)
            if in_help2:
                options = [
                    discord.SelectOption(label="📍 - Location", value="location", description="Get all 'Location' commands"),
                    discord.SelectOption(label="🎮 - Dashboard & Info", value="dashboard", description="Get all 'Dashboard & OS Info' commands"),
                    discord.SelectOption(label="🎲 - Game Manager", value="gamemanager", description="Get all 'Game Manager' commands"),
                    discord.SelectOption(label="📚 - Library & Stats", value="library", description="Get all 'Library & Stats' commands"),
                    discord.SelectOption(label="⚔️ - Games (Aux, Senet, Soldiers)", value="games", description="Get all 'Games' commands"),
                    discord.SelectOption(label="🔨 - Blind Auction", value="auction", description="Get all 'Blind Auction' commands"),
                    discord.SelectOption(label="🎂 - Birthdays", value="birthdays", description="Get all 'Birthday' commands"),
                    discord.SelectOption(label="📅 - Calendar & Intro", value="calendar", description="Get all 'Calendar & Intro' commands"),
                    discord.SelectOption(label="📌 - Sticky", value="sticky", description="Get all 'Sticky' commands"),
                    discord.SelectOption(label="↪ - Send Role", value="sendrole", description="Get all 'Send Role' commands"),
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
                    discord.SelectOption(label="⚙️ - Utility", value="utility", description="Get all 'Utility' commands"),
                    discord.SelectOption(label="👽 - Other", value="other", description="Get all 'Other' commands"),
                    discord.SelectOption(label="🐦 - BOTC", value="botc", description="Get all 'Blood on the Clocktower' commands"),
                    discord.SelectOption(label="🛡 - Status", value="status", description="Get all 'Status' commands"),
                    discord.SelectOption(label="💰 - Economy", value="economy", description="Get all 'Economy' commands"),
                    discord.SelectOption(label="📊 - Meetings & Meetup Matrix", value="meetupmatrix", description="Get all 'Meetings & Meetup Matrix' commands"),
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
        embedh.add_field(name="👟 - Moving", value="13 Commands\n`.help moving`", inline=True)
        embedh.add_field(name="🏡 - Home", value="12 Commands\n`.help home`", inline=True)
        embedh.add_field(name="🔓 - Houses and PCs handling", value="16 Commands\n`.help handling`", inline=True)
        embedh.add_field(name="📜 - Infos", value="4 Commands\n`.help infos`", inline=True)
        embedh.add_field(name="🎟️ - Presets", value="3 Commands\n`.help presets`", inline=True)
        embedh.add_field(name="🗳️ - Voting", value="7 Commands\n`.help voting`", inline=True)
        embedh.add_field(name="👉 - Nominations", value="10 Commands\n`.help nominations`", inline=True)
        embedh.add_field(name="📄 - Lists", value="9 Commands\n`.help lists`", inline=True)
        embedh.add_field(name="⚙️ - Utility", value="21 Commands\n`.help utility`", inline=True)
        embedh.add_field(name="👽 - Other", value="42 Commands\n`.help other`", inline=True)
        embedh.add_field(name="🐦 - Blood on the Clocktower", value="All Commands\n`.help botc`", inline=True)
        embedh.add_field(name="🛡 - Status", value="3 Commands\n`.help status`", inline=True)
        embedh.add_field(name="💰 - Economy", value="25 Commands\n`.help economy`", inline=True)
        embedh.add_field(name="📊 - Meetings & Meetup Matrix", value="21 Commands\n`.help meetupmatrix`", inline=True)
        embedh.set_footer(text="Village Game • Use `.help {category}` for details • `.sh <kw>` to search commands")
        await self.send_help_page(ctx, embedh, self.help_homepage)

    async def help_setup(self, ctx):
        embeds = discord.Embed(title="🏗️ - Setup commands", description="23 Commands", color=0xff3fb9)
        embeds.add_field(name="Core Setup", value=(
            "**`.setup <houses> <rcs>`** ─ Setup roles, channels & categories\n"
            "**`.roleset <key> @role`** ─ Assign a role for the bot\n"
            "**`.channelset <key> #ch`** ─ Assign a channel (mention, ID or name)\n"
            "**`.addch <text>`** ─ Append text to the current channel name (admin)\n"
            "**`.addch rename <name> [#ch]`** ─ Fully rename a channel (admin)\n"
            "**`.rename <name> [#ch]`** ─ Rename a channel (admin)\n"
            "**`.setlogserver <channel_id>`** ─ Set the logging server for role package archives (admin)\n"
            "**`.categoryset <key> <name>`** ─ Assign a category\n"
            "━━━━━━━━━━━━━━━━\n"
            "**`.houseprefix <pfx>`** ─ Set house name prefix\n"
            "**`.knockduration <sec>`** ─ Set knock timeout duration\n"
            "**`.maxpinh <num>`** ─ Max players per house\n"
            "**`.refuseresponse 1/2/3`** ─ Knock refuse: 1=show players, 2=show count, 3=no info\n"
            "━━━━━━━━━━━━━━━━\n"
            "**`.settings`** ─ View current settings\n"
            "**`.resetdb`** ─ Reset all setup\n"
            "**`.stealemoji <emoji>`** ─ Copy a custom emoji (animated/static) from another server"
        ), inline=False)
        embeds.add_field(name="`.channelset` keys", value=(
            "`daydiscussion` `megaphone` `lynchsession1` `lynchsession2` `lynchsession3`\n"
            "`lynchsession4` `lynchsession5` `lynchsession6` `leaderelection` `leaderelection2`\n"
            "`votecount` `logchannel` `actionslogchannel` `announcements` `map`\n"
            "`whisperlogs` `editdellogs` `joinleavelogs` `narrationlog`\n"
            "━━━━━━━━━━━━━━━━\n"
            "↳ `lynchsession1-6` and `leaderelection`/`leaderelection2` also store the channel\n"
            "ID, so you can rename them freely. The other keys are matched by name — re-run\n"
            "`.channelset` if you rename those channels.\n"
            "Lynch sessions run 1 to 6. Sessions 3-6 are optional extra voting slots.\n"
            "`leaderelection2` is optional and is **not** created by `.setup` — assign an\n"
            "existing channel with `.channelset leaderelection2` to enable it.\n"
            "━━━━━━━━━━━━━━━━\n"
            "The channel is matched by mention, ID, exact name, or a unique partial/close\n"
            "name — emoji, punctuation and case are ignored (e.g. `vote count` → `📊│vote-count`)."
        ), inline=False)
        embeds.add_field(name="Toggles & Flags", value=(
            "**`.showwhispersender`** ─ Show/hide whisper sender\n"
            "**`.ajifempty`** ─ Auto-join if house is empty\n"
            "**`.ajknockexpire`** ─ Auto-join when knock expires\n"
            "**`.deadcount`** ─ Deads count for Auto-Join/MaxPlayers\n"
            "**`.altcount`** ─ Alts count for Auto-Join/MaxPlayers\n"
            "━━━━━━━━━━━━━━━━\n"
            "**`.showdeadsonrefuse`** ─ Show deads on knock refuse\n"
            "**`.showaltsonrefuse`** ─ Show alts on knock refuse\n"
            "**`.candeadsinteract`** ─ Deads can open/refuse\n"
            "**`.canaltsinteract`** ─ Alts can open/refuse\n"
            "**`.autopincorpse`** ─ Auto pin corpse messages in houses"
        ), inline=False)
        embeds.add_field(name="Daily Times", value=(
            "**`.settime <event>`** ─ Set daily game time via dropdowns\n"
            "  Events: `dayend` • `lynchend` • `presetend`\n"
            "**`.times`** ─ Show all configured daily times & next occurrence"
        ), inline=False)
        embeds.add_field(name="Abbreviations", value=(
            "**RC** = RoleChat (player's private channel)  •  **PC** = Private Chat (extra channel)\n"
            "**VB** = Visit Block  •  **OS** = Overseer (game master)"
        ), inline=False)
        embeds.set_footer(text="Village Game • All listed commands need the prefix `.` to work")
        await self.send_help_page(ctx, embeds, self.help_setup)

    async def help_moving(self, ctx):
        embedm = discord.Embed(title="👟 - Moving commands", description='Add "stealth" after any command to suppress join/leave narrations. Add "read" after add/move/renmove/pcadd/addspons for read-only access.', color=0xff3fb9)
        embedm.add_field(name="Move & Knock", value=(
            "**`.move <#|name>`** ─ Move to a house. Players send a request that Overseers approve; admins act directly\n"
            "**`.renmove #House`** ─ Move to renamed house\n"
            "**`.add <#>`** ─ Add player to house (keeps current)\n"
            "**`.remove <#>`** ─ Remove player from house\n"
            "━━━━━━━━━━━━━━━━\n"
            "**`.knock <#|name>`** ─ Knock on a house. Players send a request that Overseers approve; admins act directly\n"
            "**`.pportal <#a> <#b>`** ─ Place a two-way portal between two houses\n"
            "**`.movehouse <#src> <#dest>`** ─ Move every resident from one house to another (admin)\n"
            "**`.autoroleadd @role`** ─ Add auto-visit allocation to all RC channels with this role\n"
            "  *Open* ─ Knocker joins (leaves current)\n"
            "  *Refuse* ─ Knocker sees occupants\n"
            "  *Expires* ─ OS notified in RC\n"
            "**`.pendingknock`** / `.showknocks` ─ True/False if any knock is pending + oldest age\n"
            "  *restart* ─ Scan all servers (owners only)\n"
            "**`.renknock #House`** ─ Knock on renamed house"
        ), inline=False)
        embedm.add_field(name="PC & Misc", value=(
            "**`.pcadd #PC`** ─ Add player to PC/renamed house\n"
            "**`.pcremove #PC`** ─ Remove from PC/renamed house\n"
            "**`.addhere #RC`** ─ Add RC's player to this channel\n"
            "**`.addspons @sponsor #rc`** ─ Add a sponsor directly to a rolechat"
        ), inline=False)
        embedm.set_footer(text="Village Game • All listed commands need the prefix `.` to work")
        await self.send_help_page(ctx, embedm, self.help_moving)

    async def help_home(self, ctx):
        embedh = discord.Embed(title="🏡 - Home commands", description="13 commands", color=0xff3fb9)
        embedh.add_field(name="Player Commands", value=(
            "**`.home`** ─ Bring the player home\n"
            "**`.home stealth`** ─ Bring the player home silently (no join/leave messages)\n"
            "**`.home return`** ─ Bring all players home\n"
            "**`.leaveonlyhomes`** ─ Remove all players in this RC from houses (not PCs)\n"
            "**`.owner`** ─ List house owners\n"
            "**`.owned`** ─ In a Role Chat: show the house(s) owned by the player(s) there\n"
            "**`.whorc [@player]`** ─ Show the RoleChats you can send in, and who is in each (staff can check another player)\n"
        ), inline=False)
        embedh.add_field(name="Admin Commands", value=(
            "**`.home initialize`** ─ Assign RC to alive players, houses structured (one each)\n"
            "**`.home initstagger`** ─ Assign RC to alive players, houses staggered (random)\n"
            "**`.home setup`** ─ Move sponsors to their player's house\n"
            "**`.home set @player #house`** ─ Set a player's home\n"
            "**`.home mset`** ─ Auto-set all current locations as home\n"
            "**`.home list`** ─ List all players' homes\n"
            "**`.home delete @player`** ─ Make a player homeless\n"
            "━━━━━━━━━━━━━━━━\n"
            "**`.rolechat initialize`** ─ Rebuild RCs, one alive player each\n"
            "**`.rolechat list`** ─ List all RCs with their players + sponsors (alias `.rolechat lynch`)"
        ), inline=False)
        embedh.set_footer(text="Village Game • All listed commands need the prefix `.` to work")
        await self.send_help_page(ctx, embedh, self.help_home)

    async def help_handling(self, ctx):
        embedhan = discord.Embed(title="🔓 - Houses and PCs handling", description="17 commands", color=0xff3fb9)
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
            "**`.mergepc #PC1 #PC2 [name]`** ─ Merge two PCs into a new private channel\n"
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
            "**`.preset`** ─ Add/remove/edit presets (interactive menu)\n"
            "  Categories: Lethal, Curing, Manipulation (Control, Redirect), Manipulation (Other), Blocking, Transportation and Comms, Information, Other"
        ), inline=False)
        embedpres.add_field(name="Admin Commands", value=(
            "**`.ospreset`** ─ View/reorder/remove all presets\n"
            "**`.ospresetsort`** ─ Reorder preset display categories\n"
            "**`.ospresetcategories`** ─ Add/remove custom preset categories"
        ), inline=False)
        embedpres.set_footer(text="Village Game • All listed commands need the prefix `.` to work")
        await self.send_help_page(ctx, embedpres, self.help_presets)

    async def help_voting(self, ctx):
        embedv = discord.Embed(title="🗳️ - Voting commands", description="14 commands", color=0xff3fb9)
        embedv.add_field(name="Voting", value=(
            "**`.vote @player`** ─ Vote or change your vote\n"
            "**`.abstain`** ─ Abstain from voting\n"
            "**`.manipulate @target @vote`** ─ Manipulate a player's vote\n"
            "**`.removevote @player`** ─ Remove a player's vote\n"
            "**`.skipnight <min_votes> [text]`** ─ Start skip-night vote (custom title optional)\n"
            "**`.pick [cap=#] [time=1m] <Title>, <Option> ...`** ─ Anonymous multi-option vote in this channel (Overseer)\n"
            "  One vote per player, switched by voting again. `cap=N` = votes needed, `time=1m/90s` = closes voting\n"
            "**`.pickvoters <message_id>`** ─ Reveal who voted on a pick poll (admin)\n"
            "━━━━━━━━━━━━━━━━\n"
            "**`.votelist`** ─ Show all current votes\n"
            "**`.resetvotes`** ─ Reset all votes\n"
            "**`.votehistory/vh [mode]`** ─ Scan vote history\n"
            "  Modes: `grouped` (by target), `range` (reply to end msg or send ID/link)\n"
            "  Tracks `.remvote`/`.removevote`/`.manipulate` so the count stays accurate\n"
            "**`.updatevotes`/`.uv [ch]`** ─ Guide to refresh a session's votecount via `.vh`"
        ), inline=False)
        embedv.add_field(name="Voting in RCs", value=(
            "**`.voteinrc true/false`** ─ Enable voting in RoleChats\n\n"
            "**`.remvote @player`** ─ Remove all votes by and on a player across lynch sessions\n"
            "**`.skipnightvoters <msg>`** ─ Show who voted on a skip-night vote (admin)\n"
            "**`.execution @player`** ─ Start a public execution vote for a player (admin)\n"
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
        embedu = discord.Embed(title="📄 - Lists", description="10 commands", color=0xff3fb9)
        embedu.add_field(name="Player Lists", value=(
            "**`.playerlist`** ─ List alive members\n"
            "**`.sponsorlist`** ─ List sponsor members\n"
            "**`.houselist`** ─ List visitable houses\n"
            "**`.rollhouses`** / **`.rh <num>`** ─ Pick random houses from the list\n"
            "**`.rollhouse`** [#house] <num|all> ─ Roll random alive members from a house\n"
            "**`.deadlist`** ─ Show dead players & their roles"
        ), inline=False)
        embedu.add_field(name="Admin Commands", value=(
            "**`.setuphouselist`** ─ Init houselist from existing houses\n"
            "**`.houselistadd #house`** ─ Add a house to the list\n"
            "**`.houselistremove #house`** ─ Remove a house from list\n"
            "━━━━━━━━━━━━━━━━\n"
            "**`.deadlist add @player <team> <role>`** ─ Add to deadlist\n"
            "**`.deadlist remove @player`** ─ Remove from deadlist\n"
            "**`.deadlist edit @player <team> <role>`** ─ Edit deadlist entry"
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

    async def help_download(self, ctx):
        embedd = discord.Embed(title="⬇️ - Downloads", description="4 commands", color=0xff3fb9)
        embedd.add_field(name="Download", value=(
            "**`.dl`** ─ Reply to a link, download the media and send it here\n"
            "  YouTube, Spotify tracks, and other providers\n"
            "**`.mdl`** ─ Same as `.dl`, but sends the audio as MP3\n"
            "**`.dsplit <N>`** ─ Download and split evenly into **N** equal "
            "parts (no number = minimum parts that fit Discord's upload limit)\n"
            "  Too big for one file? It reports the size vs. this server's limit "
            "and offers to send the first chunk that fits.\n"
            "**`.dclip <start> [end] [N]`** ─ Reply to a link and cut out only "
            "a timestamp range, e.g. `.dclip 1:30 2:45` = 1:30 to 2:45\n"
            "  Timestamps take `90`, `1:30` or `1:02:03`; leave the end off to go "
            "to the finish. Add **N** to split the clip too, e.g. `.dclip 1:30 2:45 3`"
        ), inline=False)
        embedd.set_footer(text="Village Game • All listed commands need the prefix `.` to work")
        await self.send_help_page(ctx, embedd, self.help_download)

    async def help_utility(self, ctx):
        embedu = discord.Embed(title="⚙️ - Utility", description="32 commands", color=0xff3fb9)
        embedu.add_field(name="General", value=(
            "**`.day`** ─ Unlock all day channels\n"
            "**`.night`** ─ Lock all day channels\n"
            "**`.daywf`** ─ Unlock the Future region's day channels\n"
            "**`.nightwf`** ─ Lock the Future region's day channels\n"
            "**`.daywp`** ─ Unlock the Past region's day channels\n"
            "**`.nightwp`** ─ Lock the Past region's day channels\n"
            "**`.broom`** ─ Delete replied-to messages (logs kept)\n"
            "**`.pins`** ─ Reorder or delete pinned messages (Manage Messages)\n"
            "**`.unpinall [#channel]`** ─ Remove every pin from a channel after confirming\n"
            "**`.fbroom`** ─ Force-delete messages including pinned ones (logs kept)\n"
            "**`.firstpin [count] [#ch]`** ─ Show the oldest pinned message(s) as embeds\n"
            "**`.channelstats`** ─ [Admin] Channel count per category, with names on demand\n"
            "**`.actionstats`** ─ Show action completion counters\n"
            "**`.kill`** ─ Log a kill attribution (Overseer only)\n"
            "**`.kills`** ─ View the kill log (admin)\n"
            "**`.killremove <n>`** ─ Remove a kill log entry by number (admin)\n"
        ), inline=False)
        embedu.add_field(name="Utility (cont.)", value=(
            "**`.log <count> [#source] [#dest]`** ─ Export messages to a text file\n"
            "**`.housecheck [hours]`** ─ List quiet houses (default 24h)\n"
            "━━━━━━━━━━━━━━━━\n"
            "**`.whisper #RC <msg>`** ─ Send anonymous whisper\n"
            "**`.switch`** ─ Toggle Player/Sponsor role"
        ), inline=False)
        embedu.add_field(name="Player Status", value=(
            "**`.dead`** ─ Move your RC to Dead category (use in RC)\n"
            "**`.deadrole`** ─ Mark dead, remove house, pin corpse (use in RC)\n"
            "**`.deadc`** ─ Move RC to Dead (admin)\n"
            "**`.corpselist`** ─ List all corpse locations (admin)"
        ), inline=False)
        embedu.add_field(name="Admin — Roles & Perms", value=(
            "**`.addrole @role @users...`** ─ Give role to members\n"
            "**`.removerole <role> <member...>`** ─ Remove role from members (admin)\n"
            "━━━━━━━━━━━━━━━━\n"
            "**`.addcategoryperms @role <cat> <perm>`** ─ R=Read, S=Send\n"
            "**`.addchannelperms @role #ch <perm>`** ─ R=Read, S=Send"
        ), inline=False)
        embedu.add_field(name="Admin — Game & Tracking", value=(
            "**`.endgame`** ─ Unlock all channels post-game\n"
            "**`.statss`** ─ Message counts by role priority\n"
            "**`.serverstats [laps|lap <label>|total]`** ─ Server-wide counts (excl. RCs)\n"
            "↳ `lap day1` (label required) asks for confirmation, then saves and resets\n"
            "━━━━━━━━━━━━━━━━\n"
            "**`.setmessagetracking`** ─ Enable/disable tracking\n"
            "**`.start_tracking`** ─ Start message tracking\n"
            "**`.stop_tracking`** ─ Stop/pause tracking\n"
            "**`.reset_tracking`** ─ Reset message counts\n"
            "**`.resetservstats [true]`** ─ Reset current counts (true = also laps)"
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
        embedo = discord.Embed(title="👽 - Other", description="45 commands", color=0xff3fb9)
        embedo.add_field(name="General", value=(
            "**`.help`** ─ Show this menu\n"
            "**`.help2`** ─ Show additional command categories\n"
            "**`.phelp`** ─ Show commands regular players can use\n"
            "**`.searchhelp <keyword>`** ─ Search all commands by keyword\n"
            "**`.fmbot`** ─ Show Last.fm bot commands by category\n"
        ), inline=False)
        embedo.add_field(name="Other (cont.)", value=(
            "**`.who #ch`** ─ List players in a channel\n"
            "**`.where #RC`** ─ Show a player's current location (staff only, reply `yes`)\n"
            "**`.housewho [#house|#RC]`** ─ Show your house and who is inside it\n"
            "**`.map`** ─ Show the game map\n"
            "**`.role`/`.firstpin [1-10] [#ch]`** ─ Show registered package or merge the first n pinned messages\n"
            "**`.role register <1-4> <role name>`** ─ Register a Role Package\n"
            "**`.role registercard [message_id]`** ─ Register a Role Card\n"
            "**`.firstmsg [#ch]`** ─ Show first message in current channel (#ch needs admin)\n"
            "**`.roll @role <n>`** ─ Random players from a role\n"
            "━━━━━━━━━━━━━━━━\n"
            "**`.ping`** ─ Bot online check\n"
            "**`.ding`** ─ Dong!\n"
            "**`.avatar [@member]`** ─ Show your own avatar (or someone else's)\n"
            "**`.line`/`.banner [lines] [title]`** ─ Draw a clean divider banner (admin)\n"
            "**`.askos <question>`** ─ Ask the Overseers from an RC, Dead RC or Alt\n"
            "**`.react <1-10 | word>`** ─ React to a replied message (admin/OS). "
            "Words spell out; repeats use lookalikes (E→3, L→1, O→0)"
        ), inline=False)
        embedo.add_field(name="Narration", value=(
            "**`.narrate #ch <msg>`** ─ Send narration to channels\n"
            "**`.narration`/`.n <text>`** ─ Storybook embed (admin, pings)\n"
            "**`.np <text>`** ─ Same as `.n` but without pinning (admin)\n"
            "**`.anarration`/`.na <text>`** ─ Silent narration (admin)\n"
            "**`.narrationcolor`** ─ Pick embed color (admin)"
        ), inline=False)
        embedo.add_field(name="Fun Commands", value=(
            "**`.dice <n>`** ─ Roll 1–N\n"
            "**`.dice <opt1> <opt2> ...`** ─ Random pick\n"
            "━━━━━━━━━━━━━━━━\n"
            "**`.opoke @user`** ─ Poke someone\n"
            "**`.opat @user`** ─ Pat someone\n"
            "**`.ohug @user`** ─ Hug someone\n"
            "**`.oslap @user`** ─ Slap someone\n"
            "**`.okill @user`** ─ Kill someone\n"
            "**`.okiss @user`** ─ Kiss someone\n"
            "**`.odance @user`** ─ Dance with someone\n"
            "**`.owave @user`** ─ Wave at someone"
        ), inline=False)
        embedo.add_field(name="Utility Commands", value=(
            "**`.loc`** ─ Show all houses and occupants (admin)\n"
            "**`.gettag <link>`** ─ Get mentioned users from a message\n"
            "**`.timer <time> [tag] [#ch]`** ─ Set a timer (1h2m10s)\n"
            "━━━━━━━━━━━━━━━━\n"
            "**`.deletechannel`** ─ Delete this channel (admin)\n"
            "**`.deletecategory [category]`** ─ Delete a category + all its channels (admin)\n"
            "**`.timestamp <DD-MM> <HH:MM>`** ─ Gen timestamp with timezone picker\n"
            "**`.time`** ─ Get sent time of replied-to message\n"
            "**`.dropitem`** ─ Drop interactive item (see docs)\n"
            "**`.revive`** ─ Revive dead players (interactive, admin)"
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
            "**`.setmeetingtargetguild <id>`** ─ Set meeting server (Discord guild ID)\n"
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
        embede = discord.Embed(title="💰 - Economy commands", description="25 commands", color=0xff3fb9)
        embede.add_field(name="Player Commands", value=(
            "**`.bal`/`.balance`** ─ Show RC balance\n"
            "**`.shop`** ─ View shop with interactive buttons\n"
            "**`.buy <item> [qty]`** ─ Buy from shop (default qty=1)\n"
            "**`.sell`/`.sell-item <item>`** ─ Sell for 50% refund\n"
            "**`.inv`/`.inventory [#ch]`** ─ View RC inventory\n"
            "**`.give @user <amt | item [qty|all]>`** ─ Give RC coins, or items to a player in the same house\n"
            "**`.give-money @user <amt>`** ─ Transfer RC coins to another player\n"
            "**`.trade @user <item> [qty]`** ─ Give items to another player\n"
            "**`.use <item>`** ─ Use an item from inventory"
        ), inline=False)
        embede.add_field(name="Admin — Shop Items", value=(
            "**`.additem <name> <price> [description] [stock]`** ─ Add shop item. Name must start with an emoji and should have **no numbers** (the first number is the price; the trailing number, if any, is the stock — 0 = unlimited); if a number is unavoidable, wrap the name in quotes — e.g. `.additem 🪵 \"Axe 3\" 500 Powerful axe 100`\n"
            "**`.updatestock <item> <stock>`** ─ Set item stock (0 = unlimited)\n"
            "**`.removeitem`/`.rmitem #ch <item> [qty]`** ─ Remove from RC\n"
            "**`.edititem <field> <name> <val>`** ─ Edit item (field: price/name/description/stock)\n"
            "**`.delitem <name>`** ─ Delete item from shop"
        ), inline=False)
        embede.add_field(name="Admin — Money & Items", value=(
            "**`.addmoney #ch <amt>`** ─ Add coins to RC\n"
            "**`.removemoney #ch <amt>`** ─ Remove coins from RC\n"
            "**`.add-money-role @role <amt>`** ─ Add RC coins by role\n"
            "**`.remove-money-role @role <amt>`** ─ Remove RC coins by role\n"
            "**`.additemrole @role <item> <qty>`** ─ Give items by role\n"
            "━━━━━━━━━━━━━━━━\n"
            "**`.sellshop on|off`** ─ Turn shop selling on or off\n"
            "**`.giveitem @user <item> [qty]`** ─ Give items to a player\n"
            "**`.removeitemplayer`/`.rip @user <item> [qty]`** ─ Remove items from a player\n"
            "**`.reseteconomy [amt]`** ─ Reset all balances (default 0)\n"
            "**`.clearinventory`** ─ Clear all inventories\n"
            "**`.collect`** ─ Add the .setcollect amount to every RC's balance\n"
            "**`.setcollect <val>`** ─ Set collect amount (max 10k)\n"
            "**`.leaderboard`/`.lb`/`.top [n]`** ─ Richest RCs (default top 10)"
        ), inline=False)
        embede.add_field(name="Shop Items", value=(
            "🎆 **Fireworks** ─ Reveal your position in announcements\n"
            "👟 **Shoes** ─ Extra visit grant\n"
            "✉ **Whisper** ─ Send anonymous private message\n"
            "🧹 **Broom** ─ Clear recent messages in a channel\n"
            "📜 **Will** ─ Notify OS to pin your last will\n"
            "🔭 **Peep Hole** ─ See who knocks on your target house\n"
            "🔒 **Private PC** ─ Open a private channel with an alive player and all sponsors (`.use private pc`)"
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
            "**`.dashboard`** ─ Open the interactive role dashboard\n"
            "**`.dashboardtoggle`** ─ Enable/disable dashboard\n"
            "**`.setrole @role`** ─ Set dashboard role\n"
            "━━━━━━━━━━━━━━━━\n"
            "**`.addpassiveability <name> <desc>`** ─ Add passive ability\n"
            "**`.removepassiveability <name>`** ─ Remove passive\n"
            "**`.addactiveability <name> <desc> <uses>`** ─ Add active ability\n"
            "**`.removeactiveability <name>`** ─ Remove active\n"
            "━━━━━━━━━━━━━━━━\n"
            "**`.vb`** ─ Toggle visit blocking for a RoleChat\n"
            "**`.checkvb #channel`** ─ Check visit block status\n"
            "**`.lockhouse #house`** ─ Lock a house (blocks moves/knocks)\n"
            "**`.unlockhouse #house`** ─ Unlock a previously locked house\n"
            "**`.setvisits #ch <normal> <forced> <stealth>`** ─ Set absolute visit counts\n"
            "**`.addvisits #ch <normal> <forced> <stealth>`** ─ Add visits to counts\n"
            "**`.removevisits #ch <normal> <forced> <stealth>`** ─ Remove from visit counts\n"
            "**`.actionlog [@user]`** ─ View action log"
        ), inline=False)
        embed.add_field(name="OS Info", value=(
            "**`.setboard`** ─ Set up the OS info board\n"
            "**`.setinfophase <phase>`** ─ Set current phase info (day/night + number)\n"
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
        embed = discord.Embed(title="📚 Library & Stats commands", description="32 commands", color=0xff3fb9)
        embed.add_field(name="Stats", value=(
            "**`.stats [@player]`** ─ View player statistics\n"
            "**`.winrate`** ─ Winrate stats by team\n"
            "**`.gamesearch <conds>`** ─ Search games by team stats, outcomes & role counts — e.g. `Village > 69% AND Evil > 22% AND RK Win` or `VillageCount > 15 AND Players > 25`\n"
            "**`.gamesearchn <conds>`** ─ Same search with percentages excluding Neutral roles (role counts stay the same)\n"
            "**`.gamesearch`** *(no query)* ─ Prints the full usage reference: teams, % conditions, Win/Lose & the count variables `VillageCount`, `EvilCount`, `RKCount`, `NeutralCount`, `Players`*\n"
            "**`.relations [@user]`** ─ Allies and nemeses (with `@user`: also a **Games Together** button listing every game you both played)"
        ), inline=False)
        embed.add_field(name="Library — Browse & Manage", value=(
            "**`.lib`** ─ Browse the game library\n"
            "**`.lib add`** ─ Add a new game\n"
            "**`.lib summary`** ─ Summary of all games\n"
            "**`.lib edit <#> <field> <val>`** ─ Edit a game field (e.g. name, team, winner)\n"
            "**`.lib delete <#>`** ─ Delete a game\n"
            "**`.lib deletegame <#>`** ─ Delete a game\n"
            "**`.lib setwin <#> <team>`** ─ Set winning team\n"
            "**`.lib search <term>`** ─ Search by name or player\n"
            "**`.lib searchdisc <query>`** ─ Search role descriptions & text\n"
            "**`.lib searchos <name>`** ─ Search games by overseer\n"
            "**`.lib idsearch <id>`** ─ Search by game ID"
        ), inline=False)
        embed.add_field(name="Role Packages & Publishing", value=(
            "**`.publishroles`** ─ Build publishing draft (clean only)\n"
            "**`.resolveplayers`** ─ Show unresolved players\n"
            "**`.resolveplayer #ch @player`** ─ Resolve a player\n"
            "**`.resolvesponsor #ch @sponsor`** ─ Choose a Library Sponsor\n"
            "**`.reviewroles`** ─ Review roles\n"
            "**`.reviewteams`** ─ Review teams (add `alive` for only alive players)\n"
            "**`.ps`** ─ Randomized players & sponsors list (no team info)\n"
            "**`.approvepublish`** ─ Publish the archive\n"
            "**`.libimport`** ─ Import approved roles into the library"
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
        embed = discord.Embed(title="⚔️ Games (Aux Battle, Senet & Soldiers)", description="23 commands", color=0xff3fb9)
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
        embed.add_field(name="🪖 Soldiers", value=(
            "**`.soldiers help`** ─ Show help and subcommands\n"
            "**`.soldiers initialize [num]`** ─ Start a new game\n"
            "**`.soldiers stop`** ─ Stop the game\n"
            "**`.soldiers color #HEX`** ─ Change team color\n"
            "**`.soldiers name NAME`** ─ Change team name\n"
            "**`.soldiers ready`** ─ Mark team as ready\n"
            "**`.soldiers board`** ─ Interactive game board"
        ), inline=False)
        embed.set_footer(text="Village Game • All listed commands need the prefix `.` to work")
        await self.send_help_page(ctx, embed, self.help_games)

    async def help_auction(self, ctx):
        embed = discord.Embed(title="🔨 Blind Auction", description="Live auction of a single item; only **Alive** players may bid. Every bidder is hidden as an `Anon #N` alias. Bids are strict-increasing, so ties are impossible.", color=0xff3fb9)
        embed.add_field(name="Player Commands", value=(
            "**`.auc status`** ─ Auction state, time left & recent activity\n"
            "**`.auc start <item> <dur> [sealed|visible]`** ─ Open an auction (Alive players). "
            "`dur` like `2h`/`30m`; `sealed` hides all amounts until reveal, `visible` shows the current highest.\n"
            "**`.auc bid <amount>`** ─ Place a bid, or click the **Bid** button on the board. "
            "Only the current highest bidder has funds held; if you are outbid your money is refunded.\n"
            "━━━━━━━━━━━━━━━━\n"
            "**`.aucset channel #ch`** ─ Board channel (admin)\n"
            "**`.aucset minbid <num>`** ─ Minimum opening bid (admin)\n"
            "**`.aucset increment <num>`** ─ Reserve for future use (admin)\n"
            "**`.aucset duration <sec>`** ─ Default length when no `dur` given (admin)\n"
            "**`.aucset show`** ─ Current auction config (admin)"
        ), inline=False)
        embed.add_field(name="Overseer Commands", value=(
            "**`.auc extend <dur>`** ─ Add time (e.g. `.auc extend 30m`)\n"
            "**`.auc close`** ─ End early & announce the winner/reveal\n"
            "**`.auc cancel`** ─ Void the auction & refund all escrow\n"
            "**`.auc alias @player`** ─ Reveal a player's `Anon #N` alias"
        ), inline=False)
        embed.add_field(name="How the escrow works", value=(
            "The moment a bid is placed, that amount is **removed from the bidder's RoleChat and held**. "
            "If someone outbids them, they are **refunded in full** and the new leader's bid is held instead "
            "(A bids 100 → hold 100; B bids 150 → hold 150, refund A 100; A bids 200 → hold 200, refund B 150). "
            "Bid money can never be spent elsewhere. On close the winner keeps the escrow (shop items auto-grant, "
            "named items are handed over by the Overseer); on cancel everyone is refunded."
        ), inline=False)
        embed.set_footer(text="Village Game • All listed commands need the prefix `.` to work")
        await self.send_help_page(ctx, embed, self.help_auction)

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

    async def help_botc(self, ctx):
        try:
            from BOTC.cogs.help import PAGES, HelpView
            embed = PAGES[0]()
            view = HelpView()
        except ImportError:
            embed = discord.Embed(title="🐦 Blood on the Clocktower", color=0x008080)
            embed.description = "See `.botchelp` for all BOTC commands."
            view = None
        await ctx.send(embed=embed, view=view)

    async def help_analytics(self, ctx):
        embed = discord.Embed(
            title="📊 Analytics & Debug Dashboard",
            description=(
                "Debugging tools for bot developers. All commands are dev-only."
            ),
            color=0x7C5CFC,
        )
        embed.add_field(name="`.analytics` / `.astats`", value=(
            "Open the interactive **Debug Dashboard** with four pages:\n\n"
            "**📊 Summary** — Health badges (latency, analytics, recent errors), "
            "slowest command, most failing command, recent errors list.\n\n"
            "**📋 Commands** — Per-command stats sorted by failure rate. "
            "Shows execs, avg/p95 latency, failure %, unique users. "
            "Use **🔍 Filter** to search by name or change sort mode "
            "(`failure_rate`, `total_execs`, `avg_time_ms`). "
            "Use **◀ ▶** to page.\n\n"
            "**⚠️ Recent Errors** — Newest errors first (up to 200). "
            "Shows error ID, command, exception type, timestamp, cog, "
            "user, guild, and the first line of the traceback with the "
            "source file & line number. "
            "Use **🔍 Filter** to filter by command name. "
            "Use **📄 Traceback** to view the full traceback for any error ID.\n\n"
            "**💚 Health** — Bot uptime, Discord latency, analytics status, "
            "database size, memory usage, and lists of all loaded cogs and commands."
        ), inline=False)
        embed.add_field(name="`.failures [command]`", value=(
            "Quick error summary without the interactive view.\n"
            "• `.failures` — Total errors, commands with errors, error types, recent 5.\n"
            "• `.failures analytics` — Paginated per-command error detail with source file/line."
        ), inline=False)
        embed.add_field(name="`.analyticsexport`", value=(
            "Export all analytics data (commands, errors, usage trends, health) "
            "to a markdown file with tables — easy to read and share."
        ), inline=False)
        embed.add_field(name="Interactive Buttons (in `.analytics`)", value=(
            "**◀ ▶** — Page through command/error lists\n"
            "**🔄 Refresh** — Reload the current page\n"
            "**🔍 Filter** — Search/filter (page-specific)\n"
            "**📄 Traceback** — Enter an error ID to view the full traceback\n"
            "**🗑 Reset Errors** — Double-click to delete all error records"
        ), inline=False)
        embed.set_footer(text="Restricted to bot developers")
        await ctx.send(embed=embed)

    async def help_surveillance(self, ctx):
        embed = discord.Embed(
            title="🔍 Surveillance commands",
            description="Follow, Track, and Stalk players. All commands must be used in a **RoleChat** channel.",
            color=0xff3fb9,
        )
        embed.add_field(name="Follow — Move with them", value=(
            "**`.follow @player`** ─ Follow a player (you move where they move)\n"
            "**`.follow @player stealth`** ─ Follow silently (no join/leave messages)\n"
            "**`.unfollow @player`** ─ Stop following a player\n"
            "**`.followlist`** ─ Show all follow pairs\n"
            "**`.unfollowall`** ─ Clear all follow pairs"
        ), inline=False)
        embed.add_field(name="Track — Watch their location", value=(
            "**`.track @player`** ─ Create a live-updating embed showing their location\n"
            "**`.untrack`** ─ Stop tracking"
        ), inline=False)
        embed.add_field(name="Stalk — Read access to their house", value=(
            "**`.stalk @player`** ─ Silently read their house channel\n"
            "**`.unstalk @player`** ─ Stop stalking a player\n"
            "**`.unstalkall`** ─ Stop stalking all players\n"
            "**`.stalklist`** ─ Show all stalk relationships"
        ), inline=False)
        embed.set_footer(text="Village Game • All listed commands need the prefix `.` to work")
        await self.send_help_page(ctx, embed, self.help_surveillance)

    async def help_status(self, ctx):
        embed = discord.Embed(
            title="🛡 Status commands",
            description="Track moderator statuses on Role Channels (Protection, Roleblock, Immunities, etc.).\nAll status commands are **admin only**.",
            color=0xff3fb9,
        )
        embed.add_field(name="Commands", value=(
            "**`/status`** ─ Open the interactive Status Manager for the current channel (ephemeral)\n"
            "**`.status clear`** ─ Clear all statuses for the current channel\n"
            "**`.statuslist`** ─ Show all channels that have active statuses\n"
            "**`.statuspanel`** ─ Post/refresh the Interactive member status panel (Online/AFK)"
        ), inline=False)
        embed.add_field(name="Built-in Statuses", value=(
            "🛡 **Protection** ─ Channel is protected\n"
            "⛔ **Roleblock** ─ Channel is roleblocked\n"
            "👣 **Visit Block** ─ Warning on movement (must confirm)\n"
            "🌑 **Stealth** ─ Warning on movement (skipped with `stealth` arg)\n"
            "✨ **Immunity** ─ Immunity active\n"
            "🎯 **Untargetable** ─ Channel cannot be targeted"
        ), inline=False)
        embed.add_field(name="Custom Statuses", value=(
            "You can also add **free-text custom statuses** via the Status Manager modal.\n"
            "Each status (built-in or custom) shows when it was added and who added it.\n"
            "Clear individual statuses or all at once with the buttons."
        ), inline=False)
        embed.add_field(name="Integration", value=(
            "The bot shows a **warning (Confirm/Cancel)** when:\n"
            "• **`.move`**, **`.renmove`**, **`.knock`**, **`.renknock`**, **`.home`** on a visitblocked channel\n"
            "• **`.move`**, **`.renmove`**, **`.knock`**, **`.renknock`**, **`.home`** on a channel with Stealth status\n\n"
            "**Visit Block** — admin must confirm to proceed (no bypass)\n"
            "**Stealth** — **`.move stealth`**, **`.renmove stealth`**, or **`.home stealth`** skip the warning\n"
            "• **`.dead`** is used on a channel with Protection\n\n"
            "All status changes are logged to the actions log channel."
        ), inline=False)
        embed.set_footer(text="Village Game • Admin only")
        await self.send_help_page(ctx, embed, self.help_status)

    async def help_sticky(self, ctx):
        embed = discord.Embed(title="📌 - Sticky messages commands", description="5 Commands", color=0xff3fb9)
        embed.add_field(name="Setup", value=(
            "**`.sticky set [#ch] <text>`** ─ Set a sticky message for a channel (default: current channel)\n"
            "**`.sticky remove [#ch]`** ─ Remove the sticky message from a channel\n"
            "**`.sticky cooldown [#ch] <sec>`** ─ Change refresh cooldown (min 10s, default 60s)\n"
            "**`.sticky list`** ─ List every sticky message in this server"
        ), inline=False)
        embed.add_field(name="How it works", value=(
            "The sticky is sent as a **plain, silent message** (no embed, no ping, no notification).\n"
            "While it's active, every new message in the channel **re-pins it to the bottom**: "
            "the old copy is deleted and a fresh one is posted, but only after the cooldown expired to avoid spam/rate limits.\n\n"
            "**`.sticky`** ─ Shows the status and content of the current channel's sticky."
        ), inline=False)
        embed.set_footer(text="Village Game • Admin only for set/remove/cooldown/list")
        await self.send_help_page(ctx, embed, self.help_sticky)


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
