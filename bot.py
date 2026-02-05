import os
import json
import asyncio
import requests
from bs4 import BeautifulSoup
from datetime import datetime, timezone
from discord.ext import commands, tasks
import discord

# ====== VARIABLES from Railway environment ======
TOKEN = os.environ.get("DISCORD_TOKEN")
DISCORD_CHANNEL = int(os.environ.get("DISCORD_CHANNEL"))  # must be an integer ID
BASE_URL_HOUSES = "https://cyleria.pl/?subtopic=houses"
BASE_URL_PLAYERS = "https://cyleria.pl/?subtopic=highscores"
CACHE_FILE = "cache.json"

# ====== BOT SETUP ======
intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix="!", intents=intents)

cache = []

# ====== FETCHING FUNCTIONS ======
def fetch_houses():
    resp = requests.get(BASE_URL_HOUSES)
    resp.raise_for_status()
    soup = BeautifulSoup(resp.text, "html.parser")
    houses = []

    table_rows = soup.select("table tbody tr")
    for row in table_rows:
        cells = row.find_all("td")
        if len(cells) < 4:
            continue
        name = cells[0].get_text(strip=True)
        try:
            size = int(cells[1].get_text(strip=True))
        except ValueError:
            continue
        player = cells[2].get_text(strip=True) or "Brak"
        last_login_text = cells[3].get_text(strip=True)
        map_link_tag = cells[0].find("a")
        map_link = map_link_tag["href"] if map_link_tag else None

        houses.append({
            "name": name,
            "size": size,
            "player": player,
            "last_login": last_login_text,
            "map_link": map_link,
        })
    return houses

def save_cache_to_file():
    with open(CACHE_FILE, "w", encoding="utf-8") as f:
        json.dump(cache, f, ensure_ascii=False, indent=2)

def load_cache_from_file():
    global cache
    if os.path.exists(CACHE_FILE):
        with open(CACHE_FILE, "r", encoding="utf-8") as f:
            cache = json.load(f)

# ====== CACHE BUILDING ======
async def build_cache(ctx=None):
    global cache
    houses = fetch_houses()
    cache = []

    total = len(houses)
    for idx, house in enumerate(houses, start=1):
        cache.append(house)
        if ctx:
            await ctx.send(f"🔄 Budowanie cache: {idx}/{total} domków")
        else:
            print(f"🔄 Budowanie cache: {idx}/{total} domków")

    save_cache_to_file()

    if ctx:
        await ctx.send(f"✅ Cache zbudowany. Znaleziono {len(cache)} domków.")
    print(f"✅ Cache zbudowany. Znaleziono {len(cache)} domków.")

# ====== DISCORD COMMANDS ======
@bot.command()
async def status(ctx):
    if not cache:
        await ctx.send("⚠️ Cache nie był jeszcze budowany!")
        return
    await ctx.send(f"✅ Cache gotowy – {len(cache)} domków.")

@bot.command()
async def sprawdz(ctx):
    if not cache:
        await ctx.send("⚠️ Cache nie był jeszcze budowany!")
        return

    houses_to_show = []
    for house in cache:
        if house["player"].lower() == "brak" or "aktywny" in house["player"].lower():
            link = f" [📍]({house['map_link']})" if house["map_link"] else ""
            houses_to_show.append(f"{house['name']} - {house['size']} - {house['player']}{link}")

    if not houses_to_show:
        await ctx.send("Brak domków spełniających kryteria.")
        return

    # wysyłanie w kawałkach po 25 domków
    chunk_size = 25
    for i in range(0, len(houses_to_show), chunk_size):
        chunk = houses_to_show[i:i+chunk_size]
        text = "\n".join(chunk)
        await ctx.send(f"🏠 Domki do przejęcia:\n```{text}```")

@bot.command()
async def info(ctx):
    commands_info = """
Lista komend bota:
!status - Pokazuje ile domków jest w cache.
!sprawdz - Pokazuje domki wolne lub z aktywnym graczem.
!info - Pokazuje ten opis.
"""
    await ctx.send(commands_info)

# ====== ALERT TASK ======
@tasks.loop(minutes=5)
async def alert_new_houses():
    global cache
    channel = bot.get_channel(DISCORD_CHANNEL)
    if not channel:
        print("❌ Nie znaleziono kanału do alertów")
        return

    houses = fetch_houses()
    new_houses = []
    for house in houses:
        if all(house["name"] != c["name"] for c in cache):
            new_houses.append(house)

    for house in new_houses:
        link = f" [📍]({house['map_link']})" if house["map_link"] else ""
        await channel.send(f"⚠️ Nowy domek do przejęcia: {house['name']} - {house['size']} - {house['player']}{link}")

    if new_houses:
        cache.extend(new_houses)
        save_cache_to_file()

# ====== BOT EVENTS ======
@bot.event
async def on_ready():
    print(f"✅ Zalogowano jako {bot.user}")
    load_cache_from_file()
    channel = bot.get_channel(DISCORD_CHANNEL)
    await build_cache(ctx=channel)
    alert_new_houses.start()

# ====== RUN BOT ======
bot.run(TOKEN)
