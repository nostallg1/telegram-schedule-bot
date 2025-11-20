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

# --- КОМАНДИ ---

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    text = (
        "👋 <b>Привіт! Я бот розкладу ЛП.</b>\n\n"
        "Щоб почати, введіть команду:\n"
        "👉 <code>/rozklad АВ-11</code>\n"
        "👉 <code>/rozklad КН-101</code>\n\n"
        "ℹ️ /info - про бота\n"
        "🛠 /support - підтримка"
    )
    # ТУТ І ДАЛІ ВИКОРИСТОВУЄМО HTML
    await update.message.reply_text(text, parse_mode='HTML')

async def get_rozklad(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update.effective_chat.id
    args = context.args
    group = "АВ-11"
    if len(args) > 0: group = args[0]
    
    USER_GROUPS[chat_id] = group

    keyboard = [
        [InlineKeyboardButton("👤 1 підгрупа", callback_data=f"sub_1_{group}"),
         InlineKeyboardButton("👤 2 підгрупа", callback_data=f"sub_2_{group}")],
        [InlineKeyboardButton("👥 Вся група", callback_data=f"sub_all_{group}")]
    ]
    
    await update.message.reply_text(
        f"🎓 Група: <b>{group}</b>\nОберіть підгрупу:",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode='HTML'
    )

async def info(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text("ℹ️ Бот парсить дані з student.lpnu.ua")

async def support(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text("🛠 Підтримка: <code>4441111131351441</code>", parse_mode='HTML')

# --- КНОПКИ ---

async def load_schedule_and_show_days(query, group, subgroup_param, subgroup_name, retry=False):
    chat_id = query.message.chat_id
    if not retry:
        await query.edit_message_text(f"⏳ Отримую розклад для <b>{group}</b> ({subgroup_name})...", parse_mode='HTML')
        
    try:
        loop = asyncio.get_running_loop()
        schedule_data = await loop.run_in_executor(None, fetch_schedule_dict, group, "1", "1", subgroup_param)
        
        if not schedule_data or "Info" in schedule_data:
            msg = schedule_data.get("Info", "❌ Помилка з'єднання.") if schedule_data else "❌ Помилка."
            await query.edit_message_text(msg, parse_mode='HTML')
            return

        SCHEDULE_CACHE[chat_id] = {
            'data': schedule_data, 'group': group, 
            'subgroup_param': subgroup_param, 'subgroup_name': subgroup_name
        }

        keyboard = []
        row = []
        for day_name in TARGET_DAYS:
            if day_name in schedule_data:
                short = DAY_SHORT_NAMES.get(day_name, day_name)
                callback = f"fetch_day_{day_name}_{group}_{subgroup_param}"
                row.append(InlineKeyboardButton(short, callback_data=callback))
            if len(row) == 3:
                keyboard.append(row)
                row = []
        if row: keyboard.append(row)
        keyboard.append([InlineKeyboardButton("🔙 Змінити підгрупу", callback_data="back_to_subs")])

        if not keyboard or (len(keyboard) == 1):
             await query.edit_message_text(f"📭 Розклад для <b>{group}</b> ({subgroup_name}) на будні дні порожній.", parse_mode='HTML')
             return

        await query.edit_message_text(
            f"✅ Розклад для <b>{group}</b> ({subgroup_name}) готовий!\nОберіть день:",
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode='HTML'
        )
    except Exception as e:
        logger.error(f"Error: {e}")
        await query.edit_message_text("❌ Сталася помилка при завантаженні.")

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    chat_id = query.message.chat_id
    data = query.data
    await query.answer()

    if data.startswith("sub_"):
        try:
            _, sub_choice, group = data.split("_", 2)
            sub_param = sub_choice if sub_choice in ["1", "2"] else None
            sub_name = f"підгр. {sub_choice}" if sub_choice != "all" else "Вся група"
            await load_schedule_and_show_days(query, group, sub_param, sub_name)
        except ValueError: await query.edit_message_text("⚠️ Помилка даних.")
        return

    if data.startswith("fetch_day_"):
        try:
            _, _, day_name, group, sub_param = data.split("_")
            
            cache = SCHEDULE_CACHE.get(chat_id)
            if cache and cache.get('group') == group and cache.get('subgroup_param') == sub_param:
                text = cache['data'].get(day_name, "Немає пар.")
                kb = [[InlineKeyboardButton("🔙 До днів тижня", callback_data="back_to_days")]]
                await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(kb), parse_mode='HTML')
                return

            sub_name = f"підгр. {sub_param}" if sub_param != "None" else "Вся група"
            await query.edit_message_text(f"⚠️ Оновлюю розклад для <b>{group}</b>...", parse_mode='HTML')
            await load_schedule_and_show_days(query, group, sub_param if sub_param != "None" else None, sub_name, retry=True)
        except ValueError: await query.edit_message_text("⚠️ Помилка даних.")
        return

    if data == "back_to_days":
        cache = SCHEDULE_CACHE.get(chat_id)
        if not cache:
            await query.edit_message_text("⚠️ Дані застаріли. Введіть /rozklad.", parse_mode='HTML')
            return

        keyboard = []
        row = []
        for day_name in TARGET_DAYS:
            if day_name in cache['data']:
                short = DAY_SHORT_NAMES.get(day_name, day_name)
                grp = cache['group']
                sb = cache['subgroup_param']
                row.append(InlineKeyboardButton(short, callback_data=f"fetch_day_{day_name}_{grp}_{sb}"))
                if len(row) == 3:
                    keyboard.append(row)
                    row = []
        if row: keyboard.append(row)
        keyboard.append([InlineKeyboardButton("🔙 Змінити підгрупу", callback_data="back_to_subs")])
        
        await query.edit_message_text("📅 Оберіть день:", reply_markup=InlineKeyboardMarkup(keyboard))
        return

    if data == "back_to_subs":
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


