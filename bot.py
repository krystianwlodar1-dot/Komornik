import os
import json
import asyncio
import requests
from bs4 import BeautifulSoup
from datetime import datetime, timezone, timedelta
import discord
from discord.ext import commands, tasks

# -------------------- CONFIG --------------------
TOKEN = os.environ.get("DISCORD_TOKEN")
DISCORD_CHANNEL = int(os.environ.get("DISCORD_CHANNEL", 0))

BASE_HOUSES_URL = "https://cyleria.pl/?subtopic=houses"
BASE_PLAYERS_URL = "https://cyleria.pl/?subtopic=highscores&player="

CACHE_FILE = "house_cache.json"
MIN_DAYS_ABSENCE = 10
ALERT_12_DAYS = 12
ALERT_4H_BEFORE = ALERT_12_DAYS * 24 - 4  # w godzinach

# -------------------- BOT --------------------
intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix="!", intents=intents)

house_cache = []

# -------------------- FETCHING FUNCTIONS --------------------
def fetch_houses():
    resp = requests.get(BASE_HOUSES_URL)
    resp.raise_for_status()
    soup = BeautifulSoup(resp.text, "html.parser")
    houses = []

    rows = soup.select("table tr")[1:]  # pomijamy nagłówek
    for row in rows:
        cells = row.find_all("td")
        if len(cells) < 3:
            continue
        house_name = cells[0].get_text(strip=True)
        size_text = cells[1].get_text(strip=True)
        owner = cells[2].get_text(strip=True)

        try:
            size = int(size_text)
        except ValueError:
            size = None

        houses.append({
            "name": house_name,
            "size": size,
            "owner": owner if owner else None,
            "link": f"https://cyleria.pl/?subtopic=houses&row={house_name.replace(' ', '%20')}",
            "last_login": None
        })
    return houses

def fetch_last_login(player_name):
    url = BASE_PLAYERS_URL + player_name
    resp = requests.get(url)
    resp.raise_for_status()
    soup = BeautifulSoup(resp.text, "html.parser")
    login_text_elem = soup.find(string=lambda s: s and "Logowanie:" in s)
    if login_text_elem:
        try:
            login_text = login_text_elem.split("Logowanie:")[-1].strip()
            last_login = datetime.strptime(login_text, "%d.%m.%Y (%H:%M)")
            return last_login.replace(tzinfo=timezone.utc)
        except ValueError:
            return None
    return None

# -------------------- CACHE BUILDING --------------------
async def build_cache(channel=None):
    global house_cache
    houses = fetch_houses()
    total = len(houses)
    progress_message = None

    if channel:
        progress_message = await channel.send(f"🔄 Budowanie cache: 0/{total}")

    for i, house in enumerate(houses, 1):
        if house["owner"]:
            last_login = fetch_last_login(house["owner"])
            house["last_login"] = last_login
        if progress_message:
            await progress_message.edit(content=f"🔄 Budowanie cache: {i}/{total}")

    house_cache = houses
    with open(CACHE_FILE, "w", encoding="utf-8") as f:
        json.dump([h for h in house_cache], f, default=str, ensure_ascii=False)

    if channel:
        await channel.send(f"✅ Cache zbudowany. Znaleziono {len(house_cache)} domków.")

# -------------------- ALERT LOGIC --------------------
async def alert_new_houses(channel):
    if not house_cache:
        return

    # wczytaj poprzedni cache, jeśli istnieje
    previous = []
    if os.path.exists(CACHE_FILE):
        with open(CACHE_FILE, "r", encoding="utf-8") as f:
            previous = json.load(f)

    previous_names = {h["name"] for h in previous}
    new_houses = []

    now = datetime.now(timezone.utc)
    for house in house_cache:
        last_login = house.get("last_login")
        if last_login and house["name"] not in previous_names:
            days_absent = (now - last_login).days
            if days_absent >= MIN_DAYS_ABSENCE:
                new_houses.append(house)

    for house in new_houses:
        await channel.send(
            f"🏠 Nowy domek do przejęcia: {house['name']} ({house['size']}), "
            f"Właściciel: {house['owner']}, Ostatnie logowanie: {house['last_login'].strftime('%d.%m.%Y (%H:%M)')}\n"
            f"Mapa: {house['link']}"
        )

# -------------------- DISCORD COMMANDS --------------------
@bot.command()
async def sprawdz(ctx):
    if not house_cache:
        await ctx.send("⚠️ Cache nie był jeszcze budowany!")
        return

    now = datetime.now(timezone.utc)
    text = ""
    for house in house_cache:
        last_login = house.get("last_login")
        if last_login:
            days_absent = (now - last_login).days
            if days_absent >= MIN_DAYS_ABSENCE:
                text += f"{house['name']} ({house['size']}) - {house['owner']} - {days_absent} dni nieobecności\nMapa: {house['link']}\n\n"

    if not text:
        text = "Brak domków spełniających kryteria."

    # Discord ma limit 4000 znaków na wiadomość
    for i in range(0, len(text), 4000):
        await ctx.send(text[i:i+4000])

@bot.command()
async def status(ctx):
    if not house_cache:
        await ctx.send("⚠️ Cache nie był jeszcze budowany!")
        return
    await ctx.send(f"✅ Cache gotowy. Znaleziono {len(house_cache)} domków.")

@bot.command()
async def info(ctx):
    cmds = """
**Dostępne komendy:**
!sprawdz - sprawdza domki do przejęcia (min. 10 dni nieobecności)
!status - pokazuje status cache
!info - pokazuje tę wiadomość z listą komend
"""
    await ctx.send(cmds)

# -------------------- BACKGROUND TASK --------------------
@tasks.loop(hours=1)
async def background_scan():
    channel = bot.get_channel(DISCORD_CHANNEL)
    if channel:
        await build_cache(channel)
        await alert_new_houses(channel)

# -------------------- BOT EVENTS --------------------
@bot.event
async def on_ready():
    print(f"Bot zalogowany jako {bot.user}")
    channel = bot.get_channel(DISCORD_CHANNEL)
    await build_cache(channel)
    await alert_new_houses(channel)
    background_scan.start()

# -------------------- RUN BOT --------------------
bot.run(TOKEN)
