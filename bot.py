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
import redis

load_dotenv()

sys.stdout.reconfigure(line_buffering=True)
sys.stderr.reconfigure(line_buffering=True)

# ===== INSTANCE LOCK — กันรันสองตัวพร้อมกัน =====
import fcntl
_lock_file = open("/tmp/sai_bot.lock", "w")
try:
    fcntl.flock(_lock_file, fcntl.LOCK_EX | fcntl.LOCK_NB)
    print("✅ Instance lock acquired", flush=True)
except BlockingIOError:
    print("❌ Bot instance อื่นรันอยู่แล้ว → ออกเลย", flush=True)
    sys.exit(0)
# ==================================================

# ========== CONFIG ==========
DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")
OWNER_ID = 1005357318281641994

API_KEYS = [k for k in [
    os.getenv("GEMINI_API_KEY"),
    os.getenv("GEMINI_API_KEY_2"),
    os.getenv("GEMINI_API_KEY_3"),
] if k]

ALLOWED_CHANNELS = [
    1518970044925739160,
    1519823094816968867,
    1520009829924474973,
]

MODEL_NAME = "gemini-2.5-flash-lite"
MAX_REPLY_TOKENS = 800
HISTORY_LIMIT_PAIRS = 20
MAX_REPLY_LENGTH = 1800

TZ_OFFSET = datetime.timezone(datetime.timedelta(hours=7))

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

# ===== Redis dedup =====
_redis = None
REDIS_URL = os.getenv("REDIS_URL")
if REDIS_URL:
    try:
        _redis = redis.from_url(REDIS_URL, decode_responses=True)
        _redis.ping()
        print("✅ Redis connected", flush=True)
    except Exception as e:
        print(f"⚠️ Redis ใช้ไม่ได้ → fallback in-memory: {e}", flush=True)
        _redis = None
else:
    print("⚠️ ไม่มี REDIS_URL → ใช้ in-memory dedup แทน", flush=True)

DEDUP_TTL = 30
processed_messages: dict[int, float] = {}  # fallback ถ้าไม่มี Redis

def check_and_mark(msg_id: int) -> bool:
    """Return True ถ้าซ้ำ (ควร skip), False ถ้าใหม่"""
    if _redis:
        key = f"sai:msg:{msg_id}"
        result = _redis.set(key, 1, nx=True, ex=DEDUP_TTL)
        return result is None  # None = key มีอยู่แล้ว = ซ้ำ
    else:
        now_ts = time.time()
        expired = [k for k, v in processed_messages.items() if now_ts - v > DEDUP_TTL]
        for k in expired:
            del processed_messages[k]
        if msg_id in processed_messages:
            return True
        processed_messages[msg_id] = now_ts
        return False
# =======================

# ===== กัน message ซ้ำระหว่าง deploy =====
_bot_ready_time: float = 0.0
STARTUP_IGNORE_SEC = 30
# ==========================================

def now_th():
    return datetime.datetime.now(TZ_OFFSET)


def get_client(key: str) -> genai.Client:
    return genai.Client(api_key=key)


user_histories = {}
exhausted_keys = set()
invalid_keys = set()
processing_users = set()

stats = {
    "total_requests": 0,
    "total_tokens_in": 0,
    "total_tokens_out": 0,
    "start_time": now_th(),
    "last_reset": now_th(),
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


def count_tokens(text):
    try:
        return len(text) // 4
    except:
        return 0


def is_daily_quota_error(msg: str) -> bool:
    msg_lower = msg.lower()
    return any(x in msg_lower for x in [
        "per_day", "perday", "daily", "quota exceeded",
        "generaterequestsperdayperproject",
        "resource_exhausted",
    ]) or (
        "429" in msg
        and "per_minute" not in msg_lower
        and "perminute" not in msg_lower
    )


def is_zero_quota_error(msg: str) -> bool:
    return "limit: 0" in msg or "limit:0" in msg.replace(" ", "")


def is_invalid_key_error(msg: str) -> bool:
    msg_lower = msg.lower()
    return (
        "api_key_invalid" in msg_lower
        or "api key not valid" in msg_lower
        or "unauthenticated" in msg_lower
        or ("invalid" in msg_lower and "key" in msg_lower)
        or "401" in msg
        or "403" in msg
        or "permission_denied" in msg_lower
    )


def get_active_key_index():
    for i in range(len(API_KEYS)):
        if i not in exhausted_keys and i not in invalid_keys:
            return i
    return None


def parse_error(e: Exception) -> str:
    msg = str(e)
    if is_invalid_key_error(msg):
        return "อุ๊ย! มีปัญหานิดนึงค่ะ ขอเวลาจัดการแป๊บนึงนะคะ 🔧"
    if "429" in msg:
        if is_zero_quota_error(msg):
            return "อุ๊ย! มีปัญหานิดนึงค่ะ ขอเวลาจัดการแป๊บนึงนะคะ 🔧"
        if is_daily_quota_error(msg):
            return "อุ๊ย! มีปัญหานิดนึงค่ะ ขอเวลาจัดการแป๊บนึงนะคะ 🔧"
        return "⏳ เยอะไปนิดนึงค่ะ รอแป๊บแล้วลองใหม่นะคะ~"
    if "400" in msg:
        return "เอ๊ะ? ข้อความนี้ไซรับไม่ได้อ่ะค่ะ ลองใหม่ด้วยข้อความอื่นได้เลยนะคะ 🙏"
    if "500" in msg or "503" in msg:
        return "ว้าย! server มีปัญหานิดหน่อยค่ะ รอแป๊บแล้วลองใหม่นะคะ 🛠️"
    return "อุ๊ย! เกิด error นิดนึงค่ะ ลองใหม่ได้เลยนะคะ~"


SUPPORTED_IMAGE_TYPES = {"image/jpeg", "image/png", "image/gif", "image/webp"}

async def fetch_image_bytes(url: str) -> tuple[bytes, str] | None:
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                if resp.status != 200:
                    return None
                content_type = resp.content_type.split(";")[0].strip()
                if content_type not in SUPPORTED_IMAGE_TYPES:
                    return None
                data = await resp.read()
                return data, content_type
    except Exception as e:
        print(f"[IMG FETCH ERROR] {e}", flush=True)
        return None


def build_contents_with_images(text: str, image_parts: list) -> list:
    parts = []
    for img_bytes, mime_type in image_parts:
        parts.append(types.Part.from_bytes(data=img_bytes, mime_type=mime_type))
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


async def summarize_if_too_long(text: str, key_index: int) -> str:
    if len(text) <= MAX_REPLY_LENGTH:
        return text
    print(f"[SUMMARIZE] ข้อความยาว {len(text)} ตัว → สรุป", flush=True)
    try:
        client_obj = get_client(API_KEYS[key_index])
        response = await asyncio.to_thread(
            client_obj.models.generate_content,
            model=MODEL_NAME,
            contents=f"สรุปข้อความนี้ให้กระชับไม่เกิน 1800 ตัวอักษร:\n\n{text}",
            config=types.GenerateContentConfig(
                system_instruction=SUMMARIZE_PROMPT,
                max_output_tokens=600,
            ),
        )
        summarized = response.text.strip()
        return summarized if summarized else text[:MAX_REPLY_LENGTH] + "..."
    except Exception as e:
        print(f"[SUMMARIZE ERROR] {e}", flush=True)
        return text[:MAX_REPLY_LENGTH] + "..."


async def process_message(message, user_input):
    if message.author.id in processing_users:
        print(f"[SKIP] user {message.author.id} กำลัง process อยู่ → skip", flush=True)
        return
    processing_users.add(message.author.id)

    typing_task = asyncio.create_task(_keep_typing(message.channel))

    try:
        last_error = None
        history = get_history(message.author.id)

        image_parts = []
        for attachment in message.attachments:
            result = await fetch_image_bytes(attachment.url)
            if result:
                image_parts.append(result)
                print(f"[IMG] โหลดรูป {attachment.filename} ({attachment.content_type})", flush=True)

        has_images = len(image_parts) > 0

        if not has_images:
            history.append({"role": "user", "parts": [{"text": user_input}]})

        for key_index in range(len(API_KEYS)):
            if key_index in exhausted_keys or key_index in invalid_keys:
                continue

            try:
                key = API_KEYS[key_index]
                print(f"[INFO] ลองใช้ key {key_index + 1}/{len(API_KEYS)} ({key[:8]}...)", flush=True)

                client_obj = get_client(key)

                if has_images:
                    prompt_text = user_input if user_input else "ช่วยดูรูปนี้ให้หน่อยนะคะ อธิบายว่าเห็นอะไรบ้าง"
                    contents = build_contents_with_images(prompt_text, image_parts)
                    response = await asyncio.to_thread(
                        client_obj.models.generate_content,
                        model=MODEL_NAME,
                        contents=contents,
                        config=types.GenerateContentConfig(
                            system_instruction=SYSTEM_PROMPT,
                            max_output_tokens=MAX_REPLY_TOKENS,
                        ),
                    )
                else:
                    response = await asyncio.to_thread(
                        client_obj.models.generate_content,
                        model=MODEL_NAME,
                        contents=history,
                        config=types.GenerateContentConfig(
                            system_instruction=SYSTEM_PROMPT,
                            max_output_tokens=MAX_REPLY_TOKENS,
                        ),
                    )

                reply = response.text

                if not has_images:
                    history.append({"role": "model", "parts": [{"text": reply}]})
                    trim_history(history)

                stats["total_requests"] += 1
                stats["total_tokens_in"] += count_tokens(user_input or "")
                stats["total_tokens_out"] += count_tokens(reply)

                reply = await summarize_if_too_long(reply, key_index)
                await message.reply(reply)
                return

            except Exception as e:
                last_error = e
                err_msg = str(e)
                print(f"[ERROR] key {key_index + 1}: {err_msg[:500]}", flush=True)

                if is_invalid_key_error(err_msg):
                    invalid_keys.add(key_index)
                    remaining = len(API_KEYS) - len(exhausted_keys) - len(invalid_keys)
                    print(f"[WARN] key {key_index + 1} invalid → ตัดออก (เหลือ {remaining} key(s))", flush=True)
                    if remaining > 0:
                        await message.channel.send("อุ๊ย! เกิดปัญหานิดนึงค่ะ ไซขอสลับโหมดแป๊บนึงนะคะ~ 🔄", delete_after=5)
                    continue

                if "429" in err_msg:
                    if is_zero_quota_error(err_msg):
                        invalid_keys.add(key_index)
                        print(f"[WARN] key {key_index + 1} limit:0 → ตัดออก", flush=True)
                        continue
                    if is_daily_quota_error(err_msg):
                        exhausted_keys.add(key_index)
                        remaining = len(API_KEYS) - len(exhausted_keys) - len(invalid_keys)
                        print(f"[WARN] key {key_index + 1} daily quota หมด → blacklist (เหลือ {remaining} key(s))", flush=True)
                        if remaining > 0:
                            await message.channel.send("แป๊บนึงนะคะ ไซกำลังเปลี่ยนไปใช้ตัวสำรองอยู่ค่ะ~ ✨", delete_after=5)
                        continue
                    else:
                        print(f"[WARN] key {key_index + 1} rate limit ต่อนาที → รอ 3s", flush=True)
                        await asyncio.sleep(3)
                        continue

                if "500" in err_msg or "503" in err_msg:
                    retry_success = False
                    for attempt in range(1, 4):
                        print(f"[RETRY] key {key_index + 1} server error → retry {attempt}/3 รอ 5s", flush=True)
                        await asyncio.sleep(5)
                        try:
                            if has_images:
                                retry_resp = await asyncio.to_thread(
                                    client_obj.models.generate_content,
                                    model=MODEL_NAME,
                                    contents=contents,
                                    config=types.GenerateContentConfig(
                                        system_instruction=SYSTEM_PROMPT,
                                        max_output_tokens=MAX_REPLY_TOKENS,
                                    ),
                                )
                            else:
                                retry_resp = await asyncio.to_thread(
                                    client_obj.models.generate_content,
                                    model=MODEL_NAME,
                                    contents=history,
                                    config=types.GenerateContentConfig(
                                        system_instruction=SYSTEM_PROMPT,
                                        max_output_tokens=MAX_REPLY_TOKENS,
                                    ),
                                )
                            reply = retry_resp.text
                            if not has_images:
                                history.append({"role": "model", "parts": [{"text": reply}]})
                                trim_history(history)
                            stats["total_requests"] += 1
                            stats["total_tokens_in"] += count_tokens(user_input or "")
                            stats["total_tokens_out"] += count_tokens(reply)
                            reply = await summarize_if_too_long(reply, key_index)
                            await message.reply(reply)
                            retry_success = True
                            break
                        except Exception as retry_e:
                            print(f"[RETRY] attempt {attempt} ล้มเหลว: {str(retry_e)[:200]}", flush=True)
                            last_error = retry_e
                    if retry_success:
                        return
                    continue

                break

        if not has_images and history and history[-1]["role"] == "user":
            history.pop()

        if last_error:
            await message.reply(parse_error(last_error))
        elif get_active_key_index() is None:
            await message.reply("ว้ายยย! ไซเหนื่อยมากแล้วค่ะ ขอไปพักก่อนนะคะ เดี๋ยวเจอกันใหม่น้าา~ 💤")
    finally:
        typing_task.cancel()
        processing_users.discard(message.author.id)


async def test_all_keys() -> str:
    if not API_KEYS:
        return "⚠️ ไม่มี API key ตั้งไว้ใน env เลยอ่ะ"

    lines = []
    for i, key in enumerate(API_KEYS):
        label = f"Key {i + 1} ({key[:8]}...)"
        try:
            client_obj = get_client(key)
            response = await asyncio.to_thread(
                client_obj.models.generate_content,
                model=MODEL_NAME,
                contents="ping",
            )
            _ = response.text
            status = "✅ ใช้งานได้"
            invalid_keys.discard(i)
            if i in exhausted_keys:
                status += " (แต่ก่อนหน้านี้โดน mark ว่า quota หมด)"
        except Exception as e:
            err = str(e)
            if is_invalid_key_error(err):
                status = f"❌ ใช้ไม่ได้ (invalid): `{err[:150]}`"
                invalid_keys.add(i)
            elif "429" in err and is_zero_quota_error(err):
                status = f"⚠️ limit:0 — quota เป็น 0: `{err[:150]}`"
                invalid_keys.add(i)
            elif "429" in err and is_daily_quota_error(err):
                status = f"⚠️ quota วันนี้หมด: `{err[:150]}`"
            elif "429" in err:
                status = f"⏳ rate limit ชั่วคราว (key ใช้ได้): `{err[:150]}`"
            else:
                status = f"❌ error อื่น: `{err[:150]}`"
        lines.append(f"**{label}** — {status}")

    return "\n".join(lines)


async def reset_daily_stats():
    await client.wait_until_ready()
    while not client.is_closed():
        now = now_th()
        next_reset = now.replace(hour=7, minute=0, second=0, microsecond=0)
        if now >= next_reset:
            next_reset += datetime.timedelta(days=1)

        wait_seconds = (next_reset - now).total_seconds()
        print(f"[RESET] จะรีเซตในอีก {wait_seconds/3600:.1f}h (ตอน {next_reset.strftime('%d/%m/%Y %H:%M')} น.)", flush=True)
        await asyncio.sleep(wait_seconds)

        stats["total_requests"] = 0
        stats["total_tokens_in"] = 0
        stats["total_tokens_out"] = 0
        stats["last_reset"] = now_th()
        user_histories.clear()
        exhausted_keys.clear()
        processing_users.clear()
        processed_messages.clear()
        print(f"[RESET] ✅ รีเซตแล้ว! ({stats['last_reset'].strftime('%d/%m/%Y %H:%M')} น.)", flush=True)


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
    active_keys = len(API_KEYS) - len(exhausted_keys) - len(invalid_keys)
    redis_status = "✅ Connected" if _redis else "⚠️ In-memory (ไม่มี Redis)"

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
        <div><div class="model-name">{MODEL_NAME}</div><div class="model-desc">Google Gemini — Chat + Vision</div></div>
        <div class="model-badge">Free Tier · {len(API_KEYS)} key(s) · {active_keys} active</div>
    </div>
    <div class="grid">
        <div class="card">
            <div class="card-icon">📨</div>
            <div class="card-label">Requests Today</div>
            <div class="card-value">{stats["total_requests"]}</div>
            <div class="card-sub">จาก 1,000 req/วัน (ต่อ key)</div>
        </div>
        <div class="card">
            <div class="card-icon">🪙</div>
            <div class="card-label">Tokens Today (ประมาณ)</div>
            <div class="card-value">{total_tokens:,}</div>
            <div class="card-sub">คำนวณคร่าวๆจากความยาวข้อความ</div>
        </div>
        <div class="card">
            <div class="card-icon">💬</div>
            <div class="card-label">Active Sessions</div>
            <div class="card-value">{len(user_histories)}</div>
            <div class="card-sub">ผู้ใช้ที่มีประวัติแชทอยู่</div>
        </div>
        <div class="card">
            <div class="card-icon">🔴</div>
            <div class="card-label">Dedup (Redis)</div>
            <div class="card-value" style="font-size:0.95rem;padding-top:4px">{redis_status}</div>
            <div class="card-sub">กัน message ซ้ำข้าม instance</div>
        </div>
    </div>
    <div class="limits-card">
        <div class="limits-title">✨ Gemini Free Tier (ต่อ key)</div>
        <div class="limit-row"><span class="limit-label">Model</span><span class="limit-val">{MODEL_NAME}</span></div>
        <div class="limit-row"><span class="limit-label">Requests / วัน</span><span class="limit-val">1,000 RPD</span></div>
        <div class="limit-row"><span class="limit-label">Requests / นาที</span><span class="limit-val">15 RPM</span></div>
        <div class="limit-row"><span class="limit-label">Vision (อ่านรูป)</span><span class="limit-val">✅ รองรับ</span></div>
        <div class="limit-row"><span class="limit-label">API Keys ที่ใช้</span><span class="limit-val">{len(API_KEYS)} key(s)</span></div>
        <div class="limit-row"><span class="limit-label">Keys ที่ยัง active</span><span class="limit-val">{active_keys} key(s)</span></div>
        <div class="limit-row"><span class="limit-label">Keys quota หมด</span><span class="limit-val">{len(exhausted_keys)} key(s)</span></div>
        <div class="limit-row"><span class="limit-label">Keys invalid</span><span class="limit-val">{len(invalid_keys)} key(s)</span></div>
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
    global _bot_ready_time
    print(f"✅ บอทออนไลน์แล้ว: {client.user} ({len(API_KEYS)} API key(s) โหลดแล้ว)", flush=True)
    print(f"🕐 เวลาไทยตอนนี้: {now_th().strftime('%d/%m/%Y %H:%M:%S')} น.", flush=True)
    print(f"⏳ รอ {STARTUP_IGNORE_SEC}s ให้ instance เก่า disconnect...", flush=True)
    await asyncio.sleep(STARTUP_IGNORE_SEC)
    _bot_ready_time = time.time()
    print("✅ พร้อมรับ message แล้ว!", flush=True)
    client.loop.create_task(reset_daily_stats())


@client.event
async def on_message(message):
    if message.author.bot:
        return

    if _bot_ready_time == 0.0:
        return

    msg_ts = message.created_at.timestamp()
    if msg_ts < _bot_ready_time - STARTUP_IGNORE_SEC:
        print(f"[SKIP] message เก่าก่อน startup → skip", flush=True)
        return

    is_dm = isinstance(message.channel, discord.DMChannel)
    in_allowed = message.channel.id in ALLOWED_CHANNELS

    if not is_dm and not in_allowed:
        return

    # ===== dedup (Redis หรือ in-memory) =====
    if check_and_mark(message.id):
        print(f"[SKIP] message {message.id} ซ้ำ → skip", flush=True)
        return
    # =========================================

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
            except:
                await message.reply("❌ ใช้แบบนี้นะคะ: `!resetuser <user_id>`")
            return
        if message.content == "!ping":
            await message.reply("🏓 Pong!")
            return
        if message.content == "!testkeys":
            async with message.channel.typing():
                result = await test_all_keys()
            await message.reply(f"🔑 **ผลทดสอบ API Keys**\n{result}")
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
            active_keys = len(API_KEYS) - len(exhausted_keys) - len(invalid_keys)
            await message.reply(
                f"📊 **Stats**\n"
                f"• Req: `{stats['total_requests']}`\n"
                f"• Tokens (ประมาณ): `{total_tokens:,}`\n"
                f"• Sessions: `{len(user_histories)}` users\n"
                f"• API Keys: `{len(API_KEYS)}` key(s) · active: `{active_keys}` · quota หมด: `{len(exhausted_keys)}` · invalid: `{len(invalid_keys)}`\n"
                f"• Redis: `{'✅' if _redis else '⚠️ in-memory'}`\n"
                f"• เวลาไทย: `{now_th().strftime('%d/%m/%Y %H:%M')} น.`\n"
                f"• รีเซตถัดไป: `{next_reset.strftime('%d/%m/%Y %H:%M')} น.` (อีก {reset_h}h {reset_m}m)"
            )
            return

    user_input = message.content.strip()

    if not user_input and not message.attachments:
        return

    await process_message(message, user_input)


keep_alive()
client.run(DISCORD_TOKEN)
