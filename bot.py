import os
import json
import asyncio
from datetime import datetime, timezone, timedelta
import requests
from bs4 import BeautifulSoup
import discord
from discord.ext import commands, tasks

# -------------------------------
# Konfiguracja z Variables (Railway)
# -------------------------------
TOKEN = os.getenv("TOKEN")
DISCORD_CHANNEL = int(os.getenv("DISCORD_CHANNEL", 0))

HOUSES_URL = "https://cyleria.pl/?subtopic=houses"

CACHE_FILE = "cache.json"
INACTIVE_DAYS_SPRAWDZ = 10    # próg dla komendy !sprawdz
ALERT_DAYS = 12               # próg dla alertu 12-dni
ALERT_HOURS_TO_14 = 4         # próg godzin do 14 dni
SCAN_INTERVAL_MINUTES = 30     # co ile minut skanujemy

# -------------------------------
# Discord bot
# -------------------------------
intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix="!", intents=intents)

houses_cache = []

# -------------------------------
# Funkcje pomocnicze
# -------------------------------
def parse_last_login(last_login_str):
    if not last_login_str:
        return None
    try:
        return datetime.strptime(last_login_str, "%d.%m.%Y (%H:%M)").replace(tzinfo=timezone.utc)
    except Exception as e:
        print(f"⚠️ Błąd przy parsowaniu daty logowania: {last_login_str} -> {e}")
        return None

def is_house_takeable(last_login_str, days_threshold: int) -> bool:
    last_login = parse_last_login(last_login_str)
    if not last_login:
        return True
    offline_days = (datetime.now(timezone.utc) - last_login).days
    return offline_days >= days_threshold

def hours_to_days_threshold(last_login_str, target_days: int) -> float:
    last_login = parse_last_login(last_login_str)
    if not last_login:
        return 0
    target_time = last_login + timedelta(days=target_days)
    remaining_hours = (target_time - datetime.now(timezone.utc)).total_seconds() / 3600
    return remaining_hours

def fetch_houses():
    resp = requests.get(HOUSES_URL)
    soup = BeautifulSoup(resp.text, "html.parser")
    table = soup.find("table")
    houses = []
    if not table:
        return houses
    rows = table.find_all("tr")[1:]  # pomijamy nagłówek
    for row in rows:
        cells = row.find_all("td")
        if len(cells) < 4:
            continue
        name = cells[0].get_text(strip=True)
        size_text = cells[1].get_text(strip=True)
        try:
            size = int(size_text)
        except ValueError:
            size = 0
        owner = cells[2].get_text(strip=True)
        last_login = cells[3].get_text(strip=True)
        map_link_tag = cells[0].find("a")
        map_link = map_link_tag['href'] if map_link_tag else ""
        houses.append({
            "name": name,
            "size": size,
            "owner": owner,
            "last_login": last_login,
            "map_link": map_link
        })
    return houses

def load_previous_cache():
    if not os.path.exists(CACHE_FILE):
        return []
    with open(CACHE_FILE, "r", encoding="utf-8") as f:
        return json.load(f)

def save_cache():
    with open(CACHE_FILE, "w", encoding="utf-8") as f:
        json.dump(houses_cache, f, ensure_ascii=False, indent=2)

# -------------------------------
# Funkcje alertów
# -------------------------------
async def send_new_alerts(channel):
    previous_cache = load_previous_cache()
    previous_names = {h['name'] for h in previous_cache}

    new_takeable = [h for h in houses_cache if h['name'] not in previous_names and is_house_takeable(h['last_login'], ALERT_DAYS)]
    for house in new_takeable:
        text = f"🏠 Domek do przejęcia (12 dni nieobecności): **{house['name']}**\n"
        text += f"Właściciel: {house['owner']} (ostatnie logowanie: {house['last_login']})\n"
        if house['map_link']:
            text += f"[Mapa]({house['map_link']})"
        await channel.send(text)

async def send_4h_alerts(channel):
    for house in houses_cache:
        remaining_hours = hours_to_days_threshold(house['last_login'], ALERT_DAYS+2)  # 14 dni
        if 0 < remaining_hours <= ALERT_HOURS_TO_14:
            text = f"⚠️ Domek **{house['name']}** jest 4h od możliwości przejęcia!\n"
            text += f"Właściciel: {house['owner']} (ostatnie logowanie: {house['last_login']})\n"
            if house['map_link']:
                text += f"[Mapa]({house['map_link']})"
            await channel.send(text)

# -------------------------------
# Budowanie cache
# -------------------------------
async def build_cache(ctx=None):
    global houses_cache
    houses = fetch_houses()
    total = len(houses)
    if total == 0:
        houses_cache = []
        if ctx:
            await ctx.send("⚠️ Nie znaleziono żadnych domków!")
        return

    houses_cache = []
    message = None
    if ctx:
        message = await ctx.send(f"🔄 Budowanie cache: 0/{total}")
    for i, house in enumerate(houses, start=1):
        houses_cache.append(house)
        if message:
            await message.edit(content=f"🔄 Budowanie cache: {i}/{total}")
        await asyncio.sleep(0.05)
    save_cache()
    if message:
        await message.edit(content=f"✅ Cache zbudowany. Znaleziono {total} domków.")

# -------------------------------
# Komendy
# -------------------------------
@bot.command()
async def status(ctx):
    if not houses_cache:
        await ctx.send("⚠️ Cache nie był jeszcze budowany!")
        return
    total = len(houses_cache)
    takeable = sum(1 for h in houses_cache if is_house_takeable(h["last_login"], INACTIVE_DAYS_SPRAWDZ))
    await ctx.send(f"ℹ️ Cache gotowy: {total} domków, {takeable} dostępnych (próg {INACTIVE_DAYS_SPRAWDZ} dni).")

@bot.command()
async def sprawdz(ctx):
    if not houses_cache:
        await ctx.send("⚠️ Cache nie był jeszcze budowany!")
        return
    lines = []
    for house in houses_cache:
        if is_house_takeable(house["last_login"], INACTIVE_DAYS_SPRAWDZ):
            line = f"🏠 **{house['name']}** ({house['size']}) - {house['owner']} - {house['last_login']}"
            if house['map_link']:
                line += f" [Mapa]({house['map_link']})"
            lines.append(line)
    if not lines:
        await ctx.send("Brak domków spełniających kryteria.")
        return
    chunk_size = 2000
    msg = ""
    for line in lines:
        if len(msg)+len(line)+1 > chunk_size:
            await ctx.send(msg)
            msg = ""
        msg += line + "\n"
    if msg:
        await ctx.send(msg)

@bot.command()
async def info(ctx):
    text = (
        "**Dostępne komendy:**\n"
        "`!status` - pokazuje stan cache i liczbę dostępnych domków\n"
        "`!sprawdz` - lista domków możliwych do przejęcia (próg 10 dni nieobecności)\n"
        "`!info` - opis wszystkich komend\n"
    )
    await ctx.send(text)

# -------------------------------
# Cykliczny skan
# -------------------------------
@tasks.loop(minutes=SCAN_INTERVAL_MINUTES)
async def periodic_scan():
    channel = bot.get_channel(DISCORD_CHANNEL)
    if not channel:
        print(f"⚠️ Nie znaleziono kanału {DISCORD_CHANNEL}")
        return
    await build_cache(ctx=channel)
    await send_new_alerts(channel)
    await send_4h_alerts(channel)

# -------------------------------
# Eventy
# -------------------------------
@bot.event
async def on_ready():
    print(f"Zalogowano jako {bot.user}")
    channel = bot.get_channel(DISCORD_CHANNEL)
    await build_cache(ctx=channel)
    await send_new_alerts(channel)
    await send_4h_alerts(channel)
    periodic_scan.start()

# -------------------------------
# Uruchomienie bota
# -------------------------------
bot.run(TOKEN)
