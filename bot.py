import os
import asyncio
import json
from datetime import datetime, timezone
import requests
from bs4 import BeautifulSoup
import discord
from discord.ext import commands

# Pobieranie tokena i kanału z Railway environment variables
TOKEN = os.environ.get("DISCORD_TOKEN")
CHANNEL_ID = int(os.environ.get("DISCORD_CHANNEL_ID", 0))

if not TOKEN:
    raise ValueError("Token bota nie został ustawiony w Railway variables jako DISCORD_TOKEN")

# Stałe
BASE_HOUSES_URL = "https://cyleria.pl/?subtopic=houses"
BASE_HIGHSCORES_URL = "https://cyleria.pl/?subtopic=highscores"
CACHE_FILE = "cache.json"
MIN_LEVEL = 600

intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix="!", intents=intents)

cache = []

# --------- FUNKCJE POMOCNICZE ---------
def save_cache():
    with open(CACHE_FILE, "w", encoding="utf-8") as f:
        json.dump(cache, f, ensure_ascii=False, indent=2)

def load_cache():
    global cache
    if os.path.exists(CACHE_FILE):
        with open(CACHE_FILE, "r", encoding="utf-8") as f:
            cache = json.load(f)
    else:
        cache = []

def parse_login_date(date_str):
    try:
        return datetime.strptime(date_str, "%d.%m.%Y (%H:%M)").replace(tzinfo=timezone.utc)
    except:
        return None

def fetch_houses():
    resp = requests.get(BASE_HOUSES_URL)
    soup = BeautifulSoup(resp.text, "html.parser")
    houses = []

    # każdy domek w tabeli
    for row in soup.select("tr"):
        cells = row.find_all("td")
        if len(cells) < 4:
            continue
        name = cells[0].get_text(strip=True)

        # Pobranie linku do mapy (pinezka)
        link_tag = cells[0].find("a")
        link = link_tag['href'] if link_tag else None

        size = int(cells[1].get_text(strip=True))
        player = cells[2].get_text(strip=True)
        login_text = cells[3].get_text(strip=True)
        last_login = parse_login_date(login_text.replace("Logowanie:", "").strip())
        houses.append({
            "name": name,
            "link": link,
            "size": size,
            "player": player,
            "last_login": login_text,
            "last_login_dt": last_login
        })
    return houses

def fetch_player_level(player_name):
    resp = requests.get(BASE_HIGHSCORES_URL)
    soup = BeautifulSoup(resp.text, "html.parser")
    for row in soup.select("tr"):
        cells = row.find_all("td")
        if len(cells) < 2:
            continue
        nick = cells[1].get_text(strip=True)
        level = int(cells[2].get_text(strip=True))
        if nick.lower() == player_name.lower():
            return level
    return 0

# --------- BUILD CACHE ---------
async def build_cache(ctx=None):
    global cache
    print("🔄 Rozpoczynam skan Cylerii...")
    cache = []
    houses = fetch_houses()

    total = len(houses)
    done = 0
    progress_bar_length = 20

    for house in houses:
        level = fetch_player_level(house["player"])
        if level >= MIN_LEVEL:
            cache.append(house)

        done += 1
        # Pasek postępu w konsoli
        progress = int(progress_bar_length * done / total)
        bar = "█" * progress + "-" * (progress_bar_length - progress)
        print(f"[{bar}] {done}/{total} domków", end="\r")
        await asyncio.sleep(0.1)

    print("\n✅ Cache gotowy –", len(cache), "domków spełniających kryteria")
    save_cache()

    # Alert w kanale Discord
    if ctx and len(cache) > 0:
        msg = "⚠️ Są domki do przejęcia!\n"
        for h in cache:
            link_text = f" [Mapa]({h['link']})" if h['link'] else ""
            msg += f"{h['name']} ({h['player']}){link_text} - Logowanie: {h['last_login']}\n"
        await ctx.send(msg)

# --------- EVENTY ---------
@bot.event
async def on_ready():
    print(f"Zalogowano jako {bot.user}")
    channel = bot.get_channel(CHANNEL_ID)
    if channel:
        await build_cache(ctx=channel)

# --------- KOMENDY ---------
@bot.command()
async def sprawdz(ctx):
    if not cache:
        await ctx.send("Cache nie był jeszcze budowany.")
        return
    msg = "🏠 Domki spełniające kryteria:\n"
    for house in cache:
        link_text = f" [Mapa]({house['link']})" if house['link'] else ""
        msg += f"{house['name']} ({house['player']}){link_text} - Logowanie: {house['last_login']}\n"
    await ctx.send(msg)

@bot.command()
async def status(ctx):
    if not cache:
        await ctx.send("Cache nie był jeszcze budowany.")
        return
    msg = f"✅ Cache zawiera {len(cache)} domków spełniających kryteria."
    await ctx.send(msg)

# --------- START BOTA ---------
load_cache()
bot.run(TOKEN)
