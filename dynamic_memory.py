"""
Динамическая память персонажа-собеседника: краткий, ограниченный по размеру
список самого важного, что с ним случилось и как он изменился. Хранится в
самом пресете персонажа (`Character.dyn_memory`), подставляется в его блок
системного промпта и переживает отдельные диалоги.

Память СТРУКТУРИРОВАНА - пять фиксированных разделов (SECTIONS):
    relationships  - Изменения отношений
    appearance     - Изменения внешности
    personality    - Изменения характера
    key_events     - Важные события (долговременные)
    recent_events  - Недавние события (короткоживущие)

Почему так. Когда память переписывалась свободным текстом, за сотни реплик
структура «уплывала». Теперь:
- модель отвечает JSON-объектом по схеме DYN_SCHEMA (structured outputs
  Ollama): разделы гарантированы самим форматом;
- хранится и показывается пользователю обычный текст с заголовками разделов
  (его можно править руками), а код при КАЖДОМ обновлении разбирает его на
  разделы (parse_text) и собирает заново (render) - структура не может
  потеряться, даже если пользователь правил текст или он остался от старой
  версии (старый «плоский» список попадает в «Важные события»).

Чистая логика без tkinter (тестируется отдельно): промпт для скрытого запроса,
схема, разбор/сборка текста, разбор ответа модели и жёсткий предел размера.
Когда и как запросы запускаются - в gui.App (`_dyn_*`).

Принципы:
- вход запроса - ТОЛЬКО новые сводки памяти диалога + текущая динамическая
  память (вход ограничен и от длины диалога не зависит);
- модель решает, есть ли что-то важное (`important_changes`): нет - память не
  трогаем (не дублируем память диалога каждый раз);
- размер ограничен (`DYN_MEMORY_LIMIT`, настройка): просим модель уложиться, а
  переполнение режем в коде (самые старые пункты крупнейшего раздела);
- подозрительный ответ (память «усохла» без нужды - обычно сломанный ответ
  слабой модели) отвергается, старая память остаётся.
"""
import json
import re

DYN_MEMORY_LIMIT = 8000        # дефолт предела, символов; выше память не растёт
DYN_LIMIT_MIN = 500            # допустимые границы настройки «Предел динамической памяти»
DYN_LIMIT_MAX = 30000
OLD_DEFAULT_LIMIT = 4000       # прежний дефолт; в сохранённых настройках читается как новый
DYN_NEW_MAX_ITEMS = 8          # сколько необработанных сводок держим (вход запроса ограничен)
RECENT_MAX_ITEMS = 6           # «Недавние события» - не больше стольких пунктов
SHRINK_GUARD_FROM = 600        # короче текущая память - защиту от «усыхания» не применяем
SHRINK_GUARD_RATIO = 0.4       # новый текст < 40 % старого - подозрительно...
SHRINK_GUARD_FULL = 0.9        # ...если только старая не была почти у предела (тогда сжатие ожидаемо)

SECTIONS = ("relationships", "appearance", "personality", "key_events", "recent_events")
TITLES = {
    "ru": {"relationships": "Изменения отношений", "appearance": "Изменения внешности",
           "personality": "Изменения характера", "key_events": "Важные события",
           "recent_events": "Недавние события"},
    "en": {"relationships": "Relationship changes", "appearance": "Appearance changes",
           "personality": "Personality changes", "key_events": "Key events",
           "recent_events": "Recent events"},
}
# для разбора заголовков: любые из названий (RU/EN) и ключей, без регистра
_ALIASES = {}
for _lang_titles in TITLES.values():
    for _k, _v in _lang_titles.items():
        _ALIASES[_v.lower()] = _k
for _k in SECTIONS:
    _ALIASES[_k] = _k

# Схема structured outputs (payload["format"]). `important_changes` идёт ПЕРВЫМ:
# модель сначала решает, есть ли что записывать, и только потом пишет разделы.
DYN_SCHEMA = {
    "type": "object",
    "properties": {
        "important_changes": {"type": "boolean"},
        **{k: {"type": "array", "items": {"type": "string"}} for k in SECTIONS},
    },
    "required": ["important_changes", *SECTIONS],
    "additionalProperties": False,
}

NO_CHANGES = "НЕТ_ИЗМЕНЕНИЙ"          # запасной текстовый маркер (если модель не держит JSON)
_NO_CHANGES_RE = re.compile(
    r"^\W*(НЕТ[_\s-]*ИЗМЕНЕНИЙ|NO[_\s-]*CHANGES?)\W*$", re.IGNORECASE)

# ---- промпт: ПРАВИЛА (редактируются пользователем) + ФОРМАТ (фиксированный) ----
DYN_RULES = (
    "Ты ведёшь «динамическую память» персонажа ролевой игры: краткую запись "
    "САМОГО ВАЖНОГО о том, что с персонажем произошло и как он изменился. Тебе "
    "дают текущую память и новые события диалога.\n"
    "Разделы памяти:\n"
    "- relationships — как изменились отношения персонажа с другими (с кем и как: "
    "сблизились, поссорились, стали доверять, появилась вражда, обещания и долги);\n"
    "- appearance — изменения внешности (шрамы, причёска, одежда, состояние тела);\n"
    "- personality — изменения характера, взглядов, привычек, целей и страхов;\n"
    "- key_events — важные долговременные события, которые персонаж помнит и которые "
    "влияют на дальнейший сюжет (тайны, решения, потери, достижения, незакрытые линии);\n"
    "- recent_events — ТОЛЬКО самые недавние события (не больше {recent} коротких "
    "пунктов). Когда событие устарело: если оно важно надолго — перенеси его в "
    "key_events (или в нужный раздел), иначе удали.\n"
    "Правила: пиши кратко, одним коротким предложением на пункт, только факты, без "
    "вступлений и домыслов. Сохраняй важное из старой памяти, объединяй повторы, "
    "убирай устаревшее и мелочи. Не выдумывай того, чего не было в событиях. "
    "Если в новых событиях нет ничего важного для истории персонажа (обычный "
    "разговор, мелочи) — поставь important_changes=false. Общий объём памяти — не "
    "более {limit} символов; если места не хватает, сокращай самое мелкое и старое."
)
DYN_RULES_EN = (
    "You keep the “dynamic memory” of a roleplay character: a brief record of "
    "ONLY THE MOST IMPORTANT things that happened to the character and how they "
    "changed. You are given the current memory and new events of the dialogue.\n"
    "Memory sections:\n"
    "- relationships — how the character's relationships with others changed (with "
    "whom and how: grew closer, quarrelled, came to trust, new enmity, promises and "
    "debts);\n"
    "- appearance — changes in appearance (scars, hairstyle, clothes, bodily state);\n"
    "- personality — changes in character, views, habits, goals and fears;\n"
    "- key_events — important long-term events the character remembers and that "
    "affect the plot (secrets, decisions, losses, achievements, open threads);\n"
    "- recent_events — ONLY the most recent events (at most {recent} short items). "
    "When an event gets stale: if it matters long-term, move it to key_events (or the "
    "proper section), otherwise drop it.\n"
    "Rules: be brief, one short sentence per item, facts only, no preamble or "
    "speculation. Keep what matters from the old memory, merge repetition, drop "
    "outdated items and trivia. Do not invent anything absent from the events. If "
    "the new events contain nothing important for the character's story (ordinary "
    "talk, trivia) — set important_changes=false. The whole memory must stay within "
    "{limit} characters; when short of space, shorten the smallest and oldest first."
)
_FORMAT_SPEC = (
    "\n\nФормат ответа — ТОЛЬКО JSON-объект без пояснений и без markdown: "
    "{\"important_changes\": true|false, \"relationships\": [строки], "
    "\"appearance\": [строки], \"personality\": [строки], \"key_events\": [строки], "
    "\"recent_events\": [строки]}. Всегда выводи ПОЛНУЮ обновлённую память "
    "(все разделы целиком, а не только новое); пустой раздел — пустой список."
)
_FORMAT_SPEC_EN = (
    "\n\nAnswer format — ONLY a JSON object with no explanations and no markdown: "
    "{\"important_changes\": true|false, \"relationships\": [strings], "
    "\"appearance\": [strings], \"personality\": [strings], \"key_events\": [strings], "
    "\"recent_events\": [strings]}. Always output the FULL updated memory (every "
    "section in full, not only the new items); an empty section is an empty list."
)


def _is_en(lang) -> bool:
    return (lang or "ru").lower().startswith("en")


def default_rules(lang: str = "ru") -> str:
    """Стандартный текст правил (его показывает окно правки промпта)."""
    return DYN_RULES_EN if _is_en(lang) else DYN_RULES


def builtin_rules() -> set:
    """Встроенные тексты правил на всех языках (чтобы не хранить дефолт как «свой»)."""
    return {DYN_RULES.strip(), DYN_RULES_EN.strip()}


def clamp_limit(v) -> int:
    """Предел из настройки -> число в [DYN_LIMIT_MIN, DYN_LIMIT_MAX]; пусто /
    мусор / bool -> DYN_MEMORY_LIMIT; прежний дефолт 4000 -> новый дефолт."""
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        return DYN_MEMORY_LIMIT
    if int(v) == OLD_DEFAULT_LIMIT:
        return DYN_MEMORY_LIMIT
    return max(DYN_LIMIT_MIN, min(DYN_LIMIT_MAX, int(v)))


# ----------------------------------------------------------- разделы <-> текст ----
def empty_sections() -> dict:
    return {k: [] for k in SECTIONS}


_BULLET_RE = re.compile(r"^\s*(?:[-*•·]+|\d+[.)])\s*")
_HEAD_RE = re.compile(r"^\s*(?:#{1,6}\s*)?(.+?)\s*:?\s*$")


def _clean_item(s) -> str:
    s = _BULLET_RE.sub("", str(s)).strip()
    return re.sub(r"\s+", " ", s)


def _dedupe(items) -> list:
    seen, out = set(), []
    for it in items:
        it = _clean_item(it)
        key = it.lower()
        if it and key not in seen:
            seen.add(key)
            out.append(it)
    return out


def parse_text(text: str) -> dict:
    """Текст памяти -> {раздел: [пункты]}. Понимает заголовки разделов (с `#`
    или без, RU/EN, с двоеточием или без) и маркеры пунктов; строки ДО первого
    заголовка (старая «плоская» память, свободный текст) попадают в
    key_events - ничего не теряется."""
    out = empty_sections()
    cur = "key_events"
    for raw in (text or "").splitlines():
        line = raw.strip()
        if not line:
            continue
        m = _HEAD_RE.match(line)
        if m:                                   # «- пункт» сюда не попадёт: дефис остаётся в тексте
            key = _ALIASES.get(m.group(1).strip().rstrip(":").lower())
            if key:
                cur = key
                continue
        item = _clean_item(line)
        if item:
            out[cur].append(item)
    return {k: _dedupe(v) for k, v in out.items()}


def render(sections: dict, lang: str = "ru") -> str:
    """{раздел: [пункты]} -> текст памяти (пустые разделы пропускаются)."""
    titles = TITLES["en" if _is_en(lang) else "ru"]
    blocks = []
    for k in SECTIONS:
        items = _dedupe((sections or {}).get(k) or [])
        if items:
            blocks.append(f"### {titles[k]}\n" + "\n".join(f"- {it}" for it in items))
    return "\n\n".join(blocks)


def normalize_text(text: str, lang: str = "ru", limit: int = DYN_MEMORY_LIMIT) -> str:
    """Привести любой текст памяти к каноническому виду (разделы + лимит)."""
    return render(fit_sections(parse_text(text), limit, lang), lang)


def fit_sections(sections: dict, limit: int = DYN_MEMORY_LIMIT, lang: str = "ru") -> dict:
    """Уложить память в `limit` символов (в отрисованном виде). Сначала
    «Недавние события» режутся до RECENT_MAX_ITEMS (остаются последние), затем,
    пока не влезает, у самого ОБЪЁМНОГО раздела отбрасывается самый старый
    (первый) пункт; последний пункт, если и он не лезет, обрезается по слову."""
    secs = {k: _dedupe((sections or {}).get(k) or []) for k in SECTIONS}
    secs["recent_events"] = secs["recent_events"][-RECENT_MAX_ITEMS:]
    if limit <= 0:
        return secs
    while len(render(secs, lang)) > limit:
        sized = [(sum(len(i) + 4 for i in v), k) for k, v in secs.items() if v]
        if not sized:
            break
        _, k = max(sized)
        if len(secs[k]) > 1:
            secs[k].pop(0)
            continue
        # в самом объёмном разделе один пункт - режем его текст
        over = len(render(secs, lang)) - limit
        item = secs[k][0]
        cut = item[:max(1, len(item) - over - 1)]
        sp = cut.rfind(" ")
        if sp > len(cut) // 2:
            cut = cut[:sp]
        secs[k][0] = cut.rstrip() + "…" if cut else ""
        if not cut or len(render(secs, lang)) > limit:
            secs[k] = []
    return secs


# ------------------------------------------------------------------- запрос ----
def build_messages(char_name: str, protagonist_name: str, current: str,
                   new_events: list, limit: int = DYN_MEMORY_LIMIT,
                   lang: str = "ru", rules: str = "") -> list:
    """messages для скрытого запроса. `current` - текущий текст памяти (любой
    вид: разберётся parse_text); `new_events` - новые сводки памяти диалога
    (берётся не больше DYN_NEW_MAX_ITEMS последних). `rules` - свои правила
    (промпт персонажа); пусто -> стандартные. Формат ответа добавляется ВСЕГДА
    и не редактируется."""
    en = _is_en(lang)
    events = "\n\n".join(e.strip() for e in (new_events or [])[-DYN_NEW_MAX_ITEMS:]
                         if e and e.strip())
    cur = parse_text(current)
    cur_json = json.dumps({k: cur[k] for k in SECTIONS}, ensure_ascii=False, indent=1)
    base = (rules or "").strip() or default_rules(lang)
    system = (base.replace("{limit}", str(limit)).replace("{recent}", str(RECENT_MAX_ITEMS))
              + (_FORMAT_SPEC_EN if en else _FORMAT_SPEC))
    if en:
        who = (f"Character: “{char_name or 'unnamed'}”."
               + (f" The protagonist (the player) is “{protagonist_name}”."
                  if protagonist_name else ""))
        user = (f"{who}\n\nCurrent dynamic memory (JSON):\n{cur_json}\n\n"
                f"New events of the dialogue:\n{events}\n\nUpdated dynamic memory (JSON):")
    else:
        who = (f"Персонаж: «{char_name or 'без имени'}»."
               + (f" Главный герой (игрок): «{protagonist_name}»."
                  if protagonist_name else ""))
        user = (f"{who}\n\nТекущая динамическая память (JSON):\n{cur_json}\n\n"
                f"Новые события диалога:\n{events}\n\nОбновлённая динамическая память (JSON):")
    return [{"role": "system", "content": system}, {"role": "user", "content": user}]


# ------------------------------------------------------------ разбор ответа ----
def _clean(text: str) -> str:
    t = (text or "").strip()
    if t.startswith("```"):                       # ответ в блоке кода
        t = re.sub(r"^```[a-zA-Z]*\s*", "", t)
        t = re.sub(r"\s*```$", "", t)
    return t.strip()


def _parse_json_object(text: str):
    """Первый JSON-объект в тексте или None."""
    i = text.find("{")
    if i < 0:
        return None
    try:
        obj, _ = json.JSONDecoder().raw_decode(text[i:])
    except ValueError:
        return None
    return obj if isinstance(obj, dict) else None


def interpret_reply(reply, current: str, limit: int = DYN_MEMORY_LIMIT, lang: str = "ru"):
    """Ответ модели -> (статус, текст):
        ("fail", current)    - пусто / нет разбираемого ответа (новые события
                               остаются необработанными - повторим позже);
        ("same", current)    - important_changes=false, НЕТ_ИЗМЕНЕНИЙ, ничего не
                               изменилось или подозрительный ответ: память не
                               меняем, события считаются обработанными;
        ("changed", новый)   - новая память: канонический текст с разделами,
                               уже уложенный в limit."""
    cur = (current or "").strip()
    if reply is None or not str(reply).strip():
        return "fail", cur
    text = _clean(str(reply))
    if not text:
        return "fail", cur
    if _NO_CHANGES_RE.match(text.split("\n", 1)[0].strip()):
        return "same", cur
    obj = _parse_json_object(text)
    if obj is not None:
        if obj.get("important_changes") is False:
            return "same", cur
        secs = empty_sections()
        found = False
        for k in SECTIONS:
            v = obj.get(k)
            if isinstance(v, list):
                found = True
                secs[k] = [x for x in v if isinstance(x, (str, int, float))
                           and not isinstance(x, bool)]
            elif isinstance(v, str) and v.strip():       # раздел строкой вместо списка
                found = True
                secs[k] = v.splitlines()
        if not found:
            return "fail", cur
    elif text.lstrip().startswith(("{", "[")):
        return "fail", cur                                # обрезанный/сломанный JSON
    else:                                                 # модель ответила текстом
        text = "\n".join(ln for ln in text.split("\n")
                         if not _NO_CHANGES_RE.match(ln.strip())).strip()
        if not text:
            return "same", cur
        secs = parse_text(text)
        if not any(secs.values()):
            return "fail", cur
    new = render(fit_sections(secs, limit, lang), lang)
    if not new:
        return "same", cur                                # всё пусто - не стираем память
    cur_norm = render(fit_sections(parse_text(cur), limit, lang), lang)
    if new == cur_norm:
        return "same", cur
    if (len(cur_norm) > SHRINK_GUARD_FROM and len(cur_norm) < limit * SHRINK_GUARD_FULL
            and len(new) < len(cur_norm) * SHRINK_GUARD_RATIO):
        return "same", cur                                # память не должна «усыхать» без причины
    return "changed", new
