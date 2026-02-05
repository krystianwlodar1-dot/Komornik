import os
import asyncio
import aiohttp
from bs4 import BeautifulSoup
from datetime import datetime, timezone
import discord
from discord.ext import commands

# ----------------------------
# CONFIG
# ----------------------------
TOKEN = os.getenv("DISCORD_TOKEN")  # Twój token bota
CHANNEL_ID = int(os.getenv("CHANNEL_ID"))  # ID kanału, gdzie bot będzie pisał

MIN_LEVEL = 600
OFFLINE_DAYS = 10

intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix="!", intents=intents)

# ----------------------------
# CACHE + ALERT
# ----------------------------
cache = {}
cache_ready = False
alerted_houses = set()  # pamięta alerty 13 dni

# ----------------------------
# ASYNC HTTP
# ----------------------------
async def fetch(session, url):
    async with session.get(url) as resp:
        return await resp.text()

async def get_all_houses():
    url = "https://cyleria.pl/?subtopic=houses"
    async with aiohttp.ClientSession() as session:
        html = await fetch(session, url)
        soup = BeautifulSoup(html, "html.parser")
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

async def get_character_info(name):
    url = f"https://cyleria.pl/?subtopic=characters&name={name}"
    async with aiohttp.ClientSession() as session:
        html = await fetch(session, url)
        soup = BeautifulSoup(html, "html.parser")
        text = soup.get_text(separator="\n")

    lvl = 0
    for line in text.splitlines():
        if "Level" in line:
            try:
                lvl = int(line.split(":")[1].strip())
            except:
                lvl = 0
            break

    house = None
    for line in text.splitlines():
        if "Domek" in line:
            house = line.split(":", 1)[1].strip()
            break

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
# UPDATE CACHE
# ----------------------------
async def update_cache_channel(channel):
    global cache, cache_ready, alerted_houses
    while True:
        cache_ready = False
        alerted_houses = set()
        houses_map = await get_all_houses()
        all_players = []

        # pobierz wszystkich graczy po 2000 na stronę
        offset = 0
        while True:
            url = f"https://cyleria.pl/?subtopic=highscores&list=experience&world=0&minLevel={MIN_LEVEL}&start={offset}"
            async with aiohttp.ClientSession() as session:
                html = await fetch(session, url)
            soup = BeautifulSoup(html, "html.parser")
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
        progress_msg = await channel.send(f"🔄 Budowanie cache: 0/{total}")

        for p in all_players:
            try:
                lvl, house, last_login = await get_character_info(p)
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
                    await channel.send(f"⚠️ Domek **{house}** gracza **{p}** osiągnął 13 dni offline!\nMapka: {houses_map[house]['map']}")

            # PASEK POSTĘPU co 50 graczy
            if done % 50 == 0:
                perc = int(done / total * 100)
                filled = int(perc / 5)
                bar = "█" * filled + "-" * (20 - filled)
                elapsed = (datetime.now(timezone.utc) - start).total_seconds()
                eta = int(elapsed / done * (total - done)) if done else 0
                await progress_msg.edit(content=f"🔄 Budowanie cache: [{bar}] {perc}% {done}/{total} | ETA: ~{eta}s")

        cache = new_cache
        cache_ready = True
        await progress_msg.edit(content=f"✅ Cache gotowy – {len(cache)} domków.")
        await asyncio.sleep(3600)  # odświeżanie co godzinę

# ----------------------------
# KOMENDY
# ----------------------------
@bot.command()
async def info(ctx):
    msg = """
**Komendy bota Cyleria**
!info - pokazuje wszystkie komendy
!sprawdz - wszystkie domki 10+ dni offline
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
# ON READY
# ----------------------------
@bot.event
async def on_ready():
    print(f"Zalogowano jako {bot.user}")
    channel = bot.get_channel(CHANNEL_ID)
    if channel:
        asyncio.create_task(update_cache_channel(channel))
    else:
        print("Nie znaleziono kanału!")

# ----------------------------
# RUN BOT
# ----------------------------
bot.run(TOKEN)
