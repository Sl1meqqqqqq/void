#!/usr/bin/env python3
"""
=============================================================================
VOID // TELEGRAM LICENSE BOT & AUTH SERVER
=============================================================================
Commands:
  /start               - Инициализация и привязка админа
  /key [ник]           - Создать ключ с привязкой к нику
  /keys                - Список всех выданных ключей и статусов
  /keycheck [ник/ключ] - Проверка последнего входа и детальная информация
  /ban [ник/ключ]      - Заблокировать ключ
  /unban [ник/ключ]    - Разблокировать ключ
=============================================================================
"""

import os
import sys
import json
import time
import random
import threading
from datetime import datetime
from urllib.parse import urlparse, parse_qs
from http.server import HTTPServer, BaseHTTPRequestHandler
import requests

TOKEN = "8419786227:AAF0XFEAmOx9fBZUaxQuW1aR0ucXRFk-Q7s"
BASE_URL = f"https://api.telegram.org/bot{TOKEN}"
SALT = "SECRET_YAW_VALENCE_AUTH_2026"
DB_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "keys_database.json")
CONFIG_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "bot_config.json")

# Database Lock
db_lock = threading.Lock()

def load_db():
    with db_lock:
        if not os.path.exists(DB_FILE):
            return {}
        try:
            with open(DB_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {}

def save_db(data):
    with db_lock:
        with open(DB_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=4, ensure_ascii=False)

def load_config():
    if not os.path.exists(CONFIG_FILE):
        return {"admin_ids": []}
    try:
        with open(CONFIG_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {"admin_ids": []}

def save_config(cfg):
    with open(CONFIG_FILE, "w", encoding="utf-8") as f:
        json.dump(cfg, f, indent=4)

config = load_config()

# Helper hash calculation
def generate_hash(text):
    h1 = 0x811C9DC5
    h2 = 0x27D4EB2F
    for ch in text:
        b = ord(ch)
        h1 = ((h1 ^ b) * 16777619) & 0xFFFFFFFF
        h2 = ((h2 ^ b) * 1540483477) & 0xFFFFFFFF
        rot_h1 = (((h1 << 5) & 0xFFFFFFFF) | (h1 >> 27))
        h1 = (rot_h1 ^ h2) & 0xFFFFFFFF
        rot_h2 = (((h2 << 7) & 0xFFFFFFFF) | (h2 >> 25))
        h2 = (rot_h2 ^ h1) & 0xFFFFFFFF
        h1 = (h1 + 0x9E3779B9) & 0xFFFFFFFF
        h2 = (h2 + 0x7F4A7C15) & 0xFFFFFFFF
    return f"{h1:08X}"

def generate_key_str():
    chars = "0123456789ABCDEF"
    nonce = "".join(random.choice(chars) for _ in range(8))
    sig = generate_hash(f"{nonce}:{SALT}")
    return f"SY-{nonce[:4]}-{nonce[4:8]}-{sig[:4]}-{sig[4:8]}"

def send_tg_message(chat_id, text, parse_mode="HTML"):
    try:
        requests.post(f"{BASE_URL}/sendMessage", json={
            "chat_id": chat_id,
            "text": text,
            "parse_mode": parse_mode
        }, timeout=10)
    except Exception as e:
        print(f"Error sending TG message: {e}")

def notify_admins(text):
    for admin_id in config.get("admin_ids", []):
        send_tg_message(admin_id, text)

# Pending state for step-by-step /key
pending_users = {}

# ---------------------------------------------------------------------------
# HTTP AUTH SERVER FOR NEVERLOSE LUA
# ---------------------------------------------------------------------------
class AuthHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        parsed = urlparse(self.path)
        if parsed.path == "/check":
            params = parse_qs(parsed.query)
            key = params.get("key", [""])[0].strip().upper()
            nl_user = params.get("user", ["Unknown"])[0].strip()

            db = load_db()
            record = db.get(key)

            if record and not record.get("banned", False):
                # Update last seen
                now_str = datetime.now().strftime("%d.%m.%Y %H:%M:%S")
                record["last_seen"] = now_str
                record["last_nl_user"] = nl_user
                db[key] = record
                save_db(db)

                # Notify Telegram admin
                owner = record.get("user", "Не указан")
                notify_admins(
                    f"🟢 <b>[VOID АКТИВАЦИЯ]</b>\n"
                    f"👤 <b>Владелец:</b> <code>{owner}</code>\n"
                    f"🎮 <b>Ник в Neverlose:</b> <code>{nl_user}</code>\n"
                    f"🔑 <b>Ключ:</b> <code>{key}</code>\n"
                    f"🕒 <b>Время:</b> <code>{now_str}</code>"
                )

                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps({
                    "valid": True,
                    "user": owner,
                    "msg": "Authenticated"
                }).encode("utf-8"))
            else:
                reason = "Banned" if (record and record.get("banned")) else "Invalid key"
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps({
                    "valid": False,
                    "error": reason
                }).encode("utf-8"))
        elif parsed.path == "/health":
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(b'{"status":"ok"}')
        else:
            self.send_response(404)
            self.end_headers()

    def log_message(self, format, *args):
        pass  # Quiet HTTP logs

def run_http_server():
    port = int(os.environ.get("PORT", 8080))
    server = HTTPServer(("0.0.0.0", port), AuthHandler)
    print(f"[*] Auth HTTP Server listening on port {port}...")
    server.serve_forever()

# ---------------------------------------------------------------------------
# TELEGRAM BOT LOGIC
# ---------------------------------------------------------------------------
def process_message(msg):
    chat_id = msg["chat"]["id"]
    text = msg.get("text", "").strip()
    if not text:
        return

    # Automatically register admin on first use
    if chat_id not in config.get("admin_ids", []):
        config.setdefault("admin_ids", []).append(chat_id)
        save_config(config)

    # Parse command cleanly
    parts = text.split()
    cmd = parts[0].lower() if parts else ""

    # Check if user was in pending state for /key
    if chat_id in pending_users:
        # If user typed another command instead, cancel pending state
        if text.startswith("/"):
            del pending_users[chat_id]
        else:
            target_username = text
            del pending_users[chat_id]
            create_and_send_key(chat_id, target_username)
            return

    if cmd == "/start" or cmd == "/help":
        send_tg_message(chat_id, (
            "⚡ <b>VOID // СИСТЕМА УПРАВЛЕНИЯ ЛИЦЕНЗИЯМИ</b> ⚡\n\n"
            "Доступные команды:\n"
            "🔑 <code>/key [ник]</code> — Сгенерировать ключ для пользователя\n"
            "📋 <code>/keys</code> — Список всех выданных ключей и статусы\n"
            "🔍 <code>/keycheck [ник/ключ]</code> — Проверка последнего захода в луа\n"
            "⛔ <code>/ban [ник/ключ]</code> — Отозвать / заблокировать ключ\n"
            "✅ <code>/unban [ник/ключ]</code> — Разблокировать ключ\n"
        ))
        return

    if cmd == "/keys":
        db = load_db()
        if not db:
            send_tg_message(chat_id, "📭 База ключей пока пуста. Создайте ключ через <code>/key [ник]</code>.")
            return

        lines = [f"📋 <b>Всего ключей в базе: {len(db)}</b>\n"]
        for i, (k, info) in enumerate(db.items(), 1):
            status = "🔴 ЗАБАНЕН" if info.get("banned") else "🟢 АКТИВЕН"
            last = info.get("last_seen") or "Ещё не заходил"
            user = info.get("user") or "Без ника"
            nl_user = info.get("last_nl_user")
            user_line = f"👤 {user}" if not nl_user else f"👤 {user} (NL: {nl_user})"
            lines.append(
                f"<b>{i}.</b> <code>{k}</code>\n"
                f"   {user_line}\n"
                f"   🕒 Посл. вход: <code>{last}</code>\n"
                f"   Статус: {status}\n"
            )
        send_tg_message(chat_id, "\n".join(lines))
        return

    if cmd == "/keycheck":
        sub_parts = text.split(maxsplit=1)
        if len(sub_parts) < 2:
            send_tg_message(chat_id, "⚠️ Использование: <code>/keycheck [ник или ключ]</code>")
            return
        query = sub_parts[1].strip()
        db = load_db()

        # Search by key or username
        found_key, found_info = None, None
        for k, v in db.items():
            if k.upper() == query.upper() or v.get("user", "").lower() == query.lower() or v.get("last_nl_user", "").lower() == query.lower():
                found_key = k
                found_info = v
                break

        if not found_key:
            send_tg_message(chat_id, f"❌ Ключ или пользователь <b>'{query}'</b> не найден в базе!")
            return

        status = "🔴 ЗАБЛОКИРОВАН (BANNED)" if found_info.get("banned") else "🟢 АКТИВЕН (ACTIVE)"
        created = found_info.get("created_at", "Неизвестно")
        last_seen = found_info.get("last_seen", "Ещё не запускал скрипт")
        nl_user = found_info.get("last_nl_user", "—")

        send_tg_message(chat_id, (
            f"🔍 <b>ИНФОРМАЦИЯ О КЛЮЧЕ:</b>\n\n"
            f"🔑 <b>Ключ:</b> <code>{found_key}</code>\n"
            f"👤 <b>Владелец:</b> <code>{found_info.get('user', '—')}</code>\n"
            f"🎮 <b>Ник в Neverlose:</b> <code>{nl_user}</code>\n"
            f"📅 <b>Дата создания:</b> <code>{created}</code>\n"
            f"🕒 <b>Последний вход с луа:</b> <code>{last_seen}</code>\n"
            f"⚡ <b>Статус:</b> {status}\n"
        ))
        return

    if cmd == "/key":
        sub_parts = text.split(maxsplit=1)
        if len(sub_parts) > 1:
            target_username = sub_parts[1].strip()
            create_and_send_key(chat_id, target_username)
        else:
            pending_users[chat_id] = True
            send_tg_message(chat_id, "✍️ <b>Введите никнейм пользователя</b>, для которого создаётся ключ:")
        return

    if cmd == "/ban":
        sub_parts = text.split(maxsplit=1)
        if len(sub_parts) < 2:
            send_tg_message(chat_id, "⚠️ Использование: <code>/ban [ник или ключ]</code>")
            return
        query = sub_parts[1].strip()
        db = load_db()
        target_k = None
        for k, v in db.items():
            if k.upper() == query.upper() or v.get("user", "").lower() == query.lower():
                target_k = k
                break

        if target_k:
            db[target_k]["banned"] = True
            save_db(db)
            send_tg_message(chat_id, f"⛔ Ключ <code>{target_k}</code> (Пользователь: <b>{db[target_k].get('user')}</b>) успешно <b>заблокирован</b>!")
        else:
            send_tg_message(chat_id, f"❌ Ключ или пользователь <b>'{query}'</b> не найден!")
        return

    if cmd == "/unban":
        sub_parts = text.split(maxsplit=1)
        if len(sub_parts) < 2:
            send_tg_message(chat_id, "⚠️ Использование: <code>/unban [ник или ключ]</code>")
            return
        query = sub_parts[1].strip()
        db = load_db()
        target_k = None
        for k, v in db.items():
            if k.upper() == query.upper() or v.get("user", "").lower() == query.lower():
                target_k = k
                break

        if target_k:
            db[target_k]["banned"] = False
            save_db(db)
            send_tg_message(chat_id, f"✅ Ключ <code>{target_k}</code> (Пользователь: <b>{db[target_k].get('user')}</b>) успешно <b>разблокирован</b>!")
        else:
            send_tg_message(chat_id, f"❌ Ключ или пользователь <b>'{query}'</b> не найден!")
        return

def create_and_send_key(chat_id, username):
    new_key = generate_key_str()
    now_str = datetime.now().strftime("%d.%m.%Y %H:%M:%S")
    db = load_db()
    db[new_key] = {
        "user": username,
        "created_at": now_str,
        "last_seen": None,
        "last_nl_user": None,
        "banned": False
    }
    save_db(db)

    send_tg_message(chat_id, (
        f"✅ <b>Новый ключ успешно создан!</b>\n\n"
        f"🔑 <b>Ключ:</b> <code>{new_key}</code>\n"
        f"👤 <b>Пользователь:</b> <code>{username}</code>\n"
        f"🕒 <b>Создан:</b> <code>{now_str}</code>\n\n"
        f"<i>(Нажмите на ключ, чтобы скопировать)</i>"
    ))

# ---------------------------------------------------------------------------
# LONG POLLING THREAD
# ---------------------------------------------------------------------------
def run_telegram_bot():
    print("[*] Telegram Bot Polling started...")
    last_update_id = 0
    while True:
        try:
            res = requests.get(f"{BASE_URL}/getUpdates", params={
                "offset": last_update_id + 1,
                "timeout": 25
            }, timeout=30).json()

            if res.get("ok"):
                for update in res.get("result", []):
                    last_update_id = update["update_id"]
                    if "message" in update:
                        process_message(update["message"])
        except Exception as e:
            time.sleep(3)

if __name__ == "__main__":
    print("=" * 60)
    print("      VOID // TELEGRAM KEY MANAGER & AUTH SERVER")
    print("=" * 60)

    # Start HTTP server thread for Neverlose Lua
    http_thread = threading.Thread(target=run_http_server, daemon=True)
    http_thread.start()

    # Start Telegram Poller (blocking in main thread)
    run_telegram_bot()
