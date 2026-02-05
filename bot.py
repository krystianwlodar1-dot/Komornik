import os
import asyncio
import json
from datetime import datetime, timedelta, timezone
import requests
from bs4 import BeautifulSoup
import discord
from discord.ext import commands, tasks

TOKEN = os.environ.get("TOKEN")
DISCORD_CHANNEL = int(os.environ.get("CHANNEL_ID", 0))

CACHE_FILE = "cache.json"
MIN_OFFLINE_DAYS = 10

BASE_HOUSES_URL = "https://cyleria.pl/?subtopic=houses"
BASE_PLAYERS_URL = "https://cyleria.pl/?subtopic=highscores"
MAP_LINK = "https://cyleria.pl/map?house="  # dodaj id domku jeśli jest

intents = discord.Intents.default()
intents.message_content = True

bot = commands.Bot(command_prefix="!", intents=intents)

cache = {}
new_houses_alerted = set()

# ------------------------ Utils ------------------------
def save_cache():
    with open(CACHE_FILE, "w", encoding="utf-8") as f:
        json.dump(cache, f, ensure_ascii=False, indent=2)

def load_cache():
    global cache
    if os.path.exists(CACHE_FILE):
        with open(CACHE_FILE, "r", encoding="utf-8") as f:
            cache = json.load(f)
    else:
        cache = {}

def fetch_houses():
    resp = requests.get(BASE_HOUSES_URL)
    soup = BeautifulSoup(resp.text, "html.parser")
    houses = []
    rows = soup.select("table tr")[1:]  # zakładam, że tabela ma nagłówek
    for row in rows:
        cells = row.find_all("td")
        if len(cells) < 3:
            continue
        house_name = cells[0].get_text(strip=True)
        owner_name = cells[2].get_text(strip=True) or None
        houses.append({
            "name": house_name,
            "owner": owner_name
        })
    return houses

def fetch_owner_last_login(owner_name):
    if not owner_name:
        return None
    resp = requests.get(BASE_PLAYERS_URL)
    soup = BeautifulSoup(resp.text, "html.parser")
    players = soup.select("table tr")[1:]
    for row in players:
        cells = row.find_all("td")
        if len(cells) < 7:
            continue
        name = cells[1].get_text(strip=True)
        if name.lower() == owner_name.lower():
            login_text = cells[6].get_text(strip=True)
            try:
                last_login = datetime.strptime(login_text, "%d.%m.%Y (%H:%M)")
                return last_login.replace(tzinfo=timezone.utc)
            except:
                return None
    return None

# ------------------------ Cache builder ------------------------
async def build_cache(ctx=None):
    global cache
    houses = fetch_houses()
    total = len(houses)
    cache = {}
    start_time = datetime.now(timezone.utc)
    
    message = None
    if ctx:
        message = await ctx.send(f"Rozpoczynam budowanie cache... 0/{total} (0%)")
    
    for i, house in enumerate(houses):
        owner_name = house["owner"]
        last_login = fetch_owner_last_login(owner_name) if owner_name else None
        cache[house["name"]] = {
            "owner": owner_name,
            "last_login": last_login.isoformat() if last_login else None
        }
        # Update progress
        if message:
            elapsed = (datetime.now(timezone.utc) - start_time).total_seconds()
            percent = int((i+1)/total*100)
            remaining = elapsed/(i+1)*(total-(i+1)) if i+1>0 else 0
            eta = str(timedelta(seconds=int(remaining)))
            await message.edit(content=f"Budowanie cache: {i+1}/{total} ({percent}%) | ETA: {eta}")
        await asyncio.sleep(0.1)  # małe opóźnienie, żeby Discord nie spamował
    save_cache()
    if message:
        await message.edit(content=f"✅ Cache zbudowany. Znaleziono {total} domków.")

# ------------------------ Commands ------------------------
@bot.command()
async def laduj(ctx):
    """Ręczne ładowanie cache"""
    await build_cache(ctx)

@bot.command()
async def status(ctx):
    """Pokazuje status cache"""
    if not cache:
        await ctx.send("⚠️ Cache nie był jeszcze budowany!")
        return
    text = "Domki w cache:\n" + "\n".join(cache.keys())
    await ctx.send(text[:2000])

@bot.command()
async def sprawdz(ctx):
    """Pokazuje domki, których właściciel nie logował się > MIN_OFFLINE_DAYS"""
    if not cache:
        await ctx.send("⚠️ Cache nie był jeszcze budowany!")
        return
    now = datetime.now(timezone.utc)
    result = []
    for house, info in cache.items():
        last_login = datetime.fromisoformat(info["last_login"]) if info["last_login"] else None
        if last_login:
            offline_days = (now - last_login).days
            if offline_days >= MIN_OFFLINE_DAYS:
                result.append(f"{house} - {info['owner']} ({offline_days} dni offline) {MAP_LINK}{house.replace(' ','%20')}")
    if not result:
        await ctx.send("Brak domków spełniających kryteria.")
        return
    # wysyłanie w paczkach po 2000 znaków
    text = ""
    for line in result:
        if len(text)+len(line)+1 > 2000:
            await ctx.send(text)
            text = ""
        text += line + "\n"
    if text:
        await ctx.send(text)

@bot.command()
async def info(ctx):
    """Pokazuje wszystkie komendy i ich opis"""
    help_text = """
!laduj - ręczne ładowanie cache
!status - pokazuje status cache
!sprawdz - pokazuje domki do przejęcia (>10 dni offline)
!info - pokazuje te informacje
"""
    await ctx.send(help_text)

# ------------------------ Alerts ------------------------
async def send_alerts():
    global new_houses_alerted
    if not cache:
        return
    now = datetime.now(timezone.utc)
    channel = bot.get_channel(DISCORD_CHANNEL)
    for house, info in cache.items():
        last_login = datetime.fromisoformat(info["last_login"]) if info["last_login"] else None
        if last_login:
            offline_days = (now - last_login).days
            hours_until_takeover = 24*(12-offline_days)
            # Alert 12 dni
            if offline_days >= 12 and house not in new_houses_alerted:
                await channel.send(f"⚠️ Domek {house} do przejęcia! Owner: {info['owner']} ({offline_days} dni offline) {MAP_LINK}{house.replace(' ','%20')}")
                new_houses_alerted.add(house)
            # Alert 4h przed 14 dniami
            elif 14*24 - (now - last_login).total_seconds()/3600 <= 4 and house not in new_houses_alerted:
                await channel.send(f"⏰ Domek {house} będzie możliwy do przejęcia za 4h! Owner: {info['owner']} ({offline_days} dni offline) {MAP_LINK}{house.replace(' ','%20')}")

# ------------------------ Cyclic scan ------------------------
@tasks.loop(minutes=30)
async def cycle_scan_alerts():
    await build_cache()
    await send_alerts()

# ------------------------ Bot events ------------------------
@bot.event
async def on_ready():
    print(f"Zalogowano jako {bot.user}")
    load_cache()
    await build_cache(ctx=None)
    cycle_scan_alerts.start()

# ------------------------ Run ------------------------
bot.run(TOKEN)
