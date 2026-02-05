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

    last_login = None
    for line in text.splitlines():
        if "Logowanie" in line:
            date_str = line.split(":", 1)[1].strip()
            try:
                last_login = datetime.strptime(date_str, "%d.%m.%Y (%H:%M)").replace(tzinfo=timezone.utc)
            except:
                last_login = datetime.now(timezone.utc)
            break

    return lvl, last_login

# ----------------------------
# UPDATE CACHE
# ----------------------------
async def update_cache_channel(channel):
    global cache, cache_ready, alerted_houses
    while True:
        cache_ready = False
        alerted_houses = set()
        houses = await get_all_houses()
        total = len(houses)
        done = 0
        start = datetime.now(timezone.utc)
        new_cache = {}

        if total == 0:
            await channel.send("⚠️ Nie znaleziono domków na Cylerii.")
            await asyncio.sleep(600)
            continue

        progress_msg = await channel.send(f"🔄 Budowanie cache: 0/{total}")

        for house_name, house_data in houses.items():
            owner = house_data["owner"]
            if not owner:
                done += 1
                continue
            try:
                lvl, last_login = await get_character_info(owner)
            except:
                done += 1
                continue

            offline_days = (datetime.now(timezone.utc) - last_login).days
            if lvl >= MIN_LEVEL:
                new_cache[owner] = {
                    "lvl": lvl,
                    "house": house_name,
                    "offline_days": offline_days,
                    "status": house_data["status"],
                    "map": house_data["map"]
                }

                # ALERT 13 dni
                if offline_days == 13 and owner not in alerted_houses:
                    alerted_houses.add(owner)
                    await channel.send(f"⚠️ Domek **{house_name}** gracza **{owner}** osiągnął 13 dni offline!\nMapka: {house_data['map']}")

            done += 1

            # PASEK POSTĘPU co 5 domków
            if done % 5 == 0:
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
    for owner, data in cache.items():
        if data["offline_days"] >= OFFLINE_DAYS:
            result.append(f"{owner} | {data['house']} | {data['offline_days']} dni offline | {data['map']}")
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
    for owner, data in cache.items():
        if data["offline_days"] >= OFFLINE_DAYS and data["lvl"] >= MIN_LEVEL:
            result.append(f"{owner} | {data['house']} | lvl {data['lvl']} | {data['offline_days']} dni offline | {data['map']}")
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
    for owner, data in top[:20]:
        msg.append(f"{owner} | {data['house']} | lvl {data['lvl']} | {data['offline_days']} dni offline | {data['map']}")
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
        await channel.send("🔄 Rozpoczynam skan Cylerii...")
        asyncio.create_task(update_cache_channel(channel))
    else:
        print("Nie znaleziono kanału!")

# ----------------------------
# RUN BOT
# ----------------------------
bot.run(TOKEN)
