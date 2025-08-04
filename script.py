import asyncio
import json
import os
from dotenv import load_dotenv
from aiogram import Bot, Dispatcher, types
from aiogram.filters import Command
from aiogram.utils.keyboard import InlineKeyboardBuilder
from rapidfuzz import fuzz
from courses_data import COURSE_CATEGORIES, COURSES
from aiogram.types import InlineKeyboardButton

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
admin_ids_str = os.getenv("ADMIN_IDS", "")
ADMIN_IDS = set(int(x.strip()) for x in admin_ids_str.split(",") if x.strip())

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

FAVORITES_FILE = "favorites.json"

def is_admin(user_id: int) -> bool:
    return user_id in ADMIN_IDS

user_states = {}
user_positions = {}
favorites = {}

def load_favorites():
    try:
        with open(FAVORITES_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception:
        return {}

def save_favorites(data):
    try:
        with open(FAVORITES_FILE, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print(f"Ошибка сохранения избранного: {e}")

favorites = load_favorites()

def total_courses_count():
    return sum(len(courses) for courses in COURSES.values())

def main_menu_keyboard():
    total_courses = total_courses_count()
    kb = InlineKeyboardBuilder()
    kb.button(text=f"📚 Курсы (всего: {total_courses})", callback_data="menu_courses")
    kb.button(text="🔍 Поиск", callback_data="start_search")
    kb.button(text="⭐️ Избранное", callback_data="view_favorites")
    kb.adjust(1)
    return kb.as_markup()

def categories_keyboard():
    kb = InlineKeyboardBuilder()
    for key, name in COURSE_CATEGORIES.items():
        kb.button(text=name, callback_data=f"category:{key}")
    kb.button(text="⬅️ Назад", callback_data="back_main")
    kb.adjust(1)
    return kb.as_markup()

def format_course_message(course, current_idx, total):
    links_text = "\n".join(f"🔗 {link['title']}: {link['url']}" for link in course.get('links', []))
    return (
        f"Курс {current_idx + 1} из {total}\n\n"
        f"{course['title']}\n"
        f"📅 Год: {course.get('year', 'Неизвестно')}\n"
        f"{course.get('description', '')}\n\n"
        f"{links_text}"
    )

def course_navigation_keyboard(course, current_idx, total, prefix, fav_list):
    kb = InlineKeyboardBuilder()

    if course['id'] in fav_list:
        kb.row(
            InlineKeyboardButton(text="❌ Удалить из избранного", callback_data=f"fav_remove:{course['id']}")
        )
    else:
        kb.row(
            InlineKeyboardButton(text="⭐ Добавить в избранное", callback_data=f"fav_add:{course['id']}")
        )

    buttons = []
    if current_idx > 0:
        buttons.append(InlineKeyboardButton(text="⬅️", callback_data=f"{prefix}_prev"))

    buttons.append(InlineKeyboardButton(text=f"{current_idx+1}/{total}", callback_data="choose_course_number"))

    if current_idx < total - 1:
        buttons.append(InlineKeyboardButton(text="➡️", callback_data=f"{prefix}_next"))

    if buttons:
        kb.row(*buttons)

    kb.row(
        InlineKeyboardButton(text="⬅️ Категории", callback_data="menu_courses"),
        InlineKeyboardButton(text="🏠 Меню", callback_data="back_main")
    )

    return kb.as_markup()

async def send_course_message(call, course, current_idx, total, prefix):
    text = format_course_message(course, current_idx, total)
    user_id = call.from_user.id
    fav_list = favorites.setdefault(str(user_id), [])
    keyboard = course_navigation_keyboard(course, current_idx, total, prefix, fav_list)
    await call.message.edit_text(text, reply_markup=keyboard)

def search_courses(query: str):
    query = query.lower()
    results = []
    for category, courses in COURSES.items():
        for course in courses:
            searchable_text = f"{course['title']} {course.get('description', '')} {course.get('year', '')} " + \
                              " ".join(link['title'] + " " + link['url'] for link in course.get('links', []))
            score = fuzz.partial_ratio(query, searchable_text.lower())
            if score > 70:
                results.append((category, course))
    return results

def courses_in_category(category_key):
    return COURSES.get(category_key, [])

@dp.message(Command("start"))
async def start_handler(message: types.Message):
    user_states.pop(message.from_user.id, None)
    user_positions.pop(message.from_user.id, None)
    await message.answer("Выберите действие:", reply_markup=main_menu_keyboard())

@dp.message(Command("admin"))
async def admin_panel_handler(message: types.Message):
    user_id = message.from_user.id
    if not is_admin(user_id):
        await message.answer("Доступ запрещён.")
        return
    kb = InlineKeyboardBuilder()
    kb.button(text="📊 Статистика", callback_data="admin_stats")
    kb.button(text="📣 Рассылка", callback_data="admin_broadcast")
    kb.button(text="🏠 Главное меню", callback_data="back_main")
    kb.adjust(1)
    await message.answer("Админ-панель:", reply_markup=kb.as_markup())

@dp.callback_query()
async def callbacks_handler(call: types.CallbackQuery):
    data = call.data
    user_id = call.from_user.id

    if data == "menu_courses":
        await call.message.edit_text("Выберите категорию курсов:", reply_markup=categories_keyboard())
        user_states[user_id] = None
        user_positions[user_id] = None
        await call.answer()
        return

    if data == "back_main":
        user_states[user_id] = None
        user_positions[user_id] = None
        await call.message.edit_text("Выберите действие:", reply_markup=main_menu_keyboard())
        await call.answer()
        return

    if data.startswith("category:"):
        category = data.split(':')[1]
        courses = courses_in_category(category)
        if not courses:
            await call.answer("В этой категории курсов нет.")
            return
        user_states[user_id] = f"category:{category}"
        user_positions[user_id] = 0
        await send_course_message(call, courses[0], 0, len(courses), "course")
        await call.answer()
        return

    if data in ("course_prev", "course_next"):
        state = user_states.get(user_id, "")
        if not isinstance(state, str) or not state.startswith("category:"):
            await call.answer()
            return
        category = state.split(':')[1]
        courses = courses_in_category(category)
        idx = user_positions.get(user_id, 0)
        if data == "course_prev" and idx > 0:
            idx -= 1
        elif data == "course_next" and idx < len(courses) - 1:
            idx += 1
        user_positions[user_id] = idx
        await send_course_message(call, courses[idx], idx, len(courses), "course")
        await call.answer()
        return

    if data == "choose_course_number":
        prefix = None
        category = None
        state = user_states.get(user_id)
        if isinstance(state, str):
            if state.startswith("category:"):
                prefix = "course"
                category = state.split(':')[1]
        elif isinstance(state, dict) and state.get("type") == "local_search_results":
            prefix = "search"
        elif state == "fav_view":
            prefix = "fav"
        else:
            prefix = None

        if prefix is None:
            await call.answer("Невозможно определить список курсов для выбора.", show_alert=True)
            return

        user_states[user_id] = {"type": "awaiting_course_number", "prefix": prefix}
        if prefix == "course":
            user_states[user_id]["category"] = category

        total = 0
        if prefix == "course":
            total = len(courses_in_category(category))
        elif prefix == "search":
            total = len(state["results"])
        elif prefix == "fav":
            fav_list = favorites.get(str(user_id), [])
            total = len(fav_list)

        await call.message.edit_text(f"Введите номер курса от 1 до {total} для перехода или 'Отмена' для отмены.")
        await call.answer()
        return

    if data == "start_search":
        await call.message.edit_text("Введите запрос для поиска или напишите 'Отмена' для отмены.")
        user_states[user_id] = "awaiting_search"
        await call.answer()
        return

    if data in ("search_prev", "search_next"):
        state = user_states.get(user_id)
        if not state or not isinstance(state, dict) or state.get("type") != "local_search_results":
            await call.answer()
            return
        idx = user_positions.get(user_id, 0)
        results = state["results"]
        if data == "search_prev" and idx > 0:
            idx -= 1
        elif data == "search_next" and idx < len(results) - 1:
            idx += 1
        user_positions[user_id] = idx
        category, course = results[idx]
        user_fav_list = favorites.setdefault(str(user_id), [])
        keyboard = course_navigation_keyboard(course, idx, len(results), "search", user_fav_list)
        text = f"Результаты поиска:\n\n{format_course_message(course, idx, len(results))}\nКатегория: {COURSE_CATEGORIES.get(category, category)}"
        await call.message.edit_text(text, reply_markup=keyboard)
        await call.answer()
        return

    if data == "view_favorites":
        fav_list = favorites.get(str(user_id), [])
        if not fav_list:
            await call.message.edit_text("Ваш список избранного пуст.", reply_markup=main_menu_keyboard())
            user_states.pop(user_id, None)
            user_positions.pop(user_id, None)
            return
        user_states[user_id] = "fav_view"
        user_positions[user_id] = 0
        idx = 0
        fav_id = fav_list[idx]
        course = None
        for cat_courses in COURSES.values():
            for c in cat_courses:
                if c['id'] == fav_id:
                    course = c
                    break
            if course:
                break
        if course:
            keyboard = course_navigation_keyboard(course, idx, len(fav_list), "fav", fav_list)
            text = format_course_message(course, idx, len(fav_list))
            await call.message.edit_text(text, reply_markup=keyboard)
        await call.answer()
        return

    if data in ("fav_prev", "fav_next"):
        if user_states.get(user_id) != "fav_view":
            await call.answer()
            return
        fav_list = favorites.get(str(user_id), [])
        if not fav_list:
            await call.answer("Избранное пусто.", show_alert=True)
            return
        idx = user_positions.get(user_id, 0)
        if data == "fav_prev" and idx > 0:
            idx -= 1
        elif data == "fav_next" and idx < len(fav_list) - 1:
            idx += 1
        user_positions[user_id] = idx
        fav_id = fav_list[idx]
        course = None
        for cat_courses in COURSES.values():
            for c in cat_courses:
                if c['id'] == fav_id:
                    course = c
                    break
            if course:
                break
        if course:
            keyboard = course_navigation_keyboard(course, idx, len(fav_list), "fav", fav_list)
            text = format_course_message(course, idx, len(fav_list))
            await call.message.edit_text(text, reply_markup=keyboard)
        await call.answer()
        return

    if data.startswith("fav_add:"):
        course_id = int(data.split(":")[1])
        fav_list = favorites.setdefault(str(user_id), [])
        if course_id not in fav_list:
            fav_list.append(course_id)
            save_favorites(favorites)
            await call.answer("Добавлено в избранное!")
        else:
            await call.answer("Уже в избранном.", show_alert=True)
        return

    if data.startswith("fav_remove:"):
        course_id = int(data.split(":")[1])
        fav_list = favorites.setdefault(str(user_id), [])
        if course_id in fav_list:
            fav_list.remove(course_id)
            save_favorites(favorites)
            await call.answer("Удалено из избранного!")
            if user_states.get(user_id) == "fav_view":
                fav_list_cur = favorites.get(str(user_id), [])
                if not fav_list_cur:
                    await call.message.edit_text("Ваш список избранного пуст.", reply_markup=main_menu_keyboard())
                    user_states.pop(user_id, None)
                    user_positions.pop(user_id, None)
                else:
                    idx = user_positions.get(user_id, 0)
                    if idx >= len(fav_list_cur):
                        idx = max(0, len(fav_list_cur) - 1)
                        user_positions[user_id] = idx
                    fav_id = fav_list_cur[idx]
                    course = None
                    for cat_courses in COURSES.values():
                        for c in cat_courses:
                            if c['id'] == fav_id:
                                course = c
                                break
                        if course:
                            break
                    if course:
                        keyboard = course_navigation_keyboard(course, idx, len(fav_list_cur), "fav", fav_list_cur)
                        text = format_course_message(course, idx, len(fav_list_cur))
                        await call.message.edit_text(text, reply_markup=keyboard)
                return
        else:
            await call.answer("Нет в избранном.", show_alert=True)
        return

    if data == "fav_clear":
        user_states[user_id] = "fav_clear_confirm"
        kb = InlineKeyboardBuilder()
        kb.button(text="Да, очистить", callback_data="fav_clear_yes")
        kb.button(text="Нет", callback_data="view_favorites")
        await call.message.edit_text("Вы уверены, что хотите очистить весь список избранного?", reply_markup=kb.as_markup())
        await call.answer()
        return
    if data == "fav_clear_yes":
        favorites[str(user_id)] = []
        save_favorites(favorites)
        await call.message.edit_text("Ваше избранное очищено.", reply_markup=main_menu_keyboard())
        user_states.pop(user_id, None)
        user_positions.pop(user_id, None)
        await call.answer()
        return

    if data == "admin_stats":
        if not is_admin(user_id):
            await call.answer("Доступ запрещён.", show_alert=True)
            return
        total_users = len(favorites)
        total_favs = sum(len(v) for v in favorites.values())
        text = f"📊 Пользователей: {total_users}\nВсего избранных курсов: {total_favs}"
        kb = InlineKeyboardBuilder()
        kb.button(text="🏠 Главное меню", callback_data="back_main")
        await call.message.edit_text(text, reply_markup=kb.as_markup())
        await call.answer()
        return
    if data == "admin_broadcast":
        if not is_admin(user_id):
            await call.answer("Доступ запрещён.", show_alert=True)
            return
        user_states[user_id] = "admin_broadcast_wait"
        await call.message.edit_text("Введите сообщение для рассылки всем пользователям или 'Отмена' для отмены:")
        await call.answer()
        return

@dp.message()
async def generic_message_handler(message: types.Message):
    user_id = message.from_user.id
    state = user_states.get(user_id)
    text_lower = message.text.strip().lower()

    if isinstance(state, dict) and state.get("type") == "awaiting_course_number":
        prefix = state.get("prefix")

        if text_lower == "отмена":
            user_states.pop(user_id, None)
            user_positions.pop(user_id, None)
            await message.answer("Отмена выбора курса.", reply_markup=main_menu_keyboard())
            return

        if not message.text.isdigit():
            await message.answer("Пожалуйста, введите корректный номер курса (число) или 'Отмена'.")
            return

        course_number = int(message.text)
        if prefix == "course":
            category = state.get("category")
            if not category:
                await message.answer("Ошибка: категория не определена.")
                user_states.pop(user_id, None)
                return
            courses = courses_in_category(category)
            total = len(courses)
            if not (1 <= course_number <= total):
                await message.answer(f"Введите номер от 1 до {total} или 'Отмена'.")
                return
            idx = course_number - 1
            user_positions[user_id] = idx
            user_states[user_id] = f"category:{category}"
            text = format_course_message(courses[idx], idx, total)
            user_fav_list = favorites.setdefault(str(user_id), [])
            keyboard = course_navigation_keyboard(courses[idx], idx, total, prefix, user_fav_list)
            await message.answer(text, reply_markup=keyboard)
            return

        elif prefix == "search":
            search_state = user_states.get(user_id)
            if not search_state or not isinstance(search_state, dict) or search_state.get("type") != "local_search_results":
                await message.answer("Ошибка: результаты поиска не найдены.")
                user_states.pop(user_id, None)
                return
            results = search_state["results"]
            total = len(results)
            if not (1 <= course_number <= total):
                await message.answer(f"Введите номер от 1 до {total} или 'Отмена'.")
                return
            idx = course_number - 1
            user_positions[user_id] = idx
            user_states[user_id] = search_state
            category, course = results[idx]
            user_fav_list = favorites.setdefault(str(user_id), [])
            keyboard = course_navigation_keyboard(course, idx, total, prefix, user_fav_list)
            text = f"Результаты поиска:\n\n{format_course_message(course, idx, total)}\nКатегория: {COURSE_CATEGORIES.get(category, category)}"
            await message.answer(text, reply_markup=keyboard)
            return

        elif prefix == "fav":
            fav_list = favorites.get(str(user_id), [])
            total = len(fav_list)
            if not (1 <= course_number <= total):
                await message.answer(f"Введите номер от 1 до {total} или 'Отмена'.")
                return
            idx = course_number - 1
            user_positions[user_id] = idx
            user_states[user_id] = "fav_view"
            fav_id = fav_list[idx]
            course = None
            for cat_courses in COURSES.values():
                for c in cat_courses:
                    if c['id'] == fav_id:
                        course = c
                        break
                if course:
                    break
            if course:
                keyboard = course_navigation_keyboard(course, idx, total, prefix, fav_list)
                text = format_course_message(course, idx, total)
                await message.answer(text, reply_markup=keyboard)
            return

    elif state == "awaiting_search":
        if text_lower == "отмена":
            user_states.pop(user_id, None)
            user_positions.pop(user_id, None)
            await message.answer("Поиск отменён.", reply_markup=main_menu_keyboard())
            return
        query = message.text.strip()
        results = search_courses(query)
        if not results:
            await message.answer("Ничего не найдено. Попробуйте другой запрос.", reply_markup=main_menu_keyboard())
            user_states.pop(user_id, None)
            return
        user_states[user_id] = {"type": "local_search_results", "results": results}
        user_positions[user_id] = 0
        category, course = results[0]
        user_fav_list = favorites.setdefault(str(user_id), [])
        keyboard = course_navigation_keyboard(course, 0, len(results), "search", user_fav_list)
        text = f"Результаты поиска:\n\n{format_course_message(course, 0, len(results))}\nКатегория: {COURSE_CATEGORIES.get(category, category)}"
        await message.answer(text, reply_markup=keyboard)

    elif state == "admin_broadcast_wait":
        if text_lower == "отмена":
            user_states.pop(user_id, None)
            await message.answer("Рассылка отменена.", reply_markup=main_menu_keyboard())
            return
        broadcast_text = message.text.strip()
        count_sent = 0
        for uid_str in favorites.keys():
            try:
                await bot.send_message(int(uid_str), f"📢 Сообщение от администрации:\n\n{broadcast_text}")
                count_sent += 1
            except Exception:
                pass
        await message.answer(f"Рассылка выполнена: {count_sent} сообщений.", reply_markup=main_menu_keyboard())
        user_states.pop(user_id, None)
    else:
        await message.answer("Используйте /start для меню.", reply_markup=main_menu_keyboard())

if __name__ == "__main__":
    print("Bot started!")
    asyncio.run(dp.start_polling(bot))
