import discord
from discord.ext import commands, tasks
import requests
from bs4 import BeautifulSoup
from datetime import datetime
import os

TOKEN = os.getenv("TOKEN")
CHANNEL_ID = int(os.getenv("CHANNEL_ID"))
CYLERIA = "https://cyleria.pl"

intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix="!", intents=intents)

CACHE = []
LAST_UPDATE = None

def get_all_players():
    players = []
    page = 0

    while True:
        url = f"{CYLERIA}/?subtopic=highscores&list=experience&world=0&page={page}"
        soup = BeautifulSoup(requests.get(url).text, "html.parser")
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
    soup = BeautifulSoup(requests.get(url).text, "html.parser")

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

def hours_left(last_login):
    offline = (datetime.now() - last_login).total_seconds() / 3600
    return max(0, 14*24 - offline)

@tasks.loop(hours=1)
async def update_cache():
    global CACHE, LAST_UPDATE
    print("🔄 Aktualizuję cache domków…")

    results = []
    players = get_all_players()

    for p in players:
        house, last_login = get_character_info(p)
        if not house or not last_login:
            continue

        offline_days = (datetime.now() - last_login).total_seconds() / 86400
        if offline_days >= 7:
            results.append((p, house, last_login))

    CACHE = results
    LAST_UPDATE = datetime.now()
    print(f"Zaktualizowano cache: {len(CACHE)} domków")

@bot.command()
async def info(ctx):
    await ctx.send("**Komendy:**\n!sprawdz – TOP 5 domków\n!sprawdz <miasto>\n!top20 – ranking 20 domków do przejęcia")

@bot.command()
async def sprawdz(ctx, city=None):
    if not CACHE:
        await ctx.send("⏳ Cache się jeszcze buduje, spróbuj za minutę.")
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

    msg = "**🏠 TOP 5 do przejęcia:**\n"
    for p, h, d in filtered:
        msg += f"**{p}**\n{h}\n⏳ {hours_left(d):.1f}h do sprzedaży\n\n"

    await ctx.send(msg)

@bot.command()
async def top20(ctx):
    if not CACHE:
        await ctx.send("⏳ Cache się jeszcze buduje.")
        return

    ranked = sorted(CACHE, key=lambda x: hours_left(x[2]))
    ranked = [x for x in ranked if (datetime.now()-x[2]).total_seconds()/86400 >= 10]
    ranked = ranked[:20]

    msg = "**🏆 TOP 20 domków do przejęcia:**\n"
    for i,(p,h,d) in enumerate(ranked,1):
        msg += f"{i}. **{p}** – {h}\n⏳ {hours_left(d):.1f}h\n\n"

    await ctx.send(msg)

@tasks.loop(minutes=30)
async def alert_loop():
    if not CACHE:
        return
    channel = bot.get_channel(CHANNEL_ID)
    if not channel:
        return

    for p,h,d in CACHE:
        offline = (datetime.now()-d).total_seconds()/86400
        if 13 <= offline < 14:
            await channel.send(
                f"⚠️ **ALERT DOMKU**\n{p}\n{h}\nZa {hours_left(d):.1f}h do sprzedaży"
            )

@bot.event
async def on_ready():
    print(f"Zalogowano jako {bot.user}")
    update_cache.start()
    alert_loop.start()

bot.run(TOKEN)
