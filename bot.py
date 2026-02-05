import os
import asyncio
import json
from datetime import datetime, timedelta, timezone
import aiohttp
from bs4 import BeautifulSoup
import discord
from discord.ext import commands, tasks

# Pobranie tokenu i kanału z Railway Environment Variables
TOKEN = os.getenv("DISCORD_TOKEN")
DISCORD_CHANNEL = int(os.getenv("DISCORD_CHANNEL", 0))

if not TOKEN or not DISCORD_CHANNEL:
    raise ValueError("Brakuje TOKEN lub DISCORD_CHANNEL w zmiennych środowiskowych!")

# URL-e
HOUSES_URL = "https://cyleria.pl/?subtopic=houses"
HIGHSCORES_URL = "https://cyleria.pl/?subtopic=highscores"
MAP_BASE_URL = "https://cyleria.pl/?subtopic=houses&house="

CACHE_FILE = "cache.json"
MIN_LOG_DAYS = 10

intents = discord.Intents.default()
intents.message_content = True

bot = commands.Bot(command_prefix="!", intents=intents)

cache = []
new_alerted = set()


async def fetch(session, url):
    async with session.get(url) as resp:
        return await resp.text()


async def get_last_login(session, player_name):
    """Pobiera datę ostatniego logowania gracza"""
    profile_url = f"https://cyleria.pl/?subtopic=characters&name={player_name}"
    html = await fetch(session, profile_url)
    soup = BeautifulSoup(html, "html.parser")
    login_elem = soup.find(string=lambda t: t and "Logowanie:" in t)
    if login_elem:
        try:
            date_str = login_elem.strip().split("Logowanie:")[1].strip()
            return datetime.strptime(date_str, "%d.%m.%Y (%H:%M)").replace(tzinfo=timezone.utc)
        except Exception:
            return None
    return None


async def fetch_houses_with_logins():
    """Pobiera listę domków oraz logowania właścicieli równolegle"""
    global cache
    houses = []
    async with aiohttp.ClientSession() as session:
        html = await fetch(session, HOUSES_URL)
        soup = BeautifulSoup(html, "html.parser")
        rows = soup.select("table tr")[1:]  # pomijamy nagłówek
        for row in rows:
            cells = row.find_all("td")
            if len(cells) < 4:
                continue
            house_name = cells[0].get_text(strip=True)
            size = cells[1].get_text(strip=True)
            owner_name = cells[2].get_text(strip=True)
            map_pin = cells[0].find("a")["href"] if cells[0].find("a") else ""
            last_login = None
            if owner_name != "Brak":
                last_login = await get_last_login(session, owner_name)
            houses.append({
                "name": house_name,
                "size": size,
                "owner": owner_name,
                "map": map_pin,
                "last_login": last_login.isoformat() if last_login else None
            })
    cache = houses
    # zapis cache
    with open(CACHE_FILE, "w", encoding="utf-8") as f:
        json.dump(cache, f, ensure_ascii=False, indent=2)
    return houses


async def send_progress_message(ctx, text):
    """Wyślij lub edytuj wiadomość z postępem"""
    if not hasattr(send_progress_message, "msg"):
        send_progress_message.msg = await ctx.send(text)
    else:
        await send_progress_message.msg.edit(content=text)


async def build_cache(ctx=None):
    total_houses = 0
    progress_msg = None
    try:
        total_houses = len(cache)
        if ctx:
            progress_msg = await ctx.send("Rozpoczynam budowanie cache...")
        houses = await fetch_houses_with_logins()
        total_houses = len(houses)
        if progress_msg:
            await progress_msg.edit(content=f"✅ Cache zbudowany. Znaleziono {total_houses} domków.")
    except Exception as e:
        if ctx:
            await ctx.send(f"⚠️ Błąd przy budowaniu cache: {e}")


@bot.event
async def on_ready():
    print(f"{bot.user} zalogowany")
    channel = bot.get_channel(DISCORD_CHANNEL)
    await build_cache(ctx=channel)


@bot.command()
async def status(ctx):
    if not cache:
        return await ctx.send("⚠️ Cache nie był jeszcze budowany!")
    await ctx.send(f"✅ Cache zbudowany. Znaleziono {len(cache)} domków.")


@bot.command()
async def sprawdz(ctx):
    if not cache:
        return await ctx.send("⚠️ Cache nie był jeszcze budowany!")
    now = datetime.now(timezone.utc)
    text_lines = []
    for h in cache:
        if h["owner"] != "Brak" and h["last_login"]:
            last_login = datetime.fromisoformat(h["last_login"])
            if (now - last_login).days >= MIN_LOG_DAYS:
                line = f"{h['name']} ({h['size']}) - {h['owner']} | Ostatnie logowanie: {last_login.strftime('%d.%m.%Y (%H:%M)')} | [Mapa]({h['map']})"
                text_lines.append(line)
    if not text_lines:
        await ctx.send("Brak domków spełniających kryteria.")
    else:
        # dzielimy wiadomość jeśli przekracza 2000 znaków
        chunk_size = 1900
        for i in range(0, len(text_lines), chunk_size):
            await ctx.send("\n".join(text_lines[i:i+chunk_size]))


@bot.command()
async def info(ctx):
    commands_info = """
**!status** - Pokazuje status cache
**!sprawdz** - Pokazuje domki do przejęcia (>10 dni nieobecności)
**!info** - Pokazuje listę wszystkich komend
"""
    await ctx.send(commands_info)


async def alert_new_houses():
    """Alert dla nowych domków do przejęcia"""
    global new_alerted
    now = datetime.now(timezone.utc)
    for h in cache:
        if h["owner"] != "Brak" and h["last_login"]:
            last_login = datetime.fromisoformat(h["last_login"])
            days_absent = (now - last_login).days
            hours_to_takeover = 14*24 - (now - last_login).total_seconds()/3600
            if days_absent >= 12 and h["name"] not in new_alerted:
                channel = bot.get_channel(DISCORD_CHANNEL)
                await channel.send(f"⚠️ Domek {h['name']} | {h['owner']} nie logował się 12 dni! [Mapa]({h['map']})")
                new_alerted.add(h["name"])
            elif 10*24 <= hours_to_takeover <= 14*24:
                channel = bot.get_channel(DISCORD_CHANNEL)
                await channel.send(f"⚠️ Domek {h['name']} będzie możliwy do przejęcia za {int(hours_to_takeover)}h | {h['owner']} [Mapa]({h['map']})")
                new_alerted.add(h["name"])


@tasks.loop(minutes=30)
async def cycle_scan_alerts():
    if cache:
        await alert_new_houses()


cycle_scan_alerts.start()

bot.run(TOKEN)
