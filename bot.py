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
SCHEDULE_CACHE = {} # Запам'ятовує завантажений розклад: {chat_id: {'params': {...}, 'data': {...}}}

# --- НАЛАШТУВАННЯ ДНІВ ---
TARGET_DAYS = ["Понеділок", "Вівторок", "Середа", "Четвер", "П'ятниця"]
DAY_SHORT_NAMES = {
    "Понеділок": "Пн", "Вівторок": "Вт", "Середа": "Ср", "Четвер": "Чт", "П'ятниця": "Пт"
}
# --- КОМАНДИ ---

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    text = (
        "👋 *Привіт! Я бот розкладу ЛП.*\n\n"
        "Ось що я вмію:\n"
        "📅 `/rozklad [група]` - отримати розклад\n"
        "ℹ️ `/info` - інформація про бота\n"
        "🛠 `/support` - підтримка"
    )
    await update.message.reply_text(text, parse_mode='Markdown')

async def get_rozklad(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update.effective_chat.id
    args = context.args
    
    group = "АВ-11" # Група за замовчуванням
    if len(args) > 0:
        group = args[0]
    
    USER_GROUPS[chat_id] = group

    # Крок 1: Показуємо кнопки підгруп
    keyboard = [
        [
            InlineKeyboardButton("👤 1 підгрупа", callback_data=f"sub_1_{group}"),
            InlineKeyboardButton("👤 2 підгрупа", callback_data=f"sub_2_{group}")
        ],
        [InlineKeyboardButton("👥 Вся група", callback_data=f"sub_all_{group}")]
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

# --- ОСНОВНА ЛОГІКА КНОПОК ---

async def load_schedule_and_show_days(query, group, subgroup_param, subgroup_name, retry=False):
    """Виконує парсинг і показує меню днів тижня."""
    
    chat_id = query.message.chat_id
    
    if not retry:
        # Редагуємо повідомлення на "Завантаження"
        await query.edit_message_text(f"⏳ Отримую розклад для **{group}** ({subgroup_name})...", parse_mode='Markdown')
        
    try:
        loop = asyncio.get_running_loop()
        schedule_data = await loop.run_in_executor(None, fetch_schedule_dict, group, "1", "1", subgroup_param)
        
        if not schedule_data or "Info" in schedule_data:
            msg = schedule_data.get("Info", "❌ Помилка з'єднання.") if schedule_data else "❌ Помилка з'єднання."
            await query.edit_message_text(msg, parse_mode='Markdown')
            return

        # Зберігаємо дані в кеш
        SCHEDULE_CACHE[chat_id] = {
            'data': schedule_data,
            'group': group,
            'subgroup_param': subgroup_param,
            'subgroup_name': subgroup_name
        }

        # Генеруємо кнопки днів (динамічно, тільки ті дні, що є)
        keyboard = []
        row = []
        
        for day_name in TARGET_DAYS:
            if day_name in schedule_data:
                short_name = DAY_SHORT_NAMES.get(day_name, day_name)
                # КРИТИЧНО: Тепер кнопка містить всі параметри
                callback_data = f"fetch_day_{day_name}_{group}_{subgroup_param}"
                row.append(InlineKeyboardButton(short_name, callback_data=callback_data))
            
            if len(row) == 3:
                keyboard.append(row)
                row = []
        if row: keyboard.append(row)
        
        keyboard.append([InlineKeyboardButton("🔙 Змінити підгрупу", callback_data="back_to_subs")])

        await query.edit_message_text(
            f"✅ Розклад для **{group}** ({subgroup_name}) готовий!\nОберіть день:",
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode='Markdown'
        )

    except Exception as e:
        logger.error(f"Error fetching schedule: {e}")
        await query.edit_message_text("❌ Сталася помилка при завантаженні.")

# --- ОБРОБНИК КНОПОК ---

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    chat_id = query.message.chat_id
    data = query.data
    await query.answer()

    # 1. ОБРАНО ПІДГРУПУ (sub_1_АВ-11)
    if data.startswith("sub_"):
        try:
            # Парсинг даних: sub_1_АВ-11
            _, sub_choice, group = data.split("_", 2)
            
            subgroup_param = None
            subgroup_name = f"підгр. {sub_choice}"
            if sub_choice == "all":
                subgroup_name = "Вся група"

            if sub_choice in ["1", "2"]:
                subgroup_param = sub_choice
            
            await load_schedule_and_show_days(query, group, subgroup_param, subgroup_name)

        except ValueError:
            await query.edit_message_text("⚠️ Некоректний формат даних.")
        return

    # 2. ОБРАНО ДЕНЬ (fetch_day_Понеділок_АВ-11_1)
    if data.startswith("fetch_day_"):
        try:
            # Парсинг даних: fetch_day_Понеділок_АВ-11_1
            _, _, day_name, group, subgroup_param = data.split("_")
            
            # --- КРОК А: Перевірка кешу ---
            cache_entry = SCHEDULE_CACHE.get(chat_id)
            
            if cache_entry and cache_entry.get('group') == group and cache_entry.get('subgroup_param') == subgroup_param:
                # Дані в кеші актуальні: просто показуємо текст
                schedule_text = cache_entry['data'].get(day_name, "Немає пар.")
                
                keyboard = [[InlineKeyboardButton("🔙 До днів тижня", callback_data="back_to_days")]]
                await query.edit_message_text(schedule_text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='Markdown')
                return

            # --- КРОК Б: Кеш застарів/відсутній. ПЕРЕЗАВАНТАЖЕННЯ ---
            
            # Визначаємо назву підгрупи для відображення
            subgroup_name = f"підгр. {subgroup_param}" if subgroup_param != "None" else "Вся група"
            
            await query.edit_message_text(
                f"⚠️ Дані застаріли. Автоматично оновлюю розклад для **{group}** ({subgroup_name})...", 
                parse_mode='Markdown'
            )
            
            # Запускаємо повне завантаження з параметрами з кнопки
            await load_schedule_and_show_days(query, group, subgroup_param if subgroup_param != "None" else None, subgroup_name, retry=True)

        except ValueError:
            await query.edit_message_text("⚠️ Некоректний формат даних для дня.")
        return

    # 3. НАЗАД ДО ДНІВ
    if data == "back_to_days":
        cache_entry = SCHEDULE_CACHE.get(chat_id)
        if not cache_entry:
            await query.edit_message_text("⚠️ Дані застаріли. Введіть /rozklad знову.")
            return

        # Відновлюємо меню днів
        keyboard = []
        row = []
        for day_name in TARGET_DAYS:
            if day_name in cache_entry['data']:
                short_name = DAY_SHORT_NAMES.get(day_name, day_name)
                # Беремо параметри з кешу для створення кнопки
                group = cache_entry['group']
                subgroup_param = cache_entry['subgroup_param']
                callback_data = f"fetch_day_{day_name}_{group}_{subgroup_param}"
                
                row.append(InlineKeyboardButton(short_name, callback_data=callback_data))
                if len(row) == 3:
                    keyboard.append(row)
                    row = []
        if row: keyboard.append(row)
        keyboard.append([InlineKeyboardButton("🔙 Змінити підгрупу", callback_data="back_to_subs")])
        
        await query.edit_message_text("📅 Оберіть день:", reply_markup=InlineKeyboardMarkup(keyboard))
        return

    # 4. НАЗАД ДО ПІДГРУП
    if data == "back_to_subs":
        group = USER_GROUPS.get(chat_id, "АВ-11")
        keyboard = [
            [InlineKeyboardButton("👤 1 підгрупа", callback_data=f"sub_1_{group}"),
             InlineKeyboardButton("👤 2 підгрупа", callback_data=f"sub_2_{group}")],
            [InlineKeyboardButton("👥 Вся група", callback_data=f"sub_all_{group}")]
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

