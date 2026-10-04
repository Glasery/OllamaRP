"""
Динамическая память персонажа-собеседника: краткий, ограниченный по размеру
список самого важного, что с ним случилось и как он изменился (события,
отношения, статусы, внешность). Хранится в самом пресете персонажа
(`Character.dyn_memory`), подставляется в его блок системного промпта и
переживает отдельные диалоги.

Чистая логика без tkinter (тестируется отдельно): промпт для скрытого запроса
«обнови динамическую память», разбор ответа модели и жёсткий предел размера.
Когда и как запросы запускаются - в gui.App (`_dyn_*`).

Принципы:
- вход запроса - ТОЛЬКО новые сводки памяти диалога + текущая динамическая
  память (вход ограничен и от длины диалога не зависит);
- модель решает, есть ли что-то важное: ответ `НЕТ_ИЗМЕНЕНИЙ` (`NO_CHANGES`)
  = память не трогаем (не дублируем память диалога каждый раз);
- размер ограничен `DYN_MEMORY_LIMIT`: просим модель уложиться, а переполнение
  всё равно режем в коде (сначала самые старые пункты) - память не растёт
  выше предела;
- подозрительный ответ (память «усохла» без нужды - обычно обрезанный или
  сломанный ответ слабой модели) отвергается, старая память остаётся.
"""
import re

DYN_MEMORY_LIMIT = 4000        # дефолт предела, символов; выше память не растёт
DYN_LIMIT_MIN = 500            # допустимые границы настройки «Предел динамической памяти»
DYN_LIMIT_MAX = 20000
DYN_NEW_MAX_ITEMS = 8          # сколько необработанных сводок держим (вход запроса ограничен)
SHRINK_GUARD_FROM = 600        # короче текущая память - защиту от «усыхания» не применяем
SHRINK_GUARD_RATIO = 0.4       # новый текст < 40 % старого - подозрительно...
SHRINK_GUARD_FULL = 0.9        # ...если только старая не была почти у предела (тогда сжатие ожидаемо)

NO_CHANGES = "НЕТ_ИЗМЕНЕНИЙ"
NO_CHANGES_EN = "NO_CHANGES"
_NO_CHANGES_RE = re.compile(
    r"^\W*(НЕТ[_\s-]*ИЗМЕНЕНИЙ|NO[_\s-]*CHANGES?)\W*$", re.IGNORECASE)

DYN_SYSTEM = (
    "Ты ведёшь «динамическую память» персонажа ролевой игры - краткий список "
    "САМОГО ВАЖНОГО, что с ним произошло и что в нём изменилось: ключевые "
    "события, важные изменения отношений (с кем и как), статуса, положения, "
    "внешности, обещания, тайны, незакрытые линии. Тебе дают текущую "
    "динамическую память и новые события диалога.\n"
    "Если в новых событиях нет ничего важного для долговременной истории "
    "персонажа (обычный разговор, мелочи) - ответь ровно одним словом "
    f"{NO_CHANGES}, без пояснений.\n"
    "Иначе выведи ПОЛНУЮ обновлённую память: сохрани важное из старой, "
    "добавь новое, слей повторы, убери устаревшее и мелкие подробности. "
    "Формат - короткие пункты, каждый с новой строки, начиная с «- ». Только "
    "факты, без вступлений и разметки. Пиши кратко: только самое важное. "
    "Объём - не более {limit} символов; если места не хватает, сокращай "
    "самое мелкое и старое."
)

DYN_SYSTEM_EN = (
    "You keep the “dynamic memory” of a roleplay character - a brief list of "
    "ONLY THE MOST IMPORTANT things that happened to them and how they "
    "changed: key events, important changes in relationships (with whom and "
    "how), status, position, appearance, promises, secrets, open threads. "
    "You are given the current dynamic memory and new events of the "
    "dialogue.\n"
    "If the new events contain nothing important for the character's "
    "long-term history (ordinary talk, trivia) - answer with exactly one "
    f"word: {NO_CHANGES_EN}, no explanations.\n"
    "Otherwise output the FULL updated memory: keep what matters from the old "
    "one, add the new, merge repetition, drop outdated and minor details. "
    "Format - short items, one per line, starting with \"- \". Facts only, no "
    "preamble or markup. Be brief: only what is most important. At most "
    "{limit} characters; when short of space, shorten the smallest and "
    "oldest first."
)


def clamp_limit(v) -> int:
    """Предел из настройки -> число в [DYN_LIMIT_MIN, DYN_LIMIT_MAX]; пусто /
    мусор / bool -> DYN_MEMORY_LIMIT."""
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        return DYN_MEMORY_LIMIT
    return max(DYN_LIMIT_MIN, min(DYN_LIMIT_MAX, int(v)))


def build_messages(char_name: str, protagonist_name: str, current: str,
                   new_events: list, limit: int = DYN_MEMORY_LIMIT,
                   lang: str = "ru") -> list:
    """messages для скрытого запроса. `new_events` - список новых сводок
    памяти диалога (строки); берётся не больше DYN_NEW_MAX_ITEMS последних."""
    en = (lang or "ru").lower().startswith("en")
    events = "\n\n".join(e.strip() for e in (new_events or [])[-DYN_NEW_MAX_ITEMS:]
                         if e and e.strip())
    cur = (current or "").strip()
    if en:
        who = (f"Character: “{char_name or 'unnamed'}”."
               + (f" The protagonist (the player) is “{protagonist_name}”."
                  if protagonist_name else ""))
        user = (f"{who}\n\nCurrent dynamic memory:\n{cur or '(empty)'}\n\n"
                f"New events of the dialogue:\n{events}\n\n"
                f"Updated dynamic memory (or {NO_CHANGES_EN}):")
        system = DYN_SYSTEM_EN
    else:
        who = (f"Персонаж: «{char_name or 'без имени'}»."
               + (f" Главный герой (игрок): «{protagonist_name}»."
                  if protagonist_name else ""))
        user = (f"{who}\n\nТекущая динамическая память:\n{cur or '(пусто)'}\n\n"
                f"Новые события диалога:\n{events}\n\n"
                f"Обновлённая динамическая память (или {NO_CHANGES}):")
        system = DYN_SYSTEM
    return [{"role": "system", "content": system.replace("{limit}", str(limit))},
            {"role": "user", "content": user}]


def fit_to_limit(text: str, limit: int = DYN_MEMORY_LIMIT) -> str:
    """Уложить текст в `limit` символов. Память - список пунктов по строкам:
    сначала выбрасываются самые СТАРЫЕ (верхние) строки; если и одна строка
    не лезет - обрезается по границе слова (с «…»)."""
    text = (text or "").strip()
    if limit <= 0 or len(text) <= limit:
        return text
    lines = text.split("\n")
    while len(lines) > 1 and len("\n".join(lines).strip()) > limit:
        lines.pop(0)
    out = "\n".join(lines).strip()
    if len(out) > limit:
        cut = out[:max(1, limit - 1)]
        sp = cut.rfind(" ")
        if sp > limit // 2:
            cut = cut[:sp]
        out = cut.rstrip() + "…"
    return out


def _clean(text: str) -> str:
    t = (text or "").strip()
    if t.startswith("```"):                       # ответ в блоке кода
        t = re.sub(r"^```[a-zA-Z]*\s*", "", t)
        t = re.sub(r"\s*```$", "", t)
    return t.strip()


def interpret_reply(reply, current: str, limit: int = DYN_MEMORY_LIMIT):
    """Ответ модели -> (статус, текст):
        ("fail", current)    - пусто / запрос не удался (новые события остаются
                               необработанными - попробуем в следующий раз);
        ("same", current)    - НЕТ_ИЗМЕНЕНИЙ или подозрительный/идентичный
                               ответ: память не меняем, события считаются
                               обработанными;
        ("changed", новый)   - новая память (уже уложена в limit)."""
    cur = (current or "").strip()
    if reply is None or not str(reply).strip():
        return "fail", cur
    text = _clean(str(reply))
    if not text:
        return "fail", cur
    if _NO_CHANGES_RE.match(text.split("\n", 1)[0].strip()):
        # маркер первой строкой = «изменений нет»; всё, что модель дописала
        # после него, - пояснение, а не память
        return "same", cur
    # маркер среди прочего текста в память не попадает
    text = "\n".join(ln for ln in text.split("\n") if not _NO_CHANGES_RE.match(ln.strip())).strip()
    if not text:
        return "same", cur
    new = fit_to_limit(text, limit)
    if new == cur:
        return "same", cur
    if (len(cur) > SHRINK_GUARD_FROM and len(cur) < limit * SHRINK_GUARD_FULL
            and len(new) < len(cur) * SHRINK_GUARD_RATIO):
        return "same", cur                         # память не должна «усыхать» без причины
    return "changed", new
