import asyncio, nest_asyncio, logging, json, os, csv, io
from pathlib import Path
from telethon import TelegramClient
from telethon.errors import SessionPasswordNeededError, AuthRestartError, FloodWaitError
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, ContextTypes, filters
from telethon.tl.functions.account import UpdateUsernameRequest
from telethon.tl.functions.account import GetAuthorizationsRequest
from telethon.errors import UsernameOccupiedError, UsernameInvalidError
import random, string
from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import CallbackQueryHandler
from dotenv import load_dotenv
load_dotenv()
from cryptography.fernet import Fernet, InvalidToken
from dataclasses import dataclass
from typing import Optional
from datetime import datetime
import re

# Encryption setup
ENCRYPTION_KEY = os.getenv("CONFIG_ENCRYPTION_KEY")
try:
    cipher = Fernet(ENCRYPTION_KEY.encode()) if ENCRYPTION_KEY else None
except (ValueError, TypeError) as e:
    logging.warning(f"Invalid CONFIG_ENCRYPTION_KEY, encryption disabled: {e}")
    cipher = None

def encrypt_data(data: str) -> str:
    if data is None:
        return data
    if not cipher:
        return data
    return cipher.encrypt(data.encode()).decode()

def decrypt_data(encrypted: str) -> str:
    if encrypted is None:
        return encrypted
    if not cipher:
        return encrypted
    try:
        return cipher.decrypt(encrypted.encode()).decode()
    except InvalidToken:
        logging.warning("Encrypted config value could not be decrypted; keeping stored value")
        return encrypted

def get_required_env_int(name: str) -> int:
    value = os.getenv(name)
    if not value:
        raise RuntimeError(f"Missing required environment variable: {name}")
    try:
        return int(value)
    except ValueError as e:
        raise RuntimeError(f"{name} must be an integer") from e

def get_required_env(name: str) -> str:
    value = os.getenv(name)
    if not value:
        raise RuntimeError(f"Missing required environment variable: {name}")
    return value
# ---------------- CONFIG ----------------
ADMIN_ID = 2100104246
API_ID = get_required_env_int("API_ID")
API_HASH = get_required_env("API_HASH")
BOT_TOKEN = get_required_env("BOT_TOKEN")
# ---------------- PATH ----------------
BASE_DIR = Path(__file__).parent

SESS_BASE = BASE_DIR / "sessions"
PENDING = SESS_BASE / "pending"
VERIFIED = SESS_BASE / "verified"
BACKUP_DIR = BASE_DIR / "backups"

PENDING.mkdir(parents=True, exist_ok=True)
VERIFIED.mkdir(parents=True, exist_ok=True)
BACKUP_DIR.mkdir(parents=True, exist_ok=True)

CONFIG_FILE = BASE_DIR / "config.json"
STARTED_AT = datetime.now()

from datetime import date

config = {
    "default_2fa": os.getenv("DEFAULT_2FA"),
    "users": [],
    "admins": [str(ADMIN_ID)],
    "blocked_users": [],
    "support_id": str(ADMIN_ID),
    "channels": [],
    "messages": {
        "welcome": "Welcome to RMX Receiver!\n\nEnter your phone number with country code\nExample: +880xxxxxxxxx\n\n/cancel",
        "help": "/start - Start receiving\n/cap - View country capacity\n/balance - View balance\n/mystats - View your stats\n/support - Contact support\n/cancel - Cancel current action",
        "support": "Support: {support_id}"
    },
    "settings": {
        "bot_enabled": True,
        "add_account_enabled": True,
        "proxy_enabled": True,
        "withdraw_enabled": True,
        "withdraw_trx_enabled": True,
        "withdraw_leder_enabled": True,
        "spam_checker_enabled": True,
        "contact_checker_enabled": False,
        "freeze_checker_enabled": False,
        "min_withdraw": 0,
        "max_withdraw": 0
    },
    "withdraw_factors": [],
    "withdraw_requests": [],
    "admin_logs": [],
    "proxies": {},

    "balances": {},          # user_id → balance
    "prices": {},            # country_code → price
    "capacity": {},          # country_code → max capacity
    "used_capacity": {},     # country_code → used count

    "daily_stats": {},
    "all_time_stats": {},
    "last_reset": ""
}





if CONFIG_FILE.exists():
    try:
        with open(CONFIG_FILE, "r") as f:
            loaded = json.load(f)
            config.update(loaded)
            # Decrypt sensitive data
            if "default_2fa" in config:
                config["default_2fa"] = decrypt_data(config["default_2fa"])
            if "proxies" in config:
                decrypted_proxies = {}
                for code, proxy in config["proxies"].items():
                    decrypted_proxies[code] = [decrypt_data(item) for item in proxy]
                    # Convert port back to int
                    decrypted_proxies[code][2] = int(decrypted_proxies[code][2])
                config["proxies"] = decrypted_proxies
    except (json.JSONDecodeError, IOError) as e:
        logging.error(f"Config load failed: {e}")

# ensure proxies key exists
if "proxies" not in config:
    config["proxies"] = {}
if "user_stats" not in config:
    config["user_stats"] = {}
config.setdefault("admins", [str(ADMIN_ID)])
config.setdefault("blocked_users", [])
config.setdefault("support_id", str(ADMIN_ID))
config.setdefault("channels", [])
config.setdefault("withdraw_factors", [])
config.setdefault("withdraw_requests", [])
config.setdefault("admin_logs", [])
config.setdefault("messages", {})
config.setdefault("settings", {})
config["messages"].setdefault("welcome", "Welcome to RMX Receiver!\n\nEnter your phone number with country code\nExample: +880xxxxxxxxx\n\n/cancel")
config["messages"].setdefault("help", "/start - Start receiving\n/cap - View country capacity\n/balance - View balance\n/mystats - View your stats\n/support - Contact support\n/cancel - Cancel current action")
config["messages"].setdefault("support", "Support: {support_id}")
for setting_key, default_value in {
    "bot_enabled": True,
    "add_account_enabled": True,
    "proxy_enabled": True,
    "withdraw_enabled": True,
    "withdraw_trx_enabled": True,
    "withdraw_leder_enabled": True,
    "spam_checker_enabled": True,
    "contact_checker_enabled": False,
    "freeze_checker_enabled": False,
    "min_withdraw": 0,
    "max_withdraw": 0,
}.items():
    config["settings"].setdefault(setting_key, default_value)
for key in ("users", "balances", "prices", "capacity", "used_capacity", "daily_stats", "all_time_stats"):
    config.setdefault(key, [] if key == "users" else {})

if (
    isinstance(config.get("default_2fa"), str)
    and config["default_2fa"].startswith("gAAAA")
    and os.getenv("DEFAULT_2FA")
):
    logging.warning("Stored default_2fa looks encrypted; using DEFAULT_2FA from environment")
    config["default_2fa"] = os.getenv("DEFAULT_2FA")
DEFAULT_2FA_PASSWORD = config.get("default_2fa") or ""
all_users = set(config.get("users", []))
users = (config.get("users", []))

VALID_DEVICES = {
    "iOS": {
        "models": ["iPhone 14", "iPhone 15", "iPhone 15 Pro"],
        "versions": ["17.0", "17.1", "17.2"]
    },
    "Android": {
        "models": ["Samsung Galaxy S24", "Google Pixel 8"],
        "versions": ["14", "15"]
    }
}

def get_random_device():
    os_type = random.choice(list(VALID_DEVICES.keys()))
    os_data = VALID_DEVICES[os_type]
    return {
        "device_model": random.choice(os_data["models"]),
        "system_version": random.choice(os_data["versions"]),
        "app_version": "10.2",
        "system_lang_code": "en-US"
    }

VALID_PHONE_REGEX = re.compile(r'^\+\d{1,3}\d{6,14}$')

def validate_phone_number(phone: str) -> bool:
    return bool(VALID_PHONE_REGEX.match(phone))



# ================= GLOBAL STATE =================
@dataclass
class UserSession:
    step: str = None
    phone: str = None
    client: Optional[object] = None
    old_2fa: str = None
    status_msg_id: int = None
    created_at: datetime = None
    
    def is_active(self):
        if not self.created_at:
            return False
        return (datetime.now() - self.created_at).total_seconds() < 600  # 10min timeout

user_sessions: dict[int, UserSession] = {}

def get_or_create_session(uid: int) -> UserSession:
    if uid not in user_sessions:
        user_sessions[uid] = UserSession(created_at=datetime.now())
    return user_sessions[uid]

# Legacy globals for backward compatibility (remove after migration)
admin_step = {}
step = {}
phones = {}
clients = {}
old_2fa = {}
status_msg = {}

# ================= CONFIG LOAD / SAVE =================

def save_config():
    # Encrypt sensitive data before saving
    config_to_save = config.copy()
    if "default_2fa" in config_to_save:
        config_to_save["default_2fa"] = encrypt_data(config_to_save["default_2fa"])
    if "proxies" in config_to_save:
        encrypted_proxies = {}
        for code, proxy in config_to_save["proxies"].items():
            encrypted_proxies[code] = [encrypt_data(str(item)) for item in proxy]
        config_to_save["proxies"] = encrypted_proxies
    
    tmp_file = CONFIG_FILE.with_suffix(".tmp")
    with open(tmp_file, "w") as f:
        json.dump(config_to_save, f, indent=2)
    os.replace(tmp_file, CONFIG_FILE)


def load_config():
    return config

def create_config_backup() -> Path:
    backup_file = BACKUP_DIR / f"config_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    config_to_save = config.copy()
    if "default_2fa" in config_to_save:
        config_to_save["default_2fa"] = encrypt_data(config_to_save["default_2fa"])
    if "proxies" in config_to_save:
        encrypted_proxies = {}
        for code, proxy in config_to_save["proxies"].items():
            encrypted_proxies[code] = [encrypt_data(str(item)) for item in proxy]
        config_to_save["proxies"] = encrypted_proxies
    with open(backup_file, "w") as f:
        json.dump(config_to_save, f, indent=2)
    return backup_file

def add_admin_log(admin_id: int, action: str):
    logs = config.setdefault("admin_logs", [])
    logs.append({
        "admin_id": str(admin_id),
        "action": action,
        "created_at": datetime.now().isoformat(timespec="seconds")
    })
    config["admin_logs"] = logs[-200:]
    save_config()

async def send_long_message(target, text: str, **kwargs):
    if not text:
        return
    for i in range(0, len(text), 3900):
        await target.reply_text(text[i:i + 3900], **kwargs)

def get_reply_target(update: Update):
    if update.message:
        return update.message
    if update.callback_query and update.callback_query.message:
        return update.callback_query.message
    return None


def register_user(uid: int):
    uid_str = str(uid)
    all_users.add(uid)
    users = [str(user_id) for user_id in config.setdefault("users", [])]
    if uid_str not in users:
        users.append(uid_str)
        config["users"] = users
        save_config()


def increase_user_stock(uid: int):
    stats = config.setdefault("user_stats", {})
    stats[str(uid)] = stats.get(str(uid), 0) + 1
    save_config()


from datetime import date

today = str(date.today())
if config.get("last_reset") != today:
    config["daily_stats"] = {}
    config["last_reset"] = today
    save_config()


logging.basicConfig(level=logging.INFO)

from logging.handlers import RotatingFileHandler

class SecretRedactionFilter(logging.Filter):
    def filter(self, record):
        secrets = [BOT_TOKEN, API_HASH, ENCRYPTION_KEY]
        message = str(record.msg)
        changed = False
        for secret in secrets:
            if secret and secret in message:
                message = message.replace(secret, "[REDACTED]")
                changed = True
        if changed:
            record.msg = message
            record.args = ()
        return True

def setup_logging():
    logger = logging.getLogger()
    logger.setLevel(logging.DEBUG)
    
    # File handler
    fh = RotatingFileHandler('bot.log', maxBytes=5*1024*1024, backupCount=5)
    fh.setLevel(logging.DEBUG)
    
    # Console handler
    ch = logging.StreamHandler()
    ch.setLevel(logging.INFO)
    
    formatter = logging.Formatter(
        '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )
    fh.setFormatter(formatter)
    ch.setFormatter(formatter)
    redaction_filter = SecretRedactionFilter()
    fh.addFilter(redaction_filter)
    ch.addFilter(redaction_filter)
    
    logger.addHandler(fh)
    logger.addHandler(ch)
    logging.getLogger("telegram").setLevel(logging.INFO)
    logging.getLogger("httpx").setLevel(logging.INFO)

setup_logging()

def normalize_country_code(value: str) -> str:
    return re.sub(r"\D", "", str(value or ""))

def get_country_from_phone(phone: str):
    """
    Extract country code from phone number.
    Tries to match with config['proxies'] first.
    If not found, fallback first 2-3 digits.
    """
    digits = normalize_country_code(phone)
    configured_codes = set(config.get("capacity", {})) | set(config.get("prices", {})) | set(config.get("proxies", {}))

    # longest match first
    for code in sorted(configured_codes, key=lambda c: len(normalize_country_code(c)), reverse=True):
        clean_code = normalize_country_code(code)
        if clean_code and digits.startswith(clean_code):
            return code

    return None



def get_proxy_from_phone(phone: str):
    """
    Smart country code matching
    Priority: longest country code first
    Example:
      +880123... -> 880
      +85512...  -> 855
      +4479...   -> 44
      +1206...   -> 1
    """
    digits = normalize_country_code(phone)

    proxies = config.get("proxies", {})
    if not proxies:
        return None
    
    # sort country codes by length (DESC)
    for code in sorted(proxies.keys(), key=lambda c: len(normalize_country_code(c)), reverse=True):
        clean_code = normalize_country_code(code)
        if clean_code and digits.startswith(clean_code):
            proxy_data = proxies[code]
            return tuple(proxy_data)  # (type, host, port, user, pass)
    return None

def get_user_stock(uid: int) -> int:
    return config.get("user_stats", {}).get(str(uid), 0)

async def cleanup_old_sessions(days=7):
    from datetime import datetime, timedelta
    cutoff = datetime.now() - timedelta(days=days)
    
    for folder in [PENDING, VERIFIED]:
        for session_file in folder.glob("*.session"):
            if datetime.fromtimestamp(session_file.stat().st_mtime) < cutoff:
                try:
                    session_file.unlink()
                    logging.info(f"Cleaned up {session_file.name}")
                except OSError as e:
                    logging.error(f"Failed to clean {session_file.name}: {e}")

async def leaderboard(update: Update, context: ContextTypes.DEFAULT_TYPE):
    stats = config.get("user_stats", {})
    if not stats:
        await update.message.reply_text("📉 No data yet")
        return

    top = sorted(stats.items(), key=lambda x: x[1], reverse=True)[:10]

    msg = "🏆 Daily Leaderboard\n\n"
    for i, (uid, total) in enumerate(top, 1):
        msg += f"{i}. User {uid} → {total}\n"

    await update.message.reply_text(msg)

async def leaderboard_daily(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return

    stats = config.get("daily_stats", {})
    if not stats:
        await update.message.reply_text("📉 No data today")
        return

    top = sorted(stats.items(), key=lambda x: x[1], reverse=True)[:10]

    msg = "🏆 Daily Leaderboard\n\n"
    for i, (uid, total) in enumerate(top, 1):
        msg += f"{i}. {uid} → {total}\n"

    await update.message.reply_text(msg)


async def leaderboard_all(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return

    stats = config.get("all_time_stats", {})
    if not stats:
        await update.message.reply_text("📉 No data yet")
        return

    top = sorted(stats.items(), key=lambda x: x[1], reverse=True)[:10]

    msg = "🏆 All-Time Leaderboard\n\n"
    for i, (uid, total) in enumerate(top, 1):
        msg += f"{i}. {uid} → {total}\n"

    await update.message.reply_text(msg)


async def user_stock(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return

    if not context.args:
        await update.message.reply_text("Usage: /userstock <user_id>")
        return

    uid = context.args[0]

    total = config.get("user_stats", {}).get(uid, 0)

    await update.message.reply_text(
        f"👤 User ID: {uid}\n"
        f"📦 Verified accounts: {total}"
    )


def short_health_status(text: str) -> str:
    t = text.lower()

    if "no limits" in t or "can send messages" in t:
        return "🟢 FREE"
    if "limited" in t or "spam" in t:
        return "🔴 SPAM"
    if "frozen" in t or "restricted" in t:
        return "❄️ FROZEN"
    if "new" in t or "recently" in t:
        return "🆕 NEW REG"
    
    return "⚪ UNKNOWN"
        
        
def is_admin(uid: int) -> bool:
    return str(uid) in {str(ADMIN_ID), *[str(a) for a in config.get("admins", [])]}

def is_blocked(uid: int) -> bool:
    return str(uid) in {str(u) for u in config.get("blocked_users", [])}

def setting_enabled(name: str) -> bool:
    return bool(config.get("settings", {}).get(name, True))

def toggle_setting(name: str) -> bool:
    config.setdefault("settings", {})
    config["settings"][name] = not bool(config["settings"].get(name, False))
    save_config()
    return config["settings"][name]

def add_unique_config_value(key: str, value: str) -> bool:
    values = [str(v) for v in config.setdefault(key, [])]
    if value in values:
        return False
    values.append(value)
    config[key] = values
    save_config()
    return True

def remove_config_value(key: str, value: str) -> bool:
    values = [str(v) for v in config.setdefault(key, [])]
    if value not in values:
        return False
    values.remove(value)
    config[key] = values
    save_config()
    return True

def format_settings() -> str:
    labels = {
        "bot_enabled": "Bot",
        "add_account_enabled": "Add account",
        "proxy_enabled": "Proxy",
        "withdraw_enabled": "Withdraw",
        "withdraw_trx_enabled": "Withdraw TRX",
        "withdraw_leder_enabled": "Withdraw Leder card",
        "spam_checker_enabled": "Spam checker",
        "contact_checker_enabled": "Contact checker",
        "freeze_checker_enabled": "Freeze checker",
    }
    lines = ["Settings"]
    for key, label in labels.items():
        state = "ON" if config.get("settings", {}).get(key) else "OFF"
        lines.append(f"{label}: {state}")
    lines.append(f"Min withdraw: {config['settings'].get('min_withdraw', 0)}")
    lines.append(f"Max withdraw: {config['settings'].get('max_withdraw', 0)}")
    return "\n".join(lines)

def build_bot_stats() -> str:
    pending = len(list(PENDING.glob("*.session")))
    verified = len(list(VERIFIED.glob("*.session")))
    balances = config.get("balances", {})
    total_balance = sum(float(v) for v in balances.values()) if balances else 0
    uptime = datetime.now() - STARTED_AT
    return (
        "Bot Statistics\n\n"
        f"Uptime: {str(uptime).split('.')[0]}\n"
        f"Users: {len(config.get('users', []))}\n"
        f"Admins: {len(config.get('admins', []))}\n"
        f"Blocked users: {len(config.get('blocked_users', []))}\n"
        f"Pending sessions: {pending}\n"
        f"Verified sessions: {verified}\n"
        f"Total accounts: {pending + verified}\n"
        f"Total balance: {total_balance}\n"
        f"Withdraw factors: {len(config.get('withdraw_factors', []))}\n"
        f"Channels: {len(config.get('channels', []))}\n"
        f"Proxies: {len(config.get('proxies', {}))}"
    )

def normalize_channel_ref(channel: str) -> str:
    value = str(channel or "").strip()
    if not value:
        return ""
    value = value.replace("https://", "").replace("http://", "")
    if value.startswith("t.me/"):
        value = value[5:].strip("/")
    if value.startswith("telegram.me/"):
        value = value[12:].strip("/")
    if value.startswith("+") or value.startswith("joinchat/"):
        return value
    if value.startswith("-100") or value.lstrip("-").isdigit():
        return value
    return value if value.startswith("@") else f"@{value}"

async def has_joined_required_channels(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    uid = update.effective_user.id
    if is_admin(uid):
        return True
    channels = [normalize_channel_ref(c) for c in config.get("channels", []) if str(c).strip()]
    if not channels:
        return True
    missing = []
    failed = []
    for channel in channels:
        try:
            member = await context.bot.get_chat_member(chat_id=channel, user_id=uid)
            if member.status in ("left", "kicked"):
                missing.append(channel)
        except Exception as e:
            logging.warning(f"Channel join check failed for {channel}: {e}")
            failed.append(channel)
    if missing:
        await update.message.reply_text(
            "Please join required channel(s) first:\n" + "\n".join(missing)
        )
        return False
    if failed:
        await update.message.reply_text(
            "Channel join check failed. Make sure the bot is admin in these channels and save public channels as @username:\n"
            + "\n".join(failed)
        )
        return False
    return True

def get_user_withdraw_history(uid: str) -> list:
    return [r for r in config.get("withdraw_requests", []) if str(r.get("user_id")) == str(uid)]
# ---------------- HANDLERS ----------------
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    if not setting_enabled("bot_enabled"):
        await update.message.reply_text("Bot is currently OFF")
        return
    if is_blocked(uid):
        await update.message.reply_text("Your account is blocked")
        return
    if not await has_joined_required_channels(update, context):
        return
    if not setting_enabled("add_account_enabled"):
        await update.message.reply_text("Add account is currently locked")
        return
    session = get_or_create_session(uid)
    session.step = "phone"
    session.created_at = datetime.now()
    
    register_user(uid)
    await update.message.reply_text(config.get("messages", {}).get("welcome", "Send phone number"))
    return

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(config.get("messages", {}).get("help", "/start"))

async def support(update: Update, context: ContextTypes.DEFAULT_TYPE):
    support_id = config.get("support_id", str(ADMIN_ID))
    text = config.get("messages", {}).get("support", "Support: {support_id}")
    await update.message.reply_text(text.format(support_id=support_id))

async def status_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = str(update.effective_user.id)
    await update.message.reply_text(
        "Account Status\n\n"
        f"Balance: {config.get('balances', {}).get(uid, 0)}\n"
        f"Accounts: {config.get('user_stats', {}).get(uid, 0)}\n"
        f"Today: {config.get('daily_stats', {}).get(uid, 0)}\n"
        f"All time: {config.get('all_time_stats', {}).get(uid, 0)}\n"
        f"Withdraw: {'ON' if setting_enabled('withdraw_enabled') else 'OFF'}\n"
        f"Bot: {'ON' if setting_enabled('bot_enabled') else 'OFF'}"
    )

async def withdraw_history(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = str(update.effective_user.id)
    history = get_user_withdraw_history(uid)[-10:]
    if not history:
        await update.message.reply_text("No withdraw history")
        return
    msg = "Withdraw History\n\n"
    for i, req in enumerate(history, 1):
        msg += f"{i}. {req.get('method')} | {req.get('amount')} | {req.get('status')} | {req.get('created_at')}\n"
    await update.message.reply_text(msg)

async def set_withdraw_status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return
    if len(context.args) != 2:
        await update.message.reply_text("Usage: /setwithdraw <number> <approved|rejected|paid>")
        return
    try:
        req_id = int(context.args[0])
    except ValueError:
        await update.message.reply_text("Invalid request number")
        return
    status = context.args[1].lower()
    if status not in ("approved", "rejected", "paid"):
        await update.message.reply_text("Status must be approved, rejected, or paid")
        return
    requests_list = config.get("withdraw_requests", [])
    req_index = next((i for i, item in enumerate(requests_list) if int(item.get("id", i + 1)) == req_id), -1)
    if req_index < 0:
        await update.message.reply_text("Withdraw request not found")
        return
    req = requests_list[req_index]
    old_status = req.get("status")
    req["status"] = status
    req["updated_at"] = datetime.now().isoformat(timespec="seconds")
    req["updated_by"] = str(update.effective_user.id)
    if status == "rejected" and old_status == "pending":
        user_id = str(req.get("user_id"))
        amount = float(req.get("amount", 0) or 0)
        config.setdefault("balances", {})[user_id] = float(config["balances"].get(user_id, 0) or 0) + amount
    save_config()
    add_admin_log(update.effective_user.id, f"withdraw {req_id} -> {status}")
    await update.message.reply_text(f"Withdraw request #{req_id} updated to {status}")
    try:
        await context.bot.send_message(
            chat_id=int(req.get("user_id")),
            text=f"Your withdraw request #{req_id} status: {status}"
        )
    except Exception as e:
        logging.warning(f"Withdraw status notify failed: {e}")

async def withdraw(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = str(update.effective_user.id)
    if is_blocked(update.effective_user.id):
        await update.message.reply_text("Your account is blocked")
        return
    if not setting_enabled("withdraw_enabled"):
        await update.message.reply_text("Withdraw is currently OFF")
        return
    if len(context.args) < 2:
        await update.message.reply_text("Usage: /withdraw <trx|leder> <amount> [wallet/card]")
        return
    method = context.args[0].lower()
    if method == "trx" and not setting_enabled("withdraw_trx_enabled"):
        await update.message.reply_text("TRX withdraw is currently OFF")
        return
    if method in ("leder", "card", "ledercard") and not setting_enabled("withdraw_leder_enabled"):
        await update.message.reply_text("Leder card withdraw is currently OFF")
        return
    try:
        amount = float(context.args[1])
    except ValueError:
        await update.message.reply_text("Invalid amount")
        return
    min_w = float(config["settings"].get("min_withdraw", 0) or 0)
    max_w = float(config["settings"].get("max_withdraw", 0) or 0)
    balance_amount = float(config.get("balances", {}).get(uid, 0) or 0)
    if amount < min_w:
        await update.message.reply_text(f"Minimum withdraw is {min_w}")
        return
    if max_w and amount > max_w:
        await update.message.reply_text(f"Maximum withdraw is {max_w}")
        return
    if amount > balance_amount:
        await update.message.reply_text("Insufficient balance")
        return
    destination = " ".join(context.args[2:]) if len(context.args) > 2 else ""
    requests_list = config.setdefault("withdraw_requests", [])
    request_id = len(requests_list) + 1
    requests_list.append({
        "id": request_id,
        "user_id": uid,
        "method": method,
        "amount": amount,
        "destination": destination,
        "status": "pending",
        "created_at": datetime.now().isoformat(timespec="seconds")
    })
    config["balances"][uid] = balance_amount - amount
    save_config()
    await update.message.reply_text(f"Withdraw request submitted. Request ID: {request_id}")
    for admin_id in config.get("admins", [str(ADMIN_ID)]):
        try:
            await context.bot.send_message(
                chat_id=int(admin_id),
                text=f"New withdraw request #{request_id}\nUser: {uid}\nMethod: {method}\nAmount: {amount}\nDestination: {destination or '-'}\nUse /setwithdraw {request_id} approved|rejected|paid"
            )
        except Exception as e:
            logging.warning(f"Withdraw report send failed to {admin_id}: {e}")

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    session = get_or_create_session(uid)
    session.step = None
    session.phone = None
    session.old_2fa = None
    session.status_msg_id = None
    c = session.client
    session.client = None

    if c:
        await c.disconnect()
    await update.message.reply_text("❌ Cancelled")

'''async def admin_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    if not is_admin(uid):
        await update.message.reply_text("❌ Access denied")
        return
    
    await update.message.reply_text(
    "👮 Admin Control Panel\n\n"
    "/set2fa <password> → Set default 2FA password\n"
    "/sessions → Pending / Verified count\n"
    "/export_pending → Export pending sessions\n"
    "/export_verified → Export verified sessions\n"
    "/users → User statistics\n"
    "/cancel_admin → Cancel admin action\n"
    "/view2fa → View Current 2FA Password\n"
    "/addproxy <212 socks5 43.152.115.77 59031 user1 pass1> Add Proxy\n"
    "/removeproxy <country code> → Enter Country Code\n"
    "/viewproxies → List all proxies\n"
    "/checkproxies → Ping & health check all proxies\n"
    "/userstock → <user_id> Specific user verified stock\n"
    "/leaderboard_daily → 📆 Daily leaderboard\n"
    "/leaderboard_all → 🏆 All-time leaderboard\n"
    "/addcap <country_code> <price> <capacity>\n"
    
    )'''
async def admin_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return
    await update.message.reply_text(
        "👮 Admin Control Panel\n\nSelect a category:",
        reply_markup=admin_main_menu()
    )

    
    
async def addcap(update, context):
    if not is_admin(update.effective_user.id):
        return

    if len(context.args) != 3:
        await update.message.reply_text(
            "Usage: /addcap <country_code> <price> <capacity>"
        )
        return

    country, price, cap = context.args

    try:
        price = float(price)
        cap = int(cap)
    except ValueError:
        await update.message.reply_text("❌ Invalid price or capacity")
        return

    config["prices"][country] = price
    config["capacity"][country] = cap

    # 🔥 RESET used capacity when admin updates
    config["used_capacity"][country] = 0

    save_config()

    await update.message.reply_text(
        f"✅ Country {country} updated\n"
        f"💵 Price: {price}$\n"
        f"📦 Capacity: {cap}\n"
    )


async def add_balance(update, context):
    if not is_admin(update.effective_user.id):
        return
    if len(context.args) != 2:
        await update.message.reply_text("Usage: /addbalance <user_id> <amount>")
        return
    uid, amount = context.args
    try:
        amount = float(amount)
    except ValueError:
        await update.message.reply_text("Invalid amount")
        return
    bal = config["balances"].get(uid, 0)
    config["balances"][uid] = bal + amount
    save_config()
    await update.message.reply_text(f"💰 Balance added → User {uid}")


async def set2fa(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global DEFAULT_2FA_PASSWORD
    uid = update.effective_user.id

    if not is_admin(uid):
        return

    if not context.args:
        await update.message.reply_text("❌ Usage: /set2fa new_password")
        return

    new_pass = context.args[0]
    DEFAULT_2FA_PASSWORD = new_pass
    config["default_2fa"] = new_pass
    save_config()  # old users & proxies safe থাকবে


    await update.message.reply_text("✅ Default 2FA password updated")


async def sessions_stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return

    pending = len(list(PENDING.glob("*.session")))
    verified = len(list(VERIFIED.glob("*.session")))

    await update.message.reply_text(
        f"📊 Session Statistics\n\n"
        f"🕓 Pending:  {pending}\n"
        f"✅ Verified: {verified}\n"
        f"📁 Total:    {pending + verified}"
    )

async def export_pending(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    if not is_admin(uid):
        return

    admin_step[uid] = "export_pending"
    await update.message.reply_text(
        "⚠️ Confirm export PENDING sessions?\n"
        "Type YES to confirm or /cancel_admin"
    )

async def export_verified(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    if not is_admin(uid):
        return

    admin_step[uid] = "export_verified"
    await update.message.reply_text(
        "⚠️ Confirm export VERIFIED sessions?\n"
        "Type YES to confirm or /cancel_admin"
    )


async def cancel_admin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    admin_step.pop(update.effective_user.id, None)
    await update.message.reply_text("❌ Admin action cancelled")


async def user_stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    cfg = load_config()
    users = cfg.get("users", [])

    if not users:
        await update.message.reply_text("❌ No users found")
        return

    text = "👥 User Statistics\n\n"
    text += f"👤 Total users: {len(users)}\n\n"
    text += "🆔 User IDs:\n"

    for uid in users:
        text += f"- `{uid}`\n"

    await send_long_message(update.message, text, parse_mode="Markdown")

async def export_users_csv(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return
    reply_target = get_reply_target(update)
    if not reply_target:
        return
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["user_id", "balance", "accounts", "daily", "all_time", "blocked"])
    all_uids = sorted(
        set(map(str, config.get("users", [])))
        | set(map(str, config.get("balances", {}).keys()))
        | set(map(str, config.get("user_stats", {}).keys())),
        key=lambda x: int(x) if x.isdigit() else 0
    )
    blocked = set(map(str, config.get("blocked_users", [])))
    for user_id in all_uids:
        writer.writerow([
            user_id,
            config.get("balances", {}).get(user_id, 0),
            config.get("user_stats", {}).get(user_id, 0),
            config.get("daily_stats", {}).get(user_id, 0),
            config.get("all_time_stats", {}).get(user_id, 0),
            "yes" if user_id in blocked else "no"
        ])
    data = io.BytesIO(output.getvalue().encode())
    data.name = f"users_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
    await reply_target.reply_document(data)

async def backup_config(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return
    reply_target = get_reply_target(update)
    if not reply_target:
        return
    backup_file = create_config_backup()
    with open(backup_file, "rb") as f:
        await reply_target.reply_document(f, filename=backup_file.name)

async def admin_logs_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return
    reply_target = get_reply_target(update)
    if not reply_target:
        return
    logs = config.get("admin_logs", [])[-30:]
    if not logs:
        await reply_target.reply_text("No admin logs")
        return
    msg = "Admin Logs\n\n"
    for item in logs:
        msg += f"{item.get('created_at')} | {item.get('admin_id')} | {item.get('action')}\n"
    await send_long_message(reply_target, msg)


async def view2fa(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return

    await update.message.reply_text(
        f"🔐 Current Default 2FA Password:\n\n`{DEFAULT_2FA_PASSWORD}`",
        parse_mode="Markdown"
    )

# ---------------- PROXY SYSTEM ----------------
async def view_proxies(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return
    if not config.get("proxies"):
        await update.message.reply_text("No proxies added")
        return

    msg = "🌐 Current Proxies:\n\n"
    for code, val in config["proxies"].items():
        msg += f"{code} → {val[0]} {val[1]}:{val[2]}\n"
    await update.message.reply_text(msg)

async def add_proxy(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    if not is_admin(uid):
        return
    if len(context.args) != 6:
        await update.message.reply_text("Usage:\n/addproxy <country_code> <type> <host> <port> <user> <pass>")
        return

    code, typ, host, port, user, pw = context.args
    try:
        port = int(port)
    except ValueError:
        await update.message.reply_text("Invalid proxy port")
        return
    config["proxies"][code] = [typ, host, port, user, pw]
    save_config()
    await update.message.reply_text(f"✅ Proxy for {code} added/updated")

async def remove_proxy(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    if not is_admin(uid):
        return
    if not context.args:
        await update.message.reply_text("Usage:\n/removeproxy <country_code>")
        return
    code = context.args[0]
    if code in config["proxies"]:
        config["proxies"].pop(code)
        save_config()
        await update.message.reply_text(f"❌ Proxy {code} removed")
    else:
        await update.message.reply_text(f"⚠️ Proxy {code} not found")

# ---------------- PROXY HEALTH CHECK ----------------
import requests

def get_ip_location(ip):
    try:
        r = requests.get(
            f"http://ip-api.com/json/{ip}?fields=status,country,regionName",
            timeout=6
        ).json()

        if r.get("status") == "success":
            return f"{r.get('country')} / {r.get('regionName')}"
    except:
        pass

    return "Unknown"




import socket, time

async def check_proxy_health(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return
    reply_target = get_reply_target(update)
    if not reply_target:
        return

    proxies = config.get("proxies", {})
    if not proxies:
        await reply_target.reply_text("No proxies added")
        return

    msg = "🌐 Proxy Full Health Report\n\n"

    for code, proxy in proxies.items():
        typ, host, port, user, pw = proxy

        # ---------- PING ----------
        start = time.time()
        try:
            s = socket.create_connection((host, port), timeout=5)
            ping = round((time.time() - start) * 1000, 2)
            s.close()
            health = "✅ UP"
        except:
            msg += f"🌍 {code}\n❌ DOWN\n\n"
            continue

        # ---------- LOCATION ----------
        loc = get_ip_location(host)

        msg += (
            f"🌍 {code}\n"
            f"Status : ✅ UP\n"
            f"Ping   : {ping} ms\n"
            f"IP     : {host}\n"
            f"Location : {loc}\n\n"
)


        
    await reply_target.reply_text(msg)
    
    
# ---------------- DEVICE CHECK ----------------
async def get_logged_devices(client):
    try:
        auths = await client(GetAuthorizationsRequest())
        total = len(auths.authorizations)

        lines = [f"📱 Active devices: {total}\n"]
        for i, a in enumerate(auths.authorizations, 1):
            lines.append(
                f"{i}. {a.device_model or 'Unknown'} | "
                f"{a.platform or 'Unknown'} | "
                f"{a.app_name or 'Telegram'} | "
                f"{a.country or 'Unknown'}"
                f"{' ✅ (current)' if a.current else ''}"
            )
        return "\n".join(lines)

    except Exception as e:
        return f"❌ Device check failed ({e})"
        
# ---------------- CAP CHECK ----------------
async def cap(update, context):
    msg = "📦 Capacity Status\n\n"

    if not config["capacity"]:
        msg += "No country configured yet."
        await update.message.reply_text(msg)
        return

    for country, max_cap in config["capacity"].items():
        used = config["used_capacity"].get(country, 0)
        remaining = max_cap - used
        price = config["prices"].get(country, 0)

        msg += f"{country} → {price}$ | {remaining}\n"

    await update.message.reply_text(msg)

# ---------------- BALANCE CHECK ----------------
async def balance(update, context):
    uid = str(update.effective_user.id)
    bal = config["balances"].get(uid, 0)
    await update.message.reply_text(f"💰 Your Balance: {bal}")

async def my_stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = str(update.effective_user.id)

    daily = config.get("daily_stats", {}).get(uid, 0)
    alltime = config.get("all_time_stats", {}).get(uid, 0)

    await update.message.reply_text(
        "📊 Your Stats\n\n"
        f"📆 Today: {daily}\n"
        f"🏆 All Time: {alltime}"
    )


# ---------------- SAFE OTP ----------------
async def safe_send_code(phone, uid, update):
    session_path = str(PENDING / f"{phone}.session")
    proxy = get_proxy_from_phone(phone) if setting_enabled("proxy_enabled") else None
    user_session = get_or_create_session(uid)

    async def close_failed_client(failed_client):
        if failed_client:
            try:
                await failed_client.disconnect()
            except Exception as disconnect_error:
                logging.error(f"Disconnect failed: {disconnect_error}")
        user_session.client = None

    for attempt in range(5):
        client = None
        try:
            device_info = get_random_device()
            if proxy:
                logging.info(f"Using proxy {proxy[1]}:{proxy[2]} for {phone}")
                client = TelegramClient(
                    session_path,
                    API_ID,
                    API_HASH,
                    proxy=proxy,
                    **device_info
                )
            else:
                logging.info(f"Using REAL IP for {phone}")
                client = TelegramClient(
                    session_path,
                    API_ID,
                    API_HASH,
                    **device_info
                )

            await client.connect()
            await client.send_code_request(phone)
            user_session.client = client
            return True
        except AuthRestartError:
            await close_failed_client(client)
            await asyncio.sleep(3)
        except FloodWaitError as e:
            await close_failed_client(client)
            await update.message.reply_text(f"⏳ Flood wait {e.seconds}s")
            await asyncio.sleep(e.seconds)
        except Exception as e:
            await close_failed_client(client)
            await update.message.reply_text("⚠️ Verification error. Please try again.")
            logging.error(f"OTP error for {phone}", exc_info=True)
            await asyncio.sleep(2)
    return False


# ---------------- SPAM CHECK ----------------
async def spam_check(client: TelegramClient) -> str:
    try:
        async with client.conversation("SpamBot", timeout=15) as conv:
            await conv.send_message("/start")
            resp = await conv.get_response()
            return resp.text
    except asyncio.TimeoutError:
        return "Spam check timeout"
    except Exception as e:
        logging.warning(f"Spam check failed: {e}")
        return "Unable to verify"


# ---------------- USERNAME SET ----------------
def generate_username():
    suffix = ''.join(
        random.choices(string.ascii_lowercase + string.digits, k=8)
    )
    return f"RMX_{suffix}"


async def auto_set_username(client):
    me = await client.get_me()
    if me.username:
        return f"👤 Existing username: @{me.username}"

    await asyncio.sleep(2)
    for _ in range(10):
        username = generate_username()
        try:
            await client(UpdateUsernameRequest(username))
            return f"👤 Username set: @{username}"
        except UsernameOccupiedError:
            continue
        except UsernameInvalidError:
            continue
        except FloodWaitError as e:
            return f"⏳ Username flood wait ({e.seconds}s)"
        except Exception:
            await asyncio.sleep(2)
    return "⚠️ Username temporarily blocked (try later)"


# ---------------- AUTO 2FA ----------------
async def auto_2fa(client, old_pass=None):
    try:
        if old_pass:
            await client.edit_2fa(
                current_password=old_pass,
                new_password=DEFAULT_2FA_PASSWORD,
                hint="R M X"
            )
            return "🔐 2FA: Password Updated"
        else:
            await client.edit_2fa(
                new_password=DEFAULT_2FA_PASSWORD,
                hint="R M X"
            )
            return "🔐 2FA: Protection Enabled."
    except Exception as e:
        return f"❌ 2FA Failed ({e})"


# ---------------- MESSAGE HANDLER ----------------
async def handle(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    text = update.message.text.strip()
    session = get_or_create_session(uid)
    if session.step and not session.is_active():
        session.step = None
        session.phone = None
        session.old_2fa = None
        session.status_msg_id = None
        if session.client:
            try:
                await session.client.disconnect()
            except Exception as e:
                logging.warning(f"Expired session disconnect failed: {e}")
        session.client = None
        await update.message.reply_text("Session expired. Please start again with /start")
        return
    if is_blocked(uid) and not is_admin(uid):
        await update.message.reply_text("Your account is blocked")
        return
    
    if uid in admin_step and admin_step[uid] == "set2fa":
        global DEFAULT_2FA_PASSWORD
        DEFAULT_2FA_PASSWORD = text
        config["default_2fa"] = text
        save_config()
        admin_step.pop(uid)
        await update.message.reply_text("✅ Default 2FA updated & saved")
        return

    if uid in admin_step:
        if admin_step[uid] == "add_proxy":
            parts = text.split()
            if len(parts) != 6:
                await update.message.reply_text("❌ Invalid format: <country> <type> <host> <port> <user> <pass>")
                return
            country, typ, host, port, user, pw = parts
            try:
                port = int(port)
                config["proxies"][country] = [typ, host, port, user, pw]
                save_config()
                await update.message.reply_text(f"✅ Proxy {country} added")
            except Exception as e:
                await update.message.reply_text(f"❌ Error: {e}")
            finally:
                admin_step.pop(uid, None)
            return
        elif admin_step[uid] == "add_admin":
            target_uid = text.strip()
            added = add_unique_config_value("admins", target_uid)
            await update.message.reply_text("Admin added" if added else "Admin already exists")
            admin_step.pop(uid, None)
            return
        elif admin_step[uid] == "remove_admin":
            target_uid = text.strip()
            if target_uid == str(ADMIN_ID):
                await update.message.reply_text("Main admin cannot be removed")
            else:
                removed = remove_config_value("admins", target_uid)
                await update.message.reply_text("Admin removed" if removed else "Admin not found")
            admin_step.pop(uid, None)
            return
        elif admin_step[uid] == "block_user":
            target_uid = text.strip()
            added = add_unique_config_value("blocked_users", target_uid)
            await update.message.reply_text("User blocked" if added else "User already blocked")
            admin_step.pop(uid, None)
            return
        elif admin_step[uid] == "unblock_user":
            target_uid = text.strip()
            removed = remove_config_value("blocked_users", target_uid)
            await update.message.reply_text("User unblocked" if removed else "User not blocked")
            admin_step.pop(uid, None)
            return
        elif admin_step[uid] == "send_user":
            parts = text.split(maxsplit=1)
            if len(parts) != 2:
                await update.message.reply_text("Format: user_id message")
                return
            target_uid, message = parts
            try:
                await context.bot.send_message(chat_id=int(target_uid), text=message)
                await update.message.reply_text("Message sent")
            except Exception as e:
                await update.message.reply_text(f"Send failed: {e}")
            admin_step.pop(uid, None)
            return
        elif admin_step[uid] == "broadcast":
            sent = 0
            failed = 0
            for target_uid in config.get("users", []):
                try:
                    await context.bot.send_message(chat_id=int(target_uid), text=text)
                    sent += 1
                    await asyncio.sleep(0.05)
                except Exception:
                    failed += 1
            await update.message.reply_text(f"Broadcast done. Sent: {sent}, Failed: {failed}")
            add_admin_log(uid, f"broadcast sent={sent} failed={failed}")
            admin_step.pop(uid, None)
            return
        elif admin_step[uid] == "user_info":
            target_uid = text.strip()
            msg = (
                f"User: {target_uid}\n"
                f"Balance: {config.get('balances', {}).get(target_uid, 0)}\n"
                f"Accounts: {config.get('user_stats', {}).get(target_uid, 0)}\n"
                f"Daily: {config.get('daily_stats', {}).get(target_uid, 0)}\n"
                f"All time: {config.get('all_time_stats', {}).get(target_uid, 0)}\n"
                f"Blocked: {'YES' if target_uid in config.get('blocked_users', []) else 'NO'}"
            )
            await update.message.reply_text(msg)
            admin_step.pop(uid, None)
            return
        elif admin_step[uid] == "set_support":
            config["support_id"] = text.strip()
            save_config()
            await update.message.reply_text("Support ID updated")
            admin_step.pop(uid, None)
            return
        elif admin_step[uid] == "add_channel":
            channel = normalize_channel_ref(text)
            added = add_unique_config_value("channels", channel)
            await update.message.reply_text("Channel added" if added else "Channel already exists")
            admin_step.pop(uid, None)
            return
        elif admin_step[uid] == "remove_channel":
            channel = normalize_channel_ref(text)
            removed = remove_config_value("channels", channel) or remove_config_value("channels", text.strip())
            await update.message.reply_text("Channel removed" if removed else "Channel not found")
            admin_step.pop(uid, None)
            return
        elif admin_step[uid] == "set_message":
            parts = text.split(maxsplit=1)
            if len(parts) != 2 or parts[0] not in ("welcome", "help", "support"):
                await update.message.reply_text("Format: welcome|help|support message")
                return
            config.setdefault("messages", {})[parts[0]] = parts[1]
            save_config()
            await update.message.reply_text("Message updated")
            admin_step.pop(uid, None)
            return
        elif admin_step[uid] == "add_withdraw_factor":
            config.setdefault("withdraw_factors", []).append(text.strip())
            save_config()
            await update.message.reply_text("Withdraw factor added")
            admin_step.pop(uid, None)
            return
        elif admin_step[uid] == "set_min_withdraw":
            try:
                config["settings"]["min_withdraw"] = float(text.strip())
                save_config()
                await update.message.reply_text("Minimum withdraw updated")
            except ValueError:
                await update.message.reply_text("Invalid amount")
            admin_step.pop(uid, None)
            return
        elif admin_step[uid] == "set_max_withdraw":
            try:
                config["settings"]["max_withdraw"] = float(text.strip())
                save_config()
                await update.message.reply_text("Maximum withdraw updated")
            except ValueError:
                await update.message.reply_text("Invalid amount")
            admin_step.pop(uid, None)
            return
        
        elif admin_step[uid] == "remove_proxy":
            code = text.strip()
            if code in config["proxies"]:
                config["proxies"].pop(code)
                save_config()
                await update.message.reply_text(f"❌ Proxy {code} removed")
            else:
                await update.message.reply_text(f"⚠️ Proxy {code} not found")
            admin_step.pop(uid, None)
            return
        
        elif admin_step[uid] == "addcap":
            parts = text.split()
            if len(parts) != 3:
                await update.message.reply_text("❌ Invalid format: <country> <price> <capacity>")
                return
            country, price, cap = parts
            try:
                price = float(price)
                cap = int(cap)
                config["prices"][country] = price
                config["capacity"][country] = cap
                config["used_capacity"][country] = 0
                save_config()
                await update.message.reply_text(f"✅ Country {country} updated")
            except Exception as e:
                await update.message.reply_text(f"❌ Error: {e}")
            finally:
                admin_step.pop(uid, None)
            return
        
        elif admin_step[uid] == "userstock":
            try:
                target_uid = int(text.strip())
                stock = get_user_stock(target_uid)
                await update.message.reply_text(f"📦 User {target_uid}: {stock} accounts")
            except ValueError:
                await update.message.reply_text("❌ Invalid user ID")
            finally:
                admin_step.pop(uid, None)
            return
        
        elif admin_step[uid] == "add_balance":
            parts = text.strip().split()
            if len(parts) != 2:
                await update.message.reply_text("❌ Format: user_id amount")
                return
            try:
                target_uid, amount = parts
                amount = float(amount)
                config["balances"][target_uid] = config["balances"].get(target_uid, 0) + amount
                save_config()
                await update.message.reply_text(f"💰 Added {amount}$ to user {target_uid}")
            except ValueError:
                await update.message.reply_text("❌ Invalid user ID or amount")
            finally:
                admin_step.pop(uid, None)
            return
        
        elif admin_step[uid] == "remove_balance":
            parts = text.strip().split()
            if len(parts) != 2:
                await update.message.reply_text("❌ Format: user_id amount")
                return
            try:
                target_uid, amount = parts
                amount = float(amount)
                current = config["balances"].get(target_uid, 0)
                config["balances"][target_uid] = max(0, current - amount)
                save_config()
                await update.message.reply_text(f"💸 Removed {amount}$ from user {target_uid}")
            except ValueError:
                await update.message.reply_text("❌ Invalid user ID or amount")
            finally:
                admin_step.pop(uid, None)
            return
        
        elif admin_step[uid] == "reset_user_stats":
            try:
                target_uid = text.strip()
                if target_uid in config.get("user_stats", {}):
                    config["user_stats"][target_uid] = 0
                    save_config()
                    await update.message.reply_text(f"🔄 Reset stats for user {target_uid}")
                else:
                    await update.message.reply_text(f"⚠️ User {target_uid} not found")
            except Exception as e:
                await update.message.reply_text(f"❌ Error: {e}")
            finally:
                admin_step.pop(uid, None)
            return
        if text.upper() == "YES":
            action = admin_step[uid]
            verified_all = len(list(VERIFIED.glob("*.session")))

            folder = PENDING if action == "export_pending" else VERIFIED
            zip_name = f"{action} {verified_all}.zip"

            import zipfile, os

            active_clients = sum(1 for s in user_sessions.values() if s.client is not None)
            if active_clients > 0:
                await update.message.reply_text(f"⚠️ {active_clients} active user session(s) running\nTry again later")
                return

            admin_step.pop(uid, None)

            try:
                with zipfile.ZipFile(zip_name, "w") as z:
                    for f in folder.glob("*.session"):
                        z.write(f, arcname=f.name)
                
                with open(zip_name, "rb") as f:
                    await update.message.reply_document(f)
                
                for f in folder.glob("*.session"):
                    f.unlink()
            finally:
                if os.path.exists(zip_name):
                    os.remove(zip_name)

            for f in folder.glob("*.session"):
                f.unlink()

            await update.message.reply_text("✅ Export completed & folder cleared")
            return

        elif text.upper() == "NO":
                admin_step.pop(uid, None)
                await update.message.reply_text("❌ Export cancelled")
                return
        else:
            await update.message.reply_text("⚠️ Type YES or NO")
            return
            
    
    if not session.step:
        await update.message.reply_text("👉 Restart Bot /start ")
        return

# ------------------ PHONE ----------------------------
    if session.step == "phone":
        if not await has_joined_required_channels(update, context):
            return
        if not validate_phone_number(text):
            await update.message.reply_text("❌ Invalid phone format: +880xxxxxxxxx")
            return
            
        country = get_country_from_phone(text)

        if not country or country not in config.get("capacity", {}):
            await update.message.reply_text("❌ Country not supported")
            return

        used = config["used_capacity"].get(country, 0)
        limit = config["capacity"].get(country, 0)

        if used >= limit:
            await update.message.reply_text(
                f"🚫 This country's number capacity is full ({country})")
            return

        session.phone = text

        msg = await update.message.reply_text("⏳ OTP sending, please wait...")
        session.status_msg_id = msg.message_id

        ok = await safe_send_code(text, uid, update)
        if not ok:
            session.step = None
            return

        session.step = "otp"
        await context.bot.edit_message_text(
            chat_id=update.effective_chat.id,
            message_id=session.status_msg_id,
            text=(
                f"🔢 Enter the code sent to the number or send the message.  ( {text} )\n\n"
                f"➿/cancel"
            )
        )
        return

    # -------- OTP --------
    if session.step == "otp":
        client = session.client
        phone = session.phone

        await context.bot.edit_message_text(
            chat_id=update.effective_chat.id,
            message_id=session.status_msg_id,
            text="🔄 Trying to login, please wait..."
        )

        try:
            await client.sign_in(phone, text)
        except SessionPasswordNeededError:
            session.step = "old2fa"
            await update.message.reply_text("🔑 Enter Your 2FA Password:")
            return
        except Exception as e:
            await update.message.reply_text(f"❌ Login failed: {e}")
            return

        await finalize(update, context, uid)
        return

    # -------- OLD 2FA --------
    if session.step == "old2fa":
        client = session.client
        session.old_2fa = text
        try:
            await client.sign_in(password=text)
        except:
            await update.message.reply_text("❌ Wrong password\nTry again")
            return
        await finalize(update, context, uid)


# ---------------- FINALIZE ----------------
async def finalize(update, context, uid):
    session = get_or_create_session(uid)
    client = session.client
    phone = session.phone
    if setting_enabled("spam_checker_enabled"):
        spam_raw = await spam_check(client)
        health = short_health_status(spam_raw)
    else:
        health = "Spam checker OFF"
    username_status = await auto_set_username(client)
    twofa = await auto_2fa(client, session.old_2fa)
    devices_info = await get_logged_devices(client)
    uid_str = str(update.effective_user.id)

    # Daily
    config.setdefault("daily_stats", {})
    config["daily_stats"][uid_str] = config["daily_stats"].get(uid_str, 0) + 1

    # All time
    config.setdefault("all_time_stats", {})
    config["all_time_stats"][uid_str] = config["all_time_stats"].get(uid_str, 0) + 1

    save_config()

    for admin_id in config.get("admins", [str(ADMIN_ID)]):
        try:
            await context.bot.send_message(
                chat_id=int(admin_id),
                text=f"New account report\nUser: {uid_str}\nPhone: {phone}\nHealth: {health}"
            )
        except Exception as e:
            logging.warning(f"Account report send failed to {admin_id}: {e}")


    await client.disconnect()
    clients.pop(uid, None)
    del client

    await asyncio.sleep(1)

    old_path = PENDING / f"{phone}.session"
    new_path = VERIFIED / f"{phone}.session"

    try:
        if old_path.exists():
            old_path.replace(new_path)
    except Exception as e:
        logging.exception(f"Session move failed: {e}")
    
    increase_user_stock(update.effective_user.id)
    user_total = get_user_stock(update.effective_user.id)
    country = get_country_from_phone(phone)
    price = config["prices"].get(country, 0)
    
    
    await context.bot.edit_message_text(
        chat_id=update.effective_chat.id,
        message_id=session.status_msg_id,
        text=(
            f"✅ Congratulations, the account\n"
            f"( {phone} ) has been successfully verified\n\n"
            f"💰 Balance added: +{price}\n"
            f"📦 Your verified accounts: {user_total}\n\n"
            f"{twofa}\n"
            f"{username_status}\n"
            f"{devices_info}\n\n"
            f"Health Status: {health}\n\n"
        )
    )

    
    session.step = "phone"
    session.created_at = datetime.now()
    session.phone = None
    session.old_2fa = None
    session.client = None
    session.status_msg_id = None

    uid_str = str(update.effective_user.id)

    # add balance
    config["balances"][uid_str] = config["balances"].get(uid_str, 0) + price

    # increase capacity used
    config["used_capacity"][country] = config["used_capacity"].get(country, 0) + 1

    save_config()
def admin_main_menu():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("2FA Settings", callback_data="admin_2fa")],
        [InlineKeyboardButton("Session Settings", callback_data="admin_sessions")],
        [InlineKeyboardButton("Proxy Settings", callback_data="admin_proxy")],
        [InlineKeyboardButton("Bot Settings", callback_data="admin_bot")],
        [InlineKeyboardButton("User Management", callback_data="admin_users")],
        [InlineKeyboardButton("Admins", callback_data="admin_admins")],
        [InlineKeyboardButton("Custom", callback_data="admin_custom")],
        [InlineKeyboardButton("Withdraw", callback_data="admin_withdraw")],
        [InlineKeyboardButton("Statistics", callback_data="admin_stats")],
        [InlineKeyboardButton("System", callback_data="admin_system")],
    ])

def menu_2fa():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("View 2FA", callback_data="view2fa")],
        [InlineKeyboardButton("Set 2FA", callback_data="set2fa")],
        [InlineKeyboardButton("Back", callback_data="admin_back")]
    ])

def menu_sessions():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("Session Stats", callback_data="sessions")],
        [InlineKeyboardButton("Export Pending", callback_data="export_pending")],
        [InlineKeyboardButton("Export Verified", callback_data="export_verified")],
        [InlineKeyboardButton("Clear Old Sessions", callback_data="clear_sessions")],
        [InlineKeyboardButton("Back", callback_data="admin_back")]
    ])

def menu_proxy():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("View Proxies", callback_data="view_proxies")],
        [InlineKeyboardButton("Add Proxy", callback_data="add_proxy")],
        [InlineKeyboardButton("Remove Proxy", callback_data="remove_proxy")],
        [InlineKeyboardButton("Proxy ON/OFF", callback_data="toggle_proxy_enabled")],
        [InlineKeyboardButton("Proxy Health", callback_data="check_proxies")],
        [InlineKeyboardButton("Back", callback_data="admin_back")]
    ])

def menu_bot():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("Bot ON/OFF", callback_data="toggle_bot_enabled")],
        [InlineKeyboardButton("Add Account Lock/Unlock", callback_data="toggle_add_account_enabled")],
        [InlineKeyboardButton("Spam Checker ON/OFF", callback_data="toggle_spam_checker_enabled")],
        [InlineKeyboardButton("Contact Checker ON/OFF", callback_data="toggle_contact_checker_enabled")],
        [InlineKeyboardButton("Freeze Checker ON/OFF", callback_data="toggle_freeze_checker_enabled")],
        [InlineKeyboardButton("Add Capacity", callback_data="addcap")],
        [InlineKeyboardButton("User Statistics", callback_data="user_stats")],
        [InlineKeyboardButton("User Stock", callback_data="userstock")],
        [InlineKeyboardButton("All-Time Leaderboard", callback_data="leaderboard_all")],
        [InlineKeyboardButton("Back", callback_data="admin_back")]
    ])

def menu_users():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("View All Users", callback_data="view_users")],
        [InlineKeyboardButton("Export Users CSV", callback_data="export_users_csv")],
        [InlineKeyboardButton("Get User Info", callback_data="user_info")],
        [InlineKeyboardButton("Block User", callback_data="block_user")],
        [InlineKeyboardButton("Unblock User", callback_data="unblock_user")],
        [InlineKeyboardButton("Send User Message", callback_data="send_user")],
        [InlineKeyboardButton("Broadcast All", callback_data="broadcast")],
        [InlineKeyboardButton("Add Balance", callback_data="add_balance")],
        [InlineKeyboardButton("Remove Balance", callback_data="remove_balance")],
        [InlineKeyboardButton("Reset User Stats", callback_data="reset_user_stats")],
        [InlineKeyboardButton("Back", callback_data="admin_back")]
    ])

def menu_admins():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("View Admins", callback_data="view_admins")],
        [InlineKeyboardButton("Add Admin", callback_data="add_admin")],
        [InlineKeyboardButton("Remove Admin", callback_data="remove_admin")],
        [InlineKeyboardButton("Back", callback_data="admin_back")]
    ])

def menu_custom():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("View Messages", callback_data="view_messages")],
        [InlineKeyboardButton("Set Message", callback_data="set_message")],
        [InlineKeyboardButton("View Channels", callback_data="view_channels")],
        [InlineKeyboardButton("Add Channel", callback_data="add_channel")],
        [InlineKeyboardButton("Remove Channel", callback_data="remove_channel")],
        [InlineKeyboardButton("Set Support ID", callback_data="set_support")],
        [InlineKeyboardButton("Back", callback_data="admin_back")]
    ])

def menu_withdraw():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("Withdraw ON/OFF", callback_data="toggle_withdraw_enabled")],
        [InlineKeyboardButton("TRX ON/OFF", callback_data="toggle_withdraw_trx_enabled")],
        [InlineKeyboardButton("Leder Card ON/OFF", callback_data="toggle_withdraw_leder_enabled")],
        [InlineKeyboardButton("Set Min Withdraw", callback_data="set_min_withdraw")],
        [InlineKeyboardButton("Set Max Withdraw", callback_data="set_max_withdraw")],
        [InlineKeyboardButton("View Factors", callback_data="view_withdraw_factors")],
        [InlineKeyboardButton("Add Factor", callback_data="add_withdraw_factor")],
        [InlineKeyboardButton("View Requests", callback_data="view_withdraw_requests")],
        [InlineKeyboardButton("Back", callback_data="admin_back")]
    ])

def menu_stats():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("Detailed Stats", callback_data="bot_stats")],
        [InlineKeyboardButton("Daily Leaderboard", callback_data="daily_leaderboard")],
        [InlineKeyboardButton("All-Time Leaderboard", callback_data="all_time_leaderboard")],
        [InlineKeyboardButton("Reset Daily Stats", callback_data="reset_daily_stats")],
        [InlineKeyboardButton("Back", callback_data="admin_back")]
    ])

def menu_system():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("Health Check", callback_data="health_check")],
        [InlineKeyboardButton("View Settings", callback_data="view_settings")],
        [InlineKeyboardButton("Backup Config", callback_data="backup_config")],
        [InlineKeyboardButton("Admin Logs", callback_data="admin_logs")],
        [InlineKeyboardButton("View Recent Logs", callback_data="view_logs")],
        [InlineKeyboardButton("Clear Old Sessions", callback_data="clear_sessions")],
        [InlineKeyboardButton("Back", callback_data="admin_back")]
    ])

async def admin_buttons(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()


    data = q.data
    uid = q.from_user.id

    if not is_admin(uid):
        return

    # ===== CATEGORY =====
    if data == "admin_2fa":
        await q.edit_message_text("🔐 2FA Settings", reply_markup=menu_2fa())
        return

    if data == "admin_sessions":
        await q.edit_message_text("📁 Session Settings", reply_markup=menu_sessions())
        return

    if data == "admin_proxy":
        await q.edit_message_text("🌐 Proxy Settings", reply_markup=menu_proxy())
        return

    if data == "admin_bot":
        await q.edit_message_text("⚙️ Bot Settings", reply_markup=menu_bot())
        return

    if data == "admin_users":
        await q.edit_message_text("👥 User Management", reply_markup=menu_users())
        return

    if data == "admin_admins":
        await q.edit_message_text("Admins", reply_markup=menu_admins())
        return

    if data == "admin_custom":
        await q.edit_message_text("Custom Messages / Channels", reply_markup=menu_custom())
        return

    if data == "admin_withdraw":
        await q.edit_message_text("Withdraw Settings", reply_markup=menu_withdraw())
        return

    if data == "admin_stats":
        await q.edit_message_text("📊 Statistics", reply_markup=menu_stats())
        return

    if data == "admin_system":
        await q.edit_message_text("🖥️ System", reply_markup=menu_system())
        return

    if data == "admin_back":
        await q.edit_message_text(
            "👮 Admin Control Panel",
            reply_markup=admin_main_menu()
        )
        return

    # ===== DIRECT =====
    if data == "view2fa":
        await q.message.reply_text(
            f"🔐 Current Default 2FA Password:\n\n`{DEFAULT_2FA_PASSWORD}`",
            parse_mode="Markdown"
        )
        return
        
    if data == "user_stats":
        cfg = load_config()
        users = cfg.get("users", [])

        text = f"👤 Total users: {len(users)}\n\n"
        text += "🆔 User IDs:\n"

        for uid in users:
            text += f"- {uid}\n"

        await q.message.reply_text(text)
        return


    if data == "sessions":
        pending = len(list(PENDING.glob("*.session")))
        verified = len(list(VERIFIED.glob("*.session")))
        await q.message.reply_text(
            f"📊 Session Statistics\n\n"
            f"🕓 Pending: {pending}\n"
            f"✅ Verified: {verified}\n"
            f"📁 Total: {pending + verified}"
        )
        return

    if data == "view_proxies":
        if not config.get("proxies"):
            await q.message.reply_text("⚠️ No proxies added yet")
            return

        msg = "🌐 Current Proxies:\n\n"
        for code, val in config["proxies"].items():
            msg += f"{code} → {val[0]} {val[1]}:{val[2]}\n"
        await send_long_message(q.message, msg)
        return

    if data == "check_proxies":
        await check_proxy_health(update, context)
        return

    if data in ("export_pending", "export_verified"):
        admin_step[uid] = data
        folder_name = "PENDING" if data == "export_pending" else "VERIFIED"
        await q.message.reply_text(
            f"Confirm export {folder_name} sessions?\n"
            "Type YES to confirm or /cancel_admin"
        )
        return

    if data == "leaderboard_all":
        stats = config.get("all_time_stats", {})
        if not stats:
            await q.message.reply_text("📉 No data yet")
            return

        top = sorted(stats.items(), key=lambda x: x[1], reverse=True)[:10]
        msg = "🏆 All-Time Leaderboard\n\n"
        for i, (u, total) in enumerate(top, 1):
            msg += f"{i}. {u} → {total}\n"
        await send_long_message(q.message, msg)
        return

    if data.startswith("toggle_"):
        setting = data.replace("toggle_", "")
        state = toggle_setting(setting)
        add_admin_log(uid, f"{setting} -> {'ON' if state else 'OFF'}")
        await q.message.reply_text(f"{setting}: {'ON' if state else 'OFF'}")
        return

    if data == "view_settings":
        await q.message.reply_text(format_settings())
        return

    if data == "bot_stats":
        await q.message.reply_text(build_bot_stats())
        return

    if data == "view_admins":
        await q.message.reply_text("Admins:\n" + "\n".join(config.get("admins", [])))
        return

    if data == "export_users_csv":
        await export_users_csv(update, context)
        return

    if data == "backup_config":
        await backup_config(update, context)
        return

    if data == "admin_logs":
        await admin_logs_command(update, context)
        return

    if data == "view_messages":
        messages = config.get("messages", {})
        msg = "\n\n".join(f"{k}:\n{v}" for k, v in messages.items())
        await q.message.reply_text(msg or "No messages configured")
        return

    if data == "view_channels":
        channels = [normalize_channel_ref(c) for c in config.get("channels", [])]
        await q.message.reply_text("Channels:\n" + ("\n".join(channels) if channels else "No channels"))
        return

    if data == "view_withdraw_factors":
        factors = config.get("withdraw_factors", [])
        await q.message.reply_text("Withdraw Factors:\n" + ("\n".join(factors) if factors else "No factors"))
        return

    if data == "view_withdraw_requests":
        requests_list = config.get("withdraw_requests", [])[-20:]
        if not requests_list:
            await q.message.reply_text("No withdraw requests")
            return
        msg = "Withdraw Requests:\n\n"
        for i, req in enumerate(requests_list, 1):
            msg += f"{req.get('id', i)}. {req.get('user_id')} | {req.get('method')} | {req.get('amount')} | {req.get('status')}\n"
        await send_long_message(q.message, msg)
        return

    # ===== NEED INPUT =====
    if data == "set2fa":
        admin_step[uid] = "set2fa"
        await q.message.reply_text("✏️ Send new 2FA password:")
        return

    if data == "add_proxy":
        admin_step[uid] = "add_proxy"
        await q.message.reply_text(
            "Send proxy:\n<country> <type> <host> <port> <user> <pass>"
        )
        return

    if data == "remove_proxy":
        admin_step[uid] = "remove_proxy"
        await q.message.reply_text(
        "Remove proxy\n\n"
        "Example:\n`/removeproxy` 880",
        parse_mode="Markdown"
        )
        return

    if data == "addcap":
        admin_step[uid] = "addcap"
        await q.message.reply_text(
            "Send format:\n"
            "`country price capacity`\n\n"
            "Example:\n"
            "`/addcap` 880 2.5 100",
            parse_mode="Markdown"
        )
        return

    if data == "userstock":
        admin_step[uid] = "userstock"
        await q.message.reply_text("Send user ID:")
        return

    # ===== NEW FEATURES =====
    if data == "view_users":
        balances = config.get("balances", {})
        user_stats = config.get("user_stats", {})
        if not balances and not user_stats:
            await q.message.reply_text("👥 No users found")
            return
        
        msg = "👥 All Users:\n\n"
        all_uids = set(balances.keys()) | set(user_stats.keys())
        for uid in sorted(all_uids, key=int):
            bal = balances.get(uid, 0)
            stock = user_stats.get(str(uid), 0)
            msg += f"ID: {uid} | 💰 {bal}$ | 📦 {stock}\n"
        await send_long_message(q.message, msg)
        return

    if data == "daily_leaderboard":
        stats = config.get("daily_stats", {})
        if not stats:
            await q.message.reply_text("📉 No daily data")
            return
        top = sorted(stats.items(), key=lambda x: x[1], reverse=True)[:10]
        msg = "📅 Daily Leaderboard\n\n"
        for i, (u, total) in enumerate(top, 1):
            msg += f"{i}. {u} → {total}\n"
        await send_long_message(q.message, msg)
        return

    if data == "all_time_leaderboard":
        stats = config.get("all_time_stats", {})
        if not stats:
            await q.message.reply_text("📉 No data yet")
            return
        top = sorted(stats.items(), key=lambda x: x[1], reverse=True)[:10]
        msg = "🏆 All-Time Leaderboard\n\n"
        for i, (u, total) in enumerate(top, 1):
            msg += f"{i}. {u} → {total}\n"
        await send_long_message(q.message, msg)
        return

    if data == "reset_daily_stats":
        config["daily_stats"] = {}
        save_config()
        await q.message.reply_text("✅ Daily stats reset")
        return

    if data == "health_check":
        pending = len(list(PENDING.glob("*.session")))
        verified = len(list(VERIFIED.glob("*.session")))
        active_sessions = sum(1 for s in user_sessions.values() if s.client is not None)
        proxies = len(config.get("proxies", {}))
        msg = f"❤️ System Health\n\n📁 Sessions: {pending} pending, {verified} verified\n👥 Active: {active_sessions} users\n🌐 Proxies: {proxies} configured"
        await send_long_message(q.message, msg)
        return

    if data == "view_logs":
        try:
            with open("bot.log", "r") as f:
                lines = f.readlines()[-20:]  # Last 20 lines
            msg = "📜 Recent Logs:\n\n" + "".join(lines)
            await send_long_message(q.message, msg)
        except FileNotFoundError:
            await q.message.reply_text("📜 No logs found")
        return

    if data == "clear_sessions":
        await cleanup_old_sessions(days=7)
        await q.message.reply_text("🧹 Old sessions cleared (7+ days)")
        return

    # ===== NEED INPUT =====
    if data == "add_balance":
        admin_step[uid] = "add_balance"
        await q.message.reply_text("Send: user_id amount\nExample: 123456789 10.5")
        return

    if data == "remove_balance":
        admin_step[uid] = "remove_balance"
        await q.message.reply_text("Send: user_id amount\nExample: 123456789 5.0")
        return

    if data == "reset_user_stats":
        admin_step[uid] = "reset_user_stats"
        await q.message.reply_text("Send user ID to reset stats:")
        return

    input_prompts = {
        "add_admin": "Send admin user ID:",
        "remove_admin": "Send admin user ID to remove:",
        "block_user": "Send user ID to block:",
        "unblock_user": "Send user ID to unblock:",
        "send_user": "Send: user_id message",
        "broadcast": "Send broadcast message:",
        "user_info": "Send user ID:",
        "set_support": "Send support user ID or username:",
        "add_channel": "Send channel username or ID:",
        "remove_channel": "Send channel username or ID:",
        "set_message": "Send: welcome|help|support message",
        "add_withdraw_factor": "Send withdraw factor text:",
        "set_min_withdraw": "Send minimum withdraw amount:",
        "set_max_withdraw": "Send maximum withdraw amount:",
    }
    if data in input_prompts:
        admin_step[uid] = data
        await q.message.reply_text(input_prompts[data])
        return


async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE):
    logging.exception("Unhandled bot error", exc_info=context.error)
    try:
        for admin_id in config.get("admins", [str(ADMIN_ID)]):
            await context.bot.send_message(chat_id=int(admin_id), text=f"Bot error: {context.error}")
    except Exception:
        logging.exception("Error notification failed")

# ---------------- MAIN ----------------
async def main():
    app = ApplicationBuilder().token(BOT_TOKEN).build()
    app.add_error_handler(error_handler)
    app.add_handler(CommandHandler("admin", admin_menu))
    app.add_handler(CallbackQueryHandler(admin_buttons))

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CommandHandler("support", support))
    app.add_handler(CommandHandler("status", status_command))
    app.add_handler(CommandHandler("withdraw", withdraw))
    app.add_handler(CommandHandler("withdraw_history", withdraw_history))
    app.add_handler(CommandHandler("cancel", cancel))
    app.add_handler(CommandHandler("cancel_admin", cancel_admin))

    # ===== ADMIN BUY SYSTEM =====
    app.add_handler(CommandHandler("addcap", addcap))
    app.add_handler(CommandHandler("addbalance", add_balance))
    app.add_handler(CommandHandler("setwithdraw", set_withdraw_status))
    app.add_handler(CommandHandler("exportusers", export_users_csv))
    app.add_handler(CommandHandler("backupconfig", backup_config))
    app.add_handler(CommandHandler("adminlogs", admin_logs_command))

    # ===== USER VIEW =====
    app.add_handler(CommandHandler("balance", balance))
    app.add_handler(CommandHandler("cap", cap))

    # ===== EXISTING =====
    app.add_handler(CommandHandler("sessions", sessions_stats))
    app.add_handler(CommandHandler("export_pending", export_pending))
    app.add_handler(CommandHandler("export_verified", export_verified))
    app.add_handler(CommandHandler("users", user_stats))
    app.add_handler(CommandHandler("userstock", user_stock))
    app.add_handler(CommandHandler("view2fa", view2fa))
    app.add_handler(CommandHandler("set2fa", set2fa))
    app.add_handler(CommandHandler("viewproxies", view_proxies))
    app.add_handler(CommandHandler("addproxy", add_proxy))
    app.add_handler(CommandHandler("removeproxy", remove_proxy))
    app.add_handler(CommandHandler("checkproxies", check_proxy_health))
    app.add_handler(CommandHandler("mystats", my_stats))
    app.add_handler(CommandHandler("leaderboard", leaderboard))
    app.add_handler(CommandHandler("leaderboard_daily", leaderboard_daily))
    app.add_handler(CommandHandler("leaderboard_all", leaderboard_all))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle))

    await app.run_polling()

if __name__ == "__main__":
    import nest_asyncio
    nest_asyncio.apply()

    asyncio.get_event_loop().run_until_complete(main())  


