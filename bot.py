import os
import asyncio
import requests
from bs4 import BeautifulSoup
from datetime import datetime, timezone, timedelta
import discord
from discord.ext import commands, tasks

# ----------------------------
# CONFIG
# ----------------------------
TOKEN = os.getenv("DISCORD_TOKEN")
CHANNEL_ID = int(os.getenv("CHANNEL_ID"))

MIN_LEVEL = 600        # minimalny lvl postaci która może mieć domek
OFFLINE_DAYS = 10      # minimalna ilość dni offline żeby domek był do przejęcia
UPDATE_INTERVAL = 60*60  # w sekundach, co ile aktualizujemy cache

intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix="!", intents=intents)

# ----------------------------
# CACHE
# ----------------------------
cache = {}
cache_ready = False
progress_msg = None

# ----------------------------
# FUNKCJE PARSERÓW
# ----------------------------

def get_all_houses():
    """Pobiera wszystkie domki z Cyleria i tworzy mapę: nazwa -> info"""
    url = "https://cyleria.pl/?subtopic=houses"
    resp = requests.get(url)
    soup = BeautifulSoup(resp.text, "html.parser")

    houses = {}
    table = soup.find("table")
    if not table:
        return houses

    for row in table.find_all("tr")[1:]:
        cols = row.find_all("td")
        if len(cols) < 4:
            continue
        name = cols[0].text.strip()
        size = int(cols[1].text.strip())
        owner = cols[2].text.strip()
        status = cols[3].text.strip()
        # Link do mapki jeśli istnieje
        link = cols[0].find("a")
        map_link = link['href'] if link else None
        houses[name] = {
            "size": size,
            "owner": owner,
            "status": status,
            "map": map_link
        }
    return houses


def get_character_info(name):
    """Pobiera info o postaci: lvl, domek, ostatnie logowanie"""
    url = f"https://cyleria.pl/?subtopic=characters&name={name}"
    resp = requests.get(url)
    soup = BeautifulSoup(resp.text, "html.parser")
    text = soup.get_text(separator="\n")

    # lvl
    lvl = 0
    for line in text.splitlines():
        if "Level" in line:
            try:
                lvl = int(line.split(":")[1].strip())
            except:
                lvl = 0
            break

    # domek
    house = None
    for line in text.splitlines():
        if "Domek" in line:
            house = line.split(":", 1)[1].strip()
            break

    # ostatnie logowanie
    last_login = None
    for line in text.splitlines():
        if "Logowanie" in line:
            date_str = line.split(":", 1)[1].strip()
            try:
                last_login = datetime.strptime(date_str, "%d.%m.%Y (%H:%M)").replace(tzinfo=timezone.utc)
            except:
                last_login = datetime.now(timezone.utc)
            break

    return lvl, house, last_login


async def update_cache_progress(ctx=None):
    """Aktualizacja cache z ETA i paskiem postępu"""
    global cache, cache_ready, progress_msg
    cache_ready = False
    houses_map = get_all_houses()
    all_players = []

    # Pobieramy listę wszystkich graczy z highscores
    offset = 0
    while True:
        url = f"https://cyleria.pl/?subtopic=highscores&list=experience&world=0&minLevel={MIN_LEVEL}&start={offset}"
        resp = requests.get(url)
        soup = BeautifulSoup(resp.text, "html.parser")
        table = soup.find("table")
        if not table or len(table.find_all("tr")) <= 1:
            break
        for row in table.find_all("tr")[1:]:
            cols = row.find_all("td")
            if len(cols) < 2:
                continue
            player_name = cols[1].text.strip()
            all_players.append(player_name)
        offset += 2000  # kolejne strony

    total = len(all_players)
    done = 0
    start = datetime.now(timezone.utc)

    new_cache = {}
    for p in all_players:
        try:
            lvl, house, last_login = get_character_info(p)
        except:
            continue
        done += 1
        elapsed = (datetime.now(timezone.utc) - start).total_seconds()
        eta = int(elapsed / done * (total - done)) if done else 0

        if house and house in houses_map and lvl >= MIN_LEVEL:
            offline_days = (datetime.now(timezone.utc) - last_login).days
            new_cache[p] = {
                "lvl": lvl,
                "house": house,
                "offline_days": offline_days,
                "city": houses_map[house]["size"],  # size placeholder
                "status": houses_map[house]["status"],
                "map": houses_map[house]["map"]
            }

        # Progress update co 50 graczy
        if done % 50 == 0 and ctx and progress_msg:
            bar_len = 20
            filled = int(done / total * bar_len)
            bar = "█" * filled + "-" * (bar_len - filled)
            await progress_msg.edit(content=f"Cache building: `{bar}` {done}/{total} | ETA ~{eta}s")

    cache = new_cache
    cache_ready = True
    if ctx and progress_msg:
        await progress_msg.edit(content=f"✅ Cache gotowy – {len(cache)} domków.")

# ----------------------------
# EVENTS
# ----------------------------

@bot.event
async def on_ready():
    print(f"Zalogowano jako {bot.user}")
    channel = bot.get_channel(CHANNEL_ID)
    if channel:
        global progress_msg
        progress_msg = await channel.send("🔄 Rozpoczynam skan Cylerii...")
        await update_cache_progress(ctx=channel)
    else:
        print("Nie znaleziono kanału!")

# ----------------------------
# KOMENDY
# ----------------------------

@bot.command()
async def info(ctx):
    msg = """
**Komendy bota Cyleria**
!info - pokazuje wszystkie komendy
!sprawdz - pokazuje wszystkie domki do przejęcia 10+ dni offline
!ultra - domki 10+ dni offline i 600+ lvl
!top20 - top 20 najstarszych offline domków
"""
    await ctx.send(msg)


@bot.command()
async def sprawdz(ctx):
    if not cache_ready:
        await ctx.send("Cache nie był jeszcze budowany.")
        return
    result = []
    for p, data in cache.items():
        if data["offline_days"] >= OFFLINE_DAYS:
            result.append(f"{p} | {data['house']} | {data['offline_days']} dni offline | {data['map']}")
    if not result:
        await ctx.send("Nie znaleziono domków dla tego filtra")
        return
    await ctx.send("\n".join(result[:20]))


@bot.command()
async def ultra(ctx):
    if not cache_ready:
        await ctx.send("Cache nie był jeszcze budowany.")
        return
    result = []
    for p, data in cache.items():
        if data["offline_days"] >= OFFLINE_DAYS and data["lvl"] >= MIN_LEVEL:
            result.append(f"{p} | {data['house']} | lvl {data['lvl']} | {data['offline_days']} dni offline | {data['map']}")
    if not result:
        await ctx.send("Nie znaleziono domków dla tego filtra")
        return
    await ctx.send("\n".join(result[:20]))


@bot.command()
async def top20(ctx):
    if not cache_ready:
        await ctx.send("Cache nie był jeszcze budowany.")
        return
    # sortujemy po offline_days
    top = sorted(cache.items(), key=lambda x: x[1]["offline_days"], reverse=True)
    msg = []
    for p, data in top[:20]:
        msg.append(f"{p} | {data['house']} | lvl {data['lvl']} | {data['offline_days']} dni offline | {data['map']}")
    await ctx.send("\n".join(msg))


@bot.command()
async def status(ctx):
    if not cache_ready:
        await ctx.send("Cache nie był jeszcze budowany.")
    else:
        await ctx.send(f"Cache gotowy – {len(cache)} domków.")

# ----------------------------
# RUN BOT
# ----------------------------
bot.run(TOKEN)
