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
- Адресат реплики (`To`, см. TO_KEY) - поле JSON-ответа с enum из имён остальных участников
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
MAX_TOKENS = 600               # num_predict запроса реплики при длине по умолчанию (меньше - если в Settings задан меньший)
STREAM_CHAR_GUARD = 3500       # ответ длиннее (символов JSON) - обрываем стрим
MAX_SPEECH_CHARS = 550         # потолок речи «развёрнутой» реплики при длине по умолчанию (символов)
MAX_ACTION_CHARS = 300         # потолок действия при длине по умолчанию
HARD_SPEECH_CHARS = 2500       # абсолютный потолок речи при любой настройке

# Ключ адресата в JSON-схеме. С ЗАГЛАВНОЙ буквы не случайно: Ollama (Go)
# пересобирает схему через map и выдаёт поля ПО АЛФАВИТУ (проверено на 0.40:
# action, speech, to). Адресат последним терялся, когда ответ обрывался по
# num_predict («→ все» вместо имени). "To" < "action" по байтам -> адресат
# приходит ПЕРВЫМ. В записях истории ключ по-прежнему "to".
TO_KEY = "To"

# Длина реплики - СЛУЧАЙНАЯ на каждый ход (иначе 8B-модель пишет все реплики
# одинаково длинными «простынями»). Класс длины говорится модели в конце
# запроса (system-промпт не меняется -> кэш промпта жив) и подкрепляется
# лимитами: потолок речи (символов, режем по границе предложения) и num_predict.
# Средний потолок задаёт ползунок «Средняя длина реплики» на панели «Сцена»
# (REPLY_LEN_*, символов речи); все потолки классов масштабируются от него.
# По умолчанию ~340 (было 900, потом ~520 - длинно, потом 340 - коротковато).
# Русский текст у Ministral ~2.8 символа на токен.
REPLY_LEN_DEFAULT = 340
REPLY_LEN_MIN = 150
REPLY_LEN_MAX = 900
_BASE_SPEECH = {"short": 200, "medium": 380, "long": MAX_SPEECH_CHARS}   # при REPLY_LEN_DEFAULT
LENGTH_WEIGHTS = {"short": 40, "medium": 40, "long": 20}
_BASE_AVG = (sum(_BASE_SPEECH[k] * w for k, w in LENGTH_WEIGHTS.items())
             / sum(LENGTH_WEIGHTS.values()))                              # ~342
# предыдущая реплика короче - «короткий вопрос, короткий ответ»: чаще short
SHORT_CUE_CHARS = 160
LENGTH_WEIGHTS_AFTER_SHORT = {"short": 60, "medium": 32, "long": 8}

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


def clamp_reply_len(v) -> int:
    """Средняя длина реплики из настройки/ползунка: мусор/пусто -> дефолт,
    иначе в [REPLY_LEN_MIN, REPLY_LEN_MAX]."""
    if isinstance(v, str):
        v = v.strip()
        v = int(v) if v.lstrip("-").isdigit() else None
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        return REPLY_LEN_DEFAULT
    return max(REPLY_LEN_MIN, min(REPLY_LEN_MAX, int(round(v))))


def _scale(avg) -> float:
    return clamp_reply_len(avg) / _BASE_AVG


def length_limits(length: str, avg=REPLY_LEN_DEFAULT):
    """Класс длины + средняя длина (ползунок) -> (потолок речи в символах,
    num_predict). Неизвестный класс - как «развёрнутая». num_predict - с
    запасом на JSON и действие (~2 символа на токен + 120)."""
    base = _BASE_SPEECH.get(length, _BASE_SPEECH["long"])
    cap = int(round(base * _scale(avg) / 10.0)) * 10
    return cap, cap // 2 + 120


def action_limit(avg=REPLY_LEN_DEFAULT) -> int:
    """Потолок действия: MAX_ACTION_CHARS при длине по умолчанию, масштабом
    вместе с речью, но в пределах 150..700."""
    return max(150, min(700, int(MAX_ACTION_CHARS * _scale(avg))))


# Таблица классов при длине по умолчанию (для справки/тестов):
# класс -> (потолок речи, num_predict)
LENGTHS = {k: length_limits(k) for k in _BASE_SPEECH}


def _sentences(cap: int) -> int:
    """Сколько предложений речи просить у модели при потолке `cap` символов."""
    return max(1, int(round(cap / 95.0)))


def _ru_sent(n: int) -> str:
    """«не больше N предложения/предложений» (родительный падеж)."""
    return "предложения" if n % 10 == 1 and n % 100 != 11 else "предложений"


_LENGTH_LABEL = {
    "ru": {"short": "КОРОТКАЯ", "medium": "СРЕДНЯЯ", "long": "РАЗВЁРНУТАЯ"},
    "en": {"short": "SHORT", "medium": "MEDIUM", "long": "LONGER"},
}


def length_text(length: str, lang: str = "ru", avg=REPLY_LEN_DEFAULT) -> str:
    """Указание модели о длине реплики (класс из LENGTHS; неизвестный - "").
    Число предложений - от потолка класса при текущей средней длине."""
    if length not in _BASE_SPEECH:
        return ""
    n = _sentences(length_limits(length, avg)[0])
    en = _is_en(lang)
    lbl = _LENGTH_LABEL["en" if en else "ru"][length]
    if en:
        speech = f"no more than {n} sentence{'s' if n != 1 else ''}"
        if length == "short":
            speech += " (a single phrase or a couple of words is fine)"
        act = "one short sentence" if length == "short" else "one or two sentences"
        return (f"Length of this line - {lbl}: speech - {speech}, action - {act}. "
                "If the moment does not call for a long answer - answer even shorter.")
    speech = f"не больше {n} {_ru_sent(n)}"
    if length == "short":
        speech += " (можно одну фразу или пару слов)"
    act = "одно короткое предложение" if length == "short" else "одно-два предложения"
    return (f"Длина этой реплики - {lbl}: speech - {speech}, action - {act}. "
            "Если момент не требует длинного ответа - отвечай ещё короче.")


def pick_length(entries: list, speaker: str, rng=None, avg=REPLY_LEN_DEFAULT) -> str:
    """Случайный класс длины реплики для хода `speaker` (ключ LENGTHS).
    Предыдущая реплика короткая (короче SHORT_CUE_CHARS) - чаще короткий ответ.
    Прошлая реплика ЭТОГО ЖЕ персонажа была длинной (длиннее средней по
    текущей настройке `avg` с запасом) - длинной снова не будет (две
    «простыни» подряд от одного голоса)."""
    import random
    rng = rng or random
    entries = entries or []
    weights = dict(LENGTH_WEIGHTS)
    if entries and len(_body(entries[-1].get("content"))) < SHORT_CUE_CHARS:
        weights = dict(LENGTH_WEIGHTS_AFTER_SHORT)
    long_body = length_limits("medium", avg)[0] + int(150 * _scale(avg))
    for e in reversed(entries):
        if same(e.get("speaker"), speaker):
            if len(_body(e.get("content"))) > long_body:
                weights["long"] = 0
            break
    keys = [k for k in _BASE_SPEECH if weights.get(k, 0) > 0]
    return rng.choices(keys, weights=[weights[k] for k in keys])[0]


def directive(speaker: str, hero: str = "", lang: str = "ru", *, first: bool = False,
              addressed: bool = False, hero_skipped: bool = False,
              length: str = "", avg=REPLY_LEN_DEFAULT) -> str:
    """Что сказать модели В КОНЦЕ запроса: чей ход. `first` - сцена только
    начинается; `addressed` - последняя реплика адресована говорящему;
    `hero_skipped` - к герою обратились, а он промолчал; `length` - класс
    длины реплики (см. pick_length; "" - без указания)."""
    en = _is_en(lang)
    parts = []
    if en:
        parts.append(f"Now it is {speaker}'s turn. Write ONLY the line of {speaker} "
                     "(JSON); do not write lines of the other participants. speech - "
                     f"only {speaker}'s own words: no lines or quotes of others with "
                     "a tag like \"Name: «...»\" or \"«...» - Name\", no script; when "
                     "another participant should answer - end the line, they will "
                     "answer in their own turn.")
        if first:
            parts.insert(0, "The scene is just beginning.")
        if addressed:
            parts.append("The last line was addressed to you - react to it.")
        if hero_skipped and hero:
            parts.append(f"{hero} did not answer and stays silent.")
    else:
        parts.append(f"Теперь ход: {speaker}. Напиши ТОЛЬКО реплику {speaker} (JSON); "
                     "не пиши реплики других участников. В speech - только "
                     f"собственные слова {speaker}: никаких чужих реплик и цитат с "
                     "подписью вида «Имя: «...»» или ««...» - Имя», никакого "
                     "сценария; когда должен ответить другой участник - закончи "
                     "реплику, он ответит сам в свой ход.")
        if first:
            parts.insert(0, "Сцена только начинается.")
        if addressed:
            parts.append("Последняя реплика адресована тебе - отреагируй на неё.")
        if hero_skipped and hero:
            parts.append(f"{hero} не ответил и молчит.")
    lt = length_text(length, lang, avg)
    if lt:
        parts.append(lt)
    return " ".join(parts)


def build_user_message(entries: list, speaker: str, hero: str = "", lang: str = "ru", *,
                       hero_skipped: bool = False, length: str = "",
                       avg=REPLY_LEN_DEFAULT) -> str:
    """Единственное user-сообщение запроса: стенограмма + директива «чей ход»
    (+ длина реплики, если задан класс `length`)."""
    en = _is_en(lang)
    last = entries[-1] if entries else None
    addressed = bool(last) and same(last.get("to"), speaker)
    head = ("Scene transcript (latest lines):" if en
            else "Стенограмма сцены (последние реплики):")
    return (f"{head}\n{transcript(entries, lang)}\n\n"
            + directive(speaker, hero, lang, first=not entries, addressed=addressed,
                        hero_skipped=hero_skipped, length=length, avg=avg))


# ---------------------------------------------------- схема и разбор ответа ----
def group_schema(others: list, lang: str = "ru", allow_all: bool = True) -> dict:
    """JSON-схема ответа (structured outputs). Адресат (TO_KEY="To") идёт
    ПЕРВЫМ (Ollama сортирует поля по алфавиту): сначала модель решает, кому
    говорит, потом пишет реплику; значение - только имя из
    `others` или «все» (enum). `allow_all=False` - один персонаж заглушён:
    говорить можно ТОЛЬКО с героем, «все» в списке нет."""
    choices = [n for n in others if str(n).strip()] + ([all_token(lang)] if allow_all else [])
    return {
        "type": "object",
        "properties": {
            TO_KEY: {"type": "string", "enum": choices},
            "action": {"type": "string"},
            "speech": {"type": "string"},
        },
        "required": [TO_KEY, "action", "speech"],
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
    partial = False
    try:
        data = json.loads(raw)
    except (ValueError, TypeError):
        partial = True
        try:
            from ollama_client import _partial_json_fields
            data = _partial_json_fields(raw)
        except Exception:
            data = None
    if isinstance(data, dict):
        def _s(k):
            v = data.get(k)
            return str(v).strip() if isinstance(v, (str, int, float)) and not isinstance(v, bool) else ""
        action, speech = _s("action"), _s("speech")
        if partial:          # ответ оборван лимитом: недописанное предложение - прочь
            if speech:
                speech = drop_unfinished_tail(speech)
            elif action:
                action = drop_unfinished_tail(action)
        return normalize_to(_s(TO_KEY) or _s("to"), others, lang), action, speech
    return "", "", raw


def has_to(text: str) -> bool:
    """В сыром ответе модели есть непустое поле адресата (в т.ч. «все»)."""
    return bool(re.search(r'"(?:%s|to)"\s*:\s*"[^"\s]' % TO_KEY, text or ""))


def guess_to(speech: str, others: list, entries: list, use_last: bool = True) -> str:
    """Адресат «все»/не пришёл (ответ оборван до поля) - уточняем по тексту.
    -> имя из `others` или "".
    1) обращение по имени: имя участника, за которым идёт запятая/«!»/«?»
       («Лайрис, ты знаешь...», «...правда, Шелти?»); несколько - самое раннее;
    2) иначе (`use_last` - поля адресата в ответе НЕ было) - тот, кто говорил
       последним (отвечают обычно ему), если он среди `others`."""
    text = speech or ""
    best = None
    for n in others or []:
        keys = sorted(_name_keys([n]), key=len, reverse=True)
        for k in keys:
            m = re.search(r"(?<![\w-])" + re.escape(k) + r"(?=\s*[,!?])", text, re.I)
            if m and (best is None or m.start() < best[0]):
                best = (m.start(), n)
    if best:
        return best[1]
    if not use_last:
        return ""
    for e in reversed(entries or []):
        spk = e.get("speaker")
        if spk:
            for n in others or []:
                if same(spk, n):
                    return n
            return ""
    return ""


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


_SENT_END = ".!?…"
_OPEN_Q = "«“„\""
_CLOSE_Q = "»”\""


def _name_keys(names) -> set:
    """Имена участников -> набор для сравнения: полное имя и каждое слово
    имени длиной от 3 букв («Виктар Велес» -> {"виктар велес", "виктар",
    "велес"}), в нижнем регистре."""
    keys = set()
    for n in names or []:
        n = _norm(n)
        if not n:
            continue
        keys.add(n)
        keys.update(w for w in n.split() if len(w) >= 3)
    return keys


def _sentence_start(text: str, pos: int) -> int:
    """Начало предложения, в котором стоит позиция `pos` (сразу после
    ближайшего знака конца предложения или перевода строки левее)."""
    i = pos
    while i > 0 and text[i - 1] not in _SENT_END + "\n":
        i -= 1
    return i


_ATTR_AFTER = re.compile(r"[»”\"]\s*[—–-]{1,2}\s*([^\W\d_][\w-]*(?:\s+[^\W\d_][\w-]*)?)")
_ATTR_BEFORE = re.compile(r"([^\W\d_][\w-]*(?:\s+[^\W\d_][\w-]*)?)\s*(?::|→)\s*")


def cut_foreign_lines(speech: str, names) -> tuple:
    """Модель иногда пишет в speech «сценарий» - реплики других участников с
    подписью: `Собака: «Да, Хозяин!» — Шелти. ...` или `Шелти: «...»`. Такой
    текст - уже не слова говорящего. Режем speech до начала первого
    предложения с подписанной репликой. -> (текст, обрезано ли).

    Признаки (`names` - имена ВСЕХ участников, включая говорящего: подпись
    своей же реплики после чужой - тоже признак сценария):
    - цитата и после неё тире с именем участника: `«...» — Шелти`;
    - имя участника в начале предложения и двоеточие/стрелка: `Шелти: ...`,
      `Шелти → Лайрис: ...` (как в стенограмме).
    Обычные обращения («Шелти, ты...») и цитаты без подписи не трогаем. Если
    обрезать пришлось бы всё - оставляем текст как есть (хуже не делаем)."""
    text = (speech or "").strip()
    keys = _name_keys(names)
    if not text or not keys:
        return text, False
    cut_at = None
    for m in _ATTR_AFTER.finditer(text):
        words = m.group(1).split()
        if _norm(m.group(1)) in keys or (words and _norm(words[0]) in keys):
            q = max(text.rfind(c, 0, m.start()) for c in _OPEN_Q)
            start = _sentence_start(text, q if q >= 0 else m.start())
            cut_at = start if cut_at is None else min(cut_at, start)
            break
    for m in _ATTR_BEFORE.finditer(text):
        if cut_at is not None and m.start() >= cut_at:
            break
        name = m.group(1)
        is_name = _norm(name) in keys or all(_norm(w) in keys for w in name.split())
        at_start = not text[_sentence_start(text, m.start()):m.start()].strip()
        if is_name and at_start:
            cut_at = m.start()
            break
    if cut_at is None:
        return text, False
    kept = text[:cut_at].rstrip()
    if not kept:
        return text, False
    return kept, True


def drop_unfinished_tail(text: str) -> str:
    """Ответ оборван лимитом (оборванный JSON): последнее предложение
    недописано («...боль будет сильнее. Крик»). Убираем хвост до последнего
    законченного предложения; если законченных нет - ставим «…»."""
    text = (text or "").rstrip()
    if not text or text[-1] in _SENT_END + _CLOSE_Q + ")*":
        return text
    end = max(text.rfind(c) for c in _SENT_END)
    if end >= 0:
        # закрывающая кавычка/скобка сразу после знака - часть предложения
        while end + 1 < len(text) and text[end + 1] in _CLOSE_Q + ")":
            end += 1
        return text[:end + 1].rstrip()
    return text + "…"


def tidy_reply(action: str, speech: str, speech_limit: int = MAX_SPEECH_CHARS,
               action_limit_: int = MAX_ACTION_CHARS):
    """Реплика -> (action, speech) без дословных повторов предложений и не длиннее
    `action_limit_` / `speech_limit` (потолки класса длины при текущей средней
    длине; мусор -> потолки по умолчанию; речь не длиннее HARD_SPEECH_CHARS)."""
    def _lim(v, default):
        ok = isinstance(v, int) and not isinstance(v, bool) and v > 0
        return min(v if ok else default, HARD_SPEECH_CHARS)
    return (cut_text(dedupe_sentences(action), _lim(action_limit_, MAX_ACTION_CHARS)),
            cut_text(dedupe_sentences(speech), _lim(speech_limit, MAX_SPEECH_CHARS)))


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
