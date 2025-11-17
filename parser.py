import requests
from bs4 import BeautifulSoup

# ПРАВИЛЬНА АДРЕСА САЙТУ:
BASE_URL = "https://student.lpnu.ua"


def fetch_schedule_data(group_name="АВ-11", semester="1", duration="1"):
    """
    Формує URL, робить запит і парсить розклад для вказаної групи.
    """

    # 1. Формуємо повний URL
    schedule_url = f"{BASE_URL}/students_schedule"

    # 'params' - це те, що буде додано до URL після знаку '?'
    params = {
        "studygroup_abbrname": group_name,
        "semestr": semester,
        "semestrduration": duration
    }

    try:
        # 2. Робимо GET-запит
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/58.0.3029.110 Safari/537.36'
        }
        response = requests.get(schedule_url, params=params, headers=headers)
        response.raise_for_status()

        # 3. "Готуємо суп" з HTML-коду
        soup = BeautifulSoup(response.text, 'html.parser')

        # 4. ШУКАЄМО РОЗКЛАД
        # <div class="view-content">
        schedule_content = soup.find('div', class_='view-content')

        if not schedule_content:
            return "Не вдалося знайти блок <div class='view-content'> на сторінці. Можливо, структура сайту змінилась, або для цієї групи немає розкладу."

        # 5. Очищуємо і форматуємо текст
        full_text = schedule_content.get_text(separator="\n", strip=True)

        # Прибираємо зайві порожні рядки
        cleaned_lines = [line for line in full_text.split('\n') if line.strip()]

        return "\n".join(cleaned_lines)

    except requests.RequestException as e:
        print(f"Помилка запиту: {e}")
        return f"Не вдалося підключитися до сайту університету. Помилка: {e}"
    except Exception as e:
        print(f"Помилка парсингу: {e}")
        return f"Не вдалося обробити сторінку. Помилка: {e}"


# --- Це для тестування парсера окремо ---
if __name__ == '__main__':
    print("Тестування парсера... (не забудьте VPN)")
    schedule = fetch_schedule_data(group_name="АВ-11")
    print(schedule)