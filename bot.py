import logging
import os
import threading
import asyncio
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, ContextTypes, CallbackQueryHandler
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

USER_GROUPS = {} 
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

# --- КОМАНДИ ---
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    text = "👋 <b>Привіт! Я бот розкладу ЛП.</b>\n\nВведіть команду:\n👉 <code>/rozklad АВ-11</code>\n🛠 /support - підтримка"
    await update.message.reply_text(text, parse_mode='HTML')

async def get_rozklad(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update.effective_chat.id
    args = context.args
    group = "АВ-11"
    if len(args) > 0:
        group = fix_layout(args[0])
    
    USER_GROUPS[chat_id] = group

    keyboard = [
        [InlineKeyboardButton("👤 1 підгрупа", callback_data=f"sub_1_{group}"),
         InlineKeyboardButton("👤 2 підгрупа", callback_data=f"sub_2_{group}")],
        [InlineKeyboardButton("👥 Вся група", callback_data=f"sub_all_{group}")]
    ]
    await update.message.reply_text(f"🎓 Група: <b>{group}</b>\nОберіть підгрупу:", reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='HTML')

async def info(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text("ℹ️ Бот парсить дані з student.lpnu.ua")

async def support(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text("🛠 Підтримка: <code>4441111131351441</code>", parse_mode='HTML')

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
        
        keyboard.append([InlineKeyboardButton("🔙 Змінити тиждень", callback_data=f"back_to_weeks_{sub_param}_{group}")])

        if not keyboard or (len(keyboard) == 1):
             await query.edit_message_text(f"📭 Розклад для <b>{group}</b> ({sub_name}, {week_name}) порожній.", parse_mode='HTML')
             return

        await query.edit_message_text(
            f"✅ <b>{group}</b> ({sub_name}, {week_name})\nОберіть день:",
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

    if data == "restart_full":
        await query.edit_message_text("Введіть команду `/rozklad ГРУПА` ще раз.", parse_mode='Markdown')
        return

    if data.startswith("sub_"):
        try:
            _, sub_choice, group = data.split("_", 2)
            keyboard = [
                [InlineKeyboardButton("numerator (Чисельник)", callback_data=f"week_chys_{sub_choice}_{group}")],
                [InlineKeyboardButton("denominator (Знаменник)", callback_data=f"week_znam_{sub_choice}_{group}")],
                [InlineKeyboardButton("Всі тижні", callback_data=f"week_all_{sub_choice}_{group}")]
            ]
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
            day_full = next((k for k, v in DAY_SHORT_NAMES.items() if v == day_short), None)
            
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
            logger.error(f"FD Error: {e}")
            await query.edit_message_text("⚠️ Помилка даних.")
        return

    if data.startswith("back_days_"):
        try:
            parts = data.split("_")
            group = parts[2]
            sub_raw = parts[3]
            week_raw = parts[4]
            
            cache = SCHEDULE_CACHE.get(chat_id)
            if not cache:
                 sub_param = sub_raw if sub_raw != "all" else None
                 sub_name = f"підгр. {sub_raw}" if sub_raw != "all" else "Вся група"
                 week_param = week_raw if week_raw != "all" else None
                 week_name = "Тиждень"
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
        kb = [
            [InlineKeyboardButton("👤 1 підгрупа", callback_data=f"sub_1_{group}"),
             InlineKeyboardButton("👤 2 підгрупа", callback_data=f"sub_2_{group}")],
            [InlineKeyboardButton("👥 Вся група", callback_data=f"sub_all_{group}")]
        ]
        await query.edit_message_text(f"🎓 Група: <b>{group}</b>\nОберіть підгрупу:", reply_markup=InlineKeyboardMarkup(kb), parse_mode='HTML')

# --- FIX: РУЧНИЙ ЗАПУСК БОТА ---
async def start_bot_manual():
    TELEGRAM_TOKEN = os.environ.get('TELEGRAM_TOKEN')
    if not TELEGRAM_TOKEN:
        logger.error("❌ NO TOKEN")
        return

    application = Application.builder().token(TELEGRAM_TOKEN).build()
    
    # Додаємо хендлери
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("rozklad", get_rozklad))
    application.add_handler(CommandHandler("info", info))
    application.add_handler(CommandHandler("support", support))
    application.add_handler(CallbackQueryHandler(button_handler))

    # Ручна ініціалізація та запуск
    await application.initialize()
    await application.start()
    await application.updater.start_polling() # Запускаємо отримання оновлень
    
    logger.info("🚀 Бот успішно запущено (Manual Mode)!")
