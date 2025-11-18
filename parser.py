import requests
from bs4 import BeautifulSoup

BASE_URL = "https://student.lpnu.ua"

def fetch_schedule_data(group_name="АВ-11", semester="1", duration="1", subgroup=None):
    """
    Парсить розклад і повертає відформатований рядок.
    subgroup: номер підгрупи (1 або 2). Якщо None - показує все.
    """
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
        response = requests.get(schedule_url, params=params, headers=headers)
        response.raise_for_status()

        soup = BeautifulSoup(response.text, 'html.parser')
        
        # Знаходимо головний контейнер з розкладом
        content_div = soup.find('div', class_='view-content')
        
        if not content_div:
            return f"❌ Не вдалося знайти розклад для групи {group_name}. Можливо, такої групи не існує або сайт змінився."

        # --- НОВА ЛОГІКА ПАРСИНГУ ---
        final_text = f"📅 **Розклад для {group_name}**\n"
        if subgroup:
             final_text += f"👤 Підгрупа: {subgroup}\n"
        final_text += "➖➖➖➖➖➖➖➖➖➖\n"

        # Дні тижня на сайті ЛП зазвичай розділені заголовками <h3>
        # Ми будемо йти по всіх елементах всередині view-content
        
        current_day = ""
        found_any = False

        # Знаходимо всі заголовки днів (Пн, Вт...)
        days = content_div.find_all('div', class_='view-grouping')
        
        if not days:
             # Якщо структура інша (без view-grouping), пробуємо старий метод
             return "⚠️ Структура сторінки нетипова. Ось сирий текст:\n" + content_div.get_text(separator="\n", strip=True)

        for day_block in days:
            # Заголовок дня (Пн, Вт...)
            header = day_block.find('span', class_='view-grouping-header')
            if header:
                current_day = header.get_text(strip=True)
                final_text += f"\n🗓 **{current_day}**\n"
            
            # Пари в цьому дні
            # Шукаємо всі рядки контенту
            rows = day_block.find_all('div', class_='stud_schedule')
            
            for row in rows:
                # Номер пари
                num_header = row.find_previous('h3') # Зазвичай номер пари стоїть перед блоком stud_schedule
                pair_num = num_header.get_text(strip=True) if num_header else "?"
                
                # Текст пари (Предмет, викладач...)
                # Знаходимо блоки <div id="group_full"> або просто текст
                # На сайті ЛП часто структура:
                # <div class="stud_schedule">
                #    <div class="group_content">...</div>
                # </div>
                
                content = row.find('div', class_='group_content')
                if not content: 
                    content = row # Якщо немає group_content, беремо весь блок
                
                text_lines = [line.strip() for line in content.get_text(separator="\n").split('\n') if line.strip()]
                full_pair_text = ", ".join(text_lines)

                # --- Фільтрація за підгрупою ---
                # Часто підгрупа пишеться як (підгр. 1) або просто у тексті
                if subgroup:
                    # Якщо користувач вибрав 1, а в тексті пари написано "підгр. 2" -> пропускаємо
                    if f"підгр. {3-int(subgroup)}" in full_pair_text.lower() or \
                       f"підгрупа {3-int(subgroup)}" in full_pair_text.lower():
                        continue
                
                final_text += f"  🔹 *{pair_num} пара*: {full_pair_text}\n"
                found_any = True
        
        if not found_any:
            return "Пар не знайдено. Можливо, вільний день! 😎"

        return final_text

    except Exception as e:
        print(f"Помилка парсингу: {e}")
        return "⚠️ Сталася помилка при обробці даних з сайту."
