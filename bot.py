import discord
import os
import sys
import json
import datetime
import time
import asyncio
import aiohttp
from dotenv import load_dotenv
from flask import Flask
from threading import Thread
from collections import deque
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
DISCORD_TOKEN      = os.getenv("DISCORD_TOKEN")
OWNER_ID           = 1005357318281641994

# ===== OpenRouter (เปลี่ยนจาก Gemini) =====
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY")
OPENROUTER_URL     = "https://openrouter.ai/api/v1/chat/completions"
# Header แนะนำของ OpenRouter (ใช้สำหรับ ranking/analytics ฝั่งเขา ไม่บังคับแต่ใส่ไว้ดีกว่า)
OPENROUTER_SITE_URL  = os.getenv("OPENROUTER_SITE_URL", "https://discord.com")
OPENROUTER_APP_NAME  = os.getenv("OPENROUTER_APP_NAME", "SAI Discord Bot")

ALLOWED_CHANNELS = [
    1518970044925739160,
    1519823094816968867,
    1520009829924474973,
]

MODEL_NAME          = "meta-llama/llama-3.3-70b-instruct:free"
MAX_REPLY_TOKENS    = 800
HISTORY_LIMIT_PAIRS = 20
MAX_REPLY_LENGTH    = 1800
TZ_OFFSET           = datetime.timezone(datetime.timedelta(hours=7))

# จำกัดความยาวรวมของ history (ตัวอักษร) ก่อนส่งเข้าโมเดล กันชน context/TPM
MAX_HISTORY_CHARS  = 12000

# โมเดลนี้เป็น text-only ไม่รองรับการดูรูปภาพ (ต่างจาก Gemini เดิมที่มี vision)
SUPPORTS_VISION = False

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
- คุยได้ทุกเรื่อง ตามใจคนคุยได้เลย
- (หมายเหตุ: ตอนนี้ไซยังดูรูปภาพไม่ได้นะคะ ถ้ามีคนส่งรูปมาให้บอกน่ารักๆ ว่ายังดูรูปไม่ได้)
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

# ===== Rate Limit =====
# OpenRouter free models (":free") จำกัดอยู่ที่ประมาณ 20 req/นาที และ 50 req/วัน
# (ถ้าไม่เคยเติมเครดิตเลย) หรือ 1000 req/วันถ้าเติมเครดิตขั้นต่ำแล้ว
# ตั้งไว้ที่ 10 ต่อนาทีเพื่อตัดหน้าก่อนโดน 429 จริงจากฝั่ง OpenRouter
request_history = deque(maxlen=10)

async def check_rate_limit(message):
    now = time.time()
    while request_history and request_history[0] < now - 60:
        request_history.popleft()

    if len(request_history) >= request_history.maxlen:
        await message.reply("⏳ ไซขอพักหายใจแป๊บนะคะ! ปะป๋ารัวเร็วเกินไปแล้ววว~ (รออีกนิดนะคะ)")
        return False

    request_history.append(now)
    return True
# ======================

# ===== Instance handoff =====
INSTANCE_ID      = str(time.time())
_bot_ready_time  : float = 0.0
STARTUP_IGNORE_SEC = 5
_tasks_started     = False  # Flag ป้องกัน Task รันซ้ำซ้อนตอน Reconnect

async def _watch_instance_signal():
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

def get_reset_time_str() -> str:
    now = now_th()
    next_reset = now.replace(hour=7, minute=0, second=0, microsecond=0)
    if now >= next_reset:
        next_reset += datetime.timedelta(days=1)
    return next_reset.strftime("%d/%m/%Y %H:%M")

# ===== OpenRouter API call =====
class OpenRouterError(Exception):
    """Error จาก OpenRouter พร้อมเก็บ status code และ raw body ไว้ debug"""
    def __init__(self, status: int, body: str):
        self.status = status
        self.body = body
        super().__init__(f"OpenRouter {status}: {body}")

async def call_openrouter(messages: list, max_tokens: int = MAX_REPLY_TOKENS, model: str = MODEL_NAME) -> str:
    """
    เรียก OpenRouter chat/completions แบบ async ด้วย aiohttp
    messages: list ของ {"role": "system"|"user"|"assistant", "content": "..."}
    คืนค่าเป็นข้อความตอบกลับ (string) หรือ raise OpenRouterError ถ้า error
    """
    headers = {
        "Authorization": f"Bearer {OPENROUTER_API_KEY}",
        "Content-Type": "application/json",
        "HTTP-Referer": OPENROUTER_SITE_URL,
        "X-Title": OPENROUTER_APP_NAME,
    }
    payload = {
        "model": model,
        "messages": messages,
        "max_tokens": max_tokens,
    }
    async with aiohttp.ClientSession() as session:
        async with session.post(
            OPENROUTER_URL,
            headers=headers,
            json=payload,
            timeout=aiohttp.ClientTimeout(total=60),
        ) as resp:
            body_text = await resp.text()
            if resp.status != 200:
                raise OpenRouterError(resp.status, body_text)
            try:
                data = json.loads(body_text)
            except Exception:
                raise OpenRouterError(resp.status, f"invalid json: {body_text[:300]}")

            # OpenRouter บางครั้งคืน 200 แต่มี error object ฝังอยู่ข้างใน
            if "error" in data:
                raise OpenRouterError(200, json.dumps(data["error"], ensure_ascii=False))

            try:
                return data["choices"][0]["message"]["content"]
            except (KeyError, IndexError):
                raise OpenRouterError(resp.status, f"unexpected response shape: {body_text[:300]}")
# ============================

# ===== Error classification (สำหรับ OpenRouter) =====
# OpenRouter ไม่มี daily/per-minute แยกชัดแบบ Gemini แต่ error message ของโมเดล free
# มักมีคำว่า "rate-limited", "rate limit", หรือ retry-after มาด้วย ส่วน daily/credit
# หมดมักมีคำว่า "credits", "quota", "exceeded your" หรือ status 402 (payment required)

def is_daily_quota_error(msg: str) -> bool:
    """เครดิต/โควตาหมดแบบที่ต้องรอข้ามวัน หรือต้องเติมเครดิต"""
    lower = msg.lower()

    # ถ้ามี retry-after เป็นวินาที/นาทีสั้นๆ ชัดเจน ไม่ใช่ daily แน่นอน
    if ("retry" in lower or "please try again" in lower) and any(
        x in lower for x in ["second", "sec", "ms", " min", "minute"]
    ):
        return False

    return (
        "402" in lower
        or "insufficient credits" in lower
        or "exceeded your" in lower
        or "quota" in lower
        or "per-day" in lower
        or "per day" in lower
        or "daily" in lower
    )

def is_rate_limit_error(msg: str) -> bool:
    """rate limit ชั่วคราว (รอแป๊บแล้วลองใหม่ได้)"""
    lower = msg.lower()
    return (
        "429" in lower
        or "rate limit" in lower
        or "rate-limited" in lower
        or "too many requests" in lower
    )
# ============================

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

    def total_chars(h):
        return sum(len(m.get("content", "")) for m in h)

    while history and total_chars(history) > MAX_HISTORY_CHARS:
        del history[0]

def count_tokens(text: str) -> int:
    # ภาษาไทยกิน token เยอะกว่าอังกฤษ (~2-3 เท่า) ในระบบ tokenizer ทั่วไปรวมถึง Llama
    return int(len(text) * 0.7) if any(ord(char) > 127 for char in text) else len(text) // 4

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
        reply = await call_openrouter(
            messages=[
                {"role": "system", "content": SUMMARIZE_PROMPT},
                {"role": "user", "content": f"สรุปข้อความนี้ให้กระชับไม่เกิน 1800 ตัวอักษร:\n\n{text}"},
            ],
            max_tokens=600,
        )
        return reply.strip() or text[:MAX_REPLY_LENGTH] + "..."
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
    await update_bot_status("playing")
    try:
        history = get_history(message.author.id)

        # โมเดลนี้ดูรูปไม่ได้ (text-only) แจ้งผู้ใช้น่ารักๆ ถ้ามีแนบไฟล์รูปมา
        has_images = bool(message.attachments) and not SUPPORTS_VISION
        if has_images and not user_input:
            user_input = "(ผู้ใช้ส่งรูปภาพมาแต่ไม่มีข้อความ)"

        history.append({"role": "user", "content": user_input})
        try:
            print("[INFO] กำลัง generate...", flush=True)
            messages = [{"role": "system", "content": SYSTEM_PROMPT}] + history
            reply = await call_openrouter(messages=messages, max_tokens=MAX_REPLY_TOKENS)

            if has_images:
                reply = "อุ๊ย! ตอนนี้ไซยังดูรูปภาพไม่ได้นะคะ 🥲 แต่ไซตอบข้อความที่แนบมาให้ละนะคะ~\n\n" + reply

            history.append({"role": "assistant", "content": reply})
            trim_history(history)

            stats["total_requests"]   += 1
            stats["total_tokens_in"]  += count_tokens(user_input or "")
            stats["total_tokens_out"] += count_tokens(reply)
            reply = await summarize_if_too_long(reply)
            await message.reply(reply)
        except Exception as e:
            err_msg = str(e)
            print(f"[ERROR RAW] {err_msg}", flush=True)
            print(f"[ERROR] {err_msg[:300]}", flush=True)
            if history and history[-1]["role"] == "user":
                history.pop()

            is_daily = is_daily_quota_error(err_msg)
            is_rpm   = is_rate_limit_error(err_msg)
            print(f"[ERROR CLASSIFY] daily_quota={is_daily} rate_limit={is_rpm}", flush=True)

            if is_daily:
                reset_str = get_reset_time_str()
                await update_bot_status("resting")
                await message.reply(f"ว้ายยย! โควตา/เครดิตของไซหมดเกลี้ยงแล้วค่ะปะป๋า 💤\nลองอีกทีตอน **{reset_str} น.** หรือเช็คเครดิต OpenRouter นะคะ!")
            elif is_rpm:
                await message.reply("⏳ อูยยย ปะป๋าหรือเพื่อนๆ รัวข้อความไวเกินไปจนไซประมวลผลไม่ทันแล้วค่ะ! ขอเวลาหายใจสัก 10-60 วินาทีแล้วลองใหม่นะคะ~ 🥺")
            elif "400" in err_msg:
                await message.reply("เอ๊ะ? ข้อความนี้ไซรับไม่ได้อ่ะค่ะ ลองเปลี่ยนคำพูดดูใหม่นะคะ 🙏")
            elif "500" in err_msg or "502" in err_msg or "503" in err_msg or "unavailable" in err_msg.lower():
                await message.reply("ว้าย! ตอนนี้โมเดลฝั่ง OpenRouter คนใช้เยอะจนระบบเอ๋อค่ะ รอแป๊บนึงแล้วลองใหม่นะคะ 🛠️")
            else:
                await message.reply("อุ๊ย! เกิด error แปลกๆ นิดนึงค่ะ ลองใหม่อีกทีนะคะปะป๋า~")
    finally:
        typing_task.cancel()
        processing_users.discard(message.author.id)
        processing_messages.discard(message.id)
        if not processing_users:
            await update_bot_status("ready")

async def test_key() -> str:
    try:
        reply = await call_openrouter(
            messages=[{"role": "user", "content": "ping"}],
            max_tokens=10,
        )
        _ = reply
        return "✅ ใช้งานได้ปกติค่ะ"
    except Exception as e:
        err = str(e)
        print(f"[TESTKEY ERROR RAW] {err}", flush=True)
        if is_daily_quota_error(err):
            return f"⚠️ โควตา/เครดิตหมดแล้วค่ะ: `{err[:150]}`"
        if is_rate_limit_error(err):
            return f"⏳ rate limit ชั่วคราว (key ยังใช้ได้): `{err[:150]}`"
        if "502" in err or "503" in err or "unavailable" in err.lower():
            return "🛠️ ระบบ OpenRouter ขัดข้องชั่วคราวค่ะ แต่ตัว Key ปกติดีอยู่ค่ะ"
        return f"❌ error: `{err[:150]}`"

async def update_bot_status(status_type: str):
    status_configs = {
        "playing": (discord.ActivityType.playing,  "กำลังเล่นกับปะป๋า! | by senz"),
        "resting": (discord.ActivityType.listening, "กำลังพักผ่อน... (Quota เต็ม) | by senz"),
        "ready":   (discord.ActivityType.watching,  "พร้อมซนแล้ว! | by senz"),
    }
    atype, name = status_configs.get(status_type, status_configs["ready"])
    await client.change_presence(activity=discord.Activity(type=atype, name=name))


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
        request_history.clear()
        print("[RESET] ✅ รีเซตแล้ว!", flush=True)
        await update_bot_status("ready")

# ===== Flask status page =====
app = Flask('')

@app.route('/')
def home():
    uptime = now_th() - stats["start_time"]
    h, rem = divmod(int(uptime.total_seconds()), 3600)
    m, s   = divmod(rem, 60)
    current_th    = now_th().strftime("%d/%m/%Y %H:%M:%S")
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
        <div><div class="model-name">{MODEL_NAME}</div><div class="model-desc">OpenRouter — Chat (text-only)</div></div>
    </div>
    <div class="grid">
        <div class="card"><div class="card-icon">📨</div><div class="card-label">Requests Today</div><div class="card-value">{stats["total_requests"]}</div><div class="card-sub">นับเฉพาะ request ที่สำเร็จ</div></div>
        <div class="card"><div class="card-icon">🪙</div><div class="card-label">Tokens Today</div><div class="card-value">{total_tokens:,}</div><div class="card-sub">ประมาณจากความยาวข้อความ</div></div>
        <div class="card"><div class="card-icon">💬</div><div class="card-label">Active Sessions</div><div class="card-value">{len(user_histories)}</div><div class="card-sub">ผู้ใช้ที่มีประวัติแชทอยู่</div></div>
        <div class="card"><div class="card-icon">🔴</div><div class="card-label">Dedup (Redis)</div><div class="card-value" style="font-size:0.95rem;padding-top:4px">{redis_status}</div><div class="card-sub">กัน message ซ้ำข้าม instance</div></div>
    </div>
    <div class="limits-card">
        <div class="limits-title">✨ OpenRouter Free Model</div>
        <div class="limit-row"><span class="limit-label">Model</span><span class="limit-val">{MODEL_NAME}</span></div>
        <div class="limit-row"><span class="limit-label">Requests / นาที</span><span class="limit-val">10 (ตัดหน้า) / ~20 (OpenRouter)</span></div>
        <div class="limit-row"><span class="limit-label">Requests / วัน</span><span class="limit-val">ขึ้นกับเครดิตบัญชี OpenRouter</span></div>
        <div class="limit-row"><span class="limit-label">Vision (อ่านรูป)</span><span class="limit-val">❌ ยังไม่รองรับ</span></div>
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
    global _bot_ready_time, _tasks_started
    print(f"✅ บอทออนไลน์: {client.user}", flush=True)
    print(f"🕐 {now_th().strftime('%d/%m/%Y %H:%M:%S')} น.", flush=True)
    if _redis:
        _redis.set("sai:active_instance", INSTANCE_ID, ex=3600)
        print("[HANDOFF] ส่ง signal ให้ instance เก่าออก", flush=True)
    print(f"⏳ รอ {STARTUP_IGNORE_SEC}s...", flush=True)
    await asyncio.sleep(STARTUP_IGNORE_SEC)
    _bot_ready_time = time.time()
    print("✅ พร้อมรับ message แล้ว!", flush=True)
    await update_bot_status("ready")

    # รันลูปเบื้องหลังเฉพาะตอนเปิดบอทครั้งแรกเท่านั้น (กันทำงานซ้ำตอนเน็ตหลุด/Reconnect)
    if not _tasks_started:
        client.loop.create_task(reset_daily_stats())
        client.loop.create_task(_watch_instance_signal())
        _tasks_started = True


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

    if not await check_rate_limit(message):
        return

    await process_message(message, user_input)


keep_alive()
client.run(DISCORD_TOKEN)
