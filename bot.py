import logging
import os
import threading
import asyncio
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, ContextTypes, CallbackQueryHandler
from parser import fetch_schedule_dict

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

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    text = (
        "👋 <b>Привіт! Я бот розкладу ЛП.</b>\n\n"
        "Введіть команду:\n"
        "👉 <code>/rozklad АВ-11</code>\n"
        "🛠 /support - підтримка"
    )
    await update.message.reply_text(text, parse_mode='HTML')

async def get_rozklad(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update.effective_chat.id
    args = context.args
    group = "АВ-11"
    if len(args) > 0: group = args[0]
    
    USER_GROUPS[chat_id] = group

    # Крок 1: Підгрупа
    keyboard = [
        [InlineKeyboardButton("👤 1 підгрупа", callback_data=f"sub_1_{group}"),
         InlineKeyboardButton("👤 2 підгрупа", callback_data=f"sub_2_{group}")],
        [InlineKeyboardButton("👥 Вся група", callback_data=f"sub_all_{group}")]
    ]
    await update.message.reply_text(f"🎓 Група: <b>{group}</b>\nОберіть підгрупу:", reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='HTML')

async def info(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text("ℹ️ Дані з student.lpnu.ua")

async def support(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text("🛠 Підтримка: <code>4441111131351441</code>", parse_mode='HTML')

# --- ЗАВАНТАЖЕННЯ ТА ПОКАЗ ДНІВ ---
async def load_schedule_and_show_days(query, group, sub_param, sub_name, week_param, week_name, retry=False):
    chat_id = query.message.chat_id
    if not retry:
        await query.edit_message_text(f"⏳ Отримую розклад: <b>{group}</b>, {sub_name}, {week_name}...", parse_mode='HTML')
        
    try:
        loop = asyncio.get_running_loop()
        # ПЕРЕДАЄМО week_filter у парсер
        schedule_data = await loop.run_in_executor(None, fetch_schedule_dict, group, "1", "1", sub_param, week_param)
        
        if not schedule_data or "Info" in schedule_data:
            msg = schedule_data.get("Info", "❌ Помилка.") if schedule_data else "❌ Помилка."
            await query.edit_message_text(msg, parse_mode='HTML')
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
                # Callback: fetch_day_День_Група_Підгрупа_Тиждень
                callback = f"fd_{day_name[:2]}_{group}_{sub_param}_{week_param}" # Скорочуємо, щоб влізло в ліміт Telegram (64 байти)
                row.append(InlineKeyboardButton(short, callback_data=callback))
            if len(row) == 3:
                keyboard.append(row)
                row = []
        if row: keyboard.append(row)
        keyboard.append([InlineKeyboardButton("🔙 Змінити параметри", callback_data="restart")])

        await query.edit_message_text(
            f"✅ <b>{group}</b> ({sub_name}, {week_name})\nОберіть день:",
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode='HTML'
        )
    except Exception as e:
        logger.error(f"Error: {e}")
        await query.edit_message_text("❌ Помилка.", parse_mode='HTML')

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    chat_id = query.message.chat_id
    data = query.data
    await query.answer()

    # 1. ОБРАНО ПІДГРУПУ -> ПОКАЗУЄМО ТИЖНІ
    if data.startswith("sub_"):
        try:
            _, sub_choice, group = data.split("_", 2)
            
            # Крок 2: Кнопки Тижнів
            keyboard = [
                [InlineKeyboardButton("numerator (Чисельник)", callback_data=f"week_chys_{sub_choice}_{group}")],
                [InlineKeyboardButton("denominator (Знаменник)", callback_data=f"week_znam_{sub_choice}_{group}")],
                [InlineKeyboardButton("Всі тижні", callback_data=f"week_all_{sub_choice}_{group}")]
            ]
            await query.edit_message_text("📅 Оберіть тиждень:", reply_markup=InlineKeyboardMarkup(keyboard))
        except ValueError: await query.edit_message_text("⚠️ Помилка.")
        return

    # 2. ОБРАНО ТИЖДЕНЬ -> ЗАВАНТАЖЕННЯ
    if data.startswith("week_"):
        try:
            # week_chys_1_AB-11
            parts = data.split("_")
            week_choice = parts[1] # chys, znam, all
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

    # 3. ОБРАНО ДЕНЬ (fd_Пн_АВ-11_1_chys)
    if data.startswith("fd_"):
        try:
            parts = data.split("_")
            day_short = parts[1]
            group = parts[2]
            sub_param = parts[3]
            week_param = parts[4]

            # Відновлюємо повну назву дня
            day_full = next((k for k, v in DAY_SHORT_NAMES.items() if v == day_short), None)
            
            cache = SCHEDULE_CACHE.get(chat_id)
            # Перевірка кешу
            if cache and cache.get('group') == group and str(cache.get('sub')) == str(sub_param if sub_param != 'None' else None) and str(cache.get('week')) == str(week_param if week_param != 'None' else None):
                text = cache['data'].get(day_full, "Немає пар.")
                kb = [[InlineKeyboardButton("🔙 До днів тижня", callback_data="back_to_days")]]
                await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(kb), parse_mode='HTML')
                return
            
            # Якщо кешу немає - перезавантаження
            sub_name = f"підгр. {sub_param}" if sub_param != "None" else "Вся група"
            week_name = "Чисельник" if week_param == "chys" else ("Знаменник" if week_param == "znam" else "Всі тижні")
            
            await query.edit_message_text(f"⚠️ Оновлюю...", parse_mode='HTML')
            await load_schedule_and_show_days(query, group, sub_param if sub_param != "None" else None, sub_name, week_param if week_param != "None" else None, week_name, retry=True)

        except Exception as e:
            logger.error(e)
            await query.edit_message_text("⚠️ Помилка даних.")
        return

    if data == "back_to_days":
        cache = SCHEDULE_CACHE.get(chat_id)
        if not cache:
            await query.edit_message_text("⚠️ Введіть /rozklad.", parse_mode='HTML')
            return
        
        # Малюємо дні з кешу
        keyboard = []
        row = []
        grp = cache['group']
        sb = str(cache['sub']) # None стає "None"
        wk = str(cache['week'])
        
        for day_name in TARGET_DAYS:
            if day_name in cache['data']:
                short = DAY_SHORT_NAMES.get(day_name, day_name)
                callback = f"fd_{short}_{grp}_{sb}_{wk}"
                row.append(InlineKeyboardButton(short, callback_data=callback))
            if len(row) == 3:
                keyboard.append(row)
                row = []
        if row: keyboard.append(row)
        keyboard.append([InlineKeyboardButton("🔙 Змінити параметри", callback_data="restart")])
        await query.edit_message_text("📅 Оберіть день:", reply_markup=InlineKeyboardMarkup(keyboard))
        return

    if data == "restart":
        group = USER_GROUPS.get(chat_id, "АВ-11")
        kb = [
            [InlineKeyboardButton("👤 1 підгрупа", callback_data=f"sub_1_{group}"),
             InlineKeyboardButton("👤 2 підгрупа", callback_data=f"sub_2_{group}")],
            [InlineKeyboardButton("👥 Вся група", callback_data=f"sub_all_{group}")]
        ]
        await query.edit_message_text(f"🎓 Група: <b>{group}</b>\nОберіть підгрупу:", reply_markup=InlineKeyboardMarkup(kb), parse_mode='HTML')

def run_bot():
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    TELEGRAM_TOKEN = os.environ.get('TELEGRAM_TOKEN')
    if not TELEGRAM_TOKEN: return
    try:
        app = Application.builder().token(TELEGRAM_TOKEN).build()
        app.add_handler(CommandHandler("start", start))
        app.add_handler(CommandHandler("rozklad", get_rozklad))
        app.add_handler(CommandHandler("info", info))
        app.add_handler(CommandHandler("support", support))
        app.add_handler(CallbackQueryHandler(button_handler))
        loop.run_until_complete(app.run_polling(stop_signals=None))
    except Exception as e: logger.error(f"Bot crashed: {e}")
    finally: loop.close()

if __name__ == '__main__':
    bot_thread = threading.Thread(target=run_bot)
    bot_thread.daemon = True
    bot_thread.start()
    port = int(os.environ.get("PORT", 5000))
    app.run(host='0.0.0.0', port=port, debug=False)

