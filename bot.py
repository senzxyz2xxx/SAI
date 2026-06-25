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

ALLOWED_CHANNELS = [
    1518970044925739160,
    1519823094816968867,
]

MODEL_NAME = "gemini-3.1-flash-lite"
# ============================

genai.configure(api_key=GEMINI_API_KEY)
model = genai.GenerativeModel(MODEL_NAME)

chat_sessions = {}

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
    try:
        return model.count_tokens(text).total_tokens
    except:
        return len(text) // 4


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
    token_percent = min(round((total_tokens / daily_token_limit) * 100, 2), 100)
    req_percent = min(round((stats["total_requests"] / daily_req_limit) * 100, 2), 100)

    req_color = "#00ff88" if req_percent < 70 else "#ffd700" if req_percent < 90 else "#ff4444"
    tok_color = "#00ff88" if token_percent < 70 else "#ffd700" if token_percent < 90 else "#ff4444"

    html = f"""<!DOCTYPE html>
<html lang="th">
<head>
    <meta charset="UTF-8">
    <meta http-equiv="refresh" content="30">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>SAI — Bot Status</title>
    <link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap" rel="stylesheet">
    <style>
        * {{ margin: 0; padding: 0; box-sizing: border-box; }}
        body {{
            font-family: 'Inter', sans-serif;
            background: #0d0d14;
            color: #e2e8f0;
            min-height: 100vh;
            padding: 32px 20px;
        }}
        .container {{ max-width: 720px; margin: 0 auto; }}

        /* HEADER */
        .header {{
            display: flex;
            align-items: center;
            gap: 16px;
            margin-bottom: 32px;
        }}
        .avatar {{
            width: 56px; height: 56px;
            background: linear-gradient(135deg, #6366f1, #8b5cf6);
            border-radius: 16px;
            display: flex; align-items: center; justify-content: center;
            font-size: 28px;
        }}
        .header-text h1 {{
            font-size: 1.5rem;
            font-weight: 700;
            background: linear-gradient(135deg, #a78bfa, #60a5fa);
            -webkit-background-clip: text;
            -webkit-text-fill-color: transparent;
        }}
        .header-text p {{ color: #64748b; font-size: 0.85rem; margin-top: 2px; }}

        /* STATUS BADGE */
        .status-badge {{
            display: inline-flex;
            align-items: center;
            gap: 6px;
            background: #0f2d1f;
            border: 1px solid #166534;
            color: #4ade80;
            padding: 4px 12px;
            border-radius: 999px;
            font-size: 0.78rem;
            font-weight: 600;
            margin-bottom: 24px;
        }}
        .dot {{
            width: 7px; height: 7px;
            background: #4ade80;
            border-radius: 50%;
            animation: pulse 2s infinite;
        }}
        @keyframes pulse {{
            0%, 100% {{ opacity: 1; }}
            50% {{ opacity: 0.4; }}
        }}

        /* CARDS */
        .grid {{ display: grid; grid-template-columns: 1fr 1fr; gap: 14px; margin-bottom: 14px; }}
        .card {{
            background: #13131f;
            border: 1px solid #1e1e30;
            border-radius: 16px;
            padding: 20px;
            transition: border-color 0.2s;
        }}
        .card:hover {{ border-color: #6366f1; }}
        .card-full {{ grid-column: span 2; }}
        .card-label {{
            font-size: 0.72rem;
            font-weight: 600;
            text-transform: uppercase;
            letter-spacing: 0.08em;
            color: #475569;
            margin-bottom: 8px;
        }}
        .card-value {{
            font-size: 1.6rem;
            font-weight: 700;
            color: #f1f5f9;
            line-height: 1;
        }}
        .card-sub {{
            font-size: 0.78rem;
            color: #475569;
            margin-top: 4px;
        }}
        .card-icon {{ font-size: 1.1rem; margin-bottom: 6px; }}

        /* PROGRESS BAR */
        .bar-wrap {{ margin-top: 12px; }}
        .bar-header {{
            display: flex;
            justify-content: space-between;
            font-size: 0.75rem;
            color: #64748b;
            margin-bottom: 6px;
        }}
        .bar-bg {{
            background: #1e1e30;
            border-radius: 999px;
            height: 8px;
            overflow: hidden;
        }}
        .bar-fill {{
            height: 100%;
            border-radius: 999px;
            transition: width 0.5s ease;
        }}

        /* MODEL CARD */
        .model-card {{
            background: linear-gradient(135deg, #1a1a2e, #16162a);
            border: 1px solid #312e6b;
            border-radius: 16px;
            padding: 20px;
            margin-bottom: 14px;
            display: flex;
            align-items: center;
            gap: 16px;
        }}
        .model-icon {{
            width: 44px; height: 44px;
            background: linear-gradient(135deg, #4f46e5, #7c3aed);
            border-radius: 12px;
            display: flex; align-items: center; justify-content: center;
            font-size: 22px;
            flex-shrink: 0;
        }}
        .model-name {{ font-weight: 700; font-size: 1rem; color: #c4b5fd; }}
        .model-desc {{ font-size: 0.78rem; color: #64748b; margin-top: 2px; }}
        .model-badge {{
            margin-left: auto;
            background: #1e1b4b;
            color: #818cf8;
            border: 1px solid #3730a3;
            padding: 3px 10px;
            border-radius: 999px;
            font-size: 0.72rem;
            font-weight: 600;
            white-space: nowrap;
        }}

        /* LIMITS TABLE */
        .limits-card {{
            background: #13131f;
            border: 1px solid #1e1e30;
            border-radius: 16px;
            padding: 20px;
            margin-bottom: 14px;
        }}
        .limits-title {{
            font-size: 0.72rem;
            font-weight: 600;
            text-transform: uppercase;
            letter-spacing: 0.08em;
            color: #475569;
            margin-bottom: 14px;
        }}
        .limit-row {{
            display: flex;
            justify-content: space-between;
            align-items: center;
            padding: 10px 0;
            border-bottom: 1px solid #1e1e30;
        }}
        .limit-row:last-child {{ border-bottom: none; }}
        .limit-label {{ font-size: 0.85rem; color: #94a3b8; }}
        .limit-val {{ font-size: 0.85rem; font-weight: 600; color: #e2e8f0; }}

        /* FOOTER */
        .footer {{ text-align: center; color: #334155; font-size: 0.72rem; margin-top: 24px; }}

        @media (max-width: 480px) {{
            .grid {{ grid-template-columns: 1fr; }}
            .card-full {{ grid-column: span 1; }}
        }}
    </style>
</head>
<body>
<div class="container">

    <div class="header">
        <div class="avatar">🤖</div>
        <div class="header-text">
            <h1>SAI Bot</h1>
            <p>Discord AI Assistant</p>
        </div>
    </div>

    <div class="status-badge">
        <div class="dot"></div>
        Online — Uptime {hours}h {minutes}m {seconds}s
    </div>

    <div class="model-card">
        <div class="model-icon">✨</div>
        <div>
            <div class="model-name">{MODEL_NAME}</div>
            <div class="model-desc">Google Gemini — Fast & Efficient</div>
        </div>
        <div class="model-badge">Free Tier</div>
    </div>

    <div class="grid">
        <div class="card">
            <div class="card-icon">📨</div>
            <div class="card-label">Requests Today</div>
            <div class="card-value">{stats["total_requests"]}</div>
            <div class="card-sub">จาก {daily_req_limit:,} req/วัน</div>
            <div class="bar-wrap">
                <div class="bar-header"><span>{req_percent}% used</span><span>{daily_req_limit - stats["total_requests"]:,} เหลือ</span></div>
                <div class="bar-bg"><div class="bar-fill" style="width:{req_percent}%;background:{req_color}"></div></div>
            </div>
        </div>
        <div class="card">
            <div class="card-icon">🪙</div>
            <div class="card-label">Tokens Today</div>
            <div class="card-value">{total_tokens:,}</div>
            <div class="card-sub">จาก {daily_token_limit:,} tokens/วัน</div>
            <div class="bar-wrap">
                <div class="bar-header"><span>{token_percent}% used</span><span>{daily_token_limit - total_tokens:,} เหลือ</span></div>
                <div class="bar-bg"><div class="bar-fill" style="width:{token_percent}%;background:{tok_color}"></div></div>
            </div>
        </div>
        <div class="card">
            <div class="card-icon">📥</div>
            <div class="card-label">Input Tokens</div>
            <div class="card-value">{stats["total_tokens_in"]:,}</div>
            <div class="card-sub">จากข้อความผู้ใช้</div>
        </div>
        <div class="card">
            <div class="card-icon">📤</div>
            <div class="card-label">Output Tokens</div>
            <div class="card-value">{stats["total_tokens_out"]:,}</div>
            <div class="card-sub">จากคำตอบบอท</div>
        </div>
    </div>

    <div class="limits-card">
        <div class="limits-title">⚡ Free Tier Rate Limits</div>
        <div class="limit-row">
            <span class="limit-label">Requests / นาที</span>
            <span class="limit-val">15 RPM</span>
        </div>
        <div class="limit-row">
            <span class="limit-label">Requests / วัน</span>
            <span class="limit-val">1,500 RPD</span>
        </div>
        <div class="limit-row">
            <span class="limit-label">Tokens / นาที</span>
            <span class="limit-val">250,000 TPM</span>
        </div>
        <div class="limit-row">
            <span class="limit-label">Tokens / วัน</span>
            <span class="limit-val">1,000,000 TPD</span>
        </div>
        <div class="limit-row">
            <span class="limit-label">Context Window</span>
            <span class="limit-val">1,000,000 tokens</span>
        </div>
    </div>

    <div class="footer">หน้านี้รีเฟรชอัตโนมัติทุก 30 วินาที • สถิติรีเซตเมื่อ restart บอท</div>

</div>
</body>
</html>"""
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
    if message.author.bot:
        return

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

            stats["total_requests"] += 1
            stats["total_tokens_in"] += input_tokens
            stats["total_tokens_out"] += output_tokens

            if len(reply) > 2000:
                await message.reply(reply[:1950] + "...")
            else:
                await message.reply(reply)

        except Exception as e:
            await message.reply(f"❌ เกิดข้อผิดพลาด: `{str(e)}`")


keep_alive()
client.run(DISCORD_TOKEN)
