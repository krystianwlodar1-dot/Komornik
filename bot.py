import discord
from discord.ext import commands, tasks
import requests
from bs4 import BeautifulSoup
from datetime import datetime, timezone
import asyncio

TOKEN = "TWÓJ_DISCORD_TOKEN"
GUILD_ID = 123456789012345678  # ID serwera (opcjonalnie)
CHANNEL_ID = 123456789012345678  # kanał do alertów
MIN_LEVEL = 600  # minimalny poziom do domku

intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix="!", intents=intents)

houses_cache = {}  # {owner: {"house":..., "lvl":..., "offline_days":..., "map":...}}
alerted_houses = set()

CYLERIA_HOUSES_URL = "https://cyleria.pl/?subtopic=houses"

# Pobranie listy domków
def get_all_houses():
    resp = requests.get(CYLERIA_HOUSES_URL)
    soup = BeautifulSoup(resp.text, "html.parser")
    houses = {}
    rows = soup.find_all("tr")[1:]  # pomijamy nagłówek tabeli
    for row in rows:
        cols = row.find_all("td")
        if len(cols) < 4:
            continue
        address = cols[0].text.strip()
        size = cols[1].text.strip()
        owner = cols[2].text.strip() if cols[2].text.strip() else None
        map_link = cols[0].find("a")["href"] if cols[0].find("a") else None
        status = cols[3].text.strip()
        houses[address] = {"owner": owner, "size": size, "map": map_link, "status": status}
    return houses

# Pobranie info o postaci
def get_character_info(name):
    if not name:
        return None, None
    url = f"https://cyleria.pl/?subtopic=characters&name={name}"
    resp = requests.get(url)
    soup = BeautifulSoup(resp.text, "html.parser")

    # poziom
    lvl_tag = soup.find(text=lambda t: t and "Level:" in t)
    lvl = int(lvl_tag.split(":")[1].strip()) if lvl_tag else 0

    # logowanie
    login_tag = soup.find(text=lambda t: t and "Logowanie" in t)
    last_login = None
    if login_tag:
        try:
            last_login_str = login_tag.split(":")[1].strip()
            last_login = datetime.strptime(last_login_str, "%d.%m.%Y (%H:%M)").replace(tzinfo=timezone.utc)
        except:
            last_login = None

    return lvl, last_login

# Funkcja do budowania cache
async def update_cache(channel=None):
    global houses_cache
    houses = get_all_houses()
    new_cache = {}
    total = len(houses)
    done = 0
    start_time = datetime.now(timezone.utc)
    if channel:
        msg = await channel.send(f"🔄 Rozpoczynam skan Cylerii... 0/{total}")

    for address, data in houses.items():
        owner = data["owner"]
        if not owner:
            done += 1
            continue
        try:
            lvl, last_login = get_character_info(owner)
        except:
            done += 1
            continue

        offline_days = 0
        if last_login:
            offline_days = (datetime.now(timezone.utc) - last_login).days

        if lvl >= MIN_LEVEL:
            new_cache[owner] = {
                "lvl": lvl,
                "house": address,
                "offline_days": offline_days,
                "map": data["map"]
            }

            # alert 13 dni
            if offline_days == 13 and owner not in alerted_houses and channel:
                alerted_houses.add(owner)
                await channel.send(f"⚠️ Domek **{address}** gracza **{owner}** osiągnął 13 dni offline!\nMapka: {data['map']}")

        done += 1
        # aktualizacja paska
        if channel:
            elapsed = (datetime.now(timezone.utc) - start_time).total_seconds()
            eta = (elapsed / done) * (total - done) if done else 0
            await msg.edit(content=f"🔄 Rozpoczynam skan Cylerii... {done}/{total} (~{int(eta)}s do końca)")

    houses_cache = new_cache
    if channel:
        await msg.edit(content=f"✅ Cache gotowy – {len(houses_cache)} domków.")

# Komendy
@bot.command()
async def info(ctx):
    msg = (
        "!info - pokaż dostępne komendy\n"
        "!status - sprawdź status cache\n"
        "!sprawdz - pokaż wszystkie domki offline >= 10 dni\n"
        "!ultra - pokaż domki lvl>=600 offline>=10 dni\n"
        "!top20 - TOP20 domków do przejęcia"
    )
    await ctx.send(msg)

@bot.command()
async def status(ctx):
    if not houses_cache:
        await ctx.send("❌ Cache nie był jeszcze budowany.")
    else:
        await ctx.send(f"✅ Cache gotowy – {len(houses_cache)} domków.")

@bot.command()
async def sprawdz(ctx):
    if not houses_cache:
        await ctx.send("❌ Cache nie był jeszcze budowany.")
        return
    msg = ""
    for owner, data in houses_cache.items():
        if data["offline_days"] >= 10:
            msg += f"{owner} – {data['house']} – {data['offline_days']} dni offline – Mapka: {data['map']}\n"
    if msg:
        await ctx.send(msg)
    else:
        await ctx.send("❌ Nie znaleziono domków dla tego filtra.")

@bot.command()
async def ultra(ctx):
    if not houses_cache:
        await ctx.send("❌ Cache nie był jeszcze budowany.")
        return
    msg = ""
    for owner, data in houses_cache.items():
        if data["lvl"] >= 600 and data["offline_days"] >= 10:
            msg += f"{owner} – {data['house']} – {data['lvl']} lvl – {data['offline_days']} dni offline – Mapka: {data['map']}\n"
    if msg:
        await ctx.send(msg)
    else:
        await ctx.send("❌ Nie znaleziono domków dla tego filtra.")

@bot.command()
async def top20(ctx):
    if not houses_cache:
        await ctx.send("❌ Cache nie był jeszcze budowany.")
        return
    sorted_houses = sorted(houses_cache.items(), key=lambda x: x[1]["offline_days"], reverse=True)
    msg = ""
    for owner, data in sorted_houses[:20]:
        msg += f"{owner} – {data['house']} – {data['offline_days']} dni offline – Mapka: {data['map']}\n"
    await ctx.send(msg)

# Automatyczne budowanie cache po starcie
@bot.event
async def on_ready():
    channel = bot.get_channel(CHANNEL_ID)
    await update_cache(channel=channel)
    print(f"Zalogowano jako {bot.user}")

bot.run(TOKEN)
