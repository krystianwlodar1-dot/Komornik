import os
import asyncio
from datetime import datetime, timezone
import discord
from discord.ext import commands, tasks
import requests
from bs4 import BeautifulSoup

# Discord intents
intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix="!", intents=intents)

# Cache domków
house_cache = {}
cache_building = False
cache_progress_msg = None

CYLERIA_HOUSES_URL = "https://cyleria.pl/?subtopic=houses"

# Minimalny poziom postaci
MIN_LEVEL = 600

# Funkcja do pobrania listy domków i właścicieli
def fetch_houses():
    houses = []
    resp = requests.get(CYLERIA_HOUSES_URL)
    soup = BeautifulSoup(resp.text, "html.parser")
    table_rows = soup.find_all("tr")[1:]  # pomijamy nagłówek

    for row in table_rows:
        cols = row.find_all("td")
        if len(cols) < 4:
            continue
        house_name = cols[0].text.strip()
        size = cols[1].text.strip()
        owner = cols[2].text.strip()
        last_login_str = cols[3].text.strip()
        if owner.lower() == "brak":
            continue
        try:
            last_login = datetime.strptime(last_login_str, "%d.%m.%Y (%H:%M)").replace(tzinfo=timezone.utc)
        except:
            last_login = None
        houses.append({
            "name": house_name,
            "size": size,
            "owner": owner,
            "last_login": last_login
        })
    return houses

# Funkcja budująca cache z paskiem postępu i ETA
async def build_cache(channel):
    global house_cache, cache_building, cache_progress_msg
    cache_building = True
    house_cache = {}
    houses = fetch_houses()
    total = len(houses)
    start_time = datetime.now(timezone.utc)

    cache_progress_msg = await channel.send(f"🔄 Rozpoczynam skan Cylerii... 0/{total}")
    for i, house in enumerate(houses, 1):
        house_cache[house["name"]] = house

        elapsed = (datetime.now(timezone.utc) - start_time).total_seconds()
        eta = int(elapsed / i * (total - i)) if i > 0 else 0
        await cache_progress_msg.edit(content=f"🔄 Skanuję domki... {i}/{total} ETA: ~{eta}s")
        await asyncio.sleep(0.1)  # sztuczne opóźnienie, żeby Discord nie spamił

    cache_building = False
    await cache_progress_msg.edit(content=f"✅ Cache gotowy – {len(house_cache)} domków.")
    await channel.send("🚨 Skan zakończony!")

# Komendy
@bot.command()
async def status(ctx):
    if cache_building:
        await ctx.send("🔄 Cache jest w trakcie budowy...")
    else:
        await ctx.send(f"✅ Cache gotowy – {len(house_cache)} domków.")

@bot.command()
async def sprawdz(ctx):
    if cache_building:
        await ctx.send("🔄 Cache jest w trakcie budowy...")
        return
    result = []
    now = datetime.now(timezone.utc)
    for house in house_cache.values():
        if house["last_login"] is None:
            continue
        offline_days = (now - house["last_login"]).days
        if offline_days >= 10:
            result.append(f"{house['name']} – {house['owner']} – {offline_days} dni offline")
    if not result:
        await ctx.send("❌ Brak domków spełniających kryteria.")
    else:
        await ctx.send("\n".join(result[:20]))

@bot.command()
async def ultra(ctx):
    if cache_building:
        await ctx.send("🔄 Cache jest w trakcie budowy...")
        return
    result = []
    now = datetime.now(timezone.utc)
    for house in house_cache.values():
        if house["last_login"] is None:
            continue
        offline_days = (now - house["last_login"]).days
        # zakładamy, że minimalny poziom właściciela jest 600
        # tu nie pobieramy poziomu z Highscores, więc traktujemy wszystkich
        if offline_days >= 10:
            result.append(f"{house['name']} – {house['owner']} – {offline_days} dni offline")
    if not result:
        await ctx.send("❌ Brak domków spełniających kryteria dla trybu ULTRA.")
    else:
        await ctx.send("\n".join(result[:20]))

@bot.event
async def on_ready():
    print(f"Zalogowano jako {bot.user}")
    channel_id = os.getenv("DISCORD_CHANNEL")  # ustaw ID kanału w zmiennej środowiskowej
    if channel_id:
        channel = bot.get_channel(int(channel_id))
        if channel:
            await build_cache(channel)
        else:
            print("Nie znaleziono kanału!")
    else:
        print("Nie ustawiono DISCORD_CHANNEL w zmiennych środowiskowych!")

# Uruchomienie bota
TOKEN = os.getenv("DISCORD_TOKEN")
if not TOKEN:
    print("❌ Nie ustawiono DISCORD_TOKEN w zmiennych środowiskowych!")
else:
    bot.run(TOKEN)
