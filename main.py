from telegram import Update, ChatPermissions
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, ContextTypes, filters
import datetime, json, os, re

# ================= CONFIG =================
import os
async def safe_delete(message):
    try:
        await message.delete()
        return True
    except:
        return False
TOKEN = os.environ.get("TOKEN")
WARN_LIMIT = 3
LOG_CHAT_ID = None # Set to your admin log group ID like -1001234567890

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
warns = {}
msg_times = {}

DATA_FILE = "settings.json"
WARNS_FILE = "warns.json"

def load_data():
    global warns, settings
    if os.path.exists(WARNS_FILE):
        with open(WARNS_FILE, 'r') as f:
            warns = json.load(f)
    if os.path.exists(DATA_FILE):
        with open(DATA_FILE, 'r') as f:
            settings.update(json.load(f))

def save_data():
    with open(WARNS_FILE, 'w') as f:
        json.dump(warns, f)
    with open(DATA_FILE, 'w') as f:
        json.dump(settings, f)

load_data()

# ================= UTILS =================
async def is_admin(update, context):
    if not update.message:
        return False
    try:
        admins = await context.bot.get_chat_administrators(update.effective_chat.id)
        return update.message.from_user.id in [a.user.id for a in admins]
    except:
        return False

async def log_action(context, text):
    if LOG_CHAT_ID:
        try:
            await context.bot.send_message(LOG_CHAT_ID, f"[LOG] {text}")
        except:
            pass

# ================= WELCOME/LEAVE =================
async def welcome_leave(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    if update.message.new_chat_members:
        for member in update.message.new_chat_members:
            if settings["delete_joins"]:
                await update.message.delete()
            if settings["antibots"] and member.is_bot:
                await context.bot.ban_chat_member(chat_id, member.id)
                await log_action(context, f"Bot {member.first_name} banned on join")
                continue
            msg = settings["welcome_msg"].format(name=member.first_name)
            await context.bot.send_message(chat_id, msg)

    if update.message.left_chat_member and settings["delete_leaves"]:
        await safe_delete(update.message)

# ================= ALL ANTI GUARD =================
async def anti_guard(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message:
        return
    chat = update.effective_chat
    user = update.message.from_user
    msg = update.message
    if await is_admin(update, context):
        return

    chat_id = str(chat.id)
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

    # ANTI FLOOD
    if settings["antiflood"]:
        msg_times.setdefault(user_id, [])
        msg_times[user_id] = [t for t in msg_times[user_id] if (now - t).seconds < settings["flood_seconds"]]
        msg_times[user_id].append(now)
        if len(msg_times[user_id]) > settings["flood_limit"]:
            msg_times[user_id] = []
            until = now + datetime.timedelta(minutes=5)
            await context.bot.restrict_chat_member(chat.id, user.id, ChatPermissions(can_send_messages=False), until)
            await msg.reply_text(f"🌊 {user.first_name} auto-muted 5min for flooding")

    # SLOWMODE
    if len(msg_times.get(user_id, [])) > 1:
        diff = (now - msg_times[user_id][-2]).total_seconds()
        if diff < settings["slowmode"]:
            await msg.delete()

async def warn_user(update, context, reason):
    await update.message.delete()
    chat_id = str(update.effective_chat.id)
    user_id = str(update.message.from_user.id)
    name = update.message.from_user.first_name

    warns.setdefault(chat_id, {})
    warns[chat_id][user_id] = warns[chat_id].get(user_id, 0) + 1
    count = warns[chat_id][user_id]
    save_data()

    if count >= WARN_LIMIT:
        await context.bot.ban_chat_member(update.effective_chat.id, user_id)
        await update.message.reply_text(f"🚫 {name} banned from community for {reason}")
        await log_action(context, f"BAN {name} - {reason}")
        warns[chat_id][user_id] = 0
    else:
        await update.message.reply_text(f"⚠️ {name}, no {reason}!\nWarning {count}/{WARN_LIMIT} → Ban next", delete_after=10)
    save_data()

# ================= BASIC COMMANDS =================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("🛡️ Ultimate Guard Bot Online\nProtecting community 24/7\nType /help for full commands")

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
async def toggle_cmd(update, context, key, name):
    if not await is_admin(update, context):
        return
    if not context.args or context.args[0].lower() not in ["on", "off"]:
        return await update.message.reply_text(f"Use: /{key} on or /{key} off")
    settings[key] = context.args[0].lower() == "on"
    save_data()
    status = "✅ ON" if settings[key] else "❌ OFF"
    await update.message.reply_text(f"{name} is now {status}")

async def antilink(update, context):
    await toggle_cmd(update, context, "antilink", "Anti-Link")
async def antimedia(update, context):
    await toggle_cmd(update, context, "antimedia", "Anti-Media")
async def antisticker(update, context):
    await toggle_cmd(update, context, "antisticker", "Anti-Sticker")
async def antianimation(update, context):
    await toggle_cmd(update, context, "antianimation", "Anti-GIF")
async def antiforward(update, context):
    await toggle_cmd(update, context, "antiforward", "Anti-Forward")
async def antibots(update, context):
    await toggle_cmd(update, context, "antibots", "Anti-Bots")
async def anticaps(update, context):
    await toggle_cmd(update, context, "anticaps", "Anti-CAPS")
async def antiflood(update, context):
    await toggle_cmd(update, context, "antiflood", "Anti-Flood")
async def antiusername(update, context):
    await toggle_cmd(update, context, "antiusername", "Anti-Username Spam")
async def deletejoins(update, context):
    await toggle_cmd(update, context, "delete_joins", "Delete Join Messages")
async def deleteleaves(update, context):
    await toggle_cmd(update, context, "delete_leaves", "Delete Leave Messages")

async def floodlimit(update, context):
    if not await is_admin(update, context):
        return
    if context.args and context.args[0].isdigit():
        settings["flood_limit"] = int(context.args[0])
        save_data()
        await update.message.reply_text(f"🌊 Flood limit set to {settings['flood_limit']} messages per {settings['flood_seconds']} seconds")

async def capslimit(update, context):
    if not await is_admin(update, context):
        return
    if context.args and context.args[0].isdigit():
        settings["caps_limit"] = int(context.args[0])
        save_data()
        await update.message.reply_text(f"🔠 CAPS limit set to {settings['caps_limit']}%")

async def slowmode(update, context):
    if not await is_admin(update, context):
        return
    if context.args and context.args[0].isdigit():
        settings["slowmode"] = int(context.args[0])
        save_data()
        await update.message.reply_text(f"⏱️ Slowmode set to {settings['slowmode']} seconds between messages")

async def setwelcome(update, context):
    if not await is_admin(update, context):
        return
    if context.args:
        settings["welcome_msg"] = " ".join(context.args)
        save_data()
        await update.message.reply_text("✅ Welcome message updated!\nUse {name} for user name placeholder")

async def antisettings(update, context):
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

async def resetwarns(update, context):
    if not await is_admin(update, context):
        return
    chat_id = str(update.effective_chat.id)
    warns[chat_id] = {}
    save_data()
    await update.message.reply_text("🗑️ All warnings have been reset for this group")

# ================= ADMIN COMMANDS =================
async def warn(update, context):
    if not await is_admin(update, context):
        return
    if update.message.reply_to_message:
        await warn_user(update, context, "admin warning")

async def kick(update, context):
    if not await is_admin(update, context):
        return
    if update.message.reply_to_message:
        user = update.message.reply_to_message.from_user
        await context.bot.ban_chat_member(update.effective_chat.id, user.id)
        await context.bot.unban_chat_member(update.effective_chat.id, user.id)
        await update.message.reply_text(f"👢 {user.first_name} was kicked from community")
        await log_action(context, f"KICK {user.first_name}")

async def ban(update, context):
    if not await is_admin(update, context):
        return
    if update.message.reply_to_message:
        user = update.message.reply_to_message.from_user
        await context.bot.ban_chat_member(update.effective_chat.id, user.id)
        await update.message.reply_text(f"🚫 {user.first_name} was banned from community")
        await log_action(context, f"BAN {user.first_name}")

async def unban(update, context):
    if not await is_admin(update, context):
        return
    if context.args:
        try:
            user_id = int(context.args[0])
            await context.bot.unban_chat_member(update.effective_chat.id, user_id)
            await update.message.reply_text("✅ User unbanned successfully")
        except:
            await update.message.reply_text("Use: /unban 123456789")

async def mute(update, context):
    if not await is_admin(update, context):
        return
    if update.message.reply_to_message:
        mins = int(context.args[0]) if context.args and context.args[0].isdigit() else 30
        user = update.message.reply_to_message.from_user
        until = datetime.datetime.now() + datetime.timedelta(minutes=mins)
        await context.bot.restrict_chat_member(
            update.effective_chat.id, user.id,
            permissions=ChatPermissions(can_send_messages=False),
            until_date=until
        )
        await update.message.reply_text(f"🔇 {user.first_name} muted for {mins} minutes")

async def unmute(update, context):
    if not await is_admin(update, context):
        return
    if update.message.reply_to_message:
        user = update.message.reply_to_message.from_user
        await context.bot.restrict_chat_member(
            update.effective_chat.id, user.id,
            permissions=ChatPermissions(can_send_messages=True)
        )
        await update.message.reply_text(f"🔊 {user.first_name} unmuted")

async def pin(update, context):
    if not await is_admin(update, context):
        return
    if update.message.reply_to_message:
        await context.bot.pin_chat_message(update.effective_chat.id, update.message.reply_to_message.message_id)
        await update.message.reply_text("📌 Message pinned for community")

async def unpin(update, context):
    if not await is_admin(update, context):
        return
    await context.bot.unpin_all_chat_messages(update.effective_chat.id)
    await update.message.reply_text("📌 All messages unpinned")

async def purge(update, context):
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
        await context.bot.send_message(chat_id, f"🗑️ Deleted {deleted} messages", delete_after=5)

# ================= MAIN =================
def main():
    app = ApplicationBuilder().token(TOKEN).build()

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

    print("🛡️ ULTIMATE GUARD BOT ACTIVE - Full Code Loaded")
    app.run_polling()

if __name__ == "__main__":
    main()
