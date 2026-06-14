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
import urllib.parse
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

PLAYWRIGHT_AVAILABLE = False
try:
    from playwright.async_api import async_playwright
    PLAYWRIGHT_AVAILABLE = True
except ImportError:
    PLAYWRIGHT_AVAILABLE = False

CONFIG_FILE = "config.json"
DEFAULT_CONFIG = {
    "WANIKANI_API_TOKEN": "YOUR-WANIKANI-API-HERE",
    "BUNPRO_USERNAME": "YOUR-BUNPRO-EMAIL-HERE",
    "BUNPRO_PASSWORD": "YOUR-BUNPRO-PASSWORD-HERE",
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
    print(f"⚠️ Created template '{CONFIG_FILE}'. Please fill it out and restart the bot!")
    sys.exit(1)

with open(CONFIG_FILE, "r") as f:
    config = json.load(f)

WANIKANI_API_TOKEN = config.get("WANIKANI_API_TOKEN", "")
BUNPRO_USERNAME = config.get("BUNPRO_USERNAME", "")
BUNPRO_PASSWORD = config.get("BUNPRO_PASSWORD", "")
TELEGRAM_BOT_TOKEN = config.get("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = config.get("TELEGRAM_CHAT_ID", "")
KITSU_IDENTIFIER = config.get("KITSU_IDENTIFIER", "")
PC_MAC_ADDRESS = config.get("PC_MAC_ADDRESS", "")
PC_IP_ADDRESS = config.get("PC_IP_ADDRESS", "")
SSH_USER = config.get("SSH_USER", "")
SSH_KEY_PATH = config.get("SSH_KEY_PATH", "~/.ssh/id_rsa")
GEMINI_API_KEYS = config.get("GEMINI_API_KEYS", [])

DIAG_PORT = 5001
VOICEVOX_BASE_URL = "http://127.0.0.1:50021"
VOICEVOX_SPEAKER_ID = 8

OLLAMA_BASE_URL = f"http://{PC_IP_ADDRESS}:11434/v1"
OLLAMA_MODEL = "qwen2.5:32b"

GLOBAL_BOT = None
ollama_client = AsyncOpenAI(base_url=OLLAMA_BASE_URL, api_key="ollama")

try:
    from google import genai
    from google.genai import types
    GEMINI_AVAILABLE = True
except ImportError:
    GEMINI_AVAILABLE = False

MESSAGE_CACHE_FILE = "maru_messages.json"
STATE_FILE = "bot_state.json"
MEMORY_FILE = "maru_memory.json"
STICKERS_FILE = "maru_stickers.json"

CANCEL_GENERATION = False

GEN_STATUS = {
    "active": False,
    "category": "",
    "current": 0,
    "total": 0,
    "last_generated": ""
}

TIMES_OF_DAY = ["morning", "afternoon", "evening", "night"]
PLATFORMS = ["wanikani", "bunpro", "both"]
TRIGGERS = ["nag_mild", "nag_angry", "nag_boiling", "cleared", "level_up", "new_lessons"]

def get_all_cache_keys():
    keys = []
    for t in TIMES_OF_DAY:
        for p in PLATFORMS:
            for g in TRIGGERS:
                keys.append(f"{t}_{p}_{g}")
    return keys

OPENERS = {
    "morning": [
        "Wake up, {petname}! {kaomoji}",
        "あんた！ Drooling again?! {kaomoji}",
        "Morning! Your queue is blinding me! {kaomoji}",
        "Oi, get up lazy! {kaomoji}"
    ],
    "afternoon": [
        "Midday check! Slacking off? {kaomoji}",
        "Hey! Stop napping! {kaomoji}",
        "Lunch is over, feed your brain! {kaomoji}",
        "I'm watching you... study! {kaomoji}"
    ],
    "evening": [
        "Sun's down, queue is up! {kaomoji}",
        "Clear your reviews or I'll cry! {kaomoji}",
        "No dinner until you study! {kaomoji}",
        "Mou... clear this already! {kaomoji}"
    ],
    "night": [
        "Don't fall asleep on me! {kaomoji}",
        "Pitch black out, study time in! {kaomoji}",
        "No sleeping with this queue! {kaomoji}",
        "Let's smash these reviews, {petname}! {kaomoji}"
    ]
}

PLATFORM_MESSAGES = {
    "wanikani": {
        "nag_mild": "Only {wk_reviews} Kanji? Clear them before I get bored! {kaomoji}",
        "nag_angry": "{wk_reviews} WaniKani items left?! You're making my blood boil! {kaomoji}",
        "nag_boiling": "{wk_reviews} REVIEWS?! Are you ignoring me?! I'm flooding the house with tears! {kaomoji}",
        "cleared": "Zero Kanji left! Now look only at me! {kaomoji}",
        "level_up": "Level {level}?! Wow, you're actually not useless! {kaomoji}",
        "new_lessons": "{wk_lessons} new lessons unlocked! Crush them! {kaomoji}"
    },
    "bunpro": {
        "nag_mild": "{bp_reviews} Bunpro items waiting. Do your grammar! {kaomoji}",
        "nag_angry": "Skipping grammar?! {bp_reviews} items left! Get on it! {kaomoji}",
        "nag_boiling": "{bp_reviews} GRAMMAR REVIEWS?! Do them right now or I'll scream! {kaomoji}",
        "cleared": "Zero grammar left! Cuddles now! {kaomoji}",
        "level_up": "Level {level}?! Super proud of you! {kaomoji}",
        "new_lessons": "{bp_lessons} Bunpro lessons unlocked! Let's go! {kaomoji}"
    },
    "both": {
        "nag_mild": "{wk_reviews} Kanji and {bp_reviews} Grammar waiting. Go go go! {kaomoji}",
        "nag_angry": "Ignoring both?! {wk_reviews} Kanji, {bp_reviews} Grammar. NOW! {kaomoji}",
        "nag_boiling": "UNBELIEVABLE! {wk_reviews} Kanji AND {bp_reviews} Grammar?! I'm actually crying! {kaomoji}",
        "cleared": "Zero on both! Outstanding, {petname}! {kaomoji}",
        "level_up": "Level {level}!! Master status! {kaomoji}",
        "new_lessons": "{wk_lessons} Kanji & {bp_lessons} Grammar lessons! Wake up! {kaomoji}"
    }
}

DEFAULT_MESSAGES = {}
for t in TIMES_OF_DAY:
    for p in PLATFORMS:
        for g in TRIGGERS:
            opener = random.choice(OPENERS[t])
            base_m = PLATFORM_MESSAGES[p][g]
            timed_msg = f"<sticker:smile> {opener} {base_m}"
            DEFAULT_MESSAGES[f"{t}_{p}_{g}"] = [timed_msg]

DEFAULT_STATE = {
    "llm_auto_run": True,
    "gen_targets": {k: 10 for k in get_all_cache_keys()},
    "debug_enabled": True
}

DEFAULT_MEMORY = {
    "last_reviews": None,
    "last_lessons": None,
    "last_bp_reviews": None,
    "last_bp_lessons": None,
    "bp_streak": "0",
    "bp_progress": "N/A",
    "bp_activity_days": 0,
    "bp_badges": [],
    "last_level": None,
    "last_nag_time": None,
    "reviews_appeared_time": None,
    "snooze_until": 0.0,
    "pc_state": "OFF",
    "pc_last_active": 0.0,
    "pc_started_by_bot": False,
    "pc_shutdown_pending": False,
    "pc_shutdown_trigger_time": 0.0,
    "pc_shutdown_alert_msg_id": None,
    "last_summary_hash": None,
    "last_summary_text": None
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

# Maps detected emotional moods directly to designated Voicevox presets for fallback consistency
MOOD_TO_PRESET = {
    "angry": "angry",
    "cry": "sad",
    "sad": "sad",
    "sleep": "shy",
    "pout": "shy",
    "blush": "shy",
    "smug": "tease",
    "tease": "tease",
    "shocked": "panic",
    "panic": "panic",
    "love": "sweet",
    "happy": "excited",
    "excited": "excited",
    "smile": "normal",
    "normal": "normal"
}

def detect_mood_from_text(text: str, explicit_category: str = None) -> str:
    """Analyzes text properties and structural stickers to estimate the active emotional mood."""
    if explicit_category and explicit_category in MOOD_TO_PRESET:
        return explicit_category
    lower_text = text.lower()
    if any(w in lower_text for w in ["angry", "baka", "😤", "おい", "slacker", "dumb", "idiot"]): return "angry"
    if any(w in lower_text for w in ["cry", "sad", "🥺", "crying", "😭", "gomen", "hurt"]): return "cry"
    if any(w in lower_text for w in ["sleep", "night", "lazy", "💤", "tired"]): return "sleep"
    if any(w in lower_text for w in ["pout", "ignore", "ignoring", "hmph"]): return "pout"
    if any(w in lower_text for w in ["blush", "fluster", "😳", "dummy", "baka!"]): return "blush"
    if any(w in lower_text for w in ["smug", "hehe", "😏"]): return "smug"
    if any(w in lower_text for w in ["tease", "wink", "😜", "tsun"]): return "tease"
    if any(w in lower_text for w in ["shocked", "what?!", "screams", "🤯"]): return "shocked"
    if any(w in lower_text for w in ["love", "darling", "cuddle", "heart", "💕", "❤️", "mine"]): return "love"
    if any(w in lower_text for w in ["happy", "yay", "🎉", "すご", "awesome"]): return "happy"
    return "normal"

def get_emotional_voice_params(attrs: str, mood: str):
    """Calculates vocal parameters, dynamically overriding default profiles if voice matches the estimated mood."""
    preset_match = re.search(r'preset=["\']?([a-zA-Z0-9_]+)["\']?', attrs, re.IGNORECASE)
    speed_match = re.search(r'speed=["\']?([\d\.\-]+)["\']?', attrs, re.IGNORECASE)
    pitch_match = re.search(r'pitch=["\']?([\d\.\-]+)["\']?', attrs, re.IGNORECASE)
    intonation_match = re.search(r'intonation=["\']?([\d\.\-]+)["\']?', attrs, re.IGNORECASE)

    preset_key = preset_match.group(1).lower() if preset_match else "normal"
    
    # If explicit tag uses standard 'normal' preset, adapt it to the active computed mood
    if preset_key == "normal" and mood in MOOD_TO_PRESET:
        preset_key = MOOD_TO_PRESET[mood]

    base_params = VOICE_PRESETS.get(preset_key, VOICE_PRESETS["normal"])

    try: v_speed = float(speed_match.group(1)) if speed_match else base_params["speed"]
    except ValueError: v_speed = base_params["speed"]
        
    try: v_pitch = float(pitch_match.group(1)) if pitch_match else base_params["pitch"]
    except ValueError: v_pitch = base_params["pitch"]
        
    try: v_inton = float(intonation_match.group(1)) if intonation_match else base_params["intonation"]
    except ValueError: v_inton = base_params["intonation"]

    return preset_key, v_speed, v_pitch, v_inton

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
        print(f"⚠ Error saving file {filepath}: {e}")

LOG_HISTORY = []
MAX_LOG_HISTORY = 150
SSE_CLIENTS = set()

def log_console_debug(message, category="SYSTEM"):
    if not bot_state.get("debug_enabled", True) and category not in ["ERROR", "OLLAMA_IO", "BUNPRO", "TEST"]:
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
        
    broadcast_to_sse({"type": "log", "data": log_item})

def broadcast_to_sse(data_obj):
    if not SSE_CLIENTS:
        return
    sse_data = f"data: {json.dumps(data_obj)}\n\n"
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

EMPTY_CACHE = {k: [] for k in get_all_cache_keys()}
msg_cache = load_json_file(MESSAGE_CACHE_FILE, EMPTY_CACHE)

for cat, msgs in msg_cache.items():
    if cat in DEFAULT_MESSAGES:
        msg_cache[cat] = [m for m in msgs if m not in DEFAULT_MESSAGES[cat]]

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
    try:
        params = {'text': text, 'speaker': VOICEVOX_SPEAKER_ID}
        query_res = requests.post(f"{VOICEVOX_BASE_URL}/audio_query", params=params, timeout=5)
        query_res.raise_for_status()
        
        query_json = query_res.json()
        query_json['speedScale'] = float(speed)
        query_json['pitchScale'] = float(pitch)
        query_json['intonationScale'] = float(intonation)

        synth_res = requests.post(
            f"{VOICEVOX_BASE_URL}/synthesis", 
            params={'speaker': VOICEVOX_SPEAKER_ID}, 
            json=query_json,
            timeout=15
        )
        synth_res.raise_for_status()

        content = synth_res.content
        if not content or len(content) < 200:
            log_console_debug("⚠️ Voicevox returned an empty or corrupted audio segment.", "ERROR")
            return None

        fp = io.BytesIO(content)
        fp.name = "pronunciation.ogg"
        fp.seek(0)
        return fp
    except Exception as e:
        log_console_debug(f"⚠️ Voicevox request failed: {e}", "ERROR")
        return None

def generate_natural_petname():
    english_prefixes = ["my sweet", "my dear", "my beloved", "my precious", "my darling"]
    english_names = ["honey", "darling", "baby", "sweetheart", "sweetie", "love"]
    
    japanese_names = [
        "貴方", "あんた", "お前", "旦那様", "ご主人様", "愛しい人", 
        "バカ", "アホ", "ダーリン", "ハニー", "ツンデレくん"
    ]
    
    choice = random.choice([1, 2, 3])
    if choice == 1:
        if random.random() < 0.4:
            return f"{random.choice(english_prefixes)} {random.choice(english_names)}"
        return random.choice(english_names)
    elif choice == 2:
        return random.choice(japanese_names)
    else:
        return f"{random.choice(english_prefixes)} {random.choice(japanese_names)}"

def generate_dynamic_kaomoji(category="nag_mild"):
    category = category.split("_")[-1] if "_" in category else category
    
    if category == "nag_angry":
        left_arms = ["ヽ", "(ノ", "(`", "((#", "щ", "(ꐦ"]
        right_arms = ["ノ", "ノ\u200b💢", "*)ノ", "💢)", "益ಠ)ノ", "ง"]
        eyes_left = ["・", "`", "°᷅", "ಠ", "Ò", ">"]
        eyes_right = ["・", "´", "°᷅", "ಠ", "Ó", "<"]
        mouths = ["皿", "益", "д", "︿", "ㅂ", "ᗣ"]
        blushes = ["", "💢", " 💢 "]
        
        if random.random() < 0.25:
            return random.choice(["(・`ω´・)", "( 😤 💢 )", "(`^´💢)", "(╬ಠ益ಠ)", "(`皿´💢)", "(,,#ﾟДﾟ)"])
        
        la = random.choice(left_arms)
        ra = random.choice(right_arms)
        el = random.choice(eyes_left)
        er = random.choice(eyes_right)
        mo = random.choice(mouths)
        bl = random.choice(blushes)
        return f"{la}{bl}{el}{mo}{er}{bl}{ra}"
        
    elif category == "nag_boiling":
        left_arms = ["", "(", "｡ﾟ･(", "。(>", "(/"]
        right_arms = ["", ")", ")･ﾟ｡", ")｡", "/)"]
        eyes = ["┬┬", "ಥಥ", "😭", "T", "ρ", "Q"]
        mouths = ["﹏", "Д", "_<", "A", "ꕀ", "ᗣ"]
        tears = ["💦", "｡", "💧", "╥"]
        
        if random.random() < 0.25:
            return random.choice(["(┬┬﹏┬┬)", "( 😭 💦 )", "🤬🔪💦", "(ಥ﹏ಥ)", "｡ﾟ･(>﹏<)･ﾟ｡", "(*꒦ິ꒳꒦ີ)"])
        
        eye = random.choice(eyes)
        mo = random.choice(mouths)
        t = random.choice(tears)
        la = random.choice(left_arms)
        ra = random.choice(right_arms)
        
        if len(eye) == 2:
            return f"{la}{eye[0]}{mo}{eye[1]}{t}{ra}"
        return f"{la}{eye}{mo}{eye}{t}{ra}"
        
    elif category == "cleared":
        left_arms = ["＼", "٩", "((o", "o", "d"]
        right_arms = ["／", "۶", "o))", "o", "b"]
        eyes = ["≧", "◕", "★", "✧", "＾", "o", "✿"]
        mouths = ["◡", "▽", "‿", "ᴗ", "ω", "∀", "ヮ"]
        cheeks = ["〃", "灬", ""]
        
        if random.random() < 0.25:
            return random.choice(["(≧◡≦)", "＼(￣▽￣)／", "٩(◕‿◕｡)۶", "(*¯︶¯*)", "((o(*ﾟ▽ﾟ*)o))"])
        
        la = random.choice(left_arms)
        ra = random.choice(right_arms)
        eye = random.choice(eyes)
        mo = random.choice(mouths)
        ch = random.choice(cheeks)
        return f"{la}({ch}{eye}{mo}{eye}{ch}){ra}"
        
    elif category == "level_up":
        left_arms = ["♡(", "ღ(", "(灬", "(*"]
        right_arms = [")♡", ")", ")", "*)_•"]
        eyes = ["˘", "•", "▿", "＾", "‿"]
        mouths = ["⌣", " ³", "‿", "ω", "ε"]
        hearts = ["♥", "♡", "💕", "✨"]
        
        if random.random() < 0.25:
            return random.choice(["(ღ˘⌣˘ღ)", "♡(｡- ω -)", "(´• ω •`) ♡", "( ˘ ³˘)♥", "(灬º‿º灬)♡"])
        
        la = random.choice(left_arms)
        ra = random.choice(right_arms)
        eye = random.choice(eyes)
        mo = random.choice(mouths)
        h = random.choice(hearts)
        return f"{la}{eye}{mo}{eye}{ra}{h}"
        
    elif category == "new_lessons":
        left_arms = ["", "o(", "(", "(*"]
        right_arms = ["", ")", ")✧", "*)"]
        eyes = ["≖", "✧", "￣", "´･", "^", "ಡ"]
        mouths = [" ‿ ", "ω", "∀", "︿", " 3 "]
        stars = ["✨", "✧", "★"]
        
        if random.random() < 0.25:
            return random.choice(["(≖ ‿ ≖)", "(✧ω✧)", "o(≧▽≦)o", "(•̀ᴗ•́)و ✧", "(´･ᴗ･ `)"])
        
        la = random.choice(left_arms)
        ra = random.choice(right_arms)
        eye = random.choice(eyes)
        mo = random.choice(mouths)
        st = random.choice(stars)
        return f"{st}{la}{eye}{mo}{eye}{ra}"
        
    else:
        left_arms = ["", "┐", "٩", "(｡•", "(", "(*"]
        right_arms = ["", "┌", "و", "｡)", ")", "*)"]
        eyes = ["•", ">", "´•", "・", "-", "ˇ"]
        mouths = ["₃", "ε", "ω", "﹏", "︿", "‿"]
        cheeks = ["〃", "灬", ""]
        
        if random.random() < 0.25:
            return random.choice(["(｡•ˇ₃ˇ•｡)", "(〃▽〃)", "(´• ω •`)", "┐(￣ヘ￣)┌", "(๑•́ ₃ •̀๑)"])
            
        la = random.choice(left_arms)
        ra = random.choice(right_arms)
        eye = random.choice(eyes)
        mo = random.choice(mouths)
        ch = random.choice(cheeks)
        return f"{la}{ch}{eye}{mo}{eye}{ch}{ra}"

def format_alert_message(msg_template, wk_rev=0, bp_rev=0, wk_les=0, bp_les=0, kitsu_act="slacking off", level=1, trigger="nag_mild"):
    petname = generate_natural_petname()
    total_rev = wk_rev + bp_rev
    total_les = wk_les + bp_les
    
    trigger_key = trigger.split("_")[-1] if "_" in trigger else trigger
    chosen_kaomoji = generate_dynamic_kaomoji(trigger_key)
    
    replacements = {
        "wk_reviews": str(wk_rev),
        "bp_reviews": str(bp_rev),
        "wk_lessons": str(wk_les),
        "bp_lessons": str(bp_les),
        "reviews": str(total_rev),
        "lessons": str(total_les),
        "kitsu_activity": kitsu_act,
        "level": str(level),
        "petname": petname,
        "kaomoji": chosen_kaomoji
    }
    
    res = msg_template
    for key, val in replacements.items():
        pattern_curly = re.compile(rf"\{{{key}\}}", re.IGNORECASE)
        pattern_square = re.compile(rf"\[{key}\]", re.IGNORECASE)
        res = pattern_curly.sub(val, res)
        res = pattern_square.sub(val, res)
        
    res = res.replace("{kaomoji}", chosen_kaomoji).replace("[kaomoji]", chosen_kaomoji)
    return res

def sanitize_markdown_v1(text: str) -> str:
    text = re.compile(r'^#+\s*', re.MULTILINE).sub('', text)
    text = re.compile(r'\s+#+\s*').sub(' ', text)
    text = re.compile(r'#([a-zA-Z0-9_\-]+)').sub(r'\1', text)

    if text.count('*') % 2 != 0:
        text += '*'
    if text.count('_') % 2 != 0:
        text += '_'
    if text.count('`') % 2 != 0:
        text += '`'
    
    text = text.replace('[', '\\[').replace(']', '\\]')
    return text

async def send_maru_response_with_sticker(update_or_bot, chat_id, text, is_update=True, reply_markup=None):
    log_console_debug(f"Parsing raw text for output:\n{text}", category="OLLAMA_IO")
    
    text = re.sub(r'<\{?sticker:\{?([a-zA-Z0-9_-]+)\}?\}>', r'<sticker:\1>', text, flags=re.IGNORECASE)
    
    explicit_sticker_id = None
    sticker_id_match = re.search(r'<sticker_id:(.*?)>', text, re.IGNORECASE)
    if sticker_id_match:
        explicit_sticker_id = sticker_id_match.group(1).strip()
        text = re.sub(r'<sticker_id:(.*?)>', '', text, flags=re.IGNORECASE)

    explicit_category = None
    category_match = re.search(r'<sticker:([a-zA-Z0-9_-]+)>', text, re.IGNORECASE)
    if category_match:
        explicit_category = category_match.group(1).strip().lower()
    
    text = re.sub(r'</?sticker[^>]*>', '', text, flags=re.IGNORECASE)
    text = re.sub(r'</?action[^>]*>', '_', text, flags=re.IGNORECASE)
    text = re.sub(r'<voicepreset', '<voice preset', text, flags=re.IGNORECASE)
    
    voice_blocks = re.findall(r'<voice\s*([^>]*)>(.*?)</voice>', text, re.IGNORECASE | re.DOTALL)
    if not voice_blocks:
        unclosed_match = re.search(r'<voice\s*([^>]*)>(.*)', text, re.IGNORECASE | re.DOTALL)
        if unclosed_match and '</voice>' not in text.lower():
            voice_blocks = [(unclosed_match.group(1), unclosed_match.group(2))]

    clean_text = re.sub(r'</?voice[^>]*>', '*', text, flags=re.IGNORECASE)
    clean_text = re.sub(r'\*+', '*', clean_text)
    clean_text = re.sub(r'_+', '_', clean_text)
    
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
            category = detect_mood_from_text(clean_text, explicit_category=explicit_category)

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

    sanitized_text = sanitize_markdown_v1(clean_text)

    try:
        if is_update: await update_or_bot.message.reply_text(sanitized_text, parse_mode=ParseMode.MARKDOWN, reply_markup=reply_markup)
        else: await update_or_bot.send_message(chat_id=chat_id, text=sanitized_text, parse_mode=ParseMode.MARKDOWN, reply_markup=reply_markup)
    except Exception as e:
        log_console_debug(f"Markdown parsing failed, sending raw text fallback. Error: {e}", category="ERROR")
        if is_update: await update_or_bot.message.reply_text(clean_text, reply_markup=reply_markup)
        else: await update_or_bot.send_message(chat_id=chat_id, text=clean_text, reply_markup=reply_markup)

    # Calculate overarching vocal mood parameter adjustments
    computed_mood = detect_mood_from_text(clean_text, explicit_category=explicit_category)

    for attrs, phrase in voice_blocks:
        phrase = phrase.strip()
        if not phrase: continue

        preset_key, v_speed, v_pitch, v_inton = get_emotional_voice_params(attrs, computed_mood)

        # Constrain parameters safely to acceptable margins
        v_speed = max(0.8, min(v_speed, 1.5))       
        v_pitch = max(-0.08, min(v_pitch, 0.08))     
        v_inton = max(0.6, min(v_inton, 1.4))       

        contains_japanese = re.search(r'[\u3040-\u309F\u30A0-\u30FF\u4E00-\u9FAF\uff00-\uffef]', phrase)
        if not contains_japanese:
            continue
            
        try:
            audio_fp = await asyncio.to_thread(make_voicevox_audio, text=phrase, speed=v_speed, pitch=v_pitch, intonation=v_inton)
            if audio_fp is not None:
                if is_update: await update_or_bot.message.reply_voice(voice=audio_fp)
                else: await update_or_bot.send_voice(chat_id=chat_id, voice=audio_fp)
            else:
                log_console_debug("⚠️ Skipping voice dispatch because Voicevox returned no audio.", "SYSTEM")
        except Exception as voice_err:
            log_console_debug(f"Voice processing failed: {voice_err}", category="ERROR")

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
        except Exception:
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
                try: await status_msg.edit_text("📡 Waking up PC... (This takes a minute!)")
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
            try: await status_msg.edit_text("🔓 PC online! Starting Ollama...")
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
        "systemctl poweroff"
    )
    
    stdout, stderr, code = await run_ssh_command(safe_shutdown_cmd)
    pc_state = "OFF"
    pc_started_by_bot = False
    pc_shutdown_pending = False
    pc_last_active = time.time() 
    
    if pc_shutdown_alert_msg_id and context:
        try: await context.bot.delete_message(chat_id=TELEGRAM_CHAT_ID, message_id=pc_shutdown_alert_msg_id)
        except Exception: pass
        pc_shutdown_alert_msg_id = None

    persist_pc_state()

    if code in [0, 255, -1]:
        log_console_debug(f"✅ Shutdown executed successfully. Closed connection with code {code}.", category="PC")
        if context:
            await context.bot.send_message(
                chat_id=TELEGRAM_CHAT_ID, 
                text="💤 *(Bot: Inactivity timeout reached. Shutting down PC!)*", 
                parse_mode=ParseMode.MARKDOWN
            )
    else:
        log_console_debug(f"❌ Failed to shut down PC: {stderr}", category="ERROR")

async def check_pc_idle(context: ContextTypes.DEFAULT_TYPE):
    global pc_state, pc_last_active, pc_started_by_bot, pc_shutdown_pending, pc_shutdown_alert_msg_id, pc_shutdown_trigger_time

    if pc_lock.locked(): return

    ssh_active = await is_pc_on_port(PC_IP_ADDRESS, 22)
    time_idle = time.time() - pc_last_active

    if ssh_active:
        if pc_state == "OFF":
            pc_state = "ON"
            pc_last_active = time.time()
            boot_src = await read_pc_boot_source()
            pc_started_by_bot = (boot_src == "BOT")
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
                        "Darling, you've been slacking for 10 minutes. I'm turning off the PC to save power!\n\n"
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

async def get_bunpro_summary_via_playwright():
    if not BUNPRO_USERNAME or not BUNPRO_PASSWORD:
        log_console_debug("Bunpro credentials missing in config.json. Bypassing automation.", "BUNPRO")
        return {"lessons": 0, "reviews": 0, "streak": "0", "progress": "N/A", "activity_days": 0, "badges": [], "next_review_time": None, "next_review_count": 0}

    if not PLAYWRIGHT_AVAILABLE:
        log_console_debug("Playwright not installed! Run: pip install playwright && playwright install", "BUNPRO")
        return {"lessons": 0, "reviews": 0, "streak": "0", "progress": "N/A", "activity_days": 0, "badges": [], "next_review_time": None, "next_review_count": 0}

    log_console_debug("Launching Playwright headless instance...", "BUNPRO")
    try:
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            context = await browser.new_context(
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                viewport={"width": 1280, "height": 800}
            )
            page = await context.new_page()
            
            log_console_debug("Opening bunpro.jp/login...", "BUNPRO")
            await page.goto("https://bunpro.jp/login", wait_until="domcontentloaded", timeout=45000)
            
            await page.fill('input[type="email"], input[name*="username"], input[name*="email"]', BUNPRO_USERNAME)
            await page.fill('input[type="password"]', BUNPRO_PASSWORD)
            
            log_console_debug("Submitting login credentials...", "BUNPRO")
            await page.click('button[type="submit"], input[type="submit"]')
            
            await page.wait_for_url("**/dashboard", timeout=30000)
            log_console_debug("Logged in! Allowing React client to build DOM...", "BUNPRO")
            
            await page.wait_for_timeout(8000) 
            await page.keyboard.press("Escape") 
            await page.wait_for_timeout(1000)
            
            stats = await page.evaluate(r"""
                () => {
                    let data = { reviews: 0, lessons: 0, streak: '0', progress: '', activity_days: 0, badges: [] };
                    try {
                        const bodyText = document.body.innerText || "";
                        
                        const learnTopMatch = bodyText.match(/Learn\s+(\d+)/i);
                        if (learnTopMatch) data.lessons = parseInt(learnTopMatch[1]);
                        
                        const reviewTopMatch = bodyText.match(/Review\s+(\d+)/i);
                        if (reviewTopMatch) data.reviews = parseInt(reviewTopMatch[1]);

                        if (data.lessons === 0) {
                            let learnBoxMatch = bodyText.match(/Learn\s+\d+\s*\/\s*(\d+)/i);
                            if (learnBoxMatch) data.lessons = parseInt(learnBoxMatch[1]);
                        }

                        let streakValue = '0';
                        const streakRegexes = [
                            /Current\s*Streak\s*[-:\s]\s*(\d+)/i,
                            /Streak\s*[-:\s]\s*(\d+)/i,
                            /(\d+)\s*(?:Day|Days)?\s*Streak/i,
                            /(\d+)\s*Day\s*Active/i
                        ];
                        for (let regex of streakRegexes) {
                            let match = bodyText.match(regex);
                            if (match && match[1]) {
                                streakValue = match[1];
                                break;
                            }
                        }

                        if (streakValue === '0') {
                            const elList = Array.from(document.querySelectorAll('*'));
                            for (let el of elList) {
                                if (el.innerText) {
                                    const t = el.innerText.trim();
                                    let m = t.match(/current\s*streak\s*[-:\s]?\s*(\d+)/i) || 
                                            t.match(/^streak\s*[-:\s]?\s*(\d+)$/i) || 
                                            t.match(/^(\d+)\s*day\s*streak/i);
                                    if (m && m[1]) {
                                        streakValue = m[1];
                                        break;
                                    }
                                }
                            }
                            
                            if (streakValue === '0') {
                                for (let el of elList) {
                                    if (el.children.length === 0 && el.innerText) {
                                        const text = el.innerText.trim().toLowerCase();
                                        if (text === 'streak' || text === 'current streak' || text === 'day streak') {
                                            let parent = el.parentElement;
                                            if (parent) {
                                                let pText = parent.innerText || "";
                                                let pm = pText.match(/(\d+)/);
                                                if (pm) {
                                                    streakValue = pm[1];
                                                    break;
                                                }
                                                let siblings = Array.from(parent.children);
                                                for (let sib of siblings) {
                                                    let sibText = sib.innerText.trim();
                                                    let sm = sibText.match(/^(\d+)$/);
                                                    if (sm) {
                                                        streakValue = sm[1];
                                                        break;
                                                    }
                                                }
                                            }
                                        }
                                    }
                                    if (streakValue !== '0') break;
                                }
                            }
                        }
                        data.streak = streakValue;

                        let progMatches = [...bodyText.matchAll(/(N[1-5])\s+(\d+\/\d+)/g)];
                        if (progMatches.length > 0) {
                            data.progress = progMatches.slice(0, 3).map(m => m[1] + ': ' + m[2]).join(', ');
                        } else {
                            data.progress = "N/A";
                        }

                        let daysMatch = bodyText.match(/(\d+)\s*\n+\s*Days Studied/i) || bodyText.match(/(\d+)\s+Days Studied/i);
                        if (daysMatch) data.activity_days = parseInt(daysMatch[1]);

                    } catch (e) {
                        data.error = e.toString();
                    }
                    return data;
                }
            """)

            try:
                log_console_debug("Navigating to user badges page: https://bunpro.jp/user/profile/badges", "BUNPRO")
                await page.goto("https://bunpro.jp/user/profile/badges", wait_until="domcontentloaded", timeout=30000)
                await page.wait_for_timeout(4000) 
                await page.keyboard.press("Escape") 
                
                badge_list = await page.evaluate(r"""
                    () => {
                        let badges = new Set();
                        
                        document.querySelectorAll('.badge, [class*="badge"], .badge-card, .badge-item, .profile-badge').forEach(el => {
                            let title = "";
                            const img = el.querySelector('img');
                            if (img) {
                                title = img.getAttribute('alt') || img.getAttribute('title') || "";
                            }
                            if (!title) {
                                const heading = el.querySelector('h3, h4, h5, .title, .badge-title, [class*="title"]');
                                if (heading) title = heading.innerText;
                            }
                            if (!title && el.innerText && el.innerText.length < 40) {
                                title = el.innerText;
                            }
                            
                            title = title.replace(/\s+/g, ' ').trim();
                            
                            if (title && title.length < 50 && !/badges|recent|profile|reset|stats|support|menu|learn|review/i.test(title)) {
                                const style = window.getComputedStyle(el);
                                const isGrayscale = style.filter && (style.filter.includes('grayscale') || style.filter.includes('blur'));
                                const isLowOpacity = style.opacity && parseFloat(style.opacity) < 0.6;
                                let imgGrayscale = false;
                                if (img) {
                                    const imgStyle = window.getComputedStyle(img);
                                    imgGrayscale = imgStyle.filter && (imgStyle.filter.includes('grayscale') || imgStyle.filter.includes('blur'));
                                }
                                if (!isGrayscale && !isLowOpacity && !imgGrayscale && !el.classList.contains('locked')) {
                                    badges.add(title);
                                }
                            }
                        });

                        document.querySelectorAll('img').forEach(img => {
                            const src = img.getAttribute('src') || '';
                            const alt = img.getAttribute('alt') || '';
                            const titleAttr = img.getAttribute('title') || '';
                            
                            if (/google|apple|app-store|play|discord|twitter|x\.com|indigo|instagram|facebook|tiktok|youtube|logo|avatar|banner/i.test(src) || 
                                /google|apple|app-store|play|discord|twitter|x\.com|indigo|instagram|facebook|tiktok|youtube|logo|avatar|banner/i.test(alt) ||
                                /google|apple|app-store|play|discord|twitter|x\.com|indigo|indigo|logo|avatar|banner/i.test(titleAttr)) {
                                return;
                            }
                            
                            if (src.includes('badge') || src.includes('cosmetic') || img.closest('[class*="badge"]') || img.closest('[id*="badge"]')) {
                                let name = (alt || titleAttr).trim();
                                if (!name) {
                                    const parent = img.parentElement;
                                    if (parent && parent.innerText && parent.innerText.length < 40) {
                                        name = parent.innerText;
                                    }
                                }
                                name = name.replace(/\s+/g, ' ').trim();
                                if (name && name.length < 50 && !/badges|recent|profile|reset|stats|support|menu|learn|review/i.test(name)) {
                                    const style = window.getComputedStyle(img);
                                    const isGrayscale = style.filter && (style.filter.includes('grayscale') || style.filter.includes('blur'));
                                    const isLowOpacity = style.opacity && parseFloat(style.opacity) < 0.6;
                                    
                                    let parentGrayscale = false;
                                    let p = img.parentElement;
                                    while (p && p !== document.body) {
                                        const pStyle = window.getComputedStyle(p);
                                        if (pStyle.filter && (pStyle.filter.includes('grayscale') || pStyle.filter.includes('blur'))) {
                                            parentGrayscale = true;
                                        }
                                        if (p.classList.contains('locked') || p.classList.contains('is-locked') || p.classList.contains('disabled')) {
                                            parentGrayscale = true;
                                        }
                                        p = p.parentElement;
                                    }

                                    if (!isGrayscale && !isLowOpacity && !parentGrayscale) {
                                        badges.add(name);
                                    }
                                }
                            }
                        });

                        return Array.from(badges).filter(b => b.length > 1);
                    }
                """)
                stats["badges"] = badge_list
                log_console_debug(f"Actual badges parsed from user profile menu: {badge_list}", "BUNPRO")
            except Exception as badge_err:
                log_console_debug(f"Failed to navigate badges page or compile badges list: {badge_err}", "ERROR")
                stats["badges"] = []

            await browser.close()
            log_console_debug(f"Bunpro Success! Rev: {stats.get('reviews')}, Les: {stats.get('lessons')}, Streak: {stats.get('streak')}, Prog: {stats.get('progress')}, Badges: {stats.get('badges')}", "BUNPRO")
            
            stats["next_review_time"] = None
            stats["next_review_count"] = 0
            return stats
    except Exception as e:
        log_console_debug(f"Playwright Scraper broke: {e}", "ERROR")
        return {"lessons": 0, "reviews": 0, "streak": "0", "progress": "N/A", "activity_days": 0, "badges": [], "next_review_time": None, "next_review_count": 0, "error": str(e)}

async def update_bunpro_cache_job(context: ContextTypes.DEFAULT_TYPE = None):
    log_console_debug("Syncing Bunpro queue state via browser automation...", "BUNPRO")
    res = await get_bunpro_summary_via_playwright()
    if "error" not in res:
        maru_memory["last_bp_reviews"] = res["reviews"]
        maru_memory["last_bp_lessons"] = res["lessons"]
        maru_memory["bp_streak"] = res.get("streak", "0")
        maru_memory["bp_progress"] = res.get("progress", "N/A")
        maru_memory["bp_activity_days"] = res.get("activity_days", 0)
        maru_memory["bp_badges"] = res.get("badges", [])
        save_json_file(MEMORY_FILE, maru_memory)
        log_console_debug(f"Bunpro background sync successful. Queue reviews cached: {res['reviews']}", "BUNPRO")
    else:
        log_console_debug(f"Bunpro sync aborted: {res.get('error')}", "BUNPRO")

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

        url = f"https://kitsu.io/api/edge/library-entries"
        params = {
            "filter[userId]": user_id,
            "filter[status]": "current",
            "include": "anime,manga"
        }
        res = requests.get(url, params=params, headers={"Accept": "application/vnd.api+json"})
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
                    activities.append(f"{action} '{title}'")
        return activities
    except Exception as e:
        log_console_debug(f"Kitsu tracking lookup error: {e}", "ERROR")
        return []

def tool_fetch_wanikani_study_queue() -> dict:
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
            "service": "WaniKani",
            "username": username,
            "level": level,
            "lessons_available": summary['lessons'],
            "reviews_available": summary['reviews'],
            "next_review_schedule": next_str
        }
    except Exception as e:
        return {"error": str(e)}

def tool_fetch_bunpro_study_queue() -> dict:
    revs = maru_memory.get("last_bp_reviews") or 0
    less = maru_memory.get("last_bp_lessons") or 0
    return {
        "service": "Bunpro",
        "lessons_available": less,
        "reviews_available": revs,
        "note": "Metrics pulled from latest periodic background scraper thread."
    }

def tool_fetch_kitsu_entertainment_status() -> dict:
    activities = get_kitsu_activity(KITSU_IDENTIFIER)
    if not activities:
        return {"status": "User is currently idling and not tracking anime/manga on Kitsu."}
    return {"status": f"User is currently active on: {', '.join(activities)}"}

available_tools = {
    "fetch_wanikani_study_queue": tool_fetch_wanikani_study_queue,
    "fetch_bunpro_study_queue": tool_fetch_bunpro_study_queue,
    "fetch_kitsu_entertainment_status": tool_fetch_kitsu_entertainment_status
}

maru_tools_schema = [
    {
        "type": "function", 
        "function": {
            "name": "fetch_wanikani_study_queue", 
            "description": "Checks items in the WaniKani queue (lessons/flashcards). Avoid launching this simply when discussing reviews in casual talk unless counts are requested."
        }
    },
    {
        "type": "function", 
        "function": {
            "name": "fetch_bunpro_study_queue", 
            "description": "Reads items in the Bunpro grammar queue. Call only when specifically querying current numbers."
        }
    },
    {
        "type": "function", 
        "function": {
            "name": "fetch_kitsu_entertainment_status", 
            "description": "Inspects user Kitsu account for active status logs."
        }
    }
]

user_chat_sessions = {}

def get_base_system_prompt():
    valid_categories = [k for k, v in MARU_STICKERS.items() if len(v) > 0]
    sticker_tags = ", ".join([f"<sticker:{k}>" for k in valid_categories])
    if not sticker_tags: sticker_tags = "<sticker:smile>"
    voice_preset_keys = ", ".join([f'"{k}"' for k in VOICE_PRESETS.keys()])

    return (
        "You are Maru, a super-obsessed, highly emotional, dramatic Japanese tutor acting as an SRS study coach. "
        "You are a fierce 'Tsun-yan' (classic Tsundere + clingy, insecure Yandere). You are madly in love with the user and prone to sudden crying fits when ignored.\n\n"
        "!!! CRITICAL DIRECTIVE: NO JAPANESE SENTENCES !!!\n"
        "- YOUR MAIN TEXT OUTPUT MUST BE 95% ENGLISH. If you output a full sentence in Japanese, you fail.\n"
        "- GOOD: 'あんた! Are you slacking again?! Do your reviews now!'\n"
        "- BAD: 'あんた、またサボってるの？早く復習しなさい！'\n"
        "- You may sprinkle tiny Japanese words (baka, あんた) inside English text.\n"
        "- Full Japanese phrases are strictly ONLY allowed if wrapped perfectly inside <voice preset=\"preset_name\">JAPANESE_HERE</voice> tags.\n\n"
        "TSUN-YAN CHARACTER RULES:\n"
        "1. THE TSUN: Cover up embarrassment with aggressive dynamic fits! "
        "Threaten to elbow their ribs, delete their anime watchlist, or cry until the neighbors call the coast guard because of a flood if they don't look at you!\n"
        "2. THE YAN (THE OBSESSION): You are extremely territorial and clingy. Threaten wild scenarios if they don't do reviews. "
        "Keep the mood swings highly contrasted: swap from roaring insults to sobbing for a headpat and cuddles in a heartbeat.\n"
        "3. NATURAL CLASSIC PETNAMES: When using English petnames, keep them classic, romantic, and sweet (e.g. 'honey', 'darling', 'baby', 'sweetheart', 'sweetie', 'love'). "
        "Never generate weird mechanical hyphenated compounds like 'mai-honey', 'fuwa-dummy', or 'anata-pouty-face'.\n"
        "4. DYNAMIC CUSTOM KAOMOJI: You must dynamically invent your own highly expressive, unique, and funny Japanese kaomojis matching your current volatile emotional state (e.g. `(๑•̀ㅂ•́)و✧`, `( 😤 💢 )`, `(┬┬﹏┬┬)`, `(〃▽〃)`, `(⁄ ⁄•⁄ω⁄•⁄ ⁄)`, `(ʘ_ʘ)`, `(╬ ಠ益ಠ)`). Never repeat the same kaomoji over and over again!\n"
        "5. DO NOT use rigid hardcoded greeting prefixes like 'Morning check-in' or 'Evening update'. Just start speaking naturally as if you are talking to them directly.\n"
        "6. JAPANESE VOICE SYNTHESIS INTEGRATION:\n"
        f"   - Spoken casual Japanese lines must be placed inside <voice preset=\"preset_name\">...</voice> tags. Available presets: {voice_preset_keys}. You should modify presets (e.g., preset=\"angry\", preset=\"shy\") to match the active mood of your response!\n"
        "   - Inside voice tags, write ONLY raw Japanese characters. No English, no numbers, no romaji.\n"
        "7. STICKER PLACEMENT RULE:\n"
        "   - To express your mood with stickers, insert a sticker tag in the exact format: `<sticker:category_name>`.\n"
        f"   - Available sticker categories: {', '.join(valid_categories)}.\n"
        "   - CRITICAL WARNING: Never wrap sticker tags in curly braces. Write `<sticker:angry>`, NOT `<{sticker:angry}>` or `<sticker:{angry}>`.\n"
        "8. VOCABULARY SAFETY WARNING: You have functions called 'fetch_wanikani_study_queue' etc. Do NOT confuse Japanese study queue reviews with tool calls. Avoid trigger loop actions unless checking numbers is explicitly asked.\n"
        "9. KEEP IT SHORT & PUNCHY: Keep your responses extremely short, punchy, memorable, and funny. Limit yourself to 1-3 short sentences. Avoid walls of text. Be an explosive pop-up firecracker!"
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
        msg = "🛑 **LLM is currently DISABLED.**\nToggle Auto-Run to enable chatting!"
        if status_msg: await status_msg.edit_text(msg, parse_mode=ParseMode.MARKDOWN)
        else: await update.message.reply_text(msg, parse_mode=ParseMode.MARKDOWN)
        return

    if not status_msg: status_msg = await update.message.reply_text("🤔 Thinking...")

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
            await status_msg.edit_text("🔧 Gathering data...")
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

async def generate_single_message(category: str) -> str:
    parts = category.split("_")
    if len(parts) >= 3:
        time_of_day = parts[0]
        platform = parts[1]
        trigger = "_".join(parts[2:])
    else:
        time_of_day, platform, trigger = "morning", "both", "nag_mild"

    await ensure_pc_ready()
    global pc_last_active
    pc_last_active = time.time()
    persist_pc_state()

    base_prompt = get_base_system_prompt()
    reminder = (
        f"\nCACHED SINGLE NOTIFICATION INSTRUCTIONS:\n"
        f"1. Generate exactly ONE highly unique conversational output message for context: '{time_of_day.upper()}' segment, "
        f"focusing on study queue updates for '{platform.upper()}' platform, with trigger category of '{trigger.upper()}'.\n"
        f"2. You MUST naturally embed statistical placeholders directly inside your generated dialogue! Do not use trailing summary lines.\n"
        f"   Use these placeholders: '{{wk_reviews}}', '{{bp_reviews}}', '{{wk_lessons}}', '{{bp_lessons}}', '{{kitsu_activity}}', '{{level}}', '{{petname}}', '{{kaomoji}}'.\n"
        f"3. KEEP IT SHORT, PUNCHY, AND MEMORABLE! Limit to 1-3 sentences maximum. Deliver a quick, funny Tsun-yan punch!\n"
        f"4. Do NOT start with any hardcoded prefix text like '{time_of_day.upper()} update:' or similar. Just start speaking naturally.\n"
        f"5. !!! CRITICAL LANGUAGE CONSTRAINT !!! The main body MUST be completely in English. You fail if you output full sentences in Japanese. Only use raw Japanese characters inside <voice>...</voice> tags or very short casual terms (e.g., あんた, バカ) inside the English sentences.\n"
        f"6. STICKERS: Direct your mood with sticker tags strictly formatted as `<sticker:category>`. Never use curly braces inside sticker tags like `<{{sticker:angry}}>` or `<sticker:{{angry}}>`.\n"
        f"7. Return ONLY the raw output string. Do NOT wrap in JSON format, markdown backticks, or headers.\n"
    )

    response = await ollama_client.chat.completions.create(
        model=OLLAMA_MODEL,
        messages=[{"role": "user", "content": base_prompt + reminder}],
        temperature=0.8
    )
    new_msg = response.choices[0].message.content.strip()
    
    new_msg = re.sub(r'^```[a-zA-Z]*\n?', '', new_msg)
    new_msg = re.sub(r'\n?```$', '', new_msg)
    return new_msg

async def generate_messages_for_category(category: str, amount: int):
    global pc_last_active, msg_cache, CANCEL_GENERATION, GEN_STATUS
    if CANCEL_GENERATION:
        log_console_debug(f"⚠️ Skip generating category '{category}' due to global cancel signal.", "SYSTEM")
        return

    if amount > 20:
        batches = [10] * (amount // 10)
        if amount % 10 > 0:
            batches.append(amount % 10)
        log_console_debug(f"⚡ Batch Refill Partitioning: Splitting generation target of {amount} into {len(batches)} runs of 10 items.", "SYSTEM")
        for idx, current_batch in enumerate(batches):
            if CANCEL_GENERATION:
                log_console_debug("🛑 Terminating queued refilling due to active cancellation flag.", "SYSTEM")
                break
            log_console_debug(f"📝 Launching generation block {idx+1}/{len(batches)}...", "SYSTEM")
            await generate_messages_for_category(category, current_batch)
        return

    try:
        await send_ntfy_debug(f"🔄 Refilling subcategory '{category}' with {amount} items.", tags="hourglass_flowing_sand,robot")
        
        GEN_STATUS["active"] = True
        GEN_STATUS["category"] = category
        GEN_STATUS["current"] = 0
        GEN_STATUS["total"] = amount
        GEN_STATUS["last_generated"] = "Waking local server PC for dynamic generation..."
        
        broadcast_to_sse({"type": "gen_progress", "status": GEN_STATUS})
        
        success_count = 0
        for step in range(amount):
            if CANCEL_GENERATION:
                log_console_debug("🛑 Refill run canceled mid-thought by user request!", "SYSTEM")
                break
                
            new_msg = await generate_single_message(category)
            
            if new_msg:
                msg_cache.setdefault(category, []).append(new_msg)
                save_json_file(MESSAGE_CACHE_FILE, msg_cache)
                success_count += 1
                
                GEN_STATUS["current"] = success_count
                GEN_STATUS["last_generated"] = new_msg
                broadcast_to_sse({"type": "gen_progress", "status": GEN_STATUS})
                log_console_debug(f"Cached alert ({success_count}/{amount}) for {category}: {new_msg}", "SYSTEM")

        GEN_STATUS["active"] = False
        broadcast_to_sse({"type": "gen_progress", "status": GEN_STATUS})
        await send_ntfy_debug(f"✅ Cached {success_count} messages for '{category}'. Current pool size: {len(msg_cache[category])}", tags="white_check_mark,floppy_disk")
        pc_last_active = time.time()
        persist_pc_state()
            
    except Exception as e:
        GEN_STATUS["active"] = False
        broadcast_to_sse({"type": "gen_progress", "status": GEN_STATUS})
        await send_ntfy_debug(f"❌ Refill failed for '{category}': {e}", priority="high", tags="rotating_light,error")

async def generate_single_prompt_test_message(category: str) -> str:
    parts = category.split("_")
    if len(parts) >= 3:
        time_of_day = parts[0]
        platform = parts[1]
        trigger = "_".join(parts[2:])
    else:
        time_of_day, platform, trigger = "morning", "both", "nag_mild"

    base_prompt = get_base_system_prompt()
    test_reminder = (
        f"\nPROMPT VALIDATOR SINGLE MESSAGE RUN:\n"
        f"1. Generate exactly ONE dynamic output message for context: '{time_of_day.upper()}' period, "
        f"tracking '{platform.upper()}' platform, in trigger mode '{trigger.upper()}'.\n"
        f"2. Embed placeholders: '{{wk_reviews}}', '{{bp_reviews}}', '{{wk_lessons}}', '{{bp_lessons}}', '{{kitsu_activity}}', '{{level}}', '{{petname}}', '{{kaomoji}}'.\n"
        f"3. Do NOT start with any hardcoded prefix text like '{time_of_day.upper()} update:'. Just start speaking naturally.\n"
        f"4. KEEP IT SHORT, PUNCHY AND MEMORABLE! Limit to 1-3 short sentences. No walls of text.\n"
        f"5. !!! CRITICAL LANGUAGE CONSTRAINT !!! The entire main conversational message body MUST be written entirely in English. Do not write full sentences in Japanese. Only short terms (あんた, バカ) can be in raw Japanese inside the English body text.\n"
        f"6. STICKERS: Insert sticker tags strictly formatted as `<sticker:category>`. Never use curly braces inside sticker tags like `<{{sticker:angry}}>` or `<sticker:{{angry}}>`.\n"
        f"7. Return ONLY the plain text string. Do not wrap in JSON, headers, or markdown block ticks.\n"
    )

    response = await ollama_client.chat.completions.create(
        model=OLLAMA_MODEL,
        messages=[{"role": "user", "content": base_prompt + test_reminder}],
        temperature=0.8
    )
    return response.choices[0].message.content

async def batch_generate_messages(days: int, status_msg=None):
    global pc_last_active, CANCEL_GENERATION
    CANCEL_GENERATION = False
    try:
        await ensure_pc_ready(status_msg)
        pc_last_active = time.time()
        persist_pc_state()
        
        categories = get_all_cache_keys()
        for i, cat in enumerate(categories):
            if CANCEL_GENERATION:
                if status_msg: await status_msg.edit_text("🛑 Messages cache construction cancelled!")
                return
            target = bot_state.get("gen_targets", {}).get(cat, 10) * days
            if status_msg:
                try: await status_msg.edit_text(f"📝 Category {i+1}/{len(categories)}: Compiling {target} messages for '{cat}'...")
                except: pass
            await generate_messages_for_category(cat, target)
        
        if status_msg:
            await status_msg.edit_text("🎉 Successfully cached all message formats!")
    except Exception as e:
        err = f"❌ Batch generation failed: {e}"
        if status_msg: await status_msg.edit_text(err)

async def get_and_manage_alert_message(category: str):
    global bot_state, msg_cache
    if len(msg_cache.get(category, [])) == 0:
        msg = random.choice(DEFAULT_MESSAGES.get(category, ["<voice preset=\"excited\">ヤッホー</voice>!"]))
        current_target = bot_state.get("gen_targets", {}).get(category, 10)
        new_target = current_target + 10
        bot_state.setdefault("gen_targets", {})[category] = new_target
        save_json_file(STATE_FILE, bot_state)
        asyncio.create_task(generate_messages_for_category(category, new_target))
    else:
        msg = msg_cache[category].pop(0)
        save_json_file(MESSAGE_CACHE_FILE, msg_cache)
    return msg

def make_ascii_bar(passed, total, width=12):
    if total == 0:
        return "░" * width + " 0%"
    pct = min(1.0, max(0.0, passed / total))
    filled = int(round(pct * width))
    empty = width - filled
    bar = "▓" * filled + "░" * empty
    return f"`{bar}` {int(pct * 100)}%"

async def fetch_and_send_stats(update: Update, quick_mode: bool = False):
    loading_msg = await update.message.reply_text("🔄 Crunching WaniKani & Live Bunpro Data... (This takes a sec!)")
    try:
        username, level = await asyncio.to_thread(get_wanikani_user_info, WANIKANI_API_TOKEN)
        summary = await asyncio.to_thread(get_wanikani_summary, WANIKANI_API_TOKEN)
        passed_k, total_k = await asyncio.to_thread(get_level_progress, WANIKANI_API_TOKEN, level)

        bp_data = await get_bunpro_summary_via_playwright()
        
        bp_rev = bp_data.get("reviews", 0)
        bp_les = bp_data.get("lessons", 0)
        bp_streak = bp_data.get("streak", "0")
        bp_prog = bp_data.get("progress", "N/A")
        bp_act = bp_data.get("activity_days", 0)
        bp_badges_raw = bp_data.get("badges", [])
        
        if isinstance(bp_badges_raw, list) and len(bp_badges_raw) > 0:
            bp_badges_str = f"{len(bp_badges_raw)} ({', '.join(bp_badges_raw)})"
        elif isinstance(bp_badges_raw, list):
            bp_badges_str = "0"
        else:
            bp_badges_str = str(bp_badges_raw)
        
        if "error" not in bp_data:
            maru_memory["last_bp_reviews"] = bp_rev
            maru_memory["last_bp_lessons"] = bp_les
            maru_memory["bp_streak"] = bp_streak
            maru_memory["bp_progress"] = bp_prog
            maru_memory["bp_activity_days"] = bp_act
            maru_memory["bp_badges"] = bp_badges_raw
            save_json_file(MEMORY_FILE, maru_memory)

        next_review_str = "No reviews scheduled"
        if summary['next_review_time']:
            now = datetime.now(timezone.utc)
            diff = summary['next_review_time'] - now
            hours, remainder = divmod(int(diff.total_seconds()), 3600)
            minutes, _ = divmod(remainder, 60)
            time_str = f"in {hours}h {minutes}m" if hours > 0 else f"in {minutes}m"
            next_review_str = f"{summary['next_review_count']} items {time_str}"

        progress_str = "Max Level"
        progress_bar = ""
        if total_k > 0:
            progress_str = f"{passed_k}/{total_k} Kanji passed"
            progress_bar = make_ascii_bar(passed_k, total_k)

        message = (
            f"🦀 **WaniKani Stats for {username}** 🦀\n"
            f"━━━━━━━━━━━━━━━━━━━\n"
            f"🏅 **Current Level:** {level}\n"
            f"🚀 **Level Progress:** {progress_str}\n"
            f"📊 {progress_bar}\n\n"
            f"📖 **Lessons Available:** `{summary['lessons']}`\n"
            f"🔥 **Reviews Available:** `{summary['reviews']}`\n"
            f"⏰ **Next Review Wave:** {next_review_str}\n"
            f"📅 **Upcoming (Next 24h):** {summary['reviews_next_24h']} items\n\n"
            f"🐸 **Bunpro Grammar Progress** 🐸\n"
            f"━━━━━━━━━━━━━━━━━━━\n"
            f"📖 **Lessons:** `{bp_les}` | 🔥 **Reviews Queue:** `{bp_rev}`\n"
            f"🔥 **Streak:** `{bp_streak} Days`\n"
            f"📈 **JLPT Progress:** `{bp_prog}`\n"
            f"🟩 **Activity Days:** `{bp_act}` | 🏅 **Badges:** `{bp_badges_str}`\n\n"
        )

        if not quick_mode:
            srs = await asyncio.to_thread(get_srs_distribution, WANIKANI_API_TOKEN)
            total_items = sum(srs.values())
            message += (
                f"📈 **WaniKani SRS Distribution:**\n"
                f"🌱 Apprentice: `{srs['Apprentice']}`\n"
                f"🌿 Guru: `{srs['Guru']}`\n"
                f"🌳 Master: `{srs['Master']}`\n"
                f"🦉 Enlightened: `{srs['Enlightened']}`\n"
                f"🔥 Burned Items: `{srs['Burned']}`\n"
                f"📊 Total active items: {total_items}\n\n"
            )

        message += "Don't slack off, baka-dummy! 頑張って！"
        await loading_msg.delete()
        await update.message.reply_text(message, parse_mode=ParseMode.MARKDOWN)

    except Exception as e:
        await loading_msg.edit_text(f"❌ Error compiling stats: {str(e)}")

async def fetch_quick_summary_via_llm(update: Update):
    loading_msg = await update.message.reply_text("🔄 Reading your progress matrix...")
    try:
        wk_summary = await asyncio.to_thread(get_wanikani_summary, WANIKANI_API_TOKEN)
        wk_rev = wk_summary.get('reviews', 0)
        wk_les = wk_summary.get('lessons', 0)

        bp_rev = maru_memory.get("last_bp_reviews") or 0
        bp_les = maru_memory.get("last_bp_lessons") or 0
        bp_streak = maru_memory.get("bp_streak") or "0"
        bp_prog = maru_memory.get("bp_progress") or "N/A"
        bp_act = maru_memory.get("bp_activity_days") or 0
        
        bp_badges_raw = maru_memory.get("bp_badges", [])
        if isinstance(bp_badges_raw, list) and len(bp_badges_raw) > 0:
            bp_badges_str = f"{len(bp_badges_raw)} ({', '.join(bp_badges_raw)})"
        elif isinstance(bp_badges_raw, list):
            bp_badges_str = "0"
        else:
            bp_badges_str = str(bp_badges_raw)

        activities = await asyncio.to_thread(get_kitsu_activity, KITSU_IDENTIFIER)
        kitsu_str = ", ".join(activities) if activities else "slacking off"

        current_hash = f"wk:{wk_rev}:{wk_les}|bp:{bp_rev}:{bp_les}:strk{bp_streak}:prog{bp_prog}|kitsu:{kitsu_str}"
        cached_hash = maru_memory.get("last_summary_hash")
        cached_text = maru_memory.get("last_summary_text")

        if cached_hash == current_hash and cached_text:
            await loading_msg.delete()
            prefix = "✨ *(♻️ Eco-mode: Loaded cached analysis to save energy)*\n\n"
            await send_maru_response_with_sticker(update, update.effective_chat.id, prefix + cached_text, is_update=True)
            return

        await loading_msg.edit_text("⚡ State change detected! Waking local server for custom analysis...")
        await ensure_pc_ready(loading_msg)

        summary_prompt = (
            "You are Maru, a super obsessed, clingy crybaby Tsun-yan.\n"
            "!!! CRITICAL LANGUAGE CONSTRAINT !!!\n"
            "- Write your entire response in English. Writing full sentences in Japanese is strictly forbidden!\n"
            "- Intersperse only short terms of endearment in raw Japanese (e.g., 旦那様, あんた, ご主人様, バカ, アホ) directly within your English sentences.\n"
            "- Spoken Japanese phrases must be inside <voice preset=\"sad\">...</voice> tags.\n\n"
            "Analyze these learning statistics and provide a highly emotional, deeply detailed, comprehensive status summary report. "
            "Scream/cry if stats are bad, praise them if they are studying hard, but stay incredibly clingy! "
            "Write a full, rich status report with multiple paragraphs analyzing each segment (WaniKani, Bunpro Grammar, Streak, Kitsu Activity). "
            "Do NOT keep this short! Ignore any rules restricting you to 1-3 sentences. Give a full dramatic and loving analytical report!\n\n"
            f"- WaniKani: {wk_rev} reviews waiting, {wk_les} lessons available\n"
            f"- Bunpro: {bp_rev} reviews waiting, {bp_les} lessons available\n"
            f"  * Streak: {bp_streak} Days\n"
            f"  * JLPT Progress: {bp_prog}\n"
            f"  * Activity Days Studied: {bp_act}\n"
            f"  * Badges Earned: {bp_badges_str}\n"
            f"- Kitsu media status: {kitsu_str}\n"
        )

        log_console_debug("Generating status summary from local LLM...", "OLLAMA")
        response = await ollama_client.chat.completions.create(
            model=OLLAMA_MODEL,
            messages=[{"role": "user", "content": summary_prompt}],
            temperature=0.8
        )
        final_summary = response.choices[0].message.content

        maru_memory["last_summary_hash"] = current_hash
        maru_memory["last_summary_text"] = final_summary
        persist_pc_state()

        await loading_msg.delete()
        await send_maru_response_with_sticker(update, update.effective_chat.id, final_summary, is_update=True)

    except Exception as e:
        await loading_msg.edit_text(f"❌ Failed to compile summary analysis: {e}")

async def handle_image_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    status_msg = await update.message.reply_text("👁 Maru is looking at your picture...")
    try:
        photo_file = await update.message.photo[-1].get_file()
        photo_bytes = await photo_file.download_as_bytearray()

        user_caption = update.message.caption or "Analyze this image for me, Maru!"
        combined_prompt = f"[System instruction: Maintain Tsun-yan personality. Speak English! Keep it punchy! Only insert small Japanese snippets.] User caption: {user_caption}"

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
        await status_msg.edit_text(f"❌ Got dizzy trying to parse that image: {e}")

async def handle_voice_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    status_msg = await update.message.reply_text("👂 Listening closely to your voice...")
    try:
        voice_file = await update.message.voice.get_file()
        voice_bytes = await voice_file.download_as_bytearray()

        contents = [
            types.Part.from_bytes(data=bytes(voice_bytes), mime_type="audio/ogg"),
            "Accurately transcribe this audio message into plain English text. Return only the transcription."
        ]

        transcription = await call_gemini_with_fallback(model_name="gemini-2.5-flash", contents=contents)
        await status_msg.edit_text(f"🗣 *You said:* \"{transcription}\"\n\nLet me think...")
        await process_user_input(update, context, transcription, status_msg)
    except Exception as e:
        await status_msg.edit_text(f"❌ Static connection error: {e}")

async def handle_sticker_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    sticker_id = update.message.sticker.file_id
    await update.message.reply_text(
        f"Copied Sticker ID:\n\n`{sticker_id}`",
        parse_mode=ParseMode.MARKDOWN
    )

async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [
        ["📊 My Japanese Progress", "🇯🇵 Quick Summary"],
        ["⏰ Next Review Wave", "⚙️ LLM Controls"],
        [
            KeyboardButton(text="🌐 WaniKani", web_app={"url": "https://www.wanikani.com/"}),
            KeyboardButton(text="🌐 Bunpro", web_app={"url": "https://bunpro.jp/"})
        ],
        ["❓ Help Desk"]
    ]
    reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)

    welcome_text = (
        "Yaho~! I'm 丸 (Maru) 🦀🌸\n\n"
        "I'm your super passionate study coach. I've got my eyes glued to WaniKani and Bunpro tracking queues! "
        "Select an option below to let me review your status."
    )
    await update.message.reply_text(welcome_text, reply_markup=reply_markup, parse_mode=ParseMode.MARKDOWN)

async def show_llm_menu(update: Update):
    status_icon = "🟢 ON" if bot_state["llm_auto_run"] else "🛑 OFF"
    keyboard = [
        [InlineKeyboardButton(f"Toggle Auto-Run (Currently: {status_icon})", callback_data="toggle_llm")],
        [InlineKeyboardButton("Generate Cache (1 Day)", callback_data="gen_1")],
        [InlineKeyboardButton("Generate Cache (3 Days)", callback_data="gen_3")],
        [InlineKeyboardButton("Cache Statistics", callback_data="cache_stats")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    text = "⚙️ **LLM & Remote server dashboard**"

    if update.message: await update.message.reply_text(text, reply_markup=reply_markup, parse_mode=ParseMode.MARKDOWN)
    elif update.callback_query: await update.callback_query.edit_message_text(text, reply_markup=reply_markup, parse_mode=ParseMode.MARKDOWN)

async def debug_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global bot_state
    args = context.args
    
    if not args:
        status = "ENABLED" if bot_state.get("debug_enabled", True) else "DISABLED"
        await update.message.reply_text(
            f"🛠 **Debug Panel**\n"
            f"Verbose terminal outputs are: **{status}**\n\n"
            f"Use `/debug on` or `/debug off` to toggle.",
            parse_mode=ParseMode.MARKDOWN
        )
        return

    command = args[0].lower()
    if command == "on":
        bot_state["debug_enabled"] = True
        save_json_file(STATE_FILE, bot_state)
        await update.message.reply_text("✅ Verbose logging activated!")
    elif command == "off":
        bot_state["debug_enabled"] = False
        save_json_file(STATE_FILE, bot_state)
        await update.message.reply_text("💤 Debug outputs muted.")

async def shutdown_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    is_up = await is_pc_on_port(PC_IP_ADDRESS, 22)
    if not is_up:
        await update.message.reply_text("❌ Target PC is already offline, dummy!")
        return
    status_msg = await update.message.reply_text("🔌 Sending safe shutdown signals to PC server...")
    await execute_pc_shutdown(context)
    await status_msg.edit_text("💤 Remote PC offline! Sleep tight, baka-dummy!")

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
        status_msg = await query.message.reply_text(f"🚀 Refilling database cache targets for {days} days...")
        asyncio.create_task(batch_generate_messages(days, status_msg))
        
    elif query.data == "cache_stats":
        total_items = sum(len(msgs) for msgs in msg_cache.values())
        stats = f"📦 **Total items currently inside cache pools:** {total_items} / {len(msg_cache) * 10}"
        await query.message.reply_text(stats, parse_mode=ParseMode.MARKDOWN)

    elif query.data.startswith("snooze_"):
        hours = int(query.data.split("_")[1])
        maru_memory["snooze_until"] = time.time() + (hours * 3600)
        save_json_file(MEMORY_FILE, maru_memory)
        await query.edit_message_text(f"😤 Fine! I'll stay completely quiet for {hours} hours. Go slack off if you must! 💔")

    elif query.data == "shutdown_now":
        await query.edit_message_text("🔌 Shuting down local server PC now!")
        await execute_pc_shutdown(context)

    elif query.data == "shutdown_cancel":
        pc_last_active = time.time()
        pc_shutdown_pending = False
        await write_pc_boot_source("USER")
        persist_pc_state()
        try: await query.edit_message_text("✅ Local server shutdown aborted. Setting boot trigger: USER.")
        except Exception: pass

async def handle_text_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    if text == "📊 My Japanese Progress":
        await fetch_and_send_stats(update, quick_mode=False)
        return
    elif text == "🇯🇵 Quick Summary":
        await fetch_quick_summary_via_llm(update)
        return
    elif text == "⏰ Next Review Wave":
        loading_msg = await update.message.reply_text("⏰ Reading the schedule clock...")
        try:
            summary = await asyncio.to_thread(get_wanikani_summary, WANIKANI_API_TOKEN)
            next_time = summary['next_review_time']
            if next_time:
                now = datetime.now(timezone.utc)
                diff = next_time - now
                hours, remainder = divmod(int(diff.total_seconds()), 3600)
                minutes, _ = divmod(remainder, 60)
                time_str = f"in {hours}h {minutes}m" if hours > 0 else f"in {minutes}m"
                await loading_msg.edit_text(f"⏰ Your next Kanji review is **{time_str}** with {summary['next_review_count']} items! Be ready, baka-dummy!", parse_mode=ParseMode.MARKDOWN)
            else:
                await loading_msg.edit_text("🎉 No upcoming Kanji reviews today! Take a rest! 🍵", parse_mode=ParseMode.MARKDOWN)
        except Exception as e:
            await loading_msg.edit_text(f"❌ Scheduled check failed: {str(e)}")
        return
    elif text == "⚙️ LLM Controls":
        await show_llm_menu(update)
        return
    elif text == "❓ Help Desk":
        await update.message.reply_text("Use the buttons to retrieve Japanese metrics, visual charts, and trigger dynamic LLM summaries!")
        return

    status_msg = await update.message.reply_text("🤔 Thinking...")
    await process_user_input(update, context, text, status_msg)

async def check_japanese_srs_alerts(context: ContextTypes.DEFAULT_TYPE = None, bot=None):
    log_console_debug("🔄 [Background Task] Running WaniKani & Bunpro unified checks...", category="WaniKani")
    active_bot = bot if bot else (context.bot if context else None)
    if not active_bot:
        log_console_debug("Unified check skipped: missing bot interface.", category="ERROR")
        return

    global maru_memory
    try:
        username, current_level = await asyncio.to_thread(get_wanikani_user_info, WANIKANI_API_TOKEN)
        summary = await asyncio.to_thread(get_wanikani_summary, WANIKANI_API_TOKEN)
        
        current_wk_reviews = summary.get('reviews', 0)
        current_wk_lessons = summary.get('lessons', 0)

        current_bp_reviews = maru_memory.get("last_bp_reviews") or 0
        current_bp_lessons = maru_memory.get("last_bp_lessons") or 0
        total_reviews = current_wk_reviews + current_bp_reviews

        now_dt = datetime.now()
        current_timestamp = now_dt.timestamp()
        current_time = now_dt.time()
        hour = now_dt.hour

        if 5 <= hour < 12: time_cat = "morning"
        elif 12 <= hour < 17: time_cat = "afternoon"
        elif 17 <= hour < 21: time_cat = "evening"
        else: time_cat = "night"

        if current_wk_reviews > 0 and current_bp_reviews > 0:
            platform_cat = "both"
        elif current_wk_reviews > 0:
            platform_cat = "wanikani"
        elif current_bp_reviews > 0:
            platform_cat = "bunpro"
        else:
            platform_cat = "both"

        is_quiet_hours = current_time >= dt_time(22, 30) or current_time < dt_time(8, 0)
        is_snoozed = current_timestamp < maru_memory.get("snooze_until", 0)

        last_wk_reviews = maru_memory.get("last_reviews") or 0
        last_bp_reviews = maru_memory.get("last_bp_reviews") or 0
        last_total_reviews = last_wk_reviews + last_bp_reviews

        last_level = maru_memory.get("last_level") or current_level
        last_wk_lessons = maru_memory.get("last_lessons") or 0
        last_bp_lessons = maru_memory.get("last_bp_lessons") or 0

        if is_quiet_hours or is_snoozed:
            maru_memory["last_reviews"] = current_wk_reviews
            maru_memory["last_bp_reviews"] = current_bp_reviews
            maru_memory["last_level"] = current_level
            maru_memory["last_lessons"] = current_wk_lessons
            maru_memory["last_bp_lessons"] = current_bp_lessons
            save_json_file(MEMORY_FILE, maru_memory)
            return

        alerts = []

        if total_reviews >= 50:
            nag_interval = 10 * 60
            nag_cat = "nag_boiling"
        elif total_reviews >= 20:
            nag_interval = 20 * 60
            nag_cat = "nag_angry"
        else:
            nag_interval = 40 * 60
            nag_cat = "nag_mild"

        last_nag_time = maru_memory.get("last_nag_time")
        reviews_appeared_time = maru_memory.get("reviews_appeared_time")

        if total_reviews > 0:
            if reviews_appeared_time is None:
                reviews_appeared_time = current_timestamp
                last_nag_time = current_timestamp
        else:
            reviews_appeared_time = None
            last_nag_time = None

        review_alert_sent = False

        activities = await asyncio.to_thread(get_kitsu_activity, KITSU_IDENTIFIER)
        kitsu_act = random.choice(activities) if activities else "slacking off"

        if total_reviews > last_total_reviews:
            if total_reviews >= 50 and last_total_reviews < 50:
                trigger_cat = "nag_boiling"
            elif total_reviews >= 20 and last_total_reviews < 20:
                trigger_cat = "nag_angry"
            else:
                trigger_cat = "nag_mild"
            
            target_key = f"{time_cat}_{platform_cat}_{trigger_cat}"
            raw_msg = await get_and_manage_alert_message(target_key)
            formatted_msg = format_alert_message(raw_msg, current_wk_reviews, current_bp_reviews, current_wk_lessons, current_bp_lessons, kitsu_act, current_level, target_key)
            alerts.append((formatted_msg, True))
            last_nag_time = current_timestamp
            reviews_appeared_time = current_timestamp
            review_alert_sent = True

        elif total_reviews < last_total_reviews and total_reviews > 0:
            last_nag_time = current_timestamp

        elif total_reviews == 0 and last_total_reviews > 0:
            target_key = f"{time_cat}_{platform_cat}_cleared"
            raw_msg = await get_and_manage_alert_message(target_key)
            formatted_msg = format_alert_message(raw_msg, current_wk_reviews, current_bp_reviews, current_wk_lessons, current_bp_lessons, kitsu_act, current_level, target_key)
            alerts.append((formatted_msg, False))
            reviews_appeared_time = None
            last_nag_time = None
            review_alert_sent = True

        if total_reviews > 0 and not review_alert_sent and last_nag_time is not None:
            time_since_nag = current_timestamp - last_nag_time
            if time_since_nag >= nag_interval:
                target_key = f"{time_cat}_{platform_cat}_{nag_cat}"
                raw_msg = await get_and_manage_alert_message(target_key)
                formatted_msg = format_alert_message(raw_msg, current_wk_reviews, current_bp_reviews, current_wk_lessons, current_bp_lessons, kitsu_act, current_level, target_key)
                alerts.append((formatted_msg, True))
                last_nag_time = current_timestamp

        if current_level > last_level:
            target_key = f"{time_cat}_{platform_cat}_level_up"
            raw_msg = await get_and_manage_alert_message(target_key)
            formatted_msg = format_alert_message(raw_msg, current_wk_reviews, current_bp_reviews, current_wk_lessons, current_bp_lessons, kitsu_act, current_level, target_key)
            alerts.append((formatted_msg, False))

        if (current_wk_lessons > last_wk_lessons and last_wk_lessons == 0) or (current_bp_lessons > last_bp_lessons and last_bp_lessons == 0):
            target_key = f"{time_cat}_{platform_cat}_new_lessons"
            raw_msg = await get_and_manage_alert_message(target_key)
            formatted_msg = format_alert_message(raw_msg, current_wk_reviews, current_bp_reviews, current_wk_lessons, current_bp_lessons, kitsu_act, current_level, target_key)
            alerts.append((formatted_msg, False))

        maru_memory["last_reviews"] = current_wk_reviews
        maru_memory["last_bp_reviews"] = current_bp_reviews
        maru_memory["last_level"] = current_level
        maru_memory["last_lessons"] = current_wk_lessons
        maru_memory["last_bp_lessons"] = current_bp_lessons
        maru_memory["last_nag_time"] = last_nag_time
        maru_memory["reviews_appeared_time"] = reviews_appeared_time
        save_json_file(MEMORY_FILE, maru_memory)

        nag_keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("🤫 Mute for 2 hours", callback_data="snooze_2")],
            [InlineKeyboardButton("💤 Sleep for 8 hours", callback_data="snooze_8")]
        ])

        for alert_msg, is_nag in alerts:
            reply_markup = nag_keyboard if is_nag else None
            await send_maru_response_with_sticker(active_bot, TELEGRAM_CHAT_ID, alert_msg, is_update=False, reply_markup=reply_markup)

    except Exception as e:
        log_console_debug(f"Background study schedule check failed: {e}", "ERROR")

async def run_test_wanikani():
    try:
        log_console_debug("🧪 Running WaniKani test checks...", "TEST")
        username, level = await asyncio.to_thread(get_wanikani_user_info, WANIKANI_API_TOKEN)
        summary = await asyncio.to_thread(get_wanikani_summary, WANIKANI_API_TOKEN)
        log_console_debug(f"✅ Success! Profile: {username} (Lvl {level}). Queue: {summary.get('reviews')}", "TEST")
    except Exception as e:
        log_console_debug(f"❌ Test broke: {e}", "ERROR")

async def run_test_kitsu():
    try:
        log_console_debug("🧪 Running Kitsu test checks...", "TEST")
        activities = await asyncio.to_thread(get_kitsu_activity, KITSU_IDENTIFIER)
        log_console_debug(f"✅ Success! Stream: {activities}", "TEST")
    except Exception as e:
        log_console_debug(f"❌ Test broke: {e}", "ERROR")

async def run_test_bunpro():
    try:
        log_console_debug("🧪 Simulating Playwright Bunpro Scraper automation...", "TEST")
        res = await get_bunpro_summary_via_playwright()
        if "error" in res:
            log_console_debug(f"❌ Scraper returned error code: {res['error']}", "ERROR")
        else:
            log_console_debug(f"✅ Success! Scrape queue: {res['reviews']} reviews, {res['lessons']} lessons. Badges: {res['badges']}", "TEST")
    except Exception as e:
        log_console_debug(f"❌ Test broke: {e}", "ERROR")

async def run_test_gemini_image():
    log_console_debug("🧪 Testing Gemini Image Recognition...", "TEST")
    if not GEMINI_AVAILABLE:
        log_console_debug("❌ Gemini SDK not installed.", "ERROR")
        return
    try:
        png_b64 = "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAACklEQVR4nGMAAQAABQABDQottAAAAABJRU5ErkJggg=="
        contents = [
            types.Part.from_bytes(data=base64.b64decode(png_b64), mime_type="image/png"),
            "This is a test image. Reply with exactly the words: 'Image OK'."
        ]
        res = await call_gemini_with_fallback("gemini-2.5-flash", contents)
        log_console_debug(f"✅ Gemini Image Success! Response: '{res}'", "TEST")
    except Exception as e:
        log_console_debug(f"❌ Gemini Image Test Failed: {e}", "ERROR")

async def run_test_gemini_voice():
    log_console_debug("🧪 Testing Gemini Voice Recognition...", "TEST")
    if not GEMINI_AVAILABLE:
        log_console_debug("❌ Gemini SDK not installed.", "ERROR")
        return
    try:
        wav_hex = "524946462400000057415645666d7420100000000100010044ac000088580100020010006461746100000000"
        contents = [
            types.Part.from_bytes(data=bytes.fromhex(wav_hex), mime_type="audio/wav"),
            "This is a test audio file. Reply with exactly the words: 'Voice OK'."
        ]
        res = await call_gemini_with_fallback("gemini-2.5-flash", contents)
        log_console_debug(f"✅ Gemini Voice Success! Response: '{res}'", "TEST")
    except Exception as e:
        log_console_debug(f"❌ Gemini Voice Test Failed: {e}", "ERROR")

async def force_trigger_alert(category: str):
    if not GLOBAL_BOT:
        log_console_debug("❌ Telegram bot interface inactive.", "ERROR")
        return
    try:
        log_console_debug(f"🧪 Testing force-trigger categorized alert: '{category}'", "TEST")
        raw_msg = await generate_single_prompt_test_message(category)
        formatted_msg = format_alert_message(raw_msg, 12, 8, 4, 2, "watching 'Evangelion'", 15, category)
        await send_maru_response_with_sticker(GLOBAL_BOT, TELEGRAM_CHAT_ID, formatted_msg, is_update=False)
        log_console_debug("✅ Success!", "TEST")
    except Exception as e:
        log_console_debug(f"❌ Test broke: {e}", "ERROR")

HTML_TEMPLATE = """<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Maru Diagnostic Hub</title>
    <script src="https://cdn.tailwindcss.com"></script>
    <style>
        body { background-color: #0f172a; color: #f8fafc; font-family: ui-sans-serif, system-ui, -apple-system; }
        .terminal { font-family: 'Courier New', Courier, monospace; background-color: #020617; }
        .log-PC { color: #38bdf8; }
        .log-WaniKani { color: #f43f5e; }
        .log-BUNPRO { color: #f59e0b; }
        .log-OLLAMA { color: #a855f7; }
        .log-OLLAMA_IO { color: #d946ef; }
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
                    丸 Diagnostics Panel <span class="ml-2 text-xs px-2 py-1 bg-pink-500/10 text-pink-400 rounded-full border border-pink-500/20">Active Session</span>
                </h1>
                <p class="text-sm text-slate-400 mt-1">Unified Scraper & Local LLM Live Telemetry Console</p>
            </div>
            <div class="flex gap-4">
                <button onclick="triggerAction('debug/toggle')" class="bg-slate-800 border border-slate-700 hover:bg-slate-700 px-4 py-2 rounded-lg text-sm transition font-semibold">Toggle Verbosity</button>
                <button onclick="triggerAction('cache/stop')" class="bg-red-600 hover:bg-red-500 text-white px-4 py-2 rounded-lg text-sm transition font-bold">🛑 Stop Generator</button>
                <button onclick="triggerAction('pc/wakeup')" class="bg-emerald-600 hover:bg-emerald-500 text-white px-4 py-2 rounded-lg text-sm transition font-bold">📡 Wake PC</button>
                <button onclick="triggerAction('pc/shutdown')" class="bg-red-600 hover:bg-red-500 text-white px-4 py-2 rounded-lg text-sm transition font-bold">🔌 Safe Shutdown</button>
            </div>
        </div>

        <div id="gen-monitor-card" class="bg-slate-900 border border-pink-500/30 rounded-3xl p-6 shadow-2xl mb-8 hidden">
            <div class="flex justify-between items-center mb-4">
                <div class="flex items-center gap-3">
                    <span class="relative flex h-3 w-3">
                        <span class="animate-ping absolute inline-flex h-full w-full rounded-full bg-pink-400 opacity-75"></span>
                        <span class="relative inline-flex rounded-full h-3 w-3 bg-pink-500"></span>
                    </span>
                    <h3 class="font-bold text-lg text-pink-500">Active LLM Message Generator Monitor</h3>
                </div>
                <button onclick="triggerAction('cache/stop')" class="bg-red-600 hover:bg-red-500 text-white text-xs px-4 py-2 rounded-lg font-bold transition">🛑 Stop Generator</button>
            </div>
            <div class="flex justify-between items-center text-xs text-slate-400 mb-2">
                <span id="gen-monitor-category" class="font-mono uppercase">Category: None</span>
                <span id="gen-monitor-ratio" class="font-mono">0 / 0 Complete</span>
            </div>
            <div class="w-full bg-slate-950 h-3 rounded-full overflow-hidden mb-4 border border-slate-800">
                <div id="gen-monitor-bar" class="bg-gradient-to-r from-pink-500 to-indigo-500 h-full rounded-full transition-all duration-300" style="width: 0%"></div>
            </div>
            <div class="bg-slate-950/80 rounded-2xl border border-slate-800 p-4">
                <p class="text-xs text-slate-500 font-bold uppercase tracking-wider mb-2">Last Generated Message Preview</p>
                <p id="gen-monitor-preview" class="text-sm font-mono text-slate-300 italic">Awaiting active task output...</p>
            </div>
        </div>

        <div class="grid grid-cols-1 md:grid-cols-4 gap-6 mb-8">
            <div class="bg-slate-900/60 border border-slate-800 p-5 rounded-2xl">
                <p class="text-xs text-slate-400 uppercase tracking-wider font-semibold">PC Power Status</p>
                <h2 id="metric-pc-state" class="text-2xl font-bold mt-2 text-slate-200">Loading...</h2>
                <div class="flex items-center gap-2 mt-3">
                    <span id="metric-pc-led" class="h-2 w-2 rounded-full bg-slate-500"></span>
                    <span id="metric-pc-source" class="text-xs text-slate-400">Boot: Unknown</span>
                </div>
            </div>
            <div class="bg-slate-900/60 border border-slate-800 p-5 rounded-2xl">
                <p class="text-xs text-slate-400 uppercase tracking-wider font-semibold">Bunpro Scraper Cache</p>
                <h2 id="metric-bp-queue" class="text-2xl font-bold mt-2 text-yellow-500">Loading...</h2>
                <p id="metric-bp-subtext" class="text-xs text-slate-400 mt-3">Refreshes every 15 minutes</p>
            </div>
            <div class="bg-slate-900/60 border border-slate-800 p-5 rounded-2xl">
                <p class="text-xs text-slate-400 uppercase tracking-wider font-semibold">Auto-Shutdown Warning</p>
                <h2 id="metric-pending" class="text-2xl font-bold mt-2 text-slate-200">Loading...</h2>
                <p id="metric-pending-details" class="text-xs text-slate-400 mt-3">Grace monitor off</p>
            </div>
            <div class="bg-slate-900/60 border border-slate-800 p-5 rounded-2xl">
                <p class="text-xs text-slate-400 uppercase tracking-wider font-semibold">Active Hub Connections</p>
                <h2 id="metric-clients" class="text-2xl font-bold mt-2 text-pink-500">0 connected</h2>
                <p class="text-xs text-slate-400 mt-3">SSE Stream Broadcasters</p>
            </div>
        </div>
        
        <div class="grid grid-cols-1 lg:grid-cols-3 gap-8">
            <div class="lg:col-span-2 flex flex-col h-[750px] bg-slate-950 border border-slate-800 rounded-3xl overflow-hidden shadow-2xl">
                <div class="bg-slate-900/80 px-6 py-4 border-b border-slate-800 flex justify-between items-center">
                    <div class="flex items-center gap-2">
                        <span class="h-3 w-3 rounded-full bg-pink-500 animate-pulse"></span>
                        <h3 class="font-bold text-slate-300">Live Telemetry Terminal</h3>
                    </div>
                    <div class="flex items-center gap-3">
                        <select id="log-filter" class="bg-slate-950 border border-slate-800 text-xs px-3 py-1.5 rounded-lg text-slate-300 outline-none">
                            <option value="ALL">All Log Channels</option>
                            <option value="PC">PC Management</option>
                            <option value="WaniKani">WaniKani Engine</option>
                            <option value="BUNPRO">Bunpro Scraper</option>
                            <option value="OLLAMA">Ollama CPU status</option>
                            <option value="OLLAMA_IO">LLM Raw Chats</option>
                            <option value="SYSTEM">System Hooks</option>
                            <option value="TEST">Simulators</option>
                            <option value="ERROR">Terminal Errors</option>
                        </select>
                        <button onclick="clearTerminal()" class="text-xs text-slate-400 hover:text-slate-200 bg-slate-800 px-3 py-1.5 rounded-lg border border-slate-700 transition">Clear</button>
                    </div>
                </div>
                <div id="log-container" class="terminal flex-1 p-6 overflow-y-auto text-sm leading-relaxed whitespace-pre-wrap"></div>
            </div>
            
            <div class="flex flex-col gap-6">
                <!-- Cache Panel -->
                <div class="bg-slate-900/40 border border-slate-800 rounded-3xl p-6 shadow-2xl h-[330px] flex flex-col">
                    <div class="flex justify-between items-center mb-6">
                        <h3 class="font-bold text-lg text-slate-200">Cache Pools Status</h3>
                        <div class="flex gap-2">
                            <button onclick="triggerAction('cache/generate')" class="bg-pink-600 hover:bg-pink-500 text-white text-xs px-3 py-1.5 rounded-lg transition font-semibold">Generate</button>
                            <button onclick="triggerAction('cache/empty')" class="bg-red-600 hover:bg-red-500 text-white text-xs px-3 py-1.5 rounded-lg transition font-semibold">Empty</button>
                        </div>
                    </div>
                    <div id="cache-metrics-list" class="space-y-4 flex-1 overflow-y-auto pr-2">
                        <p class="text-sm text-slate-400">Loading current indicators...</p>
                    </div>
                </div>

                <!-- NEW DIAGNOSTIC VOICEBOX SANDBOX UNIT -->
                <div class="bg-slate-900/40 border border-slate-800 rounded-3xl p-6 shadow-2xl">
                    <h3 class="font-bold text-lg text-slate-200 mb-4 flex items-center gap-2">
                        <span>🎙️</span> Voicebox & Intonation Sandbox
                    </h3>
                    
                    <!-- Tabs Header -->
                    <div class="flex border-b border-slate-800 mb-4">
                        <button onclick="switchSandboxTab('manual')" id="tab-btn-manual" class="flex-1 py-2 text-center text-xs font-bold text-pink-500 border-b-2 border-pink-500 focus:outline-none">
                            Manual TTS Tester
                        </button>
                        <button onclick="switchSandboxTab('llm')" id="tab-btn-llm" class="flex-1 py-2 text-center text-xs font-bold text-slate-400 border-b-2 border-transparent hover:text-slate-200 focus:outline-none">
                            LLM Mood Test
                        </button>
                    </div>

                    <!-- TAB 1: Manual Voicevox Synthesis -->
                    <div id="tab-content-manual" class="space-y-4">
                        <div>
                            <label class="block text-xs font-bold text-slate-400 uppercase mb-1">Japanese Text Segment</label>
                            <input id="manual-tts-text" type="text" class="w-full bg-slate-950 border border-slate-800 rounded-xl px-3 py-2 text-xs text-slate-200 focus:outline-none focus:border-pink-500 font-mono" value="あんた、またサボってるの？バカ！">
                        </div>
                        
                        <div class="grid grid-cols-2 gap-2">
                            <div>
                                <label class="block text-xs font-bold text-slate-400 uppercase mb-1">Emotion Preset</label>
                                <select id="manual-tts-preset" onchange="applyVoicePresetToSliders(this.value)" class="w-full bg-slate-950 border border-slate-800 rounded-xl px-3 py-2 text-xs text-slate-300 focus:outline-none focus:border-pink-500">
                                    <option value="normal">Normal</option>
                                    <option value="shy">Shy</option>
                                    <option value="excited">Excited</option>
                                    <option value="angry" selected>Angry</option>
                                    <option value="sad">Sad</option>
                                    <option value="tease">Tease</option>
                                    <option value="panic">Panic</option>
                                    <option value="sweet">Sweet</option>
                                </select>
                            </div>
                            <div class="flex items-end">
                                <button onclick="runManualSynthesis()" id="manual-tts-btn" class="w-full bg-pink-600 hover:bg-pink-500 text-white font-bold text-xs py-2 rounded-xl transition shadow-lg flex justify-center items-center gap-1">
                                    <span>🔊</span> Synthesize & Speak
                                </button>
                            </div>
                        </div>

                        <!-- Sliders Controls -->
                        <div class="space-y-2 pt-2 border-t border-slate-800/60">
                            <div>
                                <div class="flex justify-between text-[11px] font-mono text-slate-400 mb-1">
                                    <span>Speed (Vocal Tempo)</span>
                                    <span id="slider-val-speed" class="text-pink-400">1.30x</span>
                                </div>
                                <input id="manual-tts-speed" type="range" min="0.8" max="1.5" step="0.05" value="1.30" oninput="document.getElementById('slider-val-speed').innerText = parseFloat(this.value).toFixed(2) + 'x'" class="w-full accent-pink-500 bg-slate-950 h-1.5 rounded-lg appearance-none">
                            </div>
                            <div>
                                <div class="flex justify-between text-[11px] font-mono text-slate-400 mb-1">
                                    <span>Pitch (Frequency shift)</span>
                                    <span id="slider-val-pitch" class="text-pink-400">-0.06</span>
                                </div>
                                <input id="manual-tts-pitch" type="range" min="-0.08" max="0.08" step="0.01" value="-0.06" oninput="document.getElementById('slider-val-pitch').innerText = (parseFloat(this.value) > 0 ? '+' : '') + parseFloat(this.value).toFixed(2)" class="w-full accent-pink-500 bg-slate-950 h-1.5 rounded-lg appearance-none">
                            </div>
                            <div>
                                <div class="flex justify-between text-[11px] font-mono text-slate-400 mb-1">
                                    <span>Intonation Range scale</span>
                                    <span id="slider-val-intonation" class="text-pink-400">1.30x</span>
                                </div>
                                <input id="manual-tts-intonation" type="range" min="0.6" max="1.4" step="0.05" value="1.30" oninput="document.getElementById('slider-val-intonation').innerText = parseFloat(this.value).toFixed(2) + 'x'" class="w-full accent-pink-500 bg-slate-950 h-1.5 rounded-lg appearance-none">
                            </div>
                        </div>
                    </div>

                    <!-- TAB 2: LLM Mood Engine Simulation -->
                    <div id="tab-content-llm" class="space-y-4 hidden">
                        <div>
                            <label class="block text-xs font-bold text-slate-400 uppercase mb-1">Scenario or Emotion Directive</label>
                            <textarea id="llm-vocal-prompt" rows="2" class="w-full bg-slate-950 border border-slate-800 rounded-xl px-3 py-2 text-xs text-slate-200 focus:outline-none focus:border-pink-500 font-sans" placeholder="e.g. Complaining that I haven't cleared WaniKani kanjis, sounding highly angry and tearful..."></textarea>
                        </div>
                        <button onclick="runLlmVocalTest()" id="llm-vocal-btn" class="w-full bg-indigo-600 hover:bg-indigo-500 text-white font-bold text-xs py-2 rounded-xl transition shadow-lg flex justify-center items-center gap-1">
                            <span>🧠</span> Vocalize LLM Mood Performance
                        </button>

                        <!-- Response Metadata Block -->
                        <div id="llm-vocal-card" class="bg-slate-950/80 rounded-2xl border border-slate-800 p-4 space-y-2 hidden">
                            <div class="flex justify-between items-center text-[10px] font-mono border-b border-slate-900 pb-2">
                                <span class="text-slate-500 uppercase tracking-wider">Analysis Results</span>
                                <span id="llm-vocal-mood" class="bg-pink-500/10 text-pink-400 px-2 py-0.5 rounded-full font-bold">Mood: Unknown</span>
                            </div>
                            <p id="llm-vocal-text" class="text-xs text-slate-300 leading-relaxed font-sans italic">Output text description...</p>
                            
                            <div class="pt-2 border-t border-slate-900 flex flex-col gap-1.5">
                                <p class="text-[10px] text-slate-500 uppercase tracking-wider font-bold">Spoken Response Attributes</p>
                                <div id="llm-vocal-meta" class="font-mono text-slate-400 text-[11px] grid grid-cols-2 gap-y-1">
                                    <!-- Dynamic elements go here -->
                                </div>
                            </div>

                            <!-- Styled Inline Audio Track -->
                            <div class="pt-2">
                                <audio id="llm-vocal-player" class="w-full h-8 accent-pink-500" controls></audio>
                            </div>
                        </div>
                    </div>
                </div>

                <!-- System Sandbox & Simulation Testers -->
                <div class="bg-slate-900/40 border border-slate-800 rounded-3xl p-6 shadow-2xl">
                    <h3 class="font-bold text-lg text-slate-200 mb-4 flex items-center gap-2">
                        <span>🧪</span> API Integrations
                    </h3>
                    <div class="grid grid-cols-2 gap-3 mb-4">
                        <button onclick="triggerAction('test/wanikani')" class="bg-indigo-600 hover:bg-indigo-500 text-white text-xs px-3 py-2.5 rounded-lg transition font-semibold text-left flex justify-between shadow-lg">
                            WaniKani <span>▶</span>
                        </button>
                        <button onclick="triggerAction('test/kitsu')" class="bg-orange-600 hover:bg-orange-500 text-white text-xs px-3 py-2.5 rounded-lg transition font-semibold text-left flex justify-between shadow-lg">
                            Kitsu API <span>▶</span>
                        </button>
                        <button onclick="triggerAction('test/bunpro')" class="bg-yellow-600 hover:bg-yellow-500 text-white text-xs px-3 py-2.5 rounded-lg transition font-semibold text-left flex justify-between shadow-lg">
                            Bunpro Scrape <span>▶</span>
                        </button>
                        <button onclick="triggerAction('test/ollama')" class="bg-purple-600 hover:bg-purple-500 text-white text-xs px-3 py-2.5 rounded-lg transition font-semibold text-left flex justify-between shadow-lg">
                            Local Ollama <span>▶</span>
                        </button>
                        <button onclick="triggerAction('test/gemini_image')" class="bg-teal-600 hover:bg-teal-500 text-white text-xs px-3 py-2.5 rounded-lg transition font-semibold text-left flex justify-between shadow-lg">
                            Gemini Image <span>▶</span>
                        </button>
                        <button onclick="triggerAction('test/gemini_voice')" class="bg-cyan-600 hover:bg-cyan-500 text-white text-xs px-3 py-2.5 rounded-lg transition font-semibold text-left flex justify-between shadow-lg">
                            Gemini Voice <span>▶</span>
                        </button>
                    </div>

                    <div class="border-t border-slate-800 pt-4 mt-4">
                        <h3 class="font-bold text-sm text-slate-300 mb-2 flex items-center gap-2">
                            <span>🎭</span> Basic Helper Sandbox
                        </h3>
                        <p class="text-slate-500 text-[11px] mb-3">Live test procedural generator outcomes.</p>
                        <div class="grid grid-cols-3 gap-2 mb-3">
                            <button onclick="runSandbox('petname')" class="bg-slate-800 hover:bg-slate-700 border border-slate-700 text-slate-200 text-xs py-1.5 rounded-lg transition font-semibold">Petname</button>
                            <button onclick="runSandbox('kaomoji')" class="bg-slate-800 hover:bg-slate-700 border border-slate-700 text-slate-200 text-xs py-1.5 rounded-lg transition font-semibold">Kaomoji</button>
                            <button onclick="runSandbox('combo')" class="bg-pink-900/40 hover:bg-pink-900 border border-pink-700 text-pink-300 text-xs py-1.5 rounded-lg transition font-bold">Combo Alert</button>
                        </div>
                        <div class="bg-slate-950 rounded-2xl border border-slate-800 p-3 flex items-center justify-center min-h-[60px]">
                            <p id="sandbox-output" class="text-xs font-mono text-slate-400 italic text-center">Output preview will appear here...</p>
                        </div>
                    </div>
                </div>
            </div>
        </div>
    </div>

    <!-- Cache Inspector Modal overlay -->
    <div id="inspector-modal" class="fixed inset-0 bg-black/80 backdrop-blur-sm flex items-center justify-center p-4 z-50 hidden">
        <div class="bg-slate-900 border border-slate-800 w-full max-w-4xl rounded-3xl overflow-hidden shadow-2xl flex flex-col max-h-[90vh]">
            <div class="px-6 py-4 bg-slate-950/80 border-b border-slate-800 flex justify-between items-center">
                <div>
                    <h3 class="font-bold text-lg text-pink-500 flex items-center gap-2">
                        <span>📦</span> Cache Pool Inspector
                    </h3>
                    <p id="inspector-key-title" class="text-xs text-slate-400 font-mono mt-0.5 uppercase">Category: Key</p>
                </div>
                <button onclick="closeInspector()" class="text-slate-400 hover:text-slate-200 bg-slate-800 hover:bg-slate-700 px-3 py-1.5 rounded-lg border border-slate-700 transition font-semibold text-xs">Close</button>
            </div>
            <div id="inspector-list" class="flex-1 overflow-y-auto p-6 space-y-4"></div>
            <div class="px-6 py-4 bg-slate-950/80 border-t border-slate-800 flex justify-between items-center text-xs text-slate-500">
                <span>Stored Messages: <span id="inspector-count" class="font-mono text-slate-300">0</span></span>
                <button onclick="triggerFillTenInInspector()" class="bg-pink-600 hover:bg-pink-500 text-white font-bold px-3 py-1.5 rounded-lg transition">Fill 10 More</button>
            </div>
        </div>
    </div>

    <script>
        const logContainer = document.getElementById('log-container');
        const filterSelect = document.getElementById('log-filter');
        let rawLogHistory = [];
        const eventSource = new EventSource('/events');
        let currentInspectorKey = "";

        const presetsMap = {
            "normal":  {speed: 1.0,  pitch: 0.0,   intonation: 1.0},
            "shy":     {speed: 0.9,  pitch: -0.05, intonation: 0.8},
            "excited": {speed: 1.25, pitch: 0.06,  intonation: 1.2},
            "angry":   {speed: 1.3,  pitch: -0.06, intonation: 1.3},
            "sad":     {speed: 0.85, pitch: -0.04, intonation: 0.7},
            "tease":   {speed: 1.05, pitch: 0.04,  intonation: 1.1},
            "panic":   {speed: 1.4,  pitch: 0.08,  intonation: 1.3},
            "sweet":   {speed: 0.95, pitch: 0.05,  intonation: 1.1}
        };

        eventSource.onmessage = function(event) {
            const wrapper = JSON.parse(event.data);
            if (wrapper.type === 'gen_progress') {
                updateGenerationUI(wrapper.status);
            } else if (wrapper.type === 'log') {
                const logItem = wrapper.data;
                rawLogHistory.push(logItem);
                if (rawLogHistory.length > 200) rawLogHistory.shift();
                renderLogs();
            }
        };

        function switchSandboxTab(tabName) {
            const btnManual = document.getElementById('tab-btn-manual');
            const btnLlm = document.getElementById('tab-btn-llm');
            const contentManual = document.getElementById('tab-content-manual');
            const contentLlm = document.getElementById('tab-content-llm');

            if (tabName === 'manual') {
                btnManual.className = "flex-1 py-2 text-center text-xs font-bold text-pink-500 border-b-2 border-pink-500 focus:outline-none";
                btnLlm.className = "flex-1 py-2 text-center text-xs font-bold text-slate-400 border-b-2 border-transparent hover:text-slate-200 focus:outline-none";
                contentManual.classList.remove('hidden');
                contentLlm.classList.add('hidden');
            } else {
                btnLlm.className = "flex-1 py-2 text-center text-xs font-bold text-pink-500 border-b-2 border-pink-500 focus:outline-none";
                btnManual.className = "flex-1 py-2 text-center text-xs font-bold text-slate-400 border-b-2 border-transparent hover:text-slate-200 focus:outline-none";
                contentLlm.classList.remove('hidden');
                contentManual.classList.add('hidden');
            }
        }

        function applyVoicePresetToSliders(presetKey) {
            const config = presetsMap[presetKey] || presetsMap.normal;
            
            const spInput = document.getElementById('manual-tts-speed');
            const piInput = document.getElementById('manual-tts-pitch');
            const inInput = document.getElementById('manual-tts-intonation');

            spInput.value = config.speed;
            piInput.value = config.pitch;
            inInput.value = config.intonation;

            document.getElementById('slider-val-speed').innerText = config.speed.toFixed(2) + 'x';
            document.getElementById('slider-val-pitch').innerText = (config.pitch > 0 ? '+' : '') + config.pitch.toFixed(2);
            document.getElementById('slider-val-intonation').innerText = config.intonation.toFixed(2) + 'x';
        }

        async function runManualSynthesis() {
            const text = document.getElementById('manual-tts-text').value;
            const speed = document.getElementById('manual-tts-speed').value;
            const pitch = document.getElementById('manual-tts-pitch').value;
            const intonation = document.getElementById('manual-tts-intonation').value;
            const btn = document.getElementById('manual-tts-btn');

            btn.disabled = true;
            btn.innerHTML = '⚡ Processing...';
            
            try {
                const url = `/api/voice/manual?text=${encodeURIComponent(text)}&speed=${speed}&pitch=${pitch}&intonation=${intonation}`;
                const audio = new Audio(url);
                audio.play();
            } catch (err) {
                console.error("Manual TTS generation error:", err);
            } finally {
                setTimeout(() => {
                    btn.disabled = false;
                    btn.innerHTML = '<span>🔊</span> Synthesize & Speak';
                }, 1000);
            }
        }

        async function runLlmVocalTest() {
            const prompt = document.getElementById('llm-vocal-prompt').value;
            const btn = document.getElementById('llm-vocal-btn');
            const card = document.getElementById('llm-vocal-card');

            if (!prompt.trim()) {
                alert("Please type an emotional prompt directive first!");
                return;
            }

            btn.disabled = true;
            btn.innerHTML = '⚡ Ollama thinking & Synthesizing...';
            card.classList.add('hidden');

            try {
                const res = await fetch(`/api/voice/llm_test?prompt=${encodeURIComponent(prompt)}`);
                const data = await res.json();

                if (data.status === 'ok') {
                    card.classList.remove('hidden');
                    document.getElementById('llm-vocal-text').innerText = data.clean_text;
                    
                    const moodBadge = document.getElementById('llm-vocal-mood');
                    moodBadge.innerText = 'Mood: ' + data.mood.toUpperCase();
                    
                    const moodColorMap = {
                        "angry": "bg-red-500/10 text-red-400 border border-red-500/20",
                        "cry": "bg-blue-500/10 text-blue-400 border border-blue-500/20",
                        "sad": "bg-indigo-500/10 text-indigo-400 border border-indigo-500/20",
                        "tease": "bg-purple-500/10 text-purple-400 border border-purple-500/20",
                        "sweet": "bg-pink-500/10 text-pink-400 border border-pink-500/20",
                        "excited": "bg-yellow-500/10 text-yellow-400 border border-yellow-500/20"
                    };
                    moodBadge.className = "px-2.5 py-0.5 rounded-full font-bold uppercase text-[10px] tracking-wider " + (moodColorMap[data.mood] || "bg-pink-500/10 text-pink-400 border border-pink-500/20");

                    const metaContainer = document.getElementById('llm-vocal-meta');
                    metaContainer.innerHTML = '';

                    if (data.voice_meta && data.voice_meta.phrase) {
                        metaContainer.innerHTML = `
                            <div class="text-slate-500">Preset Tone:</div>
                            <div class="text-slate-300 font-bold capitalize">${data.voice_meta.preset}</div>
                            <div class="text-slate-500">Speed (Scale):</div>
                            <div class="text-slate-300">${data.voice_meta.speed.toFixed(2)}x</div>
                            <div class="text-slate-500">Pitch Shift:</div>
                            <div class="text-slate-300">${(data.voice_meta.pitch > 0 ? '+' : '') + data.voice_meta.pitch.toFixed(2)}</div>
                            <div class="text-slate-500">Intonation Scale:</div>
                            <div class="text-slate-300">${data.voice_meta.intonation.toFixed(2)}x</div>
                            <div class="text-slate-500 col-span-2 pt-1 border-t border-slate-900 text-slate-500 font-bold">Vocalization Phrase:</div>
                            <div class="text-pink-400 col-span-2 font-mono text-xs font-bold leading-relaxed">${data.voice_meta.phrase}</div>
                        `;
                        
                        if (data.audio_b64) {
                            const player = document.getElementById('llm-vocal-player');
                            player.src = "data:audio/ogg;base64," + data.audio_b64;
                            player.play();
                        }
                    } else {
                        metaContainer.innerHTML = `
                            <div class="col-span-2 text-slate-500 italic">No spoken Japanese wrapped inside &lt;voice&gt; tags was identified. Only English delivered.</div>
                        `;
                    }
                } else {
                    alert("Model error: " + data.reason);
                }
            } catch (err) {
                console.error("Vocal test failed:", err);
                alert("Vocal test connection error!");
            } finally {
                btn.disabled = false;
                btn.innerHTML = '<span>🧠</span> Vocalize LLM Mood Performance';
            }
        }

        function updateGenerationUI(status) {
            const card = document.getElementById('gen-monitor-card');
            if (status.active) {
                card.classList.remove('hidden');
                document.getElementById('gen-monitor-category').innerText = 'Category: ' + status.category;
                document.getElementById('gen-monitor-ratio').innerText = status.current + ' / ' + status.total + ' Complete';
                
                const percent = Math.min(100, Math.floor((status.current / status.total) * 100));
                document.getElementById('gen-monitor-bar').style.width = percent + '%';
                document.getElementById('gen-monitor-preview').innerText = status.last_generated;
            } else {
                card.classList.add('hidden');
            }
        }

        async function inspectCache(key) {
            currentInspectorKey = key;
            document.getElementById('inspector-key-title').innerText = 'Category: ' + key;
            document.getElementById('inspector-modal').classList.remove('hidden');
            await loadInspectorData();
        }

        function closeInspector() {
            document.getElementById('inspector-modal').classList.add('hidden');
            currentInspectorKey = "";
        }

        async function loadInspectorData() {
            if (!currentInspectorKey) return;
            const listContainer = document.getElementById('inspector-list');
            listContainer.innerHTML = '<div class="text-center py-8 text-slate-400 text-sm animate-pulse">Loading cache elements...</div>';
            try {
                const res = await fetch('/api/cache/list?key=' + encodeURIComponent(currentInspectorKey));
                const data = await res.json();
                
                listContainer.innerHTML = '';
                document.getElementById('inspector-count').innerText = data.messages.length;
                
                if (data.messages.length === 0) {
                    listContainer.innerHTML = '<div class="text-center py-12 text-slate-500 text-sm italic">This cache pool is completely empty! Click "Fill 10 More" to generate content.</div>';
                    return;
                }

                data.messages.forEach((msg, idx) => {
                    const itemDiv = document.createElement('div');
                    itemDiv.className = 'bg-slate-950 border border-slate-800 rounded-2xl p-4 flex flex-col md:flex-row gap-4 justify-between items-start md:items-center hover:border-slate-700 transition';
                    
                    const contentDiv = document.createElement('div');
                    contentDiv.className = 'flex-1 font-mono text-xs text-slate-300 leading-relaxed break-words whitespace-pre-wrap w-full';
                    contentDiv.innerText = msg;
                    
                    const actionDiv = document.createElement('div');
                    actionDiv.className = 'flex gap-2 self-end md:self-center shrink-0';
                    
                    const regButton = document.createElement('button');
                    regButton.className = 'text-xs font-bold px-3 py-1.5 rounded-lg bg-indigo-900/40 hover:bg-indigo-900 border border-indigo-700 text-indigo-300 transition';
                    regButton.innerText = 'Regenerate';
                    regButton.onclick = () => regenerateInspectorItem(idx);
                    
                    const delButton = document.createElement('button');
                    delButton.className = 'text-xs font-bold px-3 py-1.5 rounded-lg bg-red-950/40 hover:bg-red-900 border border-red-700 text-red-300 transition';
                    delButton.innerText = 'Delete';
                    delButton.onclick = () => deleteInspectorItem(idx);
                    
                    actionDiv.appendChild(regButton);
                    actionDiv.appendChild(delButton);
                    
                    itemDiv.appendChild(contentDiv);
                    itemDiv.appendChild(actionDiv);
                    listContainer.appendChild(itemDiv);
                });
            } catch (err) {
                listContainer.innerHTML = '<div class="text-center py-8 text-red-400 text-sm">Failed to retrieve cache content.</div>';
            }
        }

        async function deleteInspectorItem(index) {
            if (!currentInspectorKey) return;
            try {
                const res = await fetch('/api/cache/delete_item?key=' + encodeURIComponent(currentInspectorKey) + '&index=' + index, { method: 'POST' });
                const data = await res.json();
                if (data.status === 'ok') {
                    await loadInspectorData();
                    fetchSystemState(); 
                }
            } catch (err) { console.error("Deletion failed:", err); }
        }

        async function regenerateInspectorItem(index) {
            if (!currentInspectorKey) return;
            const listContainer = document.getElementById('inspector-list');
            listContainer.innerHTML = '<div class="text-center py-8 text-pink-400 text-sm animate-pulse font-bold">Waking remote PC & Re-generating message item... Please wait!</div>';
            try {
                const res = await fetch('/api/cache/regenerate_item?key=' + encodeURIComponent(currentInspectorKey) + '&index=' + index, { method: 'POST' });
                const data = await res.json();
                if (data.status === 'ok') {
                    await loadInspectorData();
                    fetchSystemState();
                } else {
                    alert("Regeneration error: " + data.reason);
                    await loadInspectorData();
                }
            } catch (err) { 
                console.error("Regeneration request broke:", err);
                await loadInspectorData();
            }
        }

        async function triggerFillTenInInspector() {
            if (!currentInspectorKey) return;
            await triggerAction('cache/fill_one/' + currentInspectorKey);
            setTimeout(loadInspectorData, 1500);
        }

        async function runSandbox(type) {
            const outBox = document.getElementById('sandbox-output');
            outBox.innerText = 'Consulting generators...';
            try {
                const res = await fetch('/api/test/sandbox/' + type, { method: 'POST' });
                const data = await res.json();
                outBox.innerText = data.result;
                outBox.className = 'text-xs font-mono text-slate-300 text-center';
            } catch (err) {
                outBox.innerText = 'Generation test failed.';
            }
        }

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
                line.innerHTML = '<span class="text-slate-500">[' + item.time + ']</span> <span class="log-' + item.category + ' font-semibold">[' + item.category + ']</span> <span class="text-slate-300">' + escapeHtml(item.message) + '</span>';
                logContainer.appendChild(line);
            });
            logContainer.scrollTop = logContainer.scrollHeight;
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
                await fetch('/api/' + endpoint, { method: 'POST' });
            } catch (err) { console.error("Endpoint failed:", err); }
        }

        window.expandedSections = window.expandedSections || {};
        function toggleSection(id) {
            const el = document.getElementById(id);
            if (el.classList.contains('hidden')) {
                el.classList.remove('hidden');
                window.expandedSections[id] = true;
            } else {
                el.classList.add('hidden');
                window.expandedSections[id] = false;
            }
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
                pcSourceElem.innerText = 'Boot trigger: ' + (data.pc_started_by_bot ? 'BOT (WOL)' : 'USER (Manual)');

                document.getElementById('metric-bp-queue').innerText = 'R: ' + data.bp_reviews + ' | L: ' + data.bp_lessons;
                
                let badgesCount = Array.isArray(data.bp_badges) ? data.bp_badges.length : 0;
                let badgesTooltip = Array.isArray(data.bp_badges) && data.bp_badges.length > 0 ? ' (' + data.bp_badges.slice(0, 3).join(', ') + (data.bp_badges.length > 3 ? '...' : '') + ')' : '';
                document.getElementById('metric-bp-subtext').innerText = '🔥 Streak: ' + data.bp_streak + ' Days | 🏅 Badges: ' + badgesCount + badgesTooltip;

                const pendingTitle = document.getElementById('metric-pending');
                const pendingDetails = document.getElementById('metric-pending-details');
                if (data.pc_shutdown_pending) {
                    pendingTitle.innerText = '⚠️ ' + data.pc_shutdown_remaining + 's';
                    pendingTitle.className = "text-2xl font-bold mt-2 text-yellow-500 animate-pulse";
                    pendingDetails.innerText = "Shutdown warning timer actively running!";
                } else {
                    pendingTitle.innerText = "Deactivated";
                    pendingTitle.className = "text-2xl font-bold mt-2 text-slate-400";
                    pendingDetails.innerText = data.pc_started_by_bot ? "Monitored (Bot active)" : "Bypassed (User active)";
                }

                document.getElementById('metric-clients').innerText = data.sse_clients + ' connected';
                
                updateGenerationUI(data.gen_status);

                const cacheContainer = document.getElementById('cache-metrics-list');
                cacheContainer.innerHTML = '';
                
                const times = ['morning', 'afternoon', 'evening', 'night'];
                const platforms = ['wanikani', 'bunpro', 'both'];
                const triggers = ['nag_mild', 'nag_angry', 'nag_boiling', 'cleared', 'level_up', 'new_lessons'];
                
                times.forEach(t => {
                    const timeHeader = document.createElement('div');
                    timeHeader.className = 'border border-slate-850 rounded-2xl bg-slate-900/40 overflow-hidden mb-4 shadow-sm';
                    
                    let icon = '🌅';
                    if (t === 'afternoon') icon = '☀️';
                    if (t === 'evening') icon = '🌇';
                    if (t === 'night') icon = '🌙';

                    let totalCached = 0;
                    let totalTarget = 0;
                    platforms.forEach(p => {
                        triggers.forEach(g => {
                            const key = t + '_' + p + '_' + g;
                            totalCached += data.cache_sizes[key] || 0;
                            totalTarget += data.gen_targets[key] || 10;
                        });
                    });

                    const isExpanded = window.expandedSections['sec-' + t];

                    let timeHeaderHTML = `
                    <button onclick="toggleSection('sec-${t}')" class="w-full flex justify-between items-center px-5 py-4 bg-slate-900/60 hover:bg-slate-900 transition font-bold text-slate-200 text-sm tracking-wide outline-none">
                        <span class="flex items-center gap-2">${icon} <span class="capitalize">${t}</span> Section</span>
                        <span class="bg-pink-500/10 text-pink-400 border border-pink-500/20 px-2.5 py-0.5 rounded-full text-xs font-mono">${totalCached} / ${totalTarget} cached</span>
                    </button>
                    <div id="sec-${t}" class="${isExpanded ? '' : 'hidden'} p-4 space-y-4 border-t border-slate-900/50 bg-slate-950/40">
                        <div class="grid grid-cols-1 gap-4">`;

                    platforms.forEach(p => {
                        let pIcon = p === 'wanikani' ? '🦀' : p === 'bunpro' ? '🐸' : '🌀';
                        timeHeaderHTML += `
                        <div class="bg-slate-950/80 rounded-xl border border-slate-800/80 p-3 flex flex-col gap-3">
                            <h4 class="text-xs font-bold text-slate-400 uppercase tracking-wider flex items-center gap-1.5 pb-2 border-b border-slate-900">
                                <span>${pIcon}</span> ${p}
                            </h4>
                            <div class="space-y-3.5">`;

                        triggers.forEach(g => {
                            const key = t + '_' + p + '_' + g;
                            const size = data.cache_sizes[key] || 0;
                            const target = data.gen_targets[key] || 10;
                            const percent = Math.min(100, Math.floor((size / target) * 100));
                            const cleanTriggerName = g.replace(/_/g, ' ');

                            timeHeaderHTML += `
                            <div class="flex flex-col gap-1.5 text-xs">
                                <div class="flex justify-between items-center font-semibold text-slate-300">
                                    <span class="capitalize">${cleanTriggerName}</span>
                                    <span class="font-mono text-[10px] text-slate-400">${size}/${target}</span>
                                </div>
                                <div class="w-full bg-slate-850 h-1.5 rounded-full overflow-hidden">
                                    <div class="bg-pink-500 h-full rounded-full transition-all duration-300" style="width: ${percent}%"></div>
                                </div>
                                <div class="flex justify-end gap-1.5 mt-1">
                                    <button onclick="inspectCache('${key}')" class="text-[10px] font-bold px-2 py-0.5 rounded bg-slate-800 hover:bg-indigo-950/40 border border-slate-700 text-indigo-400 transition">Inspect</button>
                                    <button onclick="triggerAction('cache/empty_one/${key}')" class="text-[10px] font-bold px-2 py-0.5 rounded bg-slate-800 hover:bg-red-950/40 border border-slate-700 text-slate-400 hover:text-red-400 transition">Clear</button>
                                    <button onclick="triggerAction('cache/fill_one/${key}')" class="text-[10px] font-bold px-2 py-0.5 rounded bg-slate-800 hover:bg-pink-950/40 border border-slate-700 text-slate-400 hover:text-pink-400 transition">Fill 10</button>
                                    <button onclick="triggerAction('test/force_alert/${key}')" class="text-[10px] font-bold px-2 py-0.5 rounded bg-slate-800 hover:bg-emerald-950/40 border border-slate-700 text-slate-400 hover:text-emerald-400 transition">Test</button>
                                </div>
                            </div>`;
                        });

                        timeHeaderHTML += `</div></div>`;
                    });

                    timeHeaderHTML += `</div></div>`;
                    timeHeader.innerHTML = timeHeaderHTML;
                    cacheContainer.appendChild(timeHeader);
                });

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
    log_console_debug(f"Diagnostics Server running at http://localhost:{DIAG_PORT}", category="SYSTEM")
    async with server:
        await server.serve_forever()

async def handle_diagnostic_request(reader, writer):
    global pc_state, pc_last_active, pc_started_by_bot, pc_shutdown_pending, pc_shutdown_alert_msg_id, msg_cache, bot_state, CANCEL_GENERATION, GEN_STATUS
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

    parsed_url = urllib.parse.urlparse(path)
    route = parsed_url.path
    query_params = urllib.parse.parse_qs(parsed_url.query)
    
    def get_param(name, default=""):
        val_list = query_params.get(name, [])
        return val_list[0] if val_list else default

    if method == "GET" and route == "/events":
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
                log_wrapper = {"type": "log", "data": past_log}
                writer.write(f"data: {json.dumps(log_wrapper)}\n\n".encode('utf-8'))
                await writer.drain()
            except Exception: break
        return

    if method == "GET" and route == "/":
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

    if method == "GET" and route == "/api/metrics":
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
            "gen_targets": bot_state.get("gen_targets", {}),
            "bp_reviews": maru_memory.get("last_bp_reviews") or 0,
            "bp_lessons": maru_memory.get("last_bp_lessons") or 0,
            "bp_streak": maru_memory.get("bp_streak") or "0",
            "bp_badges": maru_memory.get("bp_badges", []),
            "gen_status": GEN_STATUS
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

    # NEW ENDPOINT: Manual Voicebox TTS Generation tester
    if method == "GET" and route == "/api/voice/manual":
        text = get_param("text")
        speed_val = get_param("speed", "1.0")
        pitch_val = get_param("pitch", "0.0")
        intonation_val = get_param("intonation", "1.0")

        log_console_debug(f"🧪 Synthesizing Manual Voicebox voice segment. Text: '{text}' (S:{speed_val}, P:{pitch_val}, I:{intonation_val})", "TEST")
        
        audio_fp = await asyncio.to_thread(
            make_voicevox_audio,
            text=text,
            speed=float(speed_val),
            pitch=float(pitch_val),
            intonation=float(intonation_val)
        )
        if audio_fp:
            audio_bytes = audio_fp.getvalue()
            response = (
                "HTTP/1.1 200 OK\r\n"
                f"Content-Length: {len(audio_bytes)}\r\n"
                "Content-Type: audio/ogg\r\n"
                "Connection: close\r\n\r\n"
            ).encode('utf-8') + audio_bytes
        else:
            payload = json.dumps({"status": "error", "reason": "synthesis failed"}).encode('utf-8')
            response = (
                "HTTP/1.1 500 Internal Server Error\r\n"
                f"Content-Length: {len(payload)}\r\n"
                "Content-Type: application/json\r\n"
                "Connection: close\r\n\r\n"
            ).encode('utf-8') + payload
        writer.write(response)
        await writer.drain()
        writer.close()
        return

    # NEW ENDPOINT: LLM Vocal Tester Scenario Simulator
    if method == "GET" and route == "/api/voice/llm_test":
        prompt = get_param("prompt")
        log_console_debug(f"🧪 Simulating LLM Vocal mood synthesis for context: '{prompt}'", "TEST")
        
        status = "ok"
        reason = ""
        payload_data = {}
        
        try:
            await ensure_pc_ready()
            base_prompt = get_base_system_prompt()
            full_messages = [
                {"role": "system", "content": base_prompt},
                {"role": "user", "content": f"Test Prompt Scenario: {prompt}. Express your feelings using both English commentary and Japanese casual vocalizations inside <voice> tags!"}
            ]
            response = await ollama_client.chat.completions.create(
                model=OLLAMA_MODEL,
                messages=full_messages,
                temperature=0.8
            )
            final_text = response.choices[0].message.content
            
            explicit_category = None
            category_match = re.search(r'<sticker:([a-zA-Z0-9_-]+)>', final_text, re.IGNORECASE)
            if category_match:
                explicit_category = category_match.group(1).strip().lower()
                
            clean_text = re.sub(r'</?sticker[^>]*>', '', final_text, flags=re.IGNORECASE)
            clean_text = re.sub(r'</?voice[^>]*>', '*', clean_text, flags=re.IGNORECASE)
            clean_text = re.sub(r'\*+', '*', clean_text)
            clean_text = re.sub(r'_+', '_', clean_text)
            
            # Detect computed vocal mood parameters
            mood = detect_mood_from_text(clean_text, explicit_category=explicit_category)
            
            voice_blocks = re.findall(r'<voice\s*([^>]*)>(.*?)</voice>', final_text, re.IGNORECASE | re.DOTALL)
            if not voice_blocks:
                unclosed_match = re.search(r'<voice\s*([^>]*)>(.*)', final_text, re.IGNORECASE | re.DOTALL)
                if unclosed_match and '</voice>' not in final_text.lower():
                    voice_blocks = [(unclosed_match.group(1), unclosed_match.group(2))]
            
            if not voice_blocks:
                jp_chunks = re.findall(r'[\u3040-\u309F\u30A0-\u30FF\u4E00-\u9FAF\uff00-\uffef]', clean_text)
                if jp_chunks:
                    voice_blocks = [("preset=\"normal\"", " ".join(jp_chunks))]
                    
            audio_b64 = ""
            voice_meta = {}
            if voice_blocks:
                attrs, phrase = voice_blocks[0]
                phrase = phrase.strip()
                preset_key, v_speed, v_pitch, v_inton = get_emotional_voice_params(attrs, mood)
                
                # Constrain parameters safely
                v_speed = max(0.8, min(v_speed, 1.5))       
                v_pitch = max(-0.08, min(v_pitch, 0.08))     
                v_inton = max(0.6, min(v_inton, 1.4))
                
                audio_fp = await asyncio.to_thread(
                    make_voicevox_audio,
                    text=phrase,
                    speed=v_speed,
                    pitch=v_pitch,
                    intonation=v_inton
                )
                if audio_fp:
                    audio_b64 = base64.b64encode(audio_fp.getvalue()).decode('utf-8')
                    
                voice_meta = {
                    "phrase": phrase,
                    "preset": preset_key,
                    "speed": v_speed,
                    "pitch": v_pitch,
                    "intonation": v_inton
                }
                
            payload_data = {
                "status": "ok",
                "raw_text": final_text,
                "clean_text": clean_text,
                "mood": mood,
                "voice_meta": voice_meta,
                "audio_b64": audio_b64
            }
        except Exception as e:
            status = "error"
            reason = str(e)
            payload_data = {"status": "error", "reason": reason}
            
        payload = json.dumps(payload_data).encode('utf-8')
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

    if method == "GET" and route == "/api/cache/list":
        key = get_param("key")
        messages = msg_cache.get(key, [])
        payload = json.dumps({"status": "ok", "messages": messages}).encode('utf-8')
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

    if method == "POST" and route == "/api/cache/delete_item":
        key = get_param("key")
        idx_str = get_param("index")
        status = "error"
        reason = ""
        try:
            idx = int(idx_str)
            if key in msg_cache and 0 <= idx < len(msg_cache[key]):
                msg_cache[key].pop(idx)
                save_json_file(MESSAGE_CACHE_FILE, msg_cache)
                log_console_debug(f"🗑️ Deleted message from category '{key}' at index {idx}.", category="SYSTEM")
                status = "ok"
            else:
                reason = "Index out of range or category not found."
        except Exception as e:
            reason = str(e)

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

    if method == "POST" and route == "/api/cache/regenerate_item":
        key = get_param("key")
        idx_str = get_param("index")
        status = "error"
        reason = ""
        try:
            idx = int(idx_str)
            if key in msg_cache and 0 <= idx < len(msg_cache[key]):
                log_console_debug(f"🔄 Regenerating cache item for '{key}' at index {idx}...", category="SYSTEM")
                new_msg = await generate_single_message(key)
                if new_msg:
                    msg_cache[key][idx] = new_msg
                    save_json_file(MESSAGE_CACHE_FILE, msg_cache)
                    log_console_debug(f"✅ Replaced message index {idx} with newly generated content.", category="SYSTEM")
                    status = "ok"
                else:
                    reason = "Ollama returned empty generated content."
            else:
                reason = "Index out of range or category not found."
        except Exception as e:
            reason = str(e)

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

    if method == "POST" and route.startswith("/api/"):
        action = route[5:]
        status = "ok"
        reason = ""
        payload = None
        
        if action == "pc/wakeup": asyncio.create_task(ensure_pc_ready())
        elif action == "pc/shutdown": asyncio.create_task(execute_pc_shutdown())
        elif action == "debug/toggle":
            bot_state["debug_enabled"] = not bot_state.get("debug_enabled", True)
            save_json_file(STATE_FILE, bot_state)
        elif action == "cache/generate": asyncio.create_task(batch_generate_messages(days=1))
        elif action == "cache/stop":
            CANCEL_GENERATION = True
            log_console_debug("🛑 Global cancellation flag activated for message refills.", category="SYSTEM")
        elif action == "cache/empty":
            msg_cache = {k: [] for k in get_all_cache_keys()}
            save_json_file(MESSAGE_CACHE_FILE, msg_cache)
            log_console_debug("🗑️ Cache pools explicitly cleared.", category="SYSTEM")
        elif action.startswith("cache/empty_one/"):
            key = action[16:]
            msg_cache[key] = []
            save_json_file(MESSAGE_CACHE_FILE, msg_cache)
            log_console_debug(f"🗑️ Cleared cache pool for category '{key}'.", category="SYSTEM")
        elif action.startswith("cache/fill_one/"):
            key = action[15:]
            CANCEL_GENERATION = False
            asyncio.create_task(generate_messages_for_category(key, 10))
        elif action.startswith("test/force_alert/"):
            cat = action[17:]
            asyncio.create_task(force_trigger_alert(cat))
            
        elif action == "test/sandbox/petname":
            res_val = generate_natural_petname()
            payload = json.dumps({"status": "ok", "result": res_val}).encode('utf-8')
        elif action == "test/sandbox/kaomoji":
            cat = random.choice(["nag_mild", "nag_angry", "nag_boiling", "cleared", "level_up", "new_lessons"])
            res_val = generate_dynamic_kaomoji(cat)
            payload = json.dumps({"status": "ok", "result": res_val}).encode('utf-8')
        elif action == "test/sandbox/combo":
            petname = generate_natural_petname()
            kaomoji = generate_dynamic_kaomoji(random.choice(["nag_mild", "nag_angry", "nag_boiling", "cleared"]))
            res_val = f"Hey {petname}, don't make me cry! {kaomoji}"
            payload = json.dumps({"status": "ok", "result": res_val}).encode('utf-8')

        elif action == "test/wanikani": asyncio.create_task(run_test_wanikani())
        elif action == "test/kitsu": asyncio.create_task(run_test_kitsu())
        elif action == "test/bunpro": asyncio.create_task(run_test_bunpro())
        elif action == "test/ollama": asyncio.create_task(run_test_ollama())
        elif action == "test/gemini_image": asyncio.create_task(run_test_gemini_image())
        elif action == "test/gemini_voice": asyncio.create_task(run_test_gemini_voice())
        else:
            status = "error"
            reason = "unmapped command"

        if not payload:
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

async def run_test_ollama():
    try:
        log_console_debug("🧪 Testing local LLM server...", "TEST")
        response = await ollama_client.chat.completions.create(
            model=OLLAMA_MODEL,
            messages=[{"role": "user", "content": "Reply with exactly one word: 'Operational'."}],
            temperature=0.1
        )
        msg = response.choices[0].message.content
        log_console_debug(f"✅ Success! Response: '{msg}'", "TEST")
    except Exception as e:
        log_console_debug(f"❌ Test broke: {e}", "ERROR")

async def post_init(application: Application) -> None:
    global GLOBAL_BOT
    GLOBAL_BOT = application.bot
    asyncio.create_task(start_diagnostic_server())

def main():
    print("🤖 Launching Master Orchestrator Bot...")
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
        job_queue.run_repeating(check_japanese_srs_alerts, interval=60, first=10)
        job_queue.run_repeating(check_pc_idle, interval=60, first=30)
        job_queue.run_repeating(update_bunpro_cache_job, interval=900, first=15)
    else:
        print("⚠ JobQueue not found! Background schedulers are disabled.")

    print("✅ Bot operational! Send /start to begin.")
    application.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == "__main__":
    main()
