import logging
import os
import threading
import asyncio
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, ContextTypes, CallbackQueryHandler
from parser import fetch_schedule_dict

# --- FLASK (для Render) ---
from flask import Flask
app = Flask(__name__)

@app.route('/')
def health_check(): return "Bot alive!"
@app.route('/health')
def health(): return "OK"
# ---------------------------

logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# --- ПАМ'ЯТЬ БОТА ---
# Зберігає вибір користувача: {chat_id: "АВ-11"}
USER_GROUPS = {} 
# Зберігає завантажений розклад: {chat_id: {'Понеділок': '...', ...}}
SCHEDULE_CACHE = {}

# --- ФУНКЦІЇ ---

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(
        '👋 Привіт! Я бот-розклад.\n\n'
        '✍️ Введіть команду та групу:\n'
        '`/rozklad АВ-11`\n'
        'або будь-яку іншу (напр. КН-101)',
        parse_mode='Markdown'
    )

async def get_rozklad(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update.effective_chat.id
    args = context.args
    
    # Визначаємо групу
    group = "АВ-11" # Значення за замовчуванням
    if len(args) > 0:
        group = args[0]
    
    # Запам'ятовуємо, яку групу шукає цей користувач
    USER_GROUPS[chat_id] = group

    # Показуємо кнопки вибору підгрупи
    keyboard = [
        [
            InlineKeyboardButton("👤 1 підгрупа", callback_data="subgroup_1"),
            InlineKeyboardButton("👤 2 підгрупа", callback_data="subgroup_2")
        ],
        [InlineKeyboardButton("👥 Вся група", callback_data="subgroup_all")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    await update.message.reply_text(
        f"Ви обрали групу: **{group}**\nОберіть підгрупу:", 
        reply_markup=reply_markup, 
        parse_mode='Markdown'
    )

# --- ОБРОБКА НАТИСКАННЯ КНОПОК ---
async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    chat_id = query.message.chat_id
    data = query.data

    # 1. ОБРОБКА ВИБОРУ ПІДГРУПИ
    if data.startswith("subgroup_"):
        await query.answer("Завантажую...") # Показує "годинник"
        
        # Отримуємо збережену групу
        group = USER_GROUPS.get(chat_id, "АВ-11")
        
        # Визначаємо підгрупу
        sub_choice = data.split("_")[1] # "1", "2" або "all"
        subgroup_param = None
        sub_text = "Вся група"
        
        if sub_choice in ["1", "2"]:
            subgroup_param = sub_choice
            sub_text = f"Підгрупа {sub_choice}"

        # Редагуємо повідомлення на "Завантаження"
        await query.edit_message_text(f"⏳ Шукаю розклад для **{group}** ({sub_text})...", parse_mode='Markdown')

        # Виконуємо парсинг (у фоновому потоці, щоб не блокувати бота)
        try:
            loop = asyncio.get_running_loop()
            schedule_data = await loop.run_in_executor(None, fetch_schedule_dict, group, "1", "1", subgroup_param)
            
            if not schedule_data or "Info" in schedule_data:
                msg = schedule_data.get("Info", "❌ Помилка. Перевірте назву групи.") if schedule_data else "❌ Помилка з'єднання."
                await query.edit_message_text(msg)
                return

            # Зберігаємо результат в кеш
            SCHEDULE_CACHE[chat_id] = schedule_data

            # Малюємо кнопки днів
            keyboard = []
            row = []
            for day in schedule_data.keys():
                row.append(InlineKeyboardButton(day[:2], callback_data=f"day_{day}")) # Пн, Вт...
                if len(row) == 3:
                    keyboard.append(row)
                    row = []
            if row: keyboard.append(row)
            
            # Додаємо кнопку "Змінити підгрупу"
            keyboard.append([InlineKeyboardButton("🔙 Змінити підгрупу", callback_data="back_to_subs")])

            await query.edit_message_text(
                f"✅ Розклад для **{group}** ({sub_text}) завантажено!\nОберіть день:",
                reply_markup=InlineKeyboardMarkup(keyboard),
                parse_mode='Markdown'
            )

        except Exception as e:
            logger.error(f"Error: {e}")
            await query.edit_message_text("❌ Сталася помилка при обробці.")
        return

    # 2. ОБРОБКА ВИБОРУ ДНЯ
    if data.startswith("day_"):
        await query.answer()
        day_name = data.split("_")[1]
        
        # Беремо текст з кешу
        schedule_text = SCHEDULE_CACHE.get(chat_id, {}).get(day_name, "⚠️ Помилка кешу. Спробуйте /rozklad знову.")
        
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
        # Відновлюємо меню днів (логіка та сама, що вище)
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
        # Повертаємо меню підгруп
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
    await update.message.reply_text("Я бот для студентів ЛП.")

async def support(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text('Підтримка: 4441111131351441')

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
        app.add_handler(CallbackQueryHandler(button_handler)) # Обробник кнопок
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



