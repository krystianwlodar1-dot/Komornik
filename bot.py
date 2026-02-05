import os
import json
import asyncio
from datetime import datetime, timezone
import requests
from bs4 import BeautifulSoup
import discord
from discord.ext import commands, tasks

# --- Token i klient ---
TOKEN = os.getenv("TOKEN")
if not TOKEN:
    raise ValueError("Brak tokena! Ustaw zmienną środowiskową TOKEN.")

intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix="!", intents=intents)

CACHE_FILE = "cache.json"

# --- Funkcje pobierania danych ---
BASE_URL = "https://przyklad-strony-domkow.com"

def get_all_houses():
    """Pobiera listę wszystkich domków z serwisu."""
    resp = requests.get(BASE_URL)
    soup = BeautifulSoup(resp.text, "html.parser")
    houses = []

    for row in soup.select("tr"):  # dopasuj selektor do tabeli
        cols = row.find_all("td")
        if len(cols) < 3:
            continue
        adres = cols[0].text.strip()
        size = int(cols[1].text.strip())
        player = cols[2].text.strip()
        last_login_text = cols[3].text.strip() if len(cols) > 3 else None
        try:
            last_login = datetime.strptime(last_login_text, "%d.%m.%Y (%H:%M)").replace(tzinfo=timezone.utc) if last_login_text else None
        except:
            last_login = None
        houses.append({
            "adres": adres,
            "size": size,
            "player": player,
            "last_login": last_login_text,
            "last_login_dt": last_login
        })
    return houses

# --- Cache ---
def save_cache(houses):
    with open(CACHE_FILE, "w", encoding="utf-8") as f:
        json.dump(houses, f, ensure_ascii=False, indent=2)

def load_cache():
    if os.path.exists(CACHE_FILE):
        with open(CACHE_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return []

# --- Pasek postępu ---
def progress_bar(done, total, length=20):
    filled = int(length * done / total) if total else length
    bar = "█" * filled + "-" * (length - filled)
    return f"[{bar}] {done}/{total}"

# --- Aktualizacja cache ---
async def update_cache_channel(ctx=None):
    houses = get_all_houses()
    total = len(houses)
    done = 0

    filtered_houses = []
    message = None

    if ctx:
        message = await ctx.send(f"🔄 Rozpoczynam skan Cylerii...\n{progress_bar(done, total)}")

    for h in houses:
        await asyncio.sleep(0.1)  # limit requestów
        done += 1
        # filtr minimalny poziom: zakładamy, że size = poziom (przykład)
        if h["size"] >= 600:
            filtered_houses.append(h)
        if message:
            eta = ((datetime.now(timezone.utc) - datetime.now(timezone.utc)).total_seconds() / done * (total - done)) if done else 0
            await message.edit(content=f"🔄 Rozpoczynam skan Cylerii...\n{progress_bar(done, total)}\nETA: ~{int(eta)}s")

    save_cache(filtered_houses)

    if ctx:
        await ctx.send(f"✅ Cache gotowy – {len(filtered_houses)} domków spełniających kryteria!")

# --- Komendy ---
@bot.command()
async def status(ctx):
    cache = load_cache()
    if not cache:
        await ctx.send("Cache nie był jeszcze budowany.")
        return
    await ctx.send(f"Cache gotowy – {len(cache)} domków.")

@bot.command()
async def sprawdz(ctx):
    cache = load_cache()
    if not cache:
        await ctx.send("Cache nie był jeszcze budowany.")
        return
    msg = "Domki do przejęcia:\n"
    for h in cache:
        msg += f"{h['adres']} ({h['size']} lvl) – {h['player']} – logowanie: {h['last_login']}\n"
    await ctx.send(msg or "Brak domków do przejęcia.")

@bot.command()
async def ultra(ctx):
    cache = load_cache()
    if not cache:
        await ctx.send("Cache nie był jeszcze budowany.")
        return
    msg = "Ultra domki (600+ lvl, 10+ dni offline):\n"
    now = datetime.now(timezone.utc)
    for h in cache:
        if not h["last_login_dt"]:
            continue
        offline_days = (now - h["last_login_dt"]).days
        if h["size"] >= 600 and offline_days >= 10:
            msg += f"{h['adres']} ({h['size']} lvl) – {h['player']} – offline {offline_days} dni\n"
    await ctx.send(msg or "Brak ultra domków.")

# --- Automatyczne budowanie cache po starcie ---
@bot.event
async def on_ready():
    print(f"Zalogowano jako {bot.user}")
    channel_id = int(os.getenv("CHANNEL_ID", "123456789"))  # ustaw kanal do alertów
    channel = bot.get_channel(channel_id)
    if channel:
        await update_cache_channel(ctx=channel)

# --- Start ---
bot.run(TOKEN)
