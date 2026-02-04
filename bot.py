import discord
from discord.ext import commands, tasks
import requests
from bs4 import BeautifulSoup
from datetime import datetime
import os
import asyncio

TOKEN = os.getenv("TOKEN")
CHANNEL_ID = int(os.getenv("CHANNEL_ID"))
CYLERIA = "https://cyleria.pl"

intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix="!", intents=intents)

CACHE = []
LAST_UPDATE = None

# =========================
# SCRAPING
# =========================

def get_all_players():
    players = []
    page = 0

    while True:
        url = f"{CYLERIA}/?subtopic=highscores&list=experience&world=0&page={page}"
        r = requests.get(url, timeout=15)
        soup = BeautifulSoup(r.text, "html.parser")

        table = soup.find("table")
        if not table:
            break

        rows = table.find_all("tr")[1:]
        if not rows:
            break

        for r in rows:
            players.append(r.find_all("td")[1].text.strip())

        page += 1

    return players

def get_character_info(name):
    url = f"{CYLERIA}/?subtopic=characters&name={name.replace(' ', '+')}"
    r = requests.get(url, timeout=15)
    soup = BeautifulSoup(r.text, "html.parser")

    house = None
    last_login = None

    for row in soup.find_all("tr"):
        if "House" in row.text:
            house = row.find_all("td")[1].text.strip()
        if "Last Login" in row.text:
            date_str = row.find_all("td")[1].text.strip()
            try:
                last_login = datetime.strptime(date_str, "%d.%m.%Y (%H:%M)")
            except:
                pass

    return house, last_login

# =========================
# UTILS
# =========================

def hours_left(last_login):
    offline_hours = (datetime.now() - last_login).total_seconds() / 3600
    return max(0, 14*24 - offline_hours)

# =========================
# CACHE BUILDER (ASYNC SAFE)
# =========================

@tasks.loop(hours=1)
async def update_cache():
    global CACHE, LAST_UPDATE
    print("🔄 Aktualizuję cache domków...")

    players = await asyncio.to_thread(get_all_players)
    results = []

    for p in players:
        house, last_login = await asyncio.to_thread(get_character_info, p)
        if not house or not last_login:
            continue

        offline_days = (datetime.now() - last_login).total_seconds() / 86400
        if offline_days >= 7:  # bierzemy tych którzy zbliżają się do sprzedaży
            results.append((p, house, last_login))

    CACHE = results
    LAST_UPDATE = datetime.now()
    print(f"✅ Cache gotowy: {len(CACHE)} domków")

# =========================
# COMMANDS
# =========================

@bot.command()
async def info(ctx):
    await ctx.send(
        "**Komendy:**\n"
        "!sprawdz – TOP 5 domków do przejęcia\n"
        "!sprawdz <miasto>\n"
        "!top20 – ranking TOP 20"
    )

@bot.command()
async def sprawdz(ctx, city=None):
    if not CACHE:
        await ctx.send("⏳ Cache jeszcze się buduje...")
        return

    filtered = []
    for p, h, d in CACHE:
        if city and city.lower() not in h.lower():
            continue
        if (datetime.now() - d).total_seconds()/86400 >= 10:
            filtered.append((p, h, d))

    filtered.sort(key=lambda x: hours_left(x[2]))
    filtered = filtered[:5]

    if not filtered:
        await ctx.send("❌ Brak domków dla tego filtra.")
        return

    msg = "**🏠 TOP 5 domków do przejęcia:**\n"
    for p, h, d in filtered:
        msg += f"**{p}**\n{h}\n⏳ {hours_left(d):.1f}h\n\n"

    await ctx.send(msg)

@bot.command()
async def top20(ctx):
    if not CACHE:
        await ctx.send("⏳ Cache jeszcze się buduje...")
        return

    ranked = [x for x in CACHE if (datetime.now()-x[2]).total_seconds()/86400 >= 10]
    ranked.sort(key=lambda x: hours_left(x[2]))
    ranked = ranked[:20]

    msg = "**🏆 TOP 20 domków do przejęcia:**\n"
    for i, (p, h, d) in enumerate(ranked, 1):
        msg += f"{i}. **{p}** – {h}\n⏳ {hours_left(d):.1f}h\n\n"

    await ctx.send(msg)

# =========================
# ALERT 13 DAY
# =========================

@tasks.loop(minutes=30)
async def alert_loop():
    if not CACHE:
        return

    channel = bot.get_channel(CHANNEL_ID)
    if not channel:
        return

    for p, h, d in CACHE:
        offline = (datetime.now() - d).total_seconds() / 86400
        if 13 <= offline < 14:
            await channel.send(
                f"⚠️ **ALERT DOMKU**\n"
                f"{p}\n{h}\n"
                f"Za {hours_left(d):.1f}h domek trafi na sprzedaż!"
            )

# =========================
# START
# =========================

@bot.event
async def on_ready():
    print(f"Zalogowano jako {bot.user}")
    update_cache.start()
    alert_loop.start()

bot.run(TOKEN)
