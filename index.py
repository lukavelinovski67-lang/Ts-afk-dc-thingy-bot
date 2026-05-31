import discord
from discord.ext import commands
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.options import Options
from flask import Flask
from threading import Thread
import asyncio
import psycopg2
import os
import time
from datetime import datetime

# ============ CONFIG ============
DISCORD_TOKEN = os.environ.get("DISCORD_TOKEN")
ATERNOS_SESSION = os.environ.get("ATERNOS_SESSION")
DATABASE_URL = os.environ.get("DATABASE_URL")
PREFIX = "+"
COOLDOWN_SECONDS = 30
# ================================

# ── Flask (keeps Render alive) ─────────────────────────────────────

app = Flask(__name__)

@app.route("/")
def home():
    return "Bot is running!"

def run_flask():
    app.run(host="0.0.0.0", port=8080)

Thread(target=run_flask).start()

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
    options.binary_location = "/usr/bin/chromium"
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
        return driver.find_element(By.CSS_SELECTOR, ".statuslabel-label").text.strip().lower()
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

# ── Embed helpers ──────────────────────────────────────────────────

def make_embed(title, description, color):
    embed = discord.Embed(title=title, description=description, color=color)
    embed.set_footer(text="Aternos Server Bot")
    embed.timestamp = datetime.utcnow()
    return embed

COLOR_GREEN  = 0x57F287
COLOR_RED    = 0xED4245
COLOR_YELLOW = 0xFEE75C
COLOR_BLUE   = 0x5865F2
COLOR_GRAY   = 0x95A5A6

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
    embed = make_embed("📖 Server Bot Help", "", COLOR_BLUE)
    embed.add_field(
        name="👥 Everyone",
        value=(
            "`+startserver` — Start the Minecraft server\n"
            "`+serverstatus` — Check if server is online\n"
            "`+serverlogs` — See recent server activity\n"
            "`+help` — Show this message"
        ),
        inline=False
    )
    embed.add_field(
        name="🔐 Admins Only",
        value=(
            "`+stopserver` — Force stop the server\n"
            "`+restartserver` — Restart the server"
        ),
        inline=False
    )
    embed.add_field(
        name="🌙 Auto",
        value="Server shuts down automatically when everyone leaves!",
        inline=False
    )
    await ctx.reply(embed=embed)

@bot.command(name="startserver")
async def cmd_start(ctx):
    now = time.time()
    last = cooldowns.get(ctx.author.id, 0)
    diff = now - last
    if diff < COOLDOWN_SECONDS:
        embed = make_embed("⏳ Cooldown", f"Wait **{COOLDOWN_SECONDS - diff:.1f}s** before trying again.", COLOR_YELLOW)
        return await ctx.reply(embed=embed)
    cooldowns[ctx.author.id] = now

    embed = make_embed("🔍 Checking...", "Checking server status, please wait...", COLOR_BLUE)
    msg = await ctx.reply(embed=embed)
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
            embed = make_embed("✅ Already Online!", f"🌐 Connect at **{ip}**", COLOR_GREEN)
            return await msg.edit(embed=embed)

        if state == "already_starting":
            desc = "Server is already starting up!"
            if queue:
                desc += f"\n📋 Queue position: **{queue}**"
            embed = make_embed("⏳ Already Starting!", desc, COLOR_YELLOW)
            return await msg.edit(embed=embed)

        desc = "Server is booting up! Hang tight.\n📣 I'll ping here when it's ready!"
        if queue:
            desc += f"\n📋 Queue position: **{queue}**"
        embed = make_embed("🚀 Server Starting!", desc, COLOR_YELLOW)
        await msg.edit(embed=embed)

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
                    embed = make_embed("🟢 Server is ONLINE!", f"🌐 Connect at **{i}**", COLOR_GREEN)
                    await ctx.channel.send(embed=embed)
                    return

        asyncio.create_task(poll())

    except Exception as e:
        print(e)
        embed = make_embed("❌ Error", "Something went wrong while starting the server.", COLOR_RED)
        await msg.edit(embed=embed)

@bot.command(name="stopserver")
async def cmd_stop(ctx):
    if not ctx.author.guild_permissions.administrator:
        embed = make_embed("❌ No Permission", "You don't have permission to do that!", COLOR_RED)
        return await ctx.reply(embed=embed)

    embed = make_embed("🔴 Stopping...", "Sending stop signal to Aternos...", COLOR_BLUE)
    msg = await ctx.reply(embed=embed)
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
            embed = make_embed("⚠️ Already Offline", "The server is already offline!", COLOR_YELLOW)
        else:
            log_action(ctx.author.id, str(ctx.author), "stop")
            embed = make_embed("🔴 Server Stopped", "The server has been stopped successfully!", COLOR_RED)
        await msg.edit(embed=embed)
    except Exception as e:
        print(e)
        embed = make_embed("❌ Error", "Something went wrong while stopping the server.", COLOR_RED)
        await msg.edit(embed=embed)

@bot.command(name="restartserver")
async def cmd_restart(ctx):
    if not ctx.author.guild_permissions.administrator:
        embed = make_embed("❌ No Permission", "You don't have permission to do that!", COLOR_RED)
        return await ctx.reply(embed=embed)

    embed = make_embed("🔄 Restarting...", "Sending restart signal to Aternos...", COLOR_BLUE)
    msg = await ctx.reply(embed=embed)
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
        embed = make_embed("🔄 Server Restarting", "Server is restarting! It'll be back up shortly.", COLOR_YELLOW)
        await msg.edit(embed=embed)
    except Exception as e:
        print(e)
        embed = make_embed("❌ Error", "Something went wrong while restarting the server.", COLOR_RED)
        await msg.edit(embed=embed)

@bot.command(name="serverstatus")
async def cmd_status(ctx):
    embed = make_embed("🔍 Fetching Status...", "Please wait...", COLOR_BLUE)
    msg = await ctx.reply(embed=embed)
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

        color_map = {"online": COLOR_GREEN, "offline": COLOR_RED, "starting": COLOR_YELLOW, "loading": COLOR_YELLOW, "waiting": COLOR_YELLOW}
        emoji_map = {"online": "🟢", "offline": "🔴", "starting": "🟡", "loading": "🟡", "waiting": "🟡"}
        color = color_map.get(status, COLOR_GRAY)
        emoji = emoji_map.get(status, "⚪")
        count = get_start_count()

        embed = make_embed(f"{emoji} Server Status", "", color)
        embed.add_field(name="📡 Status", value=status.capitalize(), inline=True)
        embed.add_field(name="🚀 Total Starts", value=str(count), inline=True)
        if status == "online":
            embed.add_field(name="🌐 IP", value=f"`{ip}`", inline=False)
            embed.add_field(name="👥 Players", value=players, inline=True)
        if queue:
            embed.add_field(name="📋 Queue", value=queue, inline=True)

        await msg.edit(embed=embed)
    except Exception as e:
        print(e)
        embed = make_embed("❌ Error", "Couldn't fetch server status.", COLOR_RED)
        await msg.edit(embed=embed)

@bot.command(name="serverlogs")
async def cmd_logs(ctx):
    logs = get_recent_logs()
    if not logs:
        embed = make_embed("📭 No Logs", "No server activity yet!", COLOR_GRAY)
        return await ctx.reply(embed=embed)

    embed = make_embed("📋 Recent Server Logs", "", COLOR_BLUE)
    for username, action, timestamp in logs:
        emoji = {"start": "🟢", "stop": "🔴", "restart": "🔄"}.get(action, "⚪")
        embed.add_field(
            name=f"{emoji} {action.upper()}",
            value=f"By **{username}**\n`{timestamp.strftime('%Y-%m-%d %H:%M')}`",
            inline=True
        )
    await ctx.reply(embed=embed)

# ── Ready ──────────────────────────────────────────────────────────

@bot.event
async def on_ready():
    setup_db()
    print(f"✅ Bot online as {bot.user}")

bot.run(DISCORD_TOKEN)
