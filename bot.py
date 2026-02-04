import discord
from discord.ext import commands, tasks
import requests
from bs4 import BeautifulSoup
from datetime import datetime
import os, json, asyncio

TOKEN = os.getenv("TOKEN")           # Discord bot token
CHANNEL_ID = int(os.getenv("CHANNEL_ID"))  # Kanał do komunikatów
CYLERIA = "https://cyleria.pl"
CACHE_FILE = "cache.json"

FAST_MODE = True
FAST_LEVEL = 600

intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix="!", intents=intents)

CACHE = []
LAST_UPDATE = None

# =========================
# FUNKCJE POMOCNICZE
# =========================

def get_all_players():
    players = []
    page = 0
    while True:
        url = f"{CYLERIA}/?subtopic=highscores&list=experience&world=0&page={page}"
        soup = BeautifulSoup(requests.get(url, timeout=15).text, "html.parser")
        table = soup.find("table")
        if not table: break
        rows = table.find_all("tr")[1:]
        if not rows: break

        for r in rows:
            tds = r.find_all("td")
            name = tds[1].text.strip()
            level = int(tds[3].text.strip())
            if FAST_MODE and level < FAST_LEVEL: continue
            players.append(name)

        page += 1
    return players

def get_character_info(name):
    url = f"{CYLERIA}/?subtopic=characters&name={name.replace(' ', '+')}"
    soup = BeautifulSoup(requests.get(url, timeout=15).text, "html.parser")
    house = None
    last_login = None
    for row in soup.find_all("tr"):
        if "House" in row.text:
            house = row.find_all("td")[1].text.strip()
        if "Last Login" in row.text:
            date_str = row.find_all("td")[1].text.strip()
            try: last_login = datetime.strptime(date_str, "%d.%m.%Y (%H:%M)")
            except: pass
    return house, last_login

def hours_left(last_login):
    offline_hours = (datetime.now() - last_login).total_seconds() / 3600
    return max(0, 14*24 - offline_hours)

# =========================
# CACHE DO PLIKU
# =========================

def load_cache():
    global CACHE, LAST_UPDATE
    if os.path.exists(CACHE_FILE):
        with open(CACHE_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
            CACHE = [(x["player"], x["house"], datetime.fromisoformat(x["last_login"])) for x in data]
        print(f"Cache wczytany z pliku ({len(CACHE)} domków)")

def save_cache():
    data = [{"player": p, "house": h, "last_login": d.isoformat()} for p,h,d in CACHE]
    with open(CACHE_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

# =========================
# BUILD CACHE Z ETA
# =========================

@tasks.loop(hours=1)
async def update_cache():
    global CACHE, LAST_UPDATE
    channel = bot.get_channel(CHANNEL_ID)
    progress_msg = await channel.send("🔄 Skanuję Cylerię…")
    players = await asyncio.to_thread(get_all_players)
    total = len(players)
    scanned = 0
    results = []
    start_time = datetime.now()

    for p in players:
        scanned += 1
        house, last_login = await asyncio.to_thread(get_character_info, p)
        if house and last_login: results.append((p, house, last_login))

        if scanned % 25 == 0 or scanned == total:
            elapsed = (datetime.now() - start_time).total_seconds()
            avg_per_player = elapsed / scanned
            remaining_time = avg_per_player * (total - scanned)
            minutes_left = int(remaining_time // 60)
            percent = scanned / total
            bar_length = 20
            filled_length = int(bar_length * percent)
            bar = "▰" * filled_length + "▱" * (bar_length - filled_length)
            await progress_msg.edit(
                content=(
                    f"🔄 Skanuję Cylerię…\n"
                    f"{bar} {scanned}/{total} ({percent*100:.1f}%)\n"
                    f"Domków w cache: {len(results)}\n"
                    f"Szacowany czas do końca: ~{minutes_left} min"
                )
            )

    CACHE = results
    LAST_UPDATE = datetime.now()
    save_cache()
    await progress_msg.edit(
        content=f"✅ Cache gotowy!\n"
                f"Zeskanowano: {total} graczy\n"
                f"Domków w cache: {len(CACHE)}"
    )

# =========================
# KOMENDY
# =========================

@bot.command()
async def info(ctx):
    await ctx.send(
        "**Komendy:**\n"
        "!sprawdz – TOP 5 domków (10+ dni offline)\n"
        "!sprawdz <miasto>\n"
        "!top20 – TOP 20\n"
        "!ultra – TOP 5 domków 600+ lvl i offline ≥ 10 dni"
    )

@bot.command()
async def sprawdz(ctx, city=None):
    if not CACHE: return await ctx.send("⏳ Cache jeszcze się buduje…")
    filtered = []
    for p,h,d in CACHE:
        if city and city.lower() not in h.lower(): continue
        offline_days = (datetime.now()-d).total_seconds()/86400
        if offline_days >= 10: filtered.append((p,h,d))
    filtered.sort(key=lambda x: hours_left(x[2]))
    filtered = filtered[:5]
    if not filtered: return await ctx.send("❌ Brak domków.")
    msg = "**🏠 TOP 5 domków:**\n"
    for p,h,d in filtered: msg += f"**{p}**\n{h}\n⏳ {hours_left(d):.1f}h\n\n"
    await ctx.send(msg)

@bot.command()
async def top20(ctx):
    if not CACHE: return await ctx.send("⏳ Cache jeszcze się buduje…")
    ranked = [x for x in CACHE if (datetime.now()-x[2]).total_seconds()/86400 >=10]
    ranked.sort(key=lambda x: hours_left(x[2]))
    ranked = ranked[:20]
    msg = "**🏆 TOP 20:**\n"
    for i,(p,h,d) in enumerate(ranked,1): msg += f"{i}. **{p}** – {h}\n⏳ {hours_left(d):.1f}h\n\n"
    await ctx.send(msg)

@bot.command()
async def ultra(ctx):
    """Pokazuje TOP 5 domków 600+ lvl i offline ≥10 dni z paskiem ETA"""
    if not CACHE: return await ctx.send("⏳ Cache jeszcze się buduje…")

    players = []
    for p,h,d in CACHE:
        level = 0
        try:
            url = f"{CYLERIA}/?subtopic=characters&name={p.replace(' ', '+')}"
            soup = BeautifulSoup(requests.get(url, timeout=10).text, "html.parser")
            for row in soup.find_all("tr"):
                if "Level" in row.text: level=int(row.find_all("td")[1].text.strip())
        except: continue
        if level >= 600: players.append((p,h,d,level))

    total = len(players)
    if total == 0: return await ctx.send("❌ Brak graczy 600+ lvl w cache.")

    progress_msg = await ctx.send("⚡ Sprawdzanie ULTRA…")
    results = []
    start_time = datetime.now()

    for i,(p,h,d,level) in enumerate(players,1):
        offline_days = (datetime.now()-d).total_seconds()/86400
        if offline_days >= 10: results.append((p,h,d))

        if i % 10 == 0 or i == total:
            elapsed = (datetime.now()-start_time).total_seconds()
            avg_per_player = elapsed / i
            remaining_time = avg_per_player * (total - i)
            minutes_left = int(remaining_time // 60)
            percent = i / total
            bar_length = 20
            filled_length = int(bar_length * percent)
            bar = "▰"*filled_length + "▱"*(bar_length-filled_length)
            await progress_msg.edit(
                content=(
                    f"⚡ Sprawdzanie ULTRA…\n"
                    f"{bar} {i}/{total} ({percent*100:.1f}%)\n"
                    f"Znaleziono domków: {len(results)}\n"
                    f"Szacowany czas do końca: ~{minutes_left} min"
                )
            )

    results.sort(key=lambda x: hours_left(x[2]))
    results = results[:5]
    if not results: return await progress_msg.edit(content="❌ Brak domków dla filtra ULTRA.")

    msg = "**⚡ ULTRA TOP 5 domków (600+ lvl i offline ≥10 dni):**\n"
    for p,h,d in results: msg += f"**{p}**\n{h}\n⏳ {hours_left(d):.1f}h\n\n"
    await progress_msg.edit(content=msg)

# =========================
# ALERT 13 DAY
# =========================

@tasks.loop(minutes=30)
async def alert_loop():
    if not CACHE: return
    channel = bot.get_channel(CHANNEL_ID)
    if not channel: return
    for p,h,d in CACHE:
        offline = (datetime.now()-d).total_seconds()/86400
        if 13<=offline<14:
            await channel.send(
                f"⚠️ **ALERT DOMKU**\n{p}\n{h}\nZa {hours_left(d):.1f}h domek trafi na sprzedaż!"
            )

# =========================
# START
# =========================

@bot.event
async def on_ready():
    print(f"Zalogowano jako {bot.user}")
    load_cache()
    update_cache.start()
    alert_loop.start()

bot.run(TOKEN)
