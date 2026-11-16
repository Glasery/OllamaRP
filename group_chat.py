"""
Режим «Группа»: сцена с ДВУМЯ персонажами и главным героем-наблюдателем.
Персонажи говорят друг с другом сами (автодиалог), герой молчит, пока игрок не
вмешается; любой участник может обратиться к конкретному собеседнику.

Чистая логика без tkinter (тестируется отдельно): стенограмма, директива «чей
ход», схема JSON-ответа с адресатом, разбор ответа, планировщик «кто говорит
дальше». Что и когда запускается - в gui.App (`_group_*`).

Принципы:
- ОДИН запрос = ОДНА реплика одного персонажа. Так голоса не сливаются и у
  каждого своя динамическая память.
- Все запросы делят ОДИН общий system-промпт (обе карточки, сцена, память), а
  «чей ход» добавляется В КОНЕЦ запроса вместе со стенограммой: префикс
  запроса не меняется при смене говорящего, и Ollama переиспользует кэш
  промпта (иначе при каждой смене говорящего пересчитывался бы весь контекст).
- Адресат реплики (`to`) - поле JSON-ответа с enum из имён остальных участников
  и «все»: модель не может вписать несуществующее имя, отдельный запрос
  «кому слово» не нужен. Следующего говорящего выбирает КОД по `to`.
- Запись истории: {"role": "user"|"assistant", "content": "*действие*\\nречь",
  "speaker": имя, "to": имя адресата или "" (= всем)}. Герой - "user",
  персонажи - "assistant" (проверка повторов и память диалога работают как есть).
"""
import re

MAX_CHARS = 2                  # персонажей в сцене (+ герой = 3 участника)
MANUAL_CHAIN = 3               # реплик подряд после реплики героя (без автодиалога)
AUTO_TURNS_DEFAULT = 20        # лимит реплик одного запуска автодиалога
AUTO_TURNS_MIN = 1
AUTO_TURNS_MAX = 200

# Ограничения длины реплики. Без них модель иногда уходила в бесконечный повтор
# ВНУТРИ JSON-поля (структурированный ответ копится и показывается только в конце):
# минуты ожидания и «стена текста» в чате.
MAX_TOKENS = 600               # num_predict запроса реплики (меньше - если в Settings задан меньший)
STREAM_CHAR_GUARD = 3500       # ответ длиннее (символов JSON) - обрываем стрим
MAX_SPEECH_CHARS = 900         # речь в чате/истории режется до стольких символов (по границе предложения)
MAX_ACTION_CHARS = 450

ALL_TOKEN = {"ru": "все", "en": "all"}


def _is_en(lang) -> bool:
    return (lang or "ru").lower().startswith("en")


def all_token(lang: str = "ru") -> str:
    return ALL_TOKEN["en" if _is_en(lang) else "ru"]


def clamp_turns(v) -> int:
    """Лимит реплик автодиалога из настройки/поля: мусор/пусто -> дефолт,
    иначе в [AUTO_TURNS_MIN, AUTO_TURNS_MAX]."""
    if isinstance(v, str):
        v = v.strip()
        v = int(v) if v.lstrip("-").isdigit() else None
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        return AUTO_TURNS_DEFAULT
    return max(AUTO_TURNS_MIN, min(AUTO_TURNS_MAX, int(v)))


def _norm(name) -> str:
    return re.sub(r"\s+", " ", str(name or "")).strip().lower()


def roster_error(hero: str, a: str, b: str) -> str:
    """Проверка состава сцены. -> "" (всё хорошо) или код:
    "missing" (не выбран персонаж / пустое имя), "same_char" (один и тот же
    персонаж дважды), "name_clash" (имена совпадают с именем героя - по именам
    модель различает участников)."""
    na, nb, nh = _norm(a), _norm(b), _norm(hero)
    if not na or not nb:
        return "missing"
    if na == nb:
        return "same_char"
    if nh and nh in (na, nb):
        return "name_clash"
    return ""


def other_char(speaker: str, a: str, b: str) -> str:
    return b if _norm(speaker) == _norm(a) else a


def same(x, y) -> bool:
    return _norm(x) == _norm(y)


# ------------------------------------------------------------ стенограмма ----
def _body(content: str) -> str:
    """Каноничная реплика "*действие*\\nречь" -> одна строка "*действие* речь"."""
    return " ".join(ln.strip() for ln in (content or "").splitlines() if ln.strip())


def label(entry: dict, fallback: str = "…", lang: str = "ru") -> str:
    """Подпись реплики: «Имя → Кому». Адресат виден ВСЕГДА: реплика ко всем /
    с неясным адресатом подписывается «Имя → все» (иначе стрелка пропадала, и
    казалось, что адресации нет). Запись без `speaker` (старый формат) - как есть."""
    who = (entry.get("speaker") or "").strip()
    if not who:
        return fallback
    to = (entry.get("to") or "").strip() or all_token(lang)
    return f"{who} → {to}"


def transcript(entries: list, lang: str = "ru") -> str:
    """Реплики -> стенограмма «Имя → Кому: *действие* речь», по строке на реплику."""
    en = _is_en(lang)
    if not entries:
        return "(nobody has said anything yet)" if en else "(пока никто ничего не сказал)"
    lines = []
    for e in entries:
        body = _body(e.get("content"))
        if body:
            lines.append(f"{label(e, lang=lang)}: {body}")
    return "\n".join(lines)


def directive(speaker: str, hero: str = "", lang: str = "ru", *, first: bool = False,
              addressed: bool = False, hero_skipped: bool = False) -> str:
    """Что сказать модели В КОНЦЕ запроса: чей ход. `first` - сцена только
    начинается; `addressed` - последняя реплика адресована говорящему;
    `hero_skipped` - к герою обратились, а он промолчал."""
    en = _is_en(lang)
    parts = []
    if en:
        parts.append(f"Now it is {speaker}'s turn. Write ONLY the line of {speaker} "
                     "(JSON); do not write lines of the other participants.")
        if first:
            parts.insert(0, "The scene is just beginning.")
        if addressed:
            parts.append("The last line was addressed to you - react to it.")
        if hero_skipped and hero:
            parts.append(f"{hero} did not answer and stays silent.")
    else:
        parts.append(f"Теперь ход: {speaker}. Напиши ТОЛЬКО реплику {speaker} (JSON); "
                     "не пиши реплики других участников.")
        if first:
            parts.insert(0, "Сцена только начинается.")
        if addressed:
            parts.append("Последняя реплика адресована тебе - отреагируй на неё.")
        if hero_skipped and hero:
            parts.append(f"{hero} не ответил и молчит.")
    return " ".join(parts)


def build_user_message(entries: list, speaker: str, hero: str = "", lang: str = "ru", *,
                       hero_skipped: bool = False) -> str:
    """Единственное user-сообщение запроса: стенограмма + директива «чей ход»."""
    en = _is_en(lang)
    last = entries[-1] if entries else None
    addressed = bool(last) and same(last.get("to"), speaker)
    head = ("Scene transcript (latest lines):" if en
            else "Стенограмма сцены (последние реплики):")
    return (f"{head}\n{transcript(entries, lang)}\n\n"
            + directive(speaker, hero, lang, first=not entries, addressed=addressed,
                        hero_skipped=hero_skipped))


# ---------------------------------------------------- схема и разбор ответа ----
def group_schema(others: list, lang: str = "ru", allow_all: bool = True) -> dict:
    """JSON-схема ответа (structured outputs). `to` - ПЕРВЫМ: сначала модель
    решает, кому говорит, потом пишет реплику; значение - только имя из
    `others` или «все» (enum). `allow_all=False` - один персонаж заглушён:
    говорить можно ТОЛЬКО с героем, «все» в списке нет."""
    choices = [n for n in others if str(n).strip()] + ([all_token(lang)] if allow_all else [])
    return {
        "type": "object",
        "properties": {
            "to": {"type": "string", "enum": choices},
            "action": {"type": "string"},
            "speech": {"type": "string"},
        },
        "required": ["to", "action", "speech"],
    }


def normalize_to(to, others: list, lang: str = "ru") -> str:
    """Адресат из ответа модели -> имя из `others` или "" (= всем / не ясно)."""
    key = _norm(to)
    if not key or key in (_norm(all_token("ru")), _norm(all_token("en"))):
        return ""
    for n in others:
        if _norm(n) == key:
            return n
    return ""


def parse_reply(text: str, others: list, lang: str = "ru"):
    """Ответ модели -> (to, action, speech). Терпим к оборванному JSON (берём
    успевшее прийти), к не-JSON (весь текст - речь), к чужому/неизвестному
    адресату (-> ""). `to` - имя из `others` или ""."""
    import json
    raw = (text or "").strip()
    if raw.startswith("```"):
        raw = re.sub(r"^```[a-zA-Z]*\s*", "", raw)
        raw = re.sub(r"\s*```$", "", raw).strip()
    data = None
    try:
        data = json.loads(raw)
    except (ValueError, TypeError):
        try:
            from ollama_client import _partial_json_fields
            data = _partial_json_fields(raw)
        except Exception:
            data = None
    if isinstance(data, dict):
        def _s(k):
            v = data.get(k)
            return str(v).strip() if isinstance(v, (str, int, float)) and not isinstance(v, bool) else ""
        return normalize_to(_s("to"), others, lang), _s("action"), _s("speech")
    return "", "", raw


# ------------------------------------------------- длина реплики / повторы ----
_SENT_SPLIT = re.compile(r"(?<=[.!?…])\s+")


def dedupe_sentences(text: str) -> str:
    """Убрать дословно повторяющиеся предложения («Да, Хозяин! Всегда Ваша, сэр!»
    ×20 - типичный зацикленный хвост). Нет повторов - текст как есть (переводы
    строк не трогаем)."""
    text = (text or "").strip()
    parts = _SENT_SPLIT.split(text)
    seen, out, dropped = set(), [], False
    for p in parts:
        key = re.sub(r"\W+", " ", p.lower()).strip()
        if key and key in seen:
            dropped = True
            continue
        if key:
            seen.add(key)
        out.append(p)
    return " ".join(out) if dropped else text


def cut_text(text: str, limit: int) -> str:
    """Обрезать до `limit` символов по границе предложения (иначе слова, с «…»)."""
    text = (text or "").strip()
    if limit <= 0 or len(text) <= limit:
        return text
    cut = text[:limit]
    end = max(cut.rfind(c) for c in ".!?…")
    if end >= limit * 0.5:
        return cut[:end + 1].rstrip()
    sp = cut.rfind(" ")
    return (cut[:sp] if sp >= limit * 0.5 else cut).rstrip() + "…"


def tidy_reply(action: str, speech: str):
    """Реплика -> (action, speech) без дословных повторов предложений и не длиннее
    MAX_ACTION_CHARS / MAX_SPEECH_CHARS."""
    return (cut_text(dedupe_sentences(action), MAX_ACTION_CHARS),
            cut_text(dedupe_sentences(speech), MAX_SPEECH_CHARS))


# ------------------------------------------------------------- планировщик ----
def last_speakers(entries: list, a: str, b: str) -> list:
    """Имена персонажей a/b в порядке от самого недавнего говорящего."""
    out = []
    for e in reversed(entries or []):
        for n in (a, b):
            if same(e.get("speaker"), n) and not any(same(n, x) for x in out):
                out.append(n)
    return out


def least_recent(a: str, b: str, entries: list) -> str:
    """Кто из двух персонажей говорил давнее (не говорил вовсе - тот первым;
    никто - a)."""
    recent = last_speakers(entries, a, b)
    if not recent:
        return a
    if len(recent) == 1:
        return other_char(recent[0], a, b)
    return recent[-1]


def after_hero(to: str, a: str, b: str, entries: list, solo: str = "") -> list:
    """Реплика героя -> очередь ОБЯЗАТЕЛЬНЫХ ответов. Адресован один персонаж -
    отвечает он; «всем»/не ясно - отвечают оба, первым тот, кто говорил давнее.
    `solo` - имя ЕДИНСТВЕННОГО незаглушённого персонажа: отвечает только он."""
    if solo:
        return [solo]
    if same(to, a):
        return [a]
    if same(to, b):
        return [b]
    first = least_recent(a, b, entries)
    return [first, other_char(first, a, b)]


def after_char(speaker: str, to: str, a: str, b: str, hero: str, queue: list,
               solo: str = ""):
    """Реплика персонажа -> что дальше: ("char", имя) / ("hero", имя) /
    ("stop", ""). Сначала очередь обязательных ответов (после «Всем» героя);
    потом по адресату: герою - ждём героя; другому персонажу или «всем» -
    отвечает другой персонаж. При `solo` (второй заглушён) другому отвечать
    некому: обратились к герою - ждём его, иначе цепочка просто заканчивается."""
    if solo:
        return ("hero", hero) if (hero and same(to, hero)) else ("stop", "")
    if queue:
        return "char", queue[0]
    if hero and same(to, hero):
        return "hero", hero
    return "char", other_char(speaker, a, b)


def pick_start(a: str, b: str, hero: str, entries: list):
    """Кто говорит первым при запуске автодиалога/«Шага». -> (имя, hero_skipped).
    Пустая сцена - персонаж a. Последним говорил герой - тот, к кому он
    обратился (иначе давнее говоривший). Последним говорил персонаж - другой
    (если реплика была адресована герою, герой «промолчал»)."""
    if not entries:
        return a, False
    last = entries[-1]
    spk = last.get("speaker")
    to = last.get("to")
    if same(spk, a) or same(spk, b):
        return other_char(spk, a, b), bool(hero) and same(to, hero)
    if same(to, a):
        return a, False
    if same(to, b):
        return b, False
    return least_recent(a, b, entries), False
