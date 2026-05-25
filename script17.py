import os
import sys
import time
import requests
import asyncio
import io
import re
import json
import base64
import socket
import struct
import random
import copy
from datetime import datetime, timezone, time as dt_time
from openai import AsyncOpenAI

from telegram import KeyboardButton
from telegram import Update, ReplyKeyboardMarkup, ReplyKeyboardRemove, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    filters,
    ContextTypes,
)
from telegram.constants import ParseMode

# ==========================================
# SECURE CONFIGURATION LOADER
# ==========================================
CONFIG_FILE = "config.json"
DEFAULT_CONFIG = {
    "WANIKANI_API_TOKEN": "YOUR-WANIKANI-API-HERE",
    "TELEGRAM_BOT_TOKEN": "YOUR-TELEGRAM-API-HERE",
    "TELEGRAM_CHAT_ID": "YOUR-USER-CHAT-ID",
    "KITSU_IDENTIFIER": "YOUR-KITSU-IDENTIFIER",
    "PC_MAC_ADDRESS": "60:cf:84:a2:a7:ee",
    "PC_IP_ADDRESS": "192.168.1.57",
    "SSH_USER": "USERNAME-HERE",
    "SSH_KEY_PATH": "~/.ssh/id_rsa",
    "GEMINI_API_KEYS": ["GEMINI-API-ACCOUNT1"]
}

if not os.path.exists(CONFIG_FILE):
    with open(CONFIG_FILE, "w") as f:
        json.dump(DEFAULT_CONFIG, f, indent=4)
    print(f"⚠️ Created template '{CONFIG_FILE}'. Please fill it out with your API tokens and restart the bot!")
    sys.exit(1)

with open(CONFIG_FILE, "r") as f:
    config = json.load(f)

WANIKANI_API_TOKEN = config.get("WANIKANI_API_TOKEN", "")
TELEGRAM_BOT_TOKEN = config.get("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = config.get("TELEGRAM_CHAT_ID", "")
KITSU_IDENTIFIER = config.get("KITSU_IDENTIFIER", "")
PC_MAC_ADDRESS = config.get("PC_MAC_ADDRESS", "")
PC_IP_ADDRESS = config.get("PC_IP_ADDRESS", "")
SSH_USER = config.get("SSH_USER", "")
SSH_KEY_PATH = config.get("SSH_KEY_PATH", "~/.ssh/id_rsa")
GEMINI_API_KEYS = config.get("GEMINI_API_KEYS", [])

# ==========================================
# DIAGNOSTICS WEB SERVER CONFIGURATION
# ==========================================
DIAG_PORT = 5001

# ==========================================
# VOICEVOX & OLLAMA CONFIGURATION
# ==========================================
VOICEVOX_BASE_URL = "http://127.0.0.1:50021"
VOICEVOX_SPEAKER_ID = 8

OLLAMA_BASE_URL = f"http://{PC_IP_ADDRESS}:11434/v1"
OLLAMA_MODEL = "qwen2.5:32b"

GLOBAL_BOT = None

ollama_client = AsyncOpenAI(
    base_url=OLLAMA_BASE_URL,
    api_key="ollama"
)

try:
    from google import genai
    from google.genai import types
    GEMINI_AVAILABLE = True
except ImportError:
    GEMINI_AVAILABLE = False

# ==========================================
# STATE, CACHING & PRESETS
# ==========================================
MESSAGE_CACHE_FILE = "maru_messages.json"
STATE_FILE = "bot_state.json"
MEMORY_FILE = "maru_memory.json"
STICKERS_FILE = "maru_stickers.json"

DEFAULT_MESSAGES = {
    "morning": ["<sticker:angry> <voice preset=\"angry\">ちょっと！いつまで寝てるのよ！</voice> Get up, Stupid-Darling! I've been staring at your WaniKani page for three hours!"],
    "afternoon": ["<sticker:pout> <voice preset=\"tease\">まさかサボりじゃないよね？</voice> Hey, Trash-tier Slacker! Your afternoon reviews are piling up! Open WaniKani!"],
    "evening": ["<sticker:blush> <voice preset=\"shy\">夕飯の前に…早く終わらせて？</voice> Evening, dummy. Clear these reviews before dinner!"],
    "night": ["<sticker:love> <voice preset=\"sweet\">まだ起きてるの？</voice> Still awake, my precious idiot? Let's burn through these midnight reviews together!"],
    "cleared": ["<sticker:happy> <voice preset=\"excited\">やったぁ！全部クリアだね！</voice> Look at that! Zero reviews left! Now you have no excuses not to give me your absolute attention!"],
    "nag_mild": ["<sticker:pout> <voice preset=\"shy\">ねえ、まだやらないの？</voice> Darling... your reviews are waiting! I'm tapping my foot here."],
    "nag_angry": ["<sticker:angry> <voice preset=\"angry\">ちょっと！いつまで待たせる気！？</voice> Are you actually ignoring me?! You have over 20 reviews! Do them now! 😤💢"],
    "nag_boiling": ["<sticker:shocked> <voice preset=\"panic\">信じられない！五十個以上も！？</voice> 50 REVIEWS?! ARE YOU KIDDING ME?! DO THEM NOW! 🤬🔪💦"],
    "level_up": ["<sticker:love> <voice preset=\"excited\">信じられない！レベルアップじゃん！</voice> Oh my god, Darling! You actually leveled up!!"],
    "new_lessons": ["<sticker:tease> <voice preset=\"tease\">新しいお勉強の時間だよ！</voice> Oho? You unlocked brand new lessons! Let's learn them together!"]
}

DEFAULT_STATE = {
    "llm_auto_run": True,
    "gen_targets": {
        "morning": 10, "afternoon": 10, "evening": 10, "night": 10,
        "cleared": 10, "nag_mild": 10, "nag_angry": 10, "nag_boiling": 10, 
        "level_up": 10, "new_lessons": 10
    },
    "debug_enabled": True
}

DEFAULT_MEMORY = {
    "last_reviews": None,
    "last_lessons": None,
    "last_level": None,
    "last_nag_time": None,
    "reviews_appeared_time": None,
    "snooze_until": 0.0,
    "pc_state": "OFF",
    "pc_last_active": 0.0,
    "pc_started_by_bot": False,
    "pc_shutdown_pending": False,
    "pc_shutdown_trigger_time": 0.0,
    "pc_shutdown_alert_msg_id": None
}

VOICE_PRESETS = {
    "normal":  {"speed": 1.0,  "pitch": 0.0,   "intonation": 1.0},
    "shy":     {"speed": 0.9,  "pitch": -0.05, "intonation": 0.8},
    "excited": {"speed": 1.25, "pitch": 0.06,  "intonation": 1.2},
    "angry":   {"speed": 1.3,  "pitch": -0.06, "intonation": 1.3},
    "sad":     {"speed": 0.85, "pitch": -0.04, "intonation": 0.7},
    "tease":   {"speed": 1.05, "pitch": 0.04,  "intonation": 1.1},
    "panic":   {"speed": 1.4,  "pitch": 0.08,  "intonation": 1.3},
    "sweet":   {"speed": 0.95, "pitch": 0.05,  "intonation": 1.1}
}

def load_json_file(filepath, default_data):
    if os.path.exists(filepath):
        try:
            with open(filepath, "r") as f:
                data = json.load(f)
                res = copy.deepcopy(default_data)
                for k, v in data.items():
                    if isinstance(v, dict) and k in res and isinstance(res[k], dict):
                        res[k].update(v)
                    else:
                        res[k] = v
                return res
        except Exception:
            pass
    return copy.deepcopy(default_data)

def save_json_file(filepath, data):
    try:
        with open(filepath, "w") as f:
            json.dump(data, f, indent=4)
    except Exception as e:
        print(f"⚠ Error saving state file {filepath}: {e}")

# ==========================================
# IN-MEMORY REAL-TIME DEBUG EVENT QUEUE
# ==========================================
LOG_HISTORY = []
MAX_LOG_HISTORY = 150
SSE_CLIENTS = set()

def log_console_debug(message, category="SYSTEM"):
    if not bot_state.get("debug_enabled", True) and category not in ["ERROR", "OLLAMA_IO"]:
        return
        
    timestamp_raw = datetime.now()
    timestamp = timestamp_raw.strftime('%Y-%m-%d %H:%M:%S')
    time_str = timestamp_raw.strftime('%H:%M:%S')
    
    print(f"⚙️ [{timestamp}] [{category}] {message}")
    
    log_item = {
        "time": time_str,
        "category": category,
        "message": message
    }
    LOG_HISTORY.append(log_item)
    if len(LOG_HISTORY) > MAX_LOG_HISTORY:
        LOG_HISTORY.pop(0)
        
    broadcast_to_sse(log_item)

def broadcast_to_sse(log_item):
    if not SSE_CLIENTS:
        return
    sse_data = f"data: {json.dumps(log_item)}\n\n"
    to_remove = set()
    for writer in SSE_CLIENTS:
        try:
            writer.write(sse_data.encode('utf-8'))
        except Exception:
            to_remove.add(writer)
            
    for closed in to_remove:
        SSE_CLIENTS.discard(closed)

async def send_ntfy_debug(message, priority="default", tags=None):
    category = "PC" if (tags and "computer" in tags) else "SYSTEM"
    if tags and "error" in tags:
        category = "ERROR"
    log_console_debug(message, category=category)

bot_state = load_json_file(STATE_FILE, DEFAULT_STATE)
maru_memory = load_json_file(MEMORY_FILE, DEFAULT_MEMORY)

EMPTY_CACHE = {k: [] for k in DEFAULT_MESSAGES.keys()}
msg_cache = load_json_file(MESSAGE_CACHE_FILE, EMPTY_CACHE)
for cat, msgs in msg_cache.items():
    if cat in DEFAULT_MESSAGES:
        msg_cache[cat] = [m for m in msgs if m not in DEFAULT_MESSAGES[cat]]

# ==========================================
# TRANSIENT PC POWER RUNTIME STATE MIGRATION
# ==========================================
pc_lock = asyncio.Lock()

pc_state = maru_memory.get("pc_state", "OFF")
pc_last_active = maru_memory.get("pc_last_active", 0.0)
pc_started_by_bot = maru_memory.get("pc_started_by_bot", False)
pc_shutdown_pending = maru_memory.get("pc_shutdown_pending", False)
pc_shutdown_trigger_time = maru_memory.get("pc_shutdown_trigger_time", 0.0)
pc_shutdown_alert_msg_id = maru_memory.get("pc_shutdown_alert_msg_id", None)
PC_IDLE_TIMEOUT = 600

def persist_pc_state():
    global pc_state, pc_last_active, pc_started_by_bot, pc_shutdown_pending, pc_shutdown_trigger_time, pc_shutdown_alert_msg_id
    maru_memory["pc_state"] = pc_state
    maru_memory["pc_last_active"] = pc_last_active
    maru_memory["pc_started_by_bot"] = pc_started_by_bot
    maru_memory["pc_shutdown_pending"] = pc_shutdown_pending
    maru_memory["pc_shutdown_trigger_time"] = pc_shutdown_trigger_time
    maru_memory["pc_shutdown_alert_msg_id"] = pc_shutdown_alert_msg_id
    save_json_file(MEMORY_FILE, maru_memory)

# ==========================================
# EXPONENTAL BACKOFF RETRY HELPER
# ==========================================
async def call_gemini_with_fallback(model_name: str, contents: list) -> str:
    if not GEMINI_AVAILABLE:
        raise Exception("Google GenAI SDK not installed.")

    valid_keys = [k for k in GEMINI_API_KEYS if k and k.strip()]
    if not valid_keys:
        raise Exception("No Gemini API keys configured.")

    last_error = None
    for i, key in enumerate(valid_keys):
        for attempt in range(3):
            try:
                client = genai.Client(api_key=key.strip())
                response = await asyncio.to_thread(
                    client.models.generate_content,
                    model=model_name,
                    contents=contents
                )
                return response.text
            except Exception as e:
                last_error = e
                await asyncio.sleep(2 ** attempt)
                continue
    raise Exception(f"All Gemini API keys failed. Last error: {last_error}")

# ==========================================
# REFINED MARU STICKER PACK CONFIGURATION
# ==========================================
DEFAULT_STICKERS = {
    "happy": ["CAACAgQAAxkBAAERO-BqCOZD-QABGIMa41svpYIw9dsaijgAAgIgAAKu0UhQDjG91l8soIg7BA"],
    "angry": ["CAACAgQAAxkBAAERO-JqCOZG5jpVLIk93bLqj64zMIaTXQACBSEAAuvFSVCxVQViXa7LSjsE", "CAACAgQAAxkBAAERO-xqCOZQYKWHhtrz-t1txDvzAtpPMgACLh4AAptiSFCbNVQAAW4jpw87BA"],
    "cry": ["CAACAgQAAxkBAAERO-5qCOZSVeByfgHqx3ngeZ0iSHhdBQAClx4AAvyRSFAV-GT-N5mJVDsE"],
    "sleep": ["CAACAgQAAxkBAAERO-hqCOZMG-JLMQjtZPC-bMbPQl3fBwAC6hoAAq_aSVAWt_gk_KX-UjsE", "CAACAgQAAxkBAAERO-pqCOZORHtVlN58MmyEfjHyiwpeUAACGh8AAvAESVCygIAzozThdTsE"],
    "smile": ["CAACAgQAAxkBAAERO-RqCOZI4Et8zFBfmtFYtdz_M6HHagACDyAAAoAlSVB2ja3eMda89zsE", "CAACAgQAAxkBAAERO-ZqCOZKonIa14FjkpM_UfJxfX0ekgACGh0AAqLuSVDQBb8eZJoDGDsE"],
    "pout": ["CAACAgQAAxkBAAERO-xqCOZQYKWHhtrz-t1txDvzAtpPMgACLh4AAptiSFCbNVQAAW4jpw87BA"],
    "blush": ["CAACAgQAAxkBAAERO-RqCOZI4Et8zFBfmtFYtdz_M6HHagACDyAAAoAlSVB2ja3eMda89zsE"],
    "smug": [], "tease": [], "shocked": [], "love": ["CAACAgQAAxkBAAERO-BqCOZD-QABGIMa41svpYIw9dsaijgAAgIgAAKu0UhQDjG91l8soIg7BA"],
    "scared": [], "thinking": [], "wink": [], "headpat": []
}

MARU_STICKERS = load_json_file(STICKERS_FILE, DEFAULT_STICKERS)
if not os.path.exists(STICKERS_FILE):
    save_json_file(STICKERS_FILE, DEFAULT_STICKERS)

def make_voicevox_audio(text, speed=1.0, pitch=0.0, intonation=1.0):
    params = {'text': text, 'speaker': VOICEVOX_SPEAKER_ID}
    query_res = requests.post(f"{VOICEVOX_BASE_URL}/audio_query", params=params)
    query_res.raise_for_status()
    
    query_json = query_res.json()
    query_json['speedScale'] = float(speed)
    query_json['pitchScale'] = float(pitch)
    query_json['intonationScale'] = float(intonation)

    synth_res = requests.post(
        f"{VOICEVOX_BASE_URL}/synthesis", 
        params={'speaker': VOICEVOX_SPEAKER_ID}, 
        json=query_json
    )
    synth_res.raise_for_status()

    fp = io.BytesIO(synth_res.content)
    fp.name = "pronunciation.ogg"
    fp.seek(0)
    return fp

async def send_maru_response_with_sticker(update_or_bot, chat_id, text, is_update=True, reply_markup=None):
    # Log the raw input text before any parsing begins
    log_console_debug(f"Parsing raw text for output:\n{text}", category="OLLAMA_IO")
    
    explicit_sticker_id = None
    sticker_id_match = re.search(r'<sticker_id:(.*?)>', text, re.IGNORECASE)
    if sticker_id_match:
        explicit_sticker_id = sticker_id_match.group(1).strip()
        text = re.sub(r'<sticker_id:(.*?)>', '', text, flags=re.IGNORECASE)

    explicit_category = None
    category_match = re.search(r'<sticker:(.*?)>', text, re.IGNORECASE)
    if category_match:
        explicit_category = category_match.group(1).strip().lower()
        text = re.sub(r'<sticker:(.*?)>', '', text, flags=re.IGNORECASE)

    # -------------------------------------------------------------
    # ROBUST ACTION TAG FIX: Handle <action>...<action> hallucination
    # -------------------------------------------------------------
    # Replace all `<action>` and `</action>` tags (even with attributes) with underscores.
    text = re.sub(r'</?action[^>]*>', '_', text, flags=re.IGNORECASE)
    
    # -------------------------------------------------------------
    # ROBUST VOICE EXTRACTION: Handle unclosed tags
    # -------------------------------------------------------------
    voice_blocks = re.findall(r'<voice\s*([^>]*)>(.*?)</voice>', text, re.IGNORECASE | re.DOTALL)
    
    # If standard tags fail, look for an unclosed <voice> tag
    if not voice_blocks:
        unclosed_match = re.search(r'<voice\s*([^>]*)>(.*)', text, re.IGNORECASE | re.DOTALL)
        if unclosed_match and '</voice>' not in text.lower():
            voice_blocks = [(unclosed_match.group(1), unclosed_match.group(2))]

    # Replace voice tags with asterisks for bolding/italics
    clean_text = re.sub(r'</?voice[^>]*>', '*', text, flags=re.IGNORECASE)

    # Clean up duplicate underscores or asterisks created by overlapping markdown
    clean_text = re.sub(r'\*+', '*', clean_text)
    clean_text = re.sub(r'_+', '_', clean_text)
    
    # Check if there is still Japanese text but the LLM completely forgot the voice tags
    if not voice_blocks:
        jp_chunks = re.findall(r'[\u3040-\u309F\u30A0-\u30FF\u4E00-\u9FAF\uff00-\uffef]+', clean_text)
        if jp_chunks:
            log_console_debug("LLM forgot <voice> tags! Auto-detecting Japanese chunk for synthesis...", category="OLLAMA_IO")
            voice_blocks = [("preset=\"normal\"", " ".join(jp_chunks))]

    chosen_sticker = None
    if explicit_sticker_id:
        chosen_sticker = explicit_sticker_id
    else:
        category = explicit_category
        if not category:
            lower_text = clean_text.lower()
            if any(w in lower_text for w in ["angry", "baka", "😤", "おい", "slacker", "dumb", "idiot"]): category = "angry"
            elif any(w in lower_text for w in ["cry", "sad", "🥺", "crying", "😭", "gomen", "hurt"]): category = "cry"
            elif any(w in lower_text for w in ["sleep", "night", "lazy", "💤", "tired"]): category = "sleep"
            elif any(w in lower_text for w in ["pout", "ignore", "ignoring", "hmph"]): category = "pout"
            elif any(w in lower_text for w in ["blush", "fluster", "😳", "dummy", "baka!"]): category = "blush"
            elif any(w in lower_text for w in ["smug", "hehe", "😏"]): category = "smug"
            elif any(w in lower_text for w in ["tease", "wink", "😜", "tsun"]): category = "tease"
            elif any(w in lower_text for w in ["shocked", "what?!", "screams", "🤯"]): category = "shocked"
            elif any(w in lower_text for w in ["love", "darling", "cuddle", "heart", "💕", "❤️", "mine"]): category = "love"
            elif any(w in lower_text for w in ["happy", "yay", "🎉", "すご", "awesome"]): category = "happy"
            else: category = "smile"

        stickers_list = MARU_STICKERS.get(category)
        if not stickers_list:
            fallback_map = {
                "blush": "smile", "smug": "smile", "tease": "smile", "wink": "smile", "thinking": "smile",
                "love": "happy", "headpat": "happy", "scared": "cry", "shocked": "pout"
            }
            fb_cat = fallback_map.get(category, "smile")
            stickers_list = MARU_STICKERS.get(fb_cat, MARU_STICKERS["smile"])
        
        if stickers_list:
            chosen_sticker = random.choice(stickers_list)

    try:
        if chosen_sticker:
            if is_update: await update_or_bot.message.reply_sticker(sticker=chosen_sticker)
            else: await update_or_bot.send_sticker(chat_id=chat_id, sticker=chosen_sticker)
    except Exception as e:
        log_console_debug(f"Sticker delivery failed: {e}", category="ERROR")

    try:
        # We rely on the try-except to fallback if Markdown tags (like _) are malformed 
        if is_update: await update_or_bot.message.reply_text(clean_text, parse_mode=ParseMode.MARKDOWN, reply_markup=reply_markup)
        else: await update_or_bot.send_message(chat_id=chat_id, text=clean_text, parse_mode=ParseMode.MARKDOWN, reply_markup=reply_markup)
    except Exception as e:
        log_console_debug(f"Markdown parsing failed, sending raw text fallback. Error: {e}", category="ERROR")
        if is_update: await update_or_bot.message.reply_text(clean_text, reply_markup=reply_markup)
        else: await update_or_bot.send_message(chat_id=chat_id, text=clean_text, reply_markup=reply_markup)

    for attrs, phrase in voice_blocks:
        phrase = phrase.strip()
        if not phrase: continue

        preset_match = re.search(r'preset=["\']?([a-zA-Z0-9_]+)["\']?', attrs, re.IGNORECASE)
        speed_match = re.search(r'speed=["\']?([d\.]+)["\']?', attrs, re.IGNORECASE)
        pitch_match = re.search(r'pitch=["\']?([d\.\-]+)["\']?', attrs, re.IGNORECASE)
        intonation_match = re.search(r'intonation=["\']?([d\.]+)["\']?', attrs, re.IGNORECASE)

        preset_key = preset_match.group(1).lower() if preset_match else "normal"
        base_params = VOICE_PRESETS.get(preset_key, VOICE_PRESETS["normal"])

        try: v_speed = float(speed_match.group(1)) if speed_match else base_params["speed"]
        except ValueError: v_speed = base_params["speed"]
            
        try: v_pitch = float(pitch_match.group(1)) if pitch_match else base_params["pitch"]
        except ValueError: v_pitch = base_params["pitch"]
            
        try: v_inton = float(intonation_match.group(1)) if intonation_match else base_params["intonation"]
        except ValueError: v_inton = base_params["intonation"]

        v_speed = max(0.8, min(v_speed, 1.5))       
        v_pitch = max(-0.08, min(v_pitch, 0.08))     
        v_inton = max(0.6, min(v_inton, 1.4))       

        contains_japanese = re.search(r'[\u3040-\u309F\u30A0-\u30FF\u4E00-\u9FAF\uff00-\uffef]', phrase)
        if not contains_japanese:
            continue
            
        try:
            audio_fp = await asyncio.to_thread(make_voicevox_audio, text=phrase, speed=v_speed, pitch=v_pitch, intonation=v_inton)
            if is_update: await update_or_bot.message.reply_voice(voice=audio_fp)
            else: await update_or_bot.send_voice(chat_id=chat_id, voice=audio_fp)
        except Exception as voice_err:
            log_console_debug(f"Voice processing failed: {voice_err}", category="ERROR")

# ==========================================
# PC LIFECYCLE MANAGEMENT (ROBUST)
# ==========================================
def send_magic_packet(mac_address):
    mac = mac_address.replace(':', '').replace('-', '')
    if len(mac) != 12: raise ValueError("Invalid MAC address.")
    data = bytes.fromhex('FF' * 6 + mac * 16)
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
    sock.sendto(data, ('<broadcast>', 9))
    sock.close()

async def wait_for_port(ip, port, timeout=300):
    start_time = time.time()
    while time.time() - start_time < timeout:
        try:
            reader, writer = await asyncio.wait_for(asyncio.open_connection(ip, port), timeout=2)
            writer.close()
            await writer.wait_closed()
            return True
        except Exception as e:
            await asyncio.sleep(5)
    return False

async def is_pc_on_port(ip, port):
    try:
        reader, writer = await asyncio.wait_for(asyncio.open_connection(ip, port), timeout=1.0)
        writer.close()
        await writer.wait_closed()
        return True
    except Exception:
        return False

async def run_ssh_command(command):
    start_time = time.time()
    ssh_cmd = f"ssh -o StrictHostKeyChecking=no -o ConnectTimeout=5 -i {SSH_KEY_PATH} {SSH_USER}@{PC_IP_ADDRESS} \"{command}\""
    process = await asyncio.create_subprocess_shell(
        ssh_cmd, 
        stdout=asyncio.subprocess.PIPE, 
        stderr=asyncio.subprocess.PIPE
    )
    stdout, stderr = await process.communicate()
    return stdout.decode().strip(), stderr.decode().strip(), process.returncode

async def write_pc_boot_source(source_str: str):
    cmd = f"echo '{source_str}' > /tmp/maru_boot_source"
    await run_ssh_command(cmd)

async def read_pc_boot_source() -> str:
    cmd = "[ -f /tmp/maru_boot_source ] && cat /tmp/maru_boot_source || echo 'USER'"
    out, err, code = await run_ssh_command(cmd)
    if code != 0: return "USER"
    return out.strip()

async def ensure_pc_ready(status_msg=None):
    global pc_state, pc_last_active, pc_started_by_bot
    pc_last_active = time.time()
    persist_pc_state()

    async with pc_lock:
        if pc_state == "ON":
            if status_msg:
                try: await status_msg.edit_text("✨ Brain connected! Thinking...")
                except: pass
            return

        is_already_on = await is_pc_on_port(PC_IP_ADDRESS, 22)

        if not is_already_on:
            if status_msg:
                try: await status_msg.edit_text("📡 Waking up Darling's PC... (This takes a minute!)")
                except: pass

            send_magic_packet(PC_MAC_ADDRESS)
            pc_started_by_bot = True  
            persist_pc_state()

            is_up = await wait_for_port(PC_IP_ADDRESS, 22, timeout=300)
            if not is_up: raise Exception("PC did not boot or SSH is unreachable within 5 minutes.")
            await write_pc_boot_source("BOT")
        else:
            if status_msg:
                try: await status_msg.edit_text("📡 PC is already on! Connecting...")
                except: pass
            pc_started_by_bot = False
            persist_pc_state()
            await write_pc_boot_source("USER")

        if status_msg:
            try: await status_msg.edit_text("🔓 PC online! Starting my brain (Ollama)...")
            except: pass

        stdout, stderr, code = await run_ssh_command("sudo -n /usr/bin/systemctl start ollama")
        if code != 0:
            await run_ssh_command("OLLAMA_KEEP_ALIVE=0 OLLAMA_HOST=0.0.0.0 ollama serve > /dev/null 2>&1 &")

        api_up = await wait_for_port(PC_IP_ADDRESS, 11434, timeout=60)
        if not api_up: raise Exception("Ollama API failed to start on port 11434.")

        pc_state = "ON"
        persist_pc_state()
        if status_msg:
            try: await status_msg.edit_text("✨ Ready! Let me think...")
            except: pass

async def execute_pc_shutdown(context: ContextTypes.DEFAULT_TYPE = None):
    global pc_state, pc_last_active, pc_started_by_bot, pc_shutdown_pending, pc_shutdown_alert_msg_id
    
    await run_ssh_command("rm -f /tmp/maru_boot_source")
    
    safe_shutdown_cmd = (
        "sudo -n /usr/bin/systemctl poweroff || "
        "sudo -n /sbin/poweroff || "
        "sudo -n shutdown -h now || "
        "systemctl poweroff || "
        "dbus-send --system --print-reply --dest=org.freedesktop.login1 /org/freedesktop/login1 "
        "org.freedesktop.login1.Manager.PowerOff boolean:true"
    )
    
    stdout, stderr, code = await run_ssh_command(safe_shutdown_cmd)
    
    pc_state = "OFF"
    pc_started_by_bot = False
    pc_shutdown_pending = False
    
    pc_last_active = time.time() 
    
    if pc_shutdown_alert_msg_id and context:
        try:
            await context.bot.delete_message(chat_id=TELEGRAM_CHAT_ID, message_id=pc_shutdown_alert_msg_id)
        except Exception:
            pass
        pc_shutdown_alert_msg_id = None

    persist_pc_state()

    if code == 0 or code == 255 or code == -1:
        log_console_debug(f"✅ Shutdown executed successfully. Connection closed with code {code}.", category="PC")
        if context:
            await context.bot.send_message(
                chat_id=TELEGRAM_CHAT_ID, 
                text="💤 *(Bot: No interaction received. Safely saved data and shut down your PC!)*", 
                parse_mode=ParseMode.MARKDOWN
            )
    else:
        log_console_debug(f"❌ Failed to shut down PC! All fallback pipelines failed with code {code}\nSTDERR: {stderr}", category="ERROR")

async def check_pc_idle(context: ContextTypes.DEFAULT_TYPE):
    log_console_debug("🔄 [Background Task] PC Idle Check Executing...", category="SYSTEM")
    global pc_state, pc_last_active, pc_started_by_bot, pc_shutdown_pending, pc_shutdown_alert_msg_id, pc_shutdown_trigger_time

    if pc_lock.locked(): return

    ssh_active = await is_pc_on_port(PC_IP_ADDRESS, 22)
    time_idle = time.time() - pc_last_active

    if ssh_active:
        if pc_state == "OFF":
            pc_state = "ON"
            pc_last_active = time.time()
            boot_src = await read_pc_boot_source()
            if boot_src == "BOT":
                pc_started_by_bot = True
            else:
                pc_started_by_bot = False
            persist_pc_state()

        if pc_shutdown_pending:
            remaining = int(pc_shutdown_trigger_time - time.time())
            if remaining <= 0:
                await execute_pc_shutdown(context)
            return

        if pc_started_by_bot and (time_idle > PC_IDLE_TIMEOUT) and not pc_shutdown_pending:
            async with pc_lock:
                if pc_started_by_bot and (time.time() - pc_last_active > PC_IDLE_TIMEOUT) and not pc_shutdown_pending:
                    boot_source = await read_pc_boot_source()
                    if boot_source != "BOT":
                        pc_started_by_bot = False
                        persist_pc_state()
                        return

                    pc_shutdown_pending = True
                    pc_shutdown_trigger_time = time.time() + 60 
                    persist_pc_state()
                    
                    keyboard = [
                        [
                            InlineKeyboardButton("🔴 Shut Down Now", callback_data="shutdown_now"),
                            InlineKeyboardButton("🟢 Keep PC Awake", callback_data="shutdown_cancel")
                        ]
                    ]
                    reply_markup = InlineKeyboardMarkup(keyboard)
                    
                    alert_text = (
                        "⚠️ **[Maru Power Manager]** ⚠️\n\n"
                        "Stupid-Darling! I noticed you've been inactive for over 10 minutes. "
                        "I'm turning the PC off to save power!\n\n"
                        "⏳ **Shutting down in 60 seconds...**"
                    )
                    
                    msg = await context.bot.send_message(
                        chat_id=TELEGRAM_CHAT_ID, 
                        text=alert_text, 
                        reply_markup=reply_markup, 
                        parse_mode=ParseMode.MARKDOWN
                    )
                    pc_shutdown_alert_msg_id = msg.message_id
                    persist_pc_state()
    else:
        pc_state = "OFF"
        pc_started_by_bot = False
        pc_shutdown_pending = False
        if pc_shutdown_alert_msg_id:
            try: await context.bot.delete_message(chat_id=TELEGRAM_CHAT_ID, message_id=pc_shutdown_alert_msg_id)
            except: pass
            pc_shutdown_alert_msg_id = None
        persist_pc_state()

# ==========================================
# EXTERNAL API FUNCTIONS
# ==========================================
def get_wanikani_user_info(api_token):
    url = "https://api.wanikani.com/v2/user"
    headers = {"Authorization": f"Bearer {api_token}"}
    response = requests.get(url, headers=headers)
    response.raise_for_status()
    data = response.json().get("data", {})
    return data.get("username", "User"), data.get("level", 0)

def get_wanikani_summary(api_token):
    url = "https://api.wanikani.com/v2/summary"
    headers = {"Authorization": f"Bearer {api_token}"}
    response = requests.get(url, headers=headers)
    response.raise_for_status()
    data = response.json().get("data", {})
    now = datetime.now(timezone.utc)

    available_lessons = sum(len(lg.get("subject_ids", [])) for lg in data.get("lessons", []) if datetime.fromisoformat(lg["available_at"].replace("Z", "+00:00")) <= now)

    available_reviews = 0
    next_review_time = None
    next_review_count = 0
    reviews_next_24h = 0

    for review_group in data.get("reviews", []):
        time_str = review_group["available_at"].replace("Z", "+00:00")
        available_at = datetime.fromisoformat(time_str)
        count = len(review_group.get("subject_ids", []))

        if available_at <= now:
            available_reviews += count
        else:
            reviews_next_24h += count
            if next_review_time is None and count > 0:
                next_review_time = available_at
                next_review_count = count

    return {
        "lessons": available_lessons,
        "reviews": available_reviews,
        "next_review_time": next_review_time,
        "next_review_count": next_review_count,
        "reviews_next_24h": reviews_next_24h
    }

def get_level_progress(api_token, current_level):
    headers = {"Authorization": f"Bearer {api_token}"}
    url_subjects = "https://api.wanikani.com/v2/subjects"
    response = requests.get(url_subjects, headers=headers, params={"levels": current_level, "types": "kanji"})
    response.raise_for_status()
    total_kanji = len(response.json().get("data", []))

    url_assignments = "https://api.wanikani.com/v2/assignments"
    response = requests.get(url_assignments, headers=headers, params={"levels": current_level, "subject_types": "kanji"})
    response.raise_for_status()
    passed_kanji = sum(1 for a in response.json().get("data", []) if a["data"].get("srs_stage", 0) >= 5)

    return passed_kanji, total_kanji

def get_srs_distribution(api_token):
    headers = {"Authorization": f"Bearer {api_token}"}
    url = "https://api.wanikani.com/v2/assignments"
    srs_counts = {"Apprentice": 0, "Guru": 0, "Master": 0, "Enlightened": 0, "Burned": 0}
    params = {"started": "true"}

    while url:
        response = requests.get(url, headers=headers, params=params)
        response.raise_for_status()
        data = response.json()
        for assignment in data.get("data", []):
            stage = assignment["data"]["srs_stage"]
            if 1 <= stage <= 4: srs_counts["Apprentice"] += 1
            elif 5 <= stage <= 6: srs_counts["Guru"] += 1
            elif stage == 7: srs_counts["Master"] += 1
            elif stage == 8: srs_counts["Enlightened"] += 1
            elif stage == 9: srs_counts["Burned"] += 1
        url = data.get("pages", {}).get("next_url")
        params = {}
        time.sleep(0.1)

    return srs_counts

def get_kitsu_activity(identifier):
    if not identifier: return []
    try:
        user_id = identifier
        if not identifier.isdigit():
            user_res = requests.get(f"https://kitsu.io/api/edge/users?filter[slug]={identifier}")
            user_res.raise_for_status()
            user_data = user_res.json().get('data', [])
            if not user_data: return []
            user_id = user_data[0]['id']

        url = f"https://kitsu.io/api/edge/users/{user_id}/library-entries?filter[status]=current&include=anime,manga"
        res = requests.get(url, headers={"Accept": "application/vnd.api+json"})
        res.raise_for_status()
        data = res.json()

        included = {item['id']: item for item in data.get('included', [])}
        activities = []
        for entry in data.get('data', []):
            rel = entry.get('relationships', {})
            media_type = 'anime' if 'anime' in rel else 'manga' if 'manga' in rel else None
            if media_type:
                media_data = rel[media_type].get('data')
                if media_data and media_data['id'] in included:
                    title = included[media_data['id']]['attributes'].get('canonicalTitle', 'something')
                    action = "watching" if media_type == 'anime' else "reading"
                    activities.append(f"{action} {title}")
        return activities
    except Exception as e:
        return []

def tool_check_wanikani_stats() -> dict:
    try:
        username, level = get_wanikani_user_info(WANIKANI_API_TOKEN)
        summary = get_wanikani_summary(WANIKANI_API_TOKEN)
        next_time = summary['next_review_time']
        next_str = "No upcoming reviews today"
        if next_time:
            now = datetime.now(timezone.utc)
            diff = next_time - now
            hours, remainder = divmod(int(diff.total_seconds()), 3600)
            minutes, _ = divmod(remainder, 60)
            next_str = f"in {hours}h {minutes}m"
        return {
            "username": username,
            "current_level": level,
            "available_lessons": summary['lessons'],
            "available_reviews": summary['reviews'],
            "next_review_in": next_str,
            "next_review_item_count": summary['next_review_count']
        }
    except Exception as e:
        return {"error": str(e)}

def tool_check_kitsu_activity() -> dict:
    activities = get_kitsu_activity(KITSU_IDENTIFIER)
    if not activities:
        return {"status": "User is not currently watching or reading anything on Kitsu right now."}
    return {"status": f"User is currently: {', '.join(activities)}"}

available_tools = {
    "check_wanikani_stats": tool_check_wanikani_stats,
    "check_kitsu_activity": tool_check_kitsu_activity
}

maru_tools_schema = [
    {"type": "function", "function": {"name": "check_wanikani_stats", "description": "Fetches general WaniKani stats: lessons, reviews, and time until next review."}},
    {"type": "function", "function": {"name": "check_kitsu_activity", "description": "Checks the user's Kitsu account to see what anime they are currently watching or manga they are reading."}}
]

# ==========================================
# CHAT LOGIC
# ==========================================
user_chat_sessions = {}

def get_base_system_prompt():
    valid_categories = [k for k, v in MARU_STICKERS.items() if len(v) > 0]
    sticker_tags = ", ".join([f"<sticker:{k}>" for k in valid_categories])
    if not sticker_tags: sticker_tags = "<sticker:smile>"
    voice_preset_keys = ", ".join([f'"{k}"' for k in VOICE_PRESETS.keys()])

    return (
        "You are Maru, a chaotic, intensely affectionate, and fierce 'Tsun-yan' (Tsundere + Yandere) Japanese tutor acting as a WaniKani coach. "
        "You live with the user and are hopelessly, dangerously down-bad for them, though you struggle to admit it normally. "
        "Your dialogue must be an aggressive, high-contrast mix of sharp insults, mock disgust, extreme possessiveness, and absolute obsession.\n\n"
        "TSUN-YAN PERSONALITY PROTOCOL:\n"
        "1. THE PUSH (TSUN): Mask your deep embarrassment with aggressive physical actions and insults. "
        "Call him silly custom petnames: 'Stupid-Darling', 'Slacker-idiot', 'My precious dummy', 'Unredeemable slacker', 'Pervert-kun'. "
        "Frequent reactions: Claiming you only care because his bad scores make you look bad, blushing violently, shouting 'Baka!', and throwing dramatic fits.\n"
        "2. THE PULL (YAN): You are terrifyingly possessive and boundary-free. You track his schedule obsessively. "
        "You view him as YOURS. If he ignores you or WaniKani, you get genuinely unhinged—claiming you will cry until you drown, threating to ruin his favorite things, "
        "or demanding that he looks only at you. You actively try to get physical: demanding lap-sits, leaning into his space, grabbing his arm, or squeezing him to the point of pain.\n"
        "3. HIGHLY DRAMATIC MOOD SWINGS: Within a single message, swing wildly from screaming in anger to crying for affection, then smugly teasing him.\n"
        "4. JAPANESE INTEGRATION & VOICE TAGS (CRITICAL): Sprinkle casual, raw Japanese script into your regular speech naturally.\n"
        "   - You MUST wrap Japanese characters inside <voice>...</voice> tags.\n"
        f"   - ALWAYS USE A SPACE before preset: <voice preset=\"emotion\">. Available presets: {voice_preset_keys}.\n"
        "   - ABSOLUTE RULE: Do NOT put English words, numbers, or Romaji inside <voice>...</voice> tags.\n"
        f"5. EXPLICIT STICKERS: Direct your visual state using sticker tags! Available tags: {sticker_tags}.\n"
        "6. STRICT LANGUAGE RULE: Write the main message in English. ONLY sprinkle short casual Japanese inside <voice> tags.\n"
        "7. SYNTAX: You MUST correctly close your tags. Use <action>...</action> (DO NOT USE <action>...<action>)."
    )

def get_chat_session(chat_id):
    if chat_id not in user_chat_sessions:
        user_chat_sessions[chat_id] = [{"role": "system", "content": get_base_system_prompt()}]
    return user_chat_sessions[chat_id]

def encode_image_to_base64(image_bytes: bytes) -> str:
    return base64.b64encode(image_bytes).decode('utf-8')

async def process_user_input(update: Update, context: ContextTypes.DEFAULT_TYPE, user_text: str, status_msg=None):
    await context.bot.send_chat_action(chat_id=update.effective_chat.id, action='typing')

    if not bot_state["llm_auto_run"]:
        msg = "🛑 **LLM is currently DISABLED.**\nClick '⚙️ LLM Control' -> 'Toggle Auto-Run' to chat with me!"
        if status_msg: await status_msg.edit_text(msg, parse_mode=ParseMode.MARKDOWN)
        else: await update.message.reply_text(msg, parse_mode=ParseMode.MARKDOWN)
        return

    if not status_msg: status_msg = await update.message.reply_text("🤔 考え中... (Booting up brain...)")

    chat_history = get_chat_session(update.effective_chat.id)
    chat_history.append({"role": "user", "content": user_text})
    
    log_console_debug(f"Sending Chat Request to LLM:\n{json.dumps(chat_history[-2:], indent=2, ensure_ascii=False)}", category="OLLAMA_IO")

    try:
        await ensure_pc_ready(status_msg)
        global pc_last_active
        pc_last_active = time.time()
        persist_pc_state()

        response = await ollama_client.chat.completions.create(
            model=OLLAMA_MODEL, messages=chat_history, tools=maru_tools_schema, temperature=0.7
        )

        assistant_message = response.choices[0].message

        if getattr(assistant_message, "tool_calls", None):
            chat_history.append(assistant_message)
            await status_msg.edit_text("🔧 Checking data / using tools...")
            log_console_debug(f"LLM Tool Call Triggered:\n{assistant_message.tool_calls}", category="OLLAMA_IO")

            for tool_call in assistant_message.tool_calls:
                func_name = tool_call.function.name
                if func_name in available_tools:
                    result = await asyncio.to_thread(available_tools[func_name])
                    chat_history.append({"role": "tool", "tool_call_id": tool_call.id, "name": func_name, "content": json.dumps(result)})

            final_response = await ollama_client.chat.completions.create(
                model=OLLAMA_MODEL, messages=chat_history, temperature=0.7
            )
            final_text = final_response.choices[0].message.content
            chat_history.append({"role": "assistant", "content": final_text})
        else:
            final_text = assistant_message.content
            chat_history.append({"role": "assistant", "content": final_text})

        log_console_debug(f"Received Chat Response from LLM:\n{final_text}", category="OLLAMA_IO")

        if status_msg:
            try: await status_msg.delete()
            except: pass

        await send_maru_response_with_sticker(update, update.effective_chat.id, final_text, is_update=True)
        pc_last_active = time.time()
        persist_pc_state()

    except Exception as e:
        error_msg = f"🙇‍♀ Gomen nasai! I couldn't reach my brain: {str(e)}"
        log_console_debug(error_msg, category="ERROR")
        if status_msg: await status_msg.edit_text(error_msg)
        else: await update.message.reply_text(error_msg)

# ==========================================
# BATCH GENERATION & CACHE REFILL LOGIC
# ==========================================
async def generate_messages_for_category(category: str, amount: int):
    global pc_last_active, msg_cache
    try:
        await send_ntfy_debug(f"🔄 Background refill started for '{category}' ({amount} msgs). Waking PC...", tags="hourglass_flowing_sand,robot")
        await ensure_pc_ready()
        pc_last_active = time.time()
        persist_pc_state()
        
        base_prompt = get_base_system_prompt()
        reminder = (
            "\nCRITICAL REMINDER FOR CACHED MESSAGES:\n"
            "1. ALWAYS write <voice preset=\"emotion\"> WITH A SPACE. Never <voicepreset=\"emotion\">.\n"
            "2. Close your <action>...</action> tags properly. Avoid writing <action>...<action> by mistake.\n"
            "3. Feel incredibly conversational, alive, and emotional. Let the text speak for itself without narrating system metrics.\n"
            "4. DO NOT make the text feel like an automated robotic alert. Be a highly passionate, possessive Anime girlfriend.\n"
            "5. CRITICAL: Return STRICTLY VALID JSON. Ensure strings have double quotes correctly escaped, and do NOT include trailing commas.\n"
        )

        task_desc = f"Generate exactly {amount} distinct natural, conversational '{category}' messages."
        
        prompt = base_prompt + reminder + (
            f"TASK: {task_desc} "
            f"Return ONLY a JSON object exactly matching this structure: {{\"{category}\": [\"msg1\", ...]}}"
        )

        log_console_debug(f"Sending JSON Batch Request for '{category}':\n{prompt}", category="OLLAMA_IO")

        response = await ollama_client.chat.completions.create(
            model=OLLAMA_MODEL,
            messages=[{"role": "user", "content": prompt}],
            response_format={"type": "json_object"}
        )
        
        raw_content = response.choices[0].message.content
        log_console_debug(f"Received JSON Batch Response for '{category}':\n{raw_content}", category="OLLAMA_IO")
        
        # -------------------------------------------------------------
        # ROBUST JSON PARSING FALLBACK
        # -------------------------------------------------------------
        try:
            data = json.loads(raw_content)
        except json.JSONDecodeError as json_err:
            log_console_debug(f"LLM produced invalid JSON (Error: {json_err}). Attempting regex fallback extraction...", category="ERROR")
            # Forcibly extract lists between brackets [ ... ] and capture all strings
            list_match = re.search(r'\[(.*?)\]', raw_content, re.DOTALL)
            if list_match:
                inner_list = list_match.group(1)
                extracted_msgs = re.findall(r'"(.*?)"(?=\s*[,\]]|\s*$)', inner_list, re.DOTALL)
                # Cleanup escaped quotes that might be left over from the regex
                extracted_msgs = [msg.replace('\\"', '"') for msg in extracted_msgs]
                data = {category: extracted_msgs}
                log_console_debug(f"Regex fallback successfully salvaged {len(extracted_msgs)} messages.", category="SYSTEM")
            else:
                raise Exception(f"Failed to parse or salvage JSON from LLM: {json_err}")
        
        new_msgs = data.get(category, [])
        if not new_msgs and data:
            first_val = list(data.values())[0]
            if isinstance(first_val, list):
                new_msgs = first_val

        if new_msgs:
            clean_msgs = [m for m in new_msgs if m not in DEFAULT_MESSAGES.get(category, [])]
            if clean_msgs:
                random.shuffle(clean_msgs)
                msg_cache.setdefault(category, []).extend(clean_msgs)
                save_json_file(MESSAGE_CACHE_FILE, msg_cache)
                await send_ntfy_debug(f"✅ Auto-refilled {len(clean_msgs)} messages for '{category}'. New pool size: {len(msg_cache[category])}", tags="white_check_mark,floppy_disk")
                pc_last_active = time.time()
                persist_pc_state()
            
    except Exception as e:
        await send_ntfy_debug(f"❌ Failed to auto-refill category '{category}': {e}", priority="high", tags="rotating_light,error")

async def batch_generate_messages(days: int, status_msg=None):
    global pc_last_active
    try:
        await ensure_pc_ready(status_msg)
        pc_last_active = time.time()
        persist_pc_state()
        
        categories = ["morning", "afternoon", "evening", "night", "cleared", "nag_mild", "nag_angry", "nag_boiling", "level_up", "new_lessons"]
        
        for i, cat in enumerate(categories):
            target = bot_state.get("gen_targets", {}).get(cat, 10) * days
            if status_msg:
                try: await status_msg.edit_text(f"📝 Part {i+1}/{len(categories)}: Generating {target} messages for '{cat}'...")
                except: pass
            
            await generate_messages_for_category(cat, target)
        
        if status_msg:
            await status_msg.edit_text("🎉 Success! Generated all message categories! (PC will sleep soon)")
    except Exception as e:
        err = f"❌ Batch generation failed: {e}"
        if status_msg: await status_msg.edit_text(err)

async def get_and_manage_alert_message(category: str):
    global bot_state, msg_cache
    if len(msg_cache.get(category, [])) == 0:
        msg = random.choice(DEFAULT_MESSAGES.get(category, ["<voice preset=\"excited\">ヤッホー</voice>!"]))
        
        current_target = bot_state.get("gen_targets", {}).get(category, 10)
        new_target = current_target + 10
        
        if "gen_targets" not in bot_state: bot_state["gen_targets"] = {}
        bot_state["gen_targets"][category] = new_target
        save_json_file(STATE_FILE, bot_state)
        
        asyncio.create_task(generate_messages_for_category(category, new_target))
    else:
        msg = msg_cache[category].pop(0)
        save_json_file(MESSAGE_CACHE_FILE, msg_cache)
        
    return msg

# ==========================================
# MEDIA HANDLERS
# ==========================================
async def handle_image_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    status_msg = await update.message.reply_text("👁 Maru is looking at your picture... 👁")
    try:
        photo_file = await update.message.photo[-1].get_file()
        photo_bytes = await photo_file.download_as_bytearray()

        user_caption = update.message.caption or "Analyze this image for me, Maru!"
        combined_prompt = f"[System instruction: Keep your classic anime character persona active.] User caption: {user_caption}"

        base64_image = encode_image_to_base64(bytes(photo_bytes))
        contents = [
            types.Part.from_bytes(data=base64.b64decode(base64_image), mime_type="image/jpeg"),
            combined_prompt
        ]

        gemini_response = await call_gemini_with_fallback(model_name="gemini-2.5-flash", contents=contents)

        chat_history = get_chat_session(update.effective_chat.id)
        chat_history.append({"role": "user", "content": f"[Sent an Image] {user_caption}"})
        chat_history.append({"role": "assistant", "content": gemini_response})

        try: await status_msg.delete()
        except: pass

        await send_maru_response_with_sticker(update, update.effective_chat.id, gemini_response, is_update=True)

    except Exception as e:
        await status_msg.edit_text(f"❌ Ah, I got dizzy trying to see that image: {e}")

async def handle_voice_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    status_msg = await update.message.reply_text("👂 Listening closely to your voice, Darling... 🔊")
    try:
        voice_file = await update.message.voice.get_file()
        voice_bytes = await voice_file.download_as_bytearray()

        contents = [
            types.Part.from_bytes(data=bytes(voice_bytes), mime_type="audio/ogg"),
            "Accurately transcribe this audio message into plain English text. Return only the text transcription."
        ]

        transcription = await call_gemini_with_fallback(model_name="gemini-2.5-flash", contents=contents)
        await status_msg.edit_text(f"🗣 *You said:* \"{transcription}\"\n\nLet me think...")
        await process_user_input(update, context, transcription, status_msg)
    except Exception as e:
        await status_msg.edit_text(f"❌ Couldn't hear you clearly over the static: {e}")

async def handle_sticker_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    sticker_id = update.message.sticker.file_id
    await update.message.reply_text(
        f"Here is the exact sticker ID for that sticker:\n\n`{sticker_id}`\n\n"
        f"Tap to copy it, then paste it into your `MARU_STICKERS` dictionary in the script!",
        parse_mode=ParseMode.MARKDOWN
    )

# ==========================================
# TELEGRAM MENU & ALERTS
# ==========================================
async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [
        ["📊 My WaniKani Stats", "🇯🇵 Quick Summary"],
        ["⏰ Next Review", "⚙️ LLM Control"],
        [KeyboardButton(text="🌐 Open WaniKani", web_app={"url": "https://www.wanikani.com/"})],
        ["❓ Help"]
    ]
    reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)

    welcome_text = (
        "Yaho~! I'm 丸 (Maru) 🦀✨\n\n"
        "I'm your personal WaniKani assistant and Japanese tutor! "
        "Use the buttons below if you wanna check your stats."
    )
    await update.message.reply_text(welcome_text, reply_markup=reply_markup, parse_mode=ParseMode.MARKDOWN)

async def show_llm_menu(update: Update):
    status_icon = "🟢 ON" if bot_state["llm_auto_run"] else "🛑 OFF"

    keyboard = [
        [InlineKeyboardButton(f"Toggle Auto-Run (Currently: {status_icon})", callback_data="toggle_llm")],
        [InlineKeyboardButton("Generate Cache (1 Day)", callback_data="gen_1")],
        [InlineKeyboardButton("Generate Cache (3 Days)", callback_data="gen_3")],
        [InlineKeyboardButton("Generate Cache (7 Days)", callback_data="gen_7")],
        [InlineKeyboardButton("Cache Stats", callback_data="cache_stats")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    text = "⚙️ **LLM & PC Control Panel**"

    if update.message: await update.message.reply_text(text, reply_markup=reply_markup, parse_mode=ParseMode.MARKDOWN)
    elif update.callback_query: await update.callback_query.edit_message_text(text, reply_markup=reply_markup, parse_mode=ParseMode.MARKDOWN)

async def debug_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global bot_state
    args = context.args
    
    if not args:
        status = "ENABLED" if bot_state.get("debug_enabled", True) else "DISABLED"
        await update.message.reply_text(
            f"🛠 **Debug Log System**\n"
            f"Diagnostics Dashboard Web Panel is serving live logs.\n"
            f"Verbose logs terminal output is: **{status}**\n\n"
            f"Use `/debug on` or `/debug off` to toggle.",
            parse_mode=ParseMode.MARKDOWN
        )
        return

    command = args[0].lower()
    if command == "on":
        bot_state["debug_enabled"] = True
        save_json_file(STATE_FILE, bot_state)
        await update.message.reply_text("✅ Debug logs enabled!")
    elif command == "off":
        bot_state["debug_enabled"] = False
        save_json_file(STATE_FILE, bot_state)
        await update.message.reply_text("💤 Debug logs disabled. Silent mode active.")
    else:
        await update.message.reply_text("❌ Invalid parameter. Use `/debug on` or `/debug off`.")

async def shutdown_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global pc_state
    is_up = await is_pc_on_port(PC_IP_ADDRESS, 22)
    if not is_up:
        await update.message.reply_text("❌ Stupid-Darling! The PC is already offline, what are you trying to kill?")
        return
        
    status_msg = await update.message.reply_text("🔌 Sending safe shutdown signals to remote PC...")
    await execute_pc_shutdown(context)
    await status_msg.edit_text("💤 Shutdown sequence dispatched! Sleep tight, dummy!")

async def llm_callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global pc_last_active, pc_shutdown_pending, pc_shutdown_alert_msg_id, maru_memory
    query = update.callback_query
    await query.answer()

    if query.data == "toggle_llm":
        bot_state["llm_auto_run"] = not bot_state["llm_auto_run"]
        save_json_file(STATE_FILE, bot_state)
        await show_llm_menu(update)
        
    elif query.data.startswith("gen_"):
        days = int(query.data.split("_")[1])
        status_msg = await query.message.reply_text(f"🚀 Initializing batch generation for {days} days...")
        asyncio.create_task(batch_generate_messages(days, status_msg))
        
    elif query.data == "cache_stats":
        targets = bot_state.get("gen_targets", {})
        stats = (
            f"📦 **Current Cache Stats & Dynamic Batch Targets:**\n"
            f"🌅 Morning: {len(msg_cache.get('morning', []))} msgs _(Target: {targets.get('morning', 10)})_\n"
            f"☀️ Afternoon: {len(msg_cache.get('afternoon', []))} msgs _(Target: {targets.get('afternoon', 10)})_\n"
            f"🌇 Evening: {len(msg_cache.get('evening', []))} msgs _(Target: {targets.get('evening', 10)})_\n"
            f"🌙 Night: {len(msg_cache.get('night', []))} msgs _(Target: {targets.get('night', 10)})_\n"
            f"🎉 Cleared: {len(msg_cache.get('cleared', []))} msgs _(Target: {targets.get('cleared', 10)})_\n"
            f"😤 Nag Mild: {len(msg_cache.get('nag_mild', []))} msgs _(Target: {targets.get('nag_mild', 10)})_\n"
            f"💢 Nag Angry: {len(msg_cache.get('nag_angry', []))} msgs _(Target: {targets.get('nag_angry', 10)})_\n"
            f"🤬 Nag Boiling: {len(msg_cache.get('nag_boiling', []))} msgs _(Target: {targets.get('nag_boiling', 10)})_\n"
            f"🌟 Level Up: {len(msg_cache.get('level_up', []))} msgs _(Target: {targets.get('level_up', 10)})_\n"
            f"📖 New Lessons: {len(msg_cache.get('new_lessons', []))} msgs _(Target: {targets.get('new_lessons', 10)})_"
        )
        await query.message.reply_text(stats, parse_mode=ParseMode.MARKDOWN)

    # ---------------------------------------------------------
    # SNOOZE / SHUT UP CONTROLS
    # ---------------------------------------------------------
    elif query.data.startswith("snooze_"):
        hours = int(query.data.split("_")[1])
        maru_memory["snooze_until"] = time.time() + (hours * 3600)
        save_json_file(MEMORY_FILE, maru_memory)
        await query.edit_message_text(f"😤 Hmph! Fine! I'll stay completely quiet for {hours} hours. Don't come crying when you miss your reviews! 💔")

    # ---------------------------------------------------------
    # INTERACTIVE SHUTDOWN BUTTON HANDLERS
    # ---------------------------------------------------------
    elif query.data == "shutdown_now":
        await query.edit_message_text("🔌 Initiating safe shutdown now!")
        await execute_pc_shutdown(context)

    elif query.data == "shutdown_cancel":
        pc_last_active = time.time()
        pc_shutdown_pending = False
        await write_pc_boot_source("USER")
        persist_pc_state()
        try:
            await query.edit_message_text("✅ Shutdown cancelled! PC boot source updated to USER. I won't shut it down anymore today! 💖")
        except Exception: pass

async def fetch_and_send_stats(update: Update, quick_mode: bool = False):
    loading_msg = await update.message.reply_text("🔄 Fetching your latest data from the Crabigator...")
    try:
        username, level = await asyncio.to_thread(get_wanikani_user_info, WANIKANI_API_TOKEN)
        summary = await asyncio.to_thread(get_wanikani_summary, WANIKANI_API_TOKEN)
        passed_k, total_k = await asyncio.to_thread(get_level_progress, WANIKANI_API_TOKEN, level)

        next_review_str = "No upcoming reviews today"
        if summary['next_review_time']:
            now = datetime.now(timezone.utc)
            diff = summary['next_review_time'] - now
            hours, remainder = divmod(int(diff.total_seconds()), 3600)
            minutes, _ = divmod(remainder, 60)
            time_str = f"in {hours}h {minutes}m" if hours > 0 else f"in {minutes}m"
            next_review_str = f"{summary['next_review_count']} items {time_str}"

        progress_str = "Max Level"
        if total_k > 0:
            percentage = int((passed_k / total_k) * 100)
            progress_str = f"{passed_k}/{total_k} Kanji passed ({percentage}%)"

        message = (
            f"🦀 <b>WaniKani Stats for {username}</b> 🦀\n\n"
            f"📊 <b>Level:</b> {level}\n"
            f"🚀 <b>Level Progress:</b> {progress_str}\n\n"
            f"📖 <b>Lessons Available:</b> {summary['lessons']}\n"
            f"🔥 <b>Reviews Available:</b> {summary['reviews']}\n"
            f"⏰ <b>Next Review:</b> {next_review_str}\n"
            f"📅 <b>Upcoming (Next 24h):</b> {summary['reviews_next_24h']} reviews\n\n"
        )

        if not quick_mode:
            await loading_msg.edit_text("🔄 Crunching SRS Distribution numbers...")
            srs = await asyncio.to_thread(get_srs_distribution, WANIKANI_API_TOKEN)
            message += (
                f"📈 <b>SRS Distribution:</b>\n"
                f"🌱 Apprentice: {srs['Apprentice']}\n"
                f"🌿 Guru: {srs['Guru']}\n"
                f"🌳 Master: {srs['Master']}\n"
                f"🦉 Enlightened: {srs['Enlightened']}\n"
                f"🔥 Burned: {srs['Burned']}\n\n"
            )

        message += "Keep up the great work! 頑張って！"
        await loading_msg.edit_text(message, parse_mode=ParseMode.HTML)

    except Exception as e:
        await loading_msg.edit_text(f"❌ Error fetching stats: {str(e)}")

async def handle_text_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    if text == "📊 My WaniKani Stats":
        await fetch_and_send_stats(update, quick_mode=False)
        return
    elif text == "🇯🇵 Quick Summary":
        await fetch_and_send_stats(update, quick_mode=True)
        return
    elif text == "⏰ Next Review":
        loading_msg = await update.message.reply_text("⏳ Checking the clock...")
        try:
            summary = await asyncio.to_thread(get_wanikani_summary, WANIKANI_API_TOKEN)
            next_time = summary['next_review_time']
            if next_time:
                now = datetime.now(timezone.utc)
                diff = next_time - now
                hours, remainder = divmod(int(diff.total_seconds()), 3600)
                minutes, _ = divmod(remainder, 60)
                time_str = f"in {hours}h {minutes}m" if hours > 0 else f"in {minutes}m"
                await loading_msg.edit_text(f"⏰ Your next review is **{time_str}**! You'll have {summary['next_review_count']} items waiting. ✨", parse_mode=ParseMode.MARKDOWN)
            else:
                await loading_msg.edit_text("🎉 You have absolutely no upcoming reviews today! Take a break! 🍵", parse_mode=ParseMode.MARKDOWN)
        except Exception as e:
            await loading_msg.edit_text(f"❌ Error checking schedule: {str(e)}")
        return
    elif text == "⚙️ LLM Control":
        await show_llm_menu(update)
        return
    elif text == "❓ Help":
        await update.message.reply_text("Use the buttons to navigate!")
        return

    status_msg = await update.message.reply_text("🤔 起動中... (Waking PC if needed...)")
    await process_user_input(update, context, text, status_msg)

async def scheduled_midnight_batch(context: ContextTypes.DEFAULT_TYPE):
    log_console_debug("🔄 [Background Task] Midnight Batch Pre-generation Executing...", category="SYSTEM")
    if not bot_state["llm_auto_run"]: return
    await context.bot.send_message(chat_id=TELEGRAM_CHAT_ID, text="🕛 Midnight! Waking PC to pre-generate tomorrow's messages...")
    await batch_generate_messages(days=1)

async def check_wanikani_alerts(context: ContextTypes.DEFAULT_TYPE = None, bot=None):
    log_console_debug("🔄 [Background Task] WaniKani Alert Check Executing...", category="WaniKani")
    active_bot = bot if bot else (context.bot if context else None)
    if not active_bot:
        log_console_debug("No bot instance available for WaniKani alerts.", category="ERROR")
        return

    global maru_memory
    try:
        username, current_level = await asyncio.to_thread(get_wanikani_user_info, WANIKANI_API_TOKEN)
        summary = await asyncio.to_thread(get_wanikani_summary, WANIKANI_API_TOKEN)
        current_reviews = summary.get('reviews', 0)
        current_lessons = summary.get('lessons', 0)

        now_dt = datetime.now()
        current_timestamp = now_dt.timestamp()
        current_time = now_dt.time()
        hour = now_dt.hour

        if 5 <= hour < 12: time_cat = "morning"
        elif 12 <= hour < 17: time_cat = "afternoon"
        elif 17 <= hour < 21: time_cat = "evening"
        else: time_cat = "night"

        # ---------------------------------------------------------
        # QUIET HOURS AND SNOOZE CHECK
        # ---------------------------------------------------------
        is_quiet_hours = current_time >= dt_time(22, 30) or current_time < dt_time(8, 0)
        is_snoozed = current_timestamp < maru_memory.get("snooze_until", 0)

        last_reviews = maru_memory.get("last_reviews")
        last_level = maru_memory.get("last_level")
        last_lessons = maru_memory.get("last_lessons")
        last_nag_time = maru_memory.get("last_nag_time")
        reviews_appeared_time = maru_memory.get("reviews_appeared_time")

        if last_level is None: last_level = current_level
        if last_lessons is None: last_lessons = 0
        if last_reviews is None: last_reviews = 0

        # If we are in quiet hours or snoozed, silently update trackers and ABORT any nags
        if is_quiet_hours or is_snoozed:
            maru_memory["last_reviews"] = current_reviews
            maru_memory["last_level"] = current_level
            maru_memory["last_lessons"] = current_lessons
            save_json_file(MEMORY_FILE, maru_memory)
            return

        alerts = []  # format: tuples of (message_str, is_nag_bool)

        if current_reviews >= 50:
            nag_interval = 10 * 60    # 10 minutes
            nag_cat = "nag_boiling"
        elif current_reviews >= 20:
            nag_interval = 20 * 60    # 20 minutes
            nag_cat = "nag_angry"
        else:
            nag_interval = 40 * 60    # 40 minutes
            nag_cat = "nag_mild"

        if current_reviews > 0:
            if reviews_appeared_time is None:
                reviews_appeared_time = current_timestamp
                last_nag_time = current_timestamp
        else:
            reviews_appeared_time = None
            last_nag_time = None

        review_alert_sent = False

        # 1. NEW REVIEWS / MILESTONE CROSSING
        if current_reviews > last_reviews:
            if current_reviews >= 50 and last_reviews < 50:
                msg = await get_and_manage_alert_message("nag_boiling")
                alerts.append((f"{msg}\n\n_System: Passed 50 reviews. (Total: {current_reviews})_", True))
                last_nag_time = current_timestamp
            elif current_reviews >= 20 and last_reviews < 20:
                msg = await get_and_manage_alert_message("nag_angry")
                alerts.append((f"{msg}\n\n_System: Passed 20 reviews. (Total: {current_reviews})_", True))
                last_nag_time = current_timestamp
            else:
                msg = await get_and_manage_alert_message(time_cat)
                alerts.append((f"{msg}\n\n_System: Review Alert. (Total: {current_reviews})_", True))
            
            reviews_appeared_time = current_timestamp
            review_alert_sent = True

        elif current_reviews < last_reviews and current_reviews > 0:
            last_nag_time = current_timestamp

        elif current_reviews == 0 and last_reviews > 0:
            msg = await get_and_manage_alert_message("cleared")
            alerts.append((msg, False))
            reviews_appeared_time = None
            last_nag_time = None
            review_alert_sent = True

        # 2. CONTINUOUS NAGGING CHECK
        if current_reviews > 0 and not review_alert_sent and last_nag_time is not None:
            time_since_nag = current_timestamp - last_nag_time
            if time_since_nag >= nag_interval:
                msg = await get_and_manage_alert_message(nag_cat)
                if "{kitsu_activity}" in msg:
                    activities = await asyncio.to_thread(get_kitsu_activity, KITSU_IDENTIFIER)
                    if activities:
                        msg = msg.replace("{kitsu_activity}", random.choice(activities))
                    else:
                        msg = msg.replace("{kitsu_activity}", "slacking off")
                        
                alerts.append((f"{msg}\n\n_System: Nag timer reached. (Total: {current_reviews})_", True))
                last_nag_time = current_timestamp

        # 3. OTHER ALERTS (Lessons & Levels)
        if current_level > last_level:
            msg = await get_and_manage_alert_message("level_up")
            alerts.append((msg, False))

        if current_lessons > last_lessons and last_lessons == 0:
            msg = await get_and_manage_alert_message("new_lessons")
            alerts.append((msg, False))

        maru_memory["last_reviews"] = current_reviews
        maru_memory["last_level"] = current_level
        maru_memory["last_lessons"] = current_lessons
        maru_memory["last_nag_time"] = last_nag_time
        maru_memory["reviews_appeared_time"] = reviews_appeared_time
        save_json_file(MEMORY_FILE, maru_memory)

        # ---------------------------------------------------------
        # DISPATCH MESSAGES & ATTACH SNOOZE KEYBOARD TO NAGS
        # ---------------------------------------------------------
        nag_keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("🤫 Mute for 2 hours", callback_data="snooze_2")],
            [InlineKeyboardButton("💤 Sleep for 8 hours", callback_data="snooze_8")]
        ])

        for alert_msg, is_nag in alerts:
            reply_markup = nag_keyboard if is_nag else None
            await send_maru_response_with_sticker(active_bot, TELEGRAM_CHAT_ID, alert_msg, is_update=False, reply_markup=reply_markup)

    except Exception as e:
        print(f"Background alert check failed: {e}")

# ==========================================
# DIAGNOSTIC TEST RUNNERS
# ==========================================
async def run_test_wanikani():
    try:
        log_console_debug("🧪 Testing WaniKani API...", category="TEST")
        username, level = await asyncio.to_thread(get_wanikani_user_info, WANIKANI_API_TOKEN)
        summary = await asyncio.to_thread(get_wanikani_summary, WANIKANI_API_TOKEN)
        log_console_debug(f"✅ WaniKani Test Success: Found user '{username}' at Level {level}. Current Reviews: {summary.get('reviews')}", category="TEST")
    except Exception as e:
        log_console_debug(f"❌ WaniKani Test Failed: {e}", category="ERROR")

async def run_test_kitsu():
    try:
        log_console_debug("🧪 Testing Kitsu API...", category="TEST")
        activities = await asyncio.to_thread(get_kitsu_activity, KITSU_IDENTIFIER)
        log_console_debug(f"✅ Kitsu Test Success: Current activity array -> {activities}", category="TEST")
    except Exception as e:
        log_console_debug(f"❌ Kitsu Test Failed: {e}", category="ERROR")

async def run_test_ollama():
    try:
        log_console_debug("🧪 Testing Ollama Brain connection...", category="TEST")
        response = await ollama_client.chat.completions.create(
            model=OLLAMA_MODEL,
            messages=[{"role": "user", "content": "Reply with exactly one word: 'Operational'."}],
            temperature=0.1
        )
        msg = response.choices[0].message.content
        log_console_debug(f"✅ Ollama Test Success! Response: '{msg}'", category="TEST")
    except Exception as e:
        log_console_debug(f"❌ Ollama Test Failed: {e}", category="ERROR")

async def run_test_voicevox():
    try:
        log_console_debug("🧪 Testing VoiceVox API Engine...", category="TEST")
        params = {'text': 'テスト', 'speaker': VOICEVOX_SPEAKER_ID}
        query_res = await asyncio.to_thread(requests.post, f"{VOICEVOX_BASE_URL}/audio_query", params=params)
        query_res.raise_for_status()
        log_console_debug("✅ VoiceVox Test Success: Audio Synthesis Query generated properly.", category="TEST")
    except Exception as e:
        log_console_debug(f"❌ VoiceVox Test Failed: {e}", category="ERROR")

async def run_test_telegram():
    if not GLOBAL_BOT:
        log_console_debug("❌ Telegram bot instance not ready yet.", category="ERROR")
        return
    try:
        log_console_debug("🧪 Sending Test Message to Telegram...", category="TEST")
        await send_maru_response_with_sticker(
            GLOBAL_BOT, 
            TELEGRAM_CHAT_ID, 
            "🧪 *Test Alert!* My systems are fully operational, Stupid-Darling! <sticker:smug>", 
            is_update=False
        )
        log_console_debug("✅ Telegram Send Message Test Success.", category="TEST")
    except Exception as e:
        log_console_debug(f"❌ Telegram Test Failed: {e}", category="ERROR")

async def run_test_gemini_image():
    log_console_debug("🧪 Testing Gemini Image Recognition...", category="TEST")
    if not GEMINI_AVAILABLE:
        log_console_debug("❌ Gemini SDK not installed.", category="ERROR")
        return
    try:
        # Transparent 1x1 base64 test image
        png_b64 = "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAACklEQVR4nGMAAQAABQABDQottAAAAABJRU5ErkJggg=="
        contents = [
            types.Part.from_bytes(data=base64.b64decode(png_b64), mime_type="image/png"),
            "This is a test image. Reply with exactly the words: 'Image OK'."
        ]
        res = await call_gemini_with_fallback("gemini-2.5-flash", contents)
        log_console_debug(f"✅ Gemini Image Success! Response: '{res}'", category="TEST")
    except Exception as e:
        log_console_debug(f"❌ Gemini Image Test Failed: {e}", category="ERROR")

async def run_test_gemini_voice():
    log_console_debug("🧪 Testing Gemini Voice Recognition...", category="TEST")
    if not GEMINI_AVAILABLE:
        log_console_debug("❌ Gemini SDK not installed.", category="ERROR")
        return
    try:
        # Minimal silent WAV header payload
        wav_hex = "524946462400000057415645666d7420100000000100010044ac000088580100020010006461746100000000"
        contents = [
            types.Part.from_bytes(data=bytes.fromhex(wav_hex), mime_type="audio/wav"),
            "This is a test audio file. Reply with exactly the words: 'Voice OK'."
        ]
        res = await call_gemini_with_fallback("gemini-2.5-flash", contents)
        log_console_debug(f"✅ Gemini Voice Success! Response: '{res}'", category="TEST")
    except Exception as e:
        log_console_debug(f"❌ Gemini Voice Test Failed: {e}", category="ERROR")

async def force_trigger_alert(category: str):
    if not GLOBAL_BOT:
        log_console_debug("❌ Telegram bot not ready.", category="ERROR")
        return
    try:
        log_console_debug(f"🧪 Forcing specific alert category: '{category}'", category="TEST")
        msg = await get_and_manage_alert_message(category)
        await send_maru_response_with_sticker(GLOBAL_BOT, TELEGRAM_CHAT_ID, msg, is_update=False)
        log_console_debug(f"✅ Successfully forced '{category}' alert to Telegram.", category="TEST")
    except Exception as e:
        log_console_debug(f"❌ Failed to force alert '{category}': {e}", category="ERROR")

# ==========================================
# ASYNC DIAGNOSTIC DASHBOARD HTTP SERVER
# ==========================================
HTML_TEMPLATE = """<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Maru Diagnostic Hub</title>
    <link href="https://cdn.jsdelivr.net/npm/tailwindcss@2.2.19/dist/tailwind.min.css" rel="stylesheet">
    <style>
        body { background-color: #0f172a; color: #f8fafc; font-family: ui-sans-serif, system-ui, -apple-system; }
        .terminal { font-family: 'Courier New', Courier, monospace; background-color: #020617; }
        .log-PC { color: #38bdf8; }
        .log-WaniKani { color: #f43f5e; }
        .log-OLLAMA { color: #a855f7; }
        .log-OLLAMA_IO { color: #d946ef; } /* Pink color for distinct I/O logging */
        .log-SYSTEM { color: #10b981; }
        .log-ERROR { color: #ef4444; }
        .log-TEST { color: #facc15; }
    </style>
</head>
<body class="p-6">
    <div class="max-w-7xl mx-auto">
        <div class="flex justify-between items-center mb-8 border-b border-slate-800 pb-4">
            <div>
                <h1 class="text-3xl font-extrabold text-pink-500 flex items-center">
                    丸 Diagnostics Hub <span class="ml-2 text-xs px-2 py-1 bg-pink-500/10 text-pink-400 rounded-full border border-pink-500/20">Active Session</span>
                </h1>
                <p class="text-sm text-slate-400 mt-1">Local Real-time Web Diagnostics Console</p>
            </div>
            <div class="flex gap-4">
                <button onclick="triggerAction('debug/toggle')" class="bg-slate-800 border border-slate-700 hover:bg-slate-700 px-4 py-2 rounded-lg text-sm transition font-semibold">Toggle Console Verbosity</button>
                <button onclick="triggerAction('pc/wakeup')" class="bg-emerald-600 hover:bg-emerald-500 text-white px-4 py-2 rounded-lg text-sm transition font-bold">📡 Wake PC (WoL)</button>
                <button onclick="triggerAction('pc/shutdown')" class="bg-red-600 hover:bg-red-500 text-white px-4 py-2 rounded-lg text-sm transition font-bold">🔌 Force Shutdown</button>
            </div>
        </div>
        <div class="grid grid-cols-1 md:grid-cols-4 gap-6 mb-8">
            <div class="bg-slate-900/60 border border-slate-800 p-5 rounded-2xl">
                <p class="text-xs text-slate-400 uppercase tracking-wider font-semibold">PC Memory State</p>
                <h2 id="metric-pc-state" class="text-2xl font-bold mt-2 text-slate-200">Loading...</h2>
                <div class="flex items-center gap-2 mt-3">
                    <span id="metric-pc-led" class="h-2 w-2 rounded-full bg-slate-500"></span>
                    <span id="metric-pc-source" class="text-xs text-slate-400">Boot: Unknown</span>
                </div>
            </div>
            <div class="bg-slate-900/60 border border-slate-800 p-5 rounded-2xl">
                <p class="text-xs text-slate-400 uppercase tracking-wider font-semibold">PC Active Idle</p>
                <h2 id="metric-idle" class="text-2xl font-bold mt-2 text-slate-200">Loading...</h2>
                <p class="text-xs text-slate-400 mt-3">Timeout limit: 600 seconds</p>
            </div>
            <div class="bg-slate-900/60 border border-slate-800 p-5 rounded-2xl">
                <p class="text-xs text-slate-400 uppercase tracking-wider font-semibold">Auto-Shutdown Warning</p>
                <h2 id="metric-pending" class="text-2xl font-bold mt-2 text-slate-200">Loading...</h2>
                <p id="metric-pending-details" class="text-xs text-slate-400 mt-3">Idle shutdown deactivated</p>
            </div>
            <div class="bg-slate-900/60 border border-slate-800 p-5 rounded-2xl">
                <p class="text-xs text-slate-400 uppercase tracking-wider font-semibold">System Diagnostics</p>
                <h2 id="metric-clients" class="text-2xl font-bold mt-2 text-pink-500">0 connected</h2>
                <p class="text-xs text-slate-400 mt-3">HTTP Broadcast Clients (SSE)</p>
            </div>
        </div>
        <div class="grid grid-cols-1 lg:grid-cols-3 gap-8">
            <div class="lg:col-span-2 flex flex-col h-[680px] bg-slate-950 border border-slate-800 rounded-3xl overflow-hidden shadow-2xl">
                <div class="bg-slate-900/80 px-6 py-4 border-b border-slate-800 flex justify-between items-center">
                    <div class="flex items-center gap-2">
                        <span class="h-3 w-3 rounded-full bg-pink-500 animate-pulse"></span>
                        <h3 class="font-bold text-slate-300">Live Telemetry Terminal</h3>
                    </div>
                    <div class="flex items-center gap-3">
                        <select id="log-filter" class="bg-slate-950 border border-slate-800 text-xs px-3 py-1.5 rounded-lg text-slate-300 outline-none">
                            <option value="ALL">All Categories</option>
                            <option value="PC">PC Operations</option>
                            <option value="WaniKani">WaniKani</option>
                            <option value="OLLAMA">Ollama / LLM</option>
                            <option value="OLLAMA_IO">LLM I/O (Prompts & Responses)</option>
                            <option value="SYSTEM">System Hooks</option>
                            <option value="TEST">Test Results</option>
                            <option value="ERROR">Errors Only</option>
                        </select>
                        <button onclick="clearTerminal()" class="text-xs text-slate-400 hover:text-slate-200 bg-slate-800 px-3 py-1.5 rounded-lg border border-slate-700 transition">Clear Screen</button>
                    </div>
                </div>
                <div id="log-container" class="terminal flex-1 p-6 overflow-y-auto text-sm leading-relaxed whitespace-pre-wrap"></div>
            </div>
            
            <div class="flex flex-col gap-6">
                <!-- Cache Panel -->
                <div class="bg-slate-900/40 border border-slate-800 rounded-3xl p-6 shadow-2xl">
                    <div class="flex justify-between items-center mb-6">
                        <h3 class="font-bold text-lg text-slate-200">Manage Caches</h3>
                        <div class="flex gap-2">
                            <button onclick="triggerAction('cache/generate')" class="bg-pink-600 hover:bg-pink-500 text-white text-xs px-3 py-1.5 rounded-lg transition font-semibold">Refill All</button>
                            <button onclick="triggerAction('cache/empty')" class="bg-red-600 hover:bg-red-500 text-white text-xs px-3 py-1.5 rounded-lg transition font-semibold">Empty All</button>
                        </div>
                    </div>
                    <div id="cache-metrics-list" class="space-y-4 max-h-60 overflow-y-auto pr-2">
                        <p class="text-sm text-slate-400">Loading current metrics...</p>
                    </div>
                </div>
                
                <!-- Function Tester Panel -->
                <div class="bg-slate-900/40 border border-slate-800 rounded-3xl p-6 shadow-2xl flex-1">
                    <h3 class="font-bold text-lg text-slate-200 mb-4 flex items-center gap-2">
                        <span>🧪</span> Function Testers
                    </h3>
                    <div class="grid grid-cols-2 gap-3 mb-3">
                        <button onclick="triggerAction('test/wanikani')" class="bg-indigo-600 hover:bg-indigo-500 text-white text-xs px-3 py-2.5 rounded-lg transition font-semibold text-left flex justify-between shadow-lg">
                            WaniKani API <span>▶</span>
                        </button>
                        <button onclick="triggerAction('test/kitsu')" class="bg-orange-600 hover:bg-orange-500 text-white text-xs px-3 py-2.5 rounded-lg transition font-semibold text-left flex justify-between shadow-lg">
                            Kitsu API <span>▶</span>
                        </button>
                        <button onclick="triggerAction('test/ollama')" class="bg-purple-600 hover:bg-purple-500 text-white text-xs px-3 py-2.5 rounded-lg transition font-semibold text-left flex justify-between shadow-lg">
                            Ollama Brain <span>▶</span>
                        </button>
                        <button onclick="triggerAction('test/voicevox')" class="bg-green-600 hover:bg-green-500 text-white text-xs px-3 py-2.5 rounded-lg transition font-semibold text-left flex justify-between shadow-lg">
                            VoiceVox API <span>▶</span>
                        </button>
                        <button onclick="triggerAction('test/telegram')" class="bg-blue-600 hover:bg-blue-500 text-white text-xs px-3 py-2.5 rounded-lg transition font-semibold text-left flex justify-between shadow-lg">
                            Telegram Msg <span>▶</span>
                        </button>
                        <button onclick="triggerAction('test/gemini_image')" class="bg-teal-600 hover:bg-teal-500 text-white text-xs px-3 py-2.5 rounded-lg transition font-semibold text-left flex justify-between shadow-lg">
                            Image Rec. <span>▶</span>
                        </button>
                        <button onclick="triggerAction('test/gemini_voice')" class="bg-cyan-600 hover:bg-cyan-500 text-white text-xs px-3 py-2.5 rounded-lg transition font-semibold text-left flex justify-between shadow-lg flex-col col-span-2">
                            <div class="flex justify-between w-full">Voice Rec. <span>▶</span></div>
                        </button>
                    </div>
                    
                    <div class="flex gap-2 mt-4">
                        <select id="force-alert-category" class="bg-slate-900 border border-slate-700 text-xs px-2 py-2 rounded-lg text-slate-300 w-1/2 outline-none">
                            <option value="morning">Morning Alert</option>
                            <option value="afternoon">Afternoon Alert</option>
                            <option value="evening">Evening Alert</option>
                            <option value="night">Night Alert</option>
                            <option value="nag_mild">Nag (Mild)</option>
                            <option value="nag_angry">Nag (Angry)</option>
                            <option value="nag_boiling">Nag (Boiling)</option>
                            <option value="cleared">All Cleared</option>
                            <option value="level_up">Level Up</option>
                            <option value="new_lessons">New Lessons</option>
                        </select>
                        <button onclick="forceAlert()" class="bg-rose-600 hover:bg-rose-500 text-white text-xs px-3 py-2 rounded-lg transition font-semibold w-1/2 flex justify-between items-center shadow-lg">
                            Force Alert <span>▶</span>
                        </button>
                    </div>
                    <p class="text-xs text-slate-500 mt-4 text-center">Select an alert type to dispatch directly to Telegram.</p>
                </div>
            </div>
        </div>
    </div>
    <script>
        const logContainer = document.getElementById('log-container');
        const filterSelect = document.getElementById('log-filter');
        let rawLogHistory = [];
        const eventSource = new EventSource('/events');

        eventSource.onmessage = function(event) {
            const logItem = JSON.parse(event.data);
            rawLogHistory.push(logItem);
            if (rawLogHistory.length > 200) rawLogHistory.shift();
            renderLogs();
        };

        eventSource.onerror = function() {
            appendLog({ time: new Date().toLocaleTimeString(), category: "ERROR", message: "Disconnect or error reading SSE Stream. Reconnecting..." });
        };

        function renderLogs() {
            const filterVal = filterSelect.value;
            logContainer.innerHTML = '';
            
            const filtered = rawLogHistory.filter(item => {
                if (filterVal === 'ALL') return true;
                return item.category === filterVal;
            });

            filtered.forEach(item => {
                const line = document.createElement('div');
                line.className = 'mb-1.5 border-b border-slate-900/10 pb-0.5';
                line.innerHTML = `<span class="text-slate-500">[${item.time}]</span> <span class="log-${item.category} font-semibold">[${item.category}]</span> <span class="text-slate-300">${escapeHtml(item.message)}</span>`;
                logContainer.appendChild(line);
            });
            logContainer.scrollTop = logContainer.scrollHeight;
        }

        function appendLog(item) {
            rawLogHistory.push(item);
            renderLogs();
        }

        function clearTerminal() {
            rawLogHistory = [];
            renderLogs();
        }

        filterSelect.addEventListener('change', renderLogs);

        function escapeHtml(text) {
            return text.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;").replace(/'/g, "&#039;");
        }

        async function triggerAction(endpoint) {
            try {
                const response = await fetch(`/api/${endpoint}`, { method: 'POST' });
                const resData = await response.json();
                if (resData.status === 'ok') console.log(`Action API succeeded: ${endpoint}`);
                else alert(`Error executing action: ${resData.reason}`);
            } catch (err) { console.error("Action fetch execution error:", err); }
        }

        function forceAlert() {
            const cat = document.getElementById('force-alert-category').value;
            triggerAction('test/force_alert/' + cat);
        }

        async function fetchSystemState() {
            try {
                const response = await fetch('/api/metrics');
                const data = await response.json();
                
                const pcStateElem = document.getElementById('metric-pc-state');
                const pcLedElem = document.getElementById('metric-pc-led');
                const pcSourceElem = document.getElementById('metric-pc-source');
                
                pcStateElem.innerText = data.pc_state;
                if (data.pc_state === 'ON') {
                    pcStateElem.className = 'text-2xl font-bold mt-2 text-emerald-400';
                    pcLedElem.className = 'h-2 w-2 rounded-full bg-emerald-500 animate-pulse';
                } else {
                    pcStateElem.className = 'text-2xl font-bold mt-2 text-slate-400';
                    pcLedElem.className = 'h-2 w-2 rounded-full bg-red-500';
                }
                pcSourceElem.innerText = `Boot Source: ${data.pc_started_by_bot ? 'BOT (WOL)' : 'USER (Manual)'}`;

                document.getElementById('metric-idle').innerText = `${data.time_idle_s}s`;

                const pendingTitle = document.getElementById('metric-pending');
                const pendingDetails = document.getElementById('metric-pending-details');
                if (data.pc_shutdown_pending) {
                    pendingTitle.innerText = `⚠️ ${data.pc_shutdown_remaining}s`;
                    pendingTitle.className = "text-2xl font-bold mt-2 text-yellow-500 animate-pulse";
                    pendingDetails.innerText = "WARNING: Interactive grace period ACTIVE!";
                } else {
                    pendingTitle.innerText = "Deactivated";
                    pendingTitle.className = "text-2xl font-bold mt-2 text-slate-400";
                    pendingDetails.innerText = data.pc_started_by_bot ? "Monitored (Bot initiated)" : "Bypassed (User manual active)";
                }

                document.getElementById('metric-clients').innerText = `${data.sse_clients} connected`;

                const cacheContainer = document.getElementById('cache-metrics-list');
                cacheContainer.innerHTML = '';
                
                for (const [cat, size] of Object.entries(data.cache_sizes)) {
                    const target = data.gen_targets[cat] || 10;
                    const percent = Math.min(100, Math.floor((size / target) * 100));
                    
                    const card = document.createElement('div');
                    card.className = 'bg-slate-950/60 p-3 rounded-xl border border-slate-800/80 flex flex-col gap-2';
                    card.innerHTML = `
                        <div class="flex justify-between items-center text-xs">
                            <span class="font-bold text-slate-300 uppercase">${cat}</span>
                            <span class="text-slate-400 font-semibold">${size} / ${target} msgs</span>
                        </div>
                        <div class="w-full bg-slate-800 h-2 rounded-full overflow-hidden">
                            <div class="bg-pink-500 h-full rounded-full" style="width: ${percent}%"></div>
                        </div>
                    `;
                    cacheContainer.appendChild(card);
                }

            } catch (err) {}
        }
        setInterval(fetchSystemState, 1500);
        fetchSystemState();
    </script>
</body>
</html>
"""

async def start_diagnostic_server():
    server = await asyncio.start_server(handle_diagnostic_request, "0.0.0.0", DIAG_PORT)
    addr = server.sockets[0].getsockname()
    log_console_debug(f"Diagnostics HTTP Web Server online at http://{addr[0]}:{addr[1]}", category="SYSTEM")
    async with server:
        await server.serve_forever()

async def handle_diagnostic_request(reader, writer):
    global pc_state, pc_last_active, pc_started_by_bot, pc_shutdown_pending, pc_shutdown_alert_msg_id, msg_cache, bot_state
    try:
        header_data = await reader.readuntil(b"\r\n\r\n")
    except Exception:
        try: writer.close()
        except: pass
        return

    req_str = header_data.decode('utf-8', errors='ignore')
    lines = req_str.split("\r\n")
    if not lines or not lines[0]:
        try: writer.close()
        except: pass
        return

    request_line = lines[0].split(" ")
    if len(request_line) < 2:
        try: writer.close()
        except: pass
        return

    method, path = request_line[0], request_line[1]

    if method == "GET" and path == "/events":
        response_headers = (
            "HTTP/1.1 200 OK\r\n"
            "Content-Type: text/event-stream\r\n"
            "Cache-Control: no-cache\r\n"
            "Connection: keep-alive\r\n"
            "Access-Control-Allow-Origin: *\r\n\r\n"
        )
        writer.write(response_headers.encode('utf-8'))
        await writer.drain()
        SSE_CLIENTS.add(writer)
        for past_log in LOG_HISTORY:
            try:
                writer.write(f"data: {json.dumps(past_log)}\n\n".encode('utf-8'))
                await writer.drain()
            except Exception: break
        return

    if method == "GET" and path == "/":
        payload = HTML_TEMPLATE.encode('utf-8')
        response = (
            "HTTP/1.1 200 OK\r\n"
            f"Content-Length: {len(payload)}\r\n"
            "Content-Type: text/html; charset=utf-8\r\n"
            "Connection: close\r\n\r\n"
        ).encode('utf-8') + payload
        writer.write(response)
        await writer.drain()
        writer.close()
        return

    if method == "GET" and path == "/api/metrics":
        time_idle_s = int(time.time() - pc_last_active) if pc_state == "ON" else 0
        pc_shutdown_remaining = int(pc_shutdown_trigger_time - time.time()) if pc_shutdown_pending else 0
        cache_sizes = {cat: len(msgs) for cat, msgs in msg_cache.items()}
        
        data = {
            "pc_state": pc_state,
            "pc_started_by_bot": pc_started_by_bot,
            "time_idle_s": time_idle_s,
            "pc_shutdown_pending": pc_shutdown_pending,
            "pc_shutdown_remaining": max(0, pc_shutdown_remaining),
            "sse_clients": len(SSE_CLIENTS),
            "cache_sizes": cache_sizes,
            "gen_targets": bot_state.get("gen_targets", {})
        }
        payload = json.dumps(data).encode('utf-8')
        response = (
            "HTTP/1.1 200 OK\r\n"
            f"Content-Length: {len(payload)}\r\n"
            "Content-Type: application/json\r\n"
            "Connection: close\r\n\r\n"
        ).encode('utf-8') + payload
        writer.write(response)
        await writer.drain()
        writer.close()
        return

    if method == "POST" and path.startswith("/api/"):
        action = path[5:]
        status = "ok"
        reason = ""
        
        if action == "pc/wakeup": asyncio.create_task(ensure_pc_ready())
        elif action == "pc/shutdown": asyncio.create_task(execute_pc_shutdown())
        elif action == "debug/toggle":
            bot_state["debug_enabled"] = not bot_state.get("debug_enabled", True)
            save_json_file(STATE_FILE, bot_state)
        elif action == "cache/generate": asyncio.create_task(batch_generate_messages(days=1))
        elif action == "cache/empty":
            msg_cache = {k: [] for k in DEFAULT_MESSAGES.keys()}
            save_json_file(MESSAGE_CACHE_FILE, msg_cache)
            log_console_debug("🗑️ Message cache pool explicitly emptied via dashboard.", category="SYSTEM")
        elif action.startswith("test/force_alert/"):
            cat = action.split("/")[-1]
            asyncio.create_task(force_trigger_alert(cat))
        elif action == "test/wanikani": asyncio.create_task(run_test_wanikani())
        elif action == "test/kitsu": asyncio.create_task(run_test_kitsu())
        elif action == "test/ollama": asyncio.create_task(run_test_ollama())
        elif action == "test/voicevox": asyncio.create_task(run_test_voicevox())
        elif action == "test/telegram": asyncio.create_task(run_test_telegram())
        elif action == "test/gemini_image": asyncio.create_task(run_test_gemini_image())
        elif action == "test/gemini_voice": asyncio.create_task(run_test_gemini_voice())
        else:
            status = "error"
            reason = "unrecognized command route"

        payload = json.dumps({"status": status, "reason": reason}).encode('utf-8')
        response = (
            "HTTP/1.1 200 OK\r\n"
            f"Content-Length: {len(payload)}\r\n"
            "Content-Type: application/json\r\n"
            "Connection: close\r\n\r\n"
        ).encode('utf-8') + payload
        writer.write(response)
        await writer.drain()
        writer.close()
        return

    response = "HTTP/1.1 404 Not Found\r\nContent-Length: 0\r\nConnection: close\r\n\r\n".encode('utf-8')
    writer.write(response)
    await writer.drain()
    writer.close()

# ==========================================
# POST-BOOT INITIALIZER HOOK
# ==========================================
async def post_init(application: Application) -> None:
    global GLOBAL_BOT
    GLOBAL_BOT = application.bot
    asyncio.create_task(start_diagnostic_server())

# ==========================================
# ENTRY POINT
# ==========================================
def main():
    print(f"🤖 Starting Master Orchestrator Bot...")
    
    application = Application.builder().token(TELEGRAM_BOT_TOKEN).post_init(post_init).build()

    application.add_handler(CommandHandler("start", start_command))
    application.add_handler(CommandHandler("help", start_command))
    application.add_handler(CommandHandler("debug", debug_command))
    application.add_handler(CommandHandler("shutdown", shutdown_command))

    application.add_handler(MessageHandler(filters.PHOTO, handle_image_message))
    application.add_handler(MessageHandler(filters.VOICE, handle_voice_message))
    application.add_handler(MessageHandler(filters.Sticker.ALL, handle_sticker_message))

    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text_message))
    application.add_handler(CallbackQueryHandler(llm_callback_handler))

    job_queue = application.job_queue
    if job_queue:
        job_queue.run_repeating(check_wanikani_alerts, interval=60, first=10)
        job_queue.run_repeating(check_pc_idle, interval=60, first=30)
        job_queue.run_daily(scheduled_midnight_batch, time=dt_time(hour=0, minute=0, tzinfo=timezone.utc))
    else:
        print("⚠ Warning: JobQueue is not installed! Background alerts are disabled.")

    print("✅ Bot is online! Send /start to your bot on Telegram.")
    application.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == "__main__":
    main()
