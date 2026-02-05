import discord
from discord.ext import commands, tasks
import aiohttp
import asyncio
from bs4 import BeautifulSoup
from datetime import datetime, timedelta, timezone
import os

TOKEN = os.getenv("DISCORD_TOKEN")
CHANNEL_ID = int(os.getenv("CHANNEL_ID"))

BASE = "https://cyleria.pl"

CITIES = [
    "Cyleria City",
    "Celestial City",
    "Volcano City",
    "Ankardia City",
    "Dekane City",
    "Olimpus City"
]

intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix="!", intents=intents)

cache = []
progress = {"done": 0, "total": 0, "start": None}
alerted = set()

# ---------------- HTTP ----------------

async def fetch(session, url):
    try:
        async with session.get(url, timeout=10) as r:
            return await r.text()
    except:
        return None

# ---------------- PARSING ----------------

def parse_offline(text):
    try:
        return datetime.strptime(text.strip(), "%d.%m.%Y (%H:%M)")
    except:
        return None

async def get_all_players(session):
    players = []
    page = 1
    while True:
        url = f"{BASE}/?subtopic=highscores&list=experience&world=0&page={page}"
        html = await fetch(session, url)
        if not html:
            break
        soup = BeautifulSoup(html, "html.parser")
        rows = soup.select("table.TableContent tr")[1:]
        if not rows:
            break
        for r in rows:
            cols = r.find_all("td")
            if len(cols) >= 2:
                players.append(cols[1].text.strip())
        page += 1
    return players

async def get_character(session, name):
    url = f"{BASE}/?subtopic=characters&name={name.replace(' ', '+')}"
    html = await fetch(session, url)
    if not html:
        return None
    soup = BeautifulSoup(html, "html.parser")

    house = None
    city = None
    last = None

    for tr in soup.find_all("tr"):
        tds = tr.find_all("td")
        if len(tds) != 2:
            continue
        key = tds[0].text.strip()
        val = tds[1].text.strip()

        if key == "Last Login:":
            last = parse_offline(val)

        if key == "House:":
            house = val
            for c in CITIES:
                if c.lower() in val.lower():
                    city = c

    if not house or not last:
        return None

    return {
        "name": name,
        "house": house,
        "city": city,
        "last": last
    }

# ---------------- CACHE ----------------

@tasks.loop(minutes=30)
async def update_cache():
    global cache, progress

    await bot.wait_until_ready()
    channel = bot.get_channel(CHANNEL_ID)

    async with aiohttp.ClientSession() as session:
        players = await get_all_players(session)
        progress = {"done": 0, "total": len(players), "start": datetime.now(timezone.utc)}
        cache = []

        msg = await channel.send("🔄 Rozpoczynam skan Cylerii...")

        sem = asyncio.Semaphore(20)

        async def worker(name):
            async with sem:
                data = await get_character(session, name)
                progress["done"] += 1
                if data:
                    days = (datetime.now(timezone.utc) - data["last"]).days
                    if days >= 10:
                        data["days"] = days
                        cache.append(data)

        tasks_list = [worker(p) for p in players]

        for i in range(0, len(tasks_list), 50):
            await asyncio.gather(*tasks_list[i:i+50])

            done = progress["done"]
            total = progress["total"]
            percent = int(done / total * 100)
            elapsed = int((datetime.now(timezone.utc) - progress["start"]).total_seconds())
            eta = int(elapsed / done * (total - done)) if done > 0 else 0

            await msg.edit(content=f"🔄 Skan Cylerii\nPostęp: {done}/{total} ({percent}%)\nDomków: {len(cache)}\nETA: ~{eta//60}m {eta%60}s")

    await channel.send(f"✅ Cache gotowy – {len(cache)} domków.")

# ---------------- ALERTS ----------------

@tasks.loop(minutes=5)
async def alert_loop():
    await bot.wait_until_ready()
    channel = bot.get_channel(CHANNEL_ID)

    for h in cache:
        if h["days"] == 12 and h["name"] not in alerted:
            alerted.add(h["name"])
            await channel.send(
                f"🚨 **DOMEK ZA 24H**\n"
                f"{h['name']}\n"
                f"{h['house']}\n"
                f"Offline: {h['days']} dni"
            )

# ---------------- COMMANDS ----------------

@bot.command()
async def info(ctx):
    await ctx.send(
        "!sprawdz [miasto]\n"
        "!top20\n"
        "!ultra [miasto]\n"
        "!status"
    )

@bot.command()
async def status(ctx):
    if progress["total"] == 0:
        await ctx.send("Cache nie był jeszcze budowany.")
    else:
        done = progress["done"]
        total = progress["total"]
        percent = int(done/total*100)
        await ctx.send(f"Cache: {done}/{total} ({percent}%) | Domków: {len(cache)}")

def filter_city(data, city):
    if not city:
        return data
    return [x for x in data if x["city"] and city.lower() in x["city"].lower()]

@bot.command()
async def sprawdz(ctx, *, city=None):
    data = filter_city(cache, city)
    data = sorted(data, key=lambda x: -x["days"])[:5]
    if not data:
        await ctx.send("Brak domków.")
        return
    msg = ""
    for h in data:
        msg += f"{h['name']} | {h['house']} | {h['days']} dni\n"
    await ctx.send(msg)

@bot.command()
async def top20(ctx):
    data = sorted(cache, key=lambda x: -x["days"])[:20]
    msg = ""
    for h in data:
        msg += f"{h['name']} | {h['house']} | {h['days']} dni\n"
    await ctx.send(msg)

@bot.command()
async def ultra(ctx, *, city=None):
    data = [x for x in cache if x["days"] >= 10]
    data = filter_city(data, city)
    data = sorted(data, key=lambda x: -x["days"])[:10]
    msg = ""
    for h in data:
        msg += f"{h['name']} | {h['house']} | {h['days']} dni\n"
    await ctx.send(msg)

# ---------------- START ----------------

@bot.event
async def on_ready():
    print("Zalogowano jako", bot.user)
    update_cache.start()
    alert_loop.start()

bot.run(TOKEN)
