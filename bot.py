import logging
import os
import threading
from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes
from parser import fetch_schedule_data

# --- 1. НАЛАШТУВАННЯ ВЕБ-СЕРВЕРА (FLASK) ---
# Це потрібно, щоб обдурити Render. Він думає, що ми запускаємо сайт.
from flask import Flask

app = Flask(__name__)

@app.route('/')
def health_check():
    return "Бот працює! (Web server is alive)"

@app.route('/health')
def health():
    return "OK"

# -------------------------------------------

# Налаштування логування
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# --- ФУНКЦІЇ БОТА (Ті самі, що й раніше) ---

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_name = update.effective_user.first_name
    await update.message.reply_text(f'Привіт, {user_name}! Надішли /rozklad, щоб отримати розклад для АВ-11.')

async def get_rozklad(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update.effective_chat.id
    logger.info(f"Користувач {chat_id} запросив розклад.")
    await update.message.reply_text('Шукаю розклад для групи АВ-11... ⏳')
    try:
        rozklad_text = fetch_schedule_data(group_name="АВ-11", semester="1", duration="1")
        await update.message.reply_text(rozklad_text)
        logger.info(f"Надіслано розклад для {chat_id}.")
    except Exception as e:
        logger.error(f"Помилка при отриманні розкладу: {e}")
        await update.message.reply_text('Ой, сталася помилка. Не можу отримати розклад. 😢')

async def info(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    info_text = (
        "Я бот, створений для парсингу розкладу.\n"
        "Зараз я вмію:\n"
        "/start - привітатися\n"
        "/rozklad - показати розклад для АВ-11\n"
        "/info - показати це повідомлення\n"
        "/support - підтримка автора\n"
    )
    await update.message.reply_text(info_text)

async def support(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text('підтримка 4441111131351441')

# --- ФУНКЦІЯ ЗАПУСКУ БОТА ---
def run_bot():
    """Ця функція запускає бота в окремому потоці"""
    TELEGRAM_TOKEN = os.environ.get('TELEGRAM_TOKEN')
    
    if not TELEGRAM_TOKEN:
        logger.error("ПОМИЛКА: Не знайдено TELEGRAM_TOKEN!")
        return

    application = Application.builder().token(TELEGRAM_TOKEN).build()

    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("rozklad", get_rozklad))
    application.add_handler(CommandHandler("info", info))
    application.add_handler(CommandHandler("support", support))

    logger.info("Запускаю Telegram бота...")
    # loop = asyncio.new_event_loop()
    # asyncio.set_event_loop(loop)
    application.run_polling()

# --- ГОЛОВНИЙ ЗАПУСК ---
if __name__ == '__main__':
    # 1. Запускаємо бота в окремому потоці ("паралельно")
    bot_thread = threading.Thread(target=run_bot)
    bot_thread.start()

    # 2. Запускаємо веб-сервер Flask (це тримає Render активним)
    # Render сам видає порт через змінну оточення PORT
    port = int(os.environ.get("PORT", 5000))
    logger.info(f"Запускаю веб-сервер на порті {port}...")
    
    # host='0.0.0.0' означає "слухати весь інтернет", це обов'язково для Render
    app.run(host='0.0.0.0', port=port)
