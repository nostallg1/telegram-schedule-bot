import logging
import os
import re
import sqlite3
import threading
import asyncio
from contextlib import closing
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, ContextTypes, CallbackQueryHandler, MessageHandler, filters
from parser import fetch_schedule_dict

# --- FLASK ---
from flask import Flask
app = Flask(__name__)
@app.route('/')
def health_check(): return "Bot is running!"
@app.route('/health')
def health(): return "OK"

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Групи користувачів зберігаються в SQLite (див. блок db_* нижче) 
SCHEDULE_CACHE = {}
TARGET_DAYS = ["Понеділок", "Вівторок", "Середа", "Четвер", "П'ятниця"]
DAY_SHORT_NAMES = {"Понеділок": "Пн", "Вівторок": "Вт", "Середа": "Ср", "Четвер": "Чт", "П'ятниця": "Пт"}

# --- АВТО-ВИПРАВЛЕННЯ РОЗКЛАДКИ ---
def fix_layout(text):
    if not text: return text
    text = text.upper()
    replacements = {'A': 'А', 'B': 'В', 'C': 'С', 'E': 'Е', 'H': 'Н', 'I': 'І', 'K': 'К', 'M': 'М', 'O': 'О', 'P': 'Р', 'T': 'Т', 'X': 'Х', 'Y': 'У'}
    for lat, cyr in replacements.items():
        text = text.replace(lat, cyr)
    return text

# --- SQLITE: ЗБЕРЕЖЕННЯ ГРУПИ КОРИСТУВАЧА ---
# Шлях до файлу можна змінити змінною середовища DB_PATH (наприклад, на підключений постійний диск).
DB_PATH = os.environ.get("DB_PATH", "users.db")

def _db():
    return closing(sqlite3.connect(DB_PATH))

def db_init():
    folder = os.path.dirname(DB_PATH)
    if folder:
        os.makedirs(folder, exist_ok=True)
    with _db() as conn, conn:
        conn.execute("CREATE TABLE IF NOT EXISTS users (chat_id INTEGER PRIMARY KEY, group_name TEXT NOT NULL)")

def db_get_group(chat_id):
    with _db() as conn:
        row = conn.execute("SELECT group_name FROM users WHERE chat_id = ?", (chat_id,)).fetchone()
    return row[0] if row else None

def db_set_group(chat_id, group):
    with _db() as conn, conn:
        conn.execute(
            "INSERT INTO users (chat_id, group_name) VALUES (?, ?) "
            "ON CONFLICT(chat_id) DO UPDATE SET group_name = excluded.group_name",
            (chat_id, group),
        )

# --- ВАЛІДАЦІЯ НАЗВИ ГРУПИ ---
# Літери + (необов'язковий дефіс) + цифри + короткий суфікс, напр. АВ-11, КН-101, ІТ-12с.
# Без "_" (він розділяє частини callback_data) і не довше 16 символів (ліміт callback_data - 64 байти).
GROUP_RE = re.compile(r"^[^\W\d_]{1,10}-?\d{1,4}(?:[^\W_]|[-.]){0,8}$")

def is_valid_group(group):
    return bool(group) and len(group) <= 16 and bool(GROUP_RE.match(group))

# --- КЛАВІАТУРИ ---
def subgroup_text(group):
    return f"🎓 Група: <b>{group}</b>\nОберіть підгрупу:"

def subgroup_keyboard(group):
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("👤 1 підгрупа", callback_data=f"sub_1_{group}"),
         InlineKeyboardButton("👤 2 підгрупа", callback_data=f"sub_2_{group}")],
        [InlineKeyboardButton("👥 Вся група", callback_data=f"sub_all_{group}")],
        [InlineKeyboardButton("🔄 Змінити групу", callback_data="change_group")],
    ])

PROMPT_GROUP_TEXT = "👋 Привіт! Напишіть назву вашої групи (наприклад, <code>АВ-11</code>):"

# --- ГОЛОВНИЙ ЕКРАН ---
async def send_home(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Є збережена група -> меню підгруп. Немає -> просимо написати назву групи."""
    chat_id = update.effective_chat.id
    group = db_get_group(chat_id)
    if group:
        context.user_data.pop('awaiting_group', None)
        await update.effective_message.reply_text(
            subgroup_text(group), reply_markup=subgroup_keyboard(group), parse_mode='HTML')
    else:
        context.user_data['awaiting_group'] = True
        await update.effective_message.reply_text(PROMPT_GROUP_TEXT, parse_mode='HTML')

async def save_group_and_show_menu(update: Update, context: ContextTypes.DEFAULT_TYPE, group: str) -> None:
    chat_id = update.effective_chat.id
    db_set_group(chat_id, group)
    SCHEDULE_CACHE.pop(chat_id, None)  # старий кеш розкладу вже не актуальний
    context.user_data.pop('awaiting_group', None)
    await update.effective_message.reply_text(
        subgroup_text(group), reply_markup=subgroup_keyboard(group), parse_mode='HTML')

# --- КОМАНДИ ---
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await send_home(update, context)

# Старі команди залишені як "приховані" (не рекламуються в інтерфейсі), щоб нічого не зламати.
async def get_rozklad(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if context.args:
        group = fix_layout(context.args[0])
        if is_valid_group(group):
            await save_group_and_show_menu(update, context, group)
            return
    await send_home(update, context)

async def info(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text("ℹ️ Бот парсить дані з student.lpnu.ua")

async def support(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text("🛠 Підтримка: <code>4441111131351441</code>", parse_mode='HTML')

# --- ТЕКСТОВЕ ПОВІДОМЛЕННЯ = НАЗВА ГРУПИ ---
async def group_text_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    message = update.message
    if not message or not message.text:
        return

    group = fix_layout(message.text.strip())
    if is_valid_group(group):
        await save_group_and_show_menu(update, context, group)
        return

    # Текст не схожий на групу
    if context.user_data.get('awaiting_group'):
        await message.reply_text(
            "❓ Не схоже на назву групи. Напишіть її, наприклад, <code>АВ-11</code>:", parse_mode='HTML')
    elif update.effective_chat.type == "private":
        await send_home(update, context)  # завжди повертаємо користувача до кнопок
    # у групових чатах на сторонні повідомлення не реагуємо

# --- LOAD LOGIC ---
async def load_schedule_and_show_days(query, group, sub_param, sub_name, week_param, week_name, retry=False):
    chat_id = query.message.chat_id
    if not retry:
        await query.edit_message_text(f"⏳ Отримую розклад: <b>{group}</b>, {sub_name}, {week_name}...", parse_mode='HTML')
        
    try:
        loop = asyncio.get_running_loop()
        schedule_data = await loop.run_in_executor(None, fetch_schedule_dict, group, "1", "1", sub_param, week_param)
        
        if not schedule_data or "Info" in schedule_data:
            msg = schedule_data.get("Info", "❌ Помилка.") if schedule_data else "❌ Помилка."
            kb = [[InlineKeyboardButton("🔙 Спробувати іншу групу", callback_data="restart_full")]]
            await query.edit_message_text(msg, reply_markup=InlineKeyboardMarkup(kb), parse_mode='HTML')
            return

        # Службовий прапорець з парсера: на сайті немає позначок чисельник/знаменник
        week_unmarked = bool(schedule_data.pop("_week_unmarked", False))

        SCHEDULE_CACHE[chat_id] = {
            'data': schedule_data, 'group': group,
            'sub': sub_param, 'sub_n': sub_name,
            'week': week_param, 'week_n': week_name
        }

        keyboard = []
        row = []
        for day_name in TARGET_DAYS:
            if day_name in schedule_data:
                short = DAY_SHORT_NAMES.get(day_name, day_name)
                wk = week_param if week_param else 'all'
                sb = sub_param if sub_param else 'all'
                
                callback = f"fd_{day_name[:2]}_{group}_{sb}_{wk}"
                row.append(InlineKeyboardButton(short, callback_data=callback))
            if len(row) == 3:
                keyboard.append(row)
                row = []
        if row: keyboard.append(row)
        
        keyboard.append([InlineKeyboardButton("🔙 Змінити тиждень", callback_data=f"back_to_weeks_{sub_param if sub_param else 'all'}_{group}")])

        if not keyboard or (len(keyboard) == 1):
             await query.edit_message_text(f"📭 Розклад для <b>{group}</b> ({sub_name}, {week_name}) порожній.", parse_mode='HTML')
             return

        note = "\nℹ️ <i>Не вдалося визначити чисельник/знаменник для цієї групи, тому показано всі пари.</i>" if (week_unmarked and week_param) else ""
        await query.edit_message_text(
            f"✅ <b>{group}</b> ({sub_name}, {week_name}){note}\nОберіть день:",
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode='HTML'
        )
    except Exception as e:
        logger.error(f"Error: {e}")
        await query.edit_message_text("❌ Помилка.", parse_mode='HTML')

# --- BUTTONS ---
async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    chat_id = query.message.chat_id
    data = query.data
    await query.answer()

    if data in ("change_group", "restart_full"):
        context.user_data['awaiting_group'] = True
        await query.edit_message_text("✏️ Надішліть нову назву групи:")
        return

    if data.startswith("sub_"):
        try:
            _, sub_choice, group = data.split("_", 2)
            keyboard = [
                [InlineKeyboardButton("numerator (Чисельник)", callback_data=f"week_chys_{sub_choice}_{group}")],
                [InlineKeyboardButton("denominator (Знаменник)", callback_data=f"week_znam_{sub_choice}_{group}")],
                [InlineKeyboardButton("Всі тижні", callback_data=f"week_all_{sub_choice}_{group}")]
            ]
            keyboard.append([InlineKeyboardButton("🔙 Змінити підгрупу", callback_data=f"back_to_subs_{group}")])
            sub_name = f"підгр. {sub_choice}" if sub_choice != "all" else "Вся група"
            await query.edit_message_text(f"🎓 <b>{group}</b> ({sub_name})\n📅 Оберіть тиждень:", reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='HTML')
        except ValueError: await query.edit_message_text("⚠️ Помилка.")
        return

    if data.startswith("week_"):
        try:
            parts = data.split("_")
            week_choice = parts[1]
            sub_choice = parts[2]
            group = parts[3]

            sub_param = sub_choice if sub_choice in ["1", "2"] else None
            sub_name = f"підгр. {sub_choice}" if sub_choice != "all" else "Вся група"
            week_param = week_choice if week_choice in ["chys", "znam"] else None
            week_name = "Чисельник" if week_choice == "chys" else ("Знаменник" if week_choice == "znam" else "Всі тижні")

            await load_schedule_and_show_days(query, group, sub_param, sub_name, week_param, week_name)
        except Exception as e: 
            logger.error(e)
            await query.edit_message_text("⚠️ Помилка.")
        return

    if data.startswith("fd_"):
        try:
            parts = data.split("_")
            day_short = parts[1]
            group = parts[2]
            sub_raw = parts[3]
            week_raw = parts[4]

            sub_param = sub_raw if sub_raw != "all" else None
            week_param = week_raw if week_raw != "all" else None
            # Кнопки дня кодують назву як перші 2 літери ("По", "Ві", "Се", "Че", "П'"),
            # тому шукаємо день за цим префіксом (раніше порівнювали з "Пн"/"Вт" і нічого не знаходили)
            day_full = next((k for k in DAY_SHORT_NAMES if k[:2] == day_short or DAY_SHORT_NAMES[k] == day_short), None)

            cache = SCHEDULE_CACHE.get(chat_id)
            if cache and cache.get('group') == group and str(cache.get('sub')) == str(sub_param) and str(cache.get('week')) == str(week_param):
                text = cache['data'].get(day_full, "Немає пар.")
                back_cb = f"back_days_{group}_{sub_raw}_{week_raw}"
                kb = [[InlineKeyboardButton("🔙 До днів тижня", callback_data=back_cb)]]
                await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(kb), parse_mode='HTML')
                return
            
            sub_name = f"підгр. {sub_raw}" if sub_raw != "all" else "Вся група"
            week_name = "Чисельник" if week_raw == "chys" else ("Знаменник" if week_raw == "znam" else "Всі тижні")
            
            await query.edit_message_text(f"⚠️ Оновлюю...", parse_mode='HTML')
            await load_schedule_and_show_days(query, group, sub_param, sub_name, week_param, week_name, retry=True)

        except Exception as e:
            # Подвійний тап на ту саму кнопку дає "Message is not modified" - це не помилка
            if "not modified" in str(e).lower():
                return
            logger.exception(f"FD Error: {e}")  # повний traceback у логах хостингу
            await query.edit_message_text("⚠️ Помилка даних.")
        return

    if data.startswith("back_days_"):
        try:
            parts = data.split("_")
            group = parts[2]
            sub_raw = parts[3]
            week_raw = parts[4]
            
            sub_param = sub_raw if sub_raw != "all" else None
            week_param = week_raw if week_raw != "all" else None
            cache = SCHEDULE_CACHE.get(chat_id)
            # Кеш один на чат: використовуємо його лише якщо він саме для цих групи/підгрупи/тижня,
            # інакше завантажуємо заново (раніше тут міг показатись розклад іншого тижня)
            cache_ok = bool(cache) and cache.get('group') == group \
                and str(cache.get('sub')) == str(sub_param) and str(cache.get('week')) == str(week_param)
            if not cache_ok:
                 sub_name = f"підгр. {sub_raw}" if sub_raw != "all" else "Вся група"
                 week_name = "Чисельник" if week_raw == "chys" else ("Знаменник" if week_raw == "znam" else "Всі тижні")
                 await load_schedule_and_show_days(query, group, sub_param, sub_name, week_param, week_name, retry=True)
                 return

            keyboard = []
            row = []
            for day_name in TARGET_DAYS:
                if day_name in cache['data']:
                    short = DAY_SHORT_NAMES.get(day_name, day_name)
                    callback = f"fd_{day_name[:2]}_{group}_{sub_raw}_{week_raw}"
                    row.append(InlineKeyboardButton(short, callback_data=callback))
                if len(row) == 3:
                    keyboard.append(row)
                    row = []
            if row: keyboard.append(row)
            
            keyboard.append([InlineKeyboardButton("🔙 Змінити тиждень", callback_data=f"back_to_weeks_{sub_raw}_{group}")])
            
            await query.edit_message_text("📅 Оберіть день:", reply_markup=InlineKeyboardMarkup(keyboard))
        except Exception as e:
             logger.error(e)
             await query.edit_message_text("Error back days")
        return

    if data.startswith("back_to_weeks_"):
        try:
            parts = data.split("_")
            sub_choice = parts[3]
            group = parts[4]
            
            keyboard = [
                [InlineKeyboardButton("numerator (Чисельник)", callback_data=f"week_chys_{sub_choice}_{group}")],
                [InlineKeyboardButton("denominator (Знаменник)", callback_data=f"week_znam_{sub_choice}_{group}")],
                [InlineKeyboardButton("Всі тижні", callback_data=f"week_all_{sub_choice}_{group}")]
            ]
            keyboard.append([InlineKeyboardButton("🔙 Змінити підгрупу", callback_data=f"back_to_subs_{group}")])
            await query.edit_message_text("📅 Оберіть тиждень:", reply_markup=InlineKeyboardMarkup(keyboard))
        except Exception as e: logger.error(e)
        return

    if data.startswith("back_to_subs_"):
        group = data.split("_")[3]
        await query.edit_message_text(subgroup_text(group), reply_markup=subgroup_keyboard(group), parse_mode='HTML')

# --- ЗБІРКА ЗАСТОСУНКУ ---
def build_application(token):
    db_init()
    application = Application.builder().token(token).build()

    # Додаємо хендлери
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("rozklad", get_rozklad))
    application.add_handler(CommandHandler("info", info))
    application.add_handler(CommandHandler("support", support))
    application.add_handler(CallbackQueryHandler(button_handler))
    # Будь-який звичайний текст (не команда) сприймаємо як назву групи
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, group_text_handler))
    return application

# --- FIX: РУЧНИЙ ЗАПУСК БОТА (залишено для сумісності) ---
async def start_bot_manual():
    TELEGRAM_TOKEN = os.environ.get('TELEGRAM_TOKEN')
    if not TELEGRAM_TOKEN:
        logger.error("❌ NO TOKEN")
        return

    application = build_application(TELEGRAM_TOKEN)

    # Ручна ініціалізація та запуск
    await application.initialize()
    await application.start()
    await application.updater.start_polling() # Запускаємо отримання оновлень

    logger.info("🚀 Бот успішно запущено (Manual Mode)!")

# --- ТОЧКА ВХОДУ (запуск на сервері: python bot.py) ---
def run_web_server():
    # Хостинги типу Render/Railway задають PORT і чекають, що застосунок слухає цей порт.
    # Також /health можна пінгувати (UptimeRobot), щоб безкоштовний сервіс не "засинав".
    port = int(os.environ.get("PORT", "8080"))
    logging.getLogger("werkzeug").setLevel(logging.WARNING)
    app.run(host="0.0.0.0", port=port, use_reloader=False)

if __name__ == "__main__":
    token = os.environ.get("TELEGRAM_TOKEN")
    if not token:
        raise SystemExit("❌ Не задано змінну середовища TELEGRAM_TOKEN")

    # Flask запускаємо лише якщо хостинг дав PORT (на VPS/локально він не потрібен)
    if os.environ.get("PORT"):
        threading.Thread(target=run_web_server, daemon=True).start()

    application = build_application(token)
    logger.info("🚀 Бот запускається...")
    # run_polling блокує процес, сам обробляє SIGTERM/SIGINT і тримає бота живим
    application.run_polling(drop_pending_updates=True)
