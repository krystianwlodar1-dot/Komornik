import discord
from discord.ext import commands, tasks
import requests
from bs4 import BeautifulSoup
import asyncio
import json
from datetime import datetime, timezone

TOKEN = "TWÓJ_DISCORD_TOKEN"
GUILD_ID = 123456789012345678  # ID serwera Discord
CHANNEL_ID = 123456789012345678  # Kanał, na którym bot będzie wysyłał alerty

HOUSES_URL = "https://cyleria.pl/?subtopic=houses"
HIGHSCORES_URL = "https://cyleria.pl/?subtopic=highscores"
CACHE_FILE = "cache.json"
MIN_LEVEL = 600

intents = discord.Intents.default()
bot = commands.Bot(command_prefix="!", intents=intents)

cache = {}

# ------------------ pomocnicze funkcje ------------------

def save_cache():
    with open(CACHE_FILE, "w", encoding="utf-8") as f:
        json.dump(cache, f, ensure_ascii=False, indent=2)

def load_cache():
    global cache
    try:
        with open(CACHE_FILE, "r", encoding="utf-8") as f:
            cache = json.load(f)
    except FileNotFoundError:
        cache = {}

def parse_date(date_str):
    try:
        return datetime.strptime(date_str, "%d.%m.%Y (%H:%M)").replace(tzinfo=timezone.utc)
    except Exception:
        return None

def fetch_houses():
    resp = requests.get(HOUSES_URL)
    soup = BeautifulSoup(resp.text, "html.parser")
    houses_list = []

    rows = soup.select("table tr")[1:]  # pomijamy nagłówek
    for row in rows:
        cols = row.find_all("td")
        if len(cols) < 4:
            continue
        address = cols[0].get_text(strip=True)
        size = int(cols[1].get_text(strip=True))
        player_name = cols[2].get_text(strip=True)
        last_login_text = cols[3].get_text(strip=True)
        last_login = parse_date(last_login_text)
        houses_list.append({
            "address": address,
            "size": size,
            "player": player_name,
            "last_login": last_login
        })
    return houses_list

def fetch_players():
    resp = requests.get(HIGHSCORES_URL)
    soup = BeautifulSoup(resp.text, "html.parser")
    players = {}
    rows = soup.select("table tr")[1:]
    for row in rows:
        cols = row.find_all("td")
        if len(cols) < 3:
            continue
        rank = int(cols[0].get_text(strip=True))
        name = cols[1].get_text(strip=True)
        level = int(cols[2].get_text(strip=True))
        players[name] = level
    return players

async def build_cache(channel):
    global cache
    houses = fetch_houses()
    players = fetch_players()
    filtered = []

    total = len(houses)
    await channel.send(f"🔄 Rozpoczynam skan Cylerii... {total} domków do sprawdzenia.")

    for i, house in enumerate(houses, start=1):
        player_name = house["player"]
        level = players.get(player_name, 0)
        if level >= MIN_LEVEL:
            filtered.append(house)
        # Pasek postępu
        progress = int((i / total) * 20)
        bar = "█" * progress + "-" * (20 - progress)
        await channel.send(f"`[{bar}] {i}/{total}`", delete_after=3)  # krótko pokazuje pasek
        await asyncio.sleep(0.1)  # delikatne opóźnienie, żeby nie spamować serwera

    cache = {"houses": filtered, "timestamp": datetime.utcnow().isoformat()}
    save_cache()
    await channel.send(f"✅ Skan zakończony! Znaleziono {len(filtered)} domków spełniających kryteria.")

# ------------------ komendy ------------------

@bot.command()
async def status(ctx):
    if not cache.get("houses"):
        await ctx.send("Cache nie był jeszcze budowany.")
        return
    ts = cache.get("timestamp", "brak")
    await ctx.send(f"Cache ostatnio budowany: {ts}, liczba domków w cache: {len(cache['houses'])}")

@bot.command()
async def sprawdz(ctx):
    if not cache.get("houses"):
        await ctx.send("Cache nie był jeszcze budowany.")
        return
    lines = []
    for house in cache["houses"]:
        login_str = house["last_login"].strftime("%d.%m.%Y (%H:%M)") if house["last_login"] else "brak"
        lines.append(f"{house['address']}  {house['size']}  {house['player']}  {login_str}")
    msg = "```" + "\n".join(lines[:50]) + "```"  # max 50 wierszy
    await ctx.send(msg)

@bot.command()
async def ultra(ctx):
    if not cache.get("houses"):
        await ctx.send("Cache nie był jeszcze budowany.")
        return
    lines = []
    for house in cache["houses"]:
        login = house["last_login"]
        days_offline = (datetime.now(timezone.utc) - login).days if login else 0
        if days_offline >= 10:
            lines.append(f"{house['address']}  {house['size']}  {house['player']}  {login.strftime('%d.%m.%Y (%H:%M)')}")
    msg = "```" + "\n".join(lines[:50]) + "```"
    await ctx.send(msg)

# ------------------ start bota ------------------

@bot.event
async def on_ready():
    print(f"Zalogowano jako {bot.user}")
    load_cache()
    channel = bot.get_channel(CHANNEL_ID)
    if channel:
        await build_cache(channel)

bot.run(TOKEN)
