# bot.py
import os
import discord
from discord.ext import commands, tasks
import requests
from bs4 import BeautifulSoup
from datetime import datetime, timezone
import json
import asyncio

BASE_URL_HOUSES = "https://cyleria.pl/?subtopic=houses"
CACHE_FILE = "cache.json"

# Pobranie tokena z env variable
TOKEN = os.environ.get("TOKEN")  # <-- w Railway ustaw zmienną środowiskową o nazwie TOKEN

if not TOKEN:
    raise ValueError("Nie ustawiono tokena bota! Ustaw zmienną środowiskową TOKEN na Railway.")

intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix="!", intents=intents)

cache = {}

# ------------------------
# Funkcja do zapisu cache
def save_cache():
    with open(CACHE_FILE, "w", encoding="utf-8") as f:
        json.dump(cache, f, ensure_ascii=False, indent=4)

# ------------------------
# Funkcja do wczytania cache
def load_cache():
    global cache
    try:
        with open(CACHE_FILE, "r", encoding="utf-8") as f:
            cache = json.load(f)
    except FileNotFoundError:
        cache = {}

# ------------------------
# Funkcja pobierająca wszystkie domki
def get_all_houses():
    resp = requests.get(BASE_URL_HOUSES)
    resp.raise_for_status()
    soup = BeautifulSoup(resp.text, "html.parser")
    houses = []

    rows = soup.select("tr")
    for row in rows:
        cols = row.find_all("td")
        if not cols or len(cols) < 3:
            continue
        try:
            house_name = cols[0].text.strip()
            size = int(cols[1].text.strip())
            player_name = cols[2].text.strip()
            last_login_text = row.find(text=lambda t: "Logowanie:" in t)
            if last_login_text:
                last_login_str = last_login_text.split(":")[1].strip()
                last_login = datetime.strptime(last_login_str, "%d.%m.%Y (%H:%M)")
                last_login = last_login.replace(tzinfo=timezone.utc)
            else:
                last_login_str = None

            houses.append({
                "name": house_name,
                "size": size,
                "player": player_name,
                "last_login": last_login_str
            })
        except Exception:
            continue
    return houses

# ------------------------
# Funkcja do aktualizacji cache
async def update_cache_channel(ctx=None):
    global cache
    print("🔄 Rozpoczynam skan Cylerii...")

    houses = get_all_houses()
    total = len(houses)
    cache["houses"] = []

    for i, house in enumerate(houses, start=1):
        cache["houses"].append(house)
        progress = (i / total) * 100
        print(f"Budowanie cache: {i}/{total} ({progress:.1f}%)", end="\r")
        await asyncio.sleep(0)

    save_cache()
    print("\n✅ Cache gotowy –", total, "domków.")

    if ctx:
        await ctx.send(f"✅ Cache zaktualizowany – {total} domków.")

# ------------------------
# Komenda sprawdzająca cache
@bot.command()
async def sprawdz(ctx):
    load_cache()
    houses = cache.get("houses", [])
    if not houses:
        await ctx.send("Cache nie był jeszcze budowany.")
        return

    msg = "🏠 Domki w cache:\n"
    for h in houses:
        msg += f"{h['name']} | {h['size']} | {h['player']} | {h['last_login']}\n"
    await ctx.send(msg)

# ------------------------
# Komenda pokazująca status cache
@bot.command()
async def status(ctx):
    load_cache()
    houses = cache.get("houses", [])
    if not houses:
        await ctx.send("Cache nie był jeszcze budowany.")
    else:
        await ctx.send(f"✅ Cache gotowy – {len(houses)} domków.")

# ------------------------
# Automatyczne budowanie cache przy starcie
@bot.event
async def on_ready():
    print(f"Zalogowano jako {bot.user}")
    channel = None
    # channel = bot.get_channel(ID_KANAŁU)
    await update_cache_channel(ctx=channel)

# ------------------------
# Start bota
bot.run(TOKEN)
