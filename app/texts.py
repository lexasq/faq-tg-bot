"""All user-facing strings, in Ukrainian. Grouped by handler module so a
phase's build prompt only ever touches its own section."""

# --- generic ---
CANCELLED = "Скасовано."
UNKNOWN_COMMAND_IN_CONVERSATION = "Не зрозумів. Спробуйте ще раз або /cancel."
SESSION_TIMED_OUT = "⏳ Час сесії вичерпано. Почніть спочатку."

# --- /start, /help ---
START_NON_ADMIN = "Я FAQ-бот. Питання можна переглянути тут: /faq"
# Kept in sync by hand with app/handlers/*.HANDLERS — /settings and
# /admins used to be listed here despite never being implemented.
START_ADMIN_MENU = (
    "Вітаю! Ви адміністратор. Доступні команди:\n\n"
    "Записи:\n"
    "/add — додати новий запис\n"
    "/list [категорія] — список записів\n"
    "/find <текст> — пошук записів\n"
    "/import — імпорт (текстом або файлом .txt/.md/.csv)\n"
    "/export — вивантажити всі записи (.md + .csv)\n\n"
    "Аналітика:\n"
    "/review — черга нерозпізнаних запитань\n"
    "/stats [7d|30d] — статистика\n"
    "/test <текст> — перевірити, як бот відповість\n\n"
    "Інше:\n"
    "/faq — переглянути список питань як бачать користувачі\n"
    "/health — перевірка стану бота\n"
    "/cancel — скасувати поточну дію\n"
    "/help — ця довідка\n\n"
    "⚠️ Небезпечно (лише власник):\n"
    "/reset — видалити ВСІ записи FAQ"
)

# --- /reset (owner only) ---
RESET_EMPTY = "Записів немає — нічого скидати."
RESET_WARNING = (
    "⚠️ Це видалить УСІ {count} записів FAQ НАЗАВЖДИ. Цю дію неможливо скасувати.\n\n"
    "Щоб підтвердити, надішліть слово {word}. Будь-яке інше повідомлення або /cancel — скасує."
)
RESET_WRONG_CONFIRMATION = "Не підтверджено. Надішліть саме слово {word}, або /cancel."
RESET_DONE = "🗑 Видалено {count} записів. FAQ порожній."
RESET_NOT_OWNER = "Ця команда доступна лише власнику."

# --- /add conversation ---
ADD_ASK_TITLE = "Введіть заголовок запису (коротка назва, як він буде показаний у меню):"
ADD_ASK_CATEGORY = "Оберіть категорію:"
ADD_ASK_CATEGORY_NEW = "Введіть назву нової категорії:"
ADD_ASK_ANSWER = "Введіть текст відповіді. Можна декілька рядків, HTML-теги (<b>, <i>) підтримуються. Завершіть командою /done."
ADD_ANSWER_EMPTY = "Відповідь порожня. Надішліть текст або /cancel."
ADD_SUGGESTED_PATTERNS = "Автоматично згенеровані патерни:\n\n{patterns}\n\nПрийняти чи ввести свої?"
ADD_ASK_OWN_PATTERNS = "Введіть власні патерни через кому:"
ADD_PREVIEW_HEADER = "Так виглядатиме відповідь:\n\n"
ADD_PREVIEW_FOOTER = "\n\nКатегорія: {category}\nПатерни: {patterns}\n\nПідтвердити?"
ADD_CREATED = "✅ Запис створено."
ADD_TITLE_TOO_LONG = "Заголовок задовгий (максимум 100 символів)."

BTN_ACCEPT_PATTERNS = "✅ Прийняти"
BTN_OWN_PATTERNS = "✏️ Свої патерни"
BTN_CONFIRM = "✅ Підтвердити"
BTN_CANCEL = "❌ Скасувати"
BTN_NEW_CATEGORY = "➕ Нова категорія"

# --- /list, /find, entry card ---
LIST_EMPTY = "Записів ще немає. Додайте перший через /add."
LIST_HEADER = "Записи{category_suffix} (сторінка {page}/{total}):"
FIND_ASK = "Що шукаємо?"
FIND_EMPTY = "Нічого не знайдено."
FIND_RESULTS_HEADER = "Знайдено {count}:"

BTN_PREV = "⬅️"
BTN_NEXT = "➡️"
BTN_BACK = "⬅️ Назад"

ENTRY_CARD_TEMPLATE = (
    "{status_icon} <b>{title}</b>\n"
    "Категорія: {category}\n"
    "Тип: {type}\n"
    "Видимість: {visibility}\n"
    "Версія: {version} · оновлено {updated_at}\n"
    "Патернів: {pattern_count}\n\n"
    "{answer_preview}"
)
BTN_EDIT_ANSWER = "✏️ Відповідь"
BTN_EDIT_PATTERNS = "🔤 Патерни"
BTN_EDIT_CATEGORY = "🏷 Категорія"
BTN_DISABLE = "🔇 Вимкнути"
BTN_ENABLE = "🔊 Увімкнути"
BTN_MAKE_DM_ONLY = "🔒 Зробити DM-only"
BTN_MAKE_PUBLIC = "🔓 Зробити публічним"
VISIBILITY_CHANGED = "Видимість змінено на: {visibility}"
BTN_DELETE = "🗑 Видалити"
BTN_HISTORY = "🕘 Історія"

DELETE_SOFT_DONE = "Запис вимкнено. Натисніть 🗑 ще раз для остаточного видалення."
DELETE_HARD_CONFIRM = "⚠️ Остаточно видалити цей запис? Це незворотньо."
DELETE_HARD_DONE = "🗑 Запис остаточно видалено."
BTN_DELETE_CONFIRM = "🗑 Так, видалити назавжди"

EDIT_ANSWER_ASK = "Надішліть новий текст відповіді (завершіть /done):"
EDIT_ANSWER_DONE = "✅ Відповідь оновлено."
EDIT_PATTERNS_ASK = "Поточні патерни ({count}):\n{patterns}\n\nНадішліть нові через кому, щоб замінити ці — або /cancel, щоб залишити як є."
PATTERNS_EMPTY = "(немає)"
EDIT_PATTERNS_DONE = "✅ Патерни оновлено."
EDIT_CATEGORY_DONE = "✅ Категорію змінено на {category}."

HISTORY_EMPTY = "Історії змін ще немає."
HISTORY_HEADER = "Історія змін (сторінка {page}/{total}):"
HISTORY_ITEM = "v{version} · {updated_at}\n{answer_preview}"

# --- /import, /export (P5) ---
IMPORT_ASK_CONTENT = (
    "Надішліть текст для імпорту (можна вставити текстовий блок) або прикріпіть .txt/.md/.csv файл (до 1 МБ)."
)
IMPORT_EMPTY = "Порожній вміст. Спробуйте ще раз або /cancel."
IMPORT_FILE_TOO_LARGE = "Файл завеликий (максимум 1 МБ)."
IMPORT_NOTHING_TO_IMPORT = "Не знайдено жодного запису для імпорту."
IMPORT_ORPHAN = (
    "Не вдалося визначити заголовок для блоку (залишилось {remaining}):\n\n{preview}"
)
IMPORT_ASK_TITLE = "Введіть заголовок для цього блоку:"
BTN_SET_TITLE = "➕ Задати заголовок"
BTN_ATTACH_PREVIOUS = "⬆️ Приєднати до попереднього запису"
BTN_SKIP = "🗑 Пропустити"
IMPORT_SUMMARY = "Знайдено {total} записів: {new} нових, {updated} оновлень, {unchanged} без змін."
IMPORT_ERRORS_HEADER = "\n⚠️ Помилки розбору:"
IMPORT_WARNINGS_HEADER = "\n⚠️ Попередження валідації:"
IMPORT_DIFFS_HEADER = "\n📝 Зміни:"
IMPORT_DONE = "✅ Імпорт завершено: створено {created}, оновлено {updated}."
EXPORT_EMPTY = "Немає записів для експорту."

# --- group autoreply (P4) ---
BTN_ALL_QUESTIONS = "📖 Всі питання"
BTN_THUMBS_UP = "👍"
BTN_THUMBS_DOWN = "👎"
FEEDBACK_THANKS = "Дякую!"
NOT_FOUND_ON_MENTION = "Не знайшов відповіді 🤔 Спробуйте переглянути список питань:"
SENT_TO_DM = "📩 Надіслав вам у приватні повідомлення"
SENT_TO_DM_FAILED = "Не вдалося написати вам у приват — спочатку напишіть боту в особисті:"
BTN_OPEN_IN_DM = "✍️ Написати боту"

# --- /faq menu (P6/P10) ---
MENU_ROOT_HEADER = "📖 Оберіть категорію:"
MENU_CATEGORY_HEADER = "{category} (сторінка {page}/{total}):"
BTN_BACK_TO_LIST = "📖 До списку"

# --- /stats, /review, /test, /health (P7) ---
STATS_HEADER = "📊 Статистика за {period}"
STATS_BODY = (
    "Автовідповідей: {replies}\n"
    "Унікальних авторів запитань: {unique_askers}\n"
    "Пропущено (без відповіді): {misses}\n"
    "👎 серед відповідей: {downvote_rate:.0%}"
)
STATS_TOP_ENTRIES_HEADER = "\nТоп записів:"
STATS_TOP_ENTRIES_ITEM = "{rank}. {title} — {hits}"
STATS_TOP_MISSES_HEADER = "\nНайчастіші нерозпізнані запитання:"
STATS_TOP_MISSES_ITEM = "{rank}. «{text}» ×{count}"
STATS_NO_DATA = "Даних ще немає за цей період."

REVIEW_EMPTY = "Черга порожня 🎉"
REVIEW_ITEM = "Питання {index}/{total} (score {score:.2f}):\n\n«{text}»"
BTN_REVIEW_CREATE = "➕ Створити запис"
BTN_REVIEW_LINK = "🔗 Прив'язати"
BTN_REVIEW_IGNORE = "🙈 Ігнорувати"
REVIEW_IGNORED = "🙈 Позначено як опрацьоване."
REVIEW_LINKED = "🔗 Патерн додано до «{title}»."
ADD_ASK_CATEGORY_FOR = "Заголовок: «{title}»\n\nОберіть категорію:"

TEST_ASK_TEXT = "Використання: /test <текст повідомлення>"
TEST_HEADER = "🔍 Тест: «{text}»\n"
TEST_NO_MATCH = "Жоден запис не збігся."
TEST_RESULT_ITEM = "{rank}. {title} — {score:.2f}\n   {reason}"
TEST_WOULD_DO = "\nУ групі: {group}\nПри згадці: {mention}"
TEST_PREVIEW_HEADER = "👁 Так виглядатиме відповідь:\n\n"

HEALTH_OK = "ok"

# --- review_after digest (P10) ---
REVIEW_DIGEST_HEADER = "⏰ {count} записів потребують перевірки:"
REVIEW_MARKED_OK = "✅ «{title}» позначено актуальним ще на 6 місяців."
BTN_REVIEW_OK = "✅ Актуально"
BTN_REVIEW_EDIT = "✏️ Оновити"
