import discord
from discord.ext import commands, tasks
import requests
from bs4 import BeautifulSoup
from datetime import datetime, timezone
import json
import asyncio

TOKEN = "TU_WKLEJ_TOKEN"  # Twój token
CACHE_FILE = "cache.json"
ALERT_CHANNEL = "general"  # nazwa kanału, na który wysyła alerty

intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix="!", intents=intents)

house_cache = {}

# -------------------
# Funkcje pomocnicze
# -------------------

def save_cache():
    with open(CACHE_FILE, "w", encoding="utf-8") as f:
        json.dump(house_cache, f, ensure_ascii=False, indent=2)

def load_cache():
    global house_cache
    try:
        with open(CACHE_FILE, "r", encoding="utf-8") as f:
            house_cache = json.load(f)
    except FileNotFoundError:
        house_cache = {}

def parse_last_login(login_str):
    try:
        return datetime.strptime(login_str, "%d.%m.%Y (%H:%M)").replace(tzinfo=timezone.utc)
    except:
        return None

def fetch_houses():
    url = "https://cyleria.pl/?subtopic=houses"
    resp = requests.get(url)
    soup = BeautifulSoup(resp.text, "html.parser")
    houses = {}

    table = soup.find("table")
    if not table:
        return houses

    rows = table.find_all("tr")[1:]  # pomijamy nagłówek
    for row in rows:
        cols = row.find_all("td")
        if len(cols) < 4:
            continue
        name = cols[0].text.strip()
        size = cols[1].text.strip()
        player = cols[2].text.strip()
        map_link_tag = cols[0].find("a")
        map_link = map_link_tag["href"] if map_link_tag else ""
        houses[name] = {
            "name": name,
            "size": size,
            "player": player,
            "map": map_link,
            "last_login": None,
            "level": None
        }
    return houses

def fetch_player_info(player_name):
    url = f"https://cyleria.pl/?subtopic=characters&name={player_name}"
    resp = requests.get(url)
    soup = BeautifulSoup(resp.text, "html.parser")

    # Parsowanie poziomu
    level = None
    table = soup.find("table")
    if table:
        for row in table.find_all("tr"):
            if "Level" in row.text:
                level_text = row.find_all("td")[1].text.strip()
                level = int(level_text)
                break

    # Parsowanie ostatniego logowania
    last_login = None
    for row in soup.find_all("tr"):
        if "Logowanie" in row.text:
            last_login_str = row.find("td").text.strip()
            last_login = parse_last_login(last_login_str)
            break
    return level, last_login

async def update_cache_channel(channel=None):
    global house_cache
    house_cache = fetch_houses()
    total = len(house_cache)
    count = 0

    progress_msg = None
    if channel:
        progress_msg = await channel.send("🔄 Rozpoczynam skan Cylerii...")

    for house in house_cache.values():
        player_name = house["player"]
        if player_name:
            level, last_login = fetch_player_info(player_name)
            house["level"] = level
            if last_login:
                house["last_login"] = last_login.isoformat()
        count += 1
        # Pasek postępu
        if channel and progress_msg:
            percent = int(count / total * 100)
            bar = "█" * (percent // 5) + "-" * (20 - percent // 5)
            await progress_msg.edit(content=f"🔄 Skanuję domki: |{bar}| {percent}% ({count}/{total})")
        await asyncio.sleep(0.1)  # lekka przerwa, żeby Discord nie blokował
    save_cache()
    if channel and progress_msg:
        await progress_msg.edit(content=f"✅ Cache gotowy – {len(house_cache)} domków.")

    # Alert dla domków 13+ dni offline
    if channel:
        now = datetime.now(timezone.utc)
        alert_count = 0
        alert_msg = ""
        for h in house_cache.values():
            last_login = h.get("last_login")
            if not last_login:
                continue
            last_login_dt = datetime.fromisoformat(last_login)
            offline_days = (now - last_login_dt).days
            if offline_days >= 13:
                alert_msg += f"⚠ {h['name']} – {h['player']} – {offline_days} dni offline – [mapa]({h['map']})\n"
                alert_count += 1
        if alert_count > 0:
            await channel.send(f"🚨 Alert! {alert_count} domków 13+ dni offline:\n{alert_msg}")

# -------------------
# Komendy
# -------------------

@bot.command()
async def info(ctx):
    msg = ("⚙ Komendy bota:\n"
           "!info – pokazuje dostępne komendy\n"
           "!sprawdz – wszystkie domki 10+ dni offline\n"
           "!ultra – tylko domki 10+ dni offline i właściciele 600+\n"
           "!status – pokazuje status cache")
    await ctx.send(msg)

@bot.command()
async def status(ctx):
    if not house_cache:
        await ctx.send("⚠ Cache nie był jeszcze budowany.")
    else:
        await ctx.send(f"✅ Cache gotowy – {len(house_cache)} domków zapisanych.")

@bot.command()
async def sprawdz(ctx):
    if not house_cache:
        await ctx.send("⚠ Cache nie był jeszcze budowany.")
        return
    now = datetime.now(timezone.utc)
    msg = "🏠 Domki do przejęcia (10+ dni offline):\n"
    count = 0
    for h in house_cache.values():
        last_login = h.get("last_login")
        if not last_login:
            continue
        last_login_dt = datetime.fromisoformat(last_login)
        offline_days = (now - last_login_dt).days
        if offline_days >= 10:
            msg += f"{h['name']} – {h['player']} – {offline_days} dni offline – [mapa]({h['map']})\n"
            count += 1
    if count == 0:
        msg += "Brak domków spełniających warunki."
    await ctx.send(msg)

@bot.command()
async def ultra(ctx):
    if not house_cache:
        await ctx.send("⚠ Cache nie był jeszcze budowany.")
        return
    now = datetime.now(timezone.utc)
    msg = "🏠 Ultra – domki 600+ i 10+ dni offline:\n"
    count = 0
    for h in house_cache.values():
        last_login = h.get("last_login")
        level = h.get("level") or 0
        if not last_login:
            continue
        last_login_dt = datetime.fromisoformat(last_login)
        offline_days = (now - last_login_dt).days
        if offline_days >= 10 and level >= 600:
            msg += f"{h['name']} – {h['player']} ({level} lvl) – {offline_days} dni offline – [mapa]({h['map']})\n"
            count += 1
    if count == 0:
        msg += "Brak domków spełniających warunki."
    await ctx.send(msg)

# -------------------
# Eventy
# -------------------

@bot.event
async def on_ready():
    print(f"Zalogowano jako {bot.user}")
    load_cache()
    channel = discord.utils.get(bot.get_all_channels(), name=ALERT_CHANNEL)
    if channel:
        await update_cache_channel(channel=channel)

# -------------------
# Start bota
# -------------------
bot.run(TOKEN)
