import discord
import google.generativeai as genai
import os
from dotenv import load_dotenv
from flask import Flask
from threading import Thread
import datetime

load_dotenv()

# ========== CONFIG ==========
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")
OWNER_ID = 1005357318281641994

# ห้องที่บอทจะตอบ (ไม่ต้องใช้ prefix)
ALLOWED_CHANNELS = [
    1518970044925739160,
   1519823094816968867,
]
# ============================

genai.configure(api_key=GEMINI_API_KEY)
model = genai.GenerativeModel("gemini-2.0-flash")

# เก็บประวัติแชทแยกต่อ channel
chat_sessions = {}

# เก็บสถิติการใช้งาน
stats = {
    "total_requests": 0,
    "total_tokens_in": 0,
    "total_tokens_out": 0,
    "start_time": datetime.datetime.now(),
}

intents = discord.Intents.default()
intents.message_content = True
client = discord.Client(intents=intents)


def get_chat(channel_id):
    if channel_id not in chat_sessions:
        chat_sessions[channel_id] = model.start_chat(history=[])
    return chat_sessions[channel_id]


def count_tokens(text):
    return model.count_tokens(text).total_tokens


# =======================
# WEB SERVER (ANTI-SLEEP)
# =======================
app = Flask('')

@app.route('/')
def home():
    uptime = datetime.datetime.now() - stats["start_time"]
    hours, remainder = divmod(int(uptime.total_seconds()), 3600)
    minutes, seconds = divmod(remainder, 60)

    total_tokens = stats["total_tokens_in"] + stats["total_tokens_out"]
    daily_token_limit = 1_000_000
    daily_req_limit = 1_500
    token_percent = round((total_tokens / daily_token_limit) * 100, 2)
    req_percent = round((stats["total_requests"] / daily_req_limit) * 100, 2)

    html = f"""
    <!DOCTYPE html>
    <html lang="th">
    <head>
        <meta charset="UTF-8">
        <meta http-equiv="refresh" content="30">
        <title>Discord AI Bot Status</title>
        <style>
            body {{ font-family: 'Segoe UI', sans-serif; background: #1a1a2e; color: #eee; padding: 30px; }}
            h1 {{ color: #00d4ff; }}
            .card {{ background: #16213e; border-radius: 12px; padding: 20px; margin: 16px 0; }}
            .label {{ color: #aaa; font-size: 0.85em; }}
            .value {{ font-size: 1.4em; font-weight: bold; color: #00d4ff; }}
            .bar-bg {{ background: #0f3460; border-radius: 8px; height: 14px; margin-top: 6px; }}
            .bar {{ height: 14px; border-radius: 8px; background: linear-gradient(90deg, #00d4ff, #7b2ff7); }}
            .green {{ color: #00ff88; }}
            .yellow {{ color: #ffd700; }}
            .grid {{ display: grid; grid-template-columns: 1fr 1fr; gap: 16px; }}
        </style>
    </head>
    <body>
        <h1>🤖 Discord AI Bot</h1>
        <p class="green">● Online — Uptime: {hours}h {minutes}m {seconds}s</p>

        <div class="card">
            <div class="label">Model</div>
            <div class="value">Gemini 1.5 Flash (Free Tier)</div>
        </div>

        <div class="grid">
            <div class="card">
                <div class="label">📨 Requests วันนี้</div>
                <div class="value">{stats["total_requests"]} / {daily_req_limit}</div>
                <div class="bar-bg"><div class="bar" style="width:{min(req_percent,100)}%"></div></div>
                <div class="label">{req_percent}% ของ limit</div>
            </div>
            <div class="card">
                <div class="label">🪙 Tokens วันนี้</div>
                <div class="value">{total_tokens:,} / {daily_token_limit:,}</div>
                <div class="bar-bg"><div class="bar" style="width:{min(token_percent,100)}%"></div></div>
                <div class="label">{token_percent}% ของ limit</div>
            </div>
        </div>

        <div class="grid">
            <div class="card">
                <div class="label">📥 Tokens Input</div>
                <div class="value">{stats["total_tokens_in"]:,}</div>
            </div>
            <div class="card">
                <div class="label">📤 Tokens Output</div>
                <div class="value">{stats["total_tokens_out"]:,}</div>
            </div>
        </div>

        <div class="card">
            <div class="label">⚡ Free Tier Limits (Gemini 1.5 Flash)</div>
            <p>• 15 requests/นาที</p>
            <p>• 1,500 requests/วัน</p>
            <p>• 1,000,000 tokens/วัน</p>
            <p class="yellow">⚠️ หน้านี้รีเฟรชทุก 30 วินาที — สถิติรีเซตเมื่อ restart บอท</p>
        </div>
    </body>
    </html>
    """
    return html

def run_web():
    port = int(os.environ.get("PORT", 8080))
    app.run(host="0.0.0.0", port=port)

def keep_alive():
    t = Thread(target=run_web)
    t.daemon = True
    t.start()
# =======================


@client.event
async def on_ready():
    print(f"✅ บอทออนไลน์แล้ว: {client.user}")


@client.event
async def on_message(message):
    # ไม่ตอบตัวเอง
    if message.author.bot:
        return

    # คำสั่งสำหรับ owner เท่านั้น
    if message.author.id == OWNER_ID:
        if message.content == "!reset":
            chat_sessions.pop(message.channel.id, None)
            await message.reply("🔄 รีเซตประวัติแชทแล้ว!")
            return
        if message.content == "!ping":
            await message.reply("🏓 Pong!")
            return
        if message.content == "!stats":
            total_tokens = stats["total_tokens_in"] + stats["total_tokens_out"]
            await message.reply(
                f"📊 **สถิติการใช้งาน**\n"
                f"• Requests: `{stats['total_requests']}` / 1,500\n"
                f"• Tokens: `{total_tokens:,}` / 1,000,000\n"
                f"• Input: `{stats['total_tokens_in']:,}` | Output: `{stats['total_tokens_out']:,}`"
            )
            return

    # ตรวจสอบว่าอยู่ในห้องที่อนุญาต
    if message.channel.id not in ALLOWED_CHANNELS:
        return

    user_input = message.content.strip()
    if not user_input:
        return

    async with message.channel.typing():
        try:
            chat = get_chat(message.channel.id)

            input_tokens = count_tokens(user_input)
            response = chat.send_message(user_input)
            reply = response.text
            output_tokens = count_tokens(reply)
            total_used = input_tokens + output_tokens

            # อัปเดตสถิติ
            stats["total_requests"] += 1
            stats["total_tokens_in"] += input_tokens
            stats["total_tokens_out"] += output_tokens

            limit_info = (
                f"\n\n> 📊 Token: `{input_tokens}` in / `{output_tokens}` out | รวม `{total_used}`\n"
                f"> 🆓 ใช้ไปแล้ว `{stats['total_requests']}` req • `{stats['total_tokens_in'] + stats['total_tokens_out']:,}` tokens วันนี้"
            )

            full_reply = reply + limit_info

            if len(full_reply) > 2000:
                await message.reply(reply[:1900] + "...")
                await message.channel.send(limit_info)
            else:
                await message.reply(full_reply)

        except Exception as e:
            await message.reply(f"❌ เกิดข้อผิดพลาด: `{str(e)}`")


keep_alive()
client.run(DISCORD_TOKEN)
