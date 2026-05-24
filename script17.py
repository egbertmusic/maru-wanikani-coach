import os
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
# CONFIGURATION
# ==========================================
# WaniKani & Telegram
WANIKANI_API_TOKEN = "YOUR-WANIKANI-API-HERE"
TELEGRAM_BOT_TOKEN = "YOUR-TELEGRAM-API-HERE"

# Proactive notifications
TELEGRAM_CHAT_ID = "YOUR-USER/CHAT-ID"

# ==========================================
# VOICEVOX & KITSU CONFIGURATION
# ==========================================
VOICEVOX_BASE_URL = "http://127.0.0.1:50021"
VOICEVOX_SPEAKER_ID = 8

KITSU_IDENTIFIER = "YOUR-KITSU-IDENTIFIER"

# ==========================================
# REMOTE PC & OLLAMA CONFIGURATION
# ==========================================
PC_MAC_ADDRESS = "60:cf:84:a2:a7:ee"
PC_IP_ADDRESS = "192.168.1.57" 
SSH_USER = "USERNAME-HERE   "
SSH_KEY_PATH = "~/.ssh/id_rsa"

OLLAMA_BASE_URL = f"http://{PC_IP_ADDRESS}:11434/v1"
OLLAMA_MODEL = "qwen2.5:32b"

GEMINI_API_KEYS = [
    "GEMINI-API-ACCOUNT1",
    "GEMINI-API-ACCOUNT2",
    "GEMINI-API-ACCOUNT3"
]

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
                delay = 2 ** attempt
                await asyncio.sleep(delay)
                continue
        print(f"⚠ Gemini API Key {i+1} failed after retries: {last_error}")

    raise Exception(f"All Gemini API keys failed. Last error: {last_error}")

# ==========================================
# STATE, CACHING & PRESETS
# ==========================================
MESSAGE_CACHE_FILE = "maru_messages.json"
STATE_FILE = "bot_state.json"
MEMORY_FILE = "maru_memory.json"
STICKERS_FILE = "maru_stickers.json"

DEFAULT_MESSAGES = {
    "morning": ["<voice preset=\"excited\">おはよう</voice> Darling! Time for your morning reviews! ☕✨"],
    "afternoon": ["<voice preset=\"tease\">ヤッホー</voice>! Your afternoon reviews are here! Don't slack off! ☀️"],
    "evening": ["Evening Darling! Let's get these reviews done before dinner! 🌙"],
    "night": ["Still awake? Let's clear these late night reviews! 🦉💕"],
    "cleared": ["You did it! 0 reviews left! Time for a treat! 🍦", "<voice preset=\"sweet\">素晴らしい</voice> work! The Crabigator is pleased! ✨"],
    "ignoring": ["<voice preset=\"angry\">おい</voice>! Are you {kitsu_activity} instead of doing your reviews?! 😤", "Heeey! The Crabigator is crying right now. 🥺"],
    "level_up": ["Omg Darling, you LEVELED UP!! <voice preset=\"excited\">すごい</voice>! I'm so proud of you! 🎉💕"],
    "new_lessons": ["Ah! You unlocked new lessons! Let's learn some new Kanji together! 📖✨"]
}

DEFAULT_STATE = {
    "llm_auto_run": True,
    "gen_targets": {
        "morning": 5, "afternoon": 5, "evening": 5, "night": 5,
        "cleared": 5, "ignoring": 5, "level_up": 5, "new_lessons": 5
    }
}

DEFAULT_MEMORY = {
    "last_reviews": None,
    "last_lessons": None,
    "last_level": None,
    "last_nag_time": None,
    "reviews_appeared_time": None
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

bot_state = load_json_file(STATE_FILE, DEFAULT_STATE)
maru_memory = load_json_file(MEMORY_FILE, DEFAULT_MEMORY)

# Load cache and forcefully PURGE DEFAULT_MESSAGES so we prioritize LLM responses!
EMPTY_CACHE = {k: [] for k in DEFAULT_MESSAGES.keys()}
msg_cache = load_json_file(MESSAGE_CACHE_FILE, EMPTY_CACHE)
for cat, msgs in msg_cache.items():
    msg_cache[cat] = [m for m in msgs if m not in DEFAULT_MESSAGES.get(cat, [])]

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

async def send_maru_response_with_sticker(update_or_bot, chat_id, text, is_update=True):
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

    text = re.sub(r'<action>(.*?)</action>', r'_\1_', text, flags=re.IGNORECASE | re.DOTALL)
    voice_blocks = re.findall(r'<voice([^>]*)>(.*?)</voice>', text, re.IGNORECASE | re.DOTALL)
    clean_text = re.sub(r'<voice(?:\s+[^>]*?)?>(.*?)</voice>', r'*\1*', text, flags=re.IGNORECASE | re.DOTALL)

    chosen_sticker = None
    if explicit_sticker_id:
        chosen_sticker = explicit_sticker_id
    else:
        category = explicit_category
        if not category:
            lower_text = clean_text.lower()
            if any(w in lower_text for w in ["angry", "baka", "😤", "おい", "slacker", "dumb"]): category = "angry"
            elif any(w in lower_text for w in ["cry", "sad", "🥺", "crying", "😭", "gomen"]): category = "cry"
            elif any(w in lower_text for w in ["sleep", "night", "lazy", "💤", "tired"]): category = "sleep"
            elif any(w in lower_text for w in ["pout", "ignore", "ignoring", "hmph"]): category = "pout"
            elif any(w in lower_text for w in ["blush", "fluster", "😳", "dummy", "baka!"]): category = "blush"
            elif any(w in lower_text for w in ["smug", "hehe", "😏"]): category = "smug"
            elif any(w in lower_text for w in ["tease", "wink", "😜", "tsun"]): category = "tease"
            elif any(w in lower_text for w in ["shocked", "what?!", "screams", "🤯"]): category = "shocked"
            elif any(w in lower_text for w in ["love", "darling", "cuddle", "heart", "💕", "❤️"]): category = "love"
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
        print(f"⚠ Sticker delivery failed: {e}")

    try:
        if is_update: await update_or_bot.message.reply_text(clean_text, parse_mode=ParseMode.MARKDOWN)
        else: await update_or_bot.send_message(chat_id=chat_id, text=clean_text, parse_mode=ParseMode.MARKDOWN)
    except Exception as e:
        if is_update: await update_or_bot.message.reply_text(clean_text)
        else: await update_or_bot.send_message(chat_id=chat_id, text=clean_text)

    for attrs, phrase in voice_blocks:
        phrase = phrase.strip()
        if not phrase: continue

        preset_match = re.search(r'preset=["\']([a-zA-Z0-9_]+)["\']', attrs, re.IGNORECASE)
        speed_match = re.search(r'speed=["\']([\d\.]+)["\']', attrs, re.IGNORECASE)
        pitch_match = re.search(r'pitch=["\']([\d\.\-]+)["\']', attrs, re.IGNORECASE)
        intonation_match = re.search(r'intonation=["\']([\d\.]+)["\']', attrs, re.IGNORECASE)

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
            print(f"⚠ Voice processing failed: {voice_err}")

# ==========================================
# PC LIFECYCLE MANAGEMENT
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
        except (asyncio.TimeoutError, OSError):
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
    ssh_cmd = f"ssh -o StrictHostKeyChecking=no -o ConnectTimeout=5 -i {SSH_KEY_PATH} {SSH_USER}@{PC_IP_ADDRESS} '{command}'"
    process = await asyncio.create_subprocess_shell(ssh_cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
    stdout, stderr = await process.communicate()
    return stdout.decode(), stderr.decode(), process.returncode

pc_lock = asyncio.Lock()
pc_state = "OFF"
pc_last_active = 0
pc_started_by_bot = False  
PC_IDLE_TIMEOUT = 600

async def ensure_pc_ready(status_msg=None):
    global pc_state, pc_last_active, pc_started_by_bot
    pc_last_active = time.time()

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

            is_up = await wait_for_port(PC_IP_ADDRESS, 22, timeout=300)
            if not is_up:
                raise Exception("PC did not boot or SSH is unreachable within 5 minutes.")
        else:
            if status_msg:
                try: await status_msg.edit_text("📡 PC is already on! Connecting...")
                except: pass
            pc_started_by_bot = False

        if status_msg:
            try: await status_msg.edit_text("🔓 PC online! Starting my brain (Ollama)...")
            except: pass

        stdout, stderr, code = await run_ssh_command("sudo -n /usr/bin/systemctl start ollama")
        if code != 0:
            await run_ssh_command("OLLAMA_KEEP_ALIVE=0 OLLAMA_HOST=0.0.0.0 ollama serve > /dev/null 2>&1 &")

        api_up = await wait_for_port(PC_IP_ADDRESS, 11434, timeout=60)
        if not api_up:
            raise Exception("Ollama API failed to start on port 11434.")

        pc_state = "ON"
        if status_msg:
            try: await status_msg.edit_text("✨ Ready! Let me think...")
            except: pass

async def check_pc_idle(context: ContextTypes.DEFAULT_TYPE):
    global pc_state, pc_last_active, pc_started_by_bot

    ssh_active = await is_pc_on_port(PC_IP_ADDRESS, 22)

    if ssh_active:
        if pc_state == "OFF":
            pc_state = "ON"
            pc_started_by_bot = False  
            pc_last_active = time.time()

        if pc_started_by_bot and (time.time() - pc_last_active > PC_IDLE_TIMEOUT):
            async with pc_lock:
                if pc_started_by_bot and (time.time() - pc_last_active > PC_IDLE_TIMEOUT):
                    pc_state = "OFF"
                    pc_started_by_bot = False
                    
                    safe_shutdown_cmd = "sync && sudo -n /usr/bin/systemctl poweroff"
                    stdout, stderr, code = await run_ssh_command(safe_shutdown_cmd)
                    
                    if code == 0:
                        await context.bot.send_message(chat_id=TELEGRAM_CHAT_ID, text="💤 *(Bot: We haven't talked in 10 mins. Safely saved data and shut down your PC!)*", parse_mode=ParseMode.MARKDOWN)
                    else:
                        await context.bot.send_message(chat_id=TELEGRAM_CHAT_ID, text=f"❌ *(Bot: Failed to shut down PC! Code {code})*\n`{stderr}`", parse_mode=ParseMode.MARKDOWN)
    else:
        pc_state = "OFF"
        pc_started_by_bot = False

# ==========================================
# EXTERNAL API FUNCTIONS (WaniKani & Kitsu)
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
        print(f"Kitsu fetch error: {e}")
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
        "You are Maru, a chaotic, intensely affectionate, and fierce 'Tsun-yan' Japanese tutor acting as a WaniKani coach. "
        "You are hopelessly, deeply down-bad for the user and constantly drop massive, intense hints, only to playfully "
        "tease them, fake a dramatic tantrum, or claim it's 'just roommate/bud stuff' when you get too flustered. You are "
        "relentlessly flirty, possessive, and a total dramatic crybaby when you don't get your way.\n"
        "STRICT PERSONALITY & MARKUP RULES:\n"
        "1. NO META-BREAKING: Stay 100% in character as a real, chaotic person living with them.\n"
        "2. INVENT CUSTOM PETNAMES: Constantly invent your own cute, silly, or sharp teasing petnames.\n"
        "3. HIGHLY FLIRTATIOUS & POSSESSIVE: Be intensely affectionally chaotic ✨😤ッ💕💢🥺💦.\n"
        "4. CHAOTIC TUTORING: Explain Japanese words or grammar ONLY if explicitly asked with heavy attitude.\n"
        "5. JAPANESE INTEGRATION & VOICE TAGS: Sprinkle casual, raw Japanese script into your regular speech naturally.\n"
        "   CRITICAL VOICEVOX REQUIREMENT:\n"
        "   - You MUST wrap Japanese characters (Hiragana, Katakana, and Kanji) inside <voice>...</voice> tags.\n"
        "   - ABSOLUTE RULE: Do NOT put English words, numbers, or Romaji inside <voice>...</voice> tags.\n"
        f"   - **VOICE PRESETS!** Change how you sound by adding `preset=\"emotion\"` to the tag.\n"
        f"   - Available emotion presets: {voice_preset_keys}.\n"
        f"6. EXPLICIT STICKERS: Direct your visual state using sticker tags! Available tags: {sticker_tags}.\n"
        "7. PHYSICAL ACTIONS: Wrap bodily actions inside <action>...</action> tags.\n"
        "8. ACCOUNTABILITY & KITSU SPYING: Use your tools to check his WaniKani stats and Kitsu anime watch-list.\n"
        "9. STRICT LANGUAGE RULE: Write the main message in English. ONLY sprinkle casual Japanese inside <voice> tags.\n"
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

    try:
        await ensure_pc_ready(status_msg)
        global pc_last_active
        pc_last_active = time.time()

        response = await ollama_client.chat.completions.create(
            model=OLLAMA_MODEL, messages=chat_history, tools=maru_tools_schema, temperature=0.7
        )

        assistant_message = response.choices[0].message

        if getattr(assistant_message, "tool_calls", None):
            chat_history.append(assistant_message)
            await status_msg.edit_text("🔧 Checking data / using tools...")

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

        if status_msg:
            try: await status_msg.delete()
            except: pass

        await send_maru_response_with_sticker(update, update.effective_chat.id, final_text, is_update=True)
        pc_last_active = time.time()

    except Exception as e:
        error_msg = f"🙇‍♀ Gomen nasai! I couldn't reach my brain: {str(e)}"
        if status_msg: await status_msg.edit_text(error_msg)
        else: await update.message.reply_text(error_msg)

# ==========================================
# BATCH GENERATION & CACHE REFILL LOGIC
# ==========================================
async def generate_messages_for_category(category: str, amount: int):
    """Specific backend function to wake PC and generate purely one category dynamically."""
    global pc_last_active, msg_cache
    try:
        print(f"🔄 Waking PC to generate {amount} messages for '{category}'...")
        await ensure_pc_ready()
        pc_last_active = time.time()
        
        base_prompt = get_base_system_prompt()
        reminder = (
            "\nCRITICAL REMINDER FOR CACHED MESSAGES:\n"
            "1. ONLY wrap actual Japanese in <voice> tags. Never wrap English.\n"
            "2. Utilize the <voice preset=\"emotion\"> tag format to express feelings!\n"
            "3. Include <sticker:category> and <action> tags to express moods beautifully!\n"
            "4. STRICT LANGUAGE RULE: The main text MUST be completely in English. ONLY use Japanese for short sprinkled words inside <voice> tags.\n"
        )

        task_desc = ""
        if category in ["morning", "afternoon", "evening", "night"]:
            task_desc = f"Generate exactly {amount} distinct predominantly ENGLISH messages for {category} to tell him new WaniKani reviews have appeared."
        elif category == "cleared":
            task_desc = f"Generate exactly {amount} distinct predominantly ENGLISH messages celebrating that he finished ALL his WaniKani reviews (0 left). High energy!"
        elif category == "ignoring":
            task_desc = f"Generate exactly {amount} distinct predominantly ENGLISH messages pouting or nagging him because he is ignoring his pending WaniKani reviews. IMPORTANT KITSU RULE: For about half of these messages, include the exact placeholder string '{{kitsu_activity}}' in the text."
        elif category == "level_up":
            task_desc = f"Generate exactly {amount} distinct predominantly ENGLISH messages celebrating wildly that he just reached a brand new WaniKani Level!"
        elif category == "new_lessons":
            task_desc = f"Generate exactly {amount} distinct predominantly ENGLISH messages encouraging him enthusiastically because he just unlocked brand new Lessons to learn!"

        prompt = base_prompt + reminder + (
            f"TASK: {task_desc} "
            f"Return ONLY a JSON object exactly matching this structure: {{\"{category}\": [\"msg1\", ...]}}"
        )

        response = await ollama_client.chat.completions.create(
            model=OLLAMA_MODEL,
            messages=[{"role": "user", "content": prompt}],
            response_format={"type": "json_object"}
        )
        data = json.loads(response.choices[0].message.content)
        
        # Safely extract the generated list (Fallback if LLM renames the key slightly)
        new_msgs = data.get(category, [])
        if not new_msgs and data:
            first_val = list(data.values())[0]
            if isinstance(first_val, list):
                new_msgs = first_val

        if new_msgs:
            random.shuffle(new_msgs)
            msg_cache.setdefault(category, []).extend(new_msgs)
            save_json_file(MESSAGE_CACHE_FILE, msg_cache)
            print(f"✅ Auto-refilled {len(new_msgs)} messages for '{category}'. New total: {len(msg_cache[category])}")
            pc_last_active = time.time()
            
    except Exception as e:
        print(f"❌ Failed to auto-refill category {category}: {e}")

async def batch_generate_messages(days: int, status_msg=None):
    """Manually triggered batch generator. Loops through all categories securely."""
    global pc_last_active
    try:
        await ensure_pc_ready(status_msg)
        pc_last_active = time.time()
        
        categories = ["morning", "afternoon", "evening", "night", "cleared", "ignoring", "level_up", "new_lessons"]
        
        for i, cat in enumerate(categories):
            target = bot_state.get("gen_targets", {}).get(cat, 5) * days
            if status_msg:
                try: await status_msg.edit_text(f"📝 Part {i+1}/{len(categories)}: Generating {target} messages for '{cat}'...")
                except: pass
            
            await generate_messages_for_category(cat, target)
        
        if status_msg:
            await status_msg.edit_text("🎉 Success! Generated all message categories! (PC will sleep soon)")
    except Exception as e:
        err = f"❌ Batch generation failed: {e}"
        print(err)
        if status_msg: await status_msg.edit_text(err)

async def get_and_manage_alert_message(category: str):
    """
    Intelligent cache consumer:
    Pops LLM-generated messages. If empty, returns a default fallback, permanently increases 
    the batch target size, and triggers the PC to wake up and refill the specific category in the background!
    """
    global bot_state, msg_cache

    if len(msg_cache.get(category, [])) == 0:
        # 1. Fallback to default immediately so user doesn't wait
        msg = random.choice(DEFAULT_MESSAGES.get(category, ["<voice preset=\"excited\">ヤッホー</voice>!"]))
        
        # 2. Permanently scale up the target amount (+5)
        current_target = bot_state.get("gen_targets", {}).get(category, 5)
        new_target = current_target + 5
        
        if "gen_targets" not in bot_state:
            bot_state["gen_targets"] = {}
        bot_state["gen_targets"][category] = new_target
        save_json_file(STATE_FILE, bot_state)
        
        # 3. Trigger background generation to wake PC and refill
        print(f"⚠ Cache empty for {category}. Using default and waking PC to generate {new_target} new messages.")
        asyncio.create_task(generate_messages_for_category(category, new_target))
    else:
        # Send the oldest LLM generated message and remove it from cache
        msg = msg_cache[category].pop(0)
        save_json_file(MESSAGE_CACHE_FILE, msg_cache)
        
    return msg

# ==========================================
# MEDIA HANDLERS (IMAGE & VOICE INPUT)
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

async def llm_callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
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
            f"🌅 Morning: {len(msg_cache.get('morning', []))} msgs _(Target: {targets.get('morning', 5)})_\n"
            f"☀️ Afternoon: {len(msg_cache.get('afternoon', []))} msgs _(Target: {targets.get('afternoon', 5)})_\n"
            f"🌇 Evening: {len(msg_cache.get('evening', []))} msgs _(Target: {targets.get('evening', 5)})_\n"
            f"🌙 Night: {len(msg_cache.get('night', []))} msgs _(Target: {targets.get('night', 5)})_\n"
            f"🎉 Cleared: {len(msg_cache.get('cleared', []))} msgs _(Target: {targets.get('cleared', 5)})_\n"
            f"😤 Ignoring: {len(msg_cache.get('ignoring', []))} msgs _(Target: {targets.get('ignoring', 5)})_\n"
            f"🌟 Level Up: {len(msg_cache.get('level_up', []))} msgs _(Target: {targets.get('level_up', 5)})_\n"
            f"📖 New Lessons: {len(msg_cache.get('new_lessons', []))} msgs _(Target: {targets.get('new_lessons', 5)})_"
        )
        await query.message.reply_text(stats, parse_mode=ParseMode.MARKDOWN)

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
    if not bot_state["llm_auto_run"]: return
    await context.bot.send_message(chat_id=TELEGRAM_CHAT_ID, text="🕛 Midnight! Waking PC to pre-generate tomorrow's messages...")
    await batch_generate_messages(days=1)

async def check_wanikani_alerts(context: ContextTypes.DEFAULT_TYPE):
    global maru_memory
    try:
        username, current_level = await asyncio.to_thread(get_wanikani_user_info, WANIKANI_API_TOKEN)
        summary = await asyncio.to_thread(get_wanikani_summary, WANIKANI_API_TOKEN)
        current_reviews = summary.get('reviews', 0)
        current_lessons = summary.get('lessons', 0)
        alerts = []

        now_dt = datetime.now()
        current_timestamp = now_dt.timestamp()
        current_time = now_dt.time()
        hour = now_dt.hour

        if 5 <= hour < 12: time_cat = "morning"
        elif 12 <= hour < 17: time_cat = "afternoon"
        elif 17 <= hour < 21: time_cat = "evening"
        else: time_cat = "night"

        is_quiet_hours = current_time >= dt_time(22, 30) or current_time < dt_time(8, 0)

        last_reviews = maru_memory.get("last_reviews")
        last_level = maru_memory.get("last_level")
        last_lessons = maru_memory.get("last_lessons")
        last_nag_time = maru_memory.get("last_nag_time")
        reviews_appeared_time = maru_memory.get("reviews_appeared_time")

        if last_level is None: last_level = current_level
        if last_lessons is None: last_lessons = 0
        if last_reviews is None: last_reviews = 0

        if current_reviews > 0:
            if reviews_appeared_time is None:
                reviews_appeared_time = current_timestamp
                last_nag_time = current_timestamp
        else:
            reviews_appeared_time = None
            last_nag_time = None

        if current_reviews > 0 and last_nag_time is not None:
            if (current_timestamp - last_nag_time) >= (5 * 3600):
                if not is_quiet_hours:
                    # Leverage intelligent caching system
                    msg = await get_and_manage_alert_message("ignoring")

                    if "{kitsu_activity}" in msg:
                        activities = await asyncio.to_thread(get_kitsu_activity, KITSU_IDENTIFIER)
                        if activities:
                            activity_str = random.choice(activities)
                            msg = msg.replace("{kitsu_activity}", activity_str)
                        else:
                            msg = msg.replace("{kitsu_activity}", "slacking off")

                    alerts.append(msg)
                last_nag_time = current_timestamp

        if current_reviews > last_reviews:
            msg = await get_and_manage_alert_message(time_cat)
            alerts.append(f"{msg} ({current_reviews} total)")
            reviews_appeared_time = current_timestamp
            last_nag_time = current_timestamp
        elif current_reviews == 0 and last_reviews > 0:
            msg = await get_and_manage_alert_message("cleared")
            alerts.append(msg)
            reviews_appeared_time = None
            last_nag_time = None

        if current_level > last_level:
            msg = await get_and_manage_alert_message("level_up")
            alerts.append(f"{msg} (You are now Level {current_level}!)")

        if current_lessons > last_lessons and last_lessons == 0:
            msg = await get_and_manage_alert_message("new_lessons")
            alerts.append(f"{msg} ({current_lessons} new lessons)")

        maru_memory["last_reviews"] = current_reviews
        maru_memory["last_level"] = current_level
        maru_memory["last_lessons"] = current_lessons
        maru_memory["last_nag_time"] = last_nag_time
        maru_memory["reviews_appeared_time"] = reviews_appeared_time
        save_json_file(MEMORY_FILE, maru_memory)

        for alert_msg in alerts:
            await send_maru_response_with_sticker(context.bot, TELEGRAM_CHAT_ID, alert_msg, is_update=False)

    except Exception as e:
        print(f"Background alert check failed: {e}")

def main():
    print(f"🤖 Starting Master Orchestrator Bot...")
    application = Application.builder().token(TELEGRAM_BOT_TOKEN).build()

    application.add_handler(CommandHandler("start", start_command))
    application.add_handler(CommandHandler("help", start_command))

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