import os
import asyncio
import requests
from bs4 import BeautifulSoup
from datetime import datetime, timezone
import discord
from discord.ext import commands

# ----------------------------
# CONFIG
# ----------------------------
TOKEN = os.getenv("DISCORD_TOKEN")  # Twój token bota
CHANNEL_ID = int(os.getenv("CHANNEL_ID"))  # ID kanału, gdzie bot będzie pisał

MIN_LEVEL = 600        # minimalny lvl postaci która może mieć domek
OFFLINE_DAYS = 10      # minimalna ilość dni offline żeby domek był do przejęcia

intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix="!", intents=intents)

# ----------------------------
# CACHE + ALERT 13 DNI
# ----------------------------
cache = {}
cache_ready = False
progress_msg = None
alerted_houses = set()  # pamięta domki, które już dostały alert 13 dni

# ----------------------------
# PARSERY
# ----------------------------
def get_all_houses():
    """Pobiera wszystkie domki z Cyleria"""
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

# ----------------------------
# CACHE BUILD
# ----------------------------
async def update_cache(ctx=None):
    global cache, cache_ready, progress_msg, alerted_houses
    cache_ready = False
    alerted_houses = set()
    houses_map = get_all_houses()
    all_players = []

    # Pobranie wszystkich graczy z minimalnym lvl
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
        offset += 2000

    total = len(all_players)
    done = 0
    start = datetime.now(timezone.utc)
    new_cache = {}

    if ctx:
        progress_msg = await ctx.send(f"🔄 Budowanie cache: 0/{total}")

    for p in all_players:
        try:
            lvl, house, last_login = get_character_info(p)
        except:
            continue
        done += 1
        if house and house in houses_map and lvl >= MIN_LEVEL:
            offline_days = (datetime.now(timezone.utc) - last_login).days
            new_cache[p] = {
                "lvl": lvl,
                "house": house,
                "offline_days": offline_days,
                "status": houses_map[house]["status"],
                "map": houses_map[house]["map"]
            }

            # ALERT 13 dni
            if offline_days == 13 and p not in alerted_houses:
                alerted_houses.add(p)
                if ctx:
                    await ctx.send(f"⚠️ Domek **{house}** gracza **{p}** osiągnął 13 dni offline!\nMapka: {houses_map[house]['map']}")

        # PASEK POSTĘPU co 100 graczy
        if done % 100 == 0 and ctx and progress_msg:
            perc = int(done / total * 100)
            filled = int(perc / 5)
            bar = "█" * filled + "-" * (20 - filled)
            elapsed = (datetime.now(timezone.utc) - start).total_seconds()
            eta = int(elapsed / done * (total - done)) if done else 0
            await progress_msg.edit(content=f"🔄 Budowanie cache: [{bar}] {perc}% {done}/{total} | ETA: ~{eta}s")

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
        await update_cache(ctx=channel)
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
!sprawdz - pokazuje wszystkie domki 10+ dni offline
!ultra - domki 10+ dni offline i 600+ lvl
!top20 - top 20 najstarszych offline domków
!status - stan cache
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
