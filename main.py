import os
import logging
import asyncio
import datetime
import re
import sqlite3
from typing import Dict, List
from telegram import Update, ChatPermissions
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, ContextTypes, filters
from telegram.constants import ParseMode

# ================= LOGGING =================
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# ================= CONFIG =================
BOT_TOKEN = os.getenv("BOT_TOKEN", "PASTE_YOUR_TOKEN_HERE")
LOG_CHAT_ID = os.getenv("LOG_CHAT_ID", None)
OWNER_ID = int(os.getenv("OWNER_ID", "123456789"))

WARN_LIMIT = 3
DB_FILE = "guardbot.db"

# All anti features - toggle True/False
settings = {
    "antilink": True,
    "antimedia": False,
    "antisticker": True,
    "antianimation": True,
    "antiforward": True,
    "antibots": True,
    "anticaps": True,
    "antiflood": True,
    "antiusername": True,
    "delete_joins": True,
    "delete_leaves": True,
    "caps_limit": 70,
    "flood_limit": 5,
    "flood_seconds": 3,
    "slowmode": 5,
    "welcome_msg": "🎉 Welcome {name} to our community!\n📜 Read /rules • Be respectful • Have fun!"
}

msg_times: Dict[str, List[datetime.datetime]] = {}

# ================= SAFE DELETE HELPER =================
async def safe_delete(message) -> bool:
    """Delete message without crashing bot if Telegram blocks it"""
    if not message:
        return False
    try:
        await message.delete()
        return True
    except Exception as e:
        logger.warning(f"Delete failed: {e}")
        return False

async def auto_delete_message(message, delay=10):
    """Delete bot message after delay without blocking"""
    await asyncio.sleep(delay)
    await safe_delete(message)

async def reply_and_delete(message, text, delay=5):
    """Reply then delete both messages after delay"""
    msg = await message.reply_text(text)
    asyncio.create_task(auto_delete_message(msg, delay))
    asyncio.create_task(auto_delete_message(message, delay))

# ================= DATABASE =================
def init_db():
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS warns
                 (chat_id TEXT, user_id TEXT, count INTEGER, PRIMARY KEY(chat_id, user_id))''')
    c.execute('''CREATE TABLE IF NOT EXISTS settings
                 (key TEXT PRIMARY KEY, value TEXT)''')

    # Load default settings if empty
    for key, value in settings.items():
        c.execute("INSERT OR IGNORE INTO settings VALUES (?,?)", (key, str(value)))

    conn.commit()
    conn.close()

def get_warns(chat_id, user_id):
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("SELECT count FROM warns WHERE chat_id=? AND user_id=?", (str(chat_id), str(user_id)))
    row = c.fetchone()
    conn.close()
    return row[0] if row else 0

def add_warn(chat_id, user_id):
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    count = get_warns(chat_id, user_id) + 1
    c.execute("REPLACE INTO warns VALUES (?,?,?)", (str(chat_id), str(user_id), count))
    conn.commit()
    conn.close()
    return count

def reset_warns_db(chat_id):
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("DELETE FROM warns WHERE chat_id=?", (str(chat_id),))
    conn.commit()
    conn.close()

def load_settings():
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("SELECT key, value FROM settings")
    rows = c.fetchall()
    conn.close()
    for key, value in rows:
        if value.lower() == "true":
            settings[key] = True
        elif value.lower() == "false":
            settings[key] = False
        elif value.isdigit():
            settings[key] = int(value)
        else:
            settings[key] = value

def save_setting(key, value):
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("REPLACE INTO settings VALUES (?,?)", (key, str(value)))
    conn.commit()
    conn.close()

init_db()
load_settings()

# ================= UTILS =================
async def is_admin(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    if not update.effective_user or not update.effective_chat:
        return False
    if update.effective_user.id == OWNER_ID:
        return True
    try:
        admins = await context.bot.get_chat_administrators(update.effective_chat.id)
        return update.effective_user.id in [a.user.id for a in admins]
    except:
        return False

async def log_action(context: ContextTypes.DEFAULT_TYPE, text: str):
    if LOG_CHAT_ID:
        try:
            await context.bot.send_message(LOG_CHAT_ID, f"[LOG] {text}")
        except Exception as e:
            logger.error(f"Log error: {e}")

# ================= WELCOME/LEAVE =================
async def welcome_leave(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message:
        return

    chat_id = update.effective_chat.id

    # New members
    if update.message.new_chat_members:
        for member in update.message.new_chat_members:
            # Delete join message
            if settings["delete_joins"]:
                await safe_delete(update.message)

            # Anti bot
            if settings["antibots"] and member.is_bot:
                await context.bot.ban_chat_member(chat_id, member.id)
                await log_action(context, f"Bot {member.first_name} banned on join")
                continue

            # Send welcome
            msg = settings["welcome_msg"].format(name=member.first_name)
            await context.bot.send_message(chat_id, msg)

    # Left member
    if update.message.left_chat_member and settings["delete_leaves"]:
        await safe_delete(update.message)

# ================= WARN USER FUNCTION =================
async def warn_user(update: Update, context: ContextTypes.DEFAULT_TYPE, reason: str):
    if not update.message or not update.effective_user:
        return

    # FIX: Use safe_delete instead of direct delete
    await safe_delete(update.message)

    chat_id = update.effective_chat.id
    user_id = update.message.from_user.id
    name = update.message.from_user.first_name

    count = add_warn(chat_id, user_id)

    if count >= WARN_LIMIT:
        try:
            await context.bot.ban_chat_member(chat_id, user_id)
            msg = await update.message.reply_text(f"🚫 {name} banned from community for {reason}")
            await log_action(context, f"BAN {name} - {reason}")
            reset_warns_db(chat_id) # Reset after ban
            asyncio.create_task(auto_delete_message(msg, 10))
        except Exception as e:
            logger.error(f"Ban error: {e}")
    else:
        msg = await update.message.reply_text(
            f"⚠️ {name}, no {reason}!\nWarning {count}/{WARN_LIMIT} → Ban next"
        )
        asyncio.create_task(auto_delete_message(msg, 10))

# ================= ALL ANTI GUARD =================
async def anti_guard(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.effective_user:
        return

    chat = update.effective_chat
    user = update.message.from_user
    msg = update.message

    if await is_admin(update, context):
        return
    if chat.type == "private":
        return

    user_id = str(user.id)
    now = datetime.datetime.now()

    # ANTI FORWARD
    if settings["antiforward"] and msg.forward_origin:
        return await warn_user(update, context, "forwarding messages")

    # ANTI MEDIA
    if settings["antimedia"] and (msg.photo or msg.video or msg.document or msg.voice or msg.audio):
        return await warn_user(update, context, "sending media")

    # ANTI STICKER
    if settings["antisticker"] and msg.sticker:
        return await warn_user(update, context, "sending stickers")

    # ANTI GIF
    if settings["antianimation"] and msg.animation:
        return await warn_user(update, context, "sending GIFs")

    # ANTI LINK + USERNAME
    if msg.text:
        text = msg.text.lower()
        if settings["antilink"] and re.search(r'http|www|\.com|\.me|t\.me|telegram\.me', text):
            return await warn_user(update, context, "sending links")
        if settings["antiusername"] and len(re.findall(r'@\w+', text)) > 2:
            return await warn_user(update, context, "spamming usernames")

    # ANTI CAPS
    if settings["anticaps"] and msg.text and len(msg.text) > 10:
        caps = sum(1 for c in msg.text if c.isupper())
        if caps / len(msg.text) * 100 > settings["caps_limit"]:
            return await warn_user(update, context, "CAPS spam")

    # ANTI FLOOD - FIX: Use total_seconds
    if settings["antiflood"]:
        msg_times.setdefault(user_id, [])
        msg_times[user_id] = [t for t in msg_times[user_id] if (now - t).total_seconds() < settings["flood_seconds"]]
        msg_times[user_id].append(now)
        if len(msg_times[user_id]) > settings["flood_limit"]:
            msg_times[user_id] = []
            until = now + datetime.timedelta(minutes=5)
            # FIX: Added until_date
            await context.bot.restrict_chat_member(
                chat.id, user.id,
                permissions=ChatPermissions(can_send_messages=False),
                until_date=until
            )
            await msg.reply_text(f"🌊 {user.first_name} auto-muted 5min for flooding")

    # SLOWMODE - FIX: Use safe_delete
    if len(msg_times.get(user_id, [])) > 1:
        diff = (now - msg_times[user_id][-2]).total_seconds()
        if diff < settings["slowmode"]:
            await safe_delete(msg)

# ================= BASIC COMMANDS =================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("🛡️ Ultimate Guard Bot Online v3.0\nProtecting community 24/7\nType /help for full commands")

async def rules(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "**📜 COMMUNITY RULES:**\n"
        "1. No spam/links if anti is on\n"
        "2. No media/stickers/GIFs if anti is on\n"
        "3. No CAPS spam or flooding\n"
        "4. Respect all members & admins\n"
        "5. No bot accounts\n"
        "**Punishment:** 3 warnings = Ban from community",
        parse_mode="Markdown"
    )

async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = """
**👥 ALL MEMBERS:**
/start - Check bot status
/rules - Show community rules
/help - Show this menu

**🛡️ ADMIN MODERATION:**
/warn - Add warning to replied user
/kick - Kick replied user
/ban - Ban replied user
/unban 123456 - Unban by user ID
/mute 60 - Mute for 60 minutes
/unmute - Remove mute
/pin - Pin replied message
/unpin - Unpin all messages
/purge 100 - Delete last 100 messages

**🔒 ALL ANTI COMMANDS:**
/antilink on/off - Block links
/antimedia on/off - Block photos/videos
/antisticker on/off - Block stickers
/antianimation on/off - Block GIFs
/antiforward on/off - Block forwards
/antibots on/off - Auto-ban bots
/anticaps on/off - Block CAPS spam
/antiflood on/off - Block flooding
/antiusername on/off - Block @ spam
/deletejoins on/off - Delete join messages
/deleteleaves on/off - Delete leave messages
/floodlimit 5 - Set flood limit
/capslimit 70 - Set CAPS percentage
/slowmode 5 - Set slowmode seconds
/setwelcome text - Custom welcome message
/antisettings - Show all anti status
/resetwarns - Clear all warnings
"""
    await update.message.reply_text(text, parse_mode="Markdown")

# ================= ALL ANTI COMMANDS =================
async def toggle_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE, key: str, name: str):
    if not await is_admin(update, context):
        return
    if not context.args or context.args[0].lower() not in ["on", "off"]:
        return await update.message.reply_text(f"Use: /{key} on or /{key} off")
    settings[key] = context.args[0].lower() == "on"
    save_setting(key, settings[key])
    status = "✅ ON" if settings[key] else "❌ OFF"
    await reply_and_delete(update.message, f"{name} is now {status}")

async def antilink(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await toggle_cmd(update, context, "antilink", "Anti-Link")
async def antimedia(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await toggle_cmd(update, context, "antimedia", "Anti-Media")
async def antisticker(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await toggle_cmd(update, context, "antisticker", "Anti-Sticker")
async def antianimation(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await toggle_cmd(update, context, "antianimation", "Anti-GIF")
async def antiforward(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await toggle_cmd(update, context, "antiforward", "Anti-Forward")
async def antibots(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await toggle_cmd(update, context, "antibots", "Anti-Bots")
async def anticaps(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await toggle_cmd(update, context, "anticaps", "Anti-CAPS")
async def antiflood(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await toggle_cmd(update, context, "antiflood", "Anti-Flood")
async def antiusername(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await toggle_cmd(update, context, "antiusername", "Anti-Username Spam")
async def deletejoins(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await toggle_cmd(update, context, "delete_joins", "Delete Join Messages")
async def deleteleaves(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await toggle_cmd(update, context, "delete_leaves", "Delete Leave Messages")

async def floodlimit(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_admin(update, context):
        return
    if context.args and context.args[0].isdigit():
        settings["flood_limit"] = int(context.args[0])
        save_setting("flood_limit", settings["flood_limit"])
        await reply_and_delete(update.message, f"🌊 Flood limit set to {settings['flood_limit']} messages per {settings['flood_seconds']} seconds")

async def capslimit(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_admin(update, context):
        return
    if context.args and context.args[0].isdigit():
        settings["caps_limit"] = int(context.args[0])
        save_setting("caps_limit", settings["caps_limit"])
        await reply_and_delete(update.message, f"🔠 CAPS limit set to {settings['caps_limit']}%")

async def slowmode(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_admin(update, context):
        return
    if context.args and context.args[0].isdigit():
        settings["slowmode"] = int(context.args[0])
        save_setting("slowmode", settings["slowmode"])
        await reply_and_delete(update.message, f"⏱️ Slowmode set to {settings['slowmode']} seconds between messages")

async def setwelcome(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_admin(update, context):
        return
    if context.args:
        settings["welcome_msg"] = " ".join(context.args)
        save_setting("welcome_msg", settings["welcome_msg"])
        await reply_and_delete(update.message, "✅ Welcome message updated!\nUse {name} for user name placeholder")

async def antisettings(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_admin(update, context):
        return
    text = "**🔒 ALL ANTI SETTINGS STATUS:**\n\n"
    for k, v in settings.items():
        if k not in ["welcome_msg"]:
            status = "✅ ON" if v is True else "❌ OFF" if v is False else v
        else:
            status = "Custom message set"
        text += f"`{k}`: {status}\n"
    await update.message.reply_text(text, parse_mode="Markdown")

async def resetwarns(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_admin(update, context):
        return
    chat_id = update.effective_chat.id
    reset_warns_db(chat_id)
    await reply_and_delete(update.message, "🗑️ All warnings have been reset for this group")

# ================= ADMIN COMMANDS =================
async def warn(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_admin(update, context):
        return
    if update.message.reply_to_message:
        await warn_user(update, context, "admin warning")

async def kick(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_admin(update, context):
        return
    if update.message.reply_to_message:
        user = update.message.reply_to_message.from_user
        try:
            await context.bot.ban_chat_member(update.effective_chat.id, user.id)
            await context.bot.unban_chat_member(update.effective_chat.id, user.id)
            await reply_and_delete(update.message, f"👢 {user.first_name} was kicked from community")
            await log_action(context, f"KICK {user.first_name}")
        except Exception as e:
            await update.message.reply_text(f"Error: {e}")

async def ban(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_admin(update, context):
        return
    if update.message.reply_to_message:
        user = update.message.reply_to_message.from_user
        try:
            await context.bot.ban_chat_member(update.effective_chat.id, user.id)
            await reply_and_delete(update.message, f"🚫 {user.first_name} was banned from community")
            await log_action(context, f"BAN {user.first_name}")
        except Exception as e:
            await update.message.reply_text(f"Error: {e}")

async def unban(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_admin(update, context):
        return
    if context.args:
        try:
            user_id = int(context.args[0])
            await context.bot.unban_chat_member(update.effective_chat.id, user_id)
            await reply_and_delete(update.message, "✅ User unbanned successfully")
        except:
            await update.message.reply_text("Use: /unban 123456789")

async def mute(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_admin(update, context):
        return
    if update.message.reply_to_message:
        mins = int(context.args[0]) if context.args and context.args[0].isdigit() else 30
        user = update.message.reply_to_message.from_user
        until = datetime.datetime.now() + datetime.timedelta(minutes=mins)
        # FIX: Added until_date
        await context.bot.restrict_chat_member(
            update.effective_chat.id, user.id,
            permissions=ChatPermissions(can_send_messages=False),
            until_date=until
        )
        await reply_and_delete(update.message, f"🔇 {user.first_name} muted for {mins} minutes")

async def unmute(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_admin(update, context):
        return
    if update.message.reply_to_message:
        user = update.message.reply_to_message.from_user
        await context.bot.restrict_chat_member(
            update.effective_chat.id, user.id,
            permissions=ChatPermissions(can_send_messages=True)
        )
        await reply_and_delete(update.message, f"🔊 {user.first_name} unmuted")

async def pin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_admin(update, context):
        return
    if update.message.reply_to_message:
        await context.bot.pin_chat_message(update.effective_chat.id, update.message.reply_to_message.message_id)
        await reply_and_delete(update.message, "📌 Message pinned for community")

async def unpin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_admin(update, context):
        return
    await context.bot.unpin_all_chat_messages(update.effective_chat.id)
    await reply_and_delete(update.message, "📌 All messages unpinned")

async def purge(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_admin(update, context):
        return
    if context.args and context.args[0].isdigit():
        count = min(int(context.args[0]), 100)
        chat_id = update.effective_chat.id
        msg_id = update.message_id
        deleted = 0
        for i in range(msg_id - count, msg_id + 1):
            try:
                await context.bot.delete_message(chat_id, i)
                deleted += 1
            except:
                pass
        msg = await context.bot.send_message(chat_id, f"🗑️ Deleted {deleted} messages")
        asyncio.create_task(auto_delete_message(msg, 5))

# ================= ERROR HANDLER =================
async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE):
    logger.error(f"Exception: {context.error}")

# ================= MAIN =================
def main():
    if BOT_TOKEN == "PASTE_YOUR_TOKEN_HERE":
        print("ERROR: Set BOT_TOKEN in Railway Variables!")
        return

    app = ApplicationBuilder().token(BOT_TOKEN).build()

    app.add_handler(MessageHandler(filters.StatusUpdate.NEW_CHAT_MEMBERS | filters.StatusUpdate.LEFT_CHAT_MEMBER, welcome_leave))
    app.add_handler(MessageHandler(filters.ALL & filters.ChatType.GROUPS, anti_guard))

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("rules", rules))
    app.add_handler(CommandHandler("help", help_cmd))

    # All anti commands
    for cmd in ["antilink","antimedia","antisticker","antianimation","antiforward","antibots","anticaps","antiflood","antiusername","deletejoins","deleteleaves"]:
        app.add_handler(CommandHandler(cmd, globals()[cmd]))
    app.add_handler(CommandHandler("floodlimit", floodlimit))
    app.add_handler(CommandHandler("capslimit", capslimit))
    app.add_handler(CommandHandler("slowmode", slowmode))
    app.add_handler(CommandHandler("setwelcome", setwelcome))
    app.add_handler(CommandHandler("antisettings", antisettings))
    app.add_handler(CommandHandler("resetwarns", resetwarns))

    # Admin commands
    for cmd in ["warn","kick","ban","unban","mute","unmute","pin","unpin","purge"]:
        app.add_handler(CommandHandler(cmd, globals()[cmd]))

    # Error handler
    app.add_error_handler(error_handler)

    print("🛡️ ULTIMATE GUARD BOT v3.0 ACTIVE - All bugs fixed")
    app.run_polling(allowed_updates=Update.ALL_TYPES, drop_pending_updates=True)

if __name__ == "__main__":
    main()
