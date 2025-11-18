import logging
import os
import threading
import asyncio
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, ContextTypes, CallbackQueryHandler
from parser import fetch_schedule_dict

# --- FLASK SERVER ---
from flask import Flask
app = Flask(__name__)

@app.route('/')
def health_check(): return "Bot is running!"
@app.route('/health')
def health(): return "OK"
# --------------------

logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# --- ПАМ'ЯТЬ ---
USER_GROUPS = {}
SCHEDULE_CACHE = {}

# --- НАЛАШТУВАННЯ ДНІВ ---
# Цей список визначає порядок кнопок і те, ЯКІ дні показувати
TARGET_DAYS = ["Понеділок", "Вівторок", "Середа", "Четвер", "П'ятниця"]

# Словник для коротких назв на кнопках
DAY_SHORT_NAMES = {
    "Понеділок": "Пн",
    "Вівторок": "Вт",
    "Середа": "Ср",
    "Четвер": "Чт",
    "П'ятниця": "Пт"
}

# --- КОМАНДИ ---

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    text = (
        "👋 *Привіт! Я бот розкладу ЛП.*\n\n"
        "Щоб почати, введіть команду з назвою групи:\n"
        "👉 `/rozklad АВ-11`\n"
        "👉 `/rozklad КН-101`\n\n"
        "ℹ️ /info - про бота\n"
        "🛠 /support - підтримка"
    )
    await update.message.reply_text(text, parse_mode='Markdown')

async def get_rozklad(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update.effective_chat.id
    args = context.args
    
    group = "АВ-11"
    if len(args) > 0:
        group = args[0]
    
    USER_GROUPS[chat_id] = group

    keyboard = [
        [
            InlineKeyboardButton("👤 1 підгрупа", callback_data="sub_1"),
            InlineKeyboardButton("👤 2 підгрупа", callback_data="sub_2")
        ],
        [InlineKeyboardButton("👥 Вся група", callback_data="sub_all")]
    ]
    
    await update.message.reply_text(
        f"🎓 Група: **{group}**\nОберіть підгрупу:",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode='Markdown'
    )

async def info(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text("ℹ️ Бот парсить дані з student.lpnu.ua")

async def support(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text("🛠 Підтримка: `4441111131351441`", parse_mode='Markdown')

# --- ЛОГІКА КНОПОК ---
async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    chat_id = query.message.chat_id
    data = query.data

    # --- 1. ЗАВАНТАЖЕННЯ РОЗКЛАДУ ---
    if data.startswith("sub_"):
        await query.answer("🔍 Завантажую дані...")
        
        group = USER_GROUPS.get(chat_id, "АВ-11")
        sub_choice = data.split("_")[1]
        
        subgroup_param = None
        sub_text = "Вся група"
        if sub_choice in ["1", "2"]:
            subgroup_param = sub_choice
            sub_text = f"підгр. {sub_choice}"

        await query.edit_message_text(f"⏳ Отримую розклад для **{group}** ({sub_text})...", parse_mode='Markdown')

        try:
            loop = asyncio.get_running_loop()
            schedule_data = await loop.run_in_executor(None, fetch_schedule_dict, group, "1", "1", subgroup_param)
            
            if not schedule_data:
                await query.edit_message_text("❌ Помилка з'єднання.")
                return
            
            if "Info" in schedule_data:
                await query.edit_message_text(schedule_data["Info"], parse_mode='Markdown')
                return

            SCHEDULE_CACHE[chat_id] = schedule_data

            # --- ГЕНЕРАЦІЯ КНОПОК (ФІЛЬТРАЦІЯ Пн-Пт) ---
            keyboard = []
            row = []
            
            # Ми проходимо не по ключах словника, а по нашому списку TARGET_DAYS
            # Це гарантує порядок Пн -> Пт і відсікає суботу/неділю
            for day_name in TARGET_DAYS:
                # Перевіряємо, чи є такий день у завантажених даних
                if day_name in schedule_data:
                    short_name = DAY_SHORT_NAMES.get(day_name, day_name)
                    row.append(InlineKeyboardButton(short_name, callback_data=f"day_{day_name}"))
                else:
                    # (Опціонально) Можна додавати неактивну кнопку або просто пропускати
                    # row.append(InlineKeyboardButton("➖", callback_data="ignore"))
                    pass

                if len(row) == 3: # Максимум 3 кнопки в ряд
                    keyboard.append(row)
                    row = []
            
            if row: keyboard.append(row)
            
            keyboard.append([InlineKeyboardButton("🔙 Змінити підгрупу", callback_data="back_to_subs")])

            if not keyboard or (len(keyboard) == 1 and keyboard[0][0].text == "🔙 Змінити підгрупу"):
                 await query.edit_message_text(f"📭 Розклад для **{group}** ({sub_text}) на будні дні порожній.", parse_mode='Markdown')
                 return

            await query.edit_message_text(
                f"✅ Розклад для **{group}** ({sub_text}) готовий!\nОберіть день:",
                reply_markup=InlineKeyboardMarkup(keyboard),
                parse_mode='Markdown'
            )

        except Exception as e:
            logger.error(f"Error: {e}")
            await query.edit_message_text("❌ Сталася помилка.")
        return

    # --- 2. ПОКАЗ ПАР ---
    if data.startswith("day_"):
        await query.answer()
        day_name = data.split("_")[1]
        
        schedule_text = SCHEDULE_CACHE.get(chat_id, {}).get(day_name, "⚠️ Дані застаріли.")
        
        keyboard = [[InlineKeyboardButton("🔙 До днів тижня", callback_data="back_to_days")]]
        
        await query.edit_message_text(schedule_text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='Markdown')
        return

    # --- 3. НАЗАД ДО ДНІВ ---
    if data == "back_to_days":
        await query.answer()
        schedule_data = SCHEDULE_CACHE.get(chat_id)
        if not schedule_data:
            await query.edit_message_text("⚠️ Дані застаріли.")
            return
            
        keyboard = []
        row = []
        # Тут так само використовуємо фільтр TARGET_DAYS
        for day_name in TARGET_DAYS:
            if day_name in schedule_data:
                short_name = DAY_SHORT_NAMES.get(day_name, day_name)
                row.append(InlineKeyboardButton(short_name, callback_data=f"day_{day_name}"))
                if len(row) == 3:
                    keyboard.append(row)
                    row = []
        if row: keyboard.append(row)
        keyboard.append([InlineKeyboardButton("🔙 Змінити підгрупу", callback_data="back_to_subs")])
        
        await query.edit_message_text("📅 Оберіть день:", reply_markup=InlineKeyboardMarkup(keyboard))
        return

    # --- 4. НАЗАД ДО ПІДГРУП ---
    if data == "back_to_subs":
        await query.answer()
        group = USER_GROUPS.get(chat_id, "АВ-11")
        
        keyboard = [
            [InlineKeyboardButton("👤 1 підгрупа", callback_data="sub_1"),
             InlineKeyboardButton("👤 2 підгрупа", callback_data="sub_2")],
            [InlineKeyboardButton("👥 Вся група", callback_data="sub_all")]
        ]
        await query.edit_message_text(
            f"🎓 Група: **{group}**\nОберіть підгрупу:",
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode='Markdown'
        )

# --- RUN ---
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
    except Exception as e:
        logger.error(f"Bot crashed: {e}")
    finally:
        loop.close()

if __name__ == '__main__':
    bot_thread = threading.Thread(target=run_bot)
    bot_thread.daemon = True
    bot_thread.start()
    port = int(os.environ.get("PORT", 5000))
    app.run(host='0.0.0.0', port=port, debug=False)



