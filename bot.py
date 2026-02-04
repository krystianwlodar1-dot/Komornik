import discord
from discord.ext import commands, tasks
import requests
from bs4 import BeautifulSoup
from datetime import datetime, timedelta
import os
from dotenv import load_dotenv

load_dotenv()

TOKEN = os.getenv("TOKEN")
CHANNEL_ID = int(os.getenv("CHANNEL_ID"))  # ID kanału do powiadomień

intents = discord.Intents.default()
bot = commands.Bot(command_prefix="!", intents=intents)

CYLERIA = "https://cyleria.pl"

# ---------- SCRAPING ----------

def get_houses():
    url = f"{CYLERIA}/?subtopic=houses"
    soup = BeautifulSoup(requests.get(url).text, "html.parser")

    houses = []

    for row in soup.find_all("tr")[1:]:
        cols = row.find_all("td")
        if len(cols) < 5:
            continue

        name = cols[0].text.strip()
        city = cols[1].text.strip()
        owner = cols[2].text.strip()
        address = cols[3].text.strip()
        map_link = CYLERIA + cols[3].find("a")["href"] if cols[3].find("a") else "Brak mapy"

        if owner != "None":
            houses.append({
                "name": name,
                "city": city,
                "owner": owner,
                "address": address,
                "map": map_link
            })

    return houses


def get_last_login(player):
    url = f"{CYLERIA}/?subtopic=characters&name={player.replace(' ', '+')}"
    soup = BeautifulSoup(requests.get(url).text, "html.parser")

    rows = soup.find_all("tr")
    for row in rows:
        if "Last Login" in row.text:
            date_str = row.find_all("td")[1].text.strip()
            try:
                return datetime.strptime(date_str, "%d %b %Y, %H:%M:%S")
            except:
                return None
    return None


# ---------- KOMENDY ----------

@bot.command()
async def info(ctx):
    await ctx.send("""
**📌 Dostępne komendy**
!info – pokazuje wszystkie komendy  
!sprawdz [miasto] – pokazuje 5 najdłużej offline właścicieli domków, filtr na miasto opcjonalny  
""")


@bot.command()
async def sprawdz(ctx, *, miasto=None):
    await ctx.send("⏳ Sprawdzam domki...")

    houses = get_houses()
    results = []

    for h in houses:
        if miasto and h["city"].lower() != miasto.lower():
            continue

        last = get_last_login(h["owner"])
        if not last:
            continue

        offline_delta = datetime.utcnow() - last

        results.append({
            "owner": h["owner"],
            "city": h["city"],
            "address": h["address"],
            "map": h["map"],
            "offline_days": offline_delta.days,
            "offline_hours": offline_delta.seconds // 3600
        })

    results.sort(key=lambda x: x["offline_days"], reverse=True)
    top = results[:5]

    if not top:
        await ctx.send("Nie znaleziono domków dla tego filtra.")
        return

    msg = "**🏠 Najdłużej offline właściciele domków:**\n\n"
    for r in top:
        msg += f"""
**{r['owner']}**
📍 {r['city']} – {r['address']}
🗺 {r['map']}
⏱ {r['offline_days']} dni {r['offline_hours']} godzin offline
"""
    await ctx.send(msg)


# ---------- POWIADOMIENIA ----------

@tasks.loop(minutes=60)
async def check_13_days():
    channel = bot.get_channel(CHANNEL_ID)
    if not channel:
        print("Nie znaleziono kanału!")
        return

    houses = get_houses()
    for h in houses:
        last = get_last_login(h["owner"])
        if not last:
            continue

        offline_delta = datetime.utcnow() - last
        offline_days = offline_delta.days
        offline_hours = offline_delta.seconds // 3600
        remaining = timedelta(days=14) - offline_delta

        remaining_days = remaining.days
        remaining_hours = remaining.seconds // 3600

        if offline_days == 13:
            await channel.send(
                f"⚠️ **{h['owner']}** ma domek w {h['city']} – {h['address']} i jest offline {offline_days} dni {offline_hours} godzin!\n"
                f"⏳ Do wystawienia: {remaining_days} dni {remaining_hours} godzin."
            )
        elif offline_days >= 14:
            await channel.send(
                f"🏠 **{h['owner']}** domek w {h['city']} – {h['address']} został wystawiony na sprzedaż! ({offline_days} dni offline)"
            )


@bot.event
async def on_ready():
    print(f"Zalogowano jako {bot.user}")
    check_13_days.start()


bot.run(TOKEN)
