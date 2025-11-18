import logging
import os
import threading
import asyncio
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, ContextTypes, CallbackQueryHandler
from parser import fetch_schedule_dict

# --- FLASK (для роботи на Render) ---
from flask import Flask
app = Flask(__name__)

@app.route('/')
def health_check(): return "Bot is running!"
@app.route('/health')
def health(): return "OK"
# ------------------------------------

logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# --- ПАМ'ЯТЬ БОТА ---
USER_GROUPS = {} 
SCHEDULE_CACHE = {}

# --- КОМАНДИ ---

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    # Оновлений текст привітання
    welcome_text = (
        "👋 *Привіт! Я бот для студентів ЛП.*\n\n"
        "Ось що я вмію:\n"
        "📅 `/rozklad [група]` - отримати розклад\n"
        "ℹ️ `/info` - інформація про бота\n"
        "🛠 `/support` - технічна підтримка\n\n"
        "👇 *Спробуй натиснути:* `/rozklad АВ-11`"
    )
    await update.message.reply_text(welcome_text, parse_mode='Markdown')

async def get_rozklad(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update.effective_chat.id
    args = context.args
    
    group = "АВ-11" # Дефолтна група
    if len(args) > 0:
        group = args[0]
    
    USER_GROUPS[chat_id] = group

    # Кнопки вибору підгрупи
    keyboard = [
        [
            InlineKeyboardButton("👤 1 підгрупа", callback_data="subgroup_1"),
            InlineKeyboardButton("👤 2 підгрупа", callback_data="subgroup_2")
        ],
        [InlineKeyboardButton("👥 Вся група", callback_data="subgroup_all")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    await update.message.reply_text(
        f"🔍 Ви обрали групу: **{group}**\nОберіть підгрупу:", 
        reply_markup=reply_markup, 
        parse_mode='Markdown'
    )

# --- ОБРОБКА КНОПОК ---
async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    chat_id = query.message.chat_id
    data = query.data

    # 1. КОРИСТУВАЧ ОБРАВ ПІДГРУПУ -> ВАНТАЖИМО РОЗКЛАД
    if data.startswith("subgroup_"):
        await query.answer("Завантажую...")
        
        group = USER_GROUPS.get(chat_id, "АВ-11")
        sub_choice = data.split("_")[1]
        
        subgroup_param = None
        sub_text = "Вся група"
        if sub_choice in ["1", "2"]:
            subgroup_param = sub_choice
            sub_text = f"Підгрупа {sub_choice}"

        await query.edit_message_text(f"⏳ Отримую дані з сайту для **{group}** ({sub_text})...", parse_mode='Markdown')

        try:
            loop = asyncio.get_running_loop()
            # Викликаємо новий парсер (fetch_schedule_dict)
            schedule_data = await loop.run_in_executor(None, fetch_schedule_dict, group, "1", "1", subgroup_param)
            
            # Перевірка на помилки
            if not schedule_data:
                await query.edit_message_text("❌ Помилка з'єднання з сайтом.")
                return
            
            if "Info" in schedule_data:
                await query.edit_message_text(schedule_data["Info"])
                return

            SCHEDULE_CACHE[chat_id] = schedule_data

            # Малюємо кнопки днів тижня
            keyboard = []
            row = []
            for day in schedule_data.keys():
                # day[:2] скорочує назву до 2 букв (Пн, Вт...)
                row.append(InlineKeyboardButton(day[:2], callback_data=f"day_{day}"))
                if len(row) == 3:
                    keyboard.append(row)
                    row = []
            if row: keyboard.append(row)
            
            keyboard.append([InlineKeyboardButton("🔙 Змінити підгрупу", callback_data="back_to_subs")])

            await query.edit_message_text(
                f"✅ Розклад для **{group}** ({sub_text}) готовий!\nОберіть день:",
                reply_markup=InlineKeyboardMarkup(keyboard),
                parse_mode='Markdown'
            )

        except Exception as e:
            logger.error(f"Error: {e}")
            await query.edit_message_text("❌ Сталася технічна помилка.")
        return

    # 2. КОРИСТУВАЧ ОБРАВ ДЕНЬ -> ПОКАЗУЄМО ПАРИ
    if data.startswith("day_"):
        await query.answer()
        day_name = data.split("_")[1]
        
        schedule_text = SCHEDULE_CACHE.get(chat_id, {}).get(day_name, "⚠️ Дані застаріли. Введіть /rozklad знову.")
        
        keyboard = [[InlineKeyboardButton("🔙 Назад до днів", callback_data="back_to_days")]]
        
        await query.edit_message_text(
            schedule_text,
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode='Markdown'
        )
        return

    # 3. КНОПКИ "НАЗАД"
    if data == "back_to_days":
        await query.answer()
        schedule_data = SCHEDULE_CACHE.get(chat_id)
        if not schedule_data:
            await query.edit_message_text("⚠️ Дані застаріли. Введіть /rozklad знову.")
            return

        keyboard = []
        row = []
        for day in schedule_data.keys():
            row.append(InlineKeyboardButton(day[:2], callback_data=f"day_{day}"))
            if len(row) == 3:
                keyboard.append(row)
                row = []
        if row: keyboard.append(row)
        keyboard.append([InlineKeyboardButton("🔙 Змінити підгрупу", callback_data="back_to_subs")])
        
        await query.edit_message_text("📅 Оберіть день:", reply_markup=InlineKeyboardMarkup(keyboard))
        return

    if data == "back_to_subs":
        await query.answer()
        group = USER_GROUPS.get(chat_id, "АВ-11")
        keyboard = [
            [InlineKeyboardButton("👤 1 підгрупа", callback_data="subgroup_1"),
             InlineKeyboardButton("👤 2 підгрупа", callback_data="subgroup_2")],
            [InlineKeyboardButton("👥 Вся група", callback_data="subgroup_all")]
        ]
        await query.edit_message_text(
            f"Ви обрали групу: **{group}**\nОберіть підгрупу:", 
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode='Markdown'
        )

async def info(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(
        "ℹ️ **Інформація про бота**\n\n"
        "Цей бот створений для зручного перегляду розкладу НУ 'Львівська Політехніка'.\n"
        "Дані беруться безпосередньо з сайту student.lpnu.ua.\n\n"
        "Версія: 2.0 (Design Update) 🚀",
        parse_mode='Markdown'
    )

async def support(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text('📞 Підтримка: `4441111131351441`', parse_mode='Markdown')

# --- ЗАПУСК (З FIX ДЛЯ RENDER) ---
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
        
        # ВАЖЛИВО: stop_signals=None
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



