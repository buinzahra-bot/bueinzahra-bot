# main.py
import asyncio
import json
import os
import random
from datetime import datetime, timedelta

from telegram import (
    __version__ as TG_VER,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Update,
)
from telegram.ext import (
    ApplicationBuilder,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

# ---------- تنظیمات ----------
from config import BOT_TOKEN, ADMIN_ID, DATA_FOLDER, SCORE_FILE

# پارامترها
TURN_TIMEOUT = 90  # ثانیه برای پاسخ (میتونی تغییر بدی)

# ---------- load questions ----------
def load_questions(filename):
    path = os.path.join(DATA_FOLDER, filename)
    if not os.path.exists(path):
        return []
    with open(path, "r", encoding="utf-8") as f:
        lines = [l.strip() for l in f.readlines() if l.strip()]
    return lines


# ---------- state ----------
# state structure saved in memory + file:
# games: {chat_id: {players: [user_id...], idx: int (current index into players),
#    current_question: str, current_type: str, change_count: {user_id: int}, awaiting_response: bool}}
STATE_FILE = "state.json"
state = {"games": {}, "scores": {}}


def save_state():
    with open(SCORE_FILE, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)


def load_state():
    global state
    if os.path.exists(SCORE_FILE):
        try:
            with open(SCORE_FILE, "r", encoding="utf-8") as f:
                state = json.load(f)
        except:
            state = {"games": {}, "scores": {}}
    else:
        state = {"games": {}, "scores": {}}


# ---------- helpers ----------
def is_admin(user_id):
    try:
        return int(user_id) == int(ADMIN_ID)
    except:
        return False


def get_player_mention(user):
    if user.username:
        return f"@{user.username}"
    return f"{user.first_name}"


def init_game(chat_id):
    if str(chat_id) not in state["games"]:
        state["games"][str(chat_id)] = {
            "players": [],
            "idx": 0,
            "awaiting": False,
            "current_question": "",
            "current_type": "",
            "change_count": {},
            "started": False,
        }


def next_player(chat_id):
    g = state["games"][str(chat_id)]
    if not g["players"]:
        return None
    g["idx"] = (g["idx"] + 1) % len(g["players"])
    return g["players"][g["idx"]]


def current_player(chat_id):
    g = state["games"][str(chat_id)]
    if not g["players"]:
        return None
    return g["players"][g["idx"]]


def add_score(user_id, amount=1):
    uid = str(user_id)
    if uid not in state["scores"]:
        state["scores"][uid] = {"score": 0}
    state["scores"][uid]["score"] += amount
    save_state()


def get_leaderboard(limit=10):
    items = []
    for uid, info in state["scores"].items():
        items.append((uid, info.get("score", 0)))
    items.sort(key=lambda x: x[1], reverse=True)
    return items[:limit]


# ---------- load question lists ----------
def get_random_question(qtype):
    # qtype: 'truth_boy', 'truth_girl', 'dare_boy', 'dare_girl'
    files = {
        "truth_boy": "truth_boys.txt",
        "truth_girl": "truth_girls.txt",
        "dare_boy": "dare_boys.txt",
        "dare_girl": "dare_girls.txt",
    }
    fname = files.get(qtype)
    if not fname:
        return None
    qs = load_questions(fname)
    if not qs:
        return "سوال نداریم. ادمین باید فایل سوال‌ها رو پر کنه."
    return random.choice(qs)


# ---------- Handlers ----------
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "سلام! من ربات بازی جرأت یا حقیقت بوئین زهرا هستم.\n"
        "دستورها: /join /leave /startgame /stopgame /remove @username /leaderboard /myid"
    )


async def myid(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    await update.message.reply_text(f"آیدی شما: {user.id}")


async def join(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    user = update.effective_user
    init_game(chat_id)
    g = state["games"][str(chat_id)]
    uid = user.id
    if uid in g["players"]:
        await update.message.reply_text("شما قبلاً عضو بازی شده‌اید.")
        return
    g["players"].append(uid)
    g["change_count"][str(uid)] = 0
    save_state()
    await update.message.reply_text(f"{get_player_mention(user)} به بازی اضافه شد.")


async def leave(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    user = update.effective_user
    init_game(chat_id)
    g = state["games"][str(chat_id)]
    uid = user.id
    if uid not in g["players"]:
        await update.message.reply_text("شما در لیست بازی نیستید.")
        return
    g["players"].remove(uid)
    g["change_count"].pop(str(uid), None)
    save_state()
    await update.message.reply_text(f"{get_player_mention(user)} از بازی خارج شد.")


async def startgame(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    chat_id = update.effective_chat.id
    if not is_admin(user.id):
        await update.message.reply_text("فقط ادمین می‌تواند بازی را شروع کند.")
        return
    init_game(chat_id)
    g = state["games"][str(chat_id)]
    if not g["players"]:
        await update.message.reply_text("هیچ بازیکنی نیست. از /join استفاده کنید.")
        return
    g["started"] = True
    g["idx"] = -1  # so first next_player() sets idx to 0
    save_state()
    await update.message.reply_text("بازی شروع شد!")
    await do_next_turn(update, context)


async def stopgame(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    chat_id = update.effective_chat.id
    if not is_admin(user.id):
        await update.message.reply_text("فقط ادمین می‌تواند بازی را متوقف کند.")
        return
    init_game(chat_id)
    g = state["games"][str(chat_id)]
    g["started"] = False
    save_state()
    await update.message.reply_text("بازی متوقف شد.")


async def remove_player(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if not is_admin(user.id):
        await update.message.reply_text("فقط ادمین می‌تواند بازیکن را حذف کند.")
        return
    chat_id = update.effective_chat.id
    init_game(chat_id)
    g = state["games"][str(chat_id)]
    if not context.args:
        await update.message.reply_text("مثال: /remove @username")
        return
    username = context.args[0].lstrip("@")
    # find user id in players by username not always possible; just remove by mention match in chat members?
    # We'll remove by username from chat members list if found
    members = []
    # try to find user in chat by username
    try:
        chat = await context.bot.get_chat(chat_id)
        for member in await chat.get_administrators():
            pass
    except:
        pass
    # fallback: remove by scanning scores keys (not perfect). better ask admin to use reply to target with /kick
    # Simplest: support /remove user_id
    try:
        target_id = int(username)
        if target_id in g["players"]:
            g["players"].remove(target_id)
            g["change_count"].pop(str(target_id), None)
            save_state()
            await update.message.reply_text(f"کاربر {target_id} از بازی حذف شد.")
            return
    except:
        pass
    await update.message.reply_text("لطفا با آیدی عددی حذف کنید، مثال: /remove 12345678")


async def leaderboard(update: Update, context: ContextTypes.DEFAULT_TYPE):
    items = get_leaderboard(10)
    if not items:
        await update.message.reply_text("هیچ امتیازی ثبت نشده.")
        return
    text = "🏆 جدول امتیازات\n"
    i = 1
    for uid, sc in items:
        try:
            user = await context.bot.get_chat_member(update.effective_chat.id, int(uid))
            mention = user.user.username and ("@" + user.user.username) or user.user.first_name
        except:
            mention = f"{uid}"
        text += f"{i}. {mention} — {sc} امتیاز\n"
        i += 1
    await update.message.reply_text(text)


# ---------- turn flow ----------
async def do_next_turn(update_or_message, context: ContextTypes.DEFAULT_TYPE):
    # update_or_message can be Update or Message context - but we will use context to send messages
    chat_id = update_or_message.effective_chat.id
    g = state["games"][str(chat_id)]
    if not g["players"]:
        await context.bot.send_message(chat_id=chat_id, text="بازیکنی نداریم، بازی متوقف می‌شود.")
        g["started"] = False
        save_state()
        return
    # set next player
    next_pid = next_player(chat_id)
    save_state()
    # reset counters for that player
    g["change_count"][str(next_pid)] = 0
    g["awaiting"] = True
    # ask player to choose truth/dare
    try:
        user_obj = await context.bot.get_chat_member(chat_id, next_pid)
        mention = user_obj.user.username and ("@" + user_obj.user.username) or user_obj.user.first_name
    except:
        mention = str(next_pid)
    kb = InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton("🔵 حقیقت", callback_data=f"choose|truth"),
                InlineKeyboardButton("🔴 جرأت", callback_data=f"choose|dare"),
            ]
        ]
    )
    await context.bot.send_message(
        chat_id=chat_id,
        text=f"👤 نوبت: {mention}\nنوع سوال: انتخاب کن — حقیقت یا جرأت؟\n(فقط خودِ {mention} می‌تونه انتخاب کنه)",
        reply_markup=kb,
    )

    # start timeout watcher
    async def timeout_wait():
        await asyncio.sleep(TURN_TIMEOUT)
        # if still awaiting, count as no-response and move on
        load_state()
        g2 = state["games"].get(str(chat_id))
        if g2 and g2.get("awaiting"):
            g2["awaiting"] = False
            save_state()
            await context.bot.send_message(chat_id=chat_id, text=f"⏱️ زمان پاسخ به پایان رسید. نوبت به نفر بعدی می‌رود.")
            await do_next_turn(update_or_message, context)

    asyncio.create_task(timeout_wait())


async def callback_choose(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data  # "choose|truth" or "choose|dare" or others
    chat_id = query.message.chat.id
    user = query.from_user
    init_game(chat_id)
    g = state["games"][str(chat_id)]
    cur = current_player(chat_id)
    if cur is None or user.id != cur:
        await query.message.reply_text("❌ نوبت شما نیست، لطفاً صبر کنید.")
        return
    # decide question type based on player gender? we will ask player: if user chooses truth & user is male/female unknown -> ask to pick boy/girl
    typ = None
    if data.endswith("truth"):
        # ask which gender bank to use
        kb = InlineKeyboardMarkup(
            [
                [
                    InlineKeyboardButton("برای پسر", callback_data="set|truth_boy"),
                    InlineKeyboardButton("برای دختر", callback_data="set|truth_girl"),
                ]
            ]
        )
        await query.message.reply_text("کدوم دسته؟", reply_markup=kb)
        return
    elif data.endswith("dare"):
        kb = InlineKeyboardMarkup(
            [
                [
                    InlineKeyboardButton("برای پسر", callback_data="set|dare_boy"),
                    InlineKeyboardButton("برای دختر", callback_data="set|dare_girl"),
                ]
            ]
        )
        await query.message.reply_text("کدوم دسته؟", reply_markup=kb)
        return


async def callback_set_category(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data  # set|truth_boy
    _, qtype = data.split("|")
    chat_id = query.message.chat.id
    user = query.from_user
    init_game(chat_id)
    g = state["games"][str(chat_id)]
    cur = current_player(chat_id)
    if cur is None or user.id != cur:
        await query.message.reply_text("❌ نوبت شما نیست.")
        return
    # pick question
    q = get_random_question(qtype)
    g["current_question"] = q
    g["current_type"] = qtype
    g["awaiting"] = True
    save_state()
    kb = InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton("✅ پاسخ دادم", callback_data="resp|done"),
                InlineKeyboardButton("🔄 تغییر سوال (شانسی)", callback_data="resp|change"),
            ]
        ]
    )
    mention = user.username and ("@" + user.username) or user.first_name
    await query.message.reply_text(
        f"👤 نوبت: {mention}\nنوع سوال: {qtype}\n📝 سوال: {q}\n⏳ {TURN_TIMEOUT} ثانیه فرصت داری\n", reply_markup=kb
    )


async def callback_response(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data  # resp|done or resp|change
    chat_id = query.message.chat.id
    user = query.from_user
    init_game(chat_id)
    g = state["games"][str(chat_id)]
    cur = current_player(chat_id)
    if cur is None or user.id != cur:
        await query.message.reply_text("❌ نوبت شما نیست.")
        return
    if data.endswith("done"):
        # mark score +1
        add_score(user.id, 1)
        g["awaiting"] = False
        save_state()
        await query.message.reply_text("✅ امتیاز ثبت شد. نوبت نفر بعدی...")
        await do_next_turn(update, context)
        return
    elif data.endswith("change"):
        # allow change up to 2 times
        cnt = g["change_count"].get(str(user.id), 0)
        if cnt >= 2:
            await query.message.reply_text("⚠️ شما دیگر نمی‌توانید سوال را تغییر دهید.")
            return
        # pick another random question of same type
        qtype = g["current_type"]
        q = get_random_question(qtype)
        g["current_question"] = q
        g["change_count"][str(user.id)] = cnt + 1
        save_state()
        kb = InlineKeyboardMarkup(
            [
                [
                    InlineKeyboardButton("✅ پاسخ دادم", callback_data="resp|done"),
                    InlineKeyboardButton("🔄 تغییر سوال (شانسی)", callback_data="resp|change"),
                ]
            ]
        )
        await query.message.reply_text(
            f"سوال جدید:\n📝 {q}\n(تعداد تغییر باقی‌مانده: {2 - g['change_count'][str(user.id)]})",
            reply_markup=kb,
        )
        return


# ---------- main ----------
def ensure_data_folder():
    if not os.path.exists(DATA_FOLDER):
        os.makedirs(DATA_FOLDER)


async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "/join — وارد بازی شو\n"
        "/leave — از بازی خارج شو\n"
        "/startgame — (ادمین) شروع بازی\n"
        "/stopgame — (ادمین) توقف بازی\n"
        "/remove <user_id> — (ادمین) حذف از بازی\n"
        "/leaderboard — نمایش جدول امتیازات\n"
        "/myid — گرفتن آیدی عددی شما"
    )


def main():
    load_state()
    ensure_data_folder()
    app = ApplicationBuilder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_cmd))
    app.add_handler(CommandHandler("myid", myid))
    app.add_handler(CommandHandler("join", join))
    app.add_handler(CommandHandler("leave", leave))
    app.add_handler(CommandHandler("startgame", startgame))
    app.add_handler(CommandHandler("stopgame", stopgame))
    app.add_handler(CommandHandler("remove", remove_player))
    app.add_handler(CommandHandler("leaderboard", leaderboard))

    app.add_handler(CallbackQueryHandler(callback_choose, pattern=r"^choose\|"))
    app.add_handler(CallbackQueryHandler(callback_set_category, pattern=r"^set\|"))
    app.add_handler(CallbackQueryHandler(callback_response, pattern=r"^resp\|"))

    print("Bot started")
    app.run_polling()


if __name__ == "__main__":
    main()