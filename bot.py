import os
import asyncio
import json
from datetime import datetime, timezone
import requests
from bs4 import BeautifulSoup
import discord
from discord.ext import commands

# ================== CONFIG ==================
TOKEN = os.getenv("DISCORD_TOKEN")
DISCORD_CHANNEL = os.getenv("DISCORD_CHANNEL")
CACHE_FILE = "houses_cache.json"
BASE_HOUSES_URL = "https://cyleria.pl/?subtopic=houses"
BASE_HIGHSCORES_URL = "https://cyleria.pl/?subtopic=highscores"
MIN_LEVEL_FOR_HOUSE = 600
# ============================================

intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix="!", intents=intents)

cache = []

# ---------------- Helper Functions ----------------
def save_cache(data):
    with open(CACHE_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

def load_cache():
    if os.path.exists(CACHE_FILE):
        with open(CACHE_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return []

def fetch_houses():
    """Pobiera listę domków ze strony."""
    houses = []
    resp = requests.get(BASE_HOUSES_URL)
    soup = BeautifulSoup(resp.text, "html.parser")
    rows = soup.select("tr")  # każda linia tabeli
    for row in rows[1:]:  # pomijamy nagłówek
        cells = row.find_all("td")
        if len(cells) < 4:
            continue
        try:
            name = cells[0].get_text(strip=True)
            size = int(cells[1].get_text(strip=True))
            player = cells[2].get_text(strip=True)
            status = cells[3].get_text(strip=True)
            # Pobranie linku do mapki
            map_link_tag = cells[0].find("a")
            map_link = map_link_tag["href"] if map_link_tag else None

            houses.append({
                "name": name,
                "size": size,
                "player": player,
                "status": status,
                "map_link": map_link
            })
        except ValueError:
            continue
    return houses

def fetch_player_login(player_name):
    """Zwraca datetime ostatniego logowania gracza."""
    resp = requests.get(BASE_HIGHSCORES_URL)
    soup = BeautifulSoup(resp.text, "html.parser")
    rows = soup.select("tr")
    for row in rows[1:]:
        cells = row.find_all("td")
        if len(cells) < 5:
            continue
        name = cells[1].get_text(strip=True)
        if name != player_name:
            continue
        last_login_str = cells[4].get_text(strip=True)
        try:
            last_login = datetime.strptime(last_login_str, "%d.%m.%Y (%H:%M)")
            return last_login.replace(tzinfo=timezone.utc)
        except:
            return None
    return None

# ---------------- Cache Builder ----------------
async def build_cache(ctx=None):
    global cache
    houses = fetch_houses()
    total = len(houses)
    saved_houses = []

    for i, house in enumerate(houses, 1):
        saved_houses.append(house)

        # Pasek postępu liczbowy
        if ctx:
            try:
                await ctx.send(f"🔄 Budowanie cache: {i}/{total} domków")
            except:
                pass
        await asyncio.sleep(0.05)  # lekki delay

    cache = saved_houses
    save_cache(cache)

    if ctx:
        await ctx.send(f"✅ Cache gotowy! Znaleziono {len(cache)} domków.")

    return cache

# ---------------- Discord Events ----------------
@bot.event
async def on_ready():
    print(f"Zalogowano jako {bot.user}")

    # Pobranie kanału z DISCORD_CHANNEL
    ctx = None
    if DISCORD_CHANNEL:
        for guild in bot.guilds:
            ctx = discord.utils.get(guild.text_channels, name=DISCORD_CHANNEL)
            if ctx:
                break

    if ctx:
        await ctx.send("🔄 Rozpoczynam skan Cylerii...")

    # Budowanie cache przy starcie
    await build_cache(ctx=ctx)

# ---------------- Commands ----------------
@bot.command()
async def status(ctx):
    if not cache:
        await ctx.send("⚠️ Cache nie był jeszcze budowany!")
        return
    await ctx.send(f"✅ Cache gotowy, liczba domków: {len(cache)}")

@bot.command()
async def sprawdz(ctx):
    if not cache:
        await ctx.send("⚠️ Cache nie był jeszcze budowany!")
        return

    text = "🏠 Domki do przejęcia:\n"
    for house in cache:
        # tu można dodać logikę filtrowania (np. wolne domki)
        if house["status"].lower() == "aktywny" or house["player"].lower() == "brak":
            link = f" [📍]({house['map_link']})" if house["map_link"] else ""
            text += f"{house['name']} - {house['size']} - {house['player']}{link}\n"

    await ctx.send(text or "Brak domków spełniających kryteria.")

@bot.command()
async def info(ctx):
    text = (
        "📝 **Dostępne komendy:**\n"
        "`!status` - Sprawdza czy cache został zbudowany.\n"
        "`!sprawdz` - Pokazuje domki dostępne do przejęcia z linkami do mapy.\n"
        "`!info` - Pokazuje listę wszystkich komend i opis ich działania."
    )
    await ctx.send(text)

# ---------------- Run Bot ----------------
if not TOKEN:
    print("❌ Brak tokena! Ustaw DISCORD_TOKEN w zmiennych środowiskowych.")
else:
    bot.run(TOKEN)
