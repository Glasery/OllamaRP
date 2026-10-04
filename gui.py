"""
Главное окно приложения. CustomTkinter = обычные нативные виджеты
поверх Tkinter, никакого браузера или веб-вьюшки внутри.

Сетевой вызов к Ollama идёт в отдельном потоке (threading.Thread),
чтобы не подвешивать окно на время генерации ответа. Поток кладёт
кусочки текста в очередь (queue.Queue), а GUI-поток забирает их оттуда
каждые 50мс через self.after() - это стандартный безопасный способ
обновлять Tkinter-виджеты из фонового потока.

На главном экране НЕТ полей конфигурации - только выбор пресета по
блокам плюс кнопка «Настроить», открывающая менеджер пресетов (создать
/ редактировать / удалить). Всё про блоки - в blocks.py, окна
редактирования - в preset_ui.py.

Левая панель зависит от режима (переключатель dialogue/story сверху):
- dialogue: Главный герой (Вы) / Персонаж (один) / Локация / Сценарий /
  Конфиг-промпт;
- story:    Главный герой (Вы) / Персонажи (несколько) / Сценарий /
  Конфиг-промпт + поля «Размер истории» и «Дополнительные детали».
  Локации в истории меняются, поэтому блока «Локация» тут нет.
Переключение - _apply_mode_view(): все секции строятся один раз,
показываются/прячутся через pack/pack_forget.

Левая колонка - CTkTabview из двух вкладок: «Сцена» (описанные выше
селекторы пресетов) и «Settings» (параметры генерации: temperature,
top_p, num_ctx, seed, stop, reasoning и т.д.). Настройки Settings
собираются в models.InferenceConfig и уходят в КАЖДЫЙ запрос - и в
диалоге, и в истории; лежат в settings.json.

Справа от чата - панель Logs: сырой дамп каждого запроса, уходящего в
модель (ровно тот словарь, что идёт в requests.post), полного ответа
модели и, для reasoning-моделей, блока размышлений. Пишется через
отдельную очередь self.log_queue, которую тот же _poll_queue разгребает.
"""
import json
import queue
import random
import re
import subprocess
import sys
import threading
import time
import traceback
import tkinter as tk
import tkinter.font as tkfont
import webbrowser
from tkinter import messagebox, filedialog

import customtkinter as ctk

import dynamic_memory
import i18n
import overlay
import photos
from i18n import t
import help_texts
from blocks import BLOCK_SPECS, BLOCK_ORDER
from inference_spec import INFERENCE_FIELDS
from models import InferenceConfig, EMOTES_MODES
from storage import PresetStore
from prompt_builder import (build_system_prompt,
                            build_segment_summary_messages,
                            build_consolidation_messages,
                            build_compress_messages,
                            digest_boundary, estimate_tokens, next_num_ctx,
                            is_duplicate_speech, find_repeat_loop,
                            STRUCTURED_DIALOGUE_SCHEMA,
                            memory_header, digest_system,
                            DIGEST_SYSTEM, DIGEST_SYSTEM_EN)
from preset_ui import PresetManager, TextEditDialog
from sessions import SessionStore, SessionError, normalize_snapshot
from sessions_ui import SessionsDialog
from ollama_client import (list_models, model_capabilities, chat_stream,
                           parse_structured_reply, OllamaError, OllamaStallError)

ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("blue")

NONE_CHOICE = "—"  # пункт "блок не используется"

# Единая шкала отступов (px). В разметке используются ТОЛЬКО эти размеры,
# чтобы промежутки не были «рандомными»:
#   PAD_TIGHT - подпись ↔ её поле, элементы внутри одной группы;
#   PAD       - базовый: поля панелей, между колонками, между блоками, кнопки;
#   PAD_SEC   - между смысловыми группами (заголовок+поля) в списке настроек.
# Отдельные «подогнанные» отступы (выравнивание трёх подсказок по низу,
# сдвиг колонки кнопок под первое поле) намеренно оставлены как есть - они
# помечены комментариями на месте.
PAD_TIGHT = 4
PAD = 8
PAD_SEC = 16

# Три главные колонки (Сцена/Settings · чат · Logs/Память) - равной ширины
# (weight=1 у всех) и не уже COL_MIN.
COL_MIN = 500
# Высота «шапки» под таб-баром каждой из трёх колонок («Пресеты сцены» /
# «Диалог» / тулбар Logs-Память). Фиксированная и одинаковая -> низ шапки
# (= верх основного блока) на одной линии во всех трёх колонках.
HEAD_H = 44
# Высота двух верхних полос (выбор модели / статус сцены). Фиксированная и
# одинаковая для обеих: `pack_propagate(False)` -> полосы визуально равны,
# содержимое (28 px) центрируется по вертикали.
BAR_H = 40
# Вкладка «Сцена»: область селекторов - фикс. `PRESET_MIN_H`. Подобрано так,
# чтобы без прокрутки помещались И 5 селекторов dialogue, И набор story с
# одним добавленным персонажем («Размер истории» виден целиком). Поле
# «Доп. детали» резиновое (`weight=1`, минимум `DETAILS_MIN_H`) - забирает
# весь лишний запас по высоте и растёт вверх.
PRESET_MIN_H = 410
DETAILS_MIN_H = 145

# Послойная «бегущая память»: сколько последних сегментов-сводок держим как
# есть; что старше - вливается в `mem_head` отдельным запросом (см.
# App._fold_segment). Вход каждого скрытого запроса памяти от длины
# диалога не зависит.
MEM_SEGMENTS_KEEP = 3
# Аварийный предел на число сегментов (если уплотнение почему-то не
# срабатывает - чтобы память всё же не росла бесконечно).
MEM_SEGMENTS_MAX = MEM_SEGMENTS_KEEP + 8
# Гарантированный минимум контекста для скрытых запросов памяти: вход у них
# ограничен, но пользовательский num_ctx может быть мал/не задан.
MEM_MIN_NUM_CTX = 8192
# «Сжать пример»: мягкий потолок на генерацию за ОДИН скрытый запрос.
# Нужен, чтобы шаг не превращался в один огромный многоминутный запрос
# (виден прогресс, работает «Стоп»), но не дробим слишком мелко - лишние
# запросы = лишний prompt-eval и общий рост времени.
COMPRESS_CHUNK_OUT_CAP = 2400

# «Продолжить историю»: перед КАЖДОЙ генерацией продолжения ужимаем всё,
# что уже написано с прошлого пересказа (КРОМЕ последнего куска - см.
# STORY_RECAP_KEEP_RAW_TURNS), в краткий пересказ - вместо того чтобы, как
# раньше, слать сырой текст истории целиком при каждом продолжении (на
# длинной «максимально подробной» истории это быстро упирается в
# контекст). Механика - как у бегущей памяти диалога
# (build_segment_summary_messages/build_consolidation_messages), только
# по кнопке, а не каждые N ходов: self.story_recap копится последовательно
# (см. App._story_recap_worker), self.story_recap_upto - сколько записей
# self.history уже пересказано.
STORY_RECAP_CHUNK_FRACTION = 0.4   # доля num_ctx на один кусок пересказа
STORY_RECAP_CONSOLIDATE_TOKENS = 1500  # пересказ разросся - сжимаем его самого
# Последние N ходов (пара user+assistant = 1 ход) НЕ пересказываем, шлём
# как есть, дословно. Без этого модель видит только сухую 4-8-предложную
# сводку и НИ ОДНОГО реального слова из уже написанного - на практике это
# выглядело как «начинает заново» (нет ни точного места обрыва, ни стиля,
# ни темпа последней сцены). Одного последнего хода обычно достаточно для
# прямой преемственности, а рост контекста всё равно ограничен.
STORY_RECAP_KEEP_RAW_TURNS = 1

# Диалог: детектор «персонаж повторил реплику». Узкое `repeat_last_n` (по
# умолчанию 64) не ловит повтор фразы с хода 2-3 назад. Если РЕЧЕВАЯ часть
# ответа почти совпадает с одной из последних - молча перегенерируем
# (усилив разнообразие), максимум DUP_MAX_RETRIES раз, с пометкой в чате.
DUP_RATIO = 0.86            # порог похожести (difflib ratio)
DUP_WINDOW = 8             # сколько последних ответов персонажа сравнивать
DUP_MIN_LEN = 24          # реплики короче не проверяем ("Да.", "Хорошо.")
DUP_MAX_RETRIES = 2

# История/диалог без разбивки на структуру: детектор «генерация зациклилась
# на повторе абзацев». Особенно бьёт длинные истории (num_predict без
# лимита) - штраф за повтор узкий и не покрывает период цикла; на практике
# модель повторяет не строгим периодом, а ротацией из нескольких похожих
# шаблонов вперемешку с заголовками глав. Ловим это ПРЯМО ПО ХОДУ стрима
# (не ждём конца ответа): при обнаружении обрываем поток, визуально
# откатываем зациклившийся хвост (маркер __TRIM__ в token_queue) и пробуем
# ещё раз с усиленным анти-повтором, продолжая с последнего чистого места -
# см. find_repeat_loop() в prompt_builder.py.
LOOP_TAIL_CHECK = 10      # сколько последних абзацев проверяем на повтор
LOOP_WINDOW = 30          # среди какого числа предыдущих абзацев ищем совпадение
LOOP_RATIO = 0.85         # порог похожести (difflib ratio; было 0.88 - реальный
                          # экспорт показал, что деградация часто идёт не точным
                          # повтором, а «расползающимся» перефразом того же самого
                          # абзаца, и часть пар не дотягивала до 0.88)
LOOP_MIN_BLOCK_LEN = 12   # абзацы короче не проверяем ("Да.", "---")
LOOP_MIN_HITS = 3         # столько абзацев-повторов в хвосте = зацикливание
                          # (было 4 - тот же экспорт показал детекцию впритык
                          # к самому последнему абзацу; с 3 срабатывает раньше)
LOOP_MAX_RETRIES = 2

# Зависание модели (ответ уже пошёл, но токены перестали приходить дольше
# stall_timeout из Settings, обычно на этапе «размышляет»): обрываем запрос
# и шлём его заново, максимум STALL_MAX_RETRIES раз, дальше - ошибка в чат.
# См. ollama_client.chat_stream(stall_timeout=...) и App._generate_worker.
STALL_MAX_RETRIES = 3

# Аватарка рядом с репликой в диалоге: высота = столько строк текста чата
# (считаем от шрифта, поэтому ровно ложится и при масштабе экрана 125/150 %);
# между аватаркой и текстом - треть строки.
AVATAR_LINES = 2.4

# Внутреннее значение режима везде "dialogue"/"story"/"chat"; подпись
# вкладки центрального таб-бара - через i18n (MODE_LABELS()/MODE_HINTS()).
_MODE_KEYS = ("dialogue", "story", "chat")


def MODE_LABELS():
    return {m: t(f"mode_{m}") for m in _MODE_KEYS}


def MODE_FROM_LABEL():
    return {v: k for k, v in MODE_LABELS().items()}


def MODE_HINTS():
    return {m: t(f"hint_{m}") for m in _MODE_KEYS}


def TAB_SETTINGS():
    return t("tab_settings")


def STORY_SIZE_CHOICES():
    """Варианты «Размера истории» под текущий язык (0-й — NONE_CHOICE)."""
    return i18n.story_size_choices(NONE_CHOICE)


class App(ctk.CTk):
    def __init__(self):
        super().__init__()
        self.title("Ollama RP")
        self.geometry("1560x860")

        self.store = PresetStore()
        _saved = self.store.load_settings()
        self._ui_language = _saved.ui_language
        self._last_model = _saved.last_model   # для _refresh_models() на старте
        i18n.set_lang(self._ui_language)
        self._rebuilding_ui = False   # идёт пересборка интерфейса под смену языка
        self.history = []            # накопленный диалог, который уходит модели
        self.sessions = SessionStore(self.store.data_dir)   # сохранённые диалоги
        self._sessions_win = None
        # динамическая память персонажа: новые сводки памяти диалога, ещё не
        # учтённые в ней, и колбэк «после дособирания перед сохранением»
        self.dyn_new = []
        self._dyn_then = None
        self._dyn_limit = dynamic_memory.DYN_MEMORY_LIMIT   # из Settings, обновляется при запуске запросов
        self.token_queue = queue.Queue()
        self.log_queue = queue.Queue()   # сырые запросы/ответы для панели Logs
        self.generating = False
        self.mode_value = "dialogue"
        self.stop_event = None       # threading.Event, новый на каждую генерацию
        self._model_caps = set()     # capabilities выбранной модели (/api/show)
        # Послойная «бегущая память»:
        #   mem_head      - долговременная память (сжимается уплотнением, потом
        #                   не трогается);
        #   mem_segments  - недавние сводки-сегменты (каждый = ровно N ходов,
        #                   собирается ОДИН раз и больше не пересобирается);
        #   chat_digest   - производная строка (mem_head + сегменты) для показа
        #                   и подстановки в промпт - держится в синхроне
        #                   `_render_memory()`;
        #   digested_upto - сколько записей self.history уже учтено.
        self.mem_head = ""
        self.mem_segments = []
        self.chat_digest = ""
        self.digested_upto = 0
        # «Продолжить историю»: краткий пересказ истории до story_recap_upto
        # (записей self.history) - см. константы STORY_RECAP_* выше.
        # Независимо от mem_head/digested_upto - те только для dialogue.
        self.story_recap = ""
        self.story_recap_upto = 0
        # Аватарки в чате (см. _begin_turn): кэш PhotoImage по (файл, размер) и
        # реестр имя-в-Tk -> PhotoImage (нужен, чтобы пересобрать чат со
        # всеми картинками при смене языка); _hang - идёт ход с аватаркой.
        self._avatar_cache = {}
        self._chat_images = {}
        self._hang = False
        # Эмотиконы поверх интерфейса: сторона ("left"/"right") -> PhotoOverlay;
        # _emote_idx - какой по счёту эмотикон сейчас у блока (меняется на
        # каждый ответ в чате); _emotes_mode - режим кнопки вверху ("all" /
        # "companion" / "hidden")
        # (запоминается в настройках); галерея: _gallery_idx - текущее фото
        # блока, _gallery_owner - чей это пресет (смена пресета - с первого).
        self._overlays = {}
        self._ov_job = None
        self._emote_idx = {}
        self._emotes_mode = _saved.emotes_mode
        self._gallery_idx = {}
        self._gallery_owner = {}
        self._history_backup = []    # копия истории до «Сжать пример»
        self._details_backup = ""    # копия «Доп. деталей» до «Сжать пример»
        self._just_compressed = False  # только что сжали и авто-перезапустили
        self._rebuilding = False     # идёт пересборка памяти / сжатие
        self._digest_prompt = ""     # свой system-промпт генерации памяти ("" -> дефолт)
        self._right_hidden = False   # панель Logs/Память свёрнута
        self._left_hidden = False    # левая панель (Сцена/Settings) свёрнута

        # Активно выбранный пресет по каждому блоку (одиночный выбор):
        # объект целиком или None.
        self.active = {block: None for block in BLOCK_ORDER}
        # Режим story: несколько персонажей (список объектов Character).
        self.story_characters = []
        self.block_menus = {}        # block -> (CTkOptionMenu, StringVar)
        self._managers = {}          # block -> открытое окно PresetManager

        self._build_layout()
        self._build_context_menu()
        self._bind_clipboard()
        self._seed_defaults()
        self._populate_block_menus()
        self._refresh_story_char_pick()
        self._startup_select()
        self._render_story_characters()
        self._apply_mode_view(self.mode_value)
        self._load_inference_into_widgets(_saved)
        self._apply_right_panel_visibility()
        self._apply_left_panel_visibility()
        self.protocol("WM_DELETE_WINDOW", self._on_close)
        # фигуры «поверх интерфейса» следят за главным окном
        self.bind("<Configure>", self._on_root_configure, add="+")
        self.bind("<Unmap>", self._on_root_unmap, add="+")
        self.bind("<Map>", self._on_root_map, add="+")
        self._refresh_models()
        self._poll_queue()

    def _on_close(self):
        self._overlay_destroy_all()
        try:
            self.store.save_settings(self._collect_inference_config())
        except Exception:
            pass
        self.destroy()

    # ----------------------------------------------- смена языка ----
    def _on_lang_change(self, choice):
        lang = "en" if choice == "EN" else "ru"
        if lang == i18n.get_lang():
            return
        if self.generating or self._rebuilding or self._rebuilding_ui:
            self._lang_seg.set("EN" if i18n.get_lang() == "en" else "RU")
            messagebox.showinfo(t("lang_busy_title"), t("lang_busy"))
            return
        # снимок состояния делаем ДО смены языка (индексы «Размера истории»
        # и имена вкладок ещё на старом языке).
        snap = self._snapshot_ui()
        i18n.set_lang(lang)
        self._ui_language = lang
        try:
            self.store.save_settings(self._collect_inference_config())
        except Exception:
            pass
        self._relayout_language(snap)

    def _relayout_language(self, snap):
        """Пересобрать весь интерфейс под новый язык, сохранив состояние
        (сцена, история чата, ввод, настройки, свёрнутые панели)."""
        self._rebuilding_ui = True
        self._overlay_hide_all()              # вернутся в _restore_ui -> _sync_side_tabs
        for a in ("_about_win", "_help_win", "_faq_win", "_cheat_win"):
            w = getattr(self, a, None)
            if w is not None and w.winfo_exists():
                try:
                    w.destroy()
                except Exception:
                    pass
            setattr(self, a, None)
        for mgr in list(self._managers.values()):
            try:
                mgr.destroy()
            except Exception:
                pass
        self._managers = {}
        for w in (self._top_bar, self._info_bar, self._body):
            try:
                w.destroy()
            except Exception:
                pass
        self._build_context_menu()
        self._build_layout()
        self._restore_ui(snap)
        self._rebuilding_ui = False

    def _snapshot_ui(self) -> dict:
        choices = STORY_SIZE_CHOICES()
        cur_size = self.story_size_var.get()
        return {
            "mode": self.mode_value,
            "inf": self._collect_inference_config(),
            "active": dict(self.active),
            "story_characters": list(self.story_characters),
            "story_size_idx": choices.index(cur_size) if cur_size in choices else 0,
            "dlg_details": self.dialogue_details_box.get("1.0", "end-1c"),
            "story_details": self.story_details_box.get("1.0", "end-1c"),
            "act": self.act_box.get("1.0", "end-1c"),
            "reply": self.reply_box.get("1.0", "end-1c"),
            "story_input": self.story_input.get("1.0", "end-1c"),
            "chat_msg": self.chat_msg_box.get("1.0", "end-1c"),
            "chat_text": self.chat_box.get("1.0", "end-1c"),
            "chat_dump": self._dump_chat(),
            "logs_text": self.logs_box.get("1.0", "end-1c"),
            "mem_head": self.mem_head,
            "mem_segments": list(self.mem_segments),
            "digested_upto": self.digested_upto,
            "left_settings": self._left_tabs.get() == self._tab_settings,
            "left_photo": self._left_tabs.get() == self._tab_photo,
            "right_memory": self._right_tabs.get() == self._tab_memory,
            "right_photo": self._right_tabs.get() == self._tab_photo,
            "models": list(self.model_menu.cget("values")),
            "model": self.model_var.get(),
            "model_caps": set(self._model_caps),
        }

    def _restore_ui(self, snap: dict):
        # модель + бейдж reasoning (без сетевого запроса)
        models = snap["models"] or ["..."]
        if self._no_model(snap["model"]):
            models = [t("no_models")]
        self.model_menu.configure(values=models)
        self.model_var.set(models[0] if self._no_model(snap["model"]) else snap["model"])
        self._model_caps = snap["model_caps"]
        self._render_reasoning_badge()
        self._lang_seg.set("EN" if i18n.get_lang() == "en" else "RU")

        # пресеты сцены
        self._populate_block_menus()
        self.active = snap["active"]
        for block in BLOCK_ORDER:
            obj = self.active.get(block)
            _, var = self.block_menus[block]
            var.set(obj.name if (obj and obj.name) else NONE_CHOICE)
        self.story_characters = snap["story_characters"]
        self._refresh_story_char_pick()
        self._render_story_characters()

        # размер истории
        choices = STORY_SIZE_CHOICES()
        i = snap["story_size_idx"]
        self.story_size_var.set(choices[i] if 0 <= i < len(choices) else NONE_CHOICE)

        # вкладка «Настройки» (числовые поля + digest_prompt + флаги панелей)
        self._load_inference_into_widgets(snap["inf"])

        # текстовые поля
        for box, key in ((self.dialogue_details_box, "dlg_details"),
                         (self.story_details_box, "story_details"),
                         (self.act_box, "act"), (self.reply_box, "reply"),
                         (self.story_input, "story_input"),
                         (self.chat_msg_box, "chat_msg")):
            if snap[key]:
                box.insert("1.0", snap[key])

        # лента чата: переигрываем дамп (текст + теги: курсив действий, поля
        # абзаца + аватарки); нет дампа - как раньше, plain-текстом
        if snap["chat_text"].strip():
            self._replay_chat(snap.get("chat_dump") or [], snap["chat_text"])
        if snap["logs_text"].strip():
            self._append_log(snap["logs_text"])
        self.mem_head = snap["mem_head"]
        self.mem_segments = list(snap["mem_segments"])
        self.digested_upto = snap["digested_upto"]
        self._render_memory()

        # режим + вкладки + панели
        self._on_mode_change(snap["mode"])
        # ВАЖНО: по одному set() на панель. CTkTabview.set() через 100 мс
        # «забывает» все вкладки, кроме названной; два set() подряд с разными
        # именами гасили только что показанную вкладку (пустая панель).
        dlg_photos = self.mode_value == "dialogue" and self._gallery_on()
        left = (self._tab_photo if snap["left_photo"] and dlg_photos
                else self._tab_settings if snap["left_settings"] else self._tab_scene)
        right = (self._tab_photo if snap["right_photo"] and dlg_photos
                 else self._tab_memory if snap["right_memory"]
                 and self.mode_value == "dialogue" else self._tab_logs)
        self._set_tab(self._left_tabs, left)
        self._set_tab(self._right_tabs, right)
        self._sync_side_tabs()
        self._on_right_tab()
        self._on_left_tab()
        self._apply_right_panel_visibility()
        self._apply_left_panel_visibility()
        self._refresh_active_label()

    # -------------------------------------- копирование / вставка везде ----
    def _bind_clipboard(self):
        """Ctrl+C/V/X/A при русской (и любой не-латинской) раскладке.
        Латиницу Tk обрабатывает сам, здесь ловим по физической клавише
        (Windows VK) и по кириллическим keysym. bind_all -> действует во
        всех виджетах приложения, включая модальные окна."""
        self.bind_all("<Control-KeyPress>", self._on_ctrl_key, add="+")
        self.bind_all("<Button-3>", self._show_context_menu, add="+")

    def _on_ctrl_key(self, event):
        ks = event.keysym.lower()
        if ks in ("c", "v", "x", "a"):
            return                       # латиница - у Tk уже есть биндинги
        kc = event.keycode              # Windows VK: C=67 V=86 X=88 A=65
        w = event.widget
        if ks == "cyrillic_es" or kc == 67:
            virt = "<<Copy>>"
        elif ks == "cyrillic_em" or kc == 86:
            virt = "<<Paste>>"
        elif ks == "cyrillic_che" or kc == 88:
            virt = "<<Cut>>"
        elif ks == "cyrillic_ef" or kc == 65:
            virt = "select_all"
        else:
            return
        try:
            if virt == "select_all":
                self._select_all(w)
            else:
                w.event_generate(virt)
            return "break"
        except (tk.TclError, AttributeError):
            return

    @staticmethod
    def _select_all(w):
        cls = w.winfo_class()
        try:
            if cls == "Text":
                w.tag_remove("sel", "1.0", "end")
                w.tag_add("sel", "1.0", "end-1c")
                w.mark_set("insert", "end-1c")
            elif cls in ("Entry", "TEntry"):
                w.selection_range(0, "end")   # без icursor - он сбрасывает выделение
            else:
                w.event_generate("<<SelectAll>>")
        except (tk.TclError, AttributeError):
            try:
                w.event_generate("<<SelectAll>>")
            except tk.TclError:
                pass

    def _build_context_menu(self):
        m = tk.Menu(self, tearoff=0)
        m.add_command(label=t("ctx_cut"), command=lambda: self._ctx_do("<<Cut>>"))
        m.add_command(label=t("ctx_copy"), command=lambda: self._ctx_do("<<Copy>>"))
        m.add_command(label=t("ctx_paste"), command=lambda: self._ctx_do("<<Paste>>"))
        m.add_separator()
        m.add_command(label=t("ctx_select_all"),
                      command=lambda: self._ctx_do("select_all"))
        self._ctx_menu = m
        self._ctx_target = None
        self._ctx_labels = (t("ctx_cut"), t("ctx_paste"))

    def _show_context_menu(self, event):
        w = event.widget
        if w.winfo_class() not in ("Entry", "TEntry", "Text"):
            return
        self._ctx_target = w
        disabled = str(w.cget("state")) == "disabled"
        for label in self._ctx_labels:
            self._ctx_menu.entryconfigure(label,
                                          state="disabled" if disabled else "normal")
        try:
            w.focus_set()
        except tk.TclError:
            pass
        try:
            self._ctx_menu.tk_popup(event.x_root, event.y_root)
        finally:
            self._ctx_menu.grab_release()

    def _ctx_do(self, what):
        w = self._ctx_target
        if w is None:
            return
        try:
            if what == "select_all":
                self._select_all(w)
            else:
                w.event_generate(what)
        except (tk.TclError, AttributeError):
            pass

    # ---------------------------------------------------------- layout ----
    def _build_layout(self):
        top = ctk.CTkFrame(self, height=BAR_H)
        top.pack(fill="x", padx=PAD, pady=(PAD, 0))
        top.pack_propagate(False)
        self._top_bar = top

        ctk.CTkLabel(top, text=t("model_label")).pack(side="left", padx=(PAD, PAD_TIGHT))
        self.model_var = tk.StringVar(value="")
        # фикс. ширина: длинные имена моделей (hf.co/...) не должны распирать
        # верхнюю панель и толкать кнопки за край окна.
        self.model_menu = ctk.CTkOptionMenu(
            top, variable=self.model_var, values=["..."], width=300,
            dynamic_resizing=False,
            command=self._on_model_selected)
        self.model_menu.pack(side="left", padx=PAD_TIGHT)
        ctk.CTkButton(top, text=t("refresh_models"), width=140,
                      command=self._refresh_models).pack(side="left", padx=PAD_TIGHT)
        ctk.CTkButton(top, text=t("about"), width=120, fg_color="gray30",
                      hover_color="gray40", command=self._open_about).pack(
            side="left", padx=PAD_TIGHT)
        ctk.CTkButton(top, text=t("help"), width=90, fg_color="gray30",
                      hover_color="gray40", command=self._open_help).pack(
            side="left", padx=PAD_TIGHT)
        ctk.CTkButton(top, text=t("download_models"), width=130, fg_color="gray30",
                      hover_color="gray40", command=self._open_model_library).pack(
            side="left", padx=PAD_TIGHT)
        ctk.CTkButton(top, text=t("open_cmd"), width=120, fg_color="gray30",
                      hover_color="gray40", command=self._open_cmd).pack(
            side="left", padx=PAD_TIGHT)
        ctk.CTkButton(top, text=t("faq"), width=64, fg_color="gray30",
                      hover_color="gray40", command=self._open_faq).pack(
            side="left", padx=PAD_TIGHT)
        # Переключатель языка - в правом верхнем углу.
        self._lang_seg = ctk.CTkSegmentedButton(
            top, values=["RU", "EN"], width=96, command=self._on_lang_change)
        self._lang_seg.set("EN" if i18n.get_lang() == "en" else "RU")
        self._lang_seg.pack(side="right", padx=(PAD_TIGHT, PAD))
        ctk.CTkLabel(top, text=t("lang_label")).pack(side="right", padx=(PAD, PAD_TIGHT))
        # свернуть/показать эмотиконы (видна только когда они включены, диалог)
        self._emote_btn = ctk.CTkButton(
            top, text=t("emotes_mode_all"), width=230, fg_color="gray30",
            hover_color="gray40", command=self._toggle_emotes)
        # Переключатель режимов - это таб-бар центральной колонки
        # (см. _build_chat_panel), в верхней панели его нет.

        info = ctk.CTkFrame(self, height=BAR_H)
        info.pack(fill="x", padx=PAD, pady=(PAD, 0))
        info.pack_propagate(False)
        self._info_bar = info
        # Индикатор reasoning - во второй строке, слева от активных пресетов:
        # «Reasoning:» обычным цветом + enabled/disabled серым.
        self._reasoning_badge = ctk.CTkFrame(info, fg_color="transparent")
        self._reasoning_badge.pack(side="left", padx=(PAD, 0), pady=PAD_TIGHT)
        self._reasoning_prefix = ctk.CTkLabel(
            self._reasoning_badge, text="", font=ctk.CTkFont(size=12))
        self._reasoning_prefix.pack(side="left")
        self._reasoning_state = ctk.CTkLabel(
            self._reasoning_badge, text="", font=ctk.CTkFont(size=12),
            text_color="gray")
        self._reasoning_state.pack(side="left", padx=(PAD_TIGHT, 0))
        self.active_label = ctk.CTkLabel(info, text="", anchor="w",
                                         font=ctk.CTkFont(size=12))
        self.active_label.pack(side="left", padx=PAD, pady=PAD_TIGHT)
        # живой статус генерации: ⏳ ждём -> 💭 размышляет -> ✍ отвечает
        self.gen_status = ctk.CTkLabel(info, text="", anchor="e",
                                       font=ctk.CTkFont(size=12, weight="bold"))
        self.gen_status.pack(side="right", padx=PAD, pady=PAD_TIGHT)

        body = ctk.CTkFrame(self, fg_color="transparent")
        body.pack(fill="both", expand=True, padx=PAD, pady=(PAD, PAD_TIGHT))
        self._body = body
        # Три колонки равной ширины (weight=1 у всех, одинаковый minsize).
        # Зазоры между панелями одинаковые (PAD+PAD_TIGHT = 12): боковые
        # панели отдают PAD со своей внутренней стороны, чат - PAD_TIGHT с
        # каждой из двух -> все три ПАНЕЛИ теряют по 8 px и остаются равными.
        # Ширина не зависит от режима/вкладки - содержимое всегда уже колонки.
        for col in (0, 1, 2):
            body.grid_columnconfigure(col, weight=1, minsize=COL_MIN)
        body.grid_rowconfigure(0, weight=1)

        # Колонка 0: вкладки Сцена / Settings.
        self._left_col = ctk.CTkFrame(body, fg_color="transparent")
        self._left_col.grid(row=0, column=0, sticky="nsew", padx=(0, PAD))
        self._left_col.grid_rowconfigure(0, weight=1)
        self._left_col.grid_columnconfigure(0, weight=1)

        self._left_tabs = ctk.CTkTabview(self._left_col, width=390,
                                         command=self._on_left_tab)
        self._left_tabs.grid(row=0, column=0, sticky="nsew")
        self._tab_scene = t("tab_scene")
        self._tab_settings = t("tab_settings")
        self._tab_photo = t("tab_photo")        # одно имя: вкладки в разных Tabview
        self._left_tabs.add(self._tab_scene)
        self._left_tabs.add(self._tab_settings)
        self._left_tabs.add(self._tab_photo)
        self._left_seg = self._left_tabs._segmented_button   # для configure(values=)
        self._photo_panels = {}                 # block -> виджеты панели «Фото»
        self._build_preset_panel(self._left_tabs.tab(self._tab_scene))
        self._build_settings_panel(self._left_tabs.tab(self._tab_settings))
        # слева - фото выбранного главного героя (вы), справа - собеседника
        self._build_photo_tab(self._left_tabs.tab(self._tab_photo), "protagonist")

        # Кнопка «свернуть» - оверлеем в левом верхнем углу колонки, вровень
        # с переключателем вкладок (у CTkTabview таб-бар по центру, слева
        # пусто). place() не занимает ячейку сетки -> вкладки не съезжают.
        self._left_collapse_btn = ctk.CTkButton(
            self._left_col, text="‹", width=28, height=26, fg_color="gray30",
            hover_color="gray40", command=self._toggle_left_panel)
        self._left_collapse_btn.place(x=0, y=10)

        # Узкая полоска «развернуть», видна только когда левая панель свёрнута.
        lstrip = ctk.CTkFrame(body, width=26)
        lstrip.grid(row=0, column=0, sticky="ns", padx=(0, PAD))
        lstrip.grid_propagate(False)
        ctk.CTkButton(lstrip, text="›\n" + "\n".join(t("tab_scene")), width=20,
                      fg_color="gray25", hover_color="gray35",
                      command=self._toggle_left_panel).pack(
            fill="both", expand=True, padx=PAD_TIGHT // 2, pady=PAD_TIGHT // 2)
        lstrip.grid_remove()
        self._left_reopen = lstrip

        self._build_chat_panel(body)
        self._build_logs_panel(body)

    # ---------------------------------------- справочные окна ----
    def _open_about(self):
        self._open_info_window("_about_win", "about")

    def _open_help(self):
        self._open_info_window("_help_win", "help")

    def _open_faq(self):
        self._open_info_window("_faq_win", "faq")

    def _open_model_library(self):
        """Открыть каталог моделей Ollama в браузере по умолчанию."""
        webbrowser.open("https://ollama.com/library")

    def _open_cmd(self):
        """Открыть системную командную строку + окно-шпаргалку по Ollama."""
        self._open_info_window("_cheat_win", "cheatsheet")
        try:
            if sys.platform == "win32":
                subprocess.Popen("cmd /K",
                                 creationflags=subprocess.CREATE_NEW_CONSOLE)
            elif sys.platform == "darwin":
                subprocess.Popen(["open", "-a", "Terminal"])
            else:
                for term in ("x-terminal-emulator", "gnome-terminal",
                             "konsole", "xterm"):
                    try:
                        subprocess.Popen([term])
                        break
                    except FileNotFoundError:
                        continue
        except Exception as e:
            messagebox.showwarning(t("cmd_failed_title"), t("cmd_failed_msg", err=e))

    def _open_info_window(self, attr, name):
        """Немодальное окно со скроллом справочного текста. Повторный клик
        по кнопке не плодит копии - существующее окно поднимается наверх."""
        title = t(f"{name}_title")
        blocks = help_texts.blocks(name)
        win = getattr(self, attr, None)
        if win is not None and win.winfo_exists():
            win.lift()
            win.focus_force()
            return
        win = ctk.CTkToplevel(self)
        win.title(title)
        win.geometry("760x680")
        win.transient(self)
        setattr(self, attr, win)

        frame = ctk.CTkScrollableFrame(win, fg_color="transparent")
        frame.pack(fill="both", expand=True, padx=PAD_SEC, pady=PAD_SEC)
        wrap = 680
        for kind, text in blocks:
            if kind == "h":
                ctk.CTkLabel(frame, text=text, anchor="w", justify="left",
                             wraplength=wrap,
                             font=ctk.CTkFont(size=15, weight="bold")).pack(
                    fill="x", anchor="w", pady=(PAD_SEC, PAD_TIGHT))
            elif kind == "q":
                ctk.CTkLabel(frame, text=text, anchor="w", justify="left",
                             wraplength=wrap,
                             font=ctk.CTkFont(size=13, weight="bold")).pack(
                    fill="x", anchor="w", pady=(PAD_SEC, 2))
            elif kind == "li":
                row = ctk.CTkFrame(frame, fg_color="transparent")
                row.pack(fill="x", anchor="w", pady=(0, 2))
                ctk.CTkLabel(row, text="•", anchor="nw", width=14,
                             font=ctk.CTkFont(size=13)).pack(
                    side="left", anchor="n", padx=(PAD, PAD_TIGHT))
                ctk.CTkLabel(row, text=text, anchor="w", justify="left",
                             wraplength=wrap - 24,
                             font=ctk.CTkFont(size=13)).pack(
                    side="left", anchor="n", fill="x")
            else:  # "p"
                ctk.CTkLabel(frame, text=text, anchor="w", justify="left",
                             wraplength=wrap, font=ctk.CTkFont(size=13)).pack(
                    fill="x", anchor="w", pady=(0, PAD_TIGHT))

        bar = ctk.CTkFrame(win, fg_color="transparent")
        bar.pack(fill="x", padx=PAD_SEC, pady=(0, PAD_SEC))
        ctk.CTkButton(bar, text=t("info_close"), width=100,
                      command=win.destroy).pack(side="right")

        def _raise():
            if win.winfo_exists():
                win.lift()
                win.focus_force()
        win.after(90, _raise)

    def _build_preset_panel(self, parent):
        # Вкладка «Сцена», сетка:
        #   row 0 - шапка «Пресеты сцены», фикс. высота HEAD_H (как тулбар
        #           Logs и подпись «Диалог» -> верх скролла на одной линии);
        #   row 1 - скролл с селекторами: фикс. высота PRESET_MIN_H (столько
        #           же и на dialogue, и на story-с-парой-персонажей). Длинный
        #           список - скроллится, не выталкивая блоки ниже;
        #   row 2 - «Дополнительные детали»: РЕЗИНОВОЕ (weight=1), забирает
        #           весь лишний вертикальный запас, растёт ВВЕРХ; низ поля
        #           остаётся на линии с низом «Твоя реплика» / `logs_box`;
        #   row 3 - подсказка про «—» на сером фоне вкладки: ВСЕГДА видна.
        parent.grid_rowconfigure(0, weight=0)
        parent.grid_rowconfigure(1, weight=0, minsize=PRESET_MIN_H)
        parent.grid_rowconfigure(2, weight=1, minsize=DETAILS_MIN_H)
        parent.grid_rowconfigure(3, weight=0)
        parent.grid_columnconfigure(0, weight=1)

        phead = ctk.CTkFrame(parent, fg_color="transparent", height=HEAD_H)
        phead.grid(row=0, column=0, sticky="ew")
        phead.grid_propagate(False)
        phead.grid_columnconfigure(0, weight=1)
        phead.grid_rowconfigure(0, weight=1)
        ctk.CTkLabel(phead, text=t("scene_presets"), corner_radius=6,
                     fg_color=("gray75", "gray25")).grid(
            row=0, column=0, sticky="ew", padx=PAD_TIGHT)

        panel = ctk.CTkScrollableFrame(parent, fg_color="transparent")
        panel.grid(row=1, column=0, sticky="nsew")
        self._preset_panel = panel
        self._autohide_scrollbar(panel)

        # Селекторные строки для всех блоков с одиночным выбором.
        self.block_rows = {b: self._make_selector_row(panel, b) for b in BLOCK_ORDER}

        # --- story: несколько персонажей ---
        sec = ctk.CTkFrame(panel, fg_color="transparent")
        ctk.CTkLabel(sec, text=t("story_chars_label"), anchor="w").pack(anchor="w")
        pick = ctk.CTkFrame(sec, fg_color="transparent")
        pick.pack(fill="x", pady=(PAD_TIGHT, 0))
        self.story_char_pick_var = tk.StringVar(value=NONE_CHOICE)
        self.story_char_pick_menu = ctk.CTkOptionMenu(
            pick, variable=self.story_char_pick_var, values=[NONE_CHOICE])
        ctk.CTkButton(pick, text=t("configure_btn"), width=90,
                      command=lambda: self._open_manager("character")).pack(side="right")
        ctk.CTkButton(pick, text=t("add_btn"), width=80,
                      command=self._add_story_character).pack(side="right", padx=(0, PAD_TIGHT))
        self.story_char_pick_menu.pack(side="left", fill="x", expand=True, padx=(0, PAD_TIGHT))
        self.story_chars_list = ctk.CTkFrame(sec, fg_color="transparent")
        self.story_chars_list.pack(fill="x", pady=(PAD_TIGHT, 0))
        self.story_char_section = sec

        # --- story: «Размер истории» (только меню; «Доп. детали» - ниже) ---
        sec2 = ctk.CTkFrame(panel, fg_color="transparent")
        ctk.CTkLabel(sec2, text=t("story_size_label"), anchor="w").pack(anchor="w")
        self.story_size_var = tk.StringVar(value=NONE_CHOICE)
        self.story_size_menu = ctk.CTkOptionMenu(
            sec2, variable=self.story_size_var, values=STORY_SIZE_CHOICES(),
            dynamic_resizing=False)
        self.story_size_menu.pack(fill="x", pady=(PAD_TIGHT, 0))
        self.story_params_section = sec2

        # режим Chat: сцены и памяти нет, эта вкладка не используется
        self._chat_note = ctk.CTkLabel(
            panel, justify="left", text_color="gray", font=ctk.CTkFont(size=12),
            text=t("chat_mode_note"))

        # --- «Дополнительные детали»: row 2, резиновое поле. Растёт вверх на
        # весь лишний запас (row 2 `weight=1`), низ остаётся на линии с
        # низом «Твоя реплика» и панели Logs. `height=156` - только минимум.
        # Своё поле на каждый режим (переключается в _apply_mode_view).
        host = ctk.CTkFrame(parent, fg_color="transparent")
        host.grid(row=2, column=0, sticky="nsew", pady=(PAD, 0))
        host.grid_columnconfigure(0, weight=1)
        host.grid_rowconfigure(1, weight=1)   # поле тянется
        ctk.CTkLabel(host, text=t("extra_details_label"),
                     anchor="w").grid(row=0, column=0, sticky="w")
        self.dialogue_details_box = ctk.CTkTextbox(host, height=156, wrap="word")
        self.dialogue_details_box.grid(row=1, column=0, sticky="nsew")
        self.story_details_box = ctk.CTkTextbox(host, height=156, wrap="word")
        self.story_details_box.grid(row=1, column=0, sticky="nsew")
        self._details_host = host

        # Подсказка про «—» - на сером фоне вкладки, в самом низу; в один ряд
        # с Ctrl+Enter под чатом и пояснением под Logs/Память.
        self._left_hint = ctk.CTkLabel(
            parent, text=t("none_hint", none=NONE_CHOICE),
            font=ctk.CTkFont(size=10), text_color="gray", anchor="w",
            justify="left", wraplength=380)
        # нижний отступ меньше (у CTkTabview свой внутренний паддинг снизу),
        # чтобы низ подсказки встал на линию с Ctrl+Enter под чатом.
        self._left_hint.grid(row=3, column=0, sticky="ew", pady=(3, 2))

        # всё, что _apply_mode_view прячет/показывает (pack внутри скролла)
        self._panel_sections = (list(self.block_rows.values())
                                + [self.story_char_section,
                                   self.story_params_section,
                                   self._chat_note])

    def _autohide_scrollbar(self, sframe):
        """Полоса прокрутки CTkScrollableFrame видна, только когда содержимое
        реально не влезает. Проверка отложена на `after_idle` (разрывает
        синхронную рекурсию «grid полосы → <Configure> → …»), читает
        актуальный `canvas.yview()` и триггерится и прокруткой
        (`yscrollcommand`), и изменением размеров (`<Configure>`)."""
        try:
            bar = sframe._scrollbar
            canvas = sframe._parent_canvas
        except AttributeError:
            return
        st = {"pending": False}

        def _check():
            st["pending"] = False
            if not bar.winfo_exists():
                return
            try:
                lo, hi = canvas.yview()
            except Exception:
                return
            need = (float(hi) - float(lo)) < 0.999
            if need != bool(bar.winfo_ismapped()):
                bar.grid() if need else bar.grid_remove()

        def _schedule(*_a):
            if not st["pending"]:
                st["pending"] = True
                self.after_idle(_check)

        orig_set = bar.set

        def _set(lo, hi):
            orig_set(lo, hi)
            _schedule()

        canvas.configure(yscrollcommand=_set)
        sframe.bind("<Configure>", _schedule, add="+")
        canvas.bind("<Configure>", _schedule, add="+")
        sframe._autohide_recheck = _schedule   # дёргать после смены раскладки
        self.after(200, _check)

    def _make_selector_row(self, panel, block):
        row = ctk.CTkFrame(panel, fg_color="transparent")
        ctk.CTkLabel(row, text=i18n.block_title(block), anchor="w").pack(anchor="w")
        controls = ctk.CTkFrame(row, fg_color="transparent")
        controls.pack(fill="x", pady=(PAD_TIGHT, 0))
        var = tk.StringVar(value=NONE_CHOICE)
        menu = ctk.CTkOptionMenu(
            controls, variable=var, values=[NONE_CHOICE],
            command=lambda choice, b=block: self._on_select_preset(b, choice))
        # «Настроить» прижата к правому краю (в линию с краем полей ниже),
        # селектор тянется на всю оставшуюся ширину.
        ctk.CTkButton(controls, text=t("configure_btn"), width=90,
                      command=lambda b=block: self._open_manager(b)).pack(side="right")
        menu.pack(side="left", fill="x", expand=True, padx=(0, PAD_TIGHT))
        self.block_menus[block] = (menu, var)
        return row

    # ------------------------------------------------- вкладка Settings ----
    def _build_settings_panel(self, parent):
        panel = ctk.CTkScrollableFrame(parent, label_text=t("gen_params"))
        panel.pack(fill="both", expand=True)
        WRAP = 300   # минимальная ширина переноса (узкая колонка / свёрнуто)

        # Пояснительные подписи переносятся по фактической ширине колонки:
        # на весь экран они занимают всё доступное место, при сужении - не
        # уже WRAP. Список (label, extra): extra прибавляется к базовой
        # ширине (у жирных заголовков полей чуть шире).
        self._settings_wrap = []

        intro = ctk.CTkLabel(
            panel, justify="left", anchor="w", wraplength=WRAP,
            text_color="gray", font=ctk.CTkFont(size=11),
            text=t("settings_intro"))
        intro.pack(fill="x", anchor="w", padx=PAD, pady=(PAD, PAD_TIGHT))
        self._settings_wrap.append((intro, 0))

        self._inf_widgets = {}     # attr -> (kind, widget)
        for spec in INFERENCE_FIELDS:
            lbl = ctk.CTkLabel(panel, text=i18n.inf_label(spec["attr"], spec["label"]),
                               anchor="w", justify="left", wraplength=WRAP + 20,
                               font=ctk.CTkFont(weight="bold"))
            lbl.pack(fill="x", anchor="w", padx=PAD, pady=(PAD_SEC, 0))
            self._settings_wrap.append((lbl, 20))
            kind = spec["kind"]
            if kind == "think":
                _tl = i18n.think_labels()
                w = ctk.CTkOptionMenu(panel, values=list(_tl.values()), width=170)
                w.set(_tl[None])
                w.pack(anchor="w", padx=PAD, pady=(PAD_TIGHT, 0))
            elif kind == "bool":
                # «Галерея» гасит/включает вкладки «Фото», «Эмотиконы» -
                # окна поверх интерфейса и кнопку «скрыть» вверху
                cmd = (self._sync_side_tabs
                       if spec["attr"] in ("show_gallery", "show_emotes") else None)
                w = ctk.CTkCheckBox(panel, text="", command=cmd)
                if spec["attr"] == "show_emotes" and not overlay.AVAILABLE:
                    w.configure(state="disabled")      # не Windows / нет Pillow
                w.pack(anchor="w", padx=PAD, pady=(PAD_TIGHT, 0))
            elif kind == "stoplist":
                w = ctk.CTkTextbox(panel, height=64, wrap="none")
                w.pack(fill="x", padx=PAD, pady=(PAD_TIGHT, 0))
            else:
                w = ctk.CTkEntry(panel, placeholder_text=spec.get("ph", ""))
                w.pack(fill="x", padx=PAD, pady=(PAD_TIGHT, 0))
            self._inf_widgets[spec["attr"]] = (kind, w)

            help_lbl = ctk.CTkLabel(
                panel, text=i18n.inf_help(spec["attr"], spec["help"]),
                justify="left", anchor="w",
                wraplength=WRAP, text_color="gray",
                font=ctk.CTkFont(size=11))
            help_lbl.pack(fill="x", anchor="w", padx=PAD, pady=(PAD_TIGHT, 0))
            self._settings_wrap.append((help_lbl, 0))

        # Пересчёт переноса по ширине видимой области скролла.
        _canvas = panel._parent_canvas

        def _relayout_settings_wrap(_e=None):
            # отложенный after(200) может сработать уже после destroy панели
            # (пересборка под смену языка) - тихо выходим.
            try:
                if not _canvas.winfo_exists():
                    return
                w = _canvas.winfo_width()
            except tk.TclError:
                return
            if w <= 1:
                return
            base = max(WRAP, w - 2 * PAD - PAD_TIGHT)
            for lbl, extra in self._settings_wrap:
                try:
                    lbl.configure(wraplength=base + extra)
                except tk.TclError:
                    pass

        _canvas.bind("<Configure>", _relayout_settings_wrap, add="+")
        self.after(200, _relayout_settings_wrap)

        bar = ctk.CTkFrame(panel, fg_color="transparent")
        bar.pack(fill="x", padx=PAD, pady=PAD_SEC)
        ctk.CTkButton(bar, text=t("save_settings"),
                      command=self._save_inference).pack(side="left")
        ctk.CTkButton(bar, text=t("optimal_btn"), width=84,
                      command=self._optimal_inference).pack(side="left", padx=PAD_TIGHT)
        ctk.CTkButton(bar, text=t("clear_btn"), width=84, fg_color="gray30",
                      hover_color="gray40",
                      command=self._reset_inference).pack(side="left")

    def _no_model(self, model):
        return not model or model in ("...", t("no_models"), "модели не найдены",
                                      "no models found")

    def _update_model_caps(self):
        """Спросить /api/show о выбранной модели и обновить бейдж reasoning."""
        model = self.model_var.get()
        if self._no_model(model):
            self._model_caps = set()
        else:
            self._model_caps = model_capabilities(model)
        self._render_reasoning_badge()

    def _on_model_selected(self, _value=None):
        """Пользователь выбрал модель в верхнем меню - обновить бейдж
        reasoning и СРАЗУ запомнить выбор на диск (не ждать «Сохранить» в
        Settings или закрытия окна), чтобы при следующем запуске активной
        осталась именно она, а не первая по алфавиту/времени пулла."""
        self._update_model_caps()
        try:
            self.store.save_settings(self._collect_inference_config())
        except Exception:
            pass

    def _render_reasoning_badge(self):
        if "thinking" in self._model_caps:
            self._reasoning_prefix.configure(text="Reasoning:")
            self._reasoning_state.configure(text="enabled")
        elif self._model_caps:
            self._reasoning_prefix.configure(text="Reasoning:")
            self._reasoning_state.configure(text="disabled")
        else:
            self._reasoning_prefix.configure(text="")
            self._reasoning_state.configure(text="")

    def _resolve_reasoning(self, want):
        """
        want (вкладка Settings): None='как у модели' / True='включить' /
        False='выключить'. Возвращает (think, nudge):
          think - что слать в chat_stream (True/False/None);
          nudge - добавлять ли в промпт просьбу рассуждать в <think>.

        Модель С capability "thinking":
          want None/True -> think=True; want False -> think=False; nudge=False.
        Модель БЕЗ capability (официальный think дал бы 400):
          want True  -> think=None, nudge=True  (наталкиваем промптом);
          want None/False -> think=None, nudge=False (не трогаем).
        Инлайновые <think>...</think> из ответа режутся всегда, отдельно.
        """
        if "thinking" in self._model_caps:
            return (False if want is False else True), False
        return (None, want is True)

    @staticmethod
    def _parse_num(text, cast):
        text = (text or "").strip()
        if not text:
            return None
        try:
            return cast(text)
        except ValueError:
            return None

    def _collect_inference_config(self) -> InferenceConfig:
        _tfl = i18n.think_from_label()
        kwargs = {}
        for attr, (kind, w) in self._inf_widgets.items():
            if kind == "think":
                kwargs[attr] = _tfl.get(w.get())
            elif kind == "bool":
                kwargs[attr] = bool(w.get())
            elif kind == "stoplist":
                kwargs[attr] = w.get("1.0", "end").strip()
            elif kind == "float":
                kwargs[attr] = self._parse_num(w.get(), float)
            elif kind == "int":
                kwargs[attr] = self._parse_num(w.get(), int)
            else:  # "str"
                kwargs[attr] = w.get().strip()
        kwargs["digest_prompt"] = getattr(self, "_digest_prompt", "")
        kwargs["right_panel_hidden"] = getattr(self, "_right_hidden", False)
        kwargs["left_panel_hidden"] = getattr(self, "_left_hidden", False)
        kwargs["emotes_mode"] = getattr(self, "_emotes_mode", "all")
        kwargs["ui_language"] = getattr(self, "_ui_language", "ru")
        # плейсхолдеры ("...", "модели не найдены") не запоминаем - иначе
        # сохранение в момент, когда Ollama временно недоступна/список
        # моделей пуст, затёрло бы последнюю реально выбранную. В этом
        # случае просто оставляем то, что уже было запомнено раньше.
        cur_model = getattr(self, "model_var", None)
        cur_model = cur_model.get() if cur_model is not None else ""
        if self._no_model(cur_model):
            kwargs["last_model"] = getattr(self, "_last_model", "")
        else:
            kwargs["last_model"] = cur_model
            self._last_model = cur_model
        return InferenceConfig(**kwargs)

    def _load_inference_into_widgets(self, cfg: InferenceConfig, ui_state: bool = True):
        # ui_state=False: только числовые поля Settings (кнопки «Optimal» /
        # «Очистить» не должны трогать промпт памяти и состояние панелей).
        if ui_state:
            self._digest_prompt = cfg.digest_prompt or ""
            self._right_hidden = bool(cfg.right_panel_hidden)
            self._left_hidden = bool(cfg.left_panel_hidden)
            self._emotes_mode = cfg.emotes_mode
        _tl = i18n.think_labels()
        for attr, (kind, w) in self._inf_widgets.items():
            val = getattr(cfg, attr)
            if kind == "think":
                w.set(_tl.get(val, _tl[None]))
            elif kind == "bool":
                w.select() if val else w.deselect()
            elif kind == "stoplist":
                w.delete("1.0", "end")
                if val:
                    w.insert("1.0", val)
            else:
                w.delete(0, "end")
                if val is not None and val != "":
                    w.insert(0, str(val))
        # галки «Галерея»/«Эмотиконы» могли смениться программно (Optimal /
        # Очистить / загрузка настроек) - вкладки «Фото» подстроить
        if hasattr(self, "_left_seg") and hasattr(self, "_tab_logs"):
            self._sync_side_tabs()

    def _save_inference(self):
        self.store.save_settings(self._collect_inference_config())
        messagebox.showinfo(t("settings_saved_title"), t("settings_saved_msg"))

    def _optimal_inference(self):
        """Вернуть все поля к рекомендованным значениям."""
        self._load_inference_into_widgets(InferenceConfig.optimal(), ui_state=False)

    def _reset_inference(self):
        """Очистить все поля (модель решает всё сама)."""
        self._load_inference_into_widgets(InferenceConfig(), ui_state=False)

    def _apply_mode_view(self, mode):
        """Показать нужный набор секций левой панели под текущий режим."""
        for w in self._panel_sections:
            w.pack_forget()
        if mode == "dialogue":
            rows = [self.block_rows["protagonist"], self.block_rows["character"],
                    self.block_rows["environment"], self.block_rows["scenario"],
                    self.block_rows["system_config"]]
        elif mode == "story":
            rows = [self.block_rows["protagonist"], self.story_char_section,
                    self.block_rows["scenario"], self.block_rows["system_config"],
                    self.story_params_section]
        else:  # chat - сцена не используется
            rows = [self._chat_note]
        for w in rows:
            w.pack(fill="x", padx=PAD, pady=PAD_TIGHT)

        # «Дополнительные детали» под скроллом: своё поле на режим; в chat
        # блок и подсказка про «—» не нужны.
        if mode == "chat":
            self._details_host.grid_remove()
            self._left_hint.grid_remove()
        else:
            self._details_host.grid()
            self._left_hint.grid()
            self.dialogue_details_box.grid_remove()
            self.story_details_box.grid_remove()
            (self.story_details_box if mode == "story"
             else self.dialogue_details_box).grid()

        # Память - только диалог. В story/chat кнопку вкладки «Память»
        # прячем (дайджест не генерируется и к запросу не цепляется); сам
        # фрейм вкладки жив, содержимое не пересобирается.
        # В режиме Chat левую колонку сразу показываем на «Настройки».
        if mode == "chat":
            try:
                self._set_tab(self._left_tabs, self._tab_settings)
            except Exception:
                pass
        # «Память» и «Фото» - только диалог (остальные режимы - прячем
        # кнопки вкладок; фреймы живы, ничего не пересобирается), «Фото»
        # ещё и неактивна при выключенной настройке: см. _sync_side_tabs.
        self._sync_side_tabs()

        rc = getattr(self._preset_panel, "_autohide_recheck", None)
        if rc:
            rc()
        self._refresh_active_label()

    # --------------------------------------------- story: несколько персонажей ----
    def _refresh_story_char_pick(self):
        names = [p.name for p in self._load_block_presets("character") if p.name]
        values = [NONE_CHOICE] + names
        self.story_char_pick_menu.configure(values=values)
        if self.story_char_pick_var.get() not in values:
            self.story_char_pick_var.set(values[0])

    def _add_story_character(self):
        name = self.story_char_pick_var.get()
        if not name or name == NONE_CHOICE:
            return
        obj = next((p for p in self._load_block_presets("character")
                    if p.name == name), None)
        if obj is None or any(c.id == obj.id for c in self.story_characters):
            return
        self.story_characters.append(obj)
        self._render_story_characters()
        self._refresh_active_label()

    def _remove_story_character(self, char_id):
        self.story_characters = [c for c in self.story_characters if c.id != char_id]
        self._render_story_characters()
        self._refresh_active_label()

    def _render_story_characters(self):
        for w in self.story_chars_list.winfo_children():
            w.destroy()
        if not self.story_characters:
            ctk.CTkLabel(self.story_chars_list, text=t("no_chars"),
                         font=ctk.CTkFont(size=11), text_color="gray").pack(anchor="w")
            return
        for c in self.story_characters:
            r = ctk.CTkFrame(self.story_chars_list, fg_color="transparent")
            r.pack(fill="x", pady=(PAD_TIGHT, 0))
            ctk.CTkButton(r, text="✕", width=26, fg_color="#a33333",
                          hover_color="#c44444",
                          command=lambda cid=c.id: self._remove_story_character(cid)
                          ).pack(side="left")
            ctk.CTkLabel(r, text=c.name or t("unnamed"), anchor="w").pack(
                side="left", padx=(PAD_TIGHT, 0))
        rc = getattr(getattr(self, "_preset_panel", None), "_autohide_recheck", None)
        if rc:
            rc()

    _MODES = ["dialogue", "story", "chat"]

    def _build_chat_panel(self, parent):
        # Центр - тоже CTkTabview (как боковые панели -> одинаковый хром и
        # выравнивание), но его таб-бар = ПЕРЕКЛЮЧАТЕЛЬ РЕЖИМОВ: клик по
        # вкладке зовёт _on_mode_change. Содержимое (chat_box + поля ввода)
        # построено ОДИН раз как ребёнок самого CTkTabview и лежит поверх
        # (пустых) вкладок в том же ряду - не пересоздаётся при смене режима.
        col = ctk.CTkFrame(parent, fg_color="transparent")
        col.grid(row=0, column=1, sticky="nsew", padx=PAD_TIGHT)
        col.grid_rowconfigure(0, weight=1)
        col.grid_columnconfigure(0, weight=1)

        self._chat_tabs = ctk.CTkTabview(col, width=390,
                                         command=self._on_chat_tab_switch)
        self._chat_tabs.grid(row=0, column=0, sticky="nsew")
        _ml = MODE_LABELS()
        for m in self._MODES:
            self._chat_tabs.add(_ml[m])
        self._chat_tabs.set(_ml[self.mode_value])

        body = ctk.CTkFrame(self._chat_tabs, fg_color="transparent")
        # тот же ряд и тот же внутренний отступ (corner_radius), что CTkTabview
        # даёт своим фреймам-вкладкам -> контент ровно на их месте.
        _cr = self._chat_tabs.cget("corner_radius")
        body.grid(row=3, column=0, sticky="nsew", padx=_cr, pady=_cr)
        body.grid_rowconfigure(1, weight=1)          # 0 - шапка HEAD_H, 1 - чат, 2 - ввод
        body.grid_columnconfigure(0, weight=1)
        self._chat_body = body

        # Ряд HEAD_H - как «Пресеты сцены» слева и тулбар Logs справа. Внутри -
        # плашка с однострочной подсказкой по текущему режиму (текст ставит
        # _apply_input_mode из MODE_HINTS).
        mh = ctk.CTkFrame(body, fg_color="transparent", height=HEAD_H)
        mh.grid(row=0, column=0, sticky="ew")
        mh.grid_propagate(False)
        mh.grid_columnconfigure(0, weight=1)
        mh.grid_rowconfigure(0, weight=1)
        self._mode_hint = ctk.CTkLabel(
            mh, text="", corner_radius=6, fg_color=("gray75", "gray25"),
            font=ctk.CTkFont(size=12))
        self._mode_hint.grid(row=0, column=0, sticky="ew", padx=PAD_TIGHT)

        self.chat_box = ctk.CTkTextbox(body, wrap="word", state="disabled")
        self.chat_box.grid(row=1, column=0, sticky="nsew", pady=(0, PAD))
        # Строки действий/чувств - курсивом + приглушённым цветом.
        # CTkTextbox.tag_config запрещает font=, поэтому работаем с
        # внутренним tkinter.Text напрямую. Если не вышло - _action_tag=None
        # и действия оборачиваются в *звёздочки* (см. _action_piece).
        self._action_tag = None
        try:
            tb = self.chat_box._textbox
            base = tkfont.Font(font=tb.cget("font"))
            self._chat_italic = tkfont.Font(family=base.actual("family"),
                                            size=base.actual("size"),
                                            slant="italic")
            tb.tag_configure("action", font=self._chat_italic,
                             foreground="#9aa4b0")
            self._action_tag = "action"
        except Exception:
            self._action_tag = None
        # Поля абзаца для хода с аватаркой: первая строка начинается с самой
        # аватарки (уже с зазором справа), все остальные строки хода - и
        # перенесённые, и после \n - сдвинуты ровно на её ширину, так что
        # текст реплики идёт ровной колонкой правее фото. Размер аватарки -
        # от высоты строки шрифта чата (масштаб экрана учтён сам).
        self._avatar_px = 0
        self._avatar_gap = 0
        try:
            ls = tkfont.Font(font=self.chat_box._textbox.cget("font")).metrics("linespace")
            self._avatar_px = max(28, int(ls * AVATAR_LINES))
            self._avatar_gap = max(6, ls // 3)
            w = self._avatar_px + self._avatar_gap
            tb = self.chat_box._textbox
            tb.tag_configure("hang1", lmargin1=0, lmargin2=w)
            tb.tag_configure("hang", lmargin1=w, lmargin2=w)
        except Exception:
            self._avatar_px = 0

        form = ctk.CTkFrame(body, fg_color="transparent")
        # нижний отступ = как у боковых подсказок (`pady=(3, 2)`), чтобы низ
        # `_dlg_hint` / `reply_box` совпал с `_left_hint` / `logs_box`.
        form.grid(row=2, column=0, sticky="ew", pady=(0, 2))
        form.grid_columnconfigure(0, weight=1)

        # Колонки ввода тянутся по высоте колонки кнопок (row 0), нижнее поле
        # каждого режима забирает разницу -> его низ совпадает с низом
        # «Экспорт…». Подсказка Ctrl+Enter вынесена под обе колонки (row 1).

        # --- ввод для режима dialogue: действие + реплика ---
        self._dlg_input = ctk.CTkFrame(form, fg_color="transparent")
        self._dlg_input.grid(row=0, column=0, sticky="nsew")
        self._dlg_input.grid_columnconfigure(0, weight=1)
        self._dlg_input.grid_rowconfigure(3, weight=1)   # «реплика» тянется вниз
        ctk.CTkLabel(self._dlg_input, text=t("dlg_action_label"),
                     anchor="w").grid(row=0, column=0, sticky="w")
        self.act_box = ctk.CTkTextbox(self._dlg_input, height=52, wrap="word")
        self.act_box.grid(row=1, column=0, sticky="ew")
        ctk.CTkLabel(self._dlg_input, text=t("dlg_reply_label"),
                     anchor="w").grid(row=2, column=0, sticky="w", pady=(PAD, 0))
        self.reply_box = ctk.CTkTextbox(self._dlg_input, height=48, wrap="word")
        self.reply_box.grid(row=3, column=0, sticky="nsew")

        # --- ввод для режима story: свободные указания / правки ---
        self._story_input = ctk.CTkFrame(form, fg_color="transparent")
        self._story_input.grid(row=0, column=0, sticky="nsew")
        self._story_input.grid_columnconfigure(0, weight=1)
        self._story_input.grid_rowconfigure(1, weight=1)
        ctk.CTkLabel(self._story_input, text=t("story_input_label"),
                     anchor="w").grid(row=0, column=0, sticky="w")
        self.story_input = ctk.CTkTextbox(self._story_input, height=48, wrap="word")
        self.story_input.grid(row=1, column=0, sticky="nsew")

        # --- ввод для режима chat: просто сообщение ---
        self._chat_input = ctk.CTkFrame(form, fg_color="transparent")
        self._chat_input.grid(row=0, column=0, sticky="nsew")
        self._chat_input.grid_columnconfigure(0, weight=1)
        self._chat_input.grid_rowconfigure(1, weight=1)
        ctk.CTkLabel(self._chat_input, text=t("chat_msg_label"),
                     anchor="w").grid(row=0, column=0, sticky="w")
        self.chat_msg_box = ctk.CTkTextbox(self._chat_input, height=48, wrap="word")
        self.chat_msg_box.grid(row=1, column=0, sticky="nsew")

        # Подсказка Ctrl+Enter - под колонками ввода и кнопок, во всю ширину.
        hint_kw = dict(anchor="w", justify="left", wraplength=560,
                       font=ctk.CTkFont(size=10), text_color="gray")
        self._dlg_hint = ctk.CTkLabel(form, text=t("hint_send_dialogue"), **hint_kw)
        self._story_hint = ctk.CTkLabel(form, text=t("hint_send_story"), **hint_kw)
        self._chat_hint = ctk.CTkLabel(form, text=t("hint_send_chat"), **hint_kw)
        for h in (self._dlg_hint, self._story_hint, self._chat_hint):
            h.grid(row=1, column=0, columnspan=2, sticky="w", pady=(3, 0))
            h.grid_remove()

        btns = ctk.CTkFrame(form, fg_color="transparent")
        # pady=(28, 0) - НЕ из общей шкалы: опускает колонку на высоту подписи
        # над первым полем, чтобы «Отправить» встала ровно на его верхний край.
        btns.grid(row=0, column=1, sticky="n", padx=(PAD, 0), pady=(28, 0))
        self.send_btn = ctk.CTkButton(btns, text=t("send"), width=124,
                                      command=self._on_send)
        self.send_btn.pack(fill="x")
        self.stop_btn = ctk.CTkButton(btns, text=t("stop"), width=124,
                                      fg_color="#a33333", hover_color="#c44444",
                                      state="disabled", command=self._on_stop)
        self.stop_btn.pack(fill="x", pady=(PAD_TIGHT, 0))
        self.clear_btn = ctk.CTkButton(btns, text=t("clear_btn"), width=124,
                                       command=self._on_clear)
        self.clear_btn.pack(fill="x", pady=(PAD_TIGHT, 0))
        # «Очистить всё»: чат + память + панель Logs (см. _on_clear_all).
        self._clear_all_btn = ctk.CTkButton(btns, text=t("clear_all"), width=124,
                                            fg_color="#8a3a3a", hover_color="#a34a4a",
                                            command=self._on_clear_all)
        self._clear_all_btn.pack(fill="x", pady=(PAD_TIGHT, 0))
        self.export_btn = ctk.CTkButton(btns, text=t("export"), width=124,
                                        fg_color="gray30", hover_color="gray40",
                                        command=self._export_conversation)
        self.export_btn.pack(fill="x", pady=(PAD_TIGHT, 0))
        self.sessions_btn = ctk.CTkButton(btns, text=t("sessions_btn"), width=124,
                                          fg_color="gray30", hover_color="gray40",
                                          command=self._open_sessions)
        self.sessions_btn.pack(fill="x", pady=(PAD_TIGHT, 0))

        for w in (self.act_box, self.reply_box, self.story_input, self.chat_msg_box):
            w.bind("<Control-Return>", lambda e: self._on_send() or "break")

        self._chat_body.tkraise()   # контент поверх (пустых) фреймов вкладок
        self._apply_input_mode(self.mode_value)

    def _on_chat_tab_switch(self):
        """Клик по вкладке центрального таб-бара = смена режима работы."""
        self._chat_body.tkraise()   # вернуть контент поверх только что перегриженного фрейма вкладки
        self._on_mode_change(MODE_FROM_LABEL()[self._chat_tabs.get()])

    def _apply_input_mode(self, mode):
        parts = {"dialogue": (self._dlg_input, self._dlg_hint),
                 "story": (self._story_input, self._story_hint),
                 "chat": (self._chat_input, self._chat_hint)}
        for frame, hint in parts.values():
            frame.grid_remove()
            hint.grid_remove()
        frame, hint = parts.get(mode, parts["dialogue"])
        frame.grid()
        hint.grid()
        self._mode_hint.configure(text=MODE_HINTS().get(mode, ""))

    def _read_input(self):
        return (self.act_box.get("1.0", "end").strip(),
                self.reply_box.get("1.0", "end").strip())

    def _clear_input(self):
        self.act_box.delete("1.0", "end")
        self.reply_box.delete("1.0", "end")

    def _build_logs_panel(self, parent):
        # Зеркало левой колонки: обёртка `_right_col` + `CTkTabview` с
        # вкладками Logs / Память (тот же вид, что «Сцена / Settings»
        # слева). Кнопка «свернуть» «›» - в правом верхнем углу, зеркально
        # «‹» слева. У каждой вкладки свой контент: тулбар + текстбокс +
        # серая подсказка внизу.
        self._right_col = ctk.CTkFrame(parent, fg_color="transparent")
        self._right_col.grid(row=0, column=2, sticky="nsew", padx=(PAD, 0))
        self._right_col.grid_rowconfigure(0, weight=1)
        self._right_col.grid_columnconfigure(0, weight=1)

        self._tab_logs = t("tab_logs")
        self._tab_memory = t("tab_memory")
        self._right_tabs = ctk.CTkTabview(self._right_col, width=390,
                                          command=self._on_right_tab)
        self._right_tabs.grid(row=0, column=0, sticky="nsew")
        self._right_tabs.add(self._tab_logs)
        self._right_tabs.add(self._tab_memory)
        self._right_tabs.add(self._tab_photo)
        self._right_tab = self._right_tabs._segmented_button   # для configure(values=)
        self._build_logs_tab(self._right_tabs.tab(self._tab_logs))
        self._build_memory_tab(self._right_tabs.tab(self._tab_memory))
        self._build_photo_tab(self._right_tabs.tab(self._tab_photo), "character")

        # «свернуть» - оверлеем в правом верхнем углу колонки, зеркально
        # левой кнопке; place() не занимает ячейку сетки.
        self._right_collapse_btn = ctk.CTkButton(
            self._right_col, text="›", width=28, height=26, fg_color="gray30",
            hover_color="gray40", command=self._toggle_right_panel)
        self._right_collapse_btn.place(relx=1.0, x=0, y=10, anchor="ne")

        # Узкая полоска «развернуть», видна только когда панель свёрнута.
        strip = ctk.CTkFrame(parent, width=26)
        strip.grid(row=0, column=2, sticky="ns", padx=(PAD, 0))
        strip.grid_propagate(False)
        ctk.CTkButton(strip, text="‹\n" + "\n".join(t("tab_logs_short")), width=20,
                      fg_color="gray25", hover_color="gray35",
                      command=self._toggle_right_panel).pack(
            fill="both", expand=True, padx=PAD_TIGHT // 2, pady=PAD_TIGHT // 2)
        strip.grid_remove()
        self._right_reopen = strip

        self._on_right_tab()

    def _build_logs_tab(self, tab):
        tab.grid_rowconfigure(1, weight=1)
        tab.grid_columnconfigure(0, weight=1)
        bar = ctk.CTkFrame(tab, fg_color="transparent", height=HEAD_H)
        bar.grid(row=0, column=0, sticky="ew")
        bar.grid_propagate(False)
        bar.grid_columnconfigure(0, weight=1)
        bar.grid_rowconfigure(0, weight=1)
        inner = ctk.CTkFrame(bar, fg_color="transparent")
        inner.grid(row=0, column=0)   # группа кнопок по центру тулбара
        self._logs_clear_btn = ctk.CTkButton(inner, text=t("clear_btn"), width=90,
                                             command=self._clear_logs)
        self._logs_clear_btn.pack(side="left")
        self._logs_export_btn = ctk.CTkButton(
            inner, text=t("export"), width=96, fg_color="gray30",
            hover_color="gray40", command=self._export_logs)
        self._logs_export_btn.pack(side="left", padx=(PAD_TIGHT, 0))
        self.logs_box = ctk.CTkTextbox(
            tab, wrap="none", state="disabled",
            font=ctk.CTkFont(family="Consolas", size=11))
        self.logs_box.grid(row=1, column=0, sticky="nsew")
        ctk.CTkLabel(
            tab, anchor="w", justify="left", wraplength=440,
            font=ctk.CTkFont(size=10), text_color="gray",
            text=t("logs_hint")).grid(row=2, column=0, sticky="w", pady=(3, 2))

    def _build_memory_tab(self, tab):
        tab.grid_rowconfigure(1, weight=1)
        tab.grid_columnconfigure(0, weight=1)
        bar = ctk.CTkFrame(tab, fg_color="transparent", height=HEAD_H)
        bar.grid(row=0, column=0, sticky="ew")
        bar.grid_propagate(False)
        bar.grid_columnconfigure(0, weight=1)
        bar.grid_rowconfigure(0, weight=1)
        inner = ctk.CTkFrame(bar, fg_color="transparent")
        inner.grid(row=0, column=0)   # группа кнопок по центру тулбара
        self._mem_prompt_btn = ctk.CTkButton(inner, text=t("mem_prompt_btn"), width=116,
                                             command=self._edit_digest_prompt)
        self._mem_rebuild_btn = ctk.CTkButton(inner, text=t("mem_rebuild_btn"), width=100,
                                              command=self._rebuild_digest)
        self._mem_apply_btn = ctk.CTkButton(inner, text=t("mem_apply_btn"), width=90,
                                            command=self._apply_digest_edit)
        self._mem_export_btn = ctk.CTkButton(
            inner, text=t("export"), width=90, fg_color="gray30",
            hover_color="gray40", command=self._export_memory)
        self._mem_prompt_btn.pack(side="left")
        self._mem_rebuild_btn.pack(side="left", padx=(PAD_TIGHT, 0))
        self._mem_apply_btn.pack(side="left", padx=(PAD_TIGHT, 0))
        self._mem_export_btn.pack(side="left", padx=(PAD_TIGHT, 0))
        self.memory_box = ctk.CTkTextbox(tab, wrap="word", font=ctk.CTkFont(size=12))
        self.memory_box.grid(row=1, column=0, sticky="nsew")
        ctk.CTkLabel(
            tab, anchor="w", justify="left", wraplength=440,
            font=ctk.CTkFont(size=10), text_color="gray",
            text=t("memory_hint")).grid(row=2, column=0, sticky="w", pady=(3, 2))

    def _on_right_tab(self, *_):
        """Вызывается CTkTabview при клике по вкладке (и вручную)."""
        if self._right_tabs.get() == self._tab_memory:
            self._refresh_memory_box()
        self._refresh_photo_panels()

    def _on_left_tab(self, *_):
        self._refresh_photo_panels()

    # ------------------------------------- фото персонажа: три вида (диалог) ----
    # У персонажа и главного героя (форма пресета) - три НЕЗАВИСИМЫХ вида
    # фото, каждый включается своей галкой в Settings:
    #   АВАТАР    (`photo`)   - одно фото, рисуется в чате рядом с репликами;
    #   ГАЛЕРЕЯ   (`gallery`) - несколько фото, ТОЛЬКО вкладка «Фото»
    #                           (слева - герой, справа - собеседник), стрелками
    #                           можно листать;
    #   ЭМОТИКОНЫ (`emotes`)  - PNG-силуэты на прозрачном фоне, ТОЛЬКО поверх
    #                           интерфейса (overlay.py), на каждый ответ в чате
    #                           сменяются по кругу, вручную - нельзя.
    # В промпт модели ничего из этого не попадает.
    PHOTO_CAPTION_H = 30
    EMOTE_MAX_UP = 1.25         # эмотикон не растягиваем больше чем на 25 %

    _SIDES = {"left": ("protagonist", "_left_tabs", "_left_col"),
              "right": ("character", "_right_tabs", "_right_col")}

    def _set_tab(self, tabs, name):
        """Программно выбрать вкладку CTkTabview. Его set() через 100 мс
        отложенно «забывает» все вкладки, кроме названной, - если рядом (в
        пределах 100 мс) был другой set(), выбранная вкладка пропадала
        (пустая панель). Поэтому после отложенных «забываний» текущую
        вкладку ещё раз выкладываем на место (идемпотентно)."""
        if tabs.get() != name:
            tabs.set(name)

        def _reassert():
            try:
                if tabs.winfo_exists() and tabs.get() in tabs._tab_dict:
                    tabs._set_grid_current_tab()
                    self._refresh_photo_panels()
            except tk.TclError:
                pass
        self.after(110, _reassert)          # сразу после отложенных «забываний» (100 мс)

    def _setting_on(self, attr) -> bool:
        w = self._inf_widgets.get(attr) if hasattr(self, "_inf_widgets") else None
        return bool(w is not None and w[1].get())

    def _avatars_on(self) -> bool:
        return bool(photos.AVAILABLE and self._setting_on("show_avatars"))

    def _gallery_on(self) -> bool:
        return bool(photos.AVAILABLE and self._setting_on("show_gallery"))

    def _emotes_on(self) -> bool:
        """Эмотиконы сейчас должны быть на экране: галка, Windows, диалог и
        режим кнопки вверху не «скрыты»."""
        return bool(overlay.AVAILABLE and self._setting_on("show_emotes")
                    and self.mode_value == "dialogue"
                    and getattr(self, "_emotes_mode", "all") != "hidden")

    def _owner_files(self, block, kind):
        """Имена файлов вида kind ('gallery'/'emotes') активного пресета блока."""
        return list(getattr(self.active.get(block), kind, []) or [])

    # ---- ГАЛЕРЕЯ: вкладки «Фото» ----
    # Фото вписывается в панель целиком, а прозрачный PNG просто сливается с
    # цветом панели: Tk складывает альфа-канал картинки с фоном виджета.
    def _build_photo_tab(self, tab, block):
        # place(), а не grid/pack: размер картинки не должен влиять на
        # геометрию колонки (иначе большое фото расталкивало бы панели).
        img = ctk.CTkLabel(tab, text="", fg_color="transparent", justify="center",
                           wraplength=330, text_color="gray")
        img.place(relx=0.5, rely=0.5, anchor="center")
        cap = ctk.CTkLabel(tab, text="", fg_color="transparent", text_color="gray",
                           font=ctk.CTkFont(size=12))
        cap.place(relx=0.5, rely=1.0, anchor="s", y=-PAD_TIGHT)
        prev_b = ctk.CTkButton(tab, text="‹", width=38, height=30,
                               fg_color="gray30", hover_color="gray40",
                               command=lambda b=block: self._gallery_step(b, -1))
        next_b = ctk.CTkButton(tab, text="›", width=38, height=30,
                               fg_color="gray30", hover_color="gray40",
                               command=lambda b=block: self._gallery_step(b, +1))
        self._photo_panels[block] = {"tab": tab, "img": img, "cap": cap,
                                     "prev": prev_b, "next": next_b,
                                     "ctk": None, "job": None, "key": None}
        tab.bind("<Configure>", lambda _e, b=block: self._schedule_photo_panel(b))

    def _gallery_step(self, block, delta):
        n = len(self._owner_files(block, "gallery"))
        if n > 1:
            self._gallery_idx[block] = (self._gallery_idx.get(block, 0) + delta) % n
            self._schedule_photo_panel(block)

    def _schedule_photo_panel(self, block):
        """Перерисовать панель чуть позже (одним разом на пачку Configure при
        изменении размера окна)."""
        p = self._photo_panels.get(block)
        if not p:
            return
        if p["job"] is not None:
            try:
                self.after_cancel(p["job"])
            except Exception:
                pass
        p["job"] = self.after(40, lambda b=block: self._render_photo_panel(b))

    def _refresh_photo_panels(self):
        """Выбранный пресет/фото/настройки сменились: обновить галереи и
        эмотиконы на обеих сторонах."""
        for block in getattr(self, "_photo_panels", {}):
            self._schedule_photo_panel(block)
        self._overlay_reposition()

    def _render_photo_panel(self, block):
        p = self._photo_panels.get(block)
        if not p:
            return
        p["job"] = None
        try:
            tab, img, cap = p["tab"], p["img"], p["cap"]
            if not tab.winfo_exists():
                return
            obj = self.active.get(block)
            title = i18n.block_title(block)

            def show_text(txt, caption=""):
                p["ctk"], p["key"] = None, None
                img.configure(image="", text=txt)
                img.place_configure(rely=0.5, y=0, anchor="center")
                cap.configure(text=caption)
                p["prev"].place_forget()
                p["next"].place_forget()

            if obj is None:
                show_text(t("photo_panel_none", title=title))
                return
            files = self._owner_files(block, "gallery")
            # у другого пресета - снова с первого фото
            if self._gallery_owner.get(block) != obj.id:
                self._gallery_owner[block] = obj.id
                self._gallery_idx[block] = 0
            pil, name, n, i = None, "", len(files), 0
            if n:
                i = self._gallery_idx.get(block, 0) % n
                name = files[i]
                path = self.store.photo_path(name)
                pil = self._photo_pil(path)
            if pil is None:
                show_text(t("photo_panel_empty", name=obj.name or "—", title=title),
                          obj.name or "")
                return
            # область под картинку: вся панель за вычетом подписи и полей
            sc = tab._get_widget_scaling() or 1.0
            avail_w = int(tab.winfo_width() / sc) - 2 * PAD
            avail_h = int(tab.winfo_height() / sc) - self.PHOTO_CAPTION_H - 2 * PAD
            if avail_w < 40 or avail_h < 40:
                return                         # вкладка не показана / ещё не разложена
            k = min(avail_w / pil.width, avail_h / pil.height, 1.5)
            size = (max(1, int(pil.width * k)), max(1, int(pil.height * k)))
            key = (name, size)
            if p["key"] != key:                # тот же кадр - не пересоздаём
                p["ctk"] = ctk.CTkImage(light_image=pil, dark_image=pil, size=size)
                p["key"] = key
                img.configure(image=p["ctk"], text="")
            # картинка - от верха панели, чтобы не заезжать на подпись/стрелки
            img.place_configure(rely=0.0, y=PAD, anchor="n")
            caption = obj.name or ""
            if n > 1:                           # листалка: стрелки и счётчик
                caption += "  ·  " + t("gallery_counter", i=i + 1, n=n)
                p["prev"].place(relx=0.0, rely=1.0, x=PAD, y=-PAD_TIGHT, anchor="sw")
                p["next"].place(relx=1.0, rely=1.0, x=-PAD, y=-PAD_TIGHT, anchor="se")
            else:
                p["prev"].place_forget()
                p["next"].place_forget()
            cap.configure(text=caption)
        except tk.TclError:
            pass                               # окно пересобирают/закрывают

    def _photo_pil(self, path):
        """PIL-картинка фото (RGBA, с сохранением прозрачности) из кэша."""
        if not path:
            return None
        key = str(path)
        cache = self.__dict__.setdefault("_photo_pil_cache", {})
        if key not in cache:
            cache[key] = photos.load_rgba(path)
        return cache[key]

    # ---- ЭМОТИКОНЫ: PNG-силуэты поверх интерфейса (overlay.py) ----
    # По одному окну на сторону: слева эмотикон героя, справа - собеседника.
    # Нижний край ВСЕХ - низ экрана (монитора, где окно приложения), поэтому
    # они стоят на одном уровне и могут выходить за рамки приложения.
    # По горизонтали - по центру своей колонки, ширина ограничена колонкой
    # (чат по умолчанию не закрываем); остальное - на подборе картинок
    # пользователем. Клики проходят сквозь окна. Меняются на каждый ответ в
    # чате (_emote_advance); один эмотикон - не меняется.
    def _emote_pil(self, block):
        files = self._owner_files(block, "emotes")
        if not files:
            return None
        i = self._emote_idx.get(block, 0) % len(files)
        return self._photo_pil(self.store.photo_path(files[i]))

    def _emote_advance(self, block):
        """Новый ответ в чате: эмотикон этой стороны -> следующий по кругу."""
        if len(self._owner_files(block, "emotes")) > 1:
            self._emote_idx[block] = self._emote_idx.get(block, 0) + 1
        side = "left" if block == "protagonist" else "right"
        self._overlay_place(side)

    def _overlay_hide(self, side):
        ov = self._overlays.get(side)
        if ov is not None:
            ov.hide()

    def _overlay_hide_all(self):
        for side in list(self._overlays):
            self._overlay_hide(side)

    def _overlay_destroy_all(self):
        for ov in list(self._overlays.values()):
            ov.destroy()
        self._overlays = {}

    def _overlay_place(self, side):
        """Поставить/обновить эмотикон этой стороны по текущей геометрии окна."""
        block, _tabs_attr, col_attr = self._SIDES[side]
        col = getattr(self, col_attr)
        try:
            # режим «только собеседник»: эмотикон героя (левая сторона) не рисуем
            shown = self._emotes_on() and not (
                side == "left" and self._emotes_mode == "companion")
            pil = self._emote_pil(block) if shown else None
            ok = (pil is not None and col.winfo_viewable()
                  and self.state() != "iconic")
        except tk.TclError:
            ok = False
        if not ok:
            self._overlay_hide(side)
            return
        ov = self._overlays.get(side)
        if ov is None:
            try:
                ov = self._overlays[side] = overlay.PhotoOverlay(self)
            except Exception:
                return
        mon_bottom = overlay.monitor_bounds(self)[3]
        avail_h = max(80, mon_bottom - self.winfo_rooty())
        x0, w = col.winfo_rootx(), col.winfo_width()
        avail_w = max(40, w - 20)
        k = min(avail_w / pil.width, avail_h / pil.height, self.EMOTE_MAX_UP)
        tw, th = max(1, int(pil.width * k)), max(1, int(pil.height * k))
        x = x0 + (w - tw) // 2
        y = mon_bottom - th                      # общий нижний край - низ экрана
        ov.show(ov.render(pil, tw, th), x, y)

    def _overlay_reposition(self):
        """Окно сдвинули/изменили, настройки/пресет/кнопка сменились - переставить."""
        self._ov_job = None
        for side in ("left", "right"):
            self._overlay_place(side)

    def _schedule_overlay(self, delay=30):
        """Переставить эмотиконы через `delay` мс (одним разом на пачку событий)."""
        if not self._overlays and not self._emotes_on():
            return
        if self._ov_job is not None:
            try:
                self.after_cancel(self._ov_job)
            except Exception:
                pass
        self._ov_job = self.after(delay, self._overlay_reposition)

    def _on_root_configure(self, e):
        if e.widget is self:
            self._schedule_overlay(16)

    def _on_root_unmap(self, e):
        if e.widget is self:
            self._overlay_hide_all()          # окно свернули - эмотиконов не должно быть

    def _on_root_map(self, e):
        if e.widget is self:
            self._schedule_overlay(60)

    def _toggle_emotes(self):
        """Кнопка вверху: все -> только собеседник -> скрыты -> все... (так
        можно освободить левое меню, оставив собеседника, или убрать обоих,
        чтобы добраться до обоих меню). Режим запоминается."""
        i = EMOTES_MODES.index(self._emotes_mode) if self._emotes_mode in EMOTES_MODES else 0
        self._emotes_mode = EMOTES_MODES[(i + 1) % len(EMOTES_MODES)]
        self._sync_emotes_ui()
        try:
            self.store.save_settings(self._collect_inference_config())
        except Exception:
            pass

    def _sync_emotes_ui(self):
        """Кнопка режима эмотиконов видна только когда есть что переключать
        (галка, Windows, диалог); подпись = текущий режим; заодно
        переставляет сами окна."""
        btn = getattr(self, "_emote_btn", None)
        if btn is not None:
            show = bool(overlay.AVAILABLE and self._setting_on("show_emotes")
                        and self.mode_value == "dialogue")
            try:
                if show:
                    btn.configure(text=t(f"emotes_mode_{self._emotes_mode}"))
                    if not btn.winfo_ismapped():
                        btn.pack(side="right", padx=(PAD, PAD_TIGHT))
                elif btn.winfo_ismapped():
                    btn.pack_forget()
            except tk.TclError:
                pass
        self._overlay_reposition()

    def _sync_side_tabs(self):
        """Набор и доступность вкладок боковых панелей под режим и настройки:
        «Память» и «Фото» - только в диалоге; «Фото» (галерея) неактивна, если
        галка «Галерея» выключена (или нет Pillow). Зовётся при смене режима,
        переключении галок, загрузке настроек и пересборке окна."""
        dlg = self.mode_value == "dialogue"
        on = self._gallery_on()
        lvals = [self._tab_scene, self._tab_settings] + ([self._tab_photo] if dlg else [])
        rvals = [self._tab_logs] + ([self._tab_memory, self._tab_photo] if dlg else [])
        # выбранная вкладка исчезла/неактивна -> на первую
        if self._left_tabs.get() not in lvals or (
                self._left_tabs.get() == self._tab_photo and not on):
            self._set_tab(self._left_tabs, self._tab_scene)
        if self._right_tabs.get() not in rvals or (
                self._right_tabs.get() == self._tab_photo and not on):
            self._set_tab(self._right_tabs, self._tab_logs)
        self._left_seg.configure(values=lvals)
        self._right_tab.configure(values=rvals)
        for seg in (self._left_seg, self._right_tab):
            btn = seg._buttons_dict.get(self._tab_photo)
            if btn is not None:
                btn.configure(state="normal" if on else "disabled")
        self._refresh_photo_panels()
        self._sync_emotes_ui()

    def _toggle_right_panel(self):
        self._right_hidden = not self._right_hidden
        self._apply_right_panel_visibility()
        try:
            self.store.save_settings(self._collect_inference_config())
        except Exception:
            pass

    def _apply_right_panel_visibility(self):
        """Свернуть/развернуть панель Logs/Память. Свёрнута: колонка 2
        отдаётся под узкую полоску (weight=0), её место делят чат и левая
        панель. Развёрнута: снова равная треть (weight=1, minsize=COL_MIN)."""
        if self._right_hidden:
            self._right_col.grid_remove()
            self._right_reopen.grid()
            self._body.grid_columnconfigure(2, weight=0, minsize=0)
        else:
            self._right_reopen.grid_remove()
            self._right_col.grid()
            self._body.grid_columnconfigure(2, weight=1, minsize=COL_MIN)
        self._body.update_idletasks()   # чат перерисовывается сразу, без «нудж»
        self._schedule_overlay(60)

    def _toggle_left_panel(self):
        self._left_hidden = not self._left_hidden
        self._apply_left_panel_visibility()
        try:
            self.store.save_settings(self._collect_inference_config())
        except Exception:
            pass

    def _apply_left_panel_visibility(self):
        """Свернуть/развернуть левую панель (вкладки Сцена/Settings), тем же
        приёмом, что и панель Logs справа: свёрнута - колонка 0 под полоску
        (weight=0), место делят соседи; развёрнута - равная треть
        (weight=1, minsize=COL_MIN)."""
        if self._left_hidden:
            self._left_col.grid_remove()
            self._left_reopen.grid()
            self._body.grid_columnconfigure(0, weight=0, minsize=0)
        else:
            self._left_reopen.grid_remove()
            self._left_col.grid()
            self._body.grid_columnconfigure(0, weight=1, minsize=COL_MIN)
        self._body.update_idletasks()
        self._schedule_overlay(60)

    def _refresh_memory_box(self):
        self.memory_box.delete("1.0", "end")
        self.memory_box.insert("1.0", self.chat_digest)

    def _apply_digest_edit(self):
        """Ручная правка окна памяти: весь текст становится долговременной
        памятью (mem_head), недавние сводки-сегменты очищаются."""
        self.mem_head = self.memory_box.get("1.0", "end").strip()
        self.mem_segments = []
        self._render_memory()

    def _edit_digest_prompt(self):
        """Правка system-промпта, которым генерируется память. Дефолт - под
        текущий язык (`DIGEST_SYSTEM` / `DIGEST_SYSTEM_EN`); пустой
        `_digest_prompt` = «использовать дефолт», т.е. промпт памяти
        переключается вместе с языком автоматически."""
        default = digest_system(i18n.get_lang())
        cur = self._digest_prompt.strip() or default
        dlg = TextEditDialog(
            self, t("mem_prompt_dlg_title"), cur, default_text=default,
            help_text=t("mem_prompt_dlg_help"))
        self.wait_window(dlg)
        if dlg.result is None:
            return
        new = dlg.result.strip()
        # пусто или совпадает с любым из встроенных дефолтов -> хранить пусто
        builtins = {DIGEST_SYSTEM.strip(), DIGEST_SYSTEM_EN.strip()}
        self._digest_prompt = "" if (not new or new in builtins) else new
        self.store.save_settings(self._collect_inference_config())

    # ------------------------------------------------- пресеты: селекторы ----
    def _load_block_presets(self, block):
        return getattr(self.store, BLOCK_SPECS[block]["load"])()

    def _seed_defaults(self):
        """Первый запуск: если по блоку нет ни одного пресета - создать
        примеры: русский ("seed") и английский ("seed_en") - язык интерфейса
        можно сменить в любой момент, и пример должен быть на нём."""
        for block, spec in BLOCK_SPECS.items():
            if not self._load_block_presets(block):
                for key in ("seed", "seed_en"):
                    if key in spec:
                        getattr(self.store, spec["upsert"])(spec[key]())

    def _populate_block_menus(self):
        for block in BLOCK_ORDER:
            self._refresh_block_menu(block)

    def _refresh_block_menu(self, block, select=None):
        names = [p.name for p in self._load_block_presets(block) if p.name]
        values = [NONE_CHOICE] + names
        menu, var = self.block_menus[block]
        menu.configure(values=values)
        if select is not None:
            var.set(select if select in values else NONE_CHOICE)
        elif var.get() not in values:
            var.set(NONE_CHOICE)

    @staticmethod
    def _default_preset(block, presets):
        """Пресет по умолчанию: при английском интерфейсе - английский пример
        (если он есть), иначе первый в списке."""
        spec = BLOCK_SPECS[block]
        if i18n.get_lang() == "en" and "seed_en" in spec:
            en_name = spec["seed_en"]().name
            for p in presets:
                if p.name == en_name:
                    return p
        return presets[0]

    def _startup_select(self):
        """Автовыбор первого пресета каждого блока, чтобы приложение было
        рабочим сразу после запуска."""
        for block in BLOCK_ORDER:
            presets = self._load_block_presets(block)
            if presets:
                first = self._default_preset(block, presets)
                self.active[block] = first
                _, var = self.block_menus[block]
                var.set(first.name or NONE_CHOICE)
        chars = self._load_block_presets("character")
        if chars and not self.story_characters:
            self.story_characters = [self._default_preset("character", chars)]
        self._refresh_active_label()

    def _on_select_preset(self, block, choice):
        if choice == NONE_CHOICE:
            self.active[block] = None
        else:
            self.active[block] = next(
                (p for p in self._load_block_presets(block) if p.name == choice), None)
        self._refresh_active_label()

    def _open_manager(self, block):
        existing = self._managers.get(block)
        if existing is not None and existing.winfo_exists():
            existing.lift()
            existing.focus_force()
            return
        self._managers[block] = PresetManager(
            self, self.store, block,
            on_change=lambda b=block: self._after_manager_change(b),
            gen_context=self._preset_gen_context)

    def _preset_gen_context(self):
        """Контекст для кнопки «Сгенерировать» в редакторе пресета: текущая
        модель + опции семплинга из Settings + приёмник лога. Вызывается в
        момент нажатия, поэтому всегда актуально. None -> модель не выбрана."""
        model = self.model_var.get()
        if self._no_model(model):
            return None
        inf = self._collect_inference_config()
        opts = inf.to_options()
        opts.pop("stop", None)              # стоп-строки чата тут только мешают
        opts["num_predict"] = 400           # поле карточки - это несколько фраз
        return {
            "model": model,
            "options": opts or None,
            "keep_alive": inf.keep_alive or None,
            # официальный think=False нельзя слать модели без capability -
            # вернёт 400; там оставляем None (инлайн <think> вырежет клиент).
            "think": False if "thinking" in self._model_caps else None,
            "log": self.log_queue,
            "fmt_log": self._fmt_log_entry,
        }

    def _after_manager_change(self, block):
        """Список пресетов блока изменился (создание/правка/удаление).
        Обновляем меню и, если активный пресет удалён/переименован,
        подстраиваем self.active и выбранное значение."""
        presets = self._load_block_presets(block)
        active = self.active.get(block)
        if active is not None:
            match = next((p for p in presets if p.id == active.id), None)
            self.active[block] = match
            self._refresh_block_menu(
                block, select=match.name if match else NONE_CHOICE)
        else:
            self._refresh_block_menu(block)

        # список персонажей story-режима тоже мог поехать
        if block == "character":
            by_id = {p.id: p for p in presets}
            self.story_characters = [by_id[c.id] for c in self.story_characters
                                     if c.id in by_id]
            self._refresh_story_char_pick()
            self._render_story_characters()

        self._refresh_active_label()

    def _refresh_active_label(self):
        def nm(block):
            obj = self.active.get(block)
            return obj.name if obj and obj.name else NONE_CHOICE
        if self.mode_value == "chat":
            self.active_label.configure(text=t("active_chat"))
            return
        if self.mode_value == "dialogue":
            parts = [f"{t('lbl_you')}: {nm('protagonist')}",
                     f"{t('lbl_character')}: {nm('character')}",
                     f"{t('lbl_location')}: {nm('environment')}",
                     f"{t('lbl_scenario')}: {nm('scenario')}",
                     f"{t('lbl_configuration')}: {nm('system_config')}"]
        else:
            chars = ", ".join(c.name or "?" for c in self.story_characters) or NONE_CHOICE
            parts = [f"{t('lbl_you')}: {nm('protagonist')}",
                     f"{t('lbl_characters')}: {chars}",
                     f"{t('lbl_scenario')}: {nm('scenario')}",
                     f"{t('lbl_configuration')}: {nm('system_config')}"]
        self.active_label.configure(text="   ·   ".join(parts))
        self._refresh_photo_panels()      # выбранный пресет сменился - и фото тоже

    def _active_or_empty(self, block):
        return self.active[block] or BLOCK_SPECS[block]["model"]()

    def _story_size_value(self) -> str:
        """Выбранный «Размер истории» как текст для промпта; NONE_CHOICE -> ""."""
        v = self.story_size_var.get()
        return "" if v == NONE_CHOICE else v

    # ------------------------------------------------------- обработчики ----
    def _update_send_btn_label(self):
        """Текст кнопки отправки: story - «Сгенерировать историю», пока
        ничего не написано, «Продолжить историю» - как только появился хоть
        один ход (см. _on_send/_reset_story_recap); dialogue/chat - «Отправить»."""
        if self.mode_value == "story":
            self.send_btn.configure(
                text=t("continue_story_btn") if self.history else t("generate_story"))
        else:
            self.send_btn.configure(text=t("send"))

    def _reset_story_recap(self):
        """Сбросить пересказ истории (Очистить/Очистить всё/«Сжать пример»
        заменил историю - старый пересказ ей больше не соответствует)."""
        self.story_recap = ""
        self.story_recap_upto = 0

    def _on_mode_change(self, value):
        self.mode_value = value
        self._update_send_btn_label()
        # синхронизировать таб-бар (клик по нему уже выставил вкладку сам)
        label = MODE_LABELS()[value]
        if self._chat_tabs.get() != label:
            self._chat_tabs.set(label)
            self._chat_body.tkraise()
        self._apply_mode_view(value)
        self._apply_input_mode(value)

    def _refresh_models(self):
        try:
            models = list_models()
        except OllamaError as e:
            messagebox.showwarning("Ollama", str(e))
            models = []
        if not models:
            models = [t("no_models")]
        self.model_menu.configure(values=models)
        # На старте self.model_var пуст -> подставляем последнюю запомненную
        # модель (settings.json), если она есть среди установленных, иначе
        # первую из списка. При повторном нажатии «Обновить» уже во время
        # работы приоритет - у ТЕКУЩЕГО выбора (мог смениться после старта),
        # запомненная - запасной вариант.
        cur = self.model_var.get()
        preferred = cur if cur in models else getattr(self, "_last_model", "")
        self.model_var.set(preferred if preferred in models else models[0])
        self._update_model_caps()

    def _append_chat(self, text: str, tag: str = None):
        self.chat_box.configure(state="normal")
        if tag:
            self.chat_box.insert("end", text, tag)
        else:
            self.chat_box.insert("end", text)
        if self._hang:
            self._retag_turn()
        self.chat_box.see("end")
        self.chat_box.configure(state="disabled")

    # --------------------------------------- аватарки рядом с репликами ----
    # Ход с аватаркой = абзац: [аватарка][текст...]. Аватарка - обычный
    # символ-картинка в начале хода (Text.image_create), а поля абзаца
    # (теги hang1/hang) сдвигают весь остальной текст хода на её ширину -
    # верстка чата не меняется: картинка не окно и не колонка, просто
    # символ в строке, переносы слов считает сам Tk. Нет фото / фича выключена
    # -> ничего этого не происходит, чат выглядит как раньше.
    def _photo_for(self, block) -> str:
        """Имя файла фото активного пресета блока ('character'/'protagonist')
        или '' (нет фото / файл пропал / нет Pillow / нет места под аватарку)."""
        if not photos.AVAILABLE or self._avatar_px <= 0:
            return ""
        name = getattr(self.active.get(block), "photo", "") or ""
        return name if name and self.store.photo_path(name) else ""

    def _avatar_image(self, name):
        """Tk-картинка аватарки (круг, с зазором справа) - из кэша."""
        key = (name, self._avatar_px, self._avatar_gap)
        if key not in self._avatar_cache:
            path = self.store.photo_path(name)
            pil = photos.make_avatar(path, self._avatar_px, self._avatar_gap) if path else None
            ph = photos.to_tk(pil, master=self)
            self._avatar_cache[key] = ph
            if ph is not None:
                self._chat_images[str(ph)] = ph      # реестр: имя в Tk -> объект
        return self._avatar_cache[key]

    def _begin_turn(self, name):
        """Начать ход с аватаркой `name` (имя файла из пресета). Пусто/не
        вышло - обычный ход без аватарки."""
        self._end_turn()
        if not name or self._avatar_px <= 0:
            return
        img = self._avatar_image(name)
        if img is None:
            return
        tb = self.chat_box._textbox
        self.chat_box.configure(state="normal")
        tb.mark_set("turn_start", "end-1c")
        tb.mark_gravity("turn_start", "left")      # вставки справа не сдвигают метку
        tb.image_create("end-1c", image=img, align="center")
        self._hang = True
        self._retag_turn()
        self.chat_box.configure(state="disabled")

    def _end_turn(self):
        self._hang = False

    def _dump_chat(self):
        """Содержимое ленты чата как список (вид, значение, позиция): текст,
        включения/выключения тегов и картинки - чтобы при пересборке окна
        (смена языка) вернуть чат ровно таким же, с курсивом и аватарками."""
        try:
            return list(self.chat_box._textbox.dump("1.0", "end-1c", text=True,
                                                    image=True, tag=True))
        except tk.TclError:
            return []

    def _replay_chat(self, dump, fallback_text):
        tb = self.chat_box._textbox
        self.chat_box.configure(state="normal")
        try:
            if not dump:
                tb.insert("1.0", fallback_text)
                return
            active = set()
            for kind, val, _idx in dump:
                if kind == "tagon":
                    active.add(val)
                elif kind == "tagoff":
                    active.discard(val)
                elif kind == "text":
                    tb.insert("end-1c", val, tuple(sorted(active - {"sel"})))
                elif kind == "image":
                    # Tk называет повторные вставки одной картинки
                    # "pyimage3#1", "pyimage3#2"... - отрезаем суффикс
                    img = self._chat_images.get(str(val).split("#")[0])
                    if img is not None:
                        tb.image_create("end-1c", image=img, align="center")
        finally:
            self.chat_box.configure(state="disabled")

    def _retag_turn(self):
        """Выставить поля абзаца на весь ход: первая строка - hang1, остальное
        - hang. Зовётся после каждой вставки текста в ход (дёшево: 2 тега)."""
        tb = self.chat_box._textbox
        try:
            tb.tag_remove("hang1", "turn_start", "end")
            tb.tag_remove("hang", "turn_start", "end")
            first_end = tb.index("turn_start lineend")
            tb.tag_add("hang1", "turn_start", first_end)
            if tb.compare(first_end, "<", "end-1c"):
                tb.tag_add("hang", first_end, "end-1c")
        except tk.TclError:
            self._hang = False

    def _action_piece(self, text: str):
        """(строка, тег) для строки действия в чате: курсивом, либо *…* если
        курсив недоступен. Строка уже с завершающим переводом строки."""
        if self._action_tag:
            return text + "\n", self._action_tag
        return f"*{text}*\n", None

    def _append_log(self, text: str):
        self.logs_box.configure(state="normal")
        self.logs_box.insert("end", text)
        self.logs_box.see("end")
        self.logs_box.configure(state="disabled")

    def _clear_logs(self):
        self.logs_box.configure(state="normal")
        self.logs_box.delete("1.0", "end")
        self.logs_box.configure(state="disabled")

    @staticmethod
    def _fmt_log_entry(title: str, body: str) -> str:
        """Один блок лога: заголовок с меткой времени + тело AS IS."""
        ts = time.strftime("%H:%M:%S")
        return f"\n========== {title}  [{ts}] ==========\n{body}\n"

    def _set_generating(self, flag: bool):
        self.generating = flag
        self.send_btn.configure(state="disabled" if flag else "normal")
        self.clear_btn.configure(state="disabled" if flag else "normal")
        self.export_btn.configure(state="disabled" if flag else "normal")
        self.sessions_btn.configure(state="disabled" if flag else "normal")
        self.stop_btn.configure(state="normal" if flag else "disabled")
        self._mem_rebuild_btn.configure(state="disabled" if flag else "normal")
        self._clear_all_btn.configure(state="disabled" if flag else "normal")
        self._lang_seg.configure(state="disabled" if flag else "normal")
        self.gen_status.configure(text=t("st_wait") if flag else "")

    def _on_stop(self):
        if self.stop_event is not None:
            self.stop_event.set()
        self.stop_btn.configure(state="disabled")

    def _on_clear(self):
        if self.generating or self._rebuilding:
            return
        if self.history and not messagebox.askyesno(
                t("clear_dlg_title"), t("clear_dlg_msg")):
            return
        self.history = []
        self._reset_memory()
        self._reset_story_recap()
        self._update_send_btn_label()
        self.chat_box.configure(state="normal")
        self.chat_box.delete("1.0", "end")
        self.chat_box.configure(state="disabled")
        if self._right_tabs.get() == self._tab_memory:
            self._refresh_memory_box()

    def _on_clear_all(self):
        """Одной кнопкой (верхняя панель): чат + история + бегущая память +
        панель Logs. Пресеты и настройки не трогает."""
        if self.generating or self._rebuilding:
            return
        if not messagebox.askyesno(t("clear_all_title"), t("clear_all_msg")):
            return
        self.history = []
        self._reset_memory()
        self._reset_story_recap()
        self._update_send_btn_label()
        self.chat_box.configure(state="normal")
        self.chat_box.delete("1.0", "end")
        self.chat_box.configure(state="disabled")
        self._clear_logs()
        self._refresh_memory_box()

    # ------------------------------------- динамическая память персонажа ----
    # См. dynamic_memory.py. Короткая схема:
    #   * `self.dyn_new` - новые сводки памяти ДИАЛОГА, ещё не учтённые в
    #     динамической памяти (пополняется в `_fold_segment`);
    #   * авто-обновление - в конце генерации, но НЕ в тот ход, когда только что
    #     собиралась память диалога (`folded`): два скрытых запроса подряд
    #     заставили бы ждать слишком долго - динамическая память обновится
    #     на следующем ходу;
    #   * единственное исключение - сохранение диалога: по согласию
    #     пользователя сначала дособирается память диалога (хвост), сразу за
    #     ней обновляется динамическая (`_dyn_flush_worker`);
    #   * результат записывается в пресет персонажа в ГЛАВНОМ потоке
    #     (маркер `__DYN_MEMORY__`), чтобы не гоняться с правками пресетов.
    def _dyn_char(self, inf=None):
        """Активный собеседник, если динамическая память сейчас работает:
        режим «Диалог», у персонажа включена галка и память диалога не
        выключена (`digest_window` > 0 - на ней всё и держится)."""
        if self.mode_value != "dialogue":
            return None
        ch = self.active.get("character")
        if ch is None or not getattr(ch, "dyn_enabled", False):
            return None
        inf = inf or self._collect_inference_config()
        return ch if (inf.digest_window or 0) > 0 else None

    def _dyn_update(self, model, options, keep_alive, char) -> str:
        """Один скрытый запрос «обнови динамическую память» (из фонового
        потока). -> "changed" / "same" / "fail" / "skip" (нечего обрабатывать).
        Новые события (`dyn_new`) считаются обработанными при "changed" и
        "same"; при "fail" остаются - попробуем в следующий раз."""
        if not self.dyn_new:
            return "skip"
        self.token_queue.put("__DYN_BUILDING__")
        prot = self.active.get("protagonist")
        msgs = dynamic_memory.build_messages(
            char.name, getattr(prot, "name", "") or "", char.dyn_memory,
            list(self.dyn_new), limit=self._dyn_limit, lang=i18n.get_lang())
        text = self._run_hidden(
            model, msgs, self._mem_opts(options, 2000), keep_alive,
            t("log_dyn_request", name=char.name or "?", model=model),
            t("log_dyn_response", name=char.name or "?", model=model))
        status, new = dynamic_memory.interpret_reply(
            text, char.dyn_memory, self._dyn_limit)
        name = char.name or "?"
        if status == "changed":
            char.dyn_memory = new
            self.token_queue.put(("__DYN_MEMORY__", char.id, new))
            self.log_queue.put(self._fmt_log_entry(
                t("log_dyn_updated", name=name, chars=len(new)), new))
        elif status == "same":
            self.log_queue.put(self._fmt_log_entry(t("log_dyn_same", name=name), ""))
        else:
            self.log_queue.put(self._fmt_log_entry(t("log_dyn_failed", name=name), ""))
        if status != "fail":
            self.dyn_new = []
        return status

    def _apply_dyn_memory(self, char_id, text):
        """(главный поток) Записать новую динамическую память: в активные
        объекты (собеседник диалога / персонажи story) и в сохранённый пресет
        - только это поле, чтобы не затереть правки, сделанные в форме."""
        for obj in (self.active.get("character"), *self.story_characters):
            if obj is not None and obj.id == char_id:
                obj.dyn_memory = text
        try:
            stored = next((p for p in self.store.load_characters() if p.id == char_id), None)
            if stored is not None:
                stored.dyn_memory = text
                self.store.upsert_character(stored)
        except Exception as e:
            self.log_queue.put(self._fmt_log_entry("DYNAMIC MEMORY: save error", str(e)))

    def _dyn_flush_needed(self) -> bool:
        """Есть ли что дособрать перед сохранением: необработанные сводки или
        ходы, ещё не свёрнутые в память диалога."""
        if self._dyn_char() is None:
            return False
        return bool(self.dyn_new) or len(self.history) // 2 * 2 > self.digested_upto

    def _dyn_flush_start(self, then):
        """Дособрать память диалога (хвост), затем обновить динамическую -
        ЕДИНСТВЕННОЕ место, где эти два запроса идут подряд. `then(status)`
        зовётся в главном потоке по окончании."""
        model = self.model_var.get()
        inf = self._collect_inference_config()
        N = inf.digest_window or 6
        char = self._dyn_char(inf)
        self._dyn_limit = inf.dyn_limit()
        self._dyn_then = then
        self._rebuilding = True
        for b in (self.send_btn, self.clear_btn, self._clear_all_btn,
                  self._mem_rebuild_btn, self.sessions_btn):
            b.configure(state="disabled")
        self.gen_status.configure(text=t("st_memory"))
        threading.Thread(
            target=self._dyn_flush_worker,
            args=(model, N, inf.to_options(), inf.keep_alive or None,
                  inf.digest_prompt, char),
            daemon=True).start()

    def _dyn_flush_worker(self, model, N, options, keep_alive, digest_prompt, char):
        status = "fail"
        try:
            end = len(self.history) // 2 * 2
            start = self.digested_upto
            if end > start:
                self.digested_upto = end
                step = max(2, N * 2)
                while start < end:
                    e = min(start + step, end)
                    self._fold_segment(model, list(self.history[start:e]), start, e,
                                       options, keep_alive, digest_prompt)
                    start = e
            status = self._dyn_update(model, options, keep_alive, char)
        except Exception as e:
            self.log_queue.put(self._fmt_log_entry(t("log_mem_error", model=model), str(e)))
        self.token_queue.put(("__DYN_FLUSH_DONE__", status))

    # ------------------------------------------ сохранённые диалоги ----
    # Снимок состояния -> sessions.SessionStore (один JSON на сохранение).
    # Что входит: режим, модель, история (self.history), бегущая память
    # (mem_head/mem_segments/digested_upto), пересказ истории, СОДЕРЖИМОЕ
    # чата (текст + курсив + аватарки - аватарка хранится именем файла фото),
    # выбранные пресеты блоков и персонажи story (полные копии - на случай,
    # что пресет потом удалят), размер истории, «Дополнительные детали» и
    # недописанные поля ввода. НЕ входят: Logs (одноразовая телеметрия),
    # Settings (глобальные, не про диалог), эмотиконы/галерея (визуал).
    def _session_default_name(self) -> str:
        if self.mode_value == "story":
            who = ", ".join(c.name for c in self.story_characters if c.name)
        elif self.mode_value == "dialogue":
            o = self.active.get("character")
            who = o.name if (o and o.name) else ""
        else:
            who = ""
        who = who or MODE_LABELS().get(self.mode_value, self.mode_value)
        return t("sess_default_name", who=who, date=time.strftime("%d.%m.%Y %H:%M"))

    def _chat_segments(self) -> list:
        """Лента чата -> список сегментов: {"t": текст, "tags": [...]} и
        {"img": имя файла фото}. Теги: курсив действий, поля абзаца аватарки."""
        # имя картинки в Tk -> имя файла фото (аватарка хранится по имени файла)
        by_tk = {str(ph): key[0] for key, ph in self._avatar_cache.items() if ph is not None}
        segs, active = [], set()
        for kind, val, _idx in self._dump_chat():
            if kind == "tagon":
                active.add(val)
            elif kind == "tagoff":
                active.discard(val)
            elif kind == "text":
                segs.append({"t": val, "tags": sorted(active - {"sel"})})
            elif kind == "image":
                name = by_tk.get(str(val).split("#")[0])
                if name:
                    segs.append({"img": name})
        return segs

    def _load_chat_segments(self, segs):
        tb = self.chat_box._textbox
        self.chat_box.configure(state="normal")
        try:
            tb.delete("1.0", "end")
            for seg in segs if isinstance(segs, list) else []:
                if not isinstance(seg, dict):
                    continue
                if isinstance(seg.get("t"), str):
                    tags = tuple(x for x in seg.get("tags", []) if isinstance(x, str))
                    tb.insert("end-1c", seg["t"], tags)
                elif isinstance(seg.get("img"), str):
                    img = self._avatar_image(seg["img"]) if self._avatar_px > 0 else None
                    if img is not None:           # фото пропало - аватарки просто не будет
                        tb.image_create("end-1c", image=img, align="center")
            tb.see("end")
        finally:
            self.chat_box.configure(state="disabled")

    def _session_snapshot(self) -> dict:
        return {
            "mode": self.mode_value,
            "model": "" if self._no_model(self.model_var.get()) else self.model_var.get(),
            "history": [dict(m) for m in self.history],
            "mem_head": self.mem_head,
            "mem_segments": list(self.mem_segments),
            "digested_upto": self.digested_upto,
            "story_recap": self.story_recap,
            "story_recap_upto": self.story_recap_upto,
            "dyn_new": list(self.dyn_new),
            "chat": self._chat_segments(),
            "scene": {b: (self.active[b].to_dict() if self.active.get(b) else None)
                      for b in BLOCK_ORDER},
            "story_characters": [c.to_dict() for c in self.story_characters],
            "story_size": self._story_size_value(),
            "dialogue_details": self.dialogue_details_box.get("1.0", "end-1c"),
            "story_details": self.story_details_box.get("1.0", "end-1c"),
            "draft": {"act": self.act_box.get("1.0", "end-1c"),
                      "reply": self.reply_box.get("1.0", "end-1c"),
                      "story": self.story_input.get("1.0", "end-1c"),
                      "chat": self.chat_msg_box.get("1.0", "end-1c")},
        }

    def _restore_preset(self, block, d, restored):
        """Пресет блока из снимка: жив в хранилище (по id) - берём ТЕКУЩУЮ
        версию (правки после сохранения не теряются); удалён - возвращаем из
        снимка в хранилище (имя -> `restored`, чтобы сообщить пользователю)."""
        if not isinstance(d, dict):
            return None
        spec = BLOCK_SPECS[block]
        obj = spec["model"].from_dict(d)
        presets = self._load_block_presets(block)
        for p in presets:
            if p.id == obj.id:
                return p
        # хранилище склеивает пресеты по ИМЕНИ (_upsert): возврат удалённого
        # пресета поверх другого с тем же именем затёр бы чужие данные - берём
        # существующий
        for p in presets:
            if obj.name and p.name == obj.name:
                return p
        getattr(self.store, spec["upsert"])(obj)
        restored.append(obj.name or "?")
        return obj

    def _session_apply(self, d: dict) -> dict:
        """Применить снимок. -> {"restored": [имена пресетов], "model_missing":
        имя или ""}. Только в основном потоке, вне генерации. Снимок сначала
        нормализуется (типы полей гарантированы): искажённый файл не должен
        падать на середине и оставлять диалог наполовину загруженным."""
        d = normalize_snapshot(d, dynamic_memory.DYN_NEW_MAX_ITEMS)
        restored = []
        for b in BLOCK_ORDER:
            self.active[b] = self._restore_preset(b, (d.get("scene") or {}).get(b), restored)
        chars = []
        for cd in d.get("story_characters") or []:
            obj = self._restore_preset("character", cd, restored)
            if obj is not None:
                chars.append(obj)
        self.story_characters = chars
        for b in BLOCK_ORDER:                       # меню под загруженные пресеты
            o = self.active.get(b)
            self._refresh_block_menu(b, select=o.name if o and o.name else NONE_CHOICE)
        self._refresh_story_char_pick()
        self._render_story_characters()

        size = d.get("story_size") or ""
        self.story_size_var.set(size if size in STORY_SIZE_CHOICES() else NONE_CHOICE)

        def put(box, text):
            box.delete("1.0", "end")
            if isinstance(text, str) and text:
                box.insert("1.0", text)
        put(self.dialogue_details_box, d.get("dialogue_details"))
        put(self.story_details_box, d.get("story_details"))
        draft = d.get("draft") or {}
        for box, key in ((self.act_box, "act"), (self.reply_box, "reply"),
                         (self.story_input, "story"), (self.chat_msg_box, "chat")):
            put(box, draft.get(key))

        hist = [m for m in d.get("history") or []
                if isinstance(m, dict) and m.get("role") in ("user", "assistant")
                and isinstance(m.get("content"), str)]
        self.history = [{"role": m["role"], "content": m["content"]} for m in hist]
        n = len(self.history)
        self.mem_head = d.get("mem_head") if isinstance(d.get("mem_head"), str) else ""
        self.mem_segments = [s for s in d.get("mem_segments") or [] if isinstance(s, str)]
        self.digested_upto = min(max(int(d.get("digested_upto") or 0), 0), n)
        self.story_recap = d.get("story_recap") if isinstance(d.get("story_recap"), str) else ""
        self.story_recap_upto = min(max(int(d.get("story_recap_upto") or 0), 0), n)
        self.dyn_new = [s for s in d.get("dyn_new") or [] if isinstance(s, str)][
            -dynamic_memory.DYN_NEW_MAX_ITEMS:]
        self._history_backup, self._details_backup = [], ""
        self._just_compressed = False
        self._render_memory()
        self._load_chat_segments(d.get("chat"))
        self._end_turn()
        self._emote_idx = {}

        mode = d.get("mode") if d.get("mode") in self._MODES else "dialogue"
        self._on_mode_change(mode)
        missing = ""
        model = d.get("model") or ""
        if model:
            if model in list(self.model_menu.cget("values")):
                self.model_var.set(model)
                self._update_model_caps()
            else:
                missing = model
        self._refresh_active_label()
        self._sync_side_tabs()
        self._refresh_memory_box()
        return {"restored": restored, "model_missing": missing}

    def _sessions_blocked(self) -> bool:
        if self.generating or self._rebuilding or self._rebuilding_ui:
            messagebox.showinfo(t("sess_title"), t("sess_busy"))
            return True
        return False

    def _open_sessions(self):
        if self._sessions_blocked():
            return
        win = getattr(self, "_sessions_win", None)
        if win is not None and win.winfo_exists():
            win.lift()
            win.focus_force()
            return
        self._sessions_win = SessionsDialog(
            self, self.sessions, self._session_default_name(),
            save_cb=self._session_save, load_cb=self._session_load)

    def _session_save(self, name, session_id) -> bool:
        parent = getattr(self, "_sessions_win", None) or self
        if self._sessions_blocked():
            return False
        if not self.history and not self.chat_box.get("1.0", "end-1c").strip():
            messagebox.showinfo(t("sess_title"), t("sess_nothing"), parent=parent)
            return False
        # Динамическая память включена и есть что дособрать: предлагаем обновить
        # её ПЕРЕД сохранением (иначе последние события не попадут в память
        # персонажа). Это единственное место, где память диалога и динамическая
        # идут двумя запросами подряд.
        if self._dyn_flush_needed():
            char = self._dyn_char()
            ans = messagebox.askyesnocancel(
                t("sess_title"), t("sess_dyn_q", name=char.name or "?"), parent=parent)
            if ans is None:
                return False
            if ans:
                if self._no_model(self.model_var.get()):
                    return self._session_save_now(name, session_id, note=t("sess_dyn_nomodel"))
                self._dyn_flush_start(
                    lambda status, n=name, s=session_id: self._session_save_done(n, s, status))
                return False                    # сохранение завершится асинхронно
        return self._session_save_now(name, session_id)

    def _session_save_done(self, name, session_id, status):
        note = t("sess_dyn_failed") if status == "fail" else None
        if self._session_save_now(name, session_id, note=note):
            win = getattr(self, "_sessions_win", None)
            if win is not None and win.winfo_exists():
                win.render()

    def _session_save_now(self, name, session_id, note=None) -> bool:
        parent = getattr(self, "_sessions_win", None) or self
        try:
            meta = self.sessions.save(self._session_snapshot(), name, session_id)
        except SessionError as e:
            messagebox.showerror(t("sess_title"), t("sess_err", err=e), parent=parent)
            return False
        msg = t("sess_saved", name=meta["name"]) + (f"\n\n{note}" if note else "")
        messagebox.showinfo(t("sess_title"), msg, parent=parent)
        return True

    def _session_load(self, session_id) -> bool:
        parent = getattr(self, "_sessions_win", None) or self
        if self._sessions_blocked():
            return False
        name = next((m["name"] for m in self.sessions.list() if m["id"] == session_id), "")
        try:
            data = self.sessions.load(session_id)
        except SessionError as e:
            messagebox.showerror(t("sess_title"),
                                 t("sess_err_read", name=name or session_id, err=e),
                                 parent=parent)
            return False
        if (self.history or self.chat_box.get("1.0", "end-1c").strip()) and \
                not messagebox.askyesno(t("sess_title"), t("sess_replace_q", name=name),
                                        parent=parent):
            return False
        try:
            info = self._session_apply(data)
        except Exception as e:                    # повреждённое содержимое
            messagebox.showerror(t("sess_title"),
                                 t("sess_err_read", name=name or session_id, err=e),
                                 parent=parent)
            return False
        notes = [t("sess_loaded", name=name)]
        if info["restored"]:
            notes.append(t("sess_restored_presets", names=", ".join(info["restored"])))
        if info["model_missing"]:
            notes.append(t("sess_model_missing", model=info["model_missing"]))
        messagebox.showinfo(t("sess_title"), "\n\n".join(notes), parent=self)
        return True

    # ----------------------------------------------------- экспорт ----
    def _export_plain(self, text, dlg_title, default_name):
        """Сохранить произвольный текст (лог / память) в .txt (UTF-8)."""
        text = (text or "").strip()
        if not text:
            messagebox.showinfo(t("export_menu_title"), t("export_nothing"))
            return
        path = filedialog.asksaveasfilename(
            parent=self, title=dlg_title, defaultextension=".txt",
            initialfile=default_name, filetypes=[(t("ft_txt"), "*.txt")])
        if not path:
            return
        try:
            with open(path, "w", encoding="utf-8") as f:
                f.write(text.rstrip() + "\n")
        except Exception as e:
            messagebox.showerror(t("export_menu_title"), t("export_save_err", err=e))
            return
        messagebox.showinfo(t("export_menu_title"), t("export_saved", path=path))

    def _export_logs(self):
        self._export_plain(
            self.logs_box.get("1.0", "end"), t("export_logs_dlg_title"),
            f"ollama_rp_logs_{time.strftime('%Y-%m-%d_%H%M')}")

    def _export_memory(self):
        self._export_plain(
            self.chat_digest, t("export_memory_dlg_title"),
            f"ollama_rp_memory_{time.strftime('%Y-%m-%d_%H%M')}")

    def _export_conversation(self):
        if self.generating or self._rebuilding:
            return
        if not self.history:
            messagebox.showinfo(t("export_menu_title"), t("export_empty"))
            return
        fname = f"{self.mode_value}_{time.strftime('%Y-%m-%d_%H%M')}"
        path = filedialog.asksaveasfilename(
            parent=self, title=t("export_dlg_title"),
            defaultextension=".txt", initialfile=fname,
            filetypes=[(t("ft_txt"), "*.txt"), (t("ft_docx"), "*.docx")])
        if not path:
            return
        try:
            if path.lower().endswith(".docx"):
                self._write_docx(path)
            else:
                self._write_txt(path)
        except ImportError:
            messagebox.showerror(t("export_menu_title"), t("export_docx_err"))
            return
        except Exception as e:
            messagebox.showerror(t("export_menu_title"), t("export_save_err", err=e))
            return
        messagebox.showinfo(t("export_menu_title"), t("export_saved", path=path))

    def _export_title(self):
        labels = MODE_LABELS()
        return (f"{labels.get(self.mode_value, self.mode_value)} — "
                f"{time.strftime('%Y-%m-%d %H:%M')} — {self.model_var.get()}")

    def _export_scene(self):
        """Компактная шапка сцены из активных пресетов (для dialogue/story)."""
        out = []
        a = self.active
        if self.mode_value == "dialogue":
            for key, lbl in (("protagonist", t("lbl_protagonist")),
                             ("character", t("lbl_character")),
                             ("environment", t("lbl_location")),
                             ("scenario", t("lbl_scenario")),
                             ("system_config", t("lbl_configuration"))):
                o = a.get(key)
                if o and o.name:
                    out.append(f"{lbl}: {o.name}")
        elif self.mode_value == "story":
            o = a.get("protagonist")
            if o and o.name:
                out.append(f"{t('lbl_protagonist')}: {o.name}")
            cs = ", ".join(c.name for c in self.story_characters if c.name)
            if cs:
                out.append(f"{t('lbl_characters')}: {cs}")
            o = a.get("scenario")
            if o and o.name:
                out.append(f"{t('lbl_scenario')}: {o.name}")
            sz = self._story_size_value()
            if sz:
                out.append(f"{t('lbl_size')}: {sz}")
        return out

    def _export_turns(self):
        """Ходы истории -> последовательность (kind, text):
        'action' - действие/чувства (в docx курсивом, в txt в *…*),
        'line'   - строка речи/текста (первая с префиксом «Кто:»),
        'note'   - авторское указание в story, 'gap' - разделитель."""
        o = self.active.get("character")
        char_name = o.name if (o and o.name) else t("lbl_character")
        auto_msgs = {"Напиши историю.", "Продолжай историю.",
                     t("write_story"), t("continue_story")}
        for m in self.history:
            role = m["role"]
            content = (m["content"] or "").strip()
            if not content:
                continue

            if self.mode_value == "story" and role == "user":
                if content in auto_msgs:
                    continue
                yield ("note", content)
                continue

            if self.mode_value == "story":                 # assistant
                for ln in content.split("\n"):
                    ln = ln.strip()
                    if len(ln) > 1 and ln.startswith("*") and ln.endswith("*"):
                        yield ("action", ln[1:-1].strip())
                    elif ln:
                        yield ("line", ln)
                yield ("gap", "")
                continue

            if self.mode_value == "chat":
                who = t("you_prefix") if role == "user" else t("model_prefix")
            else:
                who = t("you_prefix") if role == "user" else char_name
            said = False
            for ln in content.split("\n"):
                ln = ln.strip()
                if not ln:
                    continue
                if len(ln) > 1 and ln.startswith("*") and ln.endswith("*"):
                    yield ("action", ln[1:-1].strip())
                else:
                    yield ("line", f"{who}: {ln}" if not said else ln)
                    said = True
            yield ("gap", "")

    def _write_txt(self, path):
        lines = [self._export_title(), ""]
        scene = self._export_scene()
        if scene:
            lines += scene + [""]
        lines += ["=" * 48, ""]
        for kind, text in self._export_turns():
            if kind == "action":
                lines.append(f"  *{text}*")
            elif kind == "note":
                lines.append(f"[{t('note_prefix')}: {text}]")
            elif kind == "gap":
                lines.append("")
            else:
                lines.append(text)
        with open(path, "w", encoding="utf-8") as f:
            f.write("\n".join(lines).rstrip() + "\n")

    def _write_docx(self, path):
        from docx import Document
        doc = Document()
        doc.add_heading(self._export_title(), level=1)
        scene = self._export_scene()
        if scene:
            for s in scene:
                doc.add_paragraph().add_run(s).italic = True
            doc.add_paragraph()
        for kind, text in self._export_turns():
            if kind == "gap":
                continue
            p = doc.add_paragraph()
            if kind == "action":
                p.add_run(text).italic = True
            elif kind == "note":
                p.add_run(f"[{t('note_prefix')}: {text}]").italic = True
            elif ": " in text:
                who, rest = text.split(": ", 1)
                p.add_run(who + ": ").bold = True
                p.add_run(rest)
            else:
                p.add_run(text)
        doc.save(path)

    def _on_send(self):
        if self.generating or self._rebuilding:
            return
        model = self.model_var.get()
        if self._no_model(model):
            messagebox.showwarning(t("pick_model_title"), t("pick_model_msg"))
            return
        lang = i18n.get_lang()

        inf = self._collect_inference_config()
        think, nudge = self._resolve_reasoning(inf.think)
        structured = bool(inf.structured_dialogue) and self.mode_value == "dialogue"
        if structured:
            nudge = False   # <think>-префикс несовместим с format:json
        # бегущая память - только для диалога
        digest_window = (inf.digest_window or 0) if self.mode_value == "dialogue" else 0

        av_user = av_char = ""     # имена файлов аватарок (только dialogue, см. ниже)

        # --- режим Chat: голый чат без system-промпта; влияют только Settings ---
        if self.mode_value == "chat":
            text = self.chat_msg_box.get("1.0", "end").strip()
            if not text:
                return
            self.history.append({"role": "user", "content": text})
            self.chat_msg_box.delete("1.0", "end")
            self._append_chat(f"\n\n{t('you_prefix')}: {text}\n")
            self.stop_event = threading.Event()
            self._set_generating(True)
            threading.Thread(
                target=self._generate_worker,
                args=(model, list(self.history), self.stop_event, inf.to_options(),
                      think, inf.keep_alive or None, None, False, 0, "\n\n",
                      inf.digest_prompt, inf.stall_seconds(), ""),
                daemon=True).start()
            return

        # --- story: продолжаем существующую историю, а пересказ ещё не
        # свежий (появились новые непересказанные ходы ЗА ВЫЧЕТОМ последних
        # STORY_RECAP_KEEP_RAW_TURNS - те всегда шлются как есть, дословно)
        # - сначала пересобрать пересказ отдельным скрытым запросом (см.
        # STORY_RECAP_* / _story_recap_worker), и уже ПОСЛЕ этого вызвать
        # _on_send() заново для самой генерации. Текст в story_input (если
        # есть) при этом не трогается - переживёт паузу и будет учтён на
        # повторном вызове.
        if self.mode_value == "story" and self.history \
                and self.story_recap_upto < max(
                    0, len(self.history) - STORY_RECAP_KEEP_RAW_TURNS * 2):
            self._start_story_recap(model, inf)
            return

        if self.mode_value == "dialogue":
            action, reply = self._read_input()
            if not action and not reply:
                return
            system_prompt = build_system_prompt(
                character=self._active_or_empty("character"),
                environment=self._active_or_empty("environment"),
                scenario=self._active_or_empty("scenario"),
                mode="dialogue",
                system_config=self._active_or_empty("system_config"),
                protagonist=self._active_or_empty("protagonist"),
                extra_details=self.dialogue_details_box.get("1.0", "end").strip(),
                reasoning_nudge=nudge,
                structured_dialogue=structured,
                lang=lang)
            # реплика в истории - в каноничном виде "*действие*\nречь"
            pending_user = "\n".join(p for p in (
                f"*{action}*" if action else "", reply) if p)

            # фото героя/персонажа рядом с репликами (необязательно и
            # отключаемо в Settings); пустая строка = ход без аватарки
            if inf.show_avatars:
                av_user = self._photo_for("protagonist")
                av_char = self._photo_for("character")

            def _commit():
                self.history.append({"role": "user", "content": pending_user})
                self._clear_input()
                self._append_chat("\n\n")   # два отступа перед своим ходом
                self._begin_turn(av_user)
                self._emote_advance("protagonist")   # новая реплика - следующий эмотикон
                if action:
                    self._append_chat(*self._action_piece(action))
                if reply:
                    if action:
                        self._append_chat("\n")
                    self._append_chat(f"{t('you_prefix')}: {reply}\n")
                self._end_turn()
        else:
            system_prompt = build_system_prompt(
                characters=list(self.story_characters),
                scenario=self._active_or_empty("scenario"),
                mode="story",
                system_config=self._active_or_empty("system_config"),
                protagonist=self._active_or_empty("protagonist"),
                story_size=self._story_size_value(),
                story_details=self.story_details_box.get("1.0", "end").strip(),
                reasoning_nudge=nudge,
                lang=lang)
            note = self.story_input.get("1.0", "end").strip()
            if note:
                pending_user, _marker = note, f"\n[{t('note_prefix')}: {note}]\n"
            elif not self.history:
                pending_user, _marker = t("write_story"), f"\n{t('story_gen_marker')}\n"
            else:
                pending_user, _marker = t("continue_story"), f"\n{t('story_cont_marker')}\n"

            def _commit():
                self._append_chat(_marker)
                self.history.append({"role": "user", "content": pending_user})
                self.story_input.delete("1.0", "end")
                self._update_send_btn_label()

        # --- сборка system-промпта и хвоста истории (одинаково для превью и
        # реального запроса) ---
        def _build_recent(hist):
            sp = system_prompt
            if digest_window > 0:
                if self.chat_digest.strip():
                    sp = (system_prompt + "\n\n" + memory_header(lang) + "\n"
                          + self.chat_digest.strip())
                return sp, hist[self.digested_upto:]
            if self.mode_value == "story" and self.story_recap.strip():
                # пересказ уже собран (или собирается прямо перед этим
                # вызовом, см. проверку выше) - сырым шлём только то, что
                # НЕ покрыто пересказом (обычно - только что закоммиченная
                # реплика pending_user); всё более старое - только пересказом,
                # иначе контекст рос бы с каждым «Продолжить», как раньше
                sp = (system_prompt + "\n\n" + memory_header(lang) + "\n"
                      + self.story_recap.strip())
                return sp, hist[self.story_recap_upto:]
            return sp, list(hist)

        # --- предпроверка контекста ДО фиксации хода (history/chat_box чисты) ---
        sp0, recent0 = _build_recent(self.history)
        preview = ([{"role": "system", "content": sp0}] + recent0
                   + [{"role": "user", "content": pending_user}])
        opts = inf.to_options()
        verdict = self._preflight_context(preview, inf, opts)
        if verdict == "cancel":
            return
        if verdict == "compress":
            self._compress_example(model, inf, preview)
            return
        # verdict is None (влезает / «продолжить как есть») или "increase"
        # (в opts уже подставлен новый num_ctx)

        _commit()
        self._dyn_limit = inf.dyn_limit()      # предел динамической памяти (Settings)
        sp, recent = _build_recent(self.history)
        messages = [{"role": "system", "content": sp}] + recent

        response_format = STRUCTURED_DIALOGUE_SCHEMA if structured else None
        reply_sep = "\n\n" if self.mode_value == "dialogue" else ""

        # Новый Event на каждую генерацию - переиспользовать один нельзя,
        # иначе он останется выставленным и следующая генерация оборвётся сразу.
        self.stop_event = threading.Event()
        self._set_generating(True)
        threading.Thread(
            target=self._generate_worker,
            args=(model, messages, self.stop_event, opts, think,
                  inf.keep_alive or None, response_format, structured,
                  digest_window, reply_sep, inf.digest_prompt,
                  inf.stall_seconds(), av_char, self._dyn_char(inf)),
            daemon=True).start()

    # -------------------------------------- предпроверка контекста ----
    def _preflight_context(self, messages, inf, opts):
        """Прикинуть, влезет ли запрос в num_ctx. Возвращает:
        None - продолжать (влезает / выбрано «как есть»); "increase" -
        num_ctx поднят (уже в `opts`); "compress" - запустить сжатие;
        "cancel" - не отправлять."""
        # только что сжали пример и сами перезапустили генерацию - второй
        # раз «Сжать пример» не предлагаем (защита от зацикливания).
        just = getattr(self, "_just_compressed", False)
        self._just_compressed = False
        ctx = inf.num_ctx
        reserve = inf.num_predict if (inf.num_predict and inf.num_predict > 0) else 2048
        need = estimate_tokens(messages) + reserve
        if ctx is not None and need <= int(ctx * 0.95):
            return None
        if ctx is None and need <= 4000:
            return None                  # маленький запрос - дефолта модели хватит
        suggested = next_num_ctx(need)
        choice = self._ask_context_choice(need, ctx, suggested, allow_compress=not just)
        if choice == "increase":
            _kind, w = self._inf_widgets["num_ctx"]
            w.delete(0, "end")
            w.insert(0, str(suggested))
            opts["num_ctx"] = suggested
            try:
                self.store.save_settings(self._collect_inference_config())
            except Exception:
                pass
            self._append_chat("\n" + t("ctx_increase_note", n=suggested) + "\n")
            return "increase"
        if choice in ("compress", "proceed"):
            return "compress" if choice == "compress" else None
        return "cancel"

    def _ask_context_choice(self, need, ctx, suggested, allow_compress=True):
        """Модальное окно с вариантами + отмена. -> строка/None."""
        win = ctk.CTkToplevel(self)
        win.title(t("ctx_warn_title"))
        win.geometry("560x320")
        win.transient(self)
        res = {"v": None}

        msg = (t("ctx_warn_msg", need=need, ctx=ctx) if ctx is not None
               else t("ctx_warn_msg_unknown", need=need))
        ctk.CTkLabel(win, text=msg, justify="left", anchor="w",
                     wraplength=520).pack(fill="x", padx=PAD_SEC, pady=(PAD_SEC, PAD))
        box = ctk.CTkFrame(win, fg_color="transparent")
        box.pack(fill="x", padx=PAD_SEC, pady=(0, PAD_SEC))

        def pick(v):
            res["v"] = v
            try:
                win.grab_release()
            except tk.TclError:
                pass
            win.destroy()

        ctk.CTkButton(box, text=t("ctx_btn_increase", n=suggested),
                      command=lambda: pick("increase")).pack(fill="x", pady=(0, PAD_TIGHT))
        if allow_compress:
            ctk.CTkButton(box, text=t("ctx_btn_compress"), fg_color="gray30",
                          hover_color="gray40",
                          command=lambda: pick("compress")).pack(fill="x", pady=(0, PAD_TIGHT))
        ctk.CTkButton(box, text=t("ctx_btn_proceed"), fg_color="#8a3a3a",
                      hover_color="#a34a4a",
                      command=lambda: pick("proceed")).pack(fill="x", pady=(0, PAD_TIGHT))
        ctk.CTkButton(box, text=t("cancel"), fg_color="gray25", hover_color="gray35",
                      command=lambda: pick(None)).pack(fill="x")
        win.protocol("WM_DELETE_WINDOW", lambda: pick(None))

        def _grab():
            if win.winfo_exists():
                try:
                    win.grab_set()
                except tk.TclError:
                    pass
                win.lift()
                win.focus_force()
        win.after(80, _grab)
        self.wait_window(win)
        return res["v"]

    # ------------------------------ «Сжать пример» ----
    # Задача НЕ «ужать максимально» (как память), а сжать РОВНО настолько,
    # чтобы результат влез в контекст будущей генерации, сохранив как можно
    # больше конкретики. Целевой объём сводки считается от num_ctx - чем
    # больше контекст, тем подробнее итог (см. _compress_example).
    @staticmethod
    def _size_chunks(msgs, budget=3000):
        """Разбить список сообщений на куски так, чтобы оценка каждого не
        превышала `budget` токенов (одно гигантское сообщение = свой кусок).
        Так запрос сжатия точно влезает в контекст независимо от размера
        примера."""
        chunks, cur, tok = [], [], 0
        for m in msgs:
            mt = estimate_tokens([m])
            if cur and tok + mt > budget:
                chunks.append(cur)
                cur, tok = [], 0
            cur.append(m)
            tok += mt
        if cur:
            chunks.append(cur)
        return chunks

    @staticmethod
    def _text_chunks(text, budget_chars=7000):
        """Свободный текст (вставленный диалог/история/детали) -> куски ≤
        budget по символам. Границы ищем по абзацам, потом по строкам, и
        только совсем длинную строку режем жёстко."""
        # разбить на минимальные единицы: абзацы -> строки -> жёстко
        units = []
        for para in re.split(r"\n\s*\n", text):
            para = para.strip("\n")
            if not para.strip():
                continue
            if len(para) <= budget_chars:
                units.append(para)
                continue
            for ln in para.split("\n"):
                if len(ln) <= budget_chars:
                    units.append(ln)
                else:
                    units += [ln[i:i + budget_chars]
                              for i in range(0, len(ln), budget_chars)]
        chunks, cur = [], ""
        for u in units:
            if cur and len(cur) + len(u) + 1 > budget_chars:
                chunks.append(cur)
                cur = ""
            cur = (cur + "\n" + u) if cur else u
        if cur:
            chunks.append(cur)
        return chunks or [text]

    def _split_oversized_entries(self, entries, budget):
        """Перед `_size_chunks`: если ОДНА запись истории сама по себе
        больше `budget` (обычный случай в story-режиме - один ассистентский
        ход может быть хоть на 120 абзацев), `_size_chunks` кладёт её
        целиком в свой кусок, а не дробит - и такой кусок сам по себе может
        не влезть в контекст скрытого запроса. Режем текст такой записи на
        части (см. `_text_chunks`), каждая становится своей псевдо-записью
        той же роли - тогда `_size_chunks` сможет группировать их как обычно."""
        out = []
        budget_chars = max(500, int(budget * 2.2))   # грубо, с запасом на токенизацию
        for m in entries:
            content = m.get("content") or ""
            if estimate_tokens([m]) <= budget or len(content) <= budget_chars:
                out.append(m)
                continue
            for piece in self._text_chunks(content, budget_chars):
                out.append({"role": m.get("role"), "content": piece})
        return out

    def _example_box(self):
        """Поле «Дополнительные детали» текущего режима (там пользователь
        обычно и держит большой пример)."""
        return (self.story_details_box if self.mode_value == "story"
                else self.dialogue_details_box)

    def _compress_example(self, model, inf, preview):
        """Сжать САМЫЙ КРУПНЫЙ источник примера - `self.history` ИЛИ поле
        «Дополнительные детали» - под ЦЕЛЕВОЙ ОБЪЁМ, вычисленный от `num_ctx`
        (чтобы итог занял почти весь оставшийся контекст = максимум
        деталей), подставить результат на место оригинала и сразу запустить
        генерацию. Оригинал -> backup на сессию.

        `preview` - список сообщений будущего запроса генерации (с примером);
        по нему считаем «оверхед» = всё, кроме примера."""
        if self.generating or self._rebuilding:
            return
        box = self._example_box()
        box_text = box.get("1.0", "end").strip()
        hist_msgs = list(self.history)
        hist_chars = sum(len(m.get("content") or "") for m in hist_msgs)
        if not hist_msgs and not box_text:
            return
        use_box = len(box_text) > hist_chars

        example_tok = max(1, estimate_tokens([{"content": box_text}]) if use_box
                          else estimate_tokens(hist_msgs))
        overhead_tok = max(400, estimate_tokens(preview) - example_tok)
        reply_tok = inf.num_predict if (inf.num_predict and inf.num_predict > 0) else 2048
        eff_ctx = max(int(inf.num_ctx or 0), MEM_MIN_NUM_CTX)

        # сколько токенов итоговая сводка может занять в запросе генерации
        target = int(eff_ctx * 0.85) - overhead_tok - reply_tok
        target = max(1200, min(target, int(example_tok * 0.85)))

        # Раскладка на N запросов. Два ограничения: (1) на один запрос
        # генерируем не больше COMPRESS_CHUNK_OUT_CAP токенов (короткий шаг,
        # виден прогресс, работает «Стоп»); (2) вход куска + его выход
        # должны влезть в eff_ctx.
        usable = int(eff_ctx * 0.88) - 500
        n = max(1, -(-target // COMPRESS_CHUNK_OUT_CAP))
        while n < 40:
            per_out = -(-target // n)
            chunk_in = -(-example_tok // n)
            if chunk_in + per_out + 400 <= usable:
                break
            n += 1
        per_out = max(300, -(-target // n))
        chunk_in = max(1200, -(-example_tok // n))
        words = max(60, int(per_out / 1.6))              # ориентир для промпта

        if use_box:
            chunks = self._text_chunks(box_text, int(chunk_in * 2.5))
            tgt, src_len = "box", len(box_text)
        else:
            pre = ("Пользователь: ", "Ассистент: ")
            chunks = ["\n".join((pre[0] if m["role"] == "user" else pre[1])
                                + (m.get("content") or "") for m in grp)
                      for grp in self._size_chunks(hist_msgs, chunk_in)]
            tgt, src_len = "history", len(hist_msgs)

        self._rebuilding = True
        self.stop_event = threading.Event()
        for b in (self.send_btn, self.clear_btn, self._clear_all_btn,
                  self._mem_rebuild_btn):
            b.configure(state="disabled")
        self.stop_btn.configure(state="normal")
        self._append_chat(t("compress_start_note"))
        self.gen_status.configure(text=t("st_compress", i=0, n=len(chunks)))
        threading.Thread(
            target=self._compress_worker,
            args=(model, chunks, words, per_out, tgt, src_len,
                  inf.to_options(), inf.keep_alive or None, self.stop_event),
            daemon=True).start()

    def _compress_worker(self, model, chunks, words, per_out, target, src_len,
                         options, keep_alive, stop_event):
        total = max(1, len(chunks))
        # запас на возможные <think> reasoning-модели + сам ответ
        opts = {**(options or {}), "temperature": 0.3, "num_predict": per_out + 400}
        opts["num_ctx"] = max(int(opts.get("num_ctx") or 0), MEM_MIN_NUM_CTX)
        opts.pop("stop", None)
        cut = int(per_out * 2.5)                          # запасной подрез, символов
        try:
            parts, good = [], 0
            for i, chunk in enumerate(chunks, 1):
                if stop_event.is_set():
                    break
                self.token_queue.put(("__COMPRESS_PROGRESS__", i, total))
                seen = [0]

                def _tick(nchars, nthink, _i=i, _seen=seen):
                    v = max(nchars, nthink)
                    if v - _seen[0] < 200:            # не спамим очередь
                        return
                    _seen[0] = v
                    self.token_queue.put(("__COMPRESS_TICK__", _i, total,
                                          nchars, nthink))

                text = self._run_hidden(
                    model,
                    build_compress_messages(chunk, words, lang=i18n.get_lang()),
                    opts, keep_alive,
                    t("log_compress_request", model=model, i=i, n=total),
                    t("log_compress_response", model=model, i=i, n=total),
                    stop_event=stop_event, on_tick=_tick)
                if text and text.strip():
                    parts.append(text.strip())
                    good += 1
                elif not stop_event.is_set():             # не сжалось - берём сырой кусок
                    parts.append(chunk[:cut].strip())     #   подрезанным, чтобы не потерять
            summary = "\n\n".join(p for p in parts if p)
            ok = bool(summary.strip()) and (good > 0 or stop_event.is_set())
            self.token_queue.put(("__COMPRESS_DONE__",
                                  summary if ok else None, target, src_len,
                                  stop_event.is_set()))
        except Exception as e:
            self.log_queue.put(self._fmt_log_entry(t("log_mem_error", model=model), str(e)))
            self.token_queue.put(("__COMPRESS_DONE__", None, target, src_len, False))

    # ------------------------------------- «Продолжить историю»: пересказ ----
    def _start_story_recap(self, model, inf):
        """Пересобрать self.story_recap по ходам self.history, ещё не
        учтённым (после self.story_recap_upto) и не входящим в «последние
        STORY_RECAP_KEEP_RAW_TURNS ходов» (те остаются сырыми - см.
        _build_recent в _on_send), отдельным скрытым запросом (может быть
        несколько, если не влезает в контекст - см.
        STORY_RECAP_CHUNK_FRACTION). Только для story; вызывается из
        _on_send ПЕРЕД тем, как строить сам запрос генерации."""
        if self.generating or self._rebuilding:
            return
        start_idx = self.story_recap_upto   # фиксируем ДО фонового потока
        fold_to = max(start_idx, len(self.history) - STORY_RECAP_KEEP_RAW_TURNS * 2)
        new_entries = list(self.history[start_idx:fold_to])
        if not new_entries:
            return
        eff_ctx = max(int(inf.num_ctx or 0), MEM_MIN_NUM_CTX)
        chunk_budget = max(800, int(eff_ctx * STORY_RECAP_CHUNK_FRACTION))
        split_entries = self._split_oversized_entries(new_entries, chunk_budget)
        chunks = self._size_chunks(split_entries, chunk_budget)

        self._rebuilding = True
        self.stop_event = threading.Event()
        for b in (self.send_btn, self.clear_btn, self._clear_all_btn,
                  self._mem_rebuild_btn):
            b.configure(state="disabled")
        self.stop_btn.configure(state="normal")
        self.gen_status.configure(text=t("st_story_recap", i=0, n=len(chunks)))
        threading.Thread(
            target=self._story_recap_worker,
            args=(model, chunks, start_idx, self.story_recap, inf.to_options(),
                  inf.keep_alive or None, self.stop_event),
            daemon=True).start()

    def _story_recap_worker(self, model, chunks, start_idx, known, options,
                            keep_alive, stop_event):
        """Фоновый поток: последовательно сворачивает `chunks` (группы ходов
        self.history) в краткий пересказ, начиная с уже известного `known`
        (та же механика, что у бегущей памяти диалога -
        build_segment_summary_messages: каждый шаг получает уже собранное
        как «не повторяй» и досказывает только новое). Если пересказ
        разросся - под конец ужимает его самого одним запросом
        (build_consolidation_messages). `upto` двигаем ТОЛЬКО на реально
        обработанные ходы - если прервали «Стоп» на середине, необработанный
        хвост остаётся для следующего раза, а не теряется молча."""
        total = max(1, len(chunks))
        opts = self._mem_opts(options, 500)
        lang = i18n.get_lang()
        recap = known
        done_entries = 0
        try:
            for i, chunk in enumerate(chunks, 1):
                if stop_event.is_set():
                    break
                self.token_queue.put(("__STORY_RECAP_PROGRESS__", i, total))
                text = self._run_hidden(
                    model, build_segment_summary_messages(recap, chunk, lang=lang),
                    opts, keep_alive,
                    t("log_story_recap_request", model=model, i=i, n=total),
                    t("log_story_recap_response", model=model, i=i, n=total),
                    stop_event=stop_event)
                increment = (text or "").strip()
                if increment:
                    recap = (recap + "\n\n" + increment) if recap else increment
                elif not stop_event.is_set():
                    # не получилось сжать - берём сырой кусок урезанным,
                    # чтобы хотя бы не потерять события совсем (как в
                    # "Сжать пример")
                    pre = ("Пользователь: ", "Ассистент: ")
                    raw = "\n".join(
                        (pre[0] if m.get("role") == "user" else pre[1])
                        + (m.get("content") or "") for m in chunk)
                    raw = raw[:1500].strip()
                    if raw:
                        recap = (recap + "\n\n" + raw) if recap else raw
                done_entries += len(chunk)

            # пересказ разросся (много «Продолжить» подряд) - ужимаем его
            # самого ОДНИМ финальным запросом, чтобы не расти без предела
            if not stop_event.is_set() and recap and estimate_tokens(
                    [{"content": recap}]) > STORY_RECAP_CONSOLIDATE_TOKENS:
                self.token_queue.put(("__STORY_RECAP_PROGRESS__", total, total))
                c_text = self._run_hidden(
                    model, build_consolidation_messages("", [recap], lang=lang),
                    self._mem_opts(options, 900), keep_alive,
                    t("log_story_recap_consolidate_request", model=model),
                    t("log_story_recap_consolidate_response", model=model),
                    stop_event=stop_event)
                if c_text and c_text.strip():
                    recap = c_text.strip()

            self.token_queue.put(("__STORY_RECAP_DONE__", recap,
                                  start_idx + done_entries, stop_event.is_set()))
        except Exception as e:
            self.log_queue.put(self._fmt_log_entry(t("log_mem_error", model=model), str(e)))
            self.token_queue.put(("__STORY_RECAP_DONE__", None, start_idx, False))

    def _is_dup_speech(self, speech: str) -> bool:
        """Речевая часть почти совпадает с одной из последних реплик персонажа
        в `self.history` (самой этой реплики там ещё нет). Логика - в
        prompt_builder.is_duplicate_speech (её же покрывают тесты)."""
        return is_duplicate_speech(speech, self.history, window=DUP_WINDOW,
                                   ratio=DUP_RATIO, min_len=DUP_MIN_LEN)

    def _generate_worker(self, model, messages, stop_event, options, think,
                         keep_alive, response_format=None, structured=False,
                         digest_window=0, reply_sep="", digest_prompt="",
                         stall_timeout=0, avatar_file="", dyn_char=None):
        orig_messages = list(messages)    # неизменный исходный запрос
        base_messages = orig_messages     # что уйдёт СЛЕДУЮЩЕЙ попыткой
        base_options = options            # для пересборки памяти - без anti-dup правок
        full_reply = ""
        had_error = False
        attempt = 0
        stall_retries = 0     # сколько раз уже перезапрашивали из-за тишины модели
        sep_pushed = False    # reply_sep в чат отдаём один раз за весь вызов
        story_prefix = ""   # чистый текст, уже принятый из попыток, оборванных
                             # из-за зацикливания (не-structured режим)

        def on_request(payload):
            # payload - ровно тот словарь, что уходит в requests.post(json=...).
            self.log_queue.put(self._fmt_log_entry(
                t("log_request", model=model),
                json.dumps(payload, ensure_ascii=False, indent=2)))

        # --- цикл с авто-перегенерацией: повтор реплики (structured) или
        # зацикливание текста на паре абзацев (обычный стрим - диалог без
        # разбивки, история, чат) ---
        while True:
            buffer = []
            think_buffer = []
            loop_kept = None      # find_repeat_loop() поймал цикл - что сохранить
            stalled = False       # модель замолчала дольше stall_timeout

            def on_thinking(text, _tb=think_buffer):
                if not _tb:
                    self.token_queue.put("__THINKING__")
                _tb.append(text)

            msgs = base_messages
            try:
                for chunk in chat_stream(model, msgs, options=options, think=think,
                                         keep_alive=keep_alive, stop_event=stop_event,
                                         on_request=on_request, on_thinking=on_thinking,
                                         response_format=response_format,
                                         strip_inline_think=not structured,
                                         stall_timeout=stall_timeout):
                    if not buffer:
                        self.token_queue.put("__ANSWERING__")
                        if not structured and reply_sep and not sep_pushed:
                            self.token_queue.put(reply_sep)
                            if reply_sep:     # диалог: аватарка + смена эмотикона
                                self.token_queue.put(("__TURN__", avatar_file))
                            sep_pushed = True
                    buffer.append(chunk)
                    if not structured:
                        self.token_queue.put(chunk)   # structured копит и парсит в конце
                        if "\n" in chunk:
                            loop_kept = find_repeat_loop(
                                "".join(buffer), tail_check=LOOP_TAIL_CHECK,
                                window=LOOP_WINDOW, ratio=LOOP_RATIO,
                                min_block_len=LOOP_MIN_BLOCK_LEN,
                                min_hits=LOOP_MIN_HITS)
                            if loop_kept is not None:
                                break   # закрываем стрим прямо на месте цикла
            except OllamaStallError:
                stalled = True    # не ошибка: обработаем ниже (перезапрос)
            except OllamaError as e:
                self.token_queue.put(f"\n{t('err_inline', err=e)}\n")
                self.log_queue.put(self._fmt_log_entry(t("log_error", model=model), str(e)))
                had_error = True

            if think_buffer:
                self.log_queue.put(self._fmt_log_entry(
                    t("log_thinking", model=model), "".join(think_buffer)))
            full_reply = "".join(buffer)

            # --- модель замолчала посреди ответа (чаще всего на этапе
            # «размышляет»): обрываем и шлём тот же запрос заново, если
            # пользователь сам не нажал «Стоп». Текст, успевший попасть в чат
            # до зависания, откатываем (__TRIM__ - ровно len(full_reply)
            # символов, как при зацикливании); новый seed - чтобы
            # фиксированный seed не завёл в то же самое зависание.
            if stalled and not stop_event.is_set():
                if stall_retries < STALL_MAX_RETRIES:
                    stall_retries += 1
                    if full_reply and not structured:
                        self.token_queue.put(("__TRIM__", len(full_reply)))
                    self.token_queue.put(
                        ("__RETRY_STALL__", stall_retries, STALL_MAX_RETRIES,
                         stall_timeout))
                    self.log_queue.put(self._fmt_log_entry(
                        t("log_retry_stall", s=stall_timeout,
                          i=stall_retries, n=STALL_MAX_RETRIES),
                        full_reply or t("empty_reply")))
                    options = {**options, "seed": random.randint(1, 2**31 - 1)}
                    continue
                msg = t("stall_gaveup_err", n=STALL_MAX_RETRIES, s=stall_timeout)
                self.token_queue.put(f"\n{t('err_inline', err=msg)}\n")
                self.log_queue.put(self._fmt_log_entry(
                    t("log_retry_stall_gaveup", n=STALL_MAX_RETRIES), msg))
                had_error = True

            # Финальная подстраховка: если генерация закончилась САМА (EOS),
            # инкрементальная проверка внутри цикла могла пропустить именно
            # ХВОСТ - она срабатывает только когда в очередном чанке есть
            # "\n", а последний чанк ответа модели обычно приходит БЕЗ
            # завершающего перевода строки. Раз уж поток и так уже
            # закончился, проверяем весь текст целиком ещё раз - без этого
            # повтор в самом последнем абзаце вообще никогда не ловился.
            if not structured and not had_error and not stop_event.is_set() \
                    and loop_kept is None and full_reply:
                loop_kept = find_repeat_loop(
                    full_reply, tail_check=LOOP_TAIL_CHECK, window=LOOP_WINDOW,
                    ratio=LOOP_RATIO, min_block_len=LOOP_MIN_BLOCK_LEN,
                    min_hits=LOOP_MIN_HITS)

            if had_error or stop_event.is_set():
                break

            if structured:
                _a, _sp = parse_structured_reply(full_reply)
                if _sp and attempt < DUP_MAX_RETRIES and self._is_dup_speech(_sp):
                    attempt += 1
                    self.token_queue.put(("__RETRY_DUP__", attempt, DUP_MAX_RETRIES))
                    self.log_queue.put(self._fmt_log_entry(
                        t("log_retry_dup", i=attempt, n=DUP_MAX_RETRIES), _sp))
                    options = {**options,
                               "repeat_last_n": max(int(options.get("repeat_last_n") or 0), 512),
                               "temperature": min(1.2, float(options.get("temperature") or 0.7) + 0.15),
                               "seed": random.randint(1, 2**31 - 1)}
                    base_messages = orig_messages + [
                        {"role": "user", "content": t("retry_dup_nudge")}]
                    continue
                if _sp and attempt >= DUP_MAX_RETRIES and self._is_dup_speech(_sp):
                    self.log_queue.put(self._fmt_log_entry(
                        t("log_retry_dup_gaveup"), _sp))
                break

            # --- не-structured: реакция на пойманное зацикливание ---
            if loop_kept is not None and attempt < LOOP_MAX_RETRIES:
                # визуально откатываем ТОЛЬКО то, что показала эта попытка
                # (ровно len(full_reply) символов - именно столько сырых
                # чанков этой попытки ушло в chat_box), вставляем взамен
                # чистый кусок без повтора и пробуем продолжить с него.
                self.token_queue.put(("__TRIM__", len(full_reply)))
                if loop_kept:
                    self.token_queue.put(loop_kept + "\n\n")
                story_prefix = (story_prefix + "\n\n" + loop_kept) if story_prefix \
                    else loop_kept
                attempt += 1
                self.token_queue.put(("__RETRY_LOOP__", attempt, LOOP_MAX_RETRIES))
                self.log_queue.put(self._fmt_log_entry(
                    t("log_retry_loop", i=attempt, n=LOOP_MAX_RETRIES), full_reply))
                options = {**options,
                           "repeat_last_n": max(int(options.get("repeat_last_n") or 0), 512),
                           "temperature": min(1.2, float(options.get("temperature") or 0.7) + 0.15),
                           "seed": random.randint(1, 2**31 - 1)}
                base_messages = orig_messages + [
                    {"role": "assistant", "content": story_prefix},
                    {"role": "user", "content": t("retry_loop_nudge")}]
                continue

            if loop_kept is not None:
                # лимит перегенераций исчерпан, а генерация всё ещё
                # зацикливается - не сохраняем повтор в историю/чат вообще,
                # обрезаем по последнему чистому месту и сдаёмся (только
                # в Logs - в тексте истории/диалога это ничем не отмечаем).
                self.token_queue.put(("__TRIM__", len(full_reply)))
                self.log_queue.put(self._fmt_log_entry(
                    t("log_retry_loop_gaveup"), full_reply))
                full_reply = loop_kept
                if full_reply:
                    self.token_queue.put(full_reply + "\n")
            if story_prefix:
                full_reply = story_prefix + ("\n\n" + full_reply if full_reply else "")
            break

        # --- финализация ---
        stopped = stop_event.is_set()

        got_reply = False
        if structured:
            action, speech = parse_structured_reply(full_reply)
            canon = "\n".join(p for p in (
                f"*{action}*" if action else "", speech) if p)
            if canon:
                self.history.append({"role": "assistant", "content": canon})
                got_reply = True
            self.token_queue.put(reply_sep or "\n\n")   # два отступа перед ходом персонажа
            if reply_sep and (action or speech or full_reply.strip()):
                self.token_queue.put(("__TURN__", avatar_file))   # аватарка + эмотикон
            if action:
                self.token_queue.put(self._action_piece(action))
            if speech:
                if action:
                    self.token_queue.put("\n")           # отступ между действием и речью
                self.token_queue.put((speech + "\n", None))
            if not action and not speech and full_reply.strip():
                self.token_queue.put((full_reply.strip() + "\n", None))
        else:
            # частичный/полный текст уходит в историю обычной репликой
            if full_reply:
                self.history.append({"role": "assistant", "content": full_reply})
                got_reply = True

        # Если лимит перегенераций (повтор реплики / зацикливание) был
        # исчерпан - об этом уже залогировано в Logs в момент обнаружения
        # (см. выше, КАПСОМ в заголовке). В текст диалога/истории умышленно
        # НЕ пишем: заметное сообщение прямо в реплике ломает иммерсивность.

        # Генерация ничего не дала (ошибка / «Стоп» до первого токена):
        # убираем висячую реплику user, иначе следующий ход даст два
        # user подряд и chat-шаблон модели упадёт (роли должны чередоваться).
        if not got_reply and self.history and self.history[-1]["role"] == "user":
            self.history.pop()

        self.log_queue.put(self._fmt_log_entry(
            t("log_response", model=model) + (t("stopped_suffix") if stopped else ""),
            full_reply if full_reply else t("empty_reply")))

        # Пересобрать память, ЕСЛИ перешли новый N-ходовой рубеж (не
        # каждый ход). Блокируем UI ещё чуть-чуть - это отдельный
        # короткий запрос к той же модели.
        folded = False
        if got_reply and digest_window > 0:
            folded = self._maybe_update_digest(model, base_options, keep_alive,
                                               digest_window, digest_prompt)
        # Динамическая память персонажа: НЕ в тот же ход, когда только что
        # собиралась память диалога (два скрытых запроса подряд - слишком
        # долгое ожидание); обновится на следующем ходу.
        if (got_reply and not stopped and not folded and dyn_char is not None
                and self.dyn_new):
            self._dyn_update(model, base_options, keep_alive, dyn_char)

        if stopped:
            self.token_queue.put(f"\n{t('stopped_by_user')}\n")
        self.token_queue.put("__DONE__")

    # ------------------------------------------------ бегущая память ----
    # Послойная схема (см. константы MEM_* и prompt_builder):
    #   * каждый N-ходовой сегмент сжимается РОВНО ОДИН раз (_fold_segment)
    #     -> добавляется в self.mem_segments; повторно не пересобирается;
    #   * когда недавних сводок > MEM_SEGMENTS_KEEP, самые старые вливаются
    #     в self.mem_head отдельным запросом (уплотнение);
    #   * вход КАЖДОГО скрытого запроса ограничен (голова + пара коротких
    #     блоков / N ходов) и от длины диалога не зависит -> сборщик не
    #     ломается на многочасовых сессиях;
    #   * self.digested_upto двигается ВСЕГДА (даже при сбое запроса), иначе
    #     хвост для следующего рубежа рос бы и запрос переставал влезать.
    def _reset_memory(self):
        """Полный сброс бегущей памяти (кнопки «Очистить» / «Очистить всё»)."""
        self.mem_head = ""
        self.mem_segments = []
        self.digested_upto = 0
        self.dyn_new = []
        self._render_memory()

    def _render_memory(self) -> str:
        """mem_head + сегменты -> строка self.chat_digest (её показывает окно
        памяти и подставляет в промпт _on_send). Держится в синхроне."""
        parts = []
        if self.mem_head.strip():
            parts.append(self.mem_head.strip())
        parts.extend(s.strip() for s in self.mem_segments if s and s.strip())
        self.chat_digest = "\n\n".join(parts)
        return self.chat_digest

    def _mem_opts(self, options, num_predict):
        o = {**(options or {}), "temperature": 0.2, "num_predict": num_predict}
        o["num_ctx"] = max(int(o.get("num_ctx") or 0), MEM_MIN_NUM_CTX)
        o.pop("stop", None)               # стоп-строки чата памяти только мешают
        return o

    def _run_hidden(self, model, msgs, options, keep_alive, req_title, resp_title,
                    stop_event=None, on_tick=None):
        """Один скрытый запрос к модели (память / сжатие). -> текст (str, м.б.
        пустой) либо None при сетевой ошибке. Из фонового потока. <think>
        гасится. `on_tick(nchars, thinking)` - пинги прогресса по мере
        стрима (для счётчика). `stop_event` - прервать по «Стоп»."""
        think = False if "thinking" in self._model_caps else None
        self.log_queue.put(self._fmt_log_entry(
            req_title,
            json.dumps({"model": model, "messages": msgs, "options": options,
                        "think": think}, ensure_ascii=False, indent=2)))
        parts = []
        thinking = [0]

        def _on_think(txt):
            thinking[0] += len(txt or "")
            if on_tick:
                on_tick(0, thinking[0])

        try:
            for ch in chat_stream(model, msgs, options=options, think=think,
                                  keep_alive=keep_alive, stop_event=stop_event,
                                  on_thinking=_on_think):
                parts.append(ch)
                if on_tick:
                    on_tick(sum(len(p) for p in parts), thinking[0])
        except OllamaError as e:
            self.log_queue.put(self._fmt_log_entry(t("log_mem_error", model=model), str(e)))
            return None
        result = "".join(parts).strip()
        self.log_queue.put(self._fmt_log_entry(resp_title, result or t("log_empty")))
        return result

    def _fold_segment(self, model, seg, a, b, options, keep_alive, digest_prompt,
                      quiet=False, dyn=True):
        """Сжать ОДИН сегмент истории (`seg` = history[a:b]) в сводку, добавить
        в mem_segments; затем при переполнении - влить старые сводки в
        mem_head. Из фонового потока. `quiet=True` - не слать маркеры статуса
        памяти (используется при «Сжать пример», у него свой счётчик)."""
        if not quiet:
            self.token_queue.put("__MEMORY_BUILDING__")
        ta, tb = a // 2 + 1, b // 2
        msgs = build_segment_summary_messages(
            self._render_memory(), seg, system_prompt=digest_prompt,
            lang=i18n.get_lang())
        text = self._run_hidden(
            model, msgs, self._mem_opts(options, 500), keep_alive,
            t("log_mem_seg_request", model=model, a=ta, b=tb),
            t("log_mem_seg_response", model=model, a=ta, b=tb))
        got = bool((text or "").strip())
        summary = (text or "").strip() or t("mem_segment_stub", a=ta, b=tb)
        self.mem_segments.append(summary)
        if got and dyn:
            # новая сводка ждёт обработки в динамической памяти персонажа
            self.dyn_new.append(summary)
            del self.dyn_new[:-dynamic_memory.DYN_NEW_MAX_ITEMS]

        while len(self.mem_segments) > MEM_SEGMENTS_KEEP:
            overflow = self.mem_segments[0]
            c_text = self._run_hidden(
                model,
                build_consolidation_messages(self.mem_head, [overflow],
                                             lang=i18n.get_lang()),
                self._mem_opts(options, 900), keep_alive,
                t("log_mem_consolidate_request", model=model),
                t("log_mem_consolidate_response", model=model))
            if c_text and c_text.strip():
                self.mem_head = c_text.strip()
                self.mem_segments.pop(0)
            elif len(self.mem_segments) > MEM_SEGMENTS_MAX:
                # уплотнение стабильно не даётся - грубо приклеиваем, лишь бы
                # память не росла без предела (следующее удачное уплотнение сожмёт)
                self.mem_head = (self.mem_head + "\n\n" + overflow).strip()
                self.mem_segments.pop(0)
            else:
                break                     # попробуем на следующем рубеже

        self._render_memory()
        if not quiet:
            self.token_queue.put("__MEMORY__")
        return got

    def _maybe_update_digest(self, model, options, keep_alive, N, digest_prompt):
        """-> True, если собирали память диалога (хоть один запрос ушёл)."""
        boundary = digest_boundary(len(self.history), N)
        if boundary <= self.digested_upto:
            return False
        step = max(2, N * 2)
        start, self.digested_upto = self.digested_upto, boundary
        while start < boundary:
            end = min(start + step, boundary)
            self._fold_segment(model, list(self.history[start:end]), start, end,
                               options, keep_alive, digest_prompt)
            start = end
        return True

    def _rebuild_digest(self):
        if self.generating or self._rebuilding:
            return
        model = self.model_var.get()
        if self._no_model(model):
            messagebox.showwarning(t("memory_title"), t("pick_model_msg"))
            return
        inf = self._collect_inference_config()
        K = inf.digest_window or 0
        N = K if K > 0 else 6
        n = len(self.history)
        fold_to = (n - 2 * K) if K > 0 else n
        fold_to -= fold_to % 2
        if fold_to <= 0:
            messagebox.showinfo(t("memory_title"), t("mem_nothing"))
            return
        self._rebuilding = True
        self._mem_rebuild_btn.configure(state="disabled")
        self.gen_status.configure(text=t("st_memory"))
        threading.Thread(
            target=self._rebuild_digest_worker,
            args=(model, fold_to, N, inf.to_options(),
                  inf.keep_alive or None, inf.digest_prompt),
            daemon=True).start()

    def _rebuild_digest_worker(self, model, fold_to, N, options, keep_alive,
                               digest_prompt=""):
        """Пересобрать память с нуля: пройти history[:fold_to] тем же послойным
        механизмом сегментами по N ходов. Вход каждого запроса ограничен,
        поэтому глубина истории пересборку не ломает."""
        prev_head, prev_segs = self.mem_head, list(self.mem_segments)
        self.mem_head, self.mem_segments = "", []
        step = max(2, N * 2)
        total = max(1, (fold_to + step - 1) // step)
        try:
            done, start = 0, 0
            while start < fold_to:
                end = min(start + step, fold_to)
                done += 1
                self.token_queue.put(("__MEMORY_PROGRESS__", done, total))
                self._fold_segment(model, list(self.history[start:end]), start, end,
                                   options, keep_alive, digest_prompt, dyn=False)
                start = end
            self.token_queue.put(("__DIGEST_REBUILT__", True, fold_to))
        except Exception as e:
            self.mem_head, self.mem_segments = prev_head, prev_segs
            self._render_memory()
            self.log_queue.put(self._fmt_log_entry(
                t("log_mem_error", model=model), str(e)))
            self.token_queue.put(("__DIGEST_REBUILT__", False, self.digested_upto))

    def _poll_queue(self):
        """Тик опроса очередей (каждые 50 мс). Исключение при обработке одного
        элемента НЕ должно останавливать опрос: иначе интерфейс навсегда
        «замирал» бы (статус генерации не снимается, ответы не выводятся).
        Ошибка пишется в Logs, элемент считается обработанным, опрос продолжается."""
        try:
            if not getattr(self, "_rebuilding_ui", False):
                self._poll_queue_once()
        except Exception:
            try:
                self._append_log(self._fmt_log_entry("INTERNAL ERROR", traceback.format_exc()))
            except Exception:
                pass
        finally:
            try:
                self.after(50, self._poll_queue)
            except tk.TclError:
                pass                               # окно уже закрыто

    def _poll_queue_once(self):
        # Подряд идущие куски обычного текста (токены стрима) склеиваем в ОДНУ
        # вставку + один see("end") за тик: Tk-Text на длинном абзаце считает
        # перенос строк заново при каждой вставке, и вставка по токену
        # заметно тормозила интерфейс.
        pending = []

        def flush():
            if pending:
                text = "".join(pending)
                pending.clear()
                self._append_chat(text)
        try:
            while True:
                item = self.token_queue.get_nowait()
                if isinstance(item, str) and not (item.startswith("__") and item.endswith("__")):
                    pending.append(item)
                    continue
                flush()
                if item == "__DONE__":
                    self._set_generating(False)
                    self._append_chat("\n")
                    self._end_turn()                 # ход с аватаркой закончен
                elif item == "__THINKING__":
                    self.gen_status.configure(text=t("st_think"))
                elif item == "__ANSWERING__":
                    self.gen_status.configure(text=t("st_answer"))
                elif item == "__MEMORY_BUILDING__":
                    self.gen_status.configure(text=t("st_memory"))
                elif item == "__MEMORY__":
                    if self._right_tabs.get() == self._tab_memory:
                        self._refresh_memory_box()
                elif isinstance(item, tuple) and item and item[0] == "__MEMORY_PROGRESS__":
                    _, i, n = item
                    self.gen_status.configure(text=t("st_memory_progress", i=i, n=n))
                elif isinstance(item, tuple) and item and item[0] == "__COMPRESS_PROGRESS__":
                    _, i, n = item
                    self.gen_status.configure(text=t("st_compress", i=i, n=n))
                elif isinstance(item, tuple) and item and item[0] == "__COMPRESS_TICK__":
                    _, i, n, nchars, nthink = item
                    if nchars:
                        key = "st_compress_out"
                        val = max(1, nchars // 6)      # ~символов на слово
                    else:
                        key = "st_compress_think"
                        val = max(1, nthink // 6)
                    self.gen_status.configure(text=t(key, i=i, n=n, w=val))
                elif isinstance(item, tuple) and item and item[0] == "__COMPRESS_DONE__":
                    _, summary, target, src_len, stopped = item
                    self._rebuilding = False
                    for b in (self.send_btn, self.clear_btn, self._clear_all_btn,
                              self._mem_rebuild_btn):
                        b.configure(state="normal")
                    self.stop_btn.configure(state="disabled")
                    self.gen_status.configure(text="")
                    if summary and target == "box":
                        box = self._example_box()
                        self._details_backup = box.get("1.0", "end")
                        box.delete("1.0", "end")
                        box.insert("1.0", summary)
                        self._append_chat(t("compress_stopped_note") if stopped
                                          else t("compress_ok_note_box", chars=src_len))
                        self._just_compressed = True
                        self.after(60, self._on_send)
                    elif summary:
                        self._history_backup = list(self.history)
                        self.history = [{"role": "user",
                                         "content": t("compressed_history_intro")
                                         + "\n\n" + summary}]
                        self._reset_memory()
                        # «Сжать пример» заменил всю историю целиком - старый
                        # пересказ story-режима ей больше не соответствует
                        # (индексы/содержимое не те); соберётся заново по
                        # новой, уже сжатой истории при следующем «Продолжить».
                        self._reset_story_recap()
                        self._update_send_btn_label()
                        self._append_chat(t("compress_stopped_note") if stopped
                                          else t("compress_ok_note", msgs=src_len))
                        if self._right_tabs.get() == self._tab_memory:
                            self._refresh_memory_box()
                        self._just_compressed = True
                        self.after(60, self._on_send)
                    elif stopped:
                        self._append_chat(t("compress_cancelled_note"))
                    else:
                        self._append_chat(t("compress_fail_note"))
                        messagebox.showwarning(t("compress_fail_title"),
                                               t("compress_fail_note").strip())
                elif isinstance(item, tuple) and item and item[0] == "__STORY_RECAP_PROGRESS__":
                    _, i, n = item
                    self.gen_status.configure(text=t("st_story_recap", i=i, n=n))
                elif isinstance(item, tuple) and item and item[0] == "__STORY_RECAP_DONE__":
                    _, recap, upto, stopped = item
                    self._rebuilding = False
                    for b in (self.send_btn, self.clear_btn, self._clear_all_btn,
                              self._mem_rebuild_btn):
                        b.configure(state="normal")
                    self.stop_btn.configure(state="disabled")
                    self.gen_status.configure(text="")
                    if recap is None:
                        self._append_chat(t("story_recap_fail_note"))
                        messagebox.showwarning(t("story_recap_fail_title"),
                                               t("story_recap_fail_note").strip())
                    elif not recap.strip() and stopped:
                        # остановили ДО того, как хоть что-то пересказалось -
                        # реально отменили, ничего не продвигаем и не шлём
                        self._append_chat(t("story_recap_cancelled_note"))
                    else:
                        self.story_recap = recap
                        self.story_recap_upto = upto
                        self._update_send_btn_label()
                        if stopped:
                            # частично пересказали и остановились - именно
                            # остановились: НЕ продолжаем автоматически в
                            # генерацию, иначе «Стоп» ничего бы не стопал
                            self._append_chat(t("story_recap_stopped_note"))
                        else:
                            self.after(60, self._on_send)
                elif item == "__DYN_BUILDING__":
                    self.gen_status.configure(text=t("st_dyn_memory"))
                elif isinstance(item, tuple) and item and item[0] == "__DYN_MEMORY__":
                    self._apply_dyn_memory(item[1], item[2])
                elif isinstance(item, tuple) and item and item[0] == "__DYN_FLUSH_DONE__":
                    self._rebuilding = False
                    for b in (self.send_btn, self.clear_btn, self._clear_all_btn,
                              self._mem_rebuild_btn, self.sessions_btn):
                        b.configure(state="normal")
                    self.gen_status.configure(text="")
                    if self._right_tabs.get() == self._tab_memory:
                        self._refresh_memory_box()
                    then, self._dyn_then = self._dyn_then, None
                    if then is not None:
                        then(item[1])
                elif isinstance(item, tuple) and item and item[0] == "__RETRY_DUP__":
                    # НЕ в чат/историю (ломает иммерсивность реплики) -
                    # только статус (заметно, но проходяще; постоянная
                    # запись, капсом в заголовке, уже ушла в Logs)
                    _, i, n = item
                    self.gen_status.configure(text=t("st_retry_dup", i=i, n=n))
                elif isinstance(item, tuple) and item and item[0] == "__TURN__":
                    self._begin_turn(item[1])        # аватарка перед репликой персонажа
                    self._emote_advance("character")  # и следующий эмотикон собеседника
                elif isinstance(item, tuple) and item and item[0] == "__RETRY_STALL__":
                    # только статус (запись в Logs уже сделал воркер) - в чат
                    # ничего не пишем, как и у остальных авто-перезапросов
                    _, i, n, secs = item
                    self.gen_status.configure(text=t("st_retry_stall", s=secs, i=i, n=n))
                elif isinstance(item, tuple) and item and item[0] == "__RETRY_LOOP__":
                    _, i, n = item
                    self.gen_status.configure(text=t("st_retry_loop", i=i, n=n))
                elif isinstance(item, tuple) and item and item[0] == "__TRIM__":
                    # откатить последние n символов чата (текст этой же
                    # генерации, который сама генерация только что и вывела -
                    # никакой чужой текст так не затронуть, см. _generate_worker)
                    _, n = item
                    if n > 0:
                        self.chat_box.configure(state="normal")
                        self.chat_box.delete(f"end-{n + 1}c", "end-1c")
                        self.chat_box.configure(state="disabled")
                elif isinstance(item, tuple) and item and item[0] == "__DIGEST_REBUILT__":
                    _, ok, upto = item
                    if ok:
                        self.digested_upto = upto
                    else:
                        messagebox.showwarning(t("memory_title"), t("mem_failed"))
                    self._rebuilding = False
                    self._mem_rebuild_btn.configure(state="normal")
                    self.gen_status.configure(text="")
                    if self._right_tabs.get() == self._tab_memory:
                        self._refresh_memory_box()
                elif isinstance(item, tuple):
                    text, tag = item
                    self._append_chat(text, tag)
                else:
                    self._append_chat(item)
        except queue.Empty:
            pass
        flush()
        try:
            while True:
                self._append_log(self.log_queue.get_nowait())
        except queue.Empty:
            pass
