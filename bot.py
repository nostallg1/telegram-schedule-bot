import logging
import os
import threading
import asyncio
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, ContextTypes, CallbackQueryHandler
from parser import fetch_schedule_dict

# --- FLASK SERVER (Щоб Render не засинав) ---
from flask import Flask
app = Flask(__name__)

@app.route('/')
def health_check(): return "Bot is running!"
@app.route('/health')
def health(): return "OK"
# ---------------------------------------------

logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# --- ПАМ'ЯТЬ ---
USER_GROUPS = {}    # Запам'ятовує групу користувача
SCHEDULE_CACHE = {} # Запам'ятовує завантажений розклад, щоб не парсити зайвий раз

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
    
    group = "АВ-11" # Група за замовчуванням
    if len(args) > 0:
        group = args[0]
    
    # Зберігаємо групу для цього користувача
    USER_GROUPS[chat_id] = group

    # Крок 1: Показуємо кнопки підгруп
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

    # 1. ОБРАНО ПІДГРУПУ -> ЗАВАНТАЖУЄМО РОЗКЛАД
    if data.startswith("sub_"):
        await query.answer("🔍 Завантажую дані...") # Спливаюче повідомлення
        
        group = USER_GROUPS.get(chat_id, "АВ-11")
        
        # Визначаємо параметри для парсера
        sub_choice = data.split("_")[1] # "1", "2" або "all"
        subgroup_param = None
        if sub_choice in ["1", "2"]:
            subgroup_param = sub_choice
            
        sub_text = f"підгр. {sub_choice}" if sub_choice != "all" else "всі"

        await query.edit_message_text(f"⏳ Отримую розклад для **{group}** ({sub_text})...", parse_mode='Markdown')

        try:
            loop = asyncio.get_running_loop()
            # Викликаємо парсер
            schedule_data = await loop.run_in_executor(None, fetch_schedule_dict, group, "1", "1", subgroup_param)
            
            if not schedule_data:
                await query.edit_message_text("❌ Помилка з'єднання.")
                return
            
            if "Info" in schedule_data:
                # Якщо парсер повернув помилку (напр. група не знайдена)
                await query.edit_message_text(schedule_data["Info"], parse_mode='Markdown')
                return

            # Зберігаємо розклад в пам'ять, щоб швидко показувати дні
            SCHEDULE_CACHE[chat_id] = schedule_data

            # Генеруємо кнопки днів (динамічно, тільки ті дні, що є в розкладі)
            keyboard = []
            row = []
            for day_name in schedule_data.keys():
                # day_name[:2] скорочує "Понеділок" до "По"
                btn_text = day_name if len(day_name) < 4 else day_name[:3]
                row.append(InlineKeyboardButton(btn_text, callback_data=f"day_{day_name}"))
                
                if len(row) == 3: # По 3 кнопки в ряд
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
            await query.edit_message_text("❌ Сталася помилка.")
        return

    # 2. ОБРАНО ДЕНЬ -> ПОКАЗУЄМО ТЕКСТ
    if data.startswith("day_"):
        await query.answer()
        day_name = data.split("_")[1]
        
        # Дістаємо текст з кешу
        schedule_data = SCHEDULE_CACHE.get(chat_id)
        if not schedule_data:
            await query.edit_message_text("⚠️ Дані застаріли. Введіть /rozklad знову.")
            return
            
        text = schedule_data.get(day_name, "Немає пар.")
        
        # Кнопка "Назад"
        keyboard = [[InlineKeyboardButton("🔙 До днів тижня", callback_data="back_to_days")]]
        
        await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='Markdown')
        return

    # 3. КНОПКА "НАЗАД ДО ДНІВ"
    if data == "back_to_days":
        await query.answer()
        schedule_data = SCHEDULE_CACHE.get(chat_id)
        if not schedule_data:
            await query.edit_message_text("⚠️ Дані застаріли.")
            return
            
        # Відновлюємо меню днів
        keyboard = []
        row = []
        for day_name in schedule_data.keys():
            btn_text = day_name if len(day_name) < 4 else day_name[:3]
            row.append(InlineKeyboardButton(btn_text, callback_data=f"day_{day_name}"))
            if len(row) == 3:
                keyboard.append(row)
                row = []
        if row: keyboard.append(row)
        keyboard.append([InlineKeyboardButton("🔙 Змінити підгрупу", callback_data="back_to_subs")])
        
        await query.edit_message_text("📅 Оберіть день:", reply_markup=InlineKeyboardMarkup(keyboard))
        return

    # 4. КНОПКА "НАЗАД ДО ПІДГРУП"
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

# --- MAIN ---
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
        
        # Fix for Render threads
        loop.run_until_complete(app.run_polling(stop_signals=None))
    except Exception as e:
        logger.error(f"Bot Error: {e}")
    finally:
        loop.close()

if __name__ == '__main__':
    bot_thread = threading.Thread(target=run_bot)
    bot_thread.daemon = True
    bot_thread.start()
    
    port = int(os.environ.get("PORT", 5000))
    app.run(host='0.0.0.0', port=port, debug=False)


