import logging
import os
import threading
import asyncio
from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes
from parser import fetch_schedule_data

# --- FLASK SETUP ---
from flask import Flask
app = Flask(__name__)

@app.route('/')
def health_check():
    return "Bot is running!"
@app.route('/health')
def health():
    return "OK"
# -------------------

logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(
        'Привіт! Я бот розкладу ЛП.\n'
        'Приклади команд:\n'
        '/rozklad - для АВ-11 (всі підгрупи)\n'
        '/rozklad КН-103 - для іншої групи\n'
        '/rozklad АВ-11 1 - для групи АВ-11, підгрупа 1'
    )

# --- ОНОВЛЕНА ФУНКЦІЯ РОЗКЛАДУ ---
async def get_rozklad(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update.effective_chat.id
    args = context.args # Отримуємо аргументи (те, що після команди)
    
    # Значення за замовчуванням
    group = "АВ-11"
    subgroup = None
    
    # Обробка аргументів
    if len(args) >= 1:
        group = args[0] # Перше слово - група
    
    if len(args) >= 2:
        # Друге слово - підгрупа (якщо є)
        if args[1] in ['1', '2']:
            subgroup = args[1]
    
    logger.info(f"User {chat_id} requested schedule: Group={group}, Subgroup={subgroup}")
    await update.message.reply_text(f'🔍 Шукаю розклад для **{group}**' + (f' (підгрупа {subgroup})' if subgroup else '') + '...', parse_mode='Markdown')

    try:
        # Викликаємо парсер з новими параметрами
        # run_in_executor потрібен, щоб парсинг (який займає час) не блокував бота
        loop = asyncio.get_running_loop()
        rozklad_text = await loop.run_in_executor(None, fetch_schedule_data, group, "1", "1", subgroup)
        
        await update.message.reply_text(rozklad_text, parse_mode='Markdown') # Markdown для жирного тексту
        
    except Exception as e:
        logger.error(f"Error: {e}")
        await update.message.reply_text('❌ Помилка. Перевірте назву групи (вона має бути точно як на сайті, напр. АВ-11, кирилицею).')

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
        application = Application.builder().token(TELEGRAM_TOKEN).build()
        application.add_handler(CommandHandler("start", start))
        application.add_handler(CommandHandler("rozklad", get_rozklad))
        application.add_handler(CommandHandler("info", info))
        application.add_handler(CommandHandler("support", support))
        
        loop.run_until_complete(application.run_polling(stop_signals=None))
    except Exception as e:
        logger.error(f"Bot crashed: {e}")
    finally:
        loop.close()

if __name__ == '__main__':
    bot_thread = threading.Thread(target=run_bot)
    bot_thread.start()
    
    port = int(os.environ.get("PORT", 5000))
    app.run(host='0.0.0.0', port=port, debug=False)
    
    # host='0.0.0.0' означає "слухати весь інтернет", це обов'язково для Render
    app.run(host='0.0.0.0', port=port)


