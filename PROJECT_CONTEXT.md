# PROJECT_CONTEXT

Контекст для того, кто (человек или агент) продолжает работу над проектом.
**Источник истины - код на диске.** Если этот файл где-то разошёлся с
кодом (правки руками и т.п.) - верь коду, а этот файл поправь.

## Что это

Десктопное приложение для текстового ролплея с локальной моделью через
Ollama. Нативное окно на CustomTkinter (обычный Tkinter под капотом),
никакого браузера/webview. Всё живёт локально: модель в Ollama на
`localhost:11434`, пресеты - в JSON в `%APPDATA%/OllamaRP`.

## Архитектура (по файлам)

- **`i18n.py`** - локализация интерфейса RU / EN. `get_lang()` /
  `set_lang(v)` - глобальный язык (`"ru"` / `"en"`); `t(key, **fmt)` -
  строка интерфейса по ключу из `_UI` (dict `key -> {"ru":..., "en":...}`).
  Для данных из чистых модулей русский берётся из исходника, а тут лежат
  ТОЛЬКО английские переводы: `block_title(block)` / `field_label(block,
  attr)` / `field_labels(block)` (поверх `blocks.BLOCK_SPECS`),
  `inf_label(attr, ru)` / `inf_help(attr, ru)` (поверх
  `inference_spec.INFERENCE_FIELDS`), `think_labels()` /
  `think_from_label()`, `story_size_choices(none)`. Модуль импортит
  `blocks`/`inference_spec` лениво (внутри функций) - циклов нет.
- **`models.py`** - dataclass'ы `Character`, `Protagonist`, `Environment`,
  `Scenario`, `SystemConfig`. У всех есть `id` (генерируется `_new_id()`)
  и `name`. `Character` также имеет `biography`. `Protagonist` (главный
  герой, «Вы») - `name` / `biography` / `appearance` / `personality`.
  `to_dict` через `asdict`, `from_dict` через `d.get(k, "")` по
  фиксированному списку ключей - добавление поля обратно совместимо со
  старыми JSON (недостающий ключ → `""`). Плюс **`InferenceConfig`** -
  параметры генерации (НЕ пресет): числовые поля `Optional`, `None` =
  «не отправлять»; `stop` - сырой многострочный текст; `think:
  Optional[bool]`; `keep_alive: str`. `to_options()` собирает
  `payload["options"]` только из заданных полей (`stop` → список строк;
  `think`/`keep_alive` в options НЕ входят - верхний уровень). `from_dict`
  терпим к мусору (строка вместо числа, `bool` в число → `None`).
  UI-поля `right_panel_hidden` / `left_panel_hidden` / **`ui_language`**
  (`"ru"` / `"en"`, дефолт `"ru"`) / **`last_model`** (последняя выбранная
  модель, `""` по умолчанию) - round-trip в settings.json, в options
  не идут.
  Модульный `OPTIMAL_INFERENCE` (dict) + `InferenceConfig.optimal()` -
  рекомендованный набор для RP (temp 0.8 / top_p 0.9 / top_k 40 /
  min_p 0.08 / repeat_penalty 1.05 / repeat_last_n 64 / num_predict -1 /
  num_ctx 8192; seed/stop/think/keep_alive не задаются). Мягкий
  repeat_penalty + узкое окно - намеренно: высокие значения на русском
  провоцируют code-switch на английский.
- **`storage.py`** - `PresetStore`: по файлу на каждый тип
  (`characters.json` / `protagonists.json` / `environments.json` /
  `scenarios.json` / `system_configs.json`). `load_*` / `save_*`
  (перезапись файла целиком), `upsert_*` (вставить или обновить по `id`,
  иначе по `name` - хелпер `_upsert()`; чтобы правки не плодили дубли) и
  `delete_*(id)` (фильтрация списка по `id`, несуществующий id - молча
  no-op). Отдельно `load_settings()/save_settings()` для `settings.json`
  - **один** `InferenceConfig`, не список; если файла нет →
  `InferenceConfig.optimal()` (рекомендованный набор действует сразу,
  без захода на вкладку Settings).
- **`prompt_builder.py`** - `build_system_prompt(character=None,
  environment=None, scenario=None, mode="dialogue", system_config=None,
  protagonist=None, characters=None, story_size="", story_details="",
  extra_details="", ..., lang="ru")`. **Все билдеры** (`build_system_prompt`,
  `build_digest_messages`, `build_field_generation_messages`, `role_guard`,
  `memory_header()`) принимают `lang=` со значением по умолчанию `"ru"` -
  старые вызовы (и тесты) не меняются. При `lang="en"` берутся `*_EN`
  версии констант И английские заголовки блоков (`## Character:`,
  `Biography:` …). GUI прокидывает `i18n.get_lang()`.
  `reasoning_nudge=True` → в самый верх добавляется `REASONING_NUDGE`
  (просьба рассуждать в `<think>...</think>`) - для reasoning-моделей БЕЗ
  capability `thinking`. В `dialogue`/`story` после инструкций режима
  вставляется `LANGUAGE_RULE` / `LANGUAGE_RULE_EN` (жёстко «только на
  выбранном языке, без смешения») - против code-switch; в `chat` его нет
  (там system-промпта нет вообще). Плюс `LANGUAGE_REMINDER` /
  `LANGUAGE_REMINDER_EN` - короткий ПОВТОР того же правила, но вставлен в
  САМЫЙ КОНЕЦ промпта (после персонажа/сценария/параметров истории), не
  рядом с LANGUAGE_RULE в начале. У слабых/квантованных моделей вес
  инструкции из начала промпта теряется под грузом данных сцены после неё
  - то, что модель прочитала ПОСЛЕДНИМ перед генерацией, влияет сильнее
  (эффект недавности). Текст называет КОНКРЕТНО ту деградацию, что реально
  наблюдалась в баг-репорте: не общее «пиши по-русски», а прямой запрет на
  английские служебные глаголы при репликах (`said`/`asked`/`smiled` вместо
  «сказал»/«спросила»/«улыбнулась» ОДНИМ словом внутри русского
  предложения) - самый частый вид просачивания языка у слабых моделей.
  `structured_dialogue=True` (только `mode=="dialogue"`)
  → после инструкций режима вставляется `STRUCTURED_DIALOGUE_INSTRUCTIONS`
  (ответ JSON `{action, speech}`); парная `STRUCTURED_DIALOGUE_SCHEMA`
  уходит в `chat_stream(response_format=...)`. Для **послойной «бегущей
  памяти»** (детали в разделе GUI): `build_segment_summary_messages(known,
  entries, system_prompt=, lang=)` + `SEGMENT_SUMMARY_SYSTEM[_EN]` (сжать
  один сегмент), `build_consolidation_messages(mem_head, old_segments,
  lang=)` + `CONSOLIDATE_SYSTEM[_EN]` (влить старые сводки в
  долговременную голову), `memory_header(lang)` (заголовок блока памяти в
  промпте), `digest_system(lang)` → `DIGEST_SYSTEM[_EN]` (дефолт для
  «Промпт памяти»). `build_digest_messages(...)` - старый плоский вариант,
  оставлен для совместимости/тестов, GUI им больше не пользуется.
  `role_guard(characters, protagonist)` (только dialogue) - явная строка
  «пиши ТОЛЬКО за <персонажи>; НИКОГДА не пиши за <ГГ>», ставится сразу
  после инструкций режима (борьба с «модель отвечает за главного героя»).
  Порядок блоков: [nudge] → `system_config.content` (если задан) →
  инструкции режима (`DIALOGUE_INSTRUCTIONS` / `STORY_INSTRUCTIONS`) →
  [role_guard] → [JSON-инструкция] → главный герой
  (если непустой) → персонаж(и): `characters` если задан, иначе
  `[character]` → окружение (если `environment is not None`) → сценарий →
  [«## Дополнительные детали» — только `mode="dialogue"` и непустой
  `extra_details`] → параметры истории (только `mode="story"` и непустые
  `story_size` / `story_details`). Все новые параметры имеют дефолты, старые позиционные
  вызовы `build_system_prompt(char, env, scn, mode=...)` работают
  байт-в-байт как раньше. Это ядро кастомизации - стиль бота меняется здесь.
- **`ollama_client.py`** - вся сетевая работа. `list_models()`;
  `model_capabilities(model)` - POST `/api/show`, множество (`{"completion",
  "thinking", "tools", ...}`), при любой ошибке `set()`;
  `parse_stream_line()` (message.content) и `parse_stream_thinking()`
  (message.thinking) - чистые, тестируются без сети.
  `parse_structured_reply(text)` - JSON-ответ модели → `(action, speech)`,
  фолбэк `("", text)` на битом JSON.
  `normalize_messages(messages)` - схлопывает подряд идущие роли в одну
  (через `\n\n`); вызывается ВНУТРИ `chat_stream` перед сборкой payload.
  Нужно, т.к. chat-шаблоны Mistral/Ministral/Gemma падают с Jinja-ошибкой
  (HTTP 500 "roles must alternate") на двух `user` подряд.
  `chat_stream(model, messages, options=None, think=None, keep_alive=None,
  stop_event=None, on_request=None, on_thinking=None, response_format=None,
  strip_inline_think=True)` - генератор ВИДИМОГО `content`.
  `options`/`think`/`keep_alive`/`format` кладутся в payload только если
  заданы. `strip_inline_think=False` → `_ThinkSplitter` не создаётся
  (structured-режим: контент это JSON), но `parse_stream_thinking` всё
  равно ловит `message.thinking`. Больше **не** `with requests.post(...)`: делаем
  `resp = requests.post(...)`, при `status_code >= 400` читаем тело
  (`_error_detail`) пока соединение живо и кидаем `OllamaError` с
  текстом причины; `finally: resp.close()`. `on_thinking` получает
  размышления из ДВУХ источников: поле `message.thinking` И инлайновые
  `<think>…</think>` в `message.content` - последние вырезает
  потоковый `_ThinkSplitter` (склейка тегов, разорванных между чанками;
  незакрытый тег → остаток в размышления). `stop_event` проверяется
  перед каждой строкой `iter_lines()`.
- **`inference_spec.py`** - `INFERENCE_FIELDS`: список
  `{attr, label, kind, help, ph}` для вкладки Settings. `kind` ∈
  `{"float","int","str","stoplist","think"}`. `THINK_LABELS` -
  подпись ↔ `None/True/False`. Без tkinter, `attr` обязан совпадать с
  полем `InferenceConfig` (проверяется тестом).
- **`blocks.py`** - единое описание блоков: `BLOCK_SPECS[block]` =
  `{title, model, load, upsert, delete, fields, seed}`. `fields` -
  список `(attr, label, widget)`, `widget` ∈ `{"entry", "textbox"}`,
  `attr` обязан совпадать с полем dataclass. `load/upsert/delete` -
  **имена методов** `PresetStore`. `seed` - lambda с примером для
  первого запуска. Зависит только от `models` (без tkinter) - можно
  импортировать в тестах. `BLOCK_ORDER` = все блоки с одиночным выбором
  пресета: `("protagonist", "character", "environment", "scenario",
  "system_config")` (GUI сам решает, какие показывать в каком режиме).
  `SHORT_LABELS` - там же.
- **`preset_ui.py`** - модальные окна: `PresetEditDialog` (форма одного
  пресета, `.result` = объект или `None`) и `PresetManager` (список +
  Создать/Редактировать/Удалить, зовёт `on_change()` после каждой
  правки). `grab_set` отложен через `after(90, ...)` - свежесозданное
  окно ещё не viewable. После вложенного `PresetEditDialog` менеджер
  возвращает себе grab (`after(50, self._grab)`).
  - **Кнопка «Сгенерировать»** напротив каждого поля, кроме имени/названия
    пресета (имя всегда вручную). `PresetManager`/`PresetEditDialog`
    принимают `gen_context` - callable, который GUI отдаёт как
    `App._preset_gen_context` (модель, опции семплинга из Settings без
    `stop`, `num_predict=400`, `think=False` только для reasoning-моделей,
    `log_queue` + `_fmt_log_entry`); вызывается в момент нажатия, поэтому
    всегда актуален. Запрос строит чистая
    `prompt_builder.build_field_generation_messages(block, attr, label,
    values, field_labels, short=)` -> `[{system},{user}]`: непустые поля
    объекта (включая имя) идут как «уже известно», генерируемое поле не
    подаётся, вшит `LANGUAGE_RULE`. `short=True` для `entry`-полей
    (Локация / Время суток / Погода) - просим слово/словосочетание без
    предложения; там же `_generate_field` жмёт `num_predict=64` как
    бэкстоп. `PresetEditDialog._gen_worker` гоняет `chat_stream` в потоке,
    результат кладёт в `self._gen_q`, `self.after(100, self._poll_gen)`
    его забирает и подставляет в поле: textbox - как есть, entry -
    первая непустая строка без кавычек и точки в конце. Пока идёт
    генерация - все кнопки «Сгенерировать» disabled, активная «…».
- **`help_texts.py`** - текст справочных окон «О приложении» / «Помощь» /
  «FAQ» как списки блоков `("h"|"q"|"p"|"li", str)`, по два языка:
  `_DATA[name] = {"ru": [...], "en": [...]}`, `blocks(name)` отдаёт список
  под текущий `i18n.get_lang()`. Заголовки окон - `i18n.t("about_title")`
  и т.п. Рендерит `gui.App._open_info_window(attr, name)`.
- **`gui.py`** - окно. Генерация идёт в `threading.Thread`
  (`_generate_worker`), кусочки текста складываются в `queue.Queue`,
  GUI-поток забирает их из очереди каждые 50мс в `_poll_queue`
  (`self.after(50, ...)`) - стандартный безопасный способ трогать
  Tkinter из фонового потока. Аналогично устроена панель Logs: свой
  `self.log_queue`, тот же `_poll_queue` её разгребает.
- **`main.py`** - точка входа.
- **`test_logic.py`** - тесты всего, что без GUI/сети. Запуск
  `python test_logic.py` (или `run_tests.bat`). Свой мини-раннер (не
  pytest): у каждого теста docstring, первая строка которого печатается
  в консоли рядом с номером; при падении выводит тип ошибки, её текст и
  строку `файл:номер -> исходная строка assert`, остальные тесты
  доигрываются. Код возврата 1, если что-то упало.

## Ключевые решения / детали GUI

- **Копирование/вставка** (`_bind_clipboard`, вызывается в `__init__`):
  `bind_all("<Control-KeyPress>", _on_ctrl_key)` - Tkinter привязывает
  Ctrl+C/V/X/A только к латинским клавишам, при русской раскладке они не
  срабатывают. `_on_ctrl_key` пропускает латиницу (её обрабатывает сам
  Tk), а не-латинские ловит по кириллическим keysym (`Cyrillic_es/em/
  che/ef`) И по Windows-VK `event.keycode` (67/86/88/65) → генерирует
  `<<Copy>>/<<Paste>>/<<Cut>>` на `event.widget`, для select-all -
  `_select_all` (tag `sel` / `selection_range`). `bind_all` действует во
  всех виджетах, включая модальные окна `preset_ui`. Плюс контекстное
  меню по `<Button-3>` (`_build_context_menu` / `_show_context_menu` /
  `_ctx_do`): `tk.Menu` с Вырезать/Копировать/Вставить/Выделить всё,
  для `state="disabled"` виджетов (чат, логи) Вырезать/Вставить гасятся.

- **Единая шкала отступов**: в разметке `gui.py` (и `preset_ui.py`)
  используются ТОЛЬКО три размера - `PAD_TIGHT=4` (подпись ↔ поле,
  элементы группы), `PAD=8` (поля панелей, промежутки между колонками и
  блоками, кнопки), `PAD_SEC=16` (между группами настроек, поля модалок).
  Исключения - несколько «подогнанных» под выравнивание значений, каждое
  с комментарием на месте: `pady=(28,0)` у колонки кнопок чата,
  `pady=(3,2)/(3,0)/(3,8)` у трёх нижних подсказок, `pady=(0,0)` у
  `logs_box`, `padx=(6,0)` у кнопок памяти (там своя арифметика ширины).
- **Три главные колонки - все три `CTkTabview`, зеркальные и равной
  ширины.** У каждой: обёртка `fg_color="transparent"` (`_left_col` /
  `col` / `_right_col`) + `CTkTabview` (`_left_tabs` «Сцена / Настройки» /
  `_chat_tabs` «Диалог / История / Чат» / `_right_tabs` «Logs / Память»).
  Кнопка «свернуть»
  `place()`-оверлеем в верхнем углу (`_left_collapse_btn` «‹»
  `place(x=0, y=10)`; `_right_collapse_btn` «›» `place(relx=1.0, x=0,
  y=10, anchor="ne")` - зеркально; у центра кнопки нет).
- **`_chat_tabs` - это ПЕРЕКЛЮЧАТЕЛЬ РЕЖИМОВ** (`_MODES` = `["dialogue",
  "story", "chat"]`). Вкладки подписаны локализованно через `MODE_LABELS()`
  (RU `Диалог` / `История` / `Чат`, EN `Dialogue` / `Story` / `Chat`);
  внутреннее значение режима везде остаётся английским. Отдельной кнопки
  режима в верхней панели НЕТ.
  Клик по вкладке → `command=_on_chat_tab_switch` →
  `_on_mode_change(MODE_FROM_LABEL[_chat_tabs.get()])`. Содержимое центра (`chat_box` +
  `form` + поля ввода) - фрейм `_chat_body`, ребёнок самого `_chat_tabs`,
  гридится в тот же ряд (`row=3`) и с тем же `padx/pady=corner_radius`,
  что CTkTabview даёт фреймам-вкладкам, и держится поверх (`tkraise()`
  при старте, в `_on_chat_tab_switch` и в `_on_mode_change`). Сами
  фреймы вкладок пустые. `_on_mode_change` синхронизирует `_chat_tabs.set`
  русской подписью (программный `set` command не зовёт).
- **Верх всех трёх блоков на одной линии - СТРУКТУРНО, без замеров.** Так
  как все три - `CTkTabview` с одинаковым таб-баром и внутренним хромом,
  верх контент-фрейма вкладки совпадает у всех трёх. Внутри каждой вкладки
  первый ряд - «шапка» фикс. высоты `HEAD_H=44` (`grid_propagate(False)`):
  слева «Пресеты сцены» (плашка; `label_text` у `CTkScrollableFrame`
  убран), справа тулбар вкладки (`_build_logs_tab` / `_build_memory_tab`,
  кнопки по центру), в центре - плашка `self._mode_hint` с однострочной
  подсказкой по текущему режиму (`MODE_HINTS`, текст ставит
  `_apply_input_mode`). Основной
  блок (`_preset_panel` / `chat_box` / `logs_box`) - следующий ряд.
  Проверено: L=C=R spread 0 на 1300–1800 px.
  `form` центра: `pady=(0, 2)` (как нижний отступ боковых подсказок) →
  низ `_dlg_hint` / `reply_box` совпадает с `_left_hint` / `logs_box`.
- **Равные ширина и зазоры**: `body` `grid_columnconfigure(0..2, weight=1,
  minsize=COL_MIN=500)`. Боковые панели отдают `PAD` со своей внутренней
  стороны (`_left_col`/`_left_reopen` `padx=(0, PAD)`, `_right_col`/
  `_right_reopen` `padx=(PAD, 0)`), чат - `PAD_TIGHT` с каждой из двух ->
  каждая панель теряет 8 px, зазор = 12 px с обеих сторон.
  `_apply_*_panel_visibility` при разворачивании возвращает `weight=1,
  minsize=COL_MIN`; при сворачивании колонка уходит под полоску
  (`weight=0, minsize=0`), место делят обе оставшиеся панели поровну.
  Дефолт окна - `1560x860`.
- **`_build_logs_panel`** строит `_right_tabs` и по вкладке:
  `_build_logs_tab` (тулбар «Очистить / Экспорт…» + `logs_box` + серая
  подсказка) и `_build_memory_tab` (тулбар «Промпт памяти / Пересобрать /
  Применить / Экспорт…» + `memory_box` + подсказка). Экспорт →
  `_export_logs` / `_export_memory` → общий `_export_plain(text, title,
  name)` (сохранение в .txt UTF-8; пусто → `export_nothing`); память
  экспортируется из `self.chat_digest`. Кнопки тулбаров - ПО ЦЕНТРУ, во
  вложенном `inner`-фрейме `pack(side="left")`;
  `bar.grid(pady=(PAD, PAD))` - воздух сверху и снизу. Контент у каждой
  вкладки постоянный, ничего не свапается. `_on_right_tab(*_)` -
  `command` у `CTkTabview` (плюс
  ручной вызов): при переключении на «Память» делает `_refresh_memory_box`.
  `_right_tab = _right_tabs._segmented_button` - только для
  `configure(values=["Logs"])` в story/chat (кнопка «Память» прячется,
  сам фрейм вкладки жив).
- **Левая колонка - `CTkTabview` из двух вкладок**: «Сцена» (селекторы
  пресетов, ниже) и «Настройки» (`self._tab_settings`; `_build_settings_panel` -
  параметры генерации). Чат и Logs всегда справа, вне вкладок.
- **Конструктор из независимых блоков** (вкладка «Сцена»): Главный герой
  (Вы) / Персонаж / Локация / Сценарий / Конфигурационный промпт. Каждый
  сохраняется/загружается **отдельно**. Режим `dialogue`/`story` -
  вкладка таб-бара `_chat_tabs`, НЕ блок.
- **Вкладка Settings** (`_build_settings_panel`): по полю на каждый
  элемент `INFERENCE_FIELDS` (Entry / многострочный для `stop` /
  OptionMenu для `think`) + серый help под каждым. `self._inf_widgets`:
  `attr -> (kind, widget)`. `_collect_inference_config()` читает виджеты
  → `InferenceConfig` (нечисло в числовом поле → `None`, не падаем);
  `_load_inference_into_widgets()` - обратно. Кнопки: «Сохранить
  настройки» (`_save_inference` → `store.save_settings`), «Optimal»
  (`_optimal_inference` → `InferenceConfig.optimal()`), «Очистить»
  (`_reset_inference` → пустой `InferenceConfig()`). Загрузка при старте
  (из `store.load_settings()`, т.е. рекомендованный набор, если нет
  файла) + автосейв в `_on_close` (`WM_DELETE_WINDOW`).
- **Параметры применяются к каждому запросу**: `_on_send` в обоих режимах
  делает `inf = self._collect_inference_config()` и передаёт в поток
  `opts = inf.to_options()`, `inf.think`, `inf.keep_alive or None` →
  `chat_stream(...)`. Всё это видно в Logs (оно в payload).
- **Предпроверка контекста** (`_preflight_context`, до фиксации хода -
  `history`/`chat_box` ещё чисты): `estimate_tokens(preview)` (грубая
  ВЕРХНЯЯ оценка, `chars/2.5 + 4·n`) + резерв под ответ (`num_predict>0`
  или 2048). Если `need > num_ctx·0.95` (или `num_ctx` не задан и
  `need > 4000`) - модальное `_ask_context_choice(need, ctx, suggested)`
  с 4 кнопками:
  - **«Поднять num_ctx до N»** (`next_num_ctx(need)` - степень двойки, до
    131072): пишет в виджет + `save_settings`, `opts["num_ctx"] = N`,
    отправка продолжается;
  - **«Сжать пример»** → `_compress_example(model, inf, preview)`. **Жмёт
    САМЫЙ КРУПНЫЙ источник примера**: `self.history` ИЛИ поле
    «Дополнительные детали» текущего режима (`_example_box()`; `"box"` если
    `len(box_text) > hist_chars`). Пример часто именно в «Доп. деталях»
    (туда вставляют большой диалог), history при этом пуста - раньше сжатие
    в этом случае молча ничего не делало.
    **Целевой объём сводки считается от num_ctx** (`preview` - сообщения
    будущей генерации, из них берём «оверхед» = всё, кроме примера):
    `target = int(eff_ctx·0.85) - overhead - reply_reserve`, ограничен
    `[1200 … example·0.85]`, `eff_ctx = max(num_ctx, 8192)`. Задача - НЕ
    «ужать максимально» (как память), а занять почти весь оставшийся
    контекст = сохранить максимум деталей. Дальше раскладка на `n`
    запросов под ДВА ограничения: (1) на один запрос генерим не больше
    `COMPRESS_CHUNK_OUT_CAP=2400` токенов (мягкий потолок: шаг не
    многоминутный, виден прогресс, работает «Стоп»; но не дробим мелко -
    лишние запросы = лишний prompt-eval); (2) `chunk_in + per_out`
    влезает в `eff_ctx`. `n`
    растёт, пока оба не выполнены; `per_out = ceil(target/n)`,
    `chunk_in = ceil(example/n)`. Куски - `_text_chunks(text, chunk_in·2.5)`
    (абзацы → строки → жёстко) или `_size_chunks(msgs, chunk_in)`
    (склеенные в текст).
    `_compress_worker(chunks, words, per_out, target, src_len, options,
    keep_alive, stop_event)`: по куску `_run_hidden(build_compress_messages(
    chunk, words), opts{temp 0.3, num_predict=per_out+400 (запас на
    <think>), num_ctx=eff_ctx}, stop_event=, on_tick=)`.
    `build_compress_messages` явно просит «отвечай сразу, без рассуждений и
    <think>» - для reasoning-моделей без capability. `on_tick` шлёт
    `__COMPRESS_TICK__(i, n, nchars, nthink)` (троттлинг 200 симв) →
    статус `st_compress_out` «~N слов» / `st_compress_think` «модель
    думает…». Кусок не сжался → сырой, подрезанный до `per_out`; провал =
    ни один не сжался (и не было «Стоп»). Финал -
    `__COMPRESS_DONE__(summary|None, target, src_len, stopped)`.
    **«Стоп»**: `_compress_example` создаёт `self.stop_event`, включает
    `stop_btn`; `chat_stream(stop_event=)` рвёт текущий кусок, воркер
    видит `is_set()` между кусками и завершает с тем, что успело сжаться
    (`compress_stopped_note` → всё равно авто-генерация; если ничего -
    `compress_cancelled_note`, пример не тронут).
    В `_poll_queue`: успех + `"box"` → `_details_backup = <поле>`, поле
    заменяется сводкой; успех + `"history"` → `_history_backup = history`,
    `history = [compressed_history_intro + сводка]`, `_reset_memory()`.
    Обе ветки: заметка, кнопки обратно, `stop_btn` off,
    `_just_compressed = True`, **`after(60, _on_send)` - генерация стартует
    сама**. Провал → `compress_fail_note` + `messagebox`.
    `_preflight_context` при `_just_compressed` (read-then-clear) не
    предлагает «Сжать пример» второй раз (`_ask_context_choice(...,
    allow_compress=False)`) - защита от зацикливания;
  - **«Продолжить как есть»** - отправка как есть (риск: Ollama режет с
    начала → у Mistral/Ministral Jinja-ошибка «roles must alternate»);
  - **«Отмена»** - `_on_send` выходит, ничего не тронув.
- **Две верхние полосы равной высоты**: `top` (Модель / кнопки) и `info`
  (Reasoning-бейдж + активные пресеты + `gen_status`) - обе
  `height=BAR_H=40` + `pack_propagate(False)`, содержимое (28 px)
  центрируется. Отступы одинаковые: `pady=(PAD, 0)` у `top` и `info`,
  `pady=(PAD, PAD_TIGHT)` у `body` -> зазоры окно→top→info→body все по
  `PAD` (8).
- **Верхняя панель** (`top`): «Модель:» + `model_menu` (фикс. ширина 300,
  `dynamic_resizing=False` - длинные имена `hf.co/...` не распирают
  панель) + «Обновить список» (`_refresh_models`) + «О приложении»
  (`_open_about`) + «Помощь» (`_open_help`) + «Скачать модели»
  (`_open_model_library` → `webbrowser.open("https://ollama.com/library")`)
  + «Запустить cmd» (`_open_cmd`: открывает окно-шпаргалку `"cheatsheet"`
  И системную консоль - `subprocess.Popen("cmd /K",
  CREATE_NEW_CONSOLE)` на win32, `open -a Terminal` на macOS, перебор
  терминалов на Linux; ошибка → `messagebox`) + «FAQ» (`_open_faq`);
  справа - подпись «Язык:» + `_lang_seg` (`CTkSegmentedButton` RU/EN).
  - **Запоминание последней модели**: `model_menu`'s `command=
    self._on_model_selected` (раньше было `lambda _v:
    self._update_model_caps()`) - при ручном выборе в меню, помимо
    бейджа reasoning, СРАЗУ (не дожидаясь «Сохранить» в Settings или
    закрытия окна) сохраняет `InferenceConfig.last_model` в settings.json
    (`try/except`, как `_on_close`). `_refresh_models()` (стартовый вызов
    в `__init__` ПОСЛЕ `self._last_model = _saved.last_model`, и кнопка
    «Обновить список»): приоритет - у ТЕКУЩЕГО выбора в `model_var` (мог
    смениться после старта), если его больше нет в списке - у
    запомненной `self._last_model`, если и той нет - первая по списку
    (как раньше). `_collect_inference_config()` кладёт в `last_model`
    текущий `model_var`, ЕСЛИ это настоящая модель (`_no_model()` ==
    False) - плейсхолдеры `"..."`/«модели не найдены» не пишутся поверх
    ранее запомненного (иначе сохранение в момент, когда Ollama временно
    недоступна, затёрло бы последнюю реальную модель пустой строкой);
    заодно держит `self._last_model` в синхроне для следующего
    `_refresh_models()` в ЭТОЙ ЖЕ сессии.
  Справочные кнопки открывают немодальное `CTkToplevel` со скроллом
  (`_open_info_window(attr, name)`; `name` ∈
  `"about"/"help"/"faq"/"cheatsheet"`; повторный клик поднимает уже
  открытое окно). Тексты - `help_texts.blocks(name)` под текущий язык.
- **Локализация RU / EN** (см. `i18n.py`):
  - `_lang_seg` → `_on_lang_change(choice)`: во время генерации/пересборки
    блокируется (revert `.set()` + `messagebox`); иначе `i18n.set_lang`,
    `self._ui_language = lang`, `store.save_settings`, `_relayout_language(snap)`.
  - **Живая пересборка**: `_snapshot_ui()` (делается ДО `set_lang` - индексы
    «Размера истории» и имена вкладок ещё на старом языке) → `_rebuilding_ui
    = True` → закрыть справочные `CTkToplevel` (`_about_win` / `_help_win`
    / `_faq_win` / `_cheat_win`) + менеджеры пресетов →
    `destroy` трёх корневых фреймов (`_top_bar` / `_info_bar` / `_body`) →
    `_build_context_menu()` + `_build_layout()` → `_restore_ui(snap)` →
    `_rebuilding_ui = False`. `_poll_queue` при `_rebuilding_ui` только
    перепланирует себя и выходит.
  - Снимок/восстановление: `mode_value`, `_collect_inference_config()` (все
    поля Settings + digest_prompt + флаги панелей + `ui_language`),
    `self.active`, `story_characters`, индекс «Размера истории», тексты
    полей ввода / «Доп. деталей», лента чата и лог (как plain-текст -
    курсив пересоздаётся с новых ходов), `mem_head` / `mem_segments` /
    `digested_upto` (+ `_render_memory()` после восстановления),
    какая вкладка выбрана слева/справа, список моделей + выбор + `_model_caps`
    (бейдж рисуется `_render_reasoning_badge()` без сети).
  - Подписи вкладок и `_MODES`-лейблы - функции `MODE_LABELS()` /
    `MODE_FROM_LABEL()` / `MODE_HINTS()` / `TAB_SETTINGS()` /
    `STORY_SIZE_CHOICES()` (раньше были константами). Имена вкладок в
    рантайме хранятся в `self._tab_scene/_tab_settings/_tab_logs/_tab_memory`.
- **Reasoning**:
  - Бейдж `self._reasoning_badge` - во ВТОРОЙ строке (`info`), слева от
    `active_label`: фрейм из двух подписей - `_reasoning_prefix`
    («Reasoning:», обычный цвет темы) + `_reasoning_state`
    (`enabled` / `disabled`, серым); при неизвестных caps обе пустые.
    `_update_model_caps()` - блокирующий `model_capabilities()` при выборе
    модели и в конце `_refresh_models()` → `self._model_caps` →
    `_render_reasoning_badge()` (последний рисует бейдж по `_model_caps`
    без сети - зовётся и из `_restore_ui`).
  - `_resolve_reasoning(want)` → `(think, nudge)`. Модель С capability
    `thinking`: `want None/True` → `think=True`, `want False` →
    `think=False`, `nudge=False`. Модель БЕЗ capability: `want True` →
    `think=None, nudge=True` (наталкиваем промптом, т.к. `think` дал бы
    400); `want None/False` → `(None, False)`. `nudge` уходит в
    `build_system_prompt(reasoning_nudge=...)` в обоих режимах.
  - `_generate_worker`: `on_thinking` копит в `think_buffer`, на первом
    куске шлёт маркер `__THINKING__` в `token_queue`; первый видимый
    чанк ответа → маркер `__ANSWERING__`; `_fold_segment` в начале шлёт
    `__MEMORY_BUILDING__`, `_rebuild_digest_worker` - `__MEMORY_PROGRESS__`
    i/n. `_poll_queue` по этим маркерам двигает
    `self.gen_status` (⏳ ждём модель… → 💭 размышляет… → ✍ отвечает… →
    🧠 собираю память… / 🧠 память i/n; `_set_generating(False)` / `__DIGEST_REBUILT__`
    очищают). Весь текст
    размышлений в конце - в Logs блоком `РАЗМЫШЛЕНИЯ <- model`, в чат -
    никогда.
  - Модель не поддерживает форсированный `think` → `OllamaError` с
    текстом от Ollama, виден в чате и в Logs (`ОШИБКА <- model`).
- **Вкладка «Сцена»** (`_build_preset_panel(parent)`, `parent` -
  фрейм-таб `_left_tabs`, серый) - grid из 4 рядов:
  - row 0 (`weight=0`): `phead` - плашка «Пресеты сцены» фикс. высоты
    `HEAD_H` (см. «верх всех трёх блоков на одной линии»);
  - row 1 (`weight=0`, `minsize=PRESET_MIN_H`≈410): `_preset_panel`
    (`CTkScrollableFrame` БЕЗ `label_text`) - **фикс. высота**. Высота
    подобрана так, чтобы БЕЗ прокрутки помещались и 5 селекторов dialogue,
    и набор story с ОДНИМ добавленным персонажем («Размер истории» виден
    целиком). `_apply_mode_view`
    `pack`/`pack_forget` секции внутри; длинный список story-персонажей
    **скроллится** внутри этой высоты, НЕ выталкивая блоки ниже. Полоса
    прокрутки видна ТОЛЬКО когда содержимое реально не влезает
    (`_autohide_scrollbar`: `after_idle`-проверка по актуальному
    `canvas.yview()`, триггерится `yscrollcommand` + `<Configure>` +
    ручной `_preset_panel._autohide_recheck()` из `_apply_mode_view` /
    `_render_story_characters`);
  - row 2 (`weight=1`, `minsize=DETAILS_MIN_H`≈145): `_details_host` -
    «Дополнительные детали» (`dialogue_details_box` / `story_details_box`
    в одной ячейке, `grid`/`grid_remove` по режиму; поле `sticky="nsew"`,
    `height=156` - только минимум). **Резиновое**: забирает весь лишний
    вертикальный запас и растёт ВВЕРХ (на весь экран - без пустого серого
    зазора над «Доп. деталями»); низ поля остаётся на линии с низом «Твоя
    реплика» / `logs_box` (проверено `+0` на 1400–1920 px);
  - row 3 (`weight=0`): `_left_hint` («`«—»` — блок не участвует») - на
    сером фоне таба, `pady=(3, 2)`, ВНЕ скролла → **виден всегда**,
    низ на линии с `Ctrl+Enter` под чатом и пояснением под Logs/Память.
  В `chat` `_details_host` и `_left_hint` скрыты, `_left_tabs` → «Настройки».
- **`_apply_mode_view(mode)`** - набор секций в `_preset_panel`:
  - `dialogue`: protagonist · character · environment · scenario ·
    system_config (селекторы);
  - `story`: protagonist · **несколько персонажей** · scenario ·
    system_config · **«Размер истории»** (`story_params_section` - теперь
    только меню). Блока `environment` нет.
  Плюс переключает видимое поле в `_details_host` и `_left_hint`.
- **На главном экране нет полей конфигурации** (кроме story-полей ниже).
  Селекторная строка (`_make_selector_row`): заголовок сверху, ниже -
  `CTkOptionMenu` (`pack(side="left", fill="x", expand=True)` - тянется на
  всю ширину) и кнопка «Настроить» (`pack(side="right")`, прижата к
  правому краю - в одну линию с краем текстовых полей ниже). То же в
  story-строке выбора персонажей (`pick`): меню тянется, «Добавить» и
  «Настроить» прижаты вправо. Выбор в меню = активный пресет (callback
  `_on_select_preset`). Пункт `«—»` (`NONE_CHOICE`) = блок не
  используется, в промпт уходит пустой объект (`_active_or_empty`).
- **Несколько персонажей (только story)**: `self.story_characters` -
  список объектов. Отдельный `CTkOptionMenu` (все пресеты персонажей) +
  «Добавить» (`_add_story_character`, дубли по `id` игнорируются) +
  список добавленных с кнопками `✕` (`_render_story_characters` /
  `_remove_story_character`). В `dialogue` персонаж один - через обычный
  селектор `self.active["character"]`.
- **Поля деталей** - НЕ пресеты, не сохраняются между сессиями, читаются
  в `_on_send`:
  - `story`: **«Размер истории»** - `CTkOptionMenu` `self.story_size_menu`
    / `self.story_size_var` из `STORY_SIZE_CHOICES()` (6 пунктов: `«—»` +
    5 готовых, локализованных; `dynamic_resizing=False`, чтобы ширина
    панели не ехала). Раньше было 9 готовых пунктов, часть - размытые
    словесные без цифры («объёмная новелла», «многосценовая история»),
    которым модель следовала ненадёжно; сократили до 5, у КАЖДОГО - чёткий
    диапазон абзацев и явное требование дойти до финала (`_STORY_SIZE_RU`/
    `_STORY_SIZE_EN` в `i18n.py`). Самый большой пункт раньше был «без
    ограничений по длине» - открытый лимит эмпирически провоцировал
    зацикливание (см. анти-зацикливание ниже: без ориентира по объёму
    модель не понимает, когда останавливаться); теперь верхняя граница
    названа прямо (~80-120 абзацев) и добавлено явное «не повторяйся».
    Хелпер `_story_size_value()` → `""` для `«—»`, иначе текст пункта.
    Меню - в `_preset_panel`. Плюс `self.story_details_box`
    (`CTkTextbox` `height=164` в `_details_host`, прижат вниз). Оба →
    `build_system_prompt(story_size=..., story_details=...)`;
  - `dialogue`: `self.dialogue_details_box` (`CTkTextbox` `height=164` в
    `_details_host`) → `build_system_prompt(extra_details=...)` (блок
    «## Дополнительные детали»). Каждый режим - своё поле в общей ячейке
    `_details_host`, значения между режимами не переносятся.
- **Главный герой (Вы)** - блок `protagonist`, модель его НЕ отыгрывает;
  нужен, чтобы персонажи/рассказ знали, с кем имеют дело. Форма - 4 поля
  (Имя / Биография / Внешность / Характер).
- **Порядок полей в формах персонажа и героя**: Имя → **Биография →
  Внешность → Характер** → остальное (у персонажа - Манера речи,
  Типичные фразы). Задаётся в `BLOCK_SPECS[...]["fields"]`; тот же
  порядок повторён в `_character_block` / `_protagonist_block` промпта.
  - **`typical_phrases`** (`models.Character`, было `first_message` -
    неиспользуемое поле «первая реплика», переименовано и реально
    подключено к промпту; `from_dict` мигрирует старое значение
    `first_message`, если новое поле пусто). Многострочное - по одной
    характерной реплике персонажа в строке. `prompt_builder.
    _typical_phrases_list()` режет по `\n`, отбрасывает пустые строки;
    `_character_block` при непустом списке добавляет в блок персонажа
    строку `Типичные фразы (ориентир для голоса и стиля речи - НЕ
    повторяй их дословно, придумывай новые реплики в том же духе):
    "фраза1"; "фраза2"…` (англ. вариант аналогично, `lang="en"`). Явный
    запрет дословного повтора - намеренно: иначе модель просто
    подставляет готовую фразу, а это ровно та проблема, для которой
    сделан анти-повтор в `_generate_worker` (см. детектор `DUP_*` /
    `is_duplicate_speech` выше). Пустое поле - блока в промпте нет.
- **Редактирование - только в окне «Настроить»** (`PresetManager` из
  `preset_ui.py`): список пресетов, кнопки Создать / Редактировать /
  Удалить, двойной клик = правка. Сами поля (многострочные `CTkTextbox`
  для длинных текстов, `CTkEntry` для коротких) живут в форме
  `PresetEditDialog`, а не на главном экране. Набор полей берётся из
  `BLOCK_SPECS[block]["fields"]`. Напротив каждого поля (кроме
  имени/названия) - кнопка **«Сгенерировать»**: скрытый запрос к текущей
  модели «придумай это поле» с учётом уже заполненных полей объекта (см.
  `preset_ui.py` выше).
- **Связь окна и главного экрана**: `_open_manager` передаёт менеджеру
  колбэк `_after_manager_change(block)`; тот перечитывает список,
  обновляет меню и, если активный пресет удалён/переименован (матч по
  `id`), правит `self.active[block]` и выбранное значение. Для
  `block == "character"` дополнительно чинит `self.story_characters`
  (выкидывает удалённых, подхватывает переименованных). По одному
  открытому `PresetManager` на блок (`self._managers`).
- **Активные пресеты**: `self.active` - dict `block -> объект | None`.
  При старте `_seed_defaults()` создаёт примеры для пустых блоков,
  `_startup_select()` выбирает первый пресет каждого блока (и кладёт
  первого персонажа в `self.story_characters`). Строка над чатом
  (`self.active_label`) mode-aware: в `dialogue` показывает
  Вы/Персонаж/Локация/Сценарий/Конфигурация, в `story` - Вы/Персонажи
  (списком)/Сценарий/Конфигурация. Обновляется в `_refresh_active_label()`.
- **Имя персонажа/героя** - оно же имя пресета (поле `name` в форме). Для
  Локации/Сценария/Конфига в форме есть отдельное поле «Название пресета»
  (`attr="name"`).
- **Три режима** (`self.mode_value`, переключаются таб-баром `_chat_tabs` -
  см. выше): `dialogue` / `story` / `chat`.
  - `chat` - голый чат для теста параметров модели: `_on_send` -
    отдельная ранняя ветка, `messages = list(self.history)` **без
    system-сообщения**, `structured=False`, `nudge` не применяется,
    `digest_window=0`; `think` (официальный reasoning) прокидывается.
    `_apply_mode_view` для `chat`: в `_preset_panel` только `_chat_note`,
    `_left_tabs.set(self._tab_settings)`, вкладка «Память» скрыта.
- **Поля ввода зависят от режима** (`_apply_input_mode`, вызывается из
  `_build_chat_panel` и `_on_mode_change`; grid/grid_remove):
  - `dialogue` - фрейм `self._dlg_input`: `self.act_box` («Твоё
    действие») + `self.reply_box` («Твоя реплика», только речь).
    `_read_input()` / `_clear_input()`. Отправка при непустом хотя бы
    одном. Реплика юзера уходит в `history` каноничным
    `*<действие>*\n<речь>`.
  - **Курсив для действий**: `CTkTextbox.tag_config` запрещает `font=`,
    поэтому тег `action` (курсив + `#9aa4b0`) ставится на внутренний
    `self.chat_box._textbox` напрямую. Успех → `self._action_tag =
    "action"`; если не вышло → `None`, и `_action_piece()` оборачивает
    действие в `*…*`. И юзер, и персонаж рендерятся через `_action_piece`.
  - **Отступы в чате**: 1 пустая строка между действием и речью одного
    хода; 2 пустые строки между ходом юзера и ходом персонажа
    (`reply_sep = "\n\n"` для dialogue, `""` для story - передаётся в
    `_generate_worker`).
  - `story` - фрейм `self._story_input`: одно свободное поле
    `self.story_input` («Указания / правки»). `_on_send` story:
    непустое поле → его текст = user-сообщение (и `[Указание: ...]` в
    чат); пусто + пустая история → `"Напиши историю."`; пусто +
    непустая история → `"Продолжай историю."`. История **НЕ обнуляется**
    (можно остановить и подправить ход); «Очистить» = новая история.
  - **«Продолжить историю» - пересказ перед продолжением** (кнопка
    `send_btn` в story меняет текст: `_update_send_btn_label()` -
    `t("continue_story_btn")`, пока `self.history` непусто, иначе
    `t("generate_story")`; вызывается из `_on_mode_change`,
    `_commit()` story-ветки, `_on_clear`/`_on_clear_all`,
    `__COMPRESS_DONE__`). Раньше при каждом «Продолжить» в контекст
    уходила ВСЯ сырая история целиком (`digest_window` в story всегда 0) -
    на длинной «максимально подробной» истории контекст быстро
    переполнялся. Теперь, как только есть непересказанные ходы СТАРШЕ
    последних `STORY_RECAP_KEEP_RAW_TURNS` (см. ниже), `_on_send` СНАЧАЛА
    запускает `_start_story_recap(model, inf)` и выходит - сама генерация
    откладывается до готовности пересказа.
    - Механика - как у бегущей памяти диалога, но по кнопке, а не каждые
      N ходов: `self.story_recap` (строка) / `self.story_recap_upto`
      (сколько записей `self.history` уже учтено) - НЕЗАВИСИМЫ от
      `mem_head`/`mem_segments`/`digested_upto` диалога (те бы конфликтовали,
      если бы `self.history` использовался и там, и там).
    - **`STORY_RECAP_KEEP_RAW_TURNS=1`: последний ход НИКОГДА не
      пересказывается, шлётся дословно.** Найдено на реальном экспорте:
      первая версия пересказывала ВСЁ без остатка (`fold_to = len(history)`
      каждый раз) - модель на продолжении видела ТОЛЬКО сухую 4-8-
      предложную сводку и ни одного реального слова из только что
      написанного. На практике это выглядело как «начинает заново»:
      без точного места обрыва, стиля и темпа последней сцены модель
      просто заново разыгрывала завязку. Фикс - `_on_send`'s триггер и
      `_start_story_recap` считают `fold_to = max(start_idx, len(history) -
      STORY_RECAP_KEEP_RAW_TURNS*2)` вместо `len(history)`: пересказывается
      всё СТАРШЕ последнего хода, а сам последний ход остаётся в
      `hist[story_recap_upto:]` и уходит в запрос как есть - у модели
      всегда есть точный текст, с которого продолжать. Дополнительно
      `continue_story` (i18n) усилен с голого «Продолжай историю.» до
      явного требования двигать сюжет вперёд, не пересказывая и не
      повторяя уже написанные сцены/реплики/обороты - решает вторую
      половину жалобы («мало развития», топтание на месте).
    - `_start_story_recap`: берёт `self.history[story_recap_upto:fold_to]`
      (см. `STORY_RECAP_KEEP_RAW_TURNS` выше - последний ход в этот срез
      не попадает), режет на куски бюджетом
      `int(num_ctx * STORY_RECAP_CHUNK_FRACTION)`
      токенов. Сначала `_split_oversized_entries()` - если ОДИН ход сам по
      себе больше бюджета (обычный случай в story - один ассистентский ход
      может быть на 120 абзацев), режет его текст на части (`_text_chunks`),
      каждая - своя псевдо-запись той же роли; иначе `_size_chunks` клала
      бы гигантский ход целиком в один кусок, который сам мог не влезть в
      контекст скрытого запроса (найдено и исправлено на реальном тесте -
      57 КБ в одном ходе давало 1 запрос на все 57 КБ, после фикса - 8
      запросов по ≤8К символов).
    - `_story_recap_worker` (фоновый поток): сворачивает куски
      ПОСЛЕДОВАТЕЛЬНО через `build_segment_summary_messages(recap, chunk)`
      - тот же принцип, что у `_fold_segment` диалога («уже известно» -
      не повторять, сжать только новое), только без списка сегментов -
      сразу копится в одну строку. Если после этого `estimate_tokens` для
      пересказа превышает `STORY_RECAP_CONSOLIDATE_TOKENS` - один финальный
      `build_consolidation_messages("", [recap])`, чтобы пересказ не рос
      без предела за много «Продолжить» подряд. Неудачный кусок →
      truncated сырой текст (как в «Сжать пример»), чтобы не терять события
      совсем. `("__STORY_RECAP_PROGRESS__", i, n)` → статус `st_story_recap`.
      `upto` в финальном `("__STORY_RECAP_DONE__", recap, upto, stopped)`
      считается как `start_idx + done_entries` - ТОЛЬКО реально
      обработанные куски, чтобы «Стоп» на середине не потерял хвост молча.
    - `_poll_queue`'s `__STORY_RECAP_DONE__`: `recap is None` (сетевая
      ошибка) → предупреждение, ничего не двигаем; `not recap.strip() and
      stopped` (остановили ДО первого куска) → «отменено», тоже не
      двигаем; иначе сохраняет `story_recap`/`story_recap_upto` - и если
      `stopped` - ОСТАНАВЛИВАЕТСЯ на этом (специально НЕ `self.after(60,
      self._on_send)` - иначе «Стоп» ничего бы не стопал), если нет -
      `self.after(60, self._on_send)` продолжает во вторую фазу.
    - Вторая фаза (`_build_recent` story-ветка, когда `self.story_recap`
      непусто): system-промпт получает `memory_header(lang) +
      self.story_recap` (тот же заголовок, что у диалоговой памяти - он
      достаточно общий), а «хвост истории» = `hist[self.story_recap_upto:]`
      - содержит и последний СЫРОЙ ход (за счёт `STORY_RECAP_KEEP_RAW_TURNS`
      - именно он даёт модели точный текст, с которого продолжать), и
      только что закоммиченный `pending_user` («Продолжай историю…» или
      текст указания), который пересказ ещё не видел. `self.history` при
      этом остаётся ПОЛНЫМ (для чата/экспорта) -
      пересказ используется только при СБОРКЕ запроса, ничего не подменяет.
    - `_reset_story_recap()` (→ `""`/`0`): «Очистить», «Очистить всё»,
      и когда «Сжать пример» ПОЛНОСТЬЮ заменяет `self.history` (старый
      пересказ ей больше не соответствует - пересоберётся заново по
      требованию на следующем «Продолжить»).
  - `chat` - фрейм `self._chat_input`: одно поле `self.chat_msg_box`
    («Сообщение»). Отправка при непустом; история накапливается
    (многоходовость), «Очистить» сбрасывает.
  - `Ctrl+Enter` шлёт из любого поля.
  - **Раскладка `form`**: колонка 0 - фрейм ввода режима (`sticky="nsew"`,
    у нижнего поля `grid_rowconfigure(<row>, weight=1)` + `height=48` как
    минимум), колонка 1 - `btns` (`grid(sticky="n", pady=(28, 0))`).
    Высоту row 0 задаёт колонка кнопок (она выше), поле ввода растягивается
    до неё → **низ нижнего поля совпадает с низом «Экспорт…»**, а верх
    «Отправить» - с верхом первого поля. Подсказка `Ctrl+Enter`
    (`_dlg_hint` / `_story_hint` / `_chat_hint`, свой текст на режим) -
    `form` row 1, `columnspan=2`, под обеими колонками; переключается в
    `_apply_input_mode` вместе с фреймом ввода.
  - **Колонка кнопок** (`btns`): Отправить / Стоп / Очистить /
    Очистить всё / Экспорт….
- **Три подсказки в один ряд по низу `body`** - под каждой из трёх колонок
  своя серая строка, все заканчиваются на одной линии (все три панели в
  `body` row 0 `sticky="nsew"`, у каждой подсказка - последний ряд внутри
  своей колонки, `pady` подобраны так, что низ совпадает):
  - левая: `_left_hint` (row 3 таба «Сцена», ВНЕ скролла, на сером фоне) -
    «`«—»` — блок не участвует»; в `chat` скрыта. Раньше был `panel_hint`
    внутри `_preset_panel` - вынесен, чтобы не уезжал при скролле.
  - центр: `_dlg_hint` / `_story_hint` / `_chat_hint` (`form` row 1).
  - правая: своя серая подпись в конце каждой вкладки `_right_tabs`
    (row 2): Logs → «Дословные запросы к модели и её полные ответы — как
    есть, без правок.», Память → «Сжатая «память» прошлых событий — раз в
    N ходов собирается скрытым запросом.». `pady=(3, 2)`, как у `_left_hint`
    (обе - в таб-фреймах `CTkTabview` -> низ совпадает).
  Низ полей «Доп. детали» / `reply_box` / `story_input` / `chat_msg_box`
  совпадает с низом `logs_box`/`memory_box` (проверено: diff 0).
- **`structured_dialogue`** (галка в Settings, дефолт вкл через
  `OPTIMAL_INFERENCE`; только `mode=="dialogue"`): `_on_send` собирает
  `structured`, глушит `nudge` (несовместимо с `format:json`), шлёт
  `response_format=STRUCTURED_DIALOGUE_SCHEMA` и
  `strip_inline_think=False`. `_generate_worker` в этом режиме **не**
  стримит чанки в чат (копит `buffer`), в `finally` парсит
  `parse_structured_reply(full_reply)` → кладёт в `history` каноничное
  `*action*\nspeech`, а в `token_queue` - кортежи `(text, tag)`:
  `(action, "action")` + `(speech, None)`. `_poll_queue` распаковывает
  кортеж в `_append_chat(text, tag)`. Битый JSON → весь текст как речь.
  Сырой JSON виден в Logs (`ОТВЕТ`).
  - **Анти-повтор реплики** (`DUP_RATIO=0.86` / `DUP_WINDOW=8` /
    `DUP_MIN_LEN=24` / `DUP_MAX_RETRIES=2` в `gui.py`; чистая логика -
    `prompt_builder.is_duplicate_speech(speech, history, …)` +
    `speech_of` / `norm_line`, покрыты `test_is_duplicate_speech`).
    Штрафы Ollama применяются ко всему ответу, но `repeat_last_n=64` не
    видит фразу с хода 2-3 назад, и модель повторяет РЕЧЬ (действие при
    этом разное). `_generate_worker` в structured-режиме - цикл: после
    парсинга сверяет речевую часть (`difflib.SequenceMatcher.ratio ≥
    DUP_RATIO`) с последними `DUP_WINDOW` репликами `assistant`; если
    похоже - до `DUP_MAX_RETRIES` раз перегенерирует, поднимая
    `repeat_last_n→≥512`, `temperature += 0.15` (кап 1.2), новый
    `seed`, и добавляя эфемерную (не в `history`) реплику-нудж
    `retry_dup_nudge`. Маркер `("__RETRY_DUP__", i, n)` → `_poll_queue`
    двигает ТОЛЬКО статус `st_retry_dup` - в чат/`history` НИЧЕГО не
    пишем (текстовая пометка внутри реплики персонажа ломает
    иммерсивность; статус проходящий, но заметный, пока идёт перегенерация).
    Если и после лимита похоже - оставляем последний вариант как есть, а
    само событие остаётся ТОЛЬКО в Logs: `log_retry_dup_gaveup` (заголовок
    КАПСОМ) в момент обнаружения (не в финализации - там уже поздно
    что-то показать в статусе, __DONE__ сразу же его сотрёт). Короткие
    реплики (< `DUP_MIN_LEN`) не проверяются. Память пересобирается на
    `base_options` (без анти-повтор правок). Не-structured (живой стрим)
    не трогаем.
- **Фото персонажей и героев: три вида (аватар / галерея / эмотиконы)** -
  у `Character` и `Protagonist` (`blocks.BLOCK_SPECS[...]["photo"]`, в `fields`
  их нет) три необязательных поля, все хранят ИМЕНА файлов (не пути; старые
  записи - пустые): `photo: str` (АВАТАР), `gallery: list[str]` (ГАЛЕРЕЯ),
  `emotes: list[str]` (ЭМОТИКОНЫ); `_str_list()` в `from_dict` отбрасывает
  мусор. Включаются тремя bool в `InferenceConfig` (Settings, не в `options`):
  `show_avatars` (дефолт вкл), `show_gallery` (вкл), `show_emotes` (ВЫКЛ,
  экспериментально) + `emotes_mode` (`"all"`/`"companion"`/`"hidden"` - режим кнопки вверху,
  запоминается; старый bool `emotes_hidden: true` читается как `"hidden"`,
  мусор -> `"all"`; `models.EMOTES_MODES` = порядок переключения).
  Миграция: старые ключи `show_photos` -> `show_avatars`, `photo_overlay` ->
  `show_emotes`; нет ключа/мусор -> дефолт. В промпт модели фото НЕ попадают.
  - `photos.py` (Pillow, без tkinter; `photos.AVAILABLE`): `import_photo`
    (копия в `photo_<id>.png`, длинная сторона <= `MAX_SIDE`=1024, EXIF-поворот,
    оригинал не трогаем), `make_avatar(path, size, gap)` (круг + `gap`
    прозрачных px справа), `load_rgba`, `to_tk`, `cleanup_unused`, `photo_file`
    (из папки не выпускает). **Эмотиконы** - `check_emote` (проверка по
    СОДЕРЖИМОМУ, не по расширению: формат PNG, есть альфа - в т.ч. палитровый
    с transparency, и прозрачных пикселей (alpha < `EMOTE_ALPHA_THRESHOLD`=32)
    >= `EMOTE_MIN_TRANSPARENT`=5 %), иначе `EmoteError(code)` с
    `code in {not_png, no_alpha, not_transparent}` (подкласс `PhotoError`);
    `import_emote` = проверка + `import_photo(max_side=EMOTE_MAX_SIDE=1600)`.
  - Хранение: `PresetStore.photos_dir`, `import_photo`, `import_emote`,
    `photo_path`, `cleanup_photos()` - после `upsert_*`/`delete_*` персонажа
    и героя удаляет `photo_*.png`, на которые не ссылается НИ `photo`, НИ
    элементы `gallery`/`emotes` (чужие файлы не трогает). Поэтому форма
    импортирует сразу при выборе; НЕ чистим в `_close()` формы (пресет ещё не
    записан).
  - Форма пресета (`preset_ui.PresetEditDialog(store=...)`): аватар (превью
    96 px, «Выбрать/Заменить», «Убрать») + две секции `_PhotoListSection`
    (галерея, эмотиконы): ряд превью с «x», кнопка добавления с выбором
    НЕСКОЛЬКИХ файлов; для эмотиконов `png_only=True` (фильтр `*.png`), каждая
    `EmoteError` -> строка в одном `messagebox.showwarning` (`emote_err_<code>`;
    остальные файлы пакета добавляются, это отмечено в футере). Старое
    `CTkImage` держим, пока метка не переключена (иначе `TclError: image
    "pyimageN" doesn't exist`).
  - **АВАТАР в чате без поломки верстки.** Обычный СИМВОЛ-картинка в начале
    хода (`Text.image_create`), не окно: поля абзаца - теги `hang1`
    (`lmargin1=0`, `lmargin2=W`) и `hang` (оба `W`), `W = avatar_px + gap`;
    `_retag_turn` ставит их на весь ход от метки `turn_start`. `avatar_px =
    linespace * AVATAR_LINES (2.4)`. Ход героя - `_commit()`; ход персонажа -
    воркер кладёт `("__TURN__", файл)` после `reply_sep` (стрим - при первом
    чанке, structured - в финализации), `__DONE__` зовёт `_end_turn()`.
    Имена берутся в `_on_send` один раз. `__TRIM__` удаляет только текст
    попытки. Смена языка: `_snapshot_ui` хранит `Text.dump`, `_replay_chat`
    воспроизводит его (суффикс `#k` у `pyimageN#k` отрезается перед поиском в
    `_chat_images`).
  - **ГАЛЕРЕЯ во вкладках «Фото» (только диалог).** Слева -
    `active["protagonist"].gallery`, справа - `active["character"].gallery`
    (`_SIDES`, `_build_photo_tab`, `_photo_panels[block]`: метка-картинка,
    подпись, кнопки `‹`/`›`). Всё через `place()` (размер картинки не
    влияет на геометрию колонок); картинка прижата к ВЕРХУ панели (`anchor=n`),
    чтобы не заезжать на подпись и стрелки, текстовая заглушка
    (`photo_panel_none`/`photo_panel_empty`) - по центру. Вписывание
    `min(w/iw, h/ih, 1.5)` с учётом `_get_widget_scaling`; перерисовка по
    `<Configure>` через `_schedule_photo_panel` (debounce 40 мс), одинаковый
    кадр `(файл, size)` не пересоздаётся. Листание: `_gallery_step` по кругу,
    `_gallery_idx[block]`; при смене владельца (`_gallery_owner[block]` =
    id пресета) - с первого; стрелки и счётчик (`gallery_counter`) только если
    фото > 1. Прозрачный PNG сливается с панелью (CTkImage + `fg_color=
    "transparent"`).
  - Видимость вкладок - `_sync_side_tabs()`: «Фото» и «Память» только в
    `dialogue`; кнопка «Фото» `disabled`, если выключена `show_gallery` или
    нет Pillow (`_gallery_on`). `configure(values=...)` пересоздаёт кнопки,
    поэтому состояние выставляется заново. Зовётся из `_apply_mode_view`,
    `command` галок `show_gallery`/`show_emotes`, конца
    `_load_inference_into_widgets`, пересборки окна. **Грабли
    `CTkTabview.set()`**: через 100 мс он «забывает» все вкладки, кроме
    названной; два `set()` подряд гасили показанную. Решение: `_set_tab()`
    (через 110 мс заново выкладывает текущую вкладку: `_set_grid_current_tab`)
    и по одному `set()` на панель в `_restore_ui`. Вкладки «Фото» сохраняются
    в `_snapshot_ui` (`left_photo`/`right_photo`).
  - **ЭМОТИКОНЫ поверх интерфейса (ЭКСПЕРИМЕНТ).** Они НЕ привязаны к
    вкладкам (вкладки «Фото» - только галерея); окна живут независимо.
    - **`overlay.py`** (Windows, ctypes; иначе `AVAILABLE=False`, модуль
      безопасно импортируется). `PhotoOverlay` - Win32-окно: `tk.Toplevel`
      (overrideredirect) + `WS_EX_LAYERED|TRANSPARENT|TOOLWINDOW|NOACTIVATE`,
      владелец - главное окно (`GWLP_HWNDPARENT`: над ним, но под чужими
      программами, сворачивается с ним). Кадр: `RGBA -> RGBa -> tobytes("raw",
      "BGRa")` (предумноженная альфа) в DIB и `UpdateLayeredWindow(ULW_ALPHA)`.
      Клики проходят сквозь. Явные `argtypes/restype`. Не использовать Tk
      `-alpha`. `monitor_bounds(widget)` - границы МОНИТОРА окна приложения
      (`MonitorFromWindow` + `GetMonitorInfoW`), не Windows -> размеры экрана Tk.
    - **Раскладка** (`gui._overlay_place(side)`): `side` left=героя
      (`_left_col`), right=собеседника (`_right_col`). Низ = `monitor_bounds()[3]`
      (низ экрана, общая линия для обоих); масштаб `min((col_w-20)/iw,
      (mon_bottom - окно.root_y)/ih, EMOTE_MAX_UP=1.25)`; `x` - по центру
      колонки, `y = mon_bottom - th`. Выходят за рамки приложения по низу;
      чат по горизонтали не перекрывают (ширина ограничена колонкой), а
      подбор пропорций картинок - на пользователе. Скрыты, если эмотиконов у
      пресета нет / колонка свёрнута / окно свёрнуто / не диалог.
    - **Смена на каждый ответ**: `_emote_idx[block]`, `_emote_advance(block)`
      (циклит только если эмотиконов > 1, потом `_overlay_place`). Герой -
      в `_commit()` (его реплика), собеседник - на маркере воркера
      `__TURN__` (тот же `reply_sep`-момент, что и аватарка; в диалоге маркер
      теперь шлётся всегда, даже с пустым именем аватара). Вручную не
      переключаются, к событиям не привязаны.
    - **Три режима**: кнопка `_emote_btn` в верхней панели (видна только
      при `show_emotes` + Windows + диалог), подпись = ТЕКУЩИЙ режим
      (`emotes_mode_<режим>`), клик `_toggle_emotes` циклит все -> только
      собеседник -> скрыты -> все (`_emotes_mode`, сохраняется в
      `emotes_mode`), `_sync_emotes_ui`. `_emotes_on()` = галка +
      `overlay.AVAILABLE` + диалог + режим не `hidden`; в `_overlay_place`
      режим `companion` дополнительно скрывает левую сторону (герой).
    - **Слежение за окном**: `<Configure>`/`<Map>`/`<Unmap>` корня (фильтр
      `e.widget is self`), `_schedule_overlay` (debounce) ->
      `_overlay_reposition`; сворачивание/разворачивание боковых панелей тоже
      зовёт его. Пересборка под язык прячет окна, возвращает
      `_sync_side_tabs`; `_on_close` уничтожает окна.
    - Проверено на живом окне 1920x1080 (пробы + скриншоты): дефолты, галерея
      (стрелки по кругу, подпись, смена пресета, нет галереи), низ обоих
      окон == низ экрана, ширина в колонке, чат не перекрыт, под эмотиконом
      доступны вкладки, смена на ответ (3 эмотикона / 1 не меняется), маркер
      воркера, скрыть/показать + сохранение, перемещение окна, сворачивание,
      клик сквозь, story/dialogue, выкл каждой галки по отдельности,
      смена языка, нет эмотиконов у героя. Тесты:
      `test_photo_field_roundtrip_and_backcompat`,
      `test_photos_import_avatar_and_cleanup`, `test_store_photo_lifecycle`,
      `test_emote_validation_png_transparent_only`,
      `test_photo_overlay_setting_and_frame`. Остаточный риск (поэтому
      «Экспериментально»): z-order на нестандартных конфигурациях (несколько
      мониторов с разным DPI) не проверялся.
  - Сборка: `pillow` в `requirements.txt`, `hiddenimports=
    ['PIL._tkinter_finder']` в `OllamaRP.spec` (exe нужно пересобрать).
- **Сохранённые диалоги (сессии).** Кнопка `sessions_btn` «Сохранения…»
  (колонка кнопок чата, под «Экспорт…», отключается на время генерации) ->
  `sessions_ui.SessionsDialog` (имя + «Сохранить как новое», список карточек
  «Загрузить / Перезаписать / Удалить»; про состояние приложения ничего не
  знает - только колбэки `save_cb(name, id|None)` / `load_cb(id)`).
  - `sessions.py` (чистая логика, без tkinter): `SessionStore(data_dir)` ->
    `<данные>/sessions/<id>.json` (id = hex 6-32, проверяется `_ID_RE` - из
    папки не выйти). Файл `{version, id, name, created_at, saved_at, data}`.
    `save(data, name, id=None)` (id есть - перезапись, `created_at`
    сохраняется), `list()` (метаданные, свежие первыми; битый/чужой файл
    пропускается), `load(id)`, `delete(id)`. Запись атомарная
    (`.json.tmp` + `os.replace`). Версия файла новее `SESSION_VERSION` ->
    `SessionError`.
  - Что в снимке (`App._session_snapshot`): `mode`, `model`, `history`,
    `mem_head`/`mem_segments`/`digested_upto`, `story_recap`/
    `story_recap_upto`, `chat` (сегменты `{"t", "tags"}` и `{"img": имя
    файла фото}` - из `Text.dump`; имя картинки Tk -> файл берётся обратным
    поиском по `_avatar_cache`), `scene` (полные `to_dict()` пресетов всех
    блоков), `story_characters`, `story_size`, `dialogue_details`/
    `story_details`, `draft` (act/reply/story/chat - недописанный ввод). НЕ
    входят Logs, Settings, эмотиконы/галерея.
  - Загрузка (`_session_apply`): пресеты - `_restore_preset`: есть в
    хранилище по id -> берём ТЕКУЩУЮ версию (правки после сохранения не
    теряются); нет, но есть пресет с тем же ИМЕНЕМ -> он (хранилище склеивает
    по имени в `_upsert`, возврат удалённого поверх чужого затёр бы данные);
    иначе возвращаем из снимка в хранилище и сообщаем. Индексы
    `digested_upto`/`story_recap_upto` зажимаются в `[0, len(history)]`,
    записи истории фильтруются по роли/типу, `_history_backup`/
    `_details_backup`/`_just_compressed` сбрасываются, чат грузится
    `_load_chat_segments` (аватарка с пропавшим фото просто не рисуется).
    Модели нет в списке -> остаётся текущая (+ сообщение). Перед заменой
    непустого диалога - `askyesno`. Сохранение пустого диалога отклоняется.
  - Проверено на живом окне: чат побайтно (текст, курсив, аватарки,
    сегменты), память, история, режим, модель, детали, черновик, возврат
    удалённого пресета (и не-перезапись одноимённого), перезапись,
    битый файл, блокировка при генерации, смена языка. Тест:
    `test_session_store_roundtrip_and_robustness`. Идея на потом:
    автосохранение при выходе / «продолжить последний» при старте.
- **Динамическая память персонажа-собеседника.** `Character.dyn_enabled`
  (bool, дефолт False) и `dyn_memory` (str) - в самом пресете (`from_dict`:
  не-bool/не-str -> дефолт; `BLOCK_SPECS["character"]["dynamic_memory"]=True`
  включает секцию формы, у героя её нет). Включается галкой в форме персонажа
  (НЕ в Settings).
  - `dynamic_memory.py` (чистая логика): `build_messages(char, protagonist,
    current, new_events, limit, lang)` (RU/EN; в системном промпте лимит и
    маркер `НЕТ_ИЗМЕНЕНИЙ`/`NO_CHANGES`), `interpret_reply(reply, current)` ->
    `("fail"|"same"|"changed", text)`, `fit_to_limit` (при переполнении
    выбрасываются самые СТАРЫЕ строки, одна длинная строка - по границе слова
    с «…»). Предел - настройка `InferenceConfig.dyn_memory_limit` (Settings, int;
    `dyn_limit()`: пусто/мусор/bool -> дефолт `DYN_MEMORY_LIMIT=4000`, иначе
    зажим в `DYN_LIMIT_MIN..MAX` = 500..20000 через `clamp_limit`; не в
    `options`); из UI-потока кладётся в `App._dyn_limit` при `_on_send` и
    `_dyn_flush_start` (воркер к виджетам не обращается) и идёт и в промпт
    запроса, и в `interpret_reply`. Остальные константы: `DYN_NEW_MAX_ITEMS=8`,
    защита от «усыхания» (`SHRINK_GUARD_*`: новый текст < 40 % от текущего,
    когда текущий > 600 символов и < 90 % лимита, считается испорченным
    ответом -> "same"). "fail" (пусто/ошибка сети) - события остаются на
    повтор; "same"/"changed" - очередь сводок очищается.
  - Вход запроса - ТОЛЬКО новые сводки памяти диалога (`App.dyn_new`,
    пополняется в `_fold_segment(..., dyn=True)`: только реальные сводки, не
    заглушки; «Пересобрать память» зовёт с `dyn=False`) + текущая динамическая
    память -> размер входа от длины диалога не зависит. `_reset_memory()`
    очищает `dyn_new`.
  - Промпт: `_character_block` добавляет «Динамическая память (...)» ТОЛЬКО
    при `dyn_enabled` и непустом тексте (RU/EN).
  - **Когда обновляется** (`_dyn_update`, скрытый запрос `_run_hidden`):
    в конце `_generate_worker`, если `got_reply`, не `stopped`, `dyn_char`
    (= `_dyn_char(inf)`: диалог + галка + `digest_window > 0`) и `dyn_new`
    не пуст - И `folded` False (`_maybe_update_digest` теперь возвращает, была
    ли сборка памяти диалога). То есть динамическая память идёт на ход ПОЗЖЕ
    сборки памяти диалога: два скрытых запроса подряд не запускаются.
  - **Единственное исключение - сохранение диалога** (`_session_save`): если
    `_dyn_flush_needed()` (есть необработанные сводки или не свёрнутый хвост),
    `askyesnocancel`: Да -> `_dyn_flush_start` / `_dyn_flush_worker`: сводка
    хвоста истории (`digested_upto` -> конец, сегментами по N ходов) и сразу
    `_dyn_update`, затем `__DYN_FLUSH_DONE__` -> колбэк `_session_save_done`
    -> `_session_save_now` (окно сохранений перерисовывается); Нет -> сохранить
    как есть; Отмена -> выйти. Побочный эффект: после дособирания
    `digested_upto == len(history)`, т.е. следующий запрос получит только
    память + новую реплику (то же происходит на любом N-ходовом рубеже).
    Ошибка динамического запроса не отменяет сохранение (пометка в сообщении).
    Во время дособирания `_rebuilding=True`, кнопки отправки/очистки/
    сохранений отключены.
  - Запись результата - в ГЛАВНОМ потоке: воркер кладёт `("__DYN_MEMORY__",
    id, text)`, `_apply_dyn_memory` обновляет активный объект и персонажей
    story и в хранилище меняет ТОЛЬКО поле `dyn_memory` сохранённого пресета
    (правки пресета, сделанные в форме, не затираются). Форма пресета, открытая
    во время фонового обновления: `_dyn_text_to_save` - если текст в поле не
    трогали, берётся самое свежее из хранилища, иначе (правка/«Очистить») -
    то, что в поле. «Очистить динамическую память» очищает поле и применяется
    по «Сохранить».
  - Снимок сессии содержит `dyn_new`; `dyn_memory` едет с пресетом (при
    загрузке сессии - текущая версия пресета, либо из снимка, если удалён).
  - Только диалог: в story память персонажей в промпт попадает (общий
    `_character_block`), но не обновляется (там нет бегущей памяти диалога).
  - Проверено пробой с подменой `chat_stream` (скрипт-«модель»): порядок
    запросов (ход рубежа: chat+seg; следующий: chat+dyn - никогда подряд),
    запись в хранилище и активный объект, имена/лимит/сводки во входе,
    попадание в промпт, «НЕТ_ИЗМЕНЕНИЙ», лимит (3996 <= 4000, свежие пункты
    целы), защита от усыхания, пустой ответ (сводки остаются), выкл у
    персонажа (запросов и текста в промпте нет), форма (фоновое обновление не
    затёрто, ручная правка, «Очистить» + галка), сохранение Отмена/Нет/Да
    (порядок `seg -> cons -> dyn`, хвост свёрнут, снимок), вопрос не
    задаётся при выкл, «Очистить всё». Тесты:
    `test_dynamic_memory_field_and_prompt`, `test_dynamic_memory_logic`,
    `test_dyn_memory_limit_setting`.
- **Устойчивость к плохим данным и сбоям (полный аудит).** Найдено и закрыто:
  - `storage`: JSON пресетов/настроек читается с `utf-8-sig` (BOM), повреждённый
    или не-список файл откладывается как `<имя>.corrupt-<время>` (`_quarantine`)
    и загрузка даёт пустой результат/дефолты, а не падение при старте;
    записи не-словари пропускаются; запись атомарная (`.tmp` + `os.replace`).
  - `models.from_dict` (`_s`, `_id`): нестроковые поля -> строки/`""`
    (иначе `.strip()` в промпте падал), запись без `id` получает новый (иначе у
    всех совпадало `""` и `upsert` затирал их друг друга); `stop`/`keep_alive`/
    `digest_prompt` в настройках - только строки.
  - `ollama_client`: строка `{"error": ...}` посреди потока (модель упала при
    HTTP 200) -> `OllamaError` (раньше обрыв выглядел как законченный ответ,
    `parse_stream_error`); разбор строк стрима/`list_models`/
    `model_capabilities` переживает не-объекты и неверные типы;
    `parse_structured_reply` разбирает ОБОРВАННЫЙ JSON (`_partial_json_fields`:
    обрыв связи, обрезка по `num_predict`) - в чат/историю идёт то, что успело
    прийти, а не сырой `{"action": ...`.
  - `gui._poll_queue`: исключение при обработке элемента очереди раньше
    навсегда останавливало опрос (интерфейс «замирал»); теперь тик обёрнут,
    ошибка пишется в Logs (`INTERNAL ERROR`), опрос продолжается. Подряд идущие
    токены стрима склеиваются в одну вставку + один `see("end")` за тик
    (Tk-Text на длинном абзаце пересчитывает перенос при каждой вставке).
  - `sessions.normalize_snapshot` (чистая): любой JSON -> снимок с гарантированными
    типами и зажатыми индексами; `_session_apply` применяет только его (раньше
    искажённое поле роняло загрузку на середине). `SessionStore.save`:
    несериализуемое -> `SessionError`.
  - `dynamic_memory.interpret_reply`: `НЕТ_ИЗМЕНЕНИЙ` первой строкой = «без
    изменений» (пояснение после маркера не становится памятью), маркер среди
    текста вырезается.
  - Проверено без находок: ошибки сети/пустой ответ/«Стоп»/stall/мусорный JSON,
    двойной «Отправить», режимы «История»/«Чат», переполнение контекста (все 4
    выбора), зацикливание и дубликаты, пересборка памяти и гонки с кнопками,
    закрытие во время генерации, формы пресетов, экстремальные PNG
    (3x3 ... 1600x1600), удалённые/битые файлы фото, смена языка в разных
    состояниях, первый запуск без Ollama, 1200 записей истории (загрузка
    сохранения ~2 с). Не проверялось: несколько мониторов / масштаб экрана
    выше 100 % для окон эмотиконов, сборка exe.
- **Стартовые примеры (первый запуск / build).** В `blocks.BLOCK_SPECS[...]`
  у каждого блока `"seed"` (русский) и `"seed_en"` (английский: Me / Girl /
  Old town / Sudden encounter / Basic rules). `App._seed_defaults` создаёт ОБА,
  если блок пуст (язык можно сменить потом); `_default_preset` при английском
  интерфейсе выбирает английский пример активным (и для story-персонажей).
  Существующим пользователям (блок не пуст) ничего не добавляется. Пресеты
  пользователя в exe не входят - только эти примеры. Тест:
  `test_default_seed_presets_ru_and_en`.
- **Таймаут «модель молчит» (`stall_timeout`)** - ответ уже пошёл
  (чаще всего завис на этапе «размышляет»: статус `st_think`, токены
  перестали приходить), но Ollama молчит. Раньше оставалось только вручную
  нажимать «Стоп» и слать запрос заново (а «Стоп» при полной тишине вообще
  срабатывал лишь по 120-секундному таймауту чтения).
  - Настройка `InferenceConfig.stall_timeout` (Settings, внизу; секунды):
    дефолт `STALL_TIMEOUT_DEFAULT = 30`, пусто/мусор/нет ключа в старом
    settings.json -> 30, `0` и меньше -> выключено (`stall_seconds()`).
    В `options` для Ollama НЕ уходит (не в `_OPTION_KEYS`) - это поведение
    самого приложения.
  - `ollama_client.chat_stream(stall_timeout=...)`: таймер включается с
    ПЕРВЫХ полученных данных (`_arm_read_timeout` сужает таймаут сокета
    urllib3-ответа с общих 120 с до N с; сокет достаём из
    `resp.raw._connection.sock`, не вышло/фейковый ответ -> молча прежний
    таймаут). Поэтому долгая загрузка модели и обработка длинного промпта ДО
    первого токена не считаются, а пока токены идут (в т.ч. размышления) -
    таймер не срабатывает. Тишина дольше N -> `OllamaStallError`
    (подкласс `OllamaError`, отличается по `_is_read_timeout`). Закрытие
    ответа в `finally` рвёт соединение -> Ollama отменяет генерацию (иначе
    перезапрос встал бы в очередь за зависшим: у неё `NUM_PARALLEL=1`).
  - `_generate_worker(..., stall_timeout)`: `except OllamaStallError` ->
    если не нажат «Стоп» - тот же запрос уходит заново (до
    `STALL_MAX_RETRIES=3`), новый `seed` (фиксированный seed завёл бы в то
    же зависание); успевший просочиться в чат текст откатывается
    `__TRIM__` (как при зацикливании). `reply_sep` теперь отдаётся по флагу
    `sep_pushed`, а не `attempt == 0` - иначе перезапрос задвоил бы
    отступ. Сигнал - как у остальных авто-перезапросов, БЕЗ пометок в тексте:
    статус `st_retry_stall` (`__RETRY_STALL__`) + Logs `log_retry_stall`
    (капсом). Исчерпаны попытки -> `err_inline` в чат (ответа нет вообще,
    это ошибка, а не реплика) + Logs `log_retry_stall_gaveup`.
  - Осознанное ограничение: это «тишина», а не «слишком долго думает».
    Модель, которая бесконечно стримит размышления, под таймер не попадает
    (отличить её от долго думающей нельзя).
  - Тесты: `test_stall_timeout_config`, `test_chat_stream_stall_timeout_real_socket`
    (настоящий локальный HTTP-сервер: фейковому ответу сокет не положен).
- **Анти-зацикливание текста** (обычный live-стрим - `dialogue` без
  раздельного ответа, `story`, `chat`; НЕ трогает structured-режим выше,
  у него своя защита). Деградация длинных генераций (`num_predict=-1`,
  «История без ограничений по длине»): `repeat_last_n=64` не покрывает
  период цикла, и модель зацикливается на одном абзаце или паре абзацев,
  повторяя их десятки раз подряд, пока не оборвут вручную. Константы
  `LOOP_TAIL_CHECK=10` / `LOOP_WINDOW=30` / `LOOP_RATIO=0.85` /
  `LOOP_MIN_BLOCK_LEN=12` / `LOOP_MIN_HITS=3` / `LOOP_MAX_RETRIES=2` в
  `gui.py`; чистая логика - `prompt_builder.find_repeat_loop(text, …)`
  (покрыта `test_find_repeat_loop`).
  - **v1 (заменена) искала строгий период** (последние `p*min_cycles`
    абзацев = `min_cycles` повторов p-абзацного блока, p от 1 до 4) - на
    синтетике работала, но реальный экспорт истории показал промах: модель
    зацикливалась не строгим периодом, а РОТАЦИЕЙ нескольких похожих
    абзацев вперемешку (абзац действия / реплика-1 / нейтральная реплика /
    реплика-2 шли не по кругу, а вразнобой), да ещё через вставленные
    заголовки псевдо-глав `**Заголовок**` и разделители `---`, которые
    сбивали любой фиксированный период - `find_repeat_loop` на всём этом
    тексте возвращал `None`, зацикливание доехало до конца генерации
    нетронутым (~40 абзацев повтора).
  - **v2 (текущая) без предположения о периоде**: делит текст на абзацы по
    любому числу `\n`; для каждого из последних `LOOP_TAIL_CHECK` абзацев
    ищет среди предыдущих `LOOP_WINDOW` абзацев хоть один похожий
    (`ratio ≥ LOOP_RATIO`, без требования к позиции/периоду). Если таких
    абзацев-повторов в хвосте набралось `LOOP_MIN_HITS` и больше - цикл.
    Возвращает текст ДО первого абзаца-повтора в хвосте (то, что
    сохранить). Абзацы короче `LOOP_MIN_BLOCK_LEN` (в т.ч. `---`,
    короткие реплики) не участвуют ни как проверяемые, ни как эталон - не
    путаем разметку/короткий обмен репликами с зацикливанием. На реальном
    файле из репорта при проигрывании нарастающим буфером (как при живом
    стриме) срабатывает уже на середине - а не только в конце.
  - **v2.1 (fine-tune по второму реальному экспорту)** - v2 в проде всё
    равно иногда пропускала повтор. Разобрал экспорт, нашёл ДВЕ отдельные
    причины:
    1. **Порог был впритык.** Деградация в реальности часто идёт не
       точным повтором, а «расползающимся» перефразом (тот же абзац
       слегка другими словами каждый раз) - часть пар не дотягивала до
       `ratio=0.88`, и по инкрементальной прогонке реального текста
       детектор срабатывал буквально на ПОСЛЕДНЕМ абзаце всего ответа
       (задетектировать успевал, а вот скорректировать уже почти нечего -
       генерация и так заканчивалась). Понизил `ratio` 0.88→0.85 и
       `min_hits` 4→3 - на том же файле теперь ловит на ~40 абзацев
       раньше вместо самого последнего.
    2. **Хвостовой абзац вообще не проверялся.** Инкрементальная проверка
       внутри цикла стрима срабатывает только когда в очередном `chunk`
       есть `"\n"` - а последний `chunk` ответа модели почти всегда идёт
       БЕЗ завершающего перевода строки (сообщение просто заканчивается).
       Значит САМЫЙ ПОСЛЕДНИЙ абзац ответа никогда не участвовал в
       проверке - именно там, где деградация чаще всего и оседает
       (хвост). Добавлена финальная подстраховка: сразу после выхода из
       `for chunk in chat_stream(...)` (не важно, естественным концом или
       `break`), если `not structured and loop_kept is None` - ещё раз
       `find_repeat_loop()` уже на ПОЛНОМ `full_reply`. Тест-проба
       (последний `chunk` - дословный повтор БЕЗ `"\n"` в конце,
       имитирует настоящий EOS) подтвердила: без этой правки повтор
       проходил насквозь, с ней - ловится.
  - `_generate_worker`: инкрементальная проверка идёт ПРЯМО ПО ХОДУ
    стрима (не ждём конца ответа) - после каждого чанка с `\n` на
    `"".join(buffer)` текущей попытки; плюс финальная подстраховка выше.
    При обнаружении цикла обрывает `for chunk in chat_stream(...)`
    ранним `break` (генератор закрывается штатно, `finally:
    resp.close()` в `chat_stream` отрабатывает как обычно) - НЕ через
    `stop_event` (иначе это выглядело бы как «Стоп» от пользователя в
    финализации).
  - Визуальный откат: маркер `("__TRIM__", n)` в `token_queue` → `_poll_
    queue` удаляет последние `n` символов из `chat_box`
    (`delete(f"end-{n+1}c", "end-1c")`). `n = len(full_reply)` этой
    попытки - ровно столько сырых чанков она и вывела в чат (не-
    structured пушит каждый chunk как есть), так что откат не может
    задеть чужой текст. Следом вставляется чистый кусок
    (`find_repeat_loop`'s возврат) + `"\n\n"`.
  - Продолжение БЕЗ потери уже сгенерированного: чистый кусок копится в
    `story_prefix` (через попытки), следующая попытка получает
    `orig_messages + [{assistant: story_prefix}, {user:
    retry_loop_nudge}]` - переиспользует ту же механику, что «Продолжай
    историю» в обычном потоке (два новых сообщения поверх исходного
    контекста), а не хрупкий «дописать за модель» трюк. Маркер
    `("__RETRY_LOOP__", i, n)` → `_poll_queue` двигает ТОЛЬКО статус
    `st_retry_loop`; в чат/`history` НИЧЕГО не пишем - та же логика, что
    у анти-повтора реплики выше (заметная пометка прямо в тексте истории
    ломает иммерсивность так же, как в диалоге). До этой правки маркер
    писал ещё и текстовую пометку в чат - убрано по прямому запросу
    пользователя.
  - Если и после `LOOP_MAX_RETRIES` попыток всё ещё цикл - не сохраняем
    повтор ни в чат, ни в `history`: обрезаем по последнему чистому
    месту (`__TRIM__` + чистый кусок) и сдаёмся МОЛЧА для чата - событие
    уходит ТОЛЬКО в Logs (`log_retry_loop_gaveup`, заголовок КАПСОМ),
    залогировано в момент обнаружения (не в финализации - к этому
    моменту __DONE__ уже стёр бы статус). Пользователь может нажать
    «Сгенерировать» ещё раз, чтобы продолжить вручную.
  - Финальный `full_reply` = `story_prefix` (если есть) + текст
    последней попытки, склеенные `"\n\n"` - в `history` уходит ОДНА
    запись, как обычно, без отдельных «доклеенных» ходов.
- **Бегущая память / сжатие контекста** - **только режим `dialogue`**
  (`digest_window` в Settings, дефолт 6 через `OPTIMAL_INFERENCE`;
  `0`/пусто = выкл). В `story` `_on_send` жёстко берёт `digest_window=0`
  (вся история дословно, без дайджеста и `MEMORY_HEADER`), а
  `_apply_mode_view` прячет КНОПКУ вкладки «Память»
  (`_right_tab.configure(values=["Logs"])`, где `_right_tab =
  _right_tabs._segmented_button`; сам фрейм вкладки жив; если был на
  «Память» - `_right_tabs.set("Logs")`).
  - **Послойная схема** (константы `MEM_SEGMENTS_KEEP=3` /
    `MEM_SEGMENTS_MAX=11` / `MEM_MIN_NUM_CTX=8192`):
    - `self.mem_head` - долговременная память (сжимается уплотнением, потом
      не трогается); `self.mem_segments` - недавние сводки-сегменты
      (каждый = ровно N ходов, собран ОДИН раз, повторно не пересобирается);
      `self.chat_digest` - производная строка (`_render_memory()`:
      `mem_head` + сегменты через пустую строку), держится в синхроне -
      её видит окно памяти и подстановка в промпт; `self.digested_upto` -
      сколько записей истории учтено.
  - `_on_send`: если K>0 - дословно шлём только `self.history[
    self.digested_upto:]` (теперь всегда ≤ ~2N ходов); непустой
    `chat_digest` подставляется в конец system-промпта под `memory_header(lang)`.
  - Пересборка **раз в N ходов**: `_maybe_update_digest` считает
    `digest_boundary(len(history), N)`; если рубеж не сдвинулся - выходим.
    Иначе **сразу двигаем `digested_upto = boundary`** (ВСЕГДА, даже при
    сбое запроса - иначе хвост для следующего рубежа рос бы и скрытый
    запрос переставал влезать в контекст: это была причина «поломки
    памяти» на многочасовых сессиях) и по кускам N ходов зовёт
    `_fold_segment`.
  - `_fold_segment(seg, a, b, …)`: скрытый запрос
    `build_segment_summary_messages(known=render, seg, …)` - сжать ТОЛЬКО
    этот сегмент (уже собранная память идёт как контекст «не повторяй»);
    результат (или заглушка `mem_segment_stub` при пустом/ошибке) →
    `mem_segments`. Затем `while len(mem_segments) > MEM_SEGMENTS_KEEP`:
    самая старая сводка вливается в `mem_head`
    (`build_consolidation_messages(mem_head, [overflow])`); при сбое
    уплотнения - break (повтор на следующем рубеже), при переполнении
    `MEM_SEGMENTS_MAX` - грубое склеивание, лишь бы память не росла без
    предела. Вход **обоих** запросов ограничен (голова ~20 предложений +
    пара коротких блоков / N ходов) и от длины диалога не зависит.
  - `_run_hidden(model, msgs, opts, keep_alive, req_title, resp_title)` -
    общий скрытый запрос памяти (temp 0.2 через `_mem_opts`; `num_ctx` =
    `max(user, MEM_MIN_NUM_CTX)`; `stop` убран; `num_predict` 500 для
    сегмента / 900 для уплотнения; `think=False` при capability
    `thinking`, иначе `None` - `<think>` режется/гасится). → строка (м.б.
    пустая) либо `None` при `OllamaError`.
  - **Между рубежами дословно** к запросу добавляются только ходы после
    `digested_upto`.
  - Правый пейн - `CTkTabview` «Logs / Память»: у Logs `logs_box`
    (read-only), у Память `memory_box` (редактируемый) + тулбар
    «Промпт памяти / Пересобрать / Применить».
  - **Экспорт** (`_export_conversation`, кнопка «Экспорт…» в колонке ввода):
  `filedialog.asksaveasfilename` (.txt / .docx) → `_write_txt` /
  `_write_docx` (импорт `docx` внутри, `ImportError` → подсказка про
  `pip install python-docx`). `_export_scene()` - шапка из активных
  пресетов; `_export_turns()` - ходы `self.history` как `(kind, text)`:
  `action` (курсив / `*…*`), `line` (речь, первая с «Кто:»), `note`
  (авторские указания в story; boilerplate «Напиши/Продолжай историю.»
  выкидывается), `gap`. Заблокирована во время генерации.
- **Скрытие боковых панелей** — обе колонки (0 и 2) сворачиваются одним
    приёмом; чат (колонка 1, `weight=1`) забирает место. Общая схема:
    `<колонка>.grid_remove()` + `body` `grid_columnconfigure(<n>, minsize=0)`
    + показ узкой полоски `_*_reopen` (`CTkFrame width=26`,
    `grid_propagate(False)`) в той же колонке; в конце
    `_body.update_idletasks()` — перерисовка сразу.
  - **Правая** (`_toggle_right_panel` → `_apply_right_panel_visibility`):
    `_right_col` (обёртка вокруг `_right_tabs`), `weight/minsize`
    `1/COL_MIN` ↔ `0/0`; свёрнута - место делят чат и левая панель.
    Триггеры: `_right_collapse_btn` («›», `place(relx=1.0, anchor="ne")` в
    правом верхнем углу) когда развёрнута, `_right_reopen` («‹ Логи»,
    вертикально) когда свёрнута. Флаг `InferenceConfig.right_panel_hidden`.
  - **Левая** (`_toggle_left_panel` → `_apply_left_panel_visibility`):
    `_left_col` (обёртка вокруг `_left_tabs`), `weight/minsize`
    `1/COL_MIN` ↔ `0/0`. Триггеры: `_left_collapse_btn` («‹»,
    `place(x=0, y=10)` поверх `_left_col`) когда развёрнута, `_left_reopen`
    («› Сцена», вертикально) когда свёрнута. Флаг
    `InferenceConfig.left_panel_hidden`. Отдельных кнопок в верхней панели
    НЕТ — только эти стрелки, зеркально с обеих сторон.
  - Оба флага применяются на старте (`_apply_*_panel_visibility()` после
    `_load_inference_into_widgets`). `_load_inference_into_widgets(cfg,
    ui_state=True)`: при `ui_state=False` (кнопки «Optimal» / «Очистить»)
    НЕ трогает `_digest_prompt` и флаги панелей — только числовые поля.
  - **Ширина панелей не прыгает**: все три колонки `body` - `weight=1`
    равной ширины (`minsize=COL_MIN`), содержимое всегда уже колонки, так
    что от режима/вкладки/размера окна ширина панелей не зависит. Кнопки
    памяти теперь в тулбаре вкладки «Память» (места хватает, не жмутся).
    Длинные подписи в Settings и полях ввода имеют `wraplength` +
    `anchor="w"` (иначе текст обрезался слева). Пояснения на вкладке
    Settings (`self._settings_wrap` - список `(label, extra)`)
    пересчитывают `wraplength` по `<Configure>` канваса скролла:
    `base = max(WRAP=300, canvas_w - 2·PAD - PAD_TIGHT)` → на весь экран
    текст занимает всю ширину колонки, при сужении не уже `WRAP`.
  - На вкладке «Память» кнопки «Промпт памяти» / «Пересобрать» /
    «Применить» / «Экспорт…» (последняя - `_export_memory` в .txt):
    «Промпт памяти»
    (`_edit_digest_prompt` → `preset_ui.TextEditDialog`, правит
    `self._digest_prompt`; дефолт и «Сбросить к стандартному» -
    `prompt_builder.digest_system(i18n.get_lang())` (RU `DIGEST_SYSTEM` /
    EN `DIGEST_SYSTEM_EN`); пусто **или совпадает с любым из двух
    встроенных дефолтов** = хранить "" → фактический промпт памяти
    переключается вместе с языком сам; своя правка хранится как есть и не
    переводится), «Пересобрать» (`_rebuild_digest` → `_rebuild_digest_worker`:
    обнуляет `mem_head`/`mem_segments` и проходит `history[:fold_to]` тем
    же `_fold_segment` сегментами по N ходов, шлёт `__MEMORY_PROGRESS__`
    i/n в `gen_status`; при исключении откат к прежней памяти;
    `__DIGEST_REBUILT__(ok, upto)`), «Применить» (`_apply_digest_edit` -
    весь текст поля → `mem_head`, `mem_segments=[]`).
  - `self._digest_prompt` синхронизируется в `_collect_inference_config`
    (кладёт в `InferenceConfig.digest_prompt`) и
    `_load_inference_into_widgets`; идёт system-промптом ТОЛЬКО в сводку
    сегмента (`build_segment_summary_messages(..., system_prompt=)`);
    уплотнение (`build_consolidation_messages`) - свой фиксированный
    промпт.
  - Скрытые запросы памяти логируются как `ЗАПРОС/ОТВЕТ (память: ходы a–b)`
    (сегмент), `ЗАПРОС/ОТВЕТ (память: уплотнение)`, `ПАМЯТЬ: ОШИБКА`.
  - `_reset_memory()` (кнопки «Очистить» / «Очистить всё»): `mem_head=""`,
    `mem_segments=[]`, `digested_upto=0`, `_render_memory()`.
    `self._rebuilding` блокирует `_on_send`/`_on_clear`.
- **Панель Logs** (справа от чата, `body` колонка 2). Показывает сырьё,
  без правок: заголовок `_fmt_log_entry(title, body)` с меткой времени +
  тело. `ЗАПРОС -> <model>` - `json.dumps(payload, ensure_ascii=False,
  indent=2)` того самого словаря из `chat_stream` (через колбэк
  `on_request`); `ОТВЕТ <- <model>` - полный `"".join(buffer)` без
  `strip()`; ещё `ОШИБКА <- <model>`. Всё летит через `self.log_queue`
  (колбэк вызывается в рабочем потоке - только `queue.put`, безопасно).
  `wrap="none"`, моноширинный шрифт, кнопки «Очистить» (`_clear_logs`) и
  «Экспорт…» (`_export_logs`).
- **«Стоп»**: `self.stop_event = threading.Event()` создаётся **заново в
  `_on_send` перед стартом потока** (переиспользовать нельзя - останется
  выставленным). Кнопка по клику делает `.set()`. Партиал остаётся в
  чате, уходит в `self.history` обычной репликой ассистента (чтобы
  модель не «забывала» сказанное), плюс пользователю печатается
  `\n[Остановлено пользователем]\n`.
- **«Очистить»** (`_on_clear`, колонка ввода): `self.history = []` +
  `chat_digest`/`digested_upto` + очистка `chat_box`. Пресеты/поля не
  трогает. Если история непустая - спрашивает подтверждение.
- **«Очистить всё»** (`_on_clear_all`, `_clear_all_btn` — красноватая
  кнопка в колонке ввода, под «Очистить», перед «Экспорт…»): то же, что
  «Очистить», ПЛЮС `_clear_logs()` (панель Logs) и `_refresh_memory_box()`.
  Всегда спрашивает подтверждение. Пресеты и Settings не трогает.
- **Состояния кнопок** через `_set_generating(flag)`: во время генерации
  «Отправить» / «Очистить» / «Экспорт…» / «Очистить всё» /
  «Пересобрать» задизейблены, «Стоп» активна; в простое наоборот. Сброс -
  через существующий путь `"__DONE__"` в `_poll_queue` (его всегда кладёт
  `finally` в `_generate_worker`).

## Известные упрощения

- `chat_stream()` со `stop_event`: `resp.iter_lines()` блокируется в
  ожидании следующей строки от сервера, так что при подвисшей Ollama
  остановка сработает не мгновенно, а на следующем пришедшем чанке. Для
  локальной модели, стримящей токены, не проблема.
- Сетевой код `chat_stream` в основном проверяется вживую; в тестах есть
  один мок `requests.post` для проверки, что `stop_event` реально
  обрывает цикл.
- `gui.py` / `preset_ui.py` прогнаны headless-смоук-тестом (построение
  окна, селекторы, `_open_manager`, create/edit/delete через менеджер с
  моком `PresetEditDialog`, обновление меню и активного пресета,
  состояния кнопок, панель Logs с моком `chat_stream`, переключение
  dialogue↔story и видимость секций, добавление/удаление нескольких
  персонажей, сборка story- и dialogue-промпта, вкладка Settings:
  сбор/загрузка/persist параметров, передача `options`/`think`/
  `keep_alive` в `chat_stream` в обоих режимах, routing размышлений в
  Logs); полноценная проверка с реальной Ollama и живыми окнами -
  вручную через `python main.py`. Смоук-скрипты не в репозитории.
- Панель Logs копит текст без ограничения по объёму; за длинную сессию
  разрастётся - чистится вручную кнопкой «Очистить». Автообрезки нет.
- В Logs `payload` печатается с `indent=2` (не компактной строкой, как
  реально уходит по HTTP) - значения сообщений при этом не меняются,
  меняется только форматирование JSON-обёртки.
- В `PresetEditDialog` правка матчит по `id`, поэтому «сохранить как
  новую копию» из формы редактирования не получится - для копии надо
  «Создать» с нуля (осознанный компромисс: переименование не плодит
  дубли).
- Список в `PresetManager` - это `tk.Listbox` (не CTk-виджет), стилизован
  руками под тёмную тему. Функционально ок, визуально чуть выбивается.
- Модальность окон - локальный `grab_set`; вложенность (форма поверх
  менеджера) работает за счёт ручного возврата grab. Хрупковатое место
  Tkinter, но проверено смоук-тестом.
- Если генерация ничего не вернула (ошибка / «Стоп» до первого токена),
  `_generate_worker` в `finally` **удаляет висячую реплику `user`** из
  `self.history` (`got_reply` флаг) - иначе следующий ход даст два `user`
  подряд. Дополнительно `normalize_messages` в `chat_stream` схлопывает
  такие пары как страховку.
- В режиме `story` `self.history` накапливается (можно продолжать /
  править по ходу); «Очистить» = новая история. Механики памяти в
  `story` НЕТ - вся история шлётся дословно каждым запросом; ограничения
  роста контекста и управления сюжетом (ветки, откат) здесь нет.
- Бегущая память: `_maybe_update_digest` - блокирующие запросы в конце
  генерации (UI ещё занят), строго раз в N ходов (`digest_boundary`).
  **Послойная**: сегмент = ровно N ходов, сжимается один раз в
  `mem_segments`; старые сводки вливаются в `mem_head`. Вход каждого
  скрытого запроса ограничен - от длины диалога НЕ зависит (раньше плоский
  `_build_digest` слал `chat_digest` + растущий хвост, и после первого
  сбоя хвост рос без предела → запрос переставал влезать в контекст и
  память «ломалась» на долгих сессиях). `digested_upto` двигается ВСЕГДА,
  даже при сбое запроса (иначе тот же спираль). Если сводка сегмента не
  собралась - видимая заглушка, память не застревает. «Пересобрать» /
  ручная правка - как раньше. Память не сохраняется между сессиями; свой
  промпт памяти (`digest_prompt`) - сохраняется в settings.json.
- В `dialogue` - один персонаж/локация/сценарий/конфиг/герой на чат (по
  дизайну). В `story` - несколько персонажей, но всё ещё один
  сценарий/конфиг/герой.
- Поля «Размер истории» / «Дополнительные детали» живут только в текущей
  сессии (не пишутся в JSON).
- Settings: `num_ctx` без потолка - можно вбить значение, при котором
  модель не загрузится (Ollama вернёт ошибку, будет видно в Logs).
- `model_capabilities()` - блокирующий сетевой вызов на GUI-потоке (при
  выборе модели). На localhost ~10мс; если Ollama висит - фриз до 4с
  (таймаут). Как и `list_models()` - в фон не вынесен.
- Размышления показываются в Logs целиком в конце хода, не по мере
  стрима (в реальном времени - только статус 💭 в шапке).
- `_ThinkSplitter` вырезает ЛЮБЫЕ `<think>…</think>` из текста ответа -
  если персонаж буквально произнесёт такой тег в реплике, он тоже
  уедет в Logs (в RP практически не встречается).
- `structured_dialogue`: в этом режиме **нет посимвольного стрима** -
  ответ появляется целиком после генерации (нужно дождаться валидного
  JSON). Несовместимо с `reasoning_nudge` (при обоих - nudge глушится).
  Инлайновый ризонинг у моделей без capability в этом режиме недоступен;
  `message.thinking` у capability-моделей - работает.
- `Ctrl+Enter` шлёт из полей ввода; одиночный `Enter` вставляет перевод
  строки (поля многострочные).
- `chat_stream` парсит каждую строку стрима дважды (`parse_stream_line`
  + `parse_stream_thinking`) - обе чистые/тестируемые; JSON крошечный,
  на фоне инференса незаметно.
- `seed` главного героя - `Protagonist(name="Я")` с пустыми
  биографией/характером; на старте он выбирается активным, поэтому в
  промпте появляется блок `## Главный герой ...: Я`. Пользователь его
  правит или ставит `«—»`.

## Roadmap

- Бегущая память: строить дайджест в фоне (сейчас блокирует UI на 1
  запрос раз в K ходов); сохранять между сессиями; окно по токенам, а
  не по числу ходов.
- Библиотека готовых персонажей/локаций/сценариев с превью.
- Многоходовая генерация истории («продолжай» вместо одного вызова).
- Сохранение полей story-вью (размер / доп. детали) между сессиями.
- Показывать размышления в Logs по мере стрима (сейчас - в конце хода).
- `model_capabilities()` в фоновом потоке, чтоб не фризить GUI.
- `_ask_context_choice` использует грубую оценку `chars/2.5`; настоящий
  токенайзер (или `/api/tokenize`) дал бы точнее. Порог по `num_ctx`
  модели тоже не проверяется.
- Пресеты для Settings («Creative» / «Precise» / «Deterministic»).
- Кнопка «Дублировать пресет» в `PresetManager`.
- Поиск/фильтр в списке пресетов, когда их станет много.

## Как проверять после изменений

1. `python test_logic.py` - всё зелёное.
2. `python main.py` с запущенной Ollama:
   - на главном экране только селекторы пресетов + «Настроить» (плюс в
     story - поля «Размер истории» / «Дополнительные детали»);
   - переключение dialogue/story меняет набор секций: в story исчезает
     «Локация», появляются «Персонажи (история)» с «Добавить»/`✕` и поля
     истории;
   - в story можно добавить несколько персонажей, в dialogue - один;
   - «Настроить» открывает окно со списком; Создать / Редактировать /
     Удалить работают, изменения сразу видны в селекторе, в списке
     story-персонажей и в строке активных пресетов;
   - вкладка Settings: при первом запуске поля уже заполнены
     рекомендованными значениями (num_ctx 8192, min_p 0.05, …) и они
     уходят в payload даже без захода сюда; «Optimal» возвращает их
     после ручных правок, «Очистить» обнуляет; параметры действуют и в
     диалоге, и в истории; «Сохранить» пишет settings.json, значения
     переживают перезапуск; пустое поле → ключа в payload нет;
   - бейдж «Reasoning: enabled» / «Reasoning: disabled» во второй строке
     соответствует реальности (deepseek-r1/qwen3 → enabled; произвольный
     hf.co/... GGUF → disabled);
   - при «как у модели» reasoning-модель думает автоматически, размышления
     (в т.ч. инлайновые `<think>…</think>`) уходят в Logs, в чат - только
     ответ; в шапке во время генерации: ⏳ → 💭 → ✍;
   - «включить» на модели без capability `thinking` → `think` НЕ шлётся
     (не будет 400), вместо этого в system-промпт добавляется просьба
     рассуждать в `<think>…</think>`; если модель их пишет —
     `_ThinkSplitter` уводит в Logs, в чат идёт чистый ответ;
   - «включить» с форсом `think` (модель с capability) отрабатывает
     параметром; ошибочный форс на «голой» модели дал бы понятный текст
     от Ollama в чате и Logs;
   - панель Logs справа: на каждый «Отправить» появляется блок
     `ЗАПРОС -> ...` с полным payload (виден весь system-промпт и вся
     история), по завершении - `ОТВЕТ <- ...` с полным текстом ответа;
   - «Стоп» во время генерации реально обрывает поток текста, партиал
     остаётся в чате и в истории с пометкой (в Logs ответ помечается
     «(остановлен)»);
   - «Очистить» сбрасывает диалог, не трогая настройки сцены;
   - ввод в диалоге - два поля (действие/реплика), отправка при непустом
     одном, Ctrl+Enter; действие в чате курсивом, затем «Ты: реплика»;
   - при включённом «Раздельный ответ» модель отвечает JSON'ом → в чате
     действие курсивом + отдельная реплика, сырой JSON только в Logs,
     ответ появляется целиком (без стрима); в story галка не влияет;
   - «бегущая память» (только `dialogue`): каждые N ходов (Settings) в
     Logs появляется `ЗАПРОС (память)` / `ОТВЕТ (память)`, в
     system-промпте - блок `## Что уже происходило ранее`; вкладка
     «Память» справа показывает/правит сводку, «Промпт памяти» /
     «Пересобрать» / «Применить» работают; N=0 отключает; в режиме
     `story` вкладки «Память» нет и дайджест не строится;
   - в формах персонажа и героя поля идут Имя → Биография → Внешность →
     Характер → остальное; у героя ровно эти 4 поля;
   - Герой / Персонаж / Локация / Сценарий / Конфиг сохраняются и
     загружаются независимо и комбинируются;
   - повторное сохранение под тем же именем перезаписывает, а не плодит
     дубли в JSON;
   - в UI (строка над чатом) видно, какие пресеты активны в текущем режиме.
3. Актуализировать этот файл и `README.md`.
