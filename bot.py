import os
import json
import asyncio
import requests
from bs4 import BeautifulSoup
from datetime import datetime, timezone, timedelta
from discord.ext import commands, tasks
import discord

# ------------------- Variables -------------------
TOKEN = os.getenv("DISCORD_TOKEN")
DISCORD_CHANNEL = int(os.getenv("DISCORD_CHANNEL"))

BASE_HOUSES_URL = "https://cyleria.pl/?subtopic=houses"
BASE_PLAYERS_URL = "https://cyleria.pl/?subtopic=characters&name="

CACHE_FILE = "cache.json"
MIN_INACTIVE_DAYS = 10

bot = commands.Bot(command_prefix="!", intents=discord.Intents.all())
cache = []

# ------------------- Helpers -------------------
def fetch_houses():
    resp = requests.get(BASE_HOUSES_URL)
    resp.raise_for_status()
    soup = BeautifulSoup(resp.text, "html.parser")
    houses = []
    for row in soup.find_all("tr")[1:]:
        cells = row.find_all("td")
        if len(cells) < 4:
            continue
        try:
            house_name = cells[0].get_text(strip=True)
            size = int(cells[1].get_text(strip=True))
            owner = cells[2].get_text(strip=True)
            link_map = cells[0].find("a")["href"] if cells[0].find("a") else None
        except Exception:
            continue
        houses.append({
            "house": house_name,
            "size": size,
            "owner": owner,
            "link": link_map
        })
    return houses

def fetch_last_login(player_name):
    if not player_name or player_name.lower() == "brak":
        return None
    url = BASE_PLAYERS_URL + player_name
    try:
        resp = requests.get(url)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "html.parser")
        login_elem = soup.find(string=lambda s: s and "Logowanie:" in s)
        if not login_elem:
            return None
        parent = login_elem.parent
        login_text = None
        if parent and parent.next_sibling:
            login_text = parent.next_sibling.get_text(strip=True)
        if not login_text:
            login_text = login_elem.split("Logowanie:")[-1].strip()
        last_login = datetime.strptime(login_text, "%d.%m.%Y (%H:%M)")
        return last_login.replace(tzinfo=timezone.utc)
    except Exception:
        return None

def save_cache():
    with open(CACHE_FILE, "w", encoding="utf-8") as f:
        json.dump(cache, f, ensure_ascii=False, indent=2)

def load_cache():
    global cache
    if os.path.exists(CACHE_FILE):
        with open(CACHE_FILE, "r", encoding="utf-8") as f:
            cache = json.load(f)

# ------------------- Cache Building -------------------
async def build_cache(ctx=None):
    global cache
    houses = fetch_houses()
    total = len(houses)
    cache.clear()

    if ctx:
        progress_msg = await ctx.send(f"Budowanie cache: 0/{total}")
    else:
        progress_msg = None

    for idx, h in enumerate(houses, 1):
        last_login = fetch_last_login(h["owner"])
        h["last_login"] = last_login.isoformat() if last_login else None
        cache.append(h)

        if progress_msg:
            await progress_msg.edit(content=f"Budowanie cache: {idx}/{total}")

        await asyncio.sleep(0.1)  # delikatny throttle, nie spamować serwera

    save_cache()
    if ctx:
        await progress_msg.edit(content=f"✅ Cache zbudowany. Znaleziono {len(cache)} domków.")
    else:
        print(f"✅ Cache zbudowany. Znaleziono {len(cache)} domków.")

# ------------------- Alerts -------------------
async def send_alerts():
    channel = bot.get_channel(DISCORD_CHANNEL)
    now = datetime.now(timezone.utc)
    for h in cache:
        if not h.get("last_login"):
            continue
        last_login = datetime.fromisoformat(h["last_login"])
        days_inactive = (now - last_login).days
        hours_inactive = (now - last_login).total_seconds() / 3600

        # Alert dla 12 dni
        if days_inactive == 12:
            text = f"⚠️ Domek `{h['house']}` właściciela `{h['owner']}` nieaktywny 12 dni! Mapka: {h['link']}"
            await channel.send(text)

        # Alert 4h przed przejęciem (14 dni)
        if 336 <= hours_inactive < 340:  # 336 = 14*24 - 4
            text = f"⏰ Domek `{h['house']}` właściciela `{h['owner']}` za 4h do przejęcia! Mapka: {h['link']}"
            await channel.send(text)

# ------------------- Bot Commands -------------------
@bot.command()
async def sprawdz(ctx):
    now = datetime.now(timezone.utc)
    result = []
    for h in cache:
        if not h.get("last_login"):
            continue
        last_login = datetime.fromisoformat(h["last_login"])
        if (now - last_login).days >= MIN_INACTIVE_DAYS:
            result.append(f"{h['house']} ({h['owner']}) - {h['link']}")

    if not result:
        await ctx.send("Brak domków spełniających kryteria.")
        return

    # Rozbij na wiadomości po 1900 znaków
    msg = ""
    for line in result:
        if len(msg) + len(line) + 1 > 1900:
            await ctx.send(msg)
            msg = ""
        msg += line + "\n"
    if msg:
        await ctx.send(msg)

@bot.command()
async def status(ctx):
    await ctx.send(f"Cache zawiera {len(cache)} domków.")

@bot.command()
async def info(ctx):
    text = (
        "**Dostępne komendy:**\n"
        "`!sprawdz` - pokaż domki, których właściciel nie logował się >10 dni\n"
        "`!status` - pokaż ile domków jest w cache\n"
        "`!info` - pokaż tę wiadomość\n"
    )
    await ctx.send(text)

# ------------------- Background Tasks -------------------
@tasks.loop(minutes=60)
async def background_alerts():
    await send_alerts()

# ------------------- Bot Events -------------------
@bot.event
async def on_ready():
    print(f"Zalogowano jako {bot.user}")
    load_cache()
    # Buduj cache przy starcie
    await build_cache()
    background_alerts.start()

# ------------------- Run Bot -------------------
bot.run(TOKEN)
