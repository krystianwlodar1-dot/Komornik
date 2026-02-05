import discord
from discord.ext import commands
import requests
from bs4 import BeautifulSoup
import asyncio
from datetime import datetime, timezone
import json
import os

# =======================
# Zmienne środowiskowe
# =======================
TOKEN = os.getenv("TOKEN")
BASE_HOUSES_URL = "https://cyleria.pl/?subtopic=houses"
BASE_HIGHSCORES_URL = "https://cyleria.pl/?subtopic=highscores"
CACHE_FILE = "cache.json"

intents = discord.Intents.default()
intents.message_content = True  # ważne dla komend

bot = commands.Bot(command_prefix="!", intents=intents)

# =======================
# Funkcje pomocnicze
# =======================

def parse_login_date(text):
    """Konwertuje datę logowania na datetime"""
    try:
        return datetime.strptime(text, "%d.%m.%Y (%H:%M)").replace(tzinfo=timezone.utc)
    except Exception:
        return None

def fetch_houses():
    """Pobiera listę domków ze strony"""
    resp = requests.get(BASE_HOUSES_URL)
    soup = BeautifulSoup(resp.text, "html.parser")
    houses = []

    for row in soup.select("tr"):
        cells = row.find_all("td")
        if len(cells) < 4:
            continue

        name = cells[0].get_text(strip=True)
        link_tag = cells[0].find("a")
        link = link_tag['href'] if link_tag else None

        try:
            size = int(cells[1].get_text(strip=True))
        except ValueError:
            continue  # pomija niepoprawne wiersze

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

def save_cache(houses):
    with open(CACHE_FILE, "w", encoding="utf-8") as f:
        json.dump(houses, f, ensure_ascii=False, indent=2)

def load_cache():
    if not os.path.exists(CACHE_FILE):
        return []
    with open(CACHE_FILE, "r", encoding="utf-8") as f:
        return json.load(f)

# =======================
# Budowanie cache z postępem
# =======================

async def build_cache(ctx=None):
    houses = fetch_houses()
    total = len(houses)
    saved_houses = []

    for i, house in enumerate(houses, 1):
        saved_houses.append(house)

        # Pasek postępu liczbowy w Discordzie
        if ctx:
            progress_text = f"Budowanie cache: {i}/{total} domków"
            await ctx.send(progress_text)

        await asyncio.sleep(0.1)

    save_cache(saved_houses)
    return saved_houses

# =======================
# Komendy
# =======================

@bot.command()
async def status(ctx):
    """Pokazuje ilość domków w cache"""
    houses = load_cache()
    if not houses:
        await ctx.send("Cache nie był jeszcze budowany.")
        return
    await ctx.send(f"Cache zawiera {len(houses)} domków.")

@bot.command()
async def sprawdz(ctx):
    """Pokazuje listę domków z cache i linkiem do mapki"""
    houses = load_cache()
    if not houses:
        await ctx.send("Cache nie był jeszcze budowany.")
        return

    msg = "**Domek do przejęcia:**\n"
    for house in houses:
        msg += f"{house['name']} ({house['size']}) - {house['player']} - Logowanie: {house['last_login']}"
        if house['link']:
            msg += f" [Mapa]({house['link']})"
        msg += "\n"

    await ctx.send(msg)

@bot.command()
async def info(ctx):
    """Pokazuje listę komend i opis co robią"""
    msg = (
        "**Komendy bota:**\n"
        "`!status` - Pokazuje liczbę domków w cache.\n"
        "`!sprawdz` - Wyświetla listę domków wraz z linkiem do mapki.\n"
        "`!info` - Pokazuje listę wszystkich komend i opis ich działania.\n"
    )
    await ctx.send(msg)

# =======================
# Event on_ready
# =======================

@bot.event
async def on_ready():
    print(f"Zalogowano jako {bot.user}")
    channel = discord.utils.get(bot.get_all_channels(), name="general")  # zmień na swój kanał
    if channel:
        await channel.send("🔄 Rozpoczynam skan Cylerii...")
        await build_cache(ctx=channel)
        await channel.send("✅ Cache gotowy!")

# =======================
# Start bota
# =======================

bot.run(TOKEN)
