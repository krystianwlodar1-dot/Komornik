import os
import json
import asyncio
import requests
from bs4 import BeautifulSoup
from datetime import datetime, timezone, timedelta
import discord
from discord.ext import commands, tasks
import time

# -------------------- CONFIG --------------------
TOKEN = os.environ.get("DISCORD_TOKEN")
DISCORD_CHANNEL = int(os.environ.get("DISCORD_CHANNEL", 0))

BASE_HOUSES_URL = "https://cyleria.pl/?subtopic=houses"
BASE_PLAYERS_URL = "https://cyleria.pl/?subtopic=highscores&player="

CACHE_FILE = "house_cache.json"
MIN_DAYS_ABSENCE = 10
ALERT_12_DAYS = 12
ALERT_4H_BEFORE = ALERT_12_DAYS * 24 - 4  # w godzinach (4h przed 14 dniem nieobecności)

# -------------------- BOT --------------------
intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix="!", intents=intents)

house_cache = []
alerted_10d = set()
alerted_12d = set()
alerted_4h = set()

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
    start_time = time.time()

    progress_message = None
    if channel:
        progress_message = await channel.send(f"🔄 Budowanie cache: 0/{total} (0s pozostało)")

    for i, house in enumerate(houses, 1):
        if house["owner"]:
            last_login = fetch_last_login(house["owner"])
            house["last_login"] = last_login

        if progress_message:
            elapsed = time.time() - start_time
            if i > 0:
                remaining = elapsed / i * (total - i)
            else:
                remaining = 0
            mins, secs = divmod(int(remaining), 60)
            bar = f"[{'█' * int(i/total*20):20}] {i}/{total}"
            await progress_message.edit(
                content=f"🔄 Budowanie cache: {bar} (pozostało ~{mins}m {secs}s)"
            )

    house_cache = houses
    with open(CACHE_FILE, "w", encoding="utf-8") as f:
        json.dump([h for h in house_cache], f, default=str, ensure_ascii=False)

    if channel:
        await channel.send(f"✅ Cache zbudowany. Znaleziono {len(house_cache)} domków.")

# -------------------- ALERT LOGIC --------------------
async def alert_houses(channel):
    if not house_cache:
        return

    now = datetime.now(timezone.utc)
    for house in house_cache:
        last_login = house.get("last_login")
        if not last_login or not house["owner"]:
            continue

        days_absent = (now - last_login).days
        hours_absent = (now - last_login).total_seconds() / 3600

        # 10 dni nieobecności
        if days_absent >= MIN_DAYS_ABSENCE and house["name"] not in alerted_10d:
            await channel.send(
                f"🏠 Domek do przejęcia: {house['name']} ({house['size']})\n"
                f"Właściciel: {house['owner']}\n"
                f"Ostatnie logowanie: {house['last_login'].strftime('%d.%m.%Y (%H:%M)')}\n"
                f"Mapa: {house['link']}"
            )
            alerted_10d.add(house["name"])

        # 12 dni nieobecności
        if days_absent >= ALERT_12_DAYS and house["name"] not in alerted_12d:
            await channel.send(
                f"⚠️ 12 dni nieobecności: {house['name']} ({house['size']}) "
                f"- właściciel: {house['owner']}\nMapa: {house['link']}"
            )
            alerted_12d.add(house["name"])

        # 4 godziny przed przejęciem (czyli 14 dni nieobecności)
        if ALERT_4H_BEFORE <= hours_absent < ALERT_4H_BEFORE + 1 and house["name"] not in alerted_4h:
            await channel.send(
                f"⏰ 4h do przejęcia domku: {house['name']} ({house['size']})\n"
                f"Właściciel: {house['owner']}\nMapa: {house['link']}"
            )
            alerted_4h.add(house["name"])

# -------------------- DISCORD COMMANDS --------------------
def build_progress_bar(current, total, length=20):
    filled = int(current/total * length)
    return f"[{'█'*filled}{'-'*(length-filled)}] {current}/{total}"

@bot.command()
async def sprawdz(ctx):
    if not house_cache:
        await ctx.send("⚠️ Cache nie był jeszcze budowany!")
        return

    text = ""
    now = datetime.now(timezone.utc)
    total = len(house_cache)
    progress_msg = await ctx.send(f"🔄 Sprawdzanie domków: {build_progress_bar(0,total)} (0s pozostało)")

    start_time = time.time()
    for i, house in enumerate(house_cache, 1):
        last_login = house.get("last_login")
        if last_login:
            days_absent = (now - last_login).days
            if days_absent >= MIN_DAYS_ABSENCE:
                text += f"{house['name']} ({house['size']}) - {house['owner']} - {days_absent} dni nieobecności\nMapa: {house['link']}\n\n"

        # update progress and remaining time
        if i % 2 == 0 or i == total:
            elapsed = time.time() - start_time
            remaining = elapsed / i * (total - i) if i > 0 else 0
            mins, secs = divmod(int(remaining), 60)
            await progress_msg.edit(
                content=f"🔄 Sprawdzanie domków: {build_progress_bar(i,total)} (pozostało ~{mins}m {secs}s)"
            )

    if not text:
        text = "Brak domków spełniających kryteria."
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
!info - pokazuje listę komend
"""
    await ctx.send(cmds)

# -------------------- BACKGROUND TASK --------------------
@tasks.loop(hours=1)
async def background_scan():
    channel = bot.get_channel(DISCORD_CHANNEL)
    if channel:
        await build_cache(channel)
        await alert_houses(channel)

# -------------------- BOT EVENTS --------------------
@bot.event
async def on_ready():
    print(f"Bot zalogowany jako {bot.user}")
    channel = bot.get_channel(DISCORD_CHANNEL)
    await build_cache(channel)
    await alert_houses(channel)
    background_scan.start()

# -------------------- RUN BOT --------------------
bot.run(TOKEN)
