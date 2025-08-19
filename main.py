# main.py
import asyncio
import json
import os
import random
from typing import Optional

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.constants import ParseMode
from telegram.ext import (
    ApplicationBuilder,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
)

# ---------- تنظیمات ----------
from config import BOT_TOKEN, ADMIN_ID, DATA_FOLDER, SCORE_FILE

# پارامترها (قابل تغییر)
TURN_TIMEOUT = 90           # ثانیه زمان پاسخ
SCORE_DARE = 2
SCORE_TRUTH = 1
PENALTY_NO_ANSWER = -1
MAX_CHANGES_PER_TURN = 2
AUTO_DELETE_SECONDS = 15    # حذف خودکار پیام‌های اطلاع‌رسانی join/leave

# ---------- state file ----------
STATE_FILE = SCORE_FILE  # از کانفیگ استفاده می‌کنیم

# ---------- global state ----------
state = {"games": {}, "scores": {}}
current_tasks: dict = {}  # chat_id -> asyncio.Task (واچرها)

# ---------- کمک‌کننده‌ها ----------
def save_state():
    try:
        with open(STATE_FILE, "w", encoding="utf-8") as f:
            json.dump(state, f, ensure_ascii=False, indent=2)
    except Exception:
        pass


def load_state():
    global state
    if os.path.exists(STATE_FILE):
        try:
            with open(STATE_FILE, "r", encoding="utf-8") as f:
                state = json.load(f)
        except Exception:
            state = {"games": {}, "scores": {}}
    else:
        state = {"games": {}, "scores": {}}


def is_admin(user_id) -> bool:
    try:
        return int(user_id) == int(ADMIN_ID)
    except Exception:
        return False


def mention_html(uid: int, fallback: str = "کاربر") -> str:
    return f"<a href='tg://user?id={uid}'>{fallback}</a>"


def get_player_mention(user) -> str:
    if user.username:
        return f"@{user.username}"
    return f"{user.first_name}"


def qpath(name: str) -> str:
    return os.path.join(DATA_FOLDER, name) if DATA_FOLDER else name


FILES = {
    "truth_boy": qpath("truth_boys.txt"),
    "truth_girl": qpath("truth_girls.txt"),
    "dare_boy": qpath("dare_boys.txt"),
    "dare_girl": qpath("dare_girls.txt"),
}


def ensure_data_folder():
    if DATA_FOLDER and not os.path.exists(DATA_FOLDER):
        os.makedirs(DATA_FOLDER, exist_ok=True)


def delete_later(bot, chat_id: int, message_id: int, delay: int = AUTO_DELETE_SECONDS):
    async def _del():
        try:
            await asyncio.sleep(delay)
            await bot.delete_message(chat_id=chat_id, message_id=message_id)
        except Exception:
            pass
    try:
        asyncio.create_task(_del())
    except Exception:
        pass


# ---------- سوال‌ها (اگر فایل غایب بود، همین‌ها را بنویس) ----------
def ensure_question_files():
    samples = {
        "truth_boy": [
            "برای اینکه جذاب به نظر برسی چه کار می‌کنی؟",
            "در حال حاضر از کی خوشت میاد؟",
            "به کی حسودی می‌کنی؟",
            "پنج پسر اولی که به نظرت جذابن رو نام ببر؟",
            "اگر می‌تونستی نامرئی بشی چکار می‌کردی؟",
            "دختر ایده‌آلت چه ویژگی‌هایی داره؟",
            "تا به حال عاشق شدی؟",
            "اگر هرچیزی که می‌خواستی رو می‌تونستی بخری، چی می‌خریدی؟",
            "اسم کسی که توی این جمع خیلی خیلی دوسش داری چیه؟",
            "زیباترین خاطرت با کیه؟",
            "به شریکت بگو که چه ویژگی هایی رو در اون دوست داری",
            "سخت‌ترین و تلخ‌ترین لحظات زندگیت با عشقت رو بازگو کن",
            "در چه مورد دوست نداری کسی با عشقت شوخی کنه؟",
            "اولین برداشت تو از عشقت چه بوده؟",
            "چه کسی توی این جمع از همه خوشگلتره؟",
            "یکی از فانتزی‌هات رو تعریف کن",
            "تا به حال مواد مخدر مصرف کردی؟",
            "تا به حال کسی پیشنهاد دوستی تو رو رد کرده؟",
            "مرد یا زن رویا‌های تو چه شکلیه؟",
            "جذاب‌ترین آدم توی این اتاق از نظر تو کیه؟",
            "تا حالا تو جمع گوزیدی؟",
            "رو کسی تو این جمع کراش داری؟",
            "آخرین دعوات کی بوده؟",
            "رلی یا سینگل؟",
            "گرون قیمت ترین چیزی که خریدی؟",
            "نظرت درباره ادمین گروه؟",
            "بزرگترین ترست چیه؟",
            "بزرگترین اشتباهی که تا حالا کردی چی بوده؟",
            "تا حالا عاشق شدی؟",
            "چیزی هست که از خودت پنهان کنی؟",
            "اگه میتونستی یه چیزی رو توی زندگیت تغییر بدی، چی بود؟",
            "از چی بیشتر از همه میترسی؟",
            "تاحالا به کسی دروغ گفتی؟",
            "تاحالا چیزی رو از کسی دزدیدی؟",
            "چیزی هست که ازش پشیمون باشی؟",
            "بزرگترین آرزوت چیه؟",
            "تا حالا به کسی حسودی کردی؟",
            "چیزی هست که بخوای به دوستت بگی ولی جراتشو نداشته باشی؟",
            "بهترین دوستت چه ویژگی ای داره؟",
            "اگه یه روز بتونی جای یه نفر دیگه باشی، کی رو انتخاب میکنی؟",
            "بزرگترین موفقیتت چی بوده؟",
            "تا حالا چیزی رو شکستی که خیلی با ارزش بوده؟",
            "بهترین خاطره ات از بچگی چیه؟",
            "بدترین اتفاقی که برات افتاده چی بوده؟",
            "چیزی هست که ازش خجالت بکشی؟",
            "اگه یه آرزو داشته باشی، چی از خدا میخوای؟",
        ],
        "truth_girl": [
            "دوست داری چندتا بچه داشته باشی؟",
            "بعضی از ناامنی‌هایی که تو رابطه‌ت حس می‌کنی رو نام ببر",
            "یک دروغ که توی رابطت گفتی رو تعریف کن",
            "چه چیزی در مورد ادمین رو نمی‌پسندی؟",
            "چه چیزی در مورد دوستات رو دوست داری؟",
            "اگر مجبور باشی با یکی از پسر‌ها / دختر‌های این جمع ازدواج کنی، کدام را انتخاب می‌کنی؟",
            "آهنگ مورد علاقت چیه؟",
            "به چه کسی توی این جمع حسادت می‌کنی؟",
            "از گفتن چه چیزی به من بیش از همه می‌ترسی؟",
            "اگر هرچیزی که می‌خواستی رو می‌تونستی بخری، چی می‌خریدی؟",
            "برای اینکه جذاب به نظر برسی چه کار می‌کنی؟",
            "در حال حاضر از کی خوشت میاد؟",
            "به کی حسودی می‌کنی؟",
            "پنج پسر اولی که به نظرت جذابن رو نام ببر؟",
            "جذاب‌ترین چیز در مورد مرد‌ها چیه؟",
            "آیا با کسی که از تو کوتاهتر باشه ازدواج می‌کنی؟",
            "از کی بیشتر از همه بدت میاد؟",
            "از کدوم بازیگر خوشت میاد؟",
            "اگر می‌شد پسر بشی، چکار می‌کردی؟",
            "کی توی این جمع از همه خنده‌دارتره؟",
            "آیا تاکنون از جیب کسی پول برداشته اید؟",
            "آیا از دوستی با یکی از افراد جمع پشیمان هستید؟",
            "فکر می کنید که حسود ترین شخص جمع کیست؟",
            "آیا تاکنون بدهی افراد را زیر پا گذاشته اید؟ (در صورتی که آن ها هم فراموش کرده باشند.)",
            "آیا تا به حال به کسی خیانت کرده اید؟",
            "بدترین شکست عشقی شما چه بود؟",
            "آخرین باری که به کسی دایرکت بد دادید را بخوانید.",
            "به نظر تو باهوش ترین شخص جمع کیست؟",
            "به نظر شما جلف ترین شخص جمع کیست؟",
            "لوس ترین حرفی که به پارتنرنت زدی؟",
            "بدترین جمله عاشقانه ای که گفته ای چه بود؟",
            "بد ترین سوتی عمرت",
            "دوست داری چند سالگی ازدواج کنی؟",
            "دوست داری بچه دختر باشه یا پسر؟",
            "آخرین بازی که توسط پدر و مادرت تنبیه شدی؟",
            "الان چه لباسی پوشیدی؟",
            "بدترین حرکتی یه پسر می‌تونه بزنه و از چشمات میوفته؟",
            "پسر پولدار زشت یا پسر فقیر خوشتیپ",
            "ادمین این گپ خیلی بی،شعوره قبول داری؟",
        ],
        "dare_boy": [
            "یک عکس از خودت با یک فیلتر خنده دار در گروه بفرست.",
            "یک پیام عاشقانه به فردی که بیشتر از همه دوستش داری بفرست.",
            "به مدت یک دقیقه وانمود کن که یک حیوان هستی.",
            "یک ژست خنده دار بگیر و عکسش را در گروه بفرست.",
            "یک جوک خنده دار برای گروه تعریف کن.",
            "یک کار احمقانه انجام بده و آن را در گروه به اشتراک بگذار.",
            "یک دقیقه تمام حرف بزن بدون اینکه مکث کنی.",
            "به یکی از دخترای گپ پیشنهاد ازدواج بده",
            "سرچ اخیر گوگل رو اسکرین بگیر و بفرست گروه",
            "وویس بگیر و صدای خر دربیار",
            "8 ثانیه از محیطی که الان هستی فیلم بگیر و بفرست گروه",
            "به یکی از اعضای گپ بگو روشون کراش داری",
            "یک جوک خنده دار برای گروه تعریف کن.",
            "عکس سعید طوسی رو دانلود کن و برای دو ساعت بزاز پروفایلت",
            "دو عکس اخر گالریت رو به اشتراک بزار",
            "از صفحه گوشیت اسکرین بفرست",
            "تو بیوگرافیت بنویس این کاربر عقل ندارد » و بزار یک ساعت بمونه",
            "وویس بگیر و سعی کن انگلیسی صحبت کنی",
        ],
        "dare_girl": [
            "عکس از خودت با یک فیلتر خنده دار در گروه بفرست.",
            "یک پیام عاشقانه به فردی که بیشتر از همه دوستش داری بفرست.",
            "به مدت یک دقیقه وانمود کن که یک حیوان هستی.",
            "یک ژست خنده دار بگیر و عکسش را در گروه بفرست.",
            "یک جوک خنده دار برای گروه تعریف کن.",
            "یک کار احمقانه انجام بده و آن را در گروه به اشتراک بگذار.",
            "یک دقیقه تمام حرف بزن بدون اینکه مکث کنی.",
            "به یکی از پسرای گپ پیشنهاد ازدواج بده",
            "سرچ اخیر گوگل رو اسکرین بگیر و بفرست گروه",
            "وویس بگیر و صدای خر دربیار",
            "8 ثانیه از محیطی که الان هستی فیلم بگیر و بفرست گروه",
            "به یکی از اعضای گپ بگو روشون کراش داری",
            "یک جوک خنده دار برای گروه تعریف کن.",
            "عکس آنا در آرماس  رو دانلود کن و برای دو ساعت بزاز پروفایلت",
            "دو عکس اخر گالریت رو به اشتراک بزار",
            "از صفحه گوشیت اسکرین بفرست",
            "تو بیوگرافیت بنویس این کاربر عقل ندارد » و بزار یک ساعت بمونه",
            "وویس بگیر وسعی کن انگلیسی صحبت کنی",
        ],
    }
    # اگر فایل‌های سوال وجود نداشت، آن‌ها را ایجاد کن
    for key, path in FILES.items():
        if not os.path.exists(path):
            d = os.path.dirname(path)
            if d:
                os.makedirs(d, exist_ok=True)
            arr = samples.get(key, ["سوال نمونه"])
            with open(path, "w", encoding="utf-8") as f:
                f.write("\n".join(arr))


def load_questions(fn: str):
    if fn in FILES:
        path = FILES[fn]
    else:
        path = fn
    if not path or not os.path.exists(path):
        return []
    with open(path, "r", encoding="utf-8") as f:
        return [l.strip() for l in f if l.strip()]


def get_random_question(qtype: str, avoid: Optional[str] = None) -> Optional[str]:
    filename = {
        "truth_boy": FILES["truth_boy"],
        "truth_girl": FILES["truth_girl"],
        "dare_boy": FILES["dare_boy"],
        "dare_girl": FILES["dare_girl"],
    }.get(qtype)
    if not filename:
        return None
    qs = load_questions(filename)
    if not qs:
        return None
    if avoid and len(qs) > 1:
        q = random.choice(qs)
        a = 0
        while q == avoid and a < 6:
            q = random.choice(qs)
            a += 1
        return q
    return random.choice(qs)


# ---------- مدیریت بازی ----------
def init_game(chat_id: int):
    games = state.get("games", {})
    if str(chat_id) not in games:
        games[str(chat_id)] = {
            "players": [],
            "idx": -1,
            "awaiting": False,
            "current_question": "",
            "current_type": "",
            "change_count": {},
            "started": False,
            "last_group_msg_id": None,
        }
        state["games"] = games
        save_state()


def add_score(uid, amount=1):
    s = state.setdefault("scores", {})
    k = str(uid)
    if k not in s:
        s[k] = {"score": 0}
    s[k]["score"] += amount
    save_state()


def get_leaderboard(limit=10):
    items = []
    for uid, info in state.get("scores", {}).items():
        items.append((uid, info.get("score", 0)))
    items.sort(key=lambda x: x[1], reverse=True)
    return items[:limit]


def next_player(chat_id: int) -> Optional[int]:
    g = state["games"].get(str(chat_id))
    if not g:
        return None
    if not g["players"]:
        return None
    g["idx"] = (g.get("idx", -1) + 1) % len(g["players"])
    save_state()
    return g["players"][g["idx"]]


def current_player(chat_id: int) -> Optional[int]:
    g = state["games"].get(str(chat_id))
    if not g or not g.get("players"):
        return None
    idx = g.get("idx", -1)
    if idx < 0 or idx >= len(g["players"]):
        return None
    return g["players"][idx]


# ---------- فرمان‌ها ----------
async def start_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = "سلام! 🎲 ربات جرأت یا حقیقت\nاز دکمه‌ها استفاده کن یا دستورها رو وارد کن."
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("🎯 پیوستن به بازی", callback_data="menu|join")],
        [InlineKeyboardButton("🚪 ترک بازی", callback_data="menu|leave"),
         InlineKeyboardButton("▶️ شروع بازی (ادمین)", callback_data="menu|startgame")],
        [InlineKeyboardButton("⏹ توقف بازی (ادمین)", callback_data="menu|stopgame")],
        [InlineKeyboardButton("🏆 جدول امتیازات", callback_data="menu|leaderboard"),
         InlineKeyboardButton("🆔 آیدی من", callback_data="menu|myid")],
    ])
    await context.bot.send_message(chat_id=update.effective_chat.id, text=text, reply_markup=kb)


async def myid_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    try:
        await context.bot.send_message(chat_id=user.id, text=f"آیدی شما: {user.id}")
        await update.message.reply_text("✅ پیغام به دایرکت شما ارسال شد.")
    except Exception:
        await update.message.reply_text(f"آیدی شما: {user.id}")


async def join_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    user = update.effective_user
    init_game(chat_id)
    g = state["games"][str(chat_id)]
    if user.id in g["players"]:
        try:
            await context.bot.send_message(chat_id=user.id, text="✅ شما قبلاً عضو بازی هستید.")
        except Exception:
            await context.bot.send_message(chat_id=chat_id, text="✅ شما قبلاً عضو بازی هستید.")
        return
    g["players"].append(user.id)
    g["change_count"][str(user.id)] = 0
    save_state()
    msg = await context.bot.send_message(chat_id=chat_id, text=f"✅ {get_player_mention(user)} به بازی اضافه شد. (تعداد: {len(g['players'])})")
    delete_later(context.bot, chat_id, msg.message_id, AUTO_DELETE_SECONDS)


async def leave_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    user = update.effective_user
    init_game(chat_id)
    g = state["games"][str(chat_id)]
    if user.id not in g["players"]:
        await context.bot.send_message(chat_id=chat_id, text="❌ شما در لیست نیستید.")
        return
    g["players"].remove(user.id)
    g["change_count"].pop(str(user.id), None)
    save_state()
    msg = await context.bot.send_message(chat_id=chat_id, text=f"✅ {get_player_mention(user)} از بازی خارج شد. (تعداد: {len(g['players'])})")
    delete_later(context.bot, chat_id, msg.message_id, AUTO_DELETE_SECONDS)


async def startgame_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    chat_id = update.effective_chat.id
    if not is_admin(user.id):
        await context.bot.send_message(chat_id=chat_id, text="فقط ادمین می‌تواند بازی را شروع کند.")
        return
    init_game(chat_id)
    g = state["games"][str(chat_id)]
    if not g["players"]:
        await context.bot.send_message(chat_id=chat_id, text="هیچ بازیکنی نیست. لطفاً /join کنید.")
        return
    # shuffle players
    random.shuffle(g["players"])
    g["started"] = True
    g["idx"] = -1
    g["change_count"] = {str(uid): 0 for uid in g["players"]}
    save_state()
    await context.bot.send_message(chat_id=chat_id, text=f"🎮 بازی شروع شد — شرکت‌کنندگان: {len(g['players'])}")
    await asyncio.sleep(0.2)
    await do_next_turn(chat_id, context)


async def stopgame_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    chat_id = update.effective_chat.id
    if not is_admin(user.id):
        await context.bot.send_message(chat_id=chat_id, text="فقط ادمین می‌تواند بازی را متوقف کند.")
        return
    init_game(chat_id)
    g = state["games"][str(chat_id)]
    g["started"] = False
    g["awaiting"] = False
    save_state()
    # cancel watcher
    t = current_tasks.get(chat_id)
    if t:
        try:
            t.cancel()
        except Exception:
            pass
        current_tasks.pop(chat_id, None)
    try:
        if g.get("last_group_msg_id"):
            await context.bot.delete_message(chat_id=chat_id, message_id=g["last_group_msg_id"])
            g["last_group_msg_id"] = None
            save_state()
    except Exception:
        pass
    await context.bot.send_message(chat_id=chat_id, text="⏹ بازی متوقف شد.")


async def remove_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    chat_id = update.effective_chat.id
    if not is_admin(user.id):
        await context.bot.send_message(chat_id=chat_id, text="فقط ادمین می‌تواند حذف کند.")
        return
    if not context.args:
        await context.bot.send_message(chat_id=chat_id, text="مثال: /remove 123456789")
        return
    try:
        tid = int(context.args[0])
    except Exception:
        await context.bot.send_message(chat_id=chat_id, text="آیدی عددی وارد کنید.")
        return
    removed = False
    for cid, gg in state.get("games", {}).items():
        if tid in gg.get("players", []):
            gg["players"].remove(tid)
            gg["change_count"].pop(str(tid), None)
            removed = True
    if removed:
        save_state()
        await context.bot.send_message(chat_id=chat_id, text="✅ حذف شد.")
    else:
        await context.bot.send_message(chat_id=chat_id, text="آن کاربر در بازی نیست.")


async def leaderboard_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    items = get_leaderboard(10)
    if not items:
        await context.bot.send_message(chat_id=chat_id, text="هیچ امتیازی ثبت نشده.")
        return
    lines = ["🏆 جدول امتیازات:"]
    i = 1
    for uid, sc in items:
        mention = str(uid)
        try:
            member = await context.bot.get_chat_member(chat_id, int(uid))
            mention = member.user.username and ("@" + member.user.username) or member.user.first_name
        except Exception:
            mention = str(uid)
        lines.append(f"{i}. {mention} — {sc}")
        i += 1
    await context.bot.send_message(chat_id=chat_id, text="\n".join(lines))


# ---------- رد کردن نوبت (ادمین) ----------
async def skip_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    chat_id = update.effective_chat.id
    if not is_admin(user.id):
        await context.bot.send_message(chat_id=chat_id, text="فقط ادمین می‌تواند نوبت را رد کند.")
        return
    init_game(chat_id)
    g = state["games"][str(chat_id)]
    cur = current_player(chat_id)
    if not cur:
        await context.bot.send_message(chat_id=chat_id, text="نوبتی وجود ندارد یا بازی شروع نشده.")
        return
    # cancel watcher
    t = current_tasks.get(chat_id)
    if t:
        try:
            t.cancel()
        except Exception:
            pass
        current_tasks.pop(chat_id, None)
    g["awaiting"] = False
    save_state()
    try:
        member = await context.bot.get_chat_member(chat_id, cur)
        name = member.user.username and ("@" + member.user.username) or member.user.first_name
    except Exception:
        name = str(cur)
    await context.bot.send_message(chat_id=chat_id, text=f"⏭️ ادمین {get_player_mention(user)} نوبت {mention_html(cur, name)} را رد کرد.", parse_mode=ParseMode.HTML)
    await asyncio.sleep(0.2)
    await do_next_turn(chat_id, context)


# ---------- جریان اصلی بازی ----------
async def do_next_turn(chat_id: int, context: ContextTypes.DEFAULT_TYPE):
    init_game(chat_id)
    g = state["games"][str(chat_id)]
    if not g["players"]:
        await context.bot.send_message(chat_id=chat_id, text="هیچ بازیکنی نیست. بازی متوقف می‌شود.")
        g["started"] = False
        save_state()
        return
    if not g.get("started"):
        return

    # cancel previous watcher if exists
    prev = current_tasks.get(chat_id)
    if prev:
        try:
            prev.cancel()
        except Exception:
            pass
        current_tasks.pop(chat_id, None)

    # advance index
    g["idx"] = (g.get("idx", -1) + 1) % len(g["players"])
    pid = g["players"][g["idx"]]
    g["change_count"].setdefault(str(pid), 0)
    g["awaiting"] = True
    g["current_question"] = ""
    g["current_type"] = ""
    save_state()

    # get display name
    mention_name = str(pid)
    try:
        member = await context.bot.get_chat_member(chat_id, pid)
        mention_name = member.user.username and ("@" + member.user.username) or member.user.first_name
    except Exception:
        mention_name = str(pid)

    # send group prompt with 4 options + admin skip
    group_text = f"👤 نوبت: {mention_html(pid, mention_name)}\nشرکت‌کنندگان: {len(g['players'])}\nنوع سوال: انتخاب کن"
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("حقیقت (پسر)", callback_data=f"set|truth_boy|{pid}"),
         InlineKeyboardButton("حقیقت (دختر)", callback_data=f"set|truth_girl|{pid}")],
        [InlineKeyboardButton("جرأت (پسر)", callback_data=f"set|dare_boy|{pid}"),
         InlineKeyboardButton("جرأت (دختر)", callback_data=f"set|dare_girl|{pid}")],
        [InlineKeyboardButton("⏭️ رد نوبت (ادمین)", callback_data=f"admin|skip|{pid}")]
    ])
    try:
        msg = await context.bot.send_message(chat_id=chat_id, text=group_text, reply_markup=kb, parse_mode=ParseMode.HTML)
        g["last_group_msg_id"] = msg.message_id
        save_state()
    except Exception:
        pass

    # start timeout watcher
    async def watcher(target_pid: int):
        try:
            await asyncio.sleep(TURN_TIMEOUT)
            # reload to avoid race
            load_state()
            g_local = state.get("games", {}).get(str(chat_id))
            if g_local and g_local.get("started") and g_local.get("awaiting") and g_local.get("players") and g_local.get("players")[g_local.get("idx")] == target_pid:
                # apply penalty
                state["games"][str(chat_id)]["awaiting"] = False
                add_score(target_pid, PENALTY_NO_ANSWER)
                save_state()
                try:
                    member2 = await context.bot.get_chat_member(chat_id, target_pid)
                    mname = member2.user.username and ("@" + member2.user.username) or member2.user.first_name
                except Exception:
                    mname = str(target_pid)
                try:
                    await context.bot.send_message(
                        chat_id=chat_id,
                        text=f"⏱ {mention_html(target_pid, mname)} فرصت پاسخ را از دست داد — {PENALTY_NO_ANSWER} امتیاز کسر شد.",
                        parse_mode=ParseMode.HTML
                    )
                except Exception:
                    pass
                await asyncio.sleep(0.2)
                st2 = load_state()
                g2 = state.get("games", {}).get(str(chat_id))
                if g2 and g2.get("started"):
                    await do_next_turn(chat_id, context)
        except asyncio.CancelledError:
            return

    task = asyncio.create_task(watcher(pid))
    current_tasks[chat_id] = task


# ----------------- هندلر CallbackQuery (منو و دکمه‌ها) -----------------
async def callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if not query or not query.data:
        return
    await query.answer()
    data = query.data
    parts = data.split("|")
    cmd = parts[0]

    # منوها (از /start)
    if cmd == "menu":
        sub = parts[1] if len(parts) > 1 else ""
        if sub == "join":
            await join_cmd(update, context)
            return
        if sub == "leave":
            await leave_cmd(update, context)
            return
        if sub == "startgame":
            await startgame_cmd(update, context)
            return
        if sub == "stopgame":
            await stopgame_cmd(update, context)
            return
        if sub == "leaderboard":
            await leaderboard_cmd(update, context)
            return
        if sub == "myid":
            await myid_cmd(update, context)
            return

    # admin actions from inline button
    if cmd == "admin":
        action = parts[1] if len(parts) > 1 else ""
        target = int(parts[2]) if len(parts) > 2 and parts[2].isdigit() else None
        chat_id = query.message.chat.id
        user = query.from_user
        if action == "skip":
            if not is_admin(user.id):
                try:
                    await query.answer("فقط ادمین می‌تواند نوبت را رد کند.", show_alert=True)
                except Exception:
                    pass
                return
            init_game(chat_id)
            g = state["games"][str(chat_id)]
            cur = current_player(chat_id)
            if not cur:
                await context.bot.send_message(chat_id=chat_id, text="نوبتی وجود ندارد.")
                return
            # cancel watcher
            t = current_tasks.get(chat_id)
            if t:
                try:
                    t.cancel()
                except Exception:
                    pass
                current_tasks.pop(chat_id, None)
            g["awaiting"] = False
            save_state()
            try:
                member = await context.bot.get_chat_member(chat_id, cur)
                name = member.user.username and ("@" + member.user.username) or member.user.first_name
            except Exception:
                name = str(cur)
            await context.bot.send_message(chat_id=chat_id, text=f"⏭️ ادمین {get_player_mention(user)} نوبت {mention_html(cur, name)} را رد کرد.", parse_mode=ParseMode.HTML)
            # delete last group prompt if any
            try:
                if g.get("last_group_msg_id"):
                    await context.bot.delete_message(chat_id=chat_id, message_id=g["last_group_msg_id"])
                    g["last_group_msg_id"] = None
                    save_state()
            except Exception:
                pass
            await asyncio.sleep(0.2)
            await do_next_turn(chat_id, context)
            return

    # set|<qtype>|<pid>  -> نمایش سوال **در گروه**
    if cmd == "set":
        qtype = parts[1] if len(parts) > 1 else ""
        target = int(parts[2]) if len(parts) > 2 and parts[2].isdigit() else None
        chat_id = query.message.chat.id
        user = query.from_user
        init_game(chat_id)
        g = state["games"][str(chat_id)]
        try:
            cur = current_player(chat_id)
        except Exception:
            cur = None
        if cur is None or user.id != cur or target != cur:
            try:
                await query.answer("❌ نوبت شما نیست.", show_alert=True)
            except Exception:
                pass
            return

        # delete the choose-message so player can't press again
        try:
            await query.message.delete()
        except Exception:
            pass

        q = get_random_question(qtype, avoid=g.get("current_question", ""))
        if not q:
            await context.bot.send_message(chat_id=chat_id, text="سوال موجود نیست؛ ادمین لطفا فایل سوال را کامل کنه.")
            return
        g["current_question"] = q
        g["current_type"] = qtype
        g["awaiting"] = True
        save_state()

        # group message with question and buttons
        group_kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("✅ پاسخ دادم", callback_data=f"resp|done|{target}"),
             InlineKeyboardButton("🔄 تغییر سوال", callback_data=f"resp|change|{target}")],
            [InlineKeyboardButton("🚫 پاسخ نمیدهم", callback_data=f"resp|no|{target}")]
        ])
        mention_name = user.username and ("@" + user.username) or user.first_name
        try:
            msg = await context.bot.send_message(
                chat_id=chat_id,
                text=f"📝 سوال برای {mention_html(target, mention_name)}:\n\n{q}\n\n⏳ {TURN_TIMEOUT} ثانیه فرصت دارید.",
                reply_markup=group_kb,
                parse_mode=ParseMode.HTML
            )
            g["last_group_msg_id"] = msg.message_id
            save_state()
        except Exception:
            # fallback: reply
            await query.message.reply_text(f"📝 سوال:\n{q}", reply_markup=group_kb)
        # cancel previous watcher and start a new one for this question
        prev = current_tasks.get(chat_id)
        if prev:
            try:
                prev.cancel()
            except Exception:
                pass
            current_tasks.pop(chat_id, None)

        async def watcher_q(pid_target: int):
            try:
                await asyncio.sleep(TURN_TIMEOUT)
                load_state()
                g_local = state.get("games", {}).get(str(chat_id))
                if g_local and g_local.get("started") and g_local.get("awaiting") and g_local.get("players") and g_local.get("players")[g_local.get("idx")] == pid_target:
                    state["games"][str(chat_id)]["awaiting"] = False
                    add_score(pid_target, PENALTY_NO_ANSWER)
                    save_state()
                    try:
                        member2 = await context.bot.get_chat_member(chat_id, pid_target)
                        mname = member2.user.username and ("@" + member2.user.username) or member2.user.first_name
                    except Exception:
                        mname = str(pid_target)
                    try:
                        await context.bot.send_message(chat_id=chat_id, text=f"⏱ {mention_html(pid_target, mname)} فرصت پاسخ را از دست داد — {PENALTY_NO_ANSWER} امتیاز کسر شد.", parse_mode=ParseMode.HTML)
                    except Exception:
                        pass
                    await asyncio.sleep(0.2)
                    st2 = load_state()
                    g2 = state.get("games", {}).get(str(chat_id))
                    if g2 and g2.get("started"):
                        await do_next_turn(chat_id, context)
            except asyncio.CancelledError:
                return

        task = asyncio.create_task(watcher_q(target))
        current_tasks[chat_id] = task
        return

    # resp|action|pid
    if cmd == "resp":
        action = parts[1] if len(parts) > 1 else ""
        target = int(parts[2]) if len(parts) > 2 and parts[2].isdigit() else None
        user = query.from_user
        chat_id = query.message.chat.id

        # ensure correct user
        if user.id != target:
            try:
                await query.answer("این دکمه برای شما نیست.", show_alert=True)
            except Exception:
                pass
            return

        init_game(chat_id)
        g = state["games"][str(chat_id)]
        # cancel watcher
        t = current_tasks.get(chat_id)
        if t:
            try:
                t.cancel()
            except Exception:
                pass
            current_tasks.pop(chat_id, None)

        if action == "done":
            qtype = g.get("current_type", "")
            if qtype and qtype.startswith("dare"):
                add_score(user.id, SCORE_DARE)
                pts = SCORE_DARE
            else:
                add_score(user.id, SCORE_TRUTH)
                pts = SCORE_TRUTH
            g["awaiting"] = False
            save_state()
            try:
                await context.bot.send_message(chat_id=chat_id, text=f"✅ {mention_html(user.id, user.first_name)} پاسخ داد — +{pts} امتیاز.", parse_mode=ParseMode.HTML)
            except Exception:
                pass
            # cleanup last group prompt if exists
            try:
                if g.get("last_group_msg_id"):
                    await context.bot.delete_message(chat_id=chat_id, message_id=g["last_group_msg_id"])
                    g["last_group_msg_id"] = None
                    save_state()
            except Exception:
                pass
            await asyncio.sleep(0.2)
            await do_next_turn(chat_id, context)
            return

        if action == "no":
            add_score(user.id, PENALTY_NO_ANSWER)
            g["awaiting"] = False
            save_state()
            try:
                await context.bot.send_message(chat_id=chat_id, text=f"⛔ {mention_html(user.id, user.first_name)} پاسخ نداد/نخواست — {PENALTY_NO_ANSWER} امتیاز.", parse_mode=ParseMode.HTML)
            except Exception:
                pass
            try:
                if g.get("last_group_msg_id"):
                    await context.bot.delete_message(chat_id=chat_id, message_id=g["last_group_msg_id"])
                    g["last_group_msg_id"] = None
                    save_state()
            except Exception:
                pass
            await asyncio.sleep(0.2)
            await do_next_turn(chat_id, context)
            return

        if action == "change":
            cnt = g["change_count"].get(str(user.id), 0)
            if cnt >= MAX_CHANGES_PER_TURN:
                await query.answer("⚠️ دیگر نمی‌توانید سوال را تغییر دهید.", show_alert=True)
                return
            qtype = g.get("current_type", "")
            q_new = get_random_question(qtype, avoid=g.get("current_question", ""))
            if not q_new:
                await context.bot.send_message(chat_id=chat_id, text="سوال موجود نیست؛ ادمین کاملش کنه.")
                return
            g["current_question"] = q_new
            g["change_count"][str(user.id)] = cnt + 1
            save_state()
            # update the group message (edit) if possible
            try:
                if g.get("last_group_msg_id"):
                    await context.bot.edit_message_text(
                        chat_id=chat_id,
                        message_id=g["last_group_msg_id"],
                        text=f"📝 سوال جدید برای {mention_html(user.id, user.first_name)}:\n\n{q_new}\n(تغییر: {g['change_count'][str(user.id)]}/{MAX_CHANGES_PER_TURN})\n⏳ {TURN_TIMEOUT} ثانیه فرصت دارید.",
                        reply_markup=InlineKeyboardMarkup([
                            [InlineKeyboardButton("✅ پاسخ دادم", callback_data=f"resp|done|{user.id}"),
                             InlineKeyboardButton("🔄 تغییر سوال", callback_data=f"resp|change|{user.id}")],
                            [InlineKeyboardButton("🚫 پاسخ نمیدهم", callback_data=f"resp|no|{user.id}")]
                        ]),
                        parse_mode=ParseMode.HTML
                    )
                else:
                    # fallback: send new
                    msg = await context.bot.send_message(chat_id=chat_id, text=f"📝 سوال جدید:\n{q_new}")
                    g["last_group_msg_id"] = msg.message_id
                    save_state()
            except Exception:
                try:
                    await context.bot.send_message(chat_id=chat_id, text=f"📝 سوال جدید:\n{q_new}")
                except Exception:
                    pass
            # restart watcher
            async def restart_watcher():
                try:
                    await asyncio.sleep(TURN_TIMEOUT)
                    st = load_state()
                    g_local = state.get("games", {}).get(str(chat_id))
                    if g_local and g_local.get("started") and g_local.get("awaiting") and g_local.get("players") and g_local.get("players")[g_local.get("idx")] == user.id:
                        state["games"][str(chat_id)]["awaiting"] = False
                        add_score(user.id, PENALTY_NO_ANSWER)
                        save_state()
                        try:
                            member2 = await context.bot.get_chat_member(chat_id, user.id)
                            mname = member2.user.username and ("@" + member2.user.username) or member2.user.first_name
                        except Exception:
                            mname = str(user.id)
                        try:
                            await context.bot.send_message(chat_id=chat_id, text=f"⏱ {mention_html(user.id, mname)} فرصت پاسخ را از دست داد — {PENALTY_NO_ANSWER} امتیاز کسر شد.", parse_mode=ParseMode.HTML)
                        except Exception:
                            pass
                        await asyncio.sleep(0.2)
                        st2 = load_state()
                        g2 = state.get("games", {}).get(str(chat_id))
                        if g2 and g2.get("started"):
                            await do_next_turn(chat_id, context)
                except asyncio.CancelledError:
                    return
            task = asyncio.create_task(restart_watcher())
            current_tasks[chat_id] = task
            return

    # fallback: نادیده گرفتن
    try:
        await context.bot.send_message(chat_id=update.effective_chat.id, text="عملیات نامشخص یا منقضی شده.")
    except Exception:
        pass


# ---------- main ----------
def main():
    load_state()
    ensure_data_folder()
    ensure_question_files()

    app = ApplicationBuilder().token(BOT_TOKEN).build()

    # commands
    app.add_handler(CommandHandler("start", start_cmd))
    app.add_handler(CommandHandler("help", start_cmd))
    app.add_handler(CommandHandler("myid", myid_cmd))
    app.add_handler(CommandHandler("join", join_cmd))
    app.add_handler(CommandHandler("leave", leave_cmd))
    app.add_handler(CommandHandler("startgame", startgame_cmd))
    app.add_handler(CommandHandler("stopgame", stopgame_cmd))
    app.add_handler(CommandHandler("remove", remove_cmd))
    app.add_handler(CommandHandler("leaderboard", leaderboard_cmd))
    app.add_handler(CommandHandler("skip", skip_cmd))

    # callback queries (all)
    app.add_handler(CallbackQueryHandler(callback_handler))

    print("Bot started")
    app.run_polling()


if __name__ == "__main__":
    main()
