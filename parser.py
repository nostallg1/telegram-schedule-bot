import requests
from bs4 import BeautifulSoup
import logging

# Налаштування логування, щоб бачити помилки в Render Logs
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

BASE_URL = "https://student.lpnu.ua"

def fetch_schedule_data(group_name, semester="1", duration="1", subgroup=None):
    schedule_url = f"{BASE_URL}/students_schedule"
    params = {
        "studygroup_abbrname": group_name,
        "semestr": semester,
        "semestrduration": duration
    }

    try:
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/58.0.3029.110 Safari/537.36'
        }
        logger.info(f"Запит до: {schedule_url} з параметрами {params}")
        response = requests.get(schedule_url, params=params, headers=headers)
        response.raise_for_status()

        soup = BeautifulSoup(response.text, 'html.parser')
        
        # 1. Перевірка: чи знайшли ми блок контенту?
        content_div = soup.find('div', class_='view-content')
        if not content_div:
            logger.warning("Не знайдено view-content. Можливо, група не існує.")
            return "❌ Розклад не знайдено.\nПеревірте правильність назви групи (має бути кирилицею, наприклад 'АВ-11')."

        # 2. Перевірка: чи є взагалі дні в розкладі?
        days = content_div.find_all('div', class_='view-grouping')
        if not days:
            # Іноді розклад є, але без заголовків днів. Спробуємо витягнути текст напряму.
            text = content_div.get_text(separator="\n", strip=True)
            if len(text) < 10: # Якщо тексту зовсім мало
                return "📭 Розклад для цієї групи порожній або група вказана неправильно."
            return f"⚠️ Нестандартний формат розкладу:\n\n{text}"

        # --- ФОРМУВАННЯ ВІДПОВІДІ ---
        final_text = f"📅 **Розклад для {group_name}**\n"
        if subgroup:
             final_text += f"👤 Підгрупа: {subgroup}\n"
        final_text += "➖➖➖➖➖➖➖➖➖➖\n"

        for day_block in days:
            header = day_block.find('span', class_='view-grouping-header')
            day_name = header.get_text(strip=True) if header else "Невідомий день"
            
            # Збираємо пари для цього дня
            day_schedule = []
            rows = day_block.find_all('div', class_='stud_schedule')
            
            for row in rows:
                # Номер пари
                num_header = row.find_previous('h3')
                pair_num = num_header.get_text(strip=True) if num_header else "?"
                
                # Текст пари
                content = row.find('div', class_='group_content')
                if not content: content = row
                
                full_pair_text = content.get_text(separator=" ", strip=True)

                # Фільтрація підгрупи
                if subgroup:
                    # Якщо ми шукаємо 1 підгрупу, а пара ТІЛЬКИ для 2-ї -> пропускаємо
                    if f"підгр. {3-int(subgroup)}" in full_pair_text.lower() or \
                       f"підгрупа {3-int(subgroup)}" in full_pair_text.lower():
                        continue
                
                day_schedule.append(f"🔹 *{pair_num} пара*: {full_pair_text}")
            
            # Додаємо день у фінальний текст, тільки якщо в ньому є пари (після фільтрації)
            if day_schedule:
                final_text += f"\n🗓 **{day_name}**\n"
                final_text += "\n".join(day_schedule) + "\n"

        return final_text

    except Exception as e:
        logger.error(f"CRITICAL ERROR in parser: {e}", exc_info=True)
        return f"⚠️ Технічна помилка парсера: {str(e)}"

