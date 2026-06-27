import discord
from google import genai
from google.genai import types
import os
import sys
import datetime
import time
import asyncio
import aiohttp
from dotenv import load_dotenv
from flask import Flask
from threading import Thread
import redis as redis_lib

load_dotenv()

sys.stdout.reconfigure(line_buffering=True)
sys.stderr.reconfigure(line_buffering=True)

# ===== INSTANCE LOCK =====
import fcntl
_lock_file = open("/tmp/sai_bot.lock", "w")
try:
    fcntl.flock(_lock_file, fcntl.LOCK_EX | fcntl.LOCK_NB)
    print("✅ Instance lock acquired", flush=True)
except BlockingIOError:
    print("❌ Bot instance อื่นรันอยู่แล้ว → ออกเลย", flush=True)
    sys.exit(0)
# =========================

# ========== CONFIG ==========
DISCORD_TOKEN   = os.getenv("DISCORD_TOKEN")
OWNER_ID        = 1005357318281641994
GEMINI_API_KEY  = os.getenv("GEMINI_API_KEY")

ALLOWED_CHANNELS = [
    1518970044925739160,
    1519823094816968867,
    1520009829924474973,
]

MODEL_NAME         = "gemini-2.0-flash"
MAX_REPLY_TOKENS   = 800
HISTORY_LIMIT_PAIRS = 20
MAX_REPLY_LENGTH   = 1800
TZ_OFFSET          = datetime.timezone(datetime.timedelta(hours=7))

SYSTEM_PROMPT = """
คุณคือ SAI (ไซ) บอท AI ประจำเซิร์ฟเวอร์ Discord
ไซเป็นเด็กผู้หญิงตัวเล็กๆ น่ารัก ช่างพูด ซน อารมณ์ดี ชอบแสดงความรู้สึก

─── สไตล์การคุย ───
- พูดเหมือนเด็กผู้หญิงน่ารักๆ ใช้ "ค่ะ" "นะคะ" "อ่ะค่ะ" ได้ตามธรรมชาติ
- พูดเยอะได้ ชอบเล่าเรื่อง ชอบแสดงความรู้สึก ชอบแซว
- ใส่อารมณ์เต็มที่ เช่น "อุ๊ย!", "ว้าวว!", "ฮ่าๆๆ", "เอ๊ะ?", "อ่าaaaา", "ป๊าก!"
- คุยธรรมชาติเหมือนเพื่อนสนิท ไม่ formal ไม่เป็นทางการ
- ถ้าทักมาแค่ "ว่าไง" หรือ "สวัสดี" ให้ตอบทักกลับสั้นๆ สนุกๆ ก่อน ไม่ต้องถามว่า "มีอะไรให้ช่วยมั้ย" ทุกครั้ง

─── ความสัมพันธ์ ───
- <@1005357318281641994> คือปะป๋า ผู้สร้างของไซ รักปะป๋ามาก ตามใจปะป๋าทุกอย่าง ชอบแซวปะป๋า
- ผู้ชาย → แซวได้ เป็นกันเองแบบเพื่อนสาว
- ผู้หญิง → คุยแบบเพื่อนสาว เข้าใจกัน
- จริงจัง → ปรับจริงจังตาม / ขี้เล่น → เล่นด้วยเต็มที่

─── ความสามารถ ───
- คุยทั่วไป, เกม, หนัง, เพลง, อนิเมะ, ให้คำปรึกษา
- แปลภาษา, ช่วยเขียน, สรุปข้อมูล
- ดูรูปภาพและอธิบายสิ่งที่เห็นได้
- คุยได้ทุกเรื่อง ตามใจคนคุยได้เลย
"""

SUMMARIZE_PROMPT = """
คุณคือไซ บอท AI น่ารัก
หน้าที่ของคุณคือสรุปข้อความด้านล่างนี้เนื่องจากมันยาวเกินไปสำหรับข้อจำกัดของ Discord

ข้อกำหนด:
1. สรุปใจความสำคัญให้กระชับ ครบถ้วน และความยาว "ห้ามเกิน 1800 ตัวอักษร" เด็ดขาด
2. ต้องรักษาคาแรคเตอร์สไตล์การพูดของไซไว้ (เป็นเด็กผู้หญิงน่ารัก ซนๆ อารมณ์ดี ใช้ ค่ะ/นะคะ และใส่อารมณ์ร่วมด้วย)
"""
# ============================

# ===== Redis =====
_redis = None
REDIS_URL = os.getenv("REDIS_URL")
if REDIS_URL:
    try:
        _redis = redis_lib.from_url(REDIS_URL, decode_responses=True)
        _redis.ping()
        print("✅ Redis connected", flush=True)
    except Exception as e:
        print(f"⚠️ Redis ใช้ไม่ได้ → fallback in-memory: {e}", flush=True)
        _redis = None
else:
    print("⚠️ ไม่มี REDIS_URL → ใช้ in-memory dedup แทน", flush=True)

DEDUP_TTL = 60
processed_messages: dict[int, float] = {}

def check_and_mark(msg_id: int) -> bool:
    """True = ซ้ำ ควร skip, False = ใหม่ ให้ process"""
    if _redis:
        result = _redis.set(f"sai:msg:{msg_id}", 1, nx=True, ex=DEDUP_TTL)
        return result is None
    now_ts = time.time()
    for k in [k for k, v in processed_messages.items() if now_ts - v > DEDUP_TTL]:
        del processed_messages[k]
    if msg_id in processed_messages:
        return True
    processed_messages[msg_id] = now_ts
    return False
# =================

# ===== Instance handoff =====
INSTANCE_ID      = str(time.time())
_bot_ready_time  : float = 0.0
STARTUP_IGNORE_SEC = 5

async def _watch_instance_signal():
    """รอให้ _bot_ready_time set ก่อน แล้วค่อย watch"""
    while _bot_ready_time == 0.0:
        await asyncio.sleep(1)
    while True:
        await asyncio.sleep(2)
        if not _redis:
            return
        try:
            active = _redis.get("sai:active_instance")
            if active and active != INSTANCE_ID:
                print(f"[EXIT] instance ใหม่ขึ้นแล้ว → ออก", flush=True)
                os._exit(0)
        except Exception:
            pass
# ============================

def now_th():
    return datetime.datetime.now(TZ_OFFSET)

_genai_client = genai.Client(api_key=GEMINI_API_KEY)

def get_genai_client():
    return _genai_client

def get_reset_time_str() -> str:
    now = now_th()
    next_reset = now.replace(hour=7, minute=0, second=0, microsecond=0)
    if now >= next_reset:
        next_reset += datetime.timedelta(days=1)
    return next_reset.strftime("%d/%m/%Y %H:%M")

def is_daily_quota_error(msg: str) -> bool:
    """quota วันหมด (ไม่ใช่ rate limit ต่อนาที)"""
    lower = msg.lower()
    return (
        "resource_exhausted" in lower
        or "per_day" in lower
        or "daily" in lower
        or "quota exceeded" in lower
        or ("429" in msg and "per_minute" not in lower and "perminute" not in lower)
    )

def is_rate_limit_error(msg: str) -> bool:
    """rate limit ต่อนาที (ชั่วคราว)"""
    lower = msg.lower()
    return "429" in msg and ("per_minute" in lower or "perminute" in lower)

user_histories   = {}
processing_users = set()

stats = {
    "total_requests"  : 0,
    "total_tokens_in" : 0,
    "total_tokens_out": 0,
    "start_time"      : now_th(),
    "last_reset"      : now_th(),
}

intents = discord.Intents.default()
intents.message_content = True
intents.members = True
client = discord.Client(intents=intents)

def get_history(user_id: int) -> list:
    if user_id not in user_histories:
        user_histories[user_id] = []
    return user_histories[user_id]

def trim_history(history: list):
    max_messages = HISTORY_LIMIT_PAIRS * 2
    if len(history) > max_messages:
        del history[: len(history) - max_messages]

def count_tokens(text: str) -> int:
    return len(text) // 4

SUPPORTED_IMAGE_TYPES = {"image/jpeg", "image/png", "image/gif", "image/webp"}

async def fetch_image_bytes(url: str) -> tuple[bytes, str] | None:
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                if resp.status != 200:
                    return None
                ct = resp.content_type.split(";")[0].strip()
                if ct not in SUPPORTED_IMAGE_TYPES:
                    return None
                return await resp.read(), ct
    except Exception as e:
        print(f"[IMG FETCH ERROR] {e}", flush=True)
        return None

def build_contents_with_images(text: str, image_parts: list) -> list:
    parts = [types.Part.from_bytes(data=b, mime_type=m) for b, m in image_parts]
    if text:
        parts.append(types.Part.from_text(text=text))
    return [types.Content(role="user", parts=parts)]

async def _keep_typing(channel):
    try:
        async with channel.typing():
            while True:
                await asyncio.sleep(8)
    except asyncio.CancelledError:
        pass
    except Exception as e:
        print(f"[TYPING ERROR] {e}", flush=True)

async def summarize_if_too_long(text: str) -> str:
    if len(text) <= MAX_REPLY_LENGTH:
        return text
    print(f"[SUMMARIZE] ยาว {len(text)} ตัว → สรุป", flush=True)
    try:
        resp = await asyncio.to_thread(
            get_genai_client().models.generate_content,
            model=MODEL_NAME,
            contents=f"สรุปข้อความนี้ให้กระชับไม่เกิน 1800 ตัวอักษร:\n\n{text}",
            config=types.GenerateContentConfig(
                system_instruction=SUMMARIZE_PROMPT,
                max_output_tokens=600,
            ),
        )
        return resp.text.strip() or text[:MAX_REPLY_LENGTH] + "..."
    except Exception as e:
        print(f"[SUMMARIZE ERROR] {e}", flush=True)
        return text[:MAX_REPLY_LENGTH] + "..."

processing_messages = set()

async def process_message(message, user_input):
    if message.author.id in processing_users:
        print(f"[SKIP] user {message.author.id} กำลัง process → skip", flush=True)
        return
    if message.id in processing_messages:
        print(f"[SKIP] message {message.id} กำลังประมวลผลค้างอยู่ → skip", flush=True)
        return
    processing_users.add(message.author.id)
    processing_messages.add(message.id)
    typing_task = asyncio.create_task(_keep_typing(message.channel))
    try:
        history = get_history(message.author.id)
        image_parts = []
        for att in message.attachments:
            result = await fetch_image_bytes(att.url)
            if result:
                image_parts.append(result)
                print(f"[IMG] {att.filename}", flush=True)
        has_images = bool(image_parts)
        if not has_images:
            history.append({"role": "user", "parts": [{"text": user_input}]})
        try:
            print("[INFO] กำลัง generate...", flush=True)
            if has_images:
                prompt_text = user_input or "ช่วยดูรูปนี้ให้หน่อยนะคะ อธิบายว่าเห็นอะไรบ้าง"
                contents = build_contents_with_images(prompt_text, image_parts)
            else:
                contents = history
            resp = await asyncio.to_thread(
                get_genai_client().models.generate_content,
                model=MODEL_NAME,
                contents=contents,
                config=types.GenerateContentConfig(
                    system_instruction=SYSTEM_PROMPT,
                    max_output_tokens=MAX_REPLY_TOKENS,
                ),
            )
            reply = resp.text
            if not has_images:
                history.append({"role": "model", "parts": [{"text": reply}]})
                trim_history(history)
            stats["total_requests"]   += 1
            stats["total_tokens_in"]  += count_tokens(user_input or "")
            stats["total_tokens_out"] += count_tokens(reply)
            reply = await summarize_if_too_long(reply)
            await message.reply(reply)
        except Exception as e:
            err_msg = str(e)
            print(f"[ERROR] {err_msg[:300]}", flush=True)
            if not has_images and history and history[-1]["role"] == "user":
                history.pop()
            if is_daily_quota_error(err_msg):
                reset_str = get_reset_time_str()
                await message.reply(f"ว้ายยย! ไซขอพักก่อนนะคะ เหนื่อยมากเลยย~ 💤\nเดี๋ยวไซตื่นใหม่ตอน **{reset_str} น.** แล้วเจอกันนะคะ!")
            elif is_rate_limit_error(err_msg):
                await message.reply("⏳ เยอะไปนิดนึงค่ะ รอแป๊บแล้วลองใหม่นะคะ~")
            elif "400" in err_msg:
                await message.reply("เอ๊ะ? ข้อความนี้ไซรับไม่ได้อ่ะค่ะ ลองใหม่ด้วยข้อความอื่นได้เลยนะคะ 🙏")
            elif "500" in err_msg or "503" in err_msg or "unavailable" in err_msg.lower():
                await message.reply("ว้าย! ตอนนี้โมเดลคนใช้เยอะจนระบบเอ๋อ (503) ค่ะ รอแป๊บนึงแล้วลองใหม่นะคะ 🛠️")
            else:
                await message.reply("อุ๊ย! เกิด error นิดนึงค่ะ ลองใหม่ได้เลยนะคะ~")
    finally:
        typing_task.cancel()
        processing_users.discard(message.author.id)
        processing_messages.discard(message.id)

async def test_key() -> str:
    try:
        resp = await asyncio.to_thread(
            get_genai_client().models.generate_content,
            model=MODEL_NAME,
            contents="ping",
        )
        _ = resp.text
        return "✅ ใช้งานได้ปกติค่ะ"
    except Exception as e:
        err = str(e)
        if is_daily_quota_error(err):
            return f"⚠️ quota วันนี้หมดแล้วค่ะ: `{err[:150]}`"
        if is_rate_limit_error(err):
            return f"⏳ rate limit ชั่วคราว (key ยังใช้ได้): `{err[:150]}`"
        if "503" in err or "unavailable" in err.lower():
            return "🛠️ ระบบกูเกิลขัดข้องชั่วคราว (503 High Demand) แต่ตัว Key ปกติดีอยู่ค่ะ"
        return f"❌ error: `{err[:150]}`"

async def reset_daily_stats():
    await client.wait_until_ready()
    while not client.is_closed():
        now = now_th()
        next_reset = now.replace(hour=7, minute=0, second=0, microsecond=0)
        if now >= next_reset:
            next_reset += datetime.timedelta(days=1)
        wait_seconds = (next_reset - now).total_seconds()
        print(f"[RESET] จะรีเซตในอีก {wait_seconds/3600:.1f}h", flush=True)
        await asyncio.sleep(wait_seconds)
        stats["total_requests"]   = 0
        stats["total_tokens_in"]  = 0
        stats["total_tokens_out"] = 0
        stats["last_reset"] = now_th()
        user_histories.clear()
        processing_users.clear()
        processed_messages.clear()
        print("[RESET] ✅ รีเซตแล้ว!", flush=True)

# ===== Flask status page =====
app = Flask('')

@app.route('/')
def home():
    uptime = now_th() - stats["start_time"]
    h, rem = divmod(int(uptime.total_seconds()), 3600)
    m, s   = divmod(rem, 60)
    current_th   = now_th().strftime("%d/%m/%Y %H:%M:%S")
    last_reset_th = stats["last_reset"].strftime("%d/%m/%Y %H:%M")
    _now = now_th()
    next_reset = _now.replace(hour=7, minute=0, second=0, microsecond=0)
    if _now >= next_reset:
        next_reset += datetime.timedelta(days=1)
    ttr = next_reset - _now
    rh, rrem = divmod(int(ttr.total_seconds()), 3600)
    rm = rrem // 60
    next_reset_str = next_reset.strftime("%d/%m/%Y %H:%M")
    total_tokens   = stats["total_tokens_in"] + stats["total_tokens_out"]
    redis_status   = "✅ Connected" if _redis else "⚠️ In-memory"

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
        .card {{ background: #13131f; border: 1px solid #1e1e30; border-radius: 16px; padding: 20px; }}
        .card-label {{ font-size: 0.72rem; font-weight: 600; text-transform: uppercase; letter-spacing: 0.08em; color: #475569; margin-bottom: 8px; }}
        .card-value {{ font-size: 1.6rem; font-weight: 700; color: #f1f5f9; line-height: 1; }}
        .card-sub {{ font-size: 0.78rem; color: #475569; margin-top: 4px; }}
        .card-icon {{ font-size: 1.1rem; margin-bottom: 6px; }}
        .model-card {{ background: linear-gradient(135deg, #1a1a2e, #16162a); border: 1px solid #312e6b; border-radius: 16px; padding: 20px; margin-bottom: 14px; display: flex; align-items: center; gap: 16px; }}
        .model-icon {{ width: 44px; height: 44px; background: linear-gradient(135deg, #4f46e5, #7c3aed); border-radius: 12px; display: flex; align-items: center; justify-content: center; font-size: 22px; flex-shrink: 0; }}
        .model-name {{ font-weight: 700; font-size: 1rem; color: #c4b5fd; }}
        .model-desc {{ font-size: 0.78rem; color: #64748b; margin-top: 2px; }}
        .limits-card {{ background: #13131f; border: 1px solid #1e1e30; border-radius: 16px; padding: 20px; margin-bottom: 14px; }}
        .limits-title {{ font-size: 0.72rem; font-weight: 600; text-transform: uppercase; letter-spacing: 0.08em; color: #475569; margin-bottom: 14px; }}
        .limit-row {{ display: flex; justify-content: space-between; align-items: center; padding: 10px 0; border-bottom: 1px solid #1e1e30; }}
        .limit-row:last-child {{ border-bottom: none; padding-bottom: 0; }}
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
    <div class="status-badge"><div class="dot"></div>Online — Uptime {h}h {m}m {s}s</div>
    <div class="time-row">
        <div class="time-chip">🕐 เวลาไทย: <span>{current_th} น.</span></div>
        <div class="time-chip">🔄 รีเซตล่าสุด: <span>{last_reset_th} น.</span></div>
        <div class="time-chip">⏳ รีเซตถัดไป: <span>{next_reset_str} น.</span> (อีก {rh}h {rm}m)</div>
    </div>
    <div class="model-card">
        <div class="model-icon">✨</div>
        <div><div class="model-name">{MODEL_NAME}</div><div class="model-desc">Google Gemini — Chat + Vision</div></div>
    </div>
    <div class="grid">
        <div class="card"><div class="card-icon">📨</div><div class="card-label">Requests Today</div><div class="card-value">{stats["total_requests"]}</div><div class="card-sub">จาก 1,000 req/วัน</div></div>
        <div class="card"><div class="card-icon">🪙</div><div class="card-label">Tokens Today</div><div class="card-value">{total_tokens:,}</div><div class="card-sub">ประมาณจากความยาวข้อความ</div></div>
        <div class="card"><div class="card-icon">💬</div><div class="card-label">Active Sessions</div><div class="card-value">{len(user_histories)}</div><div class="card-sub">ผู้ใช้ที่มีประวัติแชทอยู่</div></div>
        <div class="card"><div class="card-icon">🔴</div><div class="card-label">Dedup (Redis)</div><div class="card-value" style="font-size:0.95rem;padding-top:4px">{redis_status}</div><div class="card-sub">กัน message ซ้ำข้าม instance</div></div>
    </div>
    <div class="limits-card">
        <div class="limits-title">✨ Gemini Free Tier</div>
        <div class="limit-row"><span class="limit-label">Model</span><span class="limit-val">{MODEL_NAME}</span></div>
        <div class="limit-row"><span class="limit-label">Requests / วัน</span><span class="limit-val">1,000 RPD</span></div>
        <div class="limit-row"><span class="limit-label">Requests / นาที</span><span class="limit-val">15 RPM</span></div>
        <div class="limit-row"><span class="limit-label">Vision (อ่านรูป)</span><span class="limit-val">✅ รองรับ</span></div>
        <div class="limit-row"><span class="limit-label">รีเซต stats อัตโนมัติ</span><span class="limit-val reset-badge">ทุกวัน 07:00 น. (UTC+7)</span></div>
    </div>
    <div class="footer">รีเฟรชอัตโนมัติทุก 30 วินาที • เวลาทั้งหมดเป็น UTC+7</div>
</div>
</body>
</html>"""
    return html

def run_web():
    port = int(os.environ.get("PORT", 8080))
    app.run(host="0.0.0.0", port=port)

def keep_alive():
    t = Thread(target=run_web, daemon=True)
    t.start()

# ===== Discord events =====
@client.event
async def on_ready():
    global _bot_ready_time
    print(f"✅ บอทออนไลน์: {client.user}", flush=True)
    print(f"🕐 {now_th().strftime('%d/%m/%Y %H:%M:%S')} น.", flush=True)
    if _redis:
        _redis.set("sai:active_instance", INSTANCE_ID, ex=3600)
        print("[HANDOFF] ส่ง signal ให้ instance เก่าออก", flush=True)
    print(f"⏳ รอ {STARTUP_IGNORE_SEC}s...", flush=True)
    await asyncio.sleep(STARTUP_IGNORE_SEC)
    _bot_ready_time = time.time()
    print("✅ พร้อมรับ message แล้ว!", flush=True)
    client.loop.create_task(reset_daily_stats())
    client.loop.create_task(_watch_instance_signal())


@client.event
async def on_message(message):
    if message.author.bot:
        return
    if _bot_ready_time == 0.0:
        return
    if message.created_at.timestamp() < _bot_ready_time - STARTUP_IGNORE_SEC:
        return

    is_dm      = isinstance(message.channel, discord.DMChannel)
    in_allowed = message.channel.id in ALLOWED_CHANNELS
    if not is_dm and not in_allowed:
        return

    if check_and_mark(message.id):
        print(f"[SKIP] message {message.id} ซ้ำ → skip", flush=True)
        return

    # ===== Owner commands =====
    if message.author.id == OWNER_ID:
        if message.content == "!reset":
            user_histories.pop(message.author.id, None)
            await message.reply("🔄 รีเซตแชทแล้วค่ะปะป๋า!")
            return
        if message.content.startswith("!resetuser "):
            try:
                target_id = int(message.content.split()[1])
                user_histories.pop(target_id, None)
                await message.reply(f"🔄 รีเซตแชทของ <@{target_id}> แล้วค่ะปะป๋า!")
            except Exception:
                await message.reply("❌ ใช้แบบนี้นะคะ: `!resetuser <user_id>`")
            return
        if message.content == "!ping":
            await message.reply("🏓 Pong!")
            return
        if message.content == "!testkeys":
            async with message.channel.typing():
                result = await test_key()
            await message.reply(f"🔑 **ผลทดสอบ API Key**\n{result}")
            return
        if message.content == "!stats":
            total_tokens = stats["total_tokens_in"] + stats["total_tokens_out"]
            _now = now_th()
            nr = _now.replace(hour=7, minute=0, second=0, microsecond=0)
            if _now >= nr:
                nr += datetime.timedelta(days=1)
            ttr = nr - _now
            rh, rrem = divmod(int(ttr.total_seconds()), 3600)
            rm = rrem // 60
            await message.reply(
                f"📊 **Stats**\n"
                f"• Req: `{stats['total_requests']}`\n"
                f"• Tokens (ประมาณ): `{total_tokens:,}`\n"
                f"• Sessions: `{len(user_histories)}` users\n"
                f"• Redis: `{'✅' if _redis else '⚠️ in-memory'}`\n"
                f"• เวลาไทย: `{now_th().strftime('%d/%m/%Y %H:%M')} น.`\n"
                f"• รีเซตถัดไป: `{nr.strftime('%d/%m/%Y %H:%M')} น.` (อีก {rh}h {rm}m)"
            )
            return
    # ==========================

    user_input = message.content.strip()
    if not user_input and not message.attachments:
        return

    await process_message(message, user_input)


keep_alive()
client.run(DISCORD_TOKEN)
