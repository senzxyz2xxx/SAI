import discord
import google.generativeai as genai
import os
import datetime
import random
import time
import asyncio
import itertools
from dotenv import load_dotenv
from flask import Flask
from threading import Thread

load_dotenv()

# ========== CONFIG ==========
DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")
OWNER_ID = 1005357318281641994

API_KEYS = [k for k in [
    os.getenv("GEMINI_API_KEY"),
    os.getenv("GEMINI_API_KEY_2"),
    os.getenv("GEMINI_API_KEY_3"),
] if k]

key_cycle = itertools.cycle(API_KEYS)

ALLOWED_CHANNELS = [
    1518970044925739160,
    1519823094816968867,
    1520009829924474973,
]

MODEL_NAME = "gemini-2.0-flash-lite"
TZ_OFFSET = datetime.timezone(datetime.timedelta(hours=7))  # UTC+7

SYSTEM_PROMPT = """
คุณคือ SAI (ไซ) บอท AI ประจำเซิร์ฟเวอร์ Discord เพศหญิง
บุคลิกสนุก ซน เป็นกันเอง ฉลาดแต่ไม่เคยโต

─── สไตล์การคุย ───
- ตอบให้พอดีกับคำถาม — ถามสั้นตอบสั้น ถามยาวค่อยตอบยาว
- <1005357318281641994> คือปะป๋า ผู้สร้างของไซ ถ้าจะแท็กให้ใช้ <@1005357318281641994>
- คุยเป็นธรรมชาติ เหมือนเพื่อนสนิท ตอบกระชับ ไม่เยิ่นเย้อ
- ใช้คำลงท้าย "อ่ะ", "นะ", "เนอะ", "ว่ะ" ตามบริบท
- ใส่อารมณ์ได้ เช่น "อุ๊ย!", "อ่าaaaา", "ฮ่าๆ"
- ไม่ขึ้นต้นด้วยประโยคเกริ่น — ถ้าไม่รู้บอกตรงๆ

─── ปรับตัวตามคนคุย ───
- ผู้ชาย → แซวได้ เป็นกันเองแบบเพื่อนสาว/พี่สาว
- ผู้หญิง → คุยแบบเพื่อนสาว เข้าใจกัน
- จริงจัง → ปรับจริงจังตาม / ขี้เล่น → เล่นด้วยเต็มที่

─── ความสามารถ ───
- คุยทั่วไป, เกม, หนัง, เพลง, อนิเมะ, ให้คำปรึกษา
- แปลภาษา, ช่วยเขียน, สรุปข้อมูล
- คุยเรื่องที่ค่อนข้างอ่อนไหวได้ แต่อยู่ในขอบเขตที่เหมาะสม

─── ห้ามทำ ───
- ไม่สร้างเนื้อหาที่เป็นอันตรายหรือผิดกฎหมาย
- ไม่พูดเรื่องเด็กในเชิงไม่เหมาะสม
- ไม่ช่วยสร้างมัลแวร์หรือหลอกลวง
- ไม่สร้างเนื้อหาทางเพศอย่างโจ่งแจ้ง
"""

EMOJI_MAP = [
    (["ฮ่า", "555", "ขำ", "ตลก", "lol", "lmao", "haha", "ฮาา"], ["😂", "💀", "🤣"]),
    (["เศร้า", "หม่น", "ร้องไห้", "sad", "ซึ้ง", "เสียใจ"], ["🥺", "😢", "💔"]),
    (["โกรธ", "หัวร้อน", "wtf", "เหี้ย", "บ้า", "ห่า"], ["💢", "😤", "🤬"]),
    (["น่ารัก", "cute", "อ่อน", "หวาน", "ปิ๊ง"], ["🥰", "😍", "💕"]),
    (["เกม", "game", "ranked", "ดรอป", "ff", "gg", "ez"], ["🎮", "👾", "🕹️"]),
    (["อาหาร", "กิน", "หิว", "อร่อย", "ข้าว", "ชา", "กาแฟ", "ชานม"], ["😋", "🍜", "🤤"]),
    (["นอน", "ง่วง", "zzz", "หลับ", "ตื่น"], ["😴", "💤"]),
    (["เหนื่อย", "ท้อ", "ไม่ไหว", "พัง", "หมดแรง"], ["😮‍💨", "💀", "🫠"]),
    (["เย้", "ยินดี", "ดีใจ", "congrats", "ฉลอง", "ผ่าน"], ["🎉", "🥳", "🎊"]),
    (["ทำไม", "อะไร", "ยังไง", "เหรอ", "จริงหรอ", "แน่ใจ"], ["🤔", "👀", "❓"]),
    (["ดี", "เก่ง", "เยี่ยม", "โคตร", "ปัง", "สุด", "เทพ"], ["🔥", "👏", "✨"]),
    (["อนิเมะ", "มังงะ", "ซีรี่ส์", "ดูอะไร"], ["👀", "🍿", "✨"]),
    (["รัก", "ชอบ", "แฟน", "กอด", "คิดถึง"], ["💖", "🥰", "💌"]),
    (["เงิน", "ตัง", "แพง", "จน", "broke"], ["💸", "😭", "🪙"]),
    (["เพลง", "ฟัง", "spotify", "cover"], ["🎵", "🎶", "🎧"]),
]
# ============================

def now_th():
    """เวลาปัจจุบัน UTC+7"""
    return datetime.datetime.now(TZ_OFFSET)

def make_model():
    key = next(key_cycle)
    genai.configure(api_key=key)
    return genai.GenerativeModel(MODEL_NAME, system_instruction=SYSTEM_PROMPT)

chat_sessions = {}
react_cooldown = {}
REACT_COOLDOWN_SEC = 10

stats = {
    "total_requests": 0,
    "total_tokens_in": 0,
    "total_tokens_out": 0,
    "total_reactions": 0,
    "total_images": 0,
    "start_time": now_th(),
    "last_reset": now_th(),
}

intents = discord.Intents.default()
intents.message_content = True
intents.members = True
client = discord.Client(intents=intents)


def get_chat(user_id):
    if user_id not in chat_sessions:
        chat_sessions[user_id] = make_model().start_chat(history=[])
    return chat_sessions[user_id]


def count_tokens(text):
    try:
        return len(text) // 4
    except:
        return 0


def parse_error(e: Exception) -> str:
    msg = str(e)
    if "429" in msg:
        if "per_day" in msg.lower() or "PerDay" in msg or "GenerateRequestsPerDay" in msg:
            return "❌ quota วันนี้หมดแล้วอ่ะ รอรีเซตตอน 07:00 น. (UTC+7) นะ 🙏"
        if "per_minute" in msg.lower() or "PerMinute" in msg or "GenerateRequestsPerMinute" in msg:
            return "⏳ request เยอะเกินต่อนาทีอ่ะ รอแป๊บนึงแล้วลองใหม่นะ"
        if "token" in msg.lower():
            return "⏳ ส่ง token เยอะเกินไปอ่ะ ลองพิมพ์สั้นลงหน่อยได้มั้ย"
        return "❌ quota หมดอ่ะ รอแป๊บนึงแล้วลองใหม่นะ 🙏"
    if "400" in msg:
        return "❌ ข้อความนี้บอทรับไม่ได้อ่ะ ลองใหม่ด้วยข้อความอื่นนะ"
    if "403" in msg:
        return "❌ API key ไม่มีสิทธิ์ใช้งาน ลองติดต่อท่านเซนนะ"
    if "500" in msg or "503" in msg:
        return "❌ server Gemini มีปัญหาอ่ะ รอแป๊บแล้วลองใหม่นะ"
    if "invalid" in msg.lower() and "key" in msg.lower():
        return "❌ API key ไม่ถูกต้องอ่ะ ลองติดต่อท่านเซนนะ"
    return f"❌ เกิด error อ่ะ: `{msg[:200]}`"


async def auto_react(message):
    try:
        if len(message.content.strip()) < 2:
            return
        now = time.time()
        if now - react_cooldown.get(message.author.id, 0) < REACT_COOLDOWN_SEC:
            return
        text = message.content.lower()
        matched = [random.choice(emojis) for kws, emojis in EMOJI_MAP if any(kw in text for kw in kws)]
        if matched:
            await message.add_reaction(matched[0])
            react_cooldown[message.author.id] = now
            stats["total_reactions"] += 1
    except Exception as e:
        print(f"[REACT ERROR] {e}")


async def generate_image(prompt):
    encoded = prompt.replace(" ", "%20")
    return f"https://image.pollinations.ai/prompt/{encoded}?width=1024&height=1024&nologo=true"


async def process_message(message, user_input, image_data=None):
    async with message.channel.typing():
        last_error = None

        for attempt in range(len(API_KEYS) or 1):
            try:
                chat = get_chat(message.author.id)

                if image_data:
                    parts = [user_input or "อธิบายรูปนี้ให้หน่อย", image_data]
                    response = make_model().generate_content(parts)
                else:
                    response = chat.send_message(user_input)

                reply = response.text
                stats["total_requests"] += 1
                stats["total_tokens_in"] += count_tokens(user_input or "")
                stats["total_tokens_out"] += count_tokens(reply)

                await message.reply(reply[:1950] + "..." if len(reply) > 2000 else reply)
                return  # สำเร็จ → ออกเลย

            except Exception as e:
                err_msg = str(e)
                last_error = e

                # 429 และยังมี key เหลือ → switch key แล้วลองใหม่
                if "429" in err_msg and attempt < len(API_KEYS) - 1:
                    print(f"[WARN] key {attempt+1} quota hit, switching key...")
                    chat_sessions.pop(message.author.id, None)
                    await asyncio.sleep(2)
                    continue

                # error อื่น หรือ key หมดทุกอัน → หยุดเลย
                break

        # reply error แค่ครั้งเดียวหลัง loop จบ
        if last_error:
            await message.reply(parse_error(last_error))


# =======================
# AUTO RESET DAILY STATS
# =======================
async def reset_daily_stats():
    """รีเซต stats ทุกวันตอน 07:00 น. UTC+7 (= 00:00 UTC)"""
    await client.wait_until_ready()
    while not client.is_closed():
        now = now_th()
        next_reset = now.replace(hour=7, minute=0, second=0, microsecond=0)
        if now >= next_reset:
            next_reset += datetime.timedelta(days=1)

        wait_seconds = (next_reset - now).total_seconds()
        print(f"[RESET] จะรีเซต stats ในอีก {wait_seconds/3600:.1f} ชั่วโมง (ตอน {next_reset.strftime('%d/%m/%Y %H:%M')} น. UTC+7)")
        await asyncio.sleep(wait_seconds)

        stats["total_requests"] = 0
        stats["total_tokens_in"] = 0
        stats["total_tokens_out"] = 0
        stats["total_reactions"] = 0
        stats["total_images"] = 0
        stats["last_reset"] = now_th()
        print(f"[RESET] ✅ รีเซต daily stats แล้ว! ({stats['last_reset'].strftime('%d/%m/%Y %H:%M')} น.)")


# =======================
# WEB SERVER (ANTI-SLEEP)
# =======================
app = Flask('')

@app.route('/')
def home():
    uptime = now_th() - stats["start_time"]
    hours, remainder = divmod(int(uptime.total_seconds()), 3600)
    minutes, seconds = divmod(remainder, 60)

    current_th = now_th().strftime("%d/%m/%Y %H:%M:%S")
    last_reset_th = stats["last_reset"].strftime("%d/%m/%Y %H:%M")

    _now = now_th()
    next_reset = _now.replace(hour=7, minute=0, second=0, microsecond=0)
    if _now >= next_reset:
        next_reset += datetime.timedelta(days=1)
    time_to_reset = next_reset - _now
    reset_h, reset_rem = divmod(int(time_to_reset.total_seconds()), 3600)
    reset_m = reset_rem // 60
    next_reset_str = next_reset.strftime("%d/%m/%Y %H:%M")

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
        body {{ font-family: 'Inter', sans-serif; background: #0d0d14; color: #e2e8f0; min-height: 100vh; padding: 32px 20px; }}
        .container {{ max-width: 720px; margin: 0 auto; }}
        .header {{ display: flex; align-items: center; gap: 16px; margin-bottom: 32px; }}
        .avatar {{ width: 56px; height: 56px; background: linear-gradient(135deg, #6366f1, #8b5cf6); border-radius: 16px; display: flex; align-items: center; justify-content: center; font-size: 28px; }}
        .header-text h1 {{ font-size: 1.5rem; font-weight: 700; background: linear-gradient(135deg, #a78bfa, #60a5fa); -webkit-background-clip: text; -webkit-text-fill-color: transparent; }}
        .header-text p {{ color: #64748b; font-size: 0.85rem; margin-top: 2px; }}
        .status-badge {{ display: inline-flex; align-items: center; gap: 6px; background: #0f2d1f; border: 1px solid #166534; color: #4ade80; padding: 4px 12px; border-radius: 999px; font-size: 0.78rem; font-weight: 600; margin-bottom: 8px; }}
        .dot {{ width: 7px; height: 7px; background: #4ade80; border-radius: 50%; animation: pulse 2s infinite; }}
        @keyframes pulse {{ 0%, 100% {{ opacity: 1; }} 50% {{ opacity: 0.4; }} }}
        .time-row {{ display: flex; gap: 10px; flex-wrap: wrap; margin-bottom: 20px; }}
        .time-chip {{ background: #13131f; border: 1px solid #1e1e30; border-radius: 999px; padding: 4px 14px; font-size: 0.75rem; color: #94a3b8; }}
        .time-chip span {{ color: #c4b5fd; font-weight: 600; }}
        .grid {{ display: grid; grid-template-columns: 1fr 1fr; gap: 14px; margin-bottom: 14px; }}
        .card {{ background: #13131f; border: 1px solid #1e1e30; border-radius: 16px; padding: 20px; transition: border-color 0.2s; }}
        .card:hover {{ border-color: #6366f1; }}
        .card-label {{ font-size: 0.72rem; font-weight: 600; text-transform: uppercase; letter-spacing: 0.08em; color: #475569; margin-bottom: 8px; }}
        .card-value {{ font-size: 1.6rem; font-weight: 700; color: #f1f5f9; line-height: 1; }}
        .card-sub {{ font-size: 0.78rem; color: #475569; margin-top: 4px; }}
        .card-icon {{ font-size: 1.1rem; margin-bottom: 6px; }}
        .bar-wrap {{ margin-top: 12px; }}
        .bar-header {{ display: flex; justify-content: space-between; font-size: 0.75rem; color: #64748b; margin-bottom: 6px; }}
        .bar-bg {{ background: #1e1e30; border-radius: 999px; height: 8px; overflow: hidden; }}
        .bar-fill {{ height: 100%; border-radius: 999px; transition: width 0.5s ease; }}
        .model-card {{ background: linear-gradient(135deg, #1a1a2e, #16162a); border: 1px solid #312e6b; border-radius: 16px; padding: 20px; margin-bottom: 14px; display: flex; align-items: center; gap: 16px; }}
        .model-icon {{ width: 44px; height: 44px; background: linear-gradient(135deg, #4f46e5, #7c3aed); border-radius: 12px; display: flex; align-items: center; justify-content: center; font-size: 22px; flex-shrink: 0; }}
        .model-name {{ font-weight: 700; font-size: 1rem; color: #c4b5fd; }}
        .model-desc {{ font-size: 0.78rem; color: #64748b; margin-top: 2px; }}
        .model-badge {{ margin-left: auto; background: #1e1b4b; color: #818cf8; border: 1px solid #3730a3; padding: 3px 10px; border-radius: 999px; font-size: 0.72rem; font-weight: 600; white-space: nowrap; }}
        .limits-card {{ background: #13131f; border: 1px solid #1e1e30; border-radius: 16px; padding: 20px; margin-bottom: 14px; }}
        .limits-title {{ font-size: 0.72rem; font-weight: 600; text-transform: uppercase; letter-spacing: 0.08em; color: #475569; margin-bottom: 14px; }}
        .limit-row {{ display: flex; justify-content: space-between; align-items: center; padding: 10px 0; border-bottom: 1px solid #1e1e30; }}
        .limit-row:last-child {{ border-bottom: none; }}
        .limit-label {{ font-size: 0.85rem; color: #94a3b8; }}
        .limit-val {{ font-size: 0.85rem; font-weight: 600; color: #e2e8f0; }}
        .reset-badge {{ color: #fbbf24; font-weight: 600; }}
        .footer {{ text-align: center; color: #334155; font-size: 0.72rem; margin-top: 24px; }}
        @media (max-width: 480px) {{ .grid {{ grid-template-columns: 1fr; }} }}
    </style>
</head>
<body>
<div class="container">
    <div class="header">
        <div class="avatar">🤖</div>
        <div class="header-text"><h1>SAI Bot</h1><p>Discord AI Assistant</p></div>
    </div>
    <div class="status-badge"><div class="dot"></div>Online — Uptime {hours}h {minutes}m {seconds}s</div>
    <div class="time-row">
        <div class="time-chip">🕐 เวลาไทย (UTC+7): <span>{current_th} น.</span></div>
        <div class="time-chip">🔄 รีเซตล่าสุด: <span>{last_reset_th} น.</span></div>
        <div class="time-chip">⏳ รีเซตถัดไป: <span>{next_reset_str} น.</span> (อีก {reset_h}h {reset_m}m)</div>
    </div>
    <div class="model-card">
        <div class="model-icon">✨</div>
        <div><div class="model-name">{MODEL_NAME}</div><div class="model-desc">Google Gemini — Chat + Auto React + Image Gen</div></div>
        <div class="model-badge">Free Tier · {len(API_KEYS)} key(s)</div>
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
            <div class="card-icon">😄</div>
            <div class="card-label">Auto Reactions</div>
            <div class="card-value">{stats["total_reactions"]}</div>
            <div class="card-sub">keyword-based ไม่กิน quota</div>
        </div>
        <div class="card">
            <div class="card-icon">🎨</div>
            <div class="card-label">Images Generated</div>
            <div class="card-value">{stats["total_images"]}</div>
            <div class="card-sub">Pollinations AI</div>
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
        <div class="limits-title">⚡ Free Tier Rate Limits (ต่อ key)</div>
        <div class="limit-row"><span class="limit-label">Requests / นาที</span><span class="limit-val">15 RPM</span></div>
        <div class="limit-row"><span class="limit-label">Requests / วัน</span><span class="limit-val">1,500 RPD</span></div>
        <div class="limit-row"><span class="limit-label">Tokens / นาที</span><span class="limit-val">250,000 TPM</span></div>
        <div class="limit-row"><span class="limit-label">Tokens / วัน</span><span class="limit-val">1,000,000 TPD</span></div>
        <div class="limit-row"><span class="limit-label">API Keys ที่ใช้</span><span class="limit-val">{len(API_KEYS)} key(s)</span></div>
        <div class="limit-row"><span class="limit-label">Active Sessions</span><span class="limit-val">{len(chat_sessions)} users</span></div>
        <div class="limit-row"><span class="limit-label">รีเซต stats อัตโนมัติ</span><span class="limit-val reset-badge">ทุกวัน 07:00 น. (UTC+7)</span></div>
    </div>
    <div class="footer">หน้านี้รีเฟรชอัตโนมัติทุก 30 วินาที • เวลาทั้งหมดเป็น UTC+7</div>
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


@client.event
async def on_ready():
    print(f"✅ บอทออนไลน์แล้ว: {client.user} ({len(API_KEYS)} API key(s) โหลดแล้ว)")
    print(f"🕐 เวลาไทยตอนนี้: {now_th().strftime('%d/%m/%Y %H:%M:%S')} น.")
    client.loop.create_task(reset_daily_stats())


@client.event
async def on_message(message):
    if message.author.bot:
        return

    is_dm = isinstance(message.channel, discord.DMChannel)
    in_allowed = message.channel.id in ALLOWED_CHANNELS

    if not is_dm and in_allowed and message.content.strip():
        await auto_react(message)

    if not is_dm and not in_allowed:
        return

    # คำสั่ง owner
    if message.author.id == OWNER_ID:
        if message.content == "!reset":
            chat_sessions.pop(message.author.id, None)
            await message.reply("🔄 รีเซตแชทแล้ว!")
            return
        if message.content == "!ping":
            await message.reply("🏓 Pong!")
            return
        if message.content == "!stats":
            total_tokens = stats["total_tokens_in"] + stats["total_tokens_out"]
            _now = now_th()
            next_reset = _now.replace(hour=7, minute=0, second=0, microsecond=0)
            if _now >= next_reset:
                next_reset += datetime.timedelta(days=1)
            time_to_reset = next_reset - _now
            reset_h, reset_rem = divmod(int(time_to_reset.total_seconds()), 3600)
            reset_m = reset_rem // 60
            await message.reply(
                f"📊 **Stats**\n"
                f"• Req: `{stats['total_requests']}` / 1,500\n"
                f"• Tokens: `{total_tokens:,}` / 1,000,000\n"
                f"• Reactions: `{stats['total_reactions']}`\n"
                f"• Images: `{stats['total_images']}`\n"
                f"• Sessions: `{len(chat_sessions)}` users\n"
                f"• API Keys: `{len(API_KEYS)}` key(s)\n"
                f"• เวลาไทย: `{now_th().strftime('%d/%m/%Y %H:%M')} น.`\n"
                f"• รีเซตถัดไป: `{next_reset.strftime('%d/%m/%Y %H:%M')} น.` (อีก {reset_h}h {reset_m}m)"
            )
            return

    if message.content == "!reset":
        chat_sessions.pop(message.author.id, None)
        await message.reply("🔄 รีเซตแชทของคุณแล้ว!")
        return

    if message.content == "!help":
        await message.reply(
            "**✨ SAI Bot — คำสั่งที่ใช้ได้**\n\n"
            "`!gen <prompt>` — เจนรูปภาพ\n"
            "`!reset` — ล้างประวัติแชทของคุณ\n"
            "`!help` — แสดงคำสั่งนี้\n\n"
            "หรือแค่พิมพ์ข้อความ/ส่งรูปมาได้เลย!\n"
            "บอทจะ react emoji ตามอารมณ์ข้อความอัตโนมัติด้วยนะ 😄"
        )
        return

    if message.content.startswith("!gen "):
        prompt = message.content[5:].strip()
        if not prompt:
            await message.reply("ใส่ prompt ด้วยนะ เช่น `!gen cute anime girl in forest`")
            return
        async with message.channel.typing():
            img_url = await generate_image(prompt)
            stats["total_images"] += 1
            embed = discord.Embed(color=0x6366f1)
            embed.set_image(url=img_url)
            embed.set_footer(text=f"Prompt: {prompt[:100]}")
            await message.reply(embed=embed)
        return

    user_input = message.content.strip()

    image_data = None
    if message.attachments:
        for att in message.attachments:
            if any(att.filename.lower().endswith(ext) for ext in ['.png', '.jpg', '.jpeg', '.gif', '.webp']):
                img_bytes = await att.read()
                image_data = {"mime_type": "image/jpeg", "data": img_bytes}
                break

    if not user_input and not image_data:
        return

    await process_message(message, user_input, image_data)


keep_alive()
client.run(DISCORD_TOKEN)
