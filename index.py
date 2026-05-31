import discord
from discord.ext import commands
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.options import Options
import asyncio
import psycopg2
import os
import time

# ============ CONFIG ============
DISCORD_TOKEN = os.environ.get("DISCORD_TOKEN")
ATERNOS_SESSION = os.environ.get("ATERNOS_SESSION", "SLkefIvJmbAnAuSyV21uggdX8P93jmagNcpLvCVZjdHymTSl3EBOIbYQKXaVoofeuqyegaCOOWKbwadyvzH08SRWHWHsmgkqtl4Y")
DATABASE_URL = os.environ.get("DATABASE_URL", "postgresql://idkmommyfuhme_user:IrJpLB9SwzCNuHxiTIErQ5d0EFueJSz7@dpg-d8e0n3740ujc73d4pdqg-a/idkmommyfuhme")
PREFIX = "+"
COOLDOWN_SECONDS = 30
# ================================

# ── Database ───────────────────────────────────────────────────────

def get_db():
    return psycopg2.connect(DATABASE_URL)

def setup_db():
    conn = get_db()
    cur = conn.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS logs (
            id SERIAL PRIMARY KEY,
            user_id TEXT,
            username TEXT,
            action TEXT,
            timestamp TIMESTAMP DEFAULT NOW()
        );
        CREATE TABLE IF NOT EXISTS stats (
            key TEXT PRIMARY KEY,
            value TEXT
        );
    """)
    conn.commit()
    cur.close()
    conn.close()

def log_action(user_id, username, action):
    try:
        conn = get_db()
        cur = conn.cursor()
        cur.execute(
            "INSERT INTO logs (user_id, username, action) VALUES (%s, %s, %s)",
            (str(user_id), username, action)
        )
        conn.commit()
        cur.close()
        conn.close()
    except Exception as e:
        print(f"DB error: {e}")

def get_start_count():
    try:
        conn = get_db()
        cur = conn.cursor()
        cur.execute("SELECT value FROM stats WHERE key = 'start_count'")
        row = cur.fetchone()
        cur.close()
        conn.close()
        return int(row[0]) if row else 0
    except:
        return 0

def increment_start_count():
    try:
        conn = get_db()
        cur = conn.cursor()
        cur.execute("""
            INSERT INTO stats (key, value) VALUES ('start_count', '1')
            ON CONFLICT (key) DO UPDATE SET value = (CAST(stats.value AS INT) + 1)::TEXT
        """)
        conn.commit()
        cur.close()
        conn.close()
    except Exception as e:
        print(f"DB error: {e}")

def get_recent_logs():
    try:
        conn = get_db()
        cur = conn.cursor()
        cur.execute(
            "SELECT username, action, timestamp FROM logs ORDER BY timestamp DESC LIMIT 5"
        )
        rows = cur.fetchall()
        cur.close()
        conn.close()
        return rows
    except:
        return []

# ── Selenium ───────────────────────────────────────────────────────

def get_driver():
    options = Options()
    options.add_argument("--headless")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-setuid-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--disable-gpu")
    options.add_argument("--no-zygote")
    options.add_argument("--single-process")
    driver = webdriver.Chrome(options=options)
    return driver

def get_aternos_page(driver):
    driver.get("https://aternos.org/server/")
    driver.add_cookie({
        "name": "ATERNOS_SESSION",
        "value": ATERNOS_SESSION,
        "domain": ".aternos.org"
    })
    driver.get("https://aternos.org/server/")
    return driver

def get_status(driver):
    try:
        el = driver.find_element(By.CSS_SELECTOR, ".statuslabel-label")
        return el.text.strip().lower()
    except:
        return "unknown"

def get_ip(driver):
    try:
        return driver.find_element(By.CSS_SELECTOR, ".server-ip").text.strip()
    except:
        return "Check Aternos for IP"

def get_queue(driver):
    try:
        return driver.find_element(By.CSS_SELECTOR, ".queue-position").text.strip()
    except:
        return None

def get_players(driver):
    try:
        return driver.find_element(By.CSS_SELECTOR, ".players").text.strip()
    except:
        return "0/0"

# ── Bot setup ──────────────────────────────────────────────────────

intents = discord.Intents.default()
intents.message_content = True
intents.guilds = True
intents.voice_states = True
bot = commands.Bot(command_prefix=PREFIX, intents=intents, help_command=None)

cooldowns = {}

# ── Commands ───────────────────────────────────────────────────────

@bot.command(name="help")
async def cmd_help(ctx):
    await ctx.reply(
        f"╔════════════════════════╗\n"
        f"║   📖 **Server Bot Help**   ║\n"
        f"╚════════════════════════╝\n\n"
        f"👥 **Everyone:**\n"
        f"> `+startserver` — Start the Minecraft server\n"
        f"> `+serverstatus` — Check if server is online + player count\n"
        f"> `+serverlogs` — See who started/stopped the server recently\n"
        f"> `+help` — Show this message\n\n"
        f"🔐 **Admins Only:**\n"
        f"> `+stopserver` — Force stop the server\n"
        f"> `+restartserver` — Restart the server\n\n"
        f"🌙 **Auto:** Server shuts down when everyone leaves!"
    )

@bot.command(name="startserver")
async def cmd_start(ctx):
    now = time.time()
    last = cooldowns.get(ctx.author.id, 0)
    diff = now - last
    if diff < COOLDOWN_SECONDS:
        return await ctx.reply(f"⏳ Wait **{COOLDOWN_SECONDS - diff:.1f}s** before trying again.")
    cooldowns[ctx.author.id] = now

    msg = await ctx.reply("🔍 Checking server status...")
    loop = asyncio.get_event_loop()

    def start_task():
        driver = get_driver()
        try:
            get_aternos_page(driver)
            status = get_status(driver)
            if status == "online":
                ip = get_ip(driver)
                driver.quit()
                return ("already_online", ip, None)
            if status in ["starting", "loading", "waiting"]:
                queue = get_queue(driver)
                driver.quit()
                return ("already_starting", None, queue)
            driver.find_element(By.ID, "start").click()
            time.sleep(3)
            queue = get_queue(driver)
            driver.quit()
            return ("started", None, queue)
        except Exception as e:
            driver.quit()
            raise e

    try:
        result = await loop.run_in_executor(None, start_task)
        state, ip, queue = result

        if state == "already_online":
            return await msg.edit(content=f"✅ Server is already online!\n🌐 Connect at **{ip}**")

        if state == "already_starting":
            qt = f"\n📋 Queue: **{queue}**" if queue else ""
            return await msg.edit(content=f"⏳ Server is already starting up!{qt}")

        qt = f"\n📋 Queue: **{queue}**" if queue else ""
        await msg.edit(content=f"🚀 Server is booting up! Hang tight.{qt}\n📣 I'll ping here when it's ready!")

        log_action(ctx.author.id, str(ctx.author), "start")
        increment_start_count()

        async def poll():
            for _ in range(40):
                await asyncio.sleep(15)
                def check():
                    d = get_driver()
                    get_aternos_page(d)
                    s = get_status(d)
                    i = get_ip(d)
                    d.quit()
                    return s, i
                s, i = await loop.run_in_executor(None, check)
                if s == "online":
                    await ctx.channel.send(f"🟢 **Server is ONLINE!**\n🌐 Connect at **{i}**")
                    return

        asyncio.create_task(poll())

    except Exception as e:
        print(e)
        await msg.edit(content="❌ Something went wrong while starting the server.")

@bot.command(name="stopserver")
async def cmd_stop(ctx):
    if not ctx.author.guild_permissions.administrator:
        return await ctx.reply("❌ You don't have permission to do that!")

    msg = await ctx.reply("🔴 Stopping the server...")
    loop = asyncio.get_event_loop()

    def stop_task():
        driver = get_driver()
        get_aternos_page(driver)
        status = get_status(driver)
        if status == "offline":
            driver.quit()
            return "already_offline"
        driver.find_element(By.ID, "stop").click()
        time.sleep(3)
        driver.quit()
        return "stopped"

    try:
        result = await loop.run_in_executor(None, stop_task)
        if result == "already_offline":
            await msg.edit(content="⚠️ Server is already offline!")
        else:
            log_action(ctx.author.id, str(ctx.author), "stop")
            await msg.edit(content="🔴 Server has been stopped successfully!")
    except Exception as e:
        print(e)
        await msg.edit(content="❌ Something went wrong while stopping the server.")

@bot.command(name="restartserver")
async def cmd_restart(ctx):
    if not ctx.author.guild_permissions.administrator:
        return await ctx.reply("❌ You don't have permission to do that!")

    msg = await ctx.reply("🔄 Restarting the server...")
    loop = asyncio.get_event_loop()

    def restart_task():
        driver = get_driver()
        get_aternos_page(driver)
        driver.find_element(By.ID, "restart").click()
        time.sleep(3)
        driver.quit()

    try:
        await loop.run_in_executor(None, restart_task)
        log_action(ctx.author.id, str(ctx.author), "restart")
        await msg.edit(content="🔄 Server is restarting! It'll be back up shortly.")
    except Exception as e:
        print(e)
        await msg.edit(content="❌ Something went wrong while restarting the server.")

@bot.command(name="serverstatus")
async def cmd_status(ctx):
    msg = await ctx.reply("🔍 Fetching server status...")
    loop = asyncio.get_event_loop()

    def status_task():
        driver = get_driver()
        get_aternos_page(driver)
        status = get_status(driver)
        ip = get_ip(driver)
        players = get_players(driver)
        queue = get_queue(driver)
        driver.quit()
        return status, ip, players, queue

    try:
        status, ip, players, queue = await loop.run_in_executor(None, status_task)

        emoji = {"online": "🟢", "offline": "🔴", "starting": "🟡", "loading": "🟡", "waiting": "🟡"}.get(status, "⚪")
        label = status.capitalize()
        count = get_start_count()

        reply = (
            f"╔══════════════════════╗\n"
            f"║  {emoji} **Server Status**  ║\n"
            f"╚══════════════════════╝\n\n"
            f"📡 **Status:** {label}\n"
        )
        if status == "online":
            reply += f"🌐 **IP:** {ip}\n👥 **Players:** {players}\n"
        if queue:
            reply += f"📋 **Queue:** {queue}\n"
        reply += f"🚀 **Total Starts:** {count}"

        await msg.edit(content=reply)
    except Exception as e:
        print(e)
        await msg.edit(content="❌ Couldn't fetch server status.")

@bot.command(name="serverlogs")
async def cmd_logs(ctx):
    logs = get_recent_logs()
    if not logs:
        return await ctx.reply("📭 No logs yet!")

    lines = "\n".join([f"> `{action.upper()}` by **{username}** at {timestamp.strftime('%Y-%m-%d %H:%M')}" for username, action, timestamp in logs])
    await ctx.reply(
        f"📋 **Recent Server Logs:**\n\n{lines}"
    )
# flask

from flask import Flask
from threading import Thread

app = Flask(__name__)

@app.route('/')
def home():
    return "Bot is running!"

def run_flask():
    app.run(host="0.0.0.0", port=8080)

Thread(target=run_flask).start()

# ── Ready ──────────────────────────────────────────────────────────

@bot.event
async def on_ready():
    setup_db()
    print(f"✅ Bot online as {bot.user}")

bot.run(DISCORD_TOKEN)
