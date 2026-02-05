import os
import json
import asyncio
import requests
from datetime import datetime, timezone
from bs4 import BeautifulSoup
import discord
from discord.ext import commands, tasks

# --- VARIABLES from Railway ---
TOKEN = os.getenv("TOKEN")  # Discord bot token
DISCORD_CHANNEL = int(os.getenv("DISCORD_CHANNEL", "0"))

# --- Constants ---
HOUSES_URL = "https://cyleria.pl/?subtopic=houses"
HIGHSCORES_URL = "https://cyleria.pl/?subtopic=highscores"
CACHE_FILE = "cache.json"
MIN_LEVEL = 600

intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix="!", intents=intents)

cache = []

# --- UTILITIES ---
def save_cache():
    with open(CACHE_FILE, "w", encoding="utf-8") as f:
        json.dump(cache, f, ensure_ascii=False, indent=2)

def load_cache():
    global cache
    if os.path.exists(CACHE_FILE):
        with open(CACHE_FILE, "r", encoding="utf-8") as f:
            cache = json.load(f)

def fetch_houses():
    """Fetch houses from Cyleria.pl and return list of dicts."""
    resp = requests.get(HOUSES_URL)
    soup = BeautifulSoup(resp.text, "html.parser")
    houses_list = []

    # Wyszukujemy wszystkie rzędy domków
    rows = soup.select("table tbody tr")  # przyjmujemy tabelę domków
    for row in rows:
        cells = row.find_all("td")
        if len(cells) < 4:
            continue
        name_cell = cells[0]
        name = name_cell.get_text(strip=True)
        map_link_tag = name_cell.find("a")
        map_link = map_link_tag['href'] if map_link_tag else ""
        try:
            size = int(cells[1].get_text(strip=True))
        except ValueError:
            continue
        owner = cells[2].get_text(strip=True)
        last_login_text = cells[3].get_text(strip=True)
        try:
            last_login = datetime.strptime(last_login_text, "%d.%m.%Y (%H:%M)")
        except ValueError:
            last_login = None

        houses_list.append({
            "name": name,
            "map_link": map_link,
            "size": size,
            "owner": owner,
            "last_login": last_login_text
        })

    return houses_list

# --- CACHE BUILDING ---
async def build_cache(ctx=None):
    global cache
    houses = fetch_houses()
    cache = []
    total = len(houses)

    progress_msg = None
    if ctx:
        progress_msg = await ctx.send(f"🔄 Budowanie cache: 0/{total}")

    for idx, house in enumerate(houses, start=1):
        # Tu możesz wstawić filtr np. min level 600 i domki do przejęcia
        cache.append(house)
        if ctx and progress_msg:
            await progress_msg.edit(content=f"🔄 Budowanie cache: {idx}/{total}")

    save_cache()
    if ctx and progress_msg:
        await progress_msg.edit(content=f"✅ Cache zbudowany. Znaleziono {len(cache)} domków.")

# --- DISCORD EVENTS ---
@bot.event
async def on_ready():
    print(f"{bot.user} gotowy!")
    channel = bot.get_channel(DISCORD_CHANNEL)
    await build_cache(ctx=channel)

# --- COMMANDS ---
@bot.command()
async def status(ctx):
    if not cache:
        await ctx.send("⚠️ Cache nie był jeszcze budowany!")
        return
    await ctx.send(f"✅ Cache zbudowany. Liczba domków: {len(cache)}")

@bot.command()
async def sprawdz(ctx):
    if not cache:
        await ctx.send("⚠️ Cache nie był jeszcze budowany!")
        return

    text = ""
    for house in cache:
        text += f"{house['name']} ({house['size']}) - {house['owner']} - [Mapka]({house['map_link']})\n"

    # Discord limit 4000 znaków
    if len(text) > 4000:
        chunks = [text[i:i+4000] for i in range(0, len(text), 4000)]
        for chunk in chunks:
            await ctx.send(chunk)
    else:
        await ctx.send(text or "Brak domków spełniających kryteria.")

@bot.command()
async def info(ctx):
    msg = (
        "**Dostępne komendy:**\n"
        "`!status` - pokazuje status cache i liczbę domków\n"
        "`!sprawdz` - pokazuje wszystkie domki w cache z linkiem do mapy\n"
        "`!info` - pokazuje wszystkie komendy i opis"
    )
    await ctx.send(msg)

# --- RUN BOT ---
load_cache()
bot.run(TOKEN)
