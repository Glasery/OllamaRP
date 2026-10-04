"""
Сборка system-промпта из блоков сцены.

Это "секретный соус" всего приложения - вся кастомизация ролплея
происходит здесь, а не в коде GUI или сетевого клиента. Если захочешь
поменять стиль поведения бота - смотри сюда в первую очередь.

Порядок блоков в промпте:
  0. «наталкивание» на ризонинг (если reasoning_nudge=True) - самый верх
  1. system_config.content  (общие правила, если заданы)
  2. инструкции режима      (DIALOGUE_INSTRUCTIONS / STORY_INSTRUCTIONS)
  3. Главный герой (Вы)     (если задан)
  4. Персонаж(и)            (в story может быть несколько)
  5. Окружение              (в story не передаётся - локации там меняются)
  6. Сценарий
  7. Параметры истории      (только story: размер + доп. детали)
"""
import difflib
import re
from typing import List, Optional


def _is_en(lang) -> bool:
    return str(lang).strip().lower() in ("en", "eng", "english")


def norm_line(s: str) -> str:
    """Текст для сравнения на повтор: строчные буквы, без пунктуации, пробелы
    схлопнуты. «Ты... выжила?!» и «ты выжила» станут одинаковыми."""
    s = re.sub(r"[^\w\s]", " ", (s or "").lower(), flags=re.UNICODE)
    return re.sub(r"\s+", " ", s).strip()


def speech_of(content: str) -> str:
    """Из канонической записи хода «*действие*\\nречь» вернуть только РЕЧЬ
    (строки целиком в *...* считаются действием и отбрасываются)."""
    keep = [ln for ln in (content or "").split("\n")
            if not (ln.strip().startswith("*") and ln.strip().endswith("*")
                    and len(ln.strip()) > 1)]
    return "\n".join(keep).strip()


def is_duplicate_speech(speech: str, history: list, *, window: int = 8,
                        ratio: float = 0.86, min_len: int = 24) -> bool:
    """Речевая часть `speech` почти дословно повторяет одну из последних
    `window` реплик персонажа (role == "assistant") в `history`. Короткие
    реплики («Да.», «Хорошо.») не проверяем - там повтор естественен."""
    cur = norm_line(speech)
    if len(cur) < min_len:
        return False
    seen = 0
    for m in reversed(history):
        if m.get("role") != "assistant":
            continue
        prev = norm_line(speech_of(m.get("content") or ""))
        if len(prev) >= min_len and \
                difflib.SequenceMatcher(None, cur, prev).ratio() >= ratio:
            return True
        seen += 1
        if seen >= window:
            break
    return False


def find_repeat_loop(text: str, *, tail_check: int = 10, window: int = 30,
                     ratio: float = 0.85, min_block_len: int = 12,
                     min_hits: int = 3) -> Optional[str]:
    """Проверяет ХВОСТ текста на зацикливание - модель повторяет одни и те
    же абзацы снова и снова. Типичная деградация при генерации ДЛИННЫХ
    историй (`num_predict=-1`): штраф за повтор (`repeat_last_n`) слишком
    узкий и не покрывает период цикла.

    Абзацы - это строки текста, разбитые по любому числу переводов строк
    (работает и с "\\n", и с "\\n\\n"). НЕ предполагает строгий фиксированный
    период - в реальности модель может «ротировать» несколько похожих
    шаблонов вперемешку (абзац действия / реплика А / реплика Б идут не
    строго по кругу, а вразнобой), да ещё и через вставленные заголовки
    глав/разделители («---», «**Заголовок**»), которые сбивают любой
    жёсткий период. Поэтому вместо периода проверяем ПОХОЖЕСТЬ: для каждого
    из последних `tail_check` абзацев ищем среди `window` предыдущих
    абзацев хоть один почти такой же (ratio >= `ratio`). Если таких
    «абзацев-повторов» среди хвоста набралось `min_hits` и больше - текст
    зациклен. Короткие абзацы (< `min_block_len` символов после
    нормализации - реплики вроде "Да.", разделители "---") в сравнение не
    берём вообще (ни как проверяемые, ни как эталон), чтобы не ловить
    естественный короткий обмен репликами и не путать разметку с текстом.

    При обнаружении возвращает текст ДО первого абзаца-повтора в хвосте
    (то, что стоит СОХРАНИТЬ, отбросив всё дальше), склеенный "\\n\\n".
    Если зацикливания нет - None.
    """
    blocks = [b.strip() for b in re.split(r"\n+", text) if b.strip()]
    n = len(blocks)
    if n <= min_hits:
        return None
    win_start = max(0, n - window)
    check_start = max(win_start, n - tail_check, 1)
    hits = 0
    first_dup_idx = None
    for i in range(check_start, n):
        b = norm_line(blocks[i])
        if len(b) < min_block_len:
            continue
        for j in range(win_start, i):
            a = norm_line(blocks[j])
            if len(a) < min_block_len:
                continue
            if difflib.SequenceMatcher(None, a, b).ratio() >= ratio:
                hits += 1
                if first_dup_idx is None:
                    first_dup_idx = i
                break
    if hits < min_hits:
        return None
    return "\n\n".join(blocks[:first_dup_idx])


def estimate_tokens(messages: list) -> int:
    """
    Грубая ВЕРХНЯЯ оценка числа токенов в списке сообщений (без обращения к
    токенизатору - его тут нет). Настроена «с запасом» под кириллицу: она
    у BPE-токенизаторов тяжелее, ~2.5-3.5 символа на токен. Берём 2.5 +
    ~4 токена на сообщение (роль-маркеры шаблона). Нужна, чтобы ЗАРАНЕЕ
    прикинуть, влезет ли запрос в num_ctx, и предупредить пользователя.
    """
    chars = sum(len(m.get("content") or "") for m in messages)
    return int(chars / 2.5) + 4 * len(messages) + 8


def next_num_ctx(need: int) -> int:
    """Ближайшая «стандартная» величина контекста (степень двойки) не
    меньше `need`; нижняя граница 8192, разумный потолок 131072."""
    n = 8192
    while n < need and n < 131072:
        n *= 2
    return n


from models import Character, Protagonist, Environment, Scenario, SystemConfig

# Для моделей БЕЗ официальной capability "thinking" (Ollama не умеет
# отделить их размышления в message.thinking). Просим рассуждать инлайном
# в <think>...</think> - эти теги на выходе вырежет _ThinkSplitter и
# уведёт в панель Logs, в чат попадёт только реплика.
REASONING_NUDGE = (
    "Прежде чем ответить, порассуждай для себя в блоке <think>...</think>: "
    "оцени ситуацию, характер персонажа и что уместно сказать или сделать. "
    "Сразу после закрывающего </think> напиши ТОЛЬКО саму реплику и действия "
    "персонажа - без тегов, без разбора и без пояснений."
)
REASONING_NUDGE_EN = (
    "Before you answer, reason to yourself inside a <think>...</think> block: "
    "weigh the situation, the character's personality and what it is fitting to "
    "say or do. Right after the closing </think> write ONLY the character's "
    "line and actions - no tags, no analysis, no explanations."
)

# Режим structured_dialogue: жёсткое разделение действий и речи через JSON.
STRUCTURED_DIALOGUE_INSTRUCTIONS = (
    "Формат ответа строго раздельный. Верни JSON с двумя полями: "
    "\"action\" - что делает и что чувствует ИМЕННО отыгрываемый тобой "
    "персонаж, от третьего лица, без кавычек и без прямой речи; \"speech\" "
    "- только прямая речь этого персонажа, без описания действий. Ни в "
    "action, ни в speech не должно быть слов, мыслей или действий главного "
    "героя (игрока). Любое из полей может быть пустой строкой. Никакого "
    "текста вне JSON."
)
STRUCTURED_DIALOGUE_INSTRUCTIONS_EN = (
    "The reply format is strictly split. Return JSON with two fields: "
    "\"action\" - what the character YOU play does and feels, in the third "
    "person, without quotes and without direct speech; \"speech\" - only that "
    "character's direct speech, with no action description. Neither action nor "
    "speech may contain words, thoughts or actions of the protagonist (the "
    "player). Either field may be an empty string. No text outside the JSON."
)


def role_guard(characters, protagonist, lang="ru") -> str:
    """
    Явное напоминание: за кого модель пишет, а за кого - НИКОГДА. Помогает
    против «модель отвечает за главного героя». Пусто, если нет имён.
    """
    char_names = ", ".join(c.name.strip() for c in (characters or []) if c.name.strip())
    prot = protagonist.name.strip() if (protagonist and protagonist.name) else ""
    parts = []
    if _is_en(lang):
        if char_names:
            parts.append(f"In your reply you take the turn ONLY for: {char_names}.")
        if prot:
            parts.append(
                f"NEVER write or describe the lines, thoughts, feelings or "
                f"actions of «{prot}» - that is the protagonist, controlled by "
                f"the user. If speech or an action of «{prot}» appears in your "
                f"reply, that is a mistake; end the turn where it passes to "
                f"«{prot}» and wait for their line."
            )
        return " ".join(parts)
    if char_names:
        parts.append(f"В своём ответе ты ведёшь ход ТОЛЬКО за: {char_names}.")
    if prot:
        parts.append(
            f"НИКОГДА не пиши и не описывай реплики, мысли, чувства и действия "
            f"«{prot}» - это главный герой, им управляет пользователь. Если в "
            f"твоём ответе появляется речь или действие «{prot}» - это ошибка; "
            f"заканчивай ход там, где очередь переходит к «{prot}», и жди его "
            f"реплику."
        )
    return " ".join(parts)

STRUCTURED_DIALOGUE_SCHEMA = {
    "type": "object",
    "properties": {
        "action": {"type": "string"},
        "speech": {"type": "string"},
    },
    "required": ["action", "speech"],
}

# --- сжатие контекста: «бегущая память» ---
# Заголовок блока, под которым дайджест подставляется в system-промпт.
MEMORY_HEADER = "## Что уже происходило ранее (память)"
MEMORY_HEADER_EN = "## What has happened so far (memory)"


def memory_header(lang="ru") -> str:
    return MEMORY_HEADER_EN if _is_en(lang) else MEMORY_HEADER


DIGEST_SYSTEM = (
    "Ты ведёшь краткую память ролевого чата или истории. Обнови память, "
    "вписав новые события из блока ниже, и сохрани важное из старой памяти. "
    "Пиши по-русски, сжато, только факты: кто участники (явно помечай, кто "
    "ГЛАВНЫЙ ГЕРОЙ / игрок, а кто персонажи), где происходит, отношения "
    "между ними, ключевые события и решения, незакрытые линии. Ориентир по "
    "объёму - до ~15 коротких предложений. Верни ТОЛЬКО обновлённый текст "
    "памяти - без пояснений, без разметки, без вводных фраз."
)
DIGEST_SYSTEM_EN = (
    "You keep a brief memory of a roleplay chat or story. Update the memory "
    "by adding the new events from the block below and keeping what matters "
    "from the old memory. Write in English, compactly, facts only: who the "
    "participants are (mark clearly who is the PROTAGONIST / player and who "
    "are characters), where it takes place, the relationships between them, "
    "key events and decisions, open threads. Aim for up to ~15 short "
    "sentences. Return ONLY the updated memory text - no explanations, no "
    "markup, no preamble."
)


def digest_system(lang="ru") -> str:
    return DIGEST_SYSTEM_EN if _is_en(lang) else DIGEST_SYSTEM


def _convo(entries: list, en: bool) -> str:
    u_pre, a_pre = ("User: ", "Assistant: ") if en else ("Пользователь: ", "Ассистент: ")
    return "\n".join(
        (u_pre if m.get("role") == "user" else a_pre) + (m.get("content") or "")
        for m in entries
    )


def build_digest_messages(old_digest: str, entries: list,
                          system_prompt: str = "", lang="ru") -> list:
    """
    messages для скрытого запроса «обнови память»: текущий дайджест +
    выпавшие из окна ходы -> новый дайджест. entries - куски self.history
    ({"role": "user"|"assistant", "content": ...}). system_prompt - свой
    промпт вместо DIGEST_SYSTEM (пусто -> дефолт).
    """
    en = _is_en(lang)
    convo = _convo(entries, en)
    if en:
        user = (f"Current memory:\n{(old_digest or '').strip() or '(empty)'}\n\n"
                f"New events:\n{convo}\n\nUpdated memory:")
    else:
        user = (f"Текущая память:\n{(old_digest or '').strip() or '(пусто)'}\n\n"
                f"Новые события:\n{convo}\n\nОбновлённая память:")
    default_sys = DIGEST_SYSTEM_EN if en else DIGEST_SYSTEM
    return [{"role": "system", "content": (system_prompt or "").strip() or default_sys},
            {"role": "user", "content": user}]


# --- послойная память: сводка одного сегмента + периодическое уплотнение ---
# Сегмент = ровно N ходов диалога. Каждый сегмент сжимается РОВНО ОДИН раз и
# больше не пересобирается; когда недавних сводок накапливается больше
# `MEM_SEGMENTS_KEEP`, самые старые вливаются в «долговременную» память
# отдельным запросом. Так вход каждого скрытого запроса ограничен и не
# растёт с длиной диалога (см. gui.App._fold_segment).
SEGMENT_SUMMARY_SYSTEM = (
    "Ты ведёшь краткую память ролевого диалога. Тебе дают КУСОК недавних "
    "событий - реплики и действия. Сожми ТОЛЬКО этот кусок в несколько "
    "коротких предложений: кто что сделал и решил, изменения в отношениях, "
    "месте и обстановке, новые и незакрытые сюжетные линии. Только факты, "
    "без разметки и вводных фраз. Не повторяй то, что уже перечислено в "
    "блоке «Уже известно» - только новое. Ориентир по объёму - 4-8 коротких "
    "предложений."
)
SEGMENT_SUMMARY_SYSTEM_EN = (
    "You keep a brief memory of a roleplay dialogue. You are given a CHUNK of "
    "recent events - lines and actions. Compress ONLY this chunk into a few "
    "short sentences: who did and decided what, changes in relationships, "
    "place and setting, new and open plot threads. Facts only, no markup or "
    "preamble. Do not repeat what is already listed in the \"Already known\" "
    "block - only what is new. Aim for 4-8 short sentences."
)

CONSOLIDATE_SYSTEM = (
    "Ты ведёшь долговременную память ролевого диалога. Тебе дают текущую "
    "долговременную память и один или несколько блоков более старых событий. "
    "Слей их в одну связную память: сохрани все важные факты (кто участники "
    "и кто из них ГЛАВНЫЙ ГЕРОЙ / игрок, отношения между ними, ключевые "
    "решения и события, незакрытые линии), убери мелкие подробности и "
    "повторы. Только факты, без разметки и вводных фраз. Ориентир по объёму "
    "- до ~20 коротких предложений."
)
CONSOLIDATE_SYSTEM_EN = (
    "You keep a long-term memory of a roleplay dialogue. You are given the "
    "current long-term memory and one or more blocks of older events. Merge "
    "them into one coherent memory: keep every important fact (who the "
    "participants are and which one is the PROTAGONIST / player, the "
    "relationships between them, key decisions and events, open threads), "
    "drop minor detail and repetition. Facts only, no markup or preamble. "
    "Aim for up to ~20 short sentences."
)


def build_segment_summary_messages(known_memory: str, entries: list,
                                   system_prompt: str = "", lang="ru") -> list:
    """Сводка ОДНОГО сегмента (N ходов). `known_memory` - уже собранная
    память (даётся как контекст «не повторяй это»), НЕ пересобирается.
    `system_prompt` - своя инструкция вместо SEGMENT_SUMMARY_SYSTEM."""
    en = _is_en(lang)
    convo = _convo(entries, en)
    known = (known_memory or "").strip()
    if en:
        user = (f"Already known (do not repeat it):\n{known or '(nothing yet)'}\n\n"
                f"New events:\n{convo}\n\nA brief summary of ONLY the new events:")
    else:
        user = (f"Уже известно (не повторяй это):\n{known or '(пока ничего)'}\n\n"
                f"Новые события:\n{convo}\n\nКраткая сводка ТОЛЬКО новых событий:")
    default_sys = SEGMENT_SUMMARY_SYSTEM_EN if en else SEGMENT_SUMMARY_SYSTEM
    return [{"role": "system", "content": (system_prompt or "").strip() or default_sys},
            {"role": "user", "content": user}]


def build_consolidation_messages(mem_head: str, old_segments: list, lang="ru") -> list:
    """Влить старые сводки-сегменты в долговременную память `mem_head`.
    Вход ограничен: голова (~20 предложений) + пара коротких блоков."""
    en = _is_en(lang)
    blocks = "\n\n".join(s.strip() for s in (old_segments or []) if s and s.strip())
    head = (mem_head or "").strip()
    if en:
        user = (f"Long-term memory:\n{head or '(empty)'}\n\n"
                f"Older blocks to merge in:\n{blocks}\n\n"
                f"Merged long-term memory:")
    else:
        user = (f"Долговременная память:\n{head or '(пусто)'}\n\n"
                f"Старые блоки для вливания:\n{blocks}\n\n"
                f"Объединённая долговременная память:")
    default_sys = CONSOLIDATE_SYSTEM_EN if en else CONSOLIDATE_SYSTEM
    return [{"role": "system", "content": default_sys},
            {"role": "user", "content": user}]


# --- «Сжать пример»: сжатие куска текста ПОД ЗАДАННЫЙ ОБЪЁМ ------------------
# В отличие от памяти (её задача - максимально ужать), тут задача обратная:
# ужать РОВНО настолько, чтобы влезло в оставшийся контекст, и не больше -
# сохранив как можно больше конкретики. `target_words` задаёт ориентир; сам
# верхний предел держит `num_predict` в запросе (см. gui.App._compress_worker).
COMPRESS_SYSTEM = (
    "Ты сжимаешь фрагмент текста (диалог, историю или заметки), чтобы он "
    "уместился в ограниченный объём, но при этом СОХРАНИЛ максимум "
    "конкретики. Обязательно сохрани: имена и кто есть кто, места, "
    "хронологический порядок событий, важные реплики и решения (по смыслу, "
    "можно короче), изменения в отношениях, эмоциональные повороты, "
    "незакрытые линии, характерные детали. Убирай ТОЛЬКО явные повторы, "
    "воду, служебные пометки и мелкие незначимые реплики. Ничего не "
    "добавляй от себя и не оценивай. Пиши сплошным связным текстом от "
    "третьего лица, в хронологическом порядке, без разметки и заголовков. "
    "Отвечай СРАЗУ готовым пересказом - без рассуждений вслух и без блоков "
    "<think>. "
    "Ориентир по объёму - около {words} слов: можно меньше, только если "
    "сохранять действительно больше нечего, но НЕ больше."
)
COMPRESS_SYSTEM_EN = (
    "You compress a fragment of text (a dialogue, a story or notes) so it "
    "fits a limited size while KEEPING as much concrete detail as possible. "
    "Be sure to keep: names and who is who, places, the chronological order "
    "of events, important lines and decisions (paraphrased, may be shorter), "
    "changes in relationships, emotional beats, open threads, distinctive "
    "details. Remove ONLY obvious repetition, filler, service markers and "
    "minor throwaway lines. Do not add anything of your own and do not "
    "editorialize. Write as continuous coherent third-person prose, in "
    "chronological order, with no markup or headings. Answer with the "
    "finished retelling RIGHT AWAY - no reasoning out loud, no <think> "
    "blocks. "
    "Aim for about {words} words: fewer only if there really is nothing "
    "more worth keeping, but NOT more."
)


def build_compress_messages(text: str, target_words: int, lang="ru") -> list:
    """Один запрос: сжать `text` примерно до `target_words` слов, сохранив
    максимум деталей (для кнопки «Сжать пример»)."""
    en = _is_en(lang)
    w = max(40, int(target_words))
    sys = (COMPRESS_SYSTEM_EN if en else COMPRESS_SYSTEM).format(words=w)
    if en:
        user = (f"Fragment:\n{text.strip()}\n\n"
                f"Compressed retelling (~{w} words, maximum concrete detail):")
    else:
        user = (f"Фрагмент:\n{text.strip()}\n\n"
                f"Сжатый пересказ (~{w} слов, максимум конкретики):")
    return [{"role": "system", "content": sys},
            {"role": "user", "content": user}]


def digest_boundary(history_len: int, n_turns: int) -> int:
    """
    Индекс записи `history`, до которого всё должно быть свёрнуто в
    дайджест: конец последнего ПРОЙДЕННОГО N-ходового рубежа. Ход = 2
    записи (user + assistant). Память пересобирается только когда этот
    рубеж сдвигается (раз в N ходов), а не каждый ход.

    digest_boundary(0, 6)  -> 0
    digest_boundary(10, 6) -> 0    (5 ходов < 6)
    digest_boundary(12, 6) -> 12   (ровно 6 ходов)
    digest_boundary(22, 6) -> 12   (11 ходов -> рубеж всё ещё на 6)
    digest_boundary(24, 6) -> 24   (12 ходов -> новый рубеж)
    digest_boundary(24, 0) -> 0    (память выключена)
    """
    if n_turns <= 0:
        return 0
    total_turns = history_len // 2
    return (total_turns // n_turns) * n_turns * 2

DIALOGUE_INSTRUCTIONS = (
    "Ты играешь роль персонажа, описанного ниже, в текстовом ролплее с пользователем. "
    "Отвечай ТОЛЬКО репликами и действиями персонажа (действия можно оформлять в *звёздочках*), "
    "не выходи из роли и не пиши мета-комментариев от своего имени как ИИ. "
    "Учитывай окружение и ситуацию ниже - персонаж должен реагировать на них правдоподобно. "
    "Отвечай живо, не растягивай реплики искусственно, но и не обрывай их на полуслове."
)
DIALOGUE_INSTRUCTIONS_EN = (
    "You play the role of the character described below in a text roleplay with "
    "the user. Reply ONLY with the character's lines and actions (actions may be "
    "wrapped in *asterisks*), never break character and never write meta "
    "comments as an AI. Take the environment and situation below into account - "
    "the character must react to them plausibly. Answer vividly, do not pad the "
    "lines artificially, but do not cut them off mid-thought either."
)

LANGUAGE_RULE = (
    "Пиши ИСКЛЮЧИТЕЛЬНО по-русски. Каждое слово - русское. Никаких английских "
    "слов, латиницы и смешения языков внутри предложения («Привет said она» - "
    "недопустимо). Не знаешь русского слова - подбери синоним или перефразируй."
)
LANGUAGE_RULE_EN = (
    "Write EXCLUSIVELY in English. Every word must be English. No words from "
    "other languages and no language mixing within a sentence. If you do not "
    "know an English word, pick a synonym or rephrase."
)

# Короткое напоминание, продублированное в САМОМ КОНЦЕ промпта (после всех
# данных сцены - персонажей, сценария, параметров истории). У слабых/
# квантованных моделей инструкции в начале промпта теряют вес под грузом
# данных после них - то, что модель прочитала ПОСЛЕДНИМ перед генерацией,
# влияет сильнее (эффект недавности). Называет КОНКРЕТНО именно ту
# деградацию, что реально наблюдается: не общие фразы на английском, а
# английские служебные глаголы-«вставки» при русской прямой речи (said/
# asked/smiled и т.п.) - самый частый вид просачивания языка у слабых
# моделей, разобранный отдельно от общего LANGUAGE_RULE.
LANGUAGE_REMINDER = (
    "Напоминание перед ответом: пиши ТОЛЬКО по-русски, включая авторские "
    "слова при репликах («сказал», «спросила», «улыбнулась» и т.п.) - "
    "никогда не вставляй английские глаголы (said, asked, smiled, began, "
    "wanted и подобные) даже одним словом внутри русского предложения."
)
LANGUAGE_REMINDER_EN = (
    "Reminder before you answer: keep writing in English throughout, "
    "start to finish - do not switch to any other language, not even for "
    "a single word."
)

STORY_INSTRUCTIONS = (
    "Напиши связный художественный рассказ от третьего лица по сценарию ниже, "
    "используя персонажей как основу. Локации по ходу истории могут меняться. "
    "У рассказа должны быть начало, развитие и логическое завершение. "
    "Не задавай вопросов пользователю и не проси уточнений - просто напиши историю целиком."
)
STORY_INSTRUCTIONS_EN = (
    "Write a coherent third-person work of fiction from the scenario below, "
    "using the characters as a basis. Locations may change over the course of "
    "the story. The story must have a beginning, development and a logical "
    "ending. Do not ask the user questions or request clarifications - just "
    "write the whole story."
)


def _typical_phrases_list(raw: str) -> List[str]:
    """Многострочное поле "Типичные фразы" -> список непустых реплик
    (по одной в строке; пустые строки и дубли по пробелам не считаем)."""
    return [ln.strip() for ln in (raw or "").split("\n") if ln.strip()]


def _character_block(c: Character, lang="ru") -> str:
    # Порядок полей: Биография → Внешность → Характер → остальное.
    phrases = _typical_phrases_list(getattr(c, "typical_phrases", ""))
    # динамическая память - только если включена у персонажа и не пуста
    dyn = ((getattr(c, "dyn_memory", "") or "").strip()
           if getattr(c, "dyn_enabled", False) else "")
    if _is_en(lang):
        lines = [f"## Character: {c.name or 'unnamed'}"]
        if getattr(c, "biography", ""):
            lines.append(f"Biography: {c.biography}")
        if c.appearance:
            lines.append(f"Appearance: {c.appearance}")
        if c.personality:
            lines.append(f"Personality: {c.personality}")
        if c.speech_style:
            lines.append(f"Speech style: {c.speech_style}")
        if phrases:
            quoted = "; ".join(f'"{p}"' for p in phrases)
            lines.append(f"Typical phrases (a reference for voice and style "
                         f"only - do NOT quote them verbatim, write new lines "
                         f"in the same spirit): {quoted}")
        if dyn:
            lines.append("Dynamic memory (the most important things that have "
                         "already happened to this character and how they "
                         "changed - treat them as established facts of the "
                         "past):\n" + dyn)
        return "\n".join(lines)
    lines = [f"## Персонаж: {c.name or 'без имени'}"]
    if getattr(c, "biography", ""):
        lines.append(f"Биография: {c.biography}")
    if c.appearance:
        lines.append(f"Внешность: {c.appearance}")
    if c.personality:
        lines.append(f"Характер: {c.personality}")
    if c.speech_style:
        lines.append(f"Манера речи: {c.speech_style}")
    if phrases:
        quoted = "; ".join(f'"{p}"' for p in phrases)
        lines.append(f"Типичные фразы (ориентир для голоса и стиля речи - НЕ "
                     f"повторяй их дословно, придумывай новые реплики в том "
                     f"же духе): {quoted}")
    if dyn:
        lines.append("Динамическая память (самое важное, что с персонажем уже "
                     "случилось и как он изменился - считай это установленными "
                     "фактами прошлого):\n" + dyn)
    return "\n".join(lines)


def _protagonist_block(p: Protagonist, lang="ru") -> str:
    # Порядок полей: Биография → Внешность → Характер.
    if _is_en(lang):
        lines = [f"## Protagonist (controlled by the user, you do NOT play them): "
                 f"{p.name or 'unnamed'}"]
        if p.biography:
            lines.append(f"Biography: {p.biography}")
        if getattr(p, "appearance", ""):
            lines.append(f"Appearance: {p.appearance}")
        if p.personality:
            lines.append(f"Personality: {p.personality}")
        return "\n".join(lines)
    lines = [f"## Главный герой (им управляет пользователь, ты его НЕ отыгрываешь): "
             f"{p.name or 'без имени'}"]
    if p.biography:
        lines.append(f"Биография: {p.biography}")
    if getattr(p, "appearance", ""):
        lines.append(f"Внешность: {p.appearance}")
    if p.personality:
        lines.append(f"Характер: {p.personality}")
    return "\n".join(lines)


def _protagonist_has_content(p: "Optional[Protagonist]") -> bool:
    return bool(p and (p.name or p.biography or getattr(p, "appearance", "")
                       or p.personality))


def _environment_block(e: Environment, lang="ru") -> str:
    if _is_en(lang):
        lines = ["## Environment"]
        if e.location:
            lines.append(f"Location: {e.location}")
        if e.time_of_day:
            lines.append(f"Time of day: {e.time_of_day}")
        if e.weather:
            lines.append(f"Weather: {e.weather}")
        if e.atmosphere:
            lines.append(f"Atmosphere: {e.atmosphere}")
        return "\n".join(lines)
    lines = ["## Окружение"]
    if e.location:
        lines.append(f"Локация: {e.location}")
    if e.time_of_day:
        lines.append(f"Время суток: {e.time_of_day}")
    if e.weather:
        lines.append(f"Погода: {e.weather}")
    if e.atmosphere:
        lines.append(f"Атмосфера: {e.atmosphere}")
    return "\n".join(lines)


def _scenario_block(s: Scenario, lang="ru") -> str:
    if _is_en(lang):
        lines = ["## Scenario"]
        if s.base_scenario:
            lines.append(f"Situation: {s.base_scenario}")
        if s.additional_params:
            lines.append(f"Extra conditions: {s.additional_params}")
        return "\n".join(lines)
    lines = ["## Сценарий"]
    if s.base_scenario:
        lines.append(f"Ситуация: {s.base_scenario}")
    if s.additional_params:
        lines.append(f"Дополнительные условия: {s.additional_params}")
    return "\n".join(lines)


def _story_params_block(story_size: str, story_details: str, lang="ru") -> str:
    if _is_en(lang):
        lines = ["## Story parameters"]
        if story_size.strip():
            lines.append(f"Desired length: {story_size.strip()}")
        if story_details.strip():
            lines.append(f"Additional details: {story_details.strip()}")
        return "\n".join(lines)
    lines = ["## Параметры истории"]
    if story_size.strip():
        lines.append(f"Желаемый размер: {story_size.strip()}")
    if story_details.strip():
        lines.append(f"Дополнительные детали: {story_details.strip()}")
    return "\n".join(lines)


def build_system_prompt(character: "Optional[Character]" = None,
                        environment: "Optional[Environment]" = None,
                        scenario: "Optional[Scenario]" = None,
                        mode: str = "dialogue",
                        system_config: "Optional[SystemConfig]" = None,
                        protagonist: "Optional[Protagonist]" = None,
                        characters: "Optional[List[Character]]" = None,
                        story_size: str = "",
                        story_details: str = "",
                        extra_details: str = "",
                        reasoning_nudge: bool = False,
                        structured_dialogue: bool = False,
                        lang: str = "ru") -> str:
    """
    mode: "dialogue" - обычный ролплей-чат, "story" - генератор истории.

    reasoning_nudge: если True - в самое начало промпта добавляется
        REASONING_NUDGE (просьба рассуждать в <think>...</think>). Нужен
        для reasoning-моделей БЕЗ capability "thinking" - им нельзя
        послать параметр think, но инлайном они думать умеют.
    structured_dialogue: если True и mode == "dialogue" - после инструкций
        режима добавляется STRUCTURED_DIALOGUE_INSTRUCTIONS (ответ JSON
        {action, speech}). Схема - STRUCTURED_DIALOGUE_SCHEMA, её GUI
        передаёт в chat_stream как response_format.

    character / characters: одиночный персонаж или список. Если передан
        characters - используется он; иначе [character] (или пусто).
        Режим dialogue кладёт одного, story - сколько угодно.
    environment: в story-режиме GUI его не передаёт (None) - блок
        "Окружение" тогда просто не добавляется.
    protagonist: главный герой ("Вы"). Пустой/None игнорируется.
    story_size / story_details: учитываются только при mode == "story".
    extra_details: произвольные доп. детали сцены, учитываются только при
        mode == "dialogue" (аналог story_details, но для диалога; блок
        "## Дополнительные детали" в конце промпта). Пусто -> не добавляется.
    system_config: если задан и непустой - его content идёт ПЕРВЫМ
        блоком, перед инструкциями режима. None -> как раньше.

    Все новые параметры имеют значения по умолчанию, поэтому старые
    вызовы build_system_prompt(char, env, scn, mode=...) работают
    без изменений.
    """
    en = _is_en(lang)
    if en:
        instructions = DIALOGUE_INSTRUCTIONS_EN if mode == "dialogue" else STORY_INSTRUCTIONS_EN
        nudge_text = REASONING_NUDGE_EN
        lang_rule = LANGUAGE_RULE_EN
        lang_reminder = LANGUAGE_REMINDER_EN
        structured_text = STRUCTURED_DIALOGUE_INSTRUCTIONS_EN
        extra_header = "## Additional details"
    else:
        instructions = DIALOGUE_INSTRUCTIONS if mode == "dialogue" else STORY_INSTRUCTIONS
        nudge_text = REASONING_NUDGE
        lang_rule = LANGUAGE_RULE
        lang_reminder = LANGUAGE_REMINDER
        structured_text = STRUCTURED_DIALOGUE_INSTRUCTIONS
        extra_header = "## Дополнительные детали"

    if characters is None:
        characters = [character] if character is not None else []

    parts: List[str] = []
    if reasoning_nudge:
        parts += [nudge_text, ""]
    if system_config is not None and system_config.content.strip():
        parts += [system_config.content.strip(), ""]
    parts.append(instructions)
    if mode in ("dialogue", "story"):
        parts += ["", lang_rule]
    if mode == "dialogue":
        guard = role_guard(characters, protagonist, lang=lang)
        if guard:
            parts += ["", guard]
    if structured_dialogue and mode == "dialogue":
        parts += ["", structured_text]

    if _protagonist_has_content(protagonist):
        parts += ["", _protagonist_block(protagonist, lang=lang)]

    for c in characters:
        parts += ["", _character_block(c, lang=lang)]

    if environment is not None:
        parts += ["", _environment_block(environment, lang=lang)]

    if scenario is not None:
        parts += ["", _scenario_block(scenario, lang=lang)]

    if mode == "dialogue" and extra_details.strip():
        parts += ["", extra_header, extra_details.strip()]

    if mode == "story" and (story_size.strip() or story_details.strip()):
        parts += ["", _story_params_block(story_size, story_details, lang=lang)]

    # Напоминание про язык - ПОСЛЕДНИМ, после всех данных сцены (см.
    # комментарий у LANGUAGE_REMINDER: то, что модель прочитала последним,
    # влияет на генерацию сильнее длинных инструкций в начале промпта).
    if mode in ("dialogue", "story"):
        parts += ["", lang_reminder]

    return "\n".join(parts)


# --- кнопка «Сгенерировать» в редакторе пресета ------------------------------
# Короткое вступление по типу блока: чем «занят» помощник, когда придумывает
# значение одного поля карточки.
_FIELD_GEN_INTRO = {
    "protagonist": "Ты придумываешь детали для карточки главного героя "
                   "(им управляет игрок) в текстовом ролплее.",
    "character": "Ты придумываешь детали для карточки персонажа в текстовом ролплее.",
    "environment": "Ты придумываешь детали обстановки/локации для текстового ролплея.",
    "scenario": "Ты придумываешь детали завязки сценария для текстового ролплея.",
    "system_config": "Ты формулируешь общие правила поведения модели для "
                     "текстового ролплея.",
}
_FIELD_GEN_INTRO_DEFAULT = "Ты придумываешь детали для карточки в текстовом ролплее."

_FIELD_GEN_INTRO_EN = {
    "protagonist": "You invent details for the protagonist's card "
                   "(controlled by the player) in a text roleplay.",
    "character": "You invent details for a character's card in a text roleplay.",
    "environment": "You invent details of the setting/location for a text roleplay.",
    "scenario": "You invent details of the scenario's setup for a text roleplay.",
    "system_config": "You state general rules for the model's behaviour in a "
                     "text roleplay.",
}
_FIELD_GEN_INTRO_DEFAULT_EN = "You invent details for a card in a text roleplay."


def build_field_generation_messages(block: str, field_attr: str, field_label: str,
                                    values: dict, field_labels: "Optional[dict]" = None,
                                    short: bool = False, lang: str = "ru") -> list:
    """
    Сообщения для кнопки «Сгенерировать» в редакторе пресета: попросить
    модель придумать значение ОДНОГО поля карточки.

    block        - ключ блока ("character" / "environment" / ...).
    field_attr   - какое поле генерируем. Его текущее значение в промпт НЕ
                   кладётся, даже если поле уже заполнено: пользователь
                   явно просит замену.
    field_label  - человекочитаемая подпись поля («Характер»).
    values       - dict attr -> текущий текст всех полей этого же объекта.
                   Все непустые поля, кроме генерируемого (включая имя),
                   идут в промпт как «уже известно», чтобы результат был
                   согласован с ними.
    field_labels - dict attr -> подпись (для читаемых названий фактов).
                   None -> подставляются сами attr.
    short        - True для однострочных полей (widget "entry": Локация,
                   Время суток, Погода): просим одно слово / короткое
                   словосочетание без предложения. False -> 1-3 фразы.

    Возвращает [{role: system}, {role: user}] - один вопрос, без истории.
    Чистая функция, тестируется без сети (см. test_logic.py).
    """
    field_labels = field_labels or {}
    en = _is_en(lang)

    known = []
    for attr, text in values.items():
        if attr == field_attr:
            continue
        text = (text or "").strip()
        if text:
            known.append(f"- {field_labels.get(attr, attr)}: {text}")

    if en:
        intro = _FIELD_GEN_INTRO_EN.get(block, _FIELD_GEN_INTRO_DEFAULT_EN)
        if short:
            length_rule = (
                "This is a SHORT field: answer with one word or a short phrase "
                "(about 1-5 words), with NO full sentence and no trailing "
                "period. Format examples: “late evening”, “drizzling rain”, "
                "“abandoned lighthouse”."
            )
        else:
            length_rule = (
                "Keep it short: a few comma-separated phrases or 1-3 compact "
                "sentences, as is usual on character cards."
            )
        system = "\n".join([
            intro,
            f"Task: invent the value of ONE field - “{field_label}”.",
            "Return ONLY the content of this field: no preamble or "
            "explanations, no quotes, no field name at the start, no markdown.",
            "Stay consistent with the known facts below and do not contradict "
            "them. If the field was already filled in, propose a different, "
            "independent variant.",
            length_rule,
            LANGUAGE_RULE_EN,
        ])
        user_lines = []
        if known:
            user_lines.append("Already known:")
            user_lines.extend(known)
            user_lines.append("")
        else:
            user_lines.append("The other fields are not filled in yet - invent "
                              "it from scratch so it comes out whole and "
                              "interesting.")
            user_lines.append("")
        user_lines.append(f"Invent the “{field_label}” field.")
        return [
            {"role": "system", "content": system},
            {"role": "user", "content": "\n".join(user_lines)},
        ]

    intro = _FIELD_GEN_INTRO.get(block, _FIELD_GEN_INTRO_DEFAULT)
    if short:
        length_rule = (
            "Это КОРОТКОЕ поле: ответь одним словом или коротким "
            "словосочетанием (примерно 1-5 слов), БЕЗ полного предложения "
            "и без точки в конце. Пример формата: «поздний вечер», "
            "«моросящий дождь», «заброшенный маяк»."
        )
    else:
        length_rule = (
            "Объём - коротко: несколько фраз через запятую или 1-3 сжатых "
            "предложения, как принято в карточках персонажей."
        )

    system = "\n".join([
        intro,
        f"Задача: придумать значение ОДНОГО поля - «{field_label}».",
        "В ответе верни ТОЛЬКО содержимое этого поля: без вступлений и "
        "пояснений, без кавычек, без названия поля в начале, без markdown.",
        "Держись уже известных фактов ниже и не противоречь им. Если поле "
        "уже было заполнено - предложи другой, самостоятельный вариант.",
        length_rule,
        LANGUAGE_RULE,
    ])

    user_lines = []
    if known:
        user_lines.append("Уже известно:")
        user_lines.extend(known)
        user_lines.append("")
    else:
        user_lines.append("Другие поля пока не заполнены - придумай с нуля, "
                          "чтобы вышло цельно и интересно.")
        user_lines.append("")
    user_lines.append(f"Придумай поле «{field_label}».")

    return [
        {"role": "system", "content": system},
        {"role": "user", "content": "\n".join(user_lines)},
    ]
