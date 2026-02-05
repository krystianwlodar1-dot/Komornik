import discord
from discord.ext import commands, tasks
import requests
from bs4 import BeautifulSoup
import json
from datetime import datetime, timezone
import os

# --- VARIABLES FROM RAILWAY ENV ---
TOKEN = os.getenv("DISCORD_TOKEN")
DISCORD_CHANNEL = int(os.getenv("DISCORD_CHANNEL"))

# --- CONSTANTS ---
HOUSES_URL = "https://cyleria.pl/?subtopic=houses"
HIGHSCORES_URL = "https://cyleria.pl/?subtopic=highscores"
CACHE_FILE = "cache.json"
MIN_LEVEL = 600

intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix="!", intents=intents)

cache = []

# --- UTILS ---
def save_cache_to_file():
    with open(CACHE_FILE, "w", encoding="utf-8") as f:
        json.dump(cache, f, ensure_ascii=False, indent=2)

def load_cache_from_file():
    global cache
    if os.path.exists(CACHE_FILE):
        with open(CACHE_FILE, "r", encoding="utf-8") as f:
            cache = json.load(f)

def fetch_houses():
    resp = requests.get(HOUSES_URL)
    resp.raise_for_status()
    soup = BeautifulSoup(resp.text, "html.parser")
    houses = []

    # przykładowa logika parsowania
    table = soup.find("table")
    if not table:
        return houses

    for row in table.find_all("tr")[1:]:
        cells = row.find_all("td")
        if len(cells) < 4:
            continue
        try:
            name = cells[0].get_text(strip=True)
            size = int(cells[1].get_text(strip=True))
            owner = cells[2].get_text(strip=True)
            last_login_str = cells[3].get_text(strip=True)
            last_login = datetime.strptime(last_login_str, "%d.%m.%Y (%H:%M)") if last_login_str else None
            link_map = cells[0].find("a")["href"] if cells[0].find("a") else None

            houses.append({
                "name": name,
                "size": size,
                "owner": owner,
                "last_login": last_login_str,
                "link": link_map
            })
        except Exception:
            continue
    return houses

async def build_cache(ctx=None):
    global cache
    houses = fetch_houses()
    cache = []

    total = len(houses)
    progress_msg = None

    for idx, house in enumerate(houses, start=1):
        # sprawdz minimalny poziom (tutaj uproszczenie, jeśli dostępne w owner)
        cache.append(house)

        # postęp liczbowy w Discordzie
        if ctx:
            text = f"🔄 Budowanie cache: {idx}/{total} domków"
            if progress_msg is None:
                progress_msg = await ctx.send(text)
            else:
                try:
                    await progress_msg.edit(content=text)
                except discord.HTTPException:
                    pass
        else:
            print(f"🔄 Budowanie cache: {idx}/{total} domków")

    save_cache_to_file()

    if ctx:
        done_text = f"✅ Cache zbudowany. Znaleziono {len(cache)} domków."
        if progress_msg:
            await progress_msg.edit(content=done_text)
        else:
            await ctx.send(done_text)
    print(f"✅ Cache zbudowany. Znaleziono {len(cache)} domków.")

# --- EVENTS ---
@bot.event
async def on_ready():
    print(f"Zalogowano jako {bot.user}")
    load_cache_from_file()
    channel = bot.get_channel(DISCORD_CHANNEL)
    if channel:
        await build_cache(ctx=channel)
        await channel.send("✅ Bot gotowy i cache zbudowany.")

# --- COMMANDS ---
@bot.command()
async def status(ctx):
    if not cache:
        await ctx.send("⚠️ Cache nie był jeszcze budowany!")
        return
    await ctx.send(f"Cache zawiera {len(cache)} domków.")

@bot.command()
async def sprawdz(ctx):
    if not cache:
        await ctx.send("⚠️ Cache nie był jeszcze budowany!")
        return
    text_list = []
    for house in cache:
        line = f"{house['name']} ({house['size']}) - {house['owner']} - {house['last_login']}"
        if house.get("link"):
            line += f" [Mapa]({house['link']})"
        text_list.append(line)
    
    # dziel na fragmenty po 1900 znaków, żeby nie przekroczyć limitu Discorda
    CHUNK_SIZE = 1900
    for i in range(0, len(text_list), 20):
        chunk = "\n".join(text_list[i:i+20])
        await ctx.send(chunk or "Brak domków spełniających kryteria.")

@bot.command()
async def info(ctx):
    info_text = """
**Dostępne komendy:**
!status - Pokazuje ile domków jest w cache.
!sprawdz - Pokazuje wszystkie domki spełniające kryteria z linkami do mapy.
!info - Wyświetla ten opis.
"""
    await ctx.send(info_text)

bot.run(TOKEN)
