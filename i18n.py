"""
Локализация интерфейса (RU / EN).

Единая точка правды по языку приложения. `get_lang()` / `set_lang()` -
текущий язык; `t(key, **fmt)` - строка интерфейса по ключу.

Для данных, которые уже описаны по-русски в других чистых модулях
(`blocks.BLOCK_SPECS`, `inference_spec.INFERENCE_FIELDS`), тут лежат
ТОЛЬКО английские переводы, а русский берётся из исходного модуля. Так
эти модули и их тесты не трогаются.

Скрытые промпты (`prompt_builder`) переведены в самом `prompt_builder`
через параметр `lang=` - здесь их нет.
"""

_lang = "ru"


def get_lang() -> str:
    return _lang


def set_lang(value) -> str:
    global _lang
    _lang = "en" if str(value).strip().lower() in ("en", "eng", "english") else "ru"
    return _lang


def t(key: str, **fmt) -> str:
    entry = _UI.get(key)
    if not entry:
        return key
    s = entry.get(_lang) or entry.get("ru") or key
    return s.format(**fmt) if fmt else s


# --- строки интерфейса ------------------------------------------------------
_UI = {
    # верхняя панель
    "app_title": {"ru": "Ollama RP", "en": "Ollama RP"},
    "model_label": {"ru": "Модель:", "en": "Model:"},
    "refresh_models": {"ru": "Обновить список", "en": "Refresh list"},
    "about": {"ru": "О приложении", "en": "About"},
    "help": {"ru": "Помощь", "en": "Help"},
    "faq": {"ru": "FAQ", "en": "FAQ"},
    "download_models": {"ru": "Скачать модели", "en": "Download models"},
    "open_cmd": {"ru": "Запустить cmd", "en": "Open cmd"},
    "cheatsheet_title": {"ru": "Шпаргалка по командам Ollama",
                         "en": "Ollama command cheat sheet"},
    "cmd_failed_title": {"ru": "Командная строка", "en": "Command line"},
    "cmd_failed_msg": {"ru": "Не удалось открыть командную строку:\n{err}",
                       "en": "Could not open a command line:\n{err}"},
    "lang_label": {"ru": "Язык:", "en": "Language:"},
    "no_models": {"ru": "модели не найдены", "en": "no models found"},
    "ollama_unreachable": {
        "ru": "Не удалось подключиться к Ollama. Проверь, что она запущена "
              "(команда 'ollama serve' или иконка в трее).",
        "en": "Could not connect to Ollama. Make sure it is running "
              "('ollama serve' or the tray icon).",
    },
    "lang_busy_title": {"ru": "Язык", "en": "Language"},
    "lang_busy": {"ru": "Дождись окончания генерации, потом переключай язык.",
                  "en": "Wait until generation finishes, then switch the language."},

    # вторая строка (активные пресеты)
    "active_chat": {
        "ru": "Режим Chat — без ролплея и промптов; на ответ влияют только "
              "Настройки и модель",
        "en": "Chat mode — no roleplay or prompts; only Settings and the model "
              "affect the reply",
    },
    "lbl_you": {"ru": "Вы", "en": "You"},
    "lbl_character": {"ru": "Персонаж", "en": "Character"},
    "lbl_characters": {"ru": "Персонажи", "en": "Characters"},
    "lbl_location": {"ru": "Локация", "en": "Location"},
    "lbl_scenario": {"ru": "Сценарий", "en": "Scenario"},
    "lbl_configuration": {"ru": "Конфигурация", "en": "Configuration"},
    "lbl_protagonist": {"ru": "Главный герой", "en": "Protagonist"},
    "lbl_size": {"ru": "Размер", "en": "Length"},

    # левая колонка
    "tab_scene": {"ru": "Сцена", "en": "Scene"},
    "tab_settings": {"ru": "Настройки", "en": "Settings"},
    "scene_presets": {"ru": "Пресеты сцены", "en": "Scene presets"},
    "configure_btn": {"ru": "Настроить", "en": "Manage"},
    "add_btn": {"ru": "Добавить", "en": "Add"},
    "story_chars_label": {"ru": "Персонажи (история)", "en": "Characters (story)"},
    "story_size_label": {"ru": "Размер истории", "en": "Story length"},
    "extra_details_label": {"ru": "Дополнительные детали (опционально)",
                            "en": "Additional details (optional)"},
    "none_hint": {"ru": "«{none}» — блок не участвует в промпте",
                  "en": "«{none}» — the block is left out of the prompt"},
    "no_chars": {"ru": "(персонажи не добавлены)", "en": "(no characters added)"},
    "unnamed": {"ru": "(без имени)", "en": "(unnamed)"},
    "chat_mode_note": {
        "ru": "Режим Chat: ролплей, сцена и память отключены.\n\n"
              "На ответ влияют только вкладка Настройки и сама модель —\n"
              "чистый тест параметров без влияния твоих промптов.\n\n"
              "Настройки — на вкладке Настройки, вывод запросов — в Logs.",
        "en": "Chat mode: roleplay, scene and memory are off.\n\n"
              "Only the Settings tab and the model itself shape the reply —\n"
              "a clean parameter test with none of your prompts.\n\n"
              "Parameters are on the Settings tab, request dumps go to Logs.",
    },

    # вкладка настроек
    "gen_params": {"ru": "Параметры генерации", "en": "Generation parameters"},
    "settings_intro": {
        "ru": "Уходят в модель с каждым запросом. Пустое поле = параметр не "
              "отправляется, действует значение по умолчанию модели. «Optimal» "
              "— рекомендованные значения (они же стоят по умолчанию при первом "
              "запуске).",
        "en": "Sent to the model with every request. An empty field = the "
              "parameter is not sent and the model's own default applies. "
              "«Optimal» restores the recommended values (also the defaults on "
              "first launch).",
    },
    "save_settings": {"ru": "Сохранить настройки", "en": "Save settings"},
    "optimal_btn": {"ru": "Optimal", "en": "Optimal"},
    "clear_btn": {"ru": "Очистить", "en": "Clear"},
    "settings_saved_title": {"ru": "Настройки", "en": "Settings"},
    "settings_saved_msg": {"ru": "Параметры генерации сохранены.",
                           "en": "Generation parameters saved."},

    # центральная колонка
    "mode_dialogue": {"ru": "Диалог", "en": "Dialogue"},
    "mode_story": {"ru": "История", "en": "Story"},
    "mode_chat": {"ru": "Чат", "en": "Chat"},
    "hint_dialogue": {"ru": "Диалог с одним персонажем — реплики по очереди",
                      "en": "Dialogue with one character — turn by turn"},
    "hint_story": {"ru": "Генерация истории по заранее заданным параметрам",
                   "en": "Story generation from preset parameters"},
    "hint_chat": {"ru": "Тестовый чат: возможности модели с разными параметрами",
                  "en": "Test chat: the model's behaviour under different parameters"},
    "dlg_action_label": {"ru": "Твоё действие (в чат уйдёт курсивом)",
                         "en": "Your action (shown in italics in the chat)"},
    "dlg_reply_label": {"ru": "Твоя реплика (только речь)",
                        "en": "Your line (speech only)"},
    "story_input_label": {"ru": "Указания к истории / правки (необязательно)",
                          "en": "Story directions / edits (optional)"},
    "chat_msg_label": {"ru": "Сообщение", "en": "Message"},
    "hint_send_dialogue": {
        "ru": "Ctrl+Enter — отправить · достаточно заполнить одно из полей",
        "en": "Ctrl+Enter — send · filling in just one field is enough",
    },
    "hint_send_story": {
        "ru": "Ctrl+Enter — сгенерировать · пусто = «напиши / продолжай историю»",
        "en": "Ctrl+Enter — generate · empty = “write / continue the story”",
    },
    "hint_send_chat": {
        "ru": "Ctrl+Enter — отправить · без system-промпта, влияют только Настройки",
        "en": "Ctrl+Enter — send · no system prompt, only Settings apply",
    },
    "send": {"ru": "Отправить", "en": "Send"},
    "generate_story": {"ru": "Сгенерировать историю", "en": "Generate story"},
    "continue_story_btn": {"ru": "Продолжить историю", "en": "Continue story"},
    "stop": {"ru": "Стоп", "en": "Stop"},
    "clear_all": {"ru": "Очистить всё", "en": "Clear all"},
    "export": {"ru": "Экспорт…", "en": "Export…"},
    "sessions_btn": {"ru": "Сохранения…", "en": "Saves…"},

    # сохранённые диалоги (sessions_ui.py / gui._session_*)
    "sess_title": {"ru": "Сохранённые диалоги", "en": "Saved dialogues"},
    "sess_intro": {
        "ru": "Сохраняет текущий диалог целиком: чат, историю, память, выбранные "
              "пресеты, режим, модель и недописанные поля. «Загрузить» вернёт всё "
              "ровно с этого места — в том числе после перезапуска приложения.",
        "en": "Saves the current dialogue as a whole: chat, history, memory, selected "
              "presets, mode, model and unsent input. “Load” brings everything back "
              "exactly from that point — also after restarting the app."},
    "sess_name_label": {"ru": "Название сохранения", "en": "Save name"},
    "sess_save_new": {"ru": "Сохранить как новое", "en": "Save as new"},
    "sess_load": {"ru": "Загрузить", "en": "Load"},
    "sess_overwrite": {"ru": "Перезаписать", "en": "Overwrite"},
    "sess_delete": {"ru": "Удалить", "en": "Delete"},
    "sess_empty": {"ru": "Сохранений пока нет.", "en": "No saves yet."},
    "sess_info": {"ru": "{mode} · реплик в истории: {turns} · {saved}",
                  "en": "{mode} · history entries: {turns} · {saved}"},
    "sess_nothing": {"ru": "Пока нечего сохранять — диалог пуст.",
                     "en": "Nothing to save yet — the dialogue is empty."},
    "sess_busy": {"ru": "Дождитесь конца генерации (или нажмите «Стоп»), потом сохраняйте и загружайте.",
                  "en": "Wait for the generation to finish (or press “Stop”) before saving or loading."},
    "sess_saved": {"ru": "Сохранено: «{name}».", "en": "Saved: “{name}”."},
    "sess_overwrite_q": {"ru": "Перезаписать сохранение «{name}» текущим диалогом?",
                         "en": "Overwrite the save “{name}” with the current dialogue?"},
    "sess_delete_q": {"ru": "Удалить сохранение «{name}»? Это нельзя отменить.",
                      "en": "Delete the save “{name}”? This cannot be undone."},
    "sess_replace_q": {"ru": "Текущий диалог будет заменён сохранённым «{name}». Продолжить?\n\n(Чтобы не потерять текущий, сначала сохраните его.)",
                       "en": "The current dialogue will be replaced with the save “{name}”. Continue?\n\n(Save the current one first if you want to keep it.)"},
    "sess_err": {"ru": "Не удалось: {err}", "en": "Failed: {err}"},
    "sess_err_read": {"ru": "Сохранение «{name}» не читается: {err}",
                      "en": "The save “{name}” cannot be read: {err}"},
    "sess_loaded": {"ru": "Загружено: «{name}». Можно продолжать.",
                    "en": "Loaded: “{name}”. You can continue."},
    "sess_restored_presets": {
        "ru": "Эти пресеты были удалены после сохранения — восстановлены из сохранения: {names}.",
        "en": "These presets were deleted after the save — restored from the save: {names}."},
    "sess_model_missing": {
        "ru": "Модель «{model}» из сохранения не установлена — оставлена текущая.",
        "en": "The save's model “{model}” is not installed — the current one is kept."},
    "sess_dyn_q": {
        "ru": "Обновить динамическую память персонажа «{name}» перед сохранением?\n\n"
              "Чтобы не потерять последние события, сначала обновится память диалога, "
              "затем динамическая память (два запроса подряд — может занять время).\n\n"
              "Да — обновить и сохранить\nНет — сохранить без обновления\nОтмена — не сохранять",
        "en": "Update the dynamic memory of “{name}” before saving?\n\n"
              "So that the latest events are not lost, the dialogue memory is updated first, "
              "then the dynamic memory (two requests in a row — may take a while).\n\n"
              "Yes — update and save\nNo — save without updating\nCancel — do not save"},
    "sess_dyn_failed": {
        "ru": "Динамическую память обновить не удалось (смотрите Logs) — диалог сохранён без обновления.",
        "en": "The dynamic memory could not be updated (see Logs) — the dialogue was saved without it."},
    "sess_dyn_nomodel": {
        "ru": "Не выбрана модель — динамическая память не обновлена, диалог сохранён как есть.",
        "en": "No model selected — the dynamic memory was not updated, the dialogue was saved as is."},
    "sess_default_name": {"ru": "{who} — {date}", "en": "{who} — {date}"},

    # правая колонка
    "tab_logs": {"ru": "Logs", "en": "Logs"},
    "tab_memory": {"ru": "Память", "en": "Memory"},
    "tab_logs_short": {"ru": "Логи", "en": "Logs"},
    "logs_hint": {
        "ru": "Дословные запросы к модели и её полные ответы — как есть, без правок.",
        "en": "Verbatim requests to the model and its full replies — as is, unedited.",
    },
    "mem_prompt_btn": {"ru": "Промпт памяти", "en": "Memory prompt"},
    "mem_rebuild_btn": {"ru": "Пересобрать", "en": "Rebuild"},
    "mem_apply_btn": {"ru": "Применить", "en": "Apply"},
    "memory_hint": {
        "ru": "Сжатая «память» прошлых событий — раз в N ходов собирается "
              "скрытым запросом.",
        "en": "A compressed “memory” of past events — rebuilt by a hidden "
              "request every N turns.",
    },

    # статус генерации
    "st_wait": {"ru": "⏳ ждём модель…", "en": "⏳ waiting for the model…"},
    "st_think": {"ru": "💭 размышляет…", "en": "💭 thinking…"},
    "st_answer": {"ru": "✍ отвечает…", "en": "✍ replying…"},
    "st_memory": {"ru": "🧠 собираю память…", "en": "🧠 building memory…"},
    "st_memory_progress": {"ru": "🧠 память {i}/{n}", "en": "🧠 memory {i}/{n}"},
    "st_dyn_memory": {"ru": "🧠 обновляю динамическую память персонажа…",
                      "en": "🧠 updating the character's dynamic memory…"},

    # динамическая память персонажа (dynamic_memory.py, форма пресета, gui._dyn_*)
    "dyn_enable": {
        "ru": "Динамическая память персонажа",
        "en": "Character's dynamic memory"},
    "dyn_hint": {
        "ru": "Персонаж запоминает самое важное между диалогами (только собеседник, не герой). "
              "Приложение само обновляет память по ходу диалога: кратко выделяет важные события, "
              "изменения отношений, статуса, внешности. Опирается на память диалога "
              "(в Settings «Размер истории» больше 0). Предел размера (в Settings) — дальше "
              "память не растёт. Текст можно править руками. «Очистить» применится после «Сохранить».",
        "en": "The character remembers what matters between dialogues (companions only, not the hero). "
              "The app updates it during the dialogue: briefly picks out important events, "
              "changes in relationships, status, appearance. Relies on the dialogue memory "
              "(Settings “History size” above 0). The size limit (in Settings) — it never grows "
              "beyond. You can edit the text by hand. “Clear” takes effect after “Save”."},
    "dyn_clear": {"ru": "Очистить динамическую память", "en": "Clear dynamic memory"},
    "log_dyn_request": {"ru": "ЗАПРОС (динамическая память: {name}) -> {model}",
                        "en": "REQUEST (dynamic memory: {name}) -> {model}"},
    "log_dyn_response": {"ru": "ОТВЕТ (динамическая память: {name}) <- {model}",
                         "en": "REPLY (dynamic memory: {name}) <- {model}"},
    "log_dyn_same": {"ru": "ДИНАМИЧЕСКАЯ ПАМЯТЬ «{name}»: без изменений",
                     "en": "DYNAMIC MEMORY “{name}”: unchanged"},
    "log_dyn_updated": {"ru": "ДИНАМИЧЕСКАЯ ПАМЯТЬ «{name}»: обновлена ({chars} симв.)",
                        "en": "DYNAMIC MEMORY “{name}”: updated ({chars} chars)"},
    "log_dyn_failed": {"ru": "ДИНАМИЧЕСКАЯ ПАМЯТЬ «{name}»: ответа нет — повторим позже",
                       "en": "DYNAMIC MEMORY “{name}”: no reply — will retry later"},
    "st_compress": {"ru": "🗜 сжимаю пример {i}/{n}", "en": "🗜 compressing the example {i}/{n}"},
    "st_compress_out": {"ru": "🗜 пример {i}/{n} · ~{w} слов",
                        "en": "🗜 example {i}/{n} · ~{w} words"},
    "st_compress_think": {"ru": "🗜 пример {i}/{n} · модель думает…",
                          "en": "🗜 example {i}/{n} · model thinking…"},
    "st_retry_dup": {"ru": "🔁 реплика повторилась · перегенерация {i}/{n}",
                     "en": "🔁 the line repeated · regenerating {i}/{n}"},
    "st_retry_loop": {"ru": "🔁 текст зациклился · перегенерация {i}/{n}",
                      "en": "🔁 the text got stuck in a loop · regenerating {i}/{n}"},
    "st_retry_stall": {"ru": "⏱ модель молчит {s} с · повторный запрос {i}/{n}",
                       "en": "⏱ the model went silent for {s}s · resending {i}/{n}"},
    "st_story_recap": {"ru": "📖 пересказываю историю кратко… {i}/{n}",
                       "en": "📖 summarizing the story so far… {i}/{n}"},

    # предупреждение о нехватке контекста
    "ctx_warn_title": {"ru": "Не хватает контекста", "en": "Context is too small"},
    "ctx_warn_msg": {
        "ru": "Запрос ≈ {need} токенов, а размер контекста (num_ctx) = {ctx}. "
              "Всё, что не влезло, Ollama отбросит с начала — модель может "
              "потерять пример и упасть с ошибкой чередования ролей.\n\n"
              "Что сделать:",
        "en": "The request is ≈ {need} tokens, but the context size (num_ctx) "
              "= {ctx}. Whatever does not fit is dropped from the start by "
              "Ollama — the model may lose the example and fail with a "
              "role-alternation error.\n\nWhat to do:",
    },
    "ctx_warn_msg_unknown": {
        "ru": "Запрос ≈ {need} токенов. Размер контекста (num_ctx) не задан — "
              "у модели по умолчанию он обычно небольшой (2048–4096), и "
              "запрос может не влезть.\n\nЧто сделать:",
        "en": "The request is ≈ {need} tokens. Context size (num_ctx) is not "
              "set — a model's own default is usually small (2048–4096) and "
              "the request may not fit.\n\nWhat to do:",
    },
    "ctx_btn_increase": {"ru": "Поднять num_ctx до {n}",
                         "en": "Raise num_ctx to {n}"},
    "ctx_btn_compress": {"ru": "Сжать пример",
                         "en": "Compress the example"},
    "ctx_btn_proceed": {"ru": "Продолжить как есть",
                        "en": "Continue as is"},
    "ctx_increase_note": {
        "ru": "num_ctx поднят до {n} (проверь, что модель столько "
              "поддерживает; вырастет расход RAM/VRAM, модель перезагрузится).",
        "en": "num_ctx raised to {n} (check the model supports it; RAM/VRAM "
              "use grows and the model reloads).",
    },
    "compress_start_note": {
        "ru": "\n🗜 Сжимаю пример, чтобы уместить его в контекст. На большой "
              "модели это может занять несколько минут — счётчик и «~слов» "
              "справа сверху показывают, что работа идёт. Кнопка «Стоп» "
              "прерывает и берёт то, что уже сжато.\n",
        "en": "\n🗜 Compressing the example to fit the context. On a large "
              "model this can take a few minutes — the counter and “~words” "
              "at the top right show it is working. The “Stop” button "
              "interrupts and keeps what is already done.\n",
    },
    "compress_stopped_note": {
        "ru": "⏹ Остановлено — беру то, что успело сжаться. Запускаю генерацию…\n",
        "en": "⏹ Stopped — using what got compressed. Starting generation…\n",
    },
    "compress_cancelled_note": {
        "ru": "⏹ Сжатие отменено (ничего не успело сжаться). Пример не изменён.\n",
        "en": "⏹ Compression cancelled (nothing was compressed). The example "
              "is unchanged.\n",
    },
    "compress_ok_note": {
        "ru": "✓ Пример ({msgs} сообщений) сжат в краткое содержание "
              "(оригинал сохранён на эту сессию). Запускаю генерацию…\n",
        "en": "✓ The example ({msgs} messages) is compressed into a summary "
              "(the original is kept for this session). Starting generation…\n",
    },
    "compress_ok_note_box": {
        "ru": "✓ Пример из «Дополнительных деталей» ({chars} симв.) сжат в "
              "краткое содержание прямо в поле (оригинал сохранён на эту "
              "сессию). Запускаю генерацию…\n",
        "en": "✓ The example from “Additional details” ({chars} chars) is "
              "compressed into a summary right in the field (the original is "
              "kept for this session). Starting generation…\n",
    },
    "compress_fail_note": {
        "ru": "✗ Не удалось сжать пример (модель вернула ошибку или пусто). "
              "Подними num_ctx или уменьши текст вручную.\n",
        "en": "✗ Could not compress the example (the model errored or returned "
              "nothing). Raise num_ctx or trim the text by hand.\n",
    },
    "compress_fail_title": {"ru": "Сжатие не удалось", "en": "Compression failed"},

    # «Продолжить историю»: пересказ перед генерацией продолжения
    "story_recap_stopped_note": {
        "ru": "⏹ Остановлено — беру то, что успело пересказаться.\n",
        "en": "⏹ Stopped — using what got summarized so far.\n",
    },
    "story_recap_cancelled_note": {
        "ru": "⏹ Пересказ отменён (ничего не успело пересказаться).\n",
        "en": "⏹ Summarizing cancelled (nothing was summarized yet).\n",
    },
    "story_recap_fail_note": {
        "ru": "✗ Не удалось пересказать историю (модель вернула ошибку). "
              "Нажми «Продолжить историю» ещё раз, чтобы повторить попытку.\n",
        "en": "✗ Could not summarize the story (the model errored). Press "
              "“Continue story” again to retry.\n",
    },
    "story_recap_fail_title": {"ru": "Пересказ не удался", "en": "Summary failed"},
    "compressed_history_intro": {
        "ru": "Краткое содержание того, что было раньше (основа для продолжения):",
        "en": "Summary of what came before (basis for continuing):",
    },

    # диалоги подтверждения / сообщения
    "clear_dlg_title": {"ru": "Очистить диалог", "en": "Clear dialogue"},
    "clear_dlg_msg": {
        "ru": "Сбросить текущий диалог и память? Выбранные пресеты останутся.",
        "en": "Reset the current dialogue and memory? Selected presets stay.",
    },
    "clear_all_title": {"ru": "Очистить всё", "en": "Clear all"},
    "clear_all_msg": {
        "ru": "Сбросить чат, память и лог? Выбранные пресеты и настройки останутся.",
        "en": "Reset the chat, memory and log? Selected presets and settings stay.",
    },
    "export_menu_title": {"ru": "Экспорт", "en": "Export"},
    "export_empty": {"ru": "Пока нечего экспортировать — история пуста.",
                     "en": "Nothing to export yet — the history is empty."},
    "export_dlg_title": {"ru": "Экспорт диалога / истории",
                         "en": "Export dialogue / story"},
    "export_nothing": {"ru": "Пока нечего экспортировать — пусто.",
                       "en": "Nothing to export yet — it is empty."},
    "export_logs_dlg_title": {"ru": "Экспорт лога", "en": "Export the log"},
    "export_memory_dlg_title": {"ru": "Экспорт памяти", "en": "Export the memory"},
    "ft_txt": {"ru": "Текст (.txt)", "en": "Text (.txt)"},

    # вкладки «Фото» в боковых панелях (только диалог)
    "tab_photo": {"ru": "Фото", "en": "Photo"},
    "photo_panel_none": {
        "ru": "Не выбран пресет блока «{title}».",
        "en": "No preset is selected for “{title}”."},
    "photo_panel_empty": {
        "ru": "В галерее «{name}» нет фото.\nДобавьте их: «Настроить» блока «{title}».",
        "en": "The gallery of “{name}” is empty.\nAdd photos via “Manage” of the “{title}” block."},
    "gallery_counter": {"ru": "{i} / {n}", "en": "{i} / {n}"},
    "gallery_prev": {"ru": "Предыдущее фото", "en": "Previous photo"},
    "gallery_next": {"ru": "Следующее фото", "en": "Next photo"},
    # кнопка в верхней панели: режим эмотиконов (все / только собеседник / скрыты)
    # подпись кнопки = ТЕКУЩИЙ режим; клик переключает по кругу
    "emotes_mode_all": {"ru": "Эмотиконы: все", "en": "Emoticons: all"},
    "emotes_mode_companion": {"ru": "Эмотиконы: только собеседник",
                              "en": "Emoticons: companion only"},
    "emotes_mode_hidden": {"ru": "Эмотиконы: скрыты", "en": "Emoticons: hidden"},

    # фото персонажа / героя (форма пресета)
    "photo_label": {"ru": "Аватар — одно фото для чата (необязательно)",
                    "en": "Avatar — one photo for the chat (optional)"},
    "gallery_label": {
        "ru": "Галерея — несколько фото, только вкладка «Фото» (необязательно)",
        "en": "Gallery — several photos, only the “Photo” tab (optional)"},
    "gallery_add": {"ru": "Добавить фото…", "en": "Add photos…"},
    "emotes_label": {
        "ru": "Эмотиконы — PNG-силуэты на ПРОЗРАЧНОМ фоне (необязательно)",
        "en": "Emoticons — PNG silhouettes on a TRANSPARENT background (optional)"},
    "emotes_hint": {
        "ru": "Рисуются поверх интерфейса и меняются на каждый ответ в чате. "
              "Другие файлы (JPG, PNG без прозрачности) не загрузятся.",
        "en": "Drawn over the interface, switching with every reply in the chat. "
              "Other files (JPG, PNG without transparency) will not load."},
    "emotes_add": {"ru": "Добавить эмотиконы…", "en": "Add emoticons…"},
    "list_empty": {"ru": "пока пусто", "en": "empty so far"},
    "list_remove_tip": {"ru": "Убрать", "en": "Remove"},
    "emote_err_title": {"ru": "Не все эмотиконы добавлены",
                        "en": "Not all emoticons were added"},
    "emote_err_not_png": {
        "ru": "«{name}» — это не PNG. Эмотиконы — только PNG на прозрачном фоне.",
        "en": "“{name}” is not a PNG. Emoticons must be PNG on a transparent background."},
    "emote_err_no_alpha": {
        "ru": "«{name}» — PNG без прозрачности (нет альфа-канала): фон не прозрачный.",
        "en": "“{name}” is a PNG without transparency (no alpha channel): the background is not transparent."},
    "emote_err_not_transparent": {
        "ru": "«{name}» — фон не прозрачный (прозрачных пикселей меньше 5 %).",
        "en": "“{name}” has no transparent background (fewer than 5 % transparent pixels)."},
    "emote_err_other": {
        "ru": "«{name}» — не удалось открыть как картинку: {err}",
        "en": "“{name}” could not be opened as an image: {err}"},
    "emote_err_footer": {
        "ru": "\nОстальные файлы (если были) добавлены.",
        "en": "\nThe other files (if any) were added."},
    "photo_pick": {"ru": "Выбрать фото…", "en": "Choose photo…"},
    "photo_change": {"ru": "Заменить фото…", "en": "Change photo…"},
    "photo_remove": {"ru": "Убрать фото", "en": "Remove photo"},
    "photo_none": {"ru": "нет фото", "en": "no photo"},
    "photo_dlg_title": {"ru": "Выбор фото", "en": "Choose a photo"},
    "ft_images": {"ru": "Изображения", "en": "Images"},
    "photo_err_title": {"ru": "Фото не загружено", "en": "Photo not loaded"},
    "photo_err_msg": {"ru": "Не удалось открыть файл как картинку:\n{err}",
                      "en": "Could not open the file as an image:\n{err}"},
    "photo_need_pillow": {
        "ru": "Для фото нужен пакет Pillow. Установите его командой:\n\n"
              "pip install pillow\n\nи перезапустите приложение.",
        "en": "Photos need the Pillow package. Install it with:\n\n"
              "pip install pillow\n\nand restart the app."},
    "ft_docx": {"ru": "Word (.docx)", "en": "Word (.docx)"},
    "export_docx_err": {
        "ru": "Для .docx нужен пакет python-docx.\nУстанови его "
              "(pip install python-docx) или сохрани как .txt.",
        "en": "The .docx format needs the python-docx package.\nInstall it "
              "(pip install python-docx) or save as .txt.",
    },
    "export_save_err": {"ru": "Не удалось сохранить:\n{err}",
                        "en": "Could not save:\n{err}"},
    "export_saved": {"ru": "Сохранено:\n{path}", "en": "Saved:\n{path}"},
    "pick_model_title": {"ru": "Ollama RP", "en": "Ollama RP"},
    "pick_model_msg": {"ru": "Сначала выбери модель.", "en": "Pick a model first."},
    "memory_title": {"ru": "Память", "en": "Memory"},
    "mem_nothing": {"ru": "Пока нечего сворачивать — история короткая.",
                    "en": "Nothing to fold yet — the history is short."},
    "mem_failed": {
        "ru": "Не удалось собрать память (модель вернула ошибку или пусто). "
              "Старая память оставлена без изменений.",
        "en": "Could not build the memory (the model errored or returned "
              "nothing). The old memory is left unchanged.",
    },

    # экспортируемый текст
    "note_prefix": {"ru": "указание", "en": "direction"},
    "story_gen_marker": {"ru": "--- Генерация истории ---",
                         "en": "--- Story generation ---"},
    "story_cont_marker": {"ru": "--- Продолжение ---", "en": "--- Continuation ---"},
    "you_prefix": {"ru": "Ты", "en": "You"},
    "model_prefix": {"ru": "Модель", "en": "Model"},
    "err_inline": {"ru": "[Ошибка: {err}]", "en": "[Error: {err}]"},
    "stopped_by_user": {"ru": "[Остановлено пользователем]",
                        "en": "[Stopped by the user]"},
    "empty_reply": {"ru": "(пустой ответ)", "en": "(empty reply)"},
    "stopped_suffix": {"ru": " (остановлен)", "en": " (stopped)"},
    "write_story": {"ru": "Напиши историю.", "en": "Write the story."},
    "continue_story": {
        "ru": "Продолжай историю дальше по сюжету. Не пересказывай и не "
              "повторяй уже написанные сцены, реплики и обороты - переходи "
              "к следующему событию, развивай отношения и сюжет вперёд.",
        "en": "Continue the story further along the plot. Do not retell or "
              "repeat scenes, lines or phrasing already written - move on "
              "to the next event, develop the relationship and the plot "
              "forward.",
    },

    # авто-перегенерация при повторе реплики персонажа (structured-режим).
    # НЕ пишется в чат/историю (ломает иммерсивность) - только статус
    # генерации (заметно, но проходяще) и Logs (постоянная запись,
    # заголовок КАПСОМ, чтобы бросался в глаза среди обычных запросов).
    "log_retry_dup_gaveup": {
        "ru": "ПОВТОР РЕПЛИКИ — ЛИМИТ ПЕРЕГЕНЕРАЦИЙ ИСЧЕРПАН, оставлен "
              "последний вариант <- (речь)",
        "en": "DUPLICATE LINE — REGENERATION LIMIT REACHED, keeping the "
              "last attempt <- (speech)"},
    "retry_dup_nudge": {
        "ru": "Твоя прошлая прямая речь получилась почти дословным повтором "
              "уже сказанного ранее. Дай СОВЕРШЕННО другую по формулировке "
              "реплику: другие слова, другой ход мысли, другая интонация. "
              "Смысл сцены сохрани, но фразу построй заново.",
        "en": "Your last spoken line was an almost word-for-word repeat of "
              "something already said earlier. Give a COMPLETELY different "
              "line: different wording, different train of thought, different "
              "tone. Keep the scene's meaning, but build the phrase anew."},
    "log_retry_dup": {"ru": "ПОВТОР РЕПЛИКИ — перегенерация {i}/{n} <- (речь)",
                      "en": "DUPLICATE LINE — regeneration {i}/{n} <- (speech)"},

    # авто-перегенерация при зацикливании текста (длинные истории/диалоги).
    # Тоже не пишется в чат/историю - только статус и Logs (см. коммент
    # выше про повтор реплики - та же логика).
    "log_retry_loop_gaveup": {
        "ru": "ЗАЦИКЛИВАНИЕ ТЕКСТА — ЛИМИТ ПЕРЕГЕНЕРАЦИЙ ИСЧЕРПАН, обрезано "
              "до последнего чистого места <- (оборванный ответ)",
        "en": "TEXT LOOP — REGENERATION LIMIT REACHED, trimmed to the last "
              "clean point <- (aborted reply)"},
    "retry_loop_nudge": {
        "ru": "Продолжи текст СРАЗУ с этого места, без вступлений и повторов "
              "уже написанного. Введи что-то новое: развитие сцены, новую "
              "деталь или реплику — не пересказывай и не перефразируй то, "
              "что уже было.",
        "en": "Continue the text RIGHT from this point, with no preamble and "
              "no repeating what's already written. Introduce something new "
              "- a development, a new detail or line - do not retell or "
              "rephrase what already happened."},
    # зависание модели (тишина дольше таймаута из Settings): статус + Logs;
    # в чат - только если попытки кончились (тогда ответа нет вообще)
    "log_retry_stall": {
        "ru": "ЗАВИСАНИЕ МОДЕЛИ — тишина {s} с, повторный запрос {i}/{n}",
        "en": "MODEL STALLED — silent for {s}s, resending {i}/{n}"},
    "log_retry_stall_gaveup": {
        "ru": "ЗАВИСАНИЕ МОДЕЛИ — ЛИМИТ ПОВТОРНЫХ ЗАПРОСОВ ИСЧЕРПАН ({n}), ответ не получен",
        "en": "MODEL STALLED — RESEND LIMIT REACHED ({n}), no reply received"},
    "stall_gaveup_err": {
        "ru": "модель молчит: {n} повторных запросов подряд без ответа "
              "(таймаут {s} с, настраивается в Settings)",
        "en": "the model keeps going silent: {n} resends in a row with no "
              "reply (timeout {s}s, set in Settings)"},
    "log_retry_loop": {"ru": "ЗАЦИКЛИВАНИЕ ТЕКСТА — перегенерация {i}/{n} <- (оборванный ответ)",
                       "en": "TEXT LOOP — regeneration {i}/{n} <- (aborted reply)"},

    # заголовки блоков лога
    "log_request": {"ru": "ЗАПРОС -> {model}", "en": "REQUEST -> {model}"},
    "log_response": {"ru": "ОТВЕТ <- {model}", "en": "REPLY <- {model}"},
    "log_error": {"ru": "ОШИБКА <- {model}", "en": "ERROR <- {model}"},
    "log_thinking": {"ru": "РАЗМЫШЛЕНИЯ <- {model}", "en": "REASONING <- {model}"},
    "log_mem_request": {"ru": "ЗАПРОС (память) -> {model}",
                        "en": "REQUEST (memory) -> {model}"},
    "log_mem_response": {"ru": "ОТВЕТ (память) <- {model}",
                         "en": "REPLY (memory) <- {model}"},
    "log_mem_error": {"ru": "ПАМЯТЬ: ОШИБКА <- {model}",
                      "en": "MEMORY: ERROR <- {model}"},
    "log_mem": {"ru": "ПАМЯТЬ <- {model}", "en": "MEMORY <- {model}"},
    "log_mem_no_move": {"ru": "(модель вернула пусто - рубеж не сдвигаем)",
                        "en": "(model returned nothing - boundary not advanced)"},
    "log_mem_seg_request": {"ru": "ЗАПРОС (память: ходы {a}–{b}) -> {model}",
                            "en": "REQUEST (memory: turns {a}–{b}) -> {model}"},
    "log_mem_seg_response": {"ru": "ОТВЕТ (память: ходы {a}–{b}) <- {model}",
                             "en": "REPLY (memory: turns {a}–{b}) <- {model}"},
    "log_mem_consolidate_request": {"ru": "ЗАПРОС (память: уплотнение) -> {model}",
                                    "en": "REQUEST (memory: consolidate) -> {model}"},
    "log_mem_consolidate_response": {"ru": "ОТВЕТ (память: уплотнение) <- {model}",
                                     "en": "REPLY (memory: consolidate) <- {model}"},
    "log_compress_request": {"ru": "ЗАПРОС (сжатие примера {i}/{n}) -> {model}",
                             "en": "REQUEST (compress example {i}/{n}) -> {model}"},
    "log_compress_response": {"ru": "ОТВЕТ (сжатие примера {i}/{n}) <- {model}",
                              "en": "REPLY (compress example {i}/{n}) <- {model}"},
    "log_story_recap_request": {"ru": "ЗАПРОС (пересказ истории {i}/{n}) -> {model}",
                                "en": "REQUEST (story recap {i}/{n}) -> {model}"},
    "log_story_recap_response": {"ru": "ОТВЕТ (пересказ истории {i}/{n}) <- {model}",
                                 "en": "REPLY (story recap {i}/{n}) <- {model}"},
    "log_story_recap_consolidate_request": {
        "ru": "ЗАПРОС (пересказ истории: уплотнение) -> {model}",
        "en": "REQUEST (story recap: consolidate) -> {model}"},
    "log_story_recap_consolidate_response": {
        "ru": "ОТВЕТ (пересказ истории: уплотнение) <- {model}",
        "en": "REPLY (story recap: consolidate) <- {model}"},
    "mem_segment_stub": {"ru": "[ходы {a}–{b}: сводку собрать не удалось]",
                         "en": "[turns {a}–{b}: summary unavailable]"},
    "log_empty": {"ru": "(пусто)", "en": "(empty)"},
    "log_field_request": {"ru": "ЗАПРОС (поле «{attr}») -> {model}",
                          "en": "REQUEST (field “{attr}”) -> {model}"},
    "log_field_error": {"ru": "ОШИБКА (поле «{attr}») <- {model}",
                        "en": "ERROR (field “{attr}”) <- {model}"},
    "log_field_response": {"ru": "ОТВЕТ (поле «{attr}») <- {model}",
                           "en": "REPLY (field “{attr}”) <- {model}"},

    # контекстное меню
    "ctx_cut": {"ru": "Вырезать", "en": "Cut"},
    "ctx_copy": {"ru": "Копировать", "en": "Copy"},
    "ctx_paste": {"ru": "Вставить", "en": "Paste"},
    "ctx_select_all": {"ru": "Выделить всё", "en": "Select all"},

    # окно правки промпта памяти
    "mem_prompt_dlg_title": {"ru": "Промпт генерации памяти",
                             "en": "Memory generation prompt"},
    "mem_prompt_dlg_help": {
        "ru": "Этим текстом инструктируется модель при пересборке памяти (роль "
              "system). «Сбросить к стандартному» — вернуть встроенный вариант.",
        "en": "This text instructs the model when rebuilding the memory (the "
              "system role). “Reset to default” brings back the built-in one.",
    },

    # окна пресетов (preset_ui.py)
    "editing": {"ru": "Редактирование", "en": "Editing"},
    "new_preset": {"ru": "Новый пресет", "en": "New preset"},
    "preset_win_title": {"ru": "{verb} — {title}", "en": "{verb} — {title}"},
    "generate": {"ru": "Сгенерировать", "en": "Generate"},
    "save": {"ru": "Сохранить", "en": "Save"},
    "cancel": {"ru": "Отмена", "en": "Cancel"},
    "reset_default": {"ru": "Сбросить к стандартному", "en": "Reset to default"},
    "preset_name_title": {"ru": "Пресет", "en": "Preset"},
    "preset_name_msg": {"ru": "Укажите имя / название пресета.",
                        "en": "Enter a name / title for the preset."},
    "gen_title": {"ru": "Генерация", "en": "Generation"},
    "gen_pick_model": {"ru": "Сначала выбери модель в главном окне.",
                       "en": "Pick a model in the main window first."},
    "gen_field_err": {"ru": "Не удалось сгенерировать поле:\n{err}",
                      "en": "Could not generate the field:\n{err}"},
    "gen_empty": {"ru": "Модель вернула пустой ответ.",
                  "en": "The model returned an empty reply."},
    "presets_win_title": {"ru": "Пресеты — {title}", "en": "Presets — {title}"},
    "dbl_click_edit": {"ru": "Двойной клик — редактировать",
                       "en": "Double-click to edit"},
    "create": {"ru": "Создать", "en": "New"},
    "edit": {"ru": "Редактировать", "en": "Edit"},
    "delete": {"ru": "Удалить", "en": "Delete"},
    "close": {"ru": "Закрыть", "en": "Close"},
    "pick_preset_title": {"ru": "Пресеты", "en": "Presets"},
    "pick_preset_msg": {"ru": "Выберите пресет в списке.",
                        "en": "Select a preset in the list."},
    "delete_preset_title": {"ru": "Удалить пресет", "en": "Delete preset"},
    "delete_preset_msg": {"ru": "Удалить «{name}»?", "en": "Delete “{name}”?"},

    # справочные окна
    "info_close": {"ru": "Закрыть", "en": "Close"},
    "about_title": {"ru": "О приложении — Ollama RP", "en": "About — Ollama RP"},
    "help_title": {"ru": "Помощь — установка и первый запуск",
                   "en": "Help — setup and first launch"},
    "faq_title": {"ru": "FAQ — частые вопросы", "en": "FAQ — common questions"},
}


# --- переводы данных из чистых модулей (только EN; RU = исходный модуль) ----
_BLOCK_TITLE_EN = {
    "protagonist": "Protagonist (You)",
    "character": "Character",
    "environment": "Location",
    "scenario": "Scenario",
    "system_config": "Configuration prompt",
}

_FIELD_LABEL_EN = {
    ("protagonist", "name"): "Name",
    ("protagonist", "biography"): "Biography",
    ("protagonist", "appearance"): "Appearance",
    ("protagonist", "personality"): "Personality",
    ("character", "name"): "Name",
    ("character", "biography"): "Biography",
    ("character", "appearance"): "Appearance",
    ("character", "personality"): "Personality",
    ("character", "speech_style"): "Speech style",
    ("character", "typical_phrases"): "Typical phrases (optional, one per line)",
    ("environment", "name"): "Preset name",
    ("environment", "location"): "Location",
    ("environment", "time_of_day"): "Time of day",
    ("environment", "weather"): "Weather",
    ("environment", "atmosphere"): "Atmosphere (optional)",
    ("scenario", "name"): "Preset name",
    ("scenario", "base_scenario"): "Base scenario",
    ("scenario", "additional_params"): "Extra parameters",
    ("system_config", "name"): "Preset name",
    ("system_config", "content"): "General rules for the model",
}

_THINK_LABELS_EN = {None: "as in the model", True: "force on", False: "force off"}


# Раньше было 9 пунктов, часть из них - размытые словесные ("развёрнутая
# история", "объёмная новелла") без конкретной цифры, которым модель
# следовала не особо надёжно. Сократили до 5 - у КАЖДОГО чёткий диапазон
# абзацев (числа модель держит куда лучше слов вроде «объёмная») и явное
# требование дойти до финала. Последний пункт заменил «без ограничений по
# длине» - открытый лимит эмпирически провоцировал зацикливание (у модели
# нет ориентира, когда останавливаться); теперь верхняя граница названа
# прямо, и добавлено явное «не повторяйся» - именно в этом самом длинном
# варианте деградация случалась чаще всего.
_STORY_SIZE_RU = [
    "короткая сцена, 3–5 абзацев",
    "рассказ средней длины, 10–15 абзацев",
    "длинный рассказ, 20–30 абзацев, с чёткой завязкой, развитием и финалом",
    "очень длинный рассказ на несколько сцен, 40–60 абзацев, с чёткой "
    "завязкой, развитием по сценам и финалом",
    "максимально длинно и подробно, ориентировочно 80–120 абзацев; "
    "обязательно доведи историю до логического финала, не повторяй уже "
    "написанные абзацы и реплики",
]

_STORY_SIZE_EN = [
    "short scene, 3–5 paragraphs",
    "medium-length story, 10–15 paragraphs",
    "long story, 20–30 paragraphs, with a clear setup, development and ending",
    "very long multi-scene story, 40–60 paragraphs, with a clear setup, "
    "development across scenes and ending",
    "as long and detailed as possible, roughly 80–120 paragraphs; you MUST "
    "still reach a proper ending, do not repeat paragraphs or lines "
    "already written",
]

_INF_LABEL_EN = {
    "show_avatars": "Avatars: photos next to the lines in the chat",
    "show_gallery": "Gallery: “Photo” tabs in the side panels",
    "show_emotes": "Emoticons over the interface (experimental, Windows)",
    "structured_dialogue": "Split reply: action + speech (dialogue)",
    "digest_window": "Memory: rebuild every N turns",
    "temperature": "Temperature",
    "top_p": "top_p (nucleus)",
    "top_k": "top_k",
    "min_p": "min_p",
    "repeat_penalty": "Repeat penalty",
    "repeat_last_n": "Repeat-penalty window",
    "num_predict": "Max tokens in a reply",
    "num_ctx": "Context size (num_ctx)",
    "seed": "Seed",
    "stop": "Stop strings",
    "think": "Reasoning (model's thinking)",
    "keep_alive": "Keep the model in memory",
    "stall_timeout": "“Model is silent” timeout (sec)",
    "dyn_memory_limit": "Character dynamic memory limit (characters)",
}

_INF_HELP_EN = {
    "show_avatars":
        "Dialogue mode only. If the character / protagonist has an AVATAR (one "
        "photo, set in the preset form), a small round avatar is drawn next to "
        "their lines in the chat. Off — the chat looks as before. Applies to "
        "new lines; what is already on screen is not redrawn.",
    "show_gallery":
        "Dialogue mode only. The “Photo” tab on the left (your protagonist) and "
        "on the right (the partner) shows the GALLERY — several photos from the "
        "preset form; flip through them with the arrows. Off — the tabs stay "
        "but are inactive.",
    "show_emotes":
        "Experimental, off by default. EMOTICONS are PNG silhouettes on a "
        "transparent background with different poses/emotions (set in the "
        "preset form). They are drawn in a separate transparent window OVER the "
        "interface: all share one bottom line at the bottom of the screen and "
        "may extend past the app; the protagonist's on the left, the partner's "
        "on the right. With each new reply in the chat (yours — the "
        "protagonist's, the model's — the partner's) the picture switches to "
        "the next one; a single emoticon never changes. They cannot be switched "
        "by hand. The “Emoticons” button at the top right temporarily collapses "
        "them so you can reach the left and right menus. Clicks pass through "
        "the pictures. Windows only.",
    "structured_dialogue":
        "Dialogue mode only. The model answers in exactly two parts: "
        "action/feelings (italic in the chat) and, separately, the spoken "
        "line. Works through Ollama's JSON format — reliable, but the reply "
        "appears all at once after generation, with no token streaming. "
        "While it is on, the <think> nudge for models without official "
        "reasoning is disabled (incompatible with JSON). Ignored in Story mode.",
    "digest_window":
        "Every N turns of the dialogue/story a separate hidden request (same "
        "model) builds a short “memory” of everything before that boundary and "
        "prepends it to the prompt. Between boundaries the memory is left "
        "alone — only the turns collected since the last boundary are sent "
        "verbatim. This keeps the context from growing without bound. The "
        "memory can be viewed and edited on the “Memory” tab on the right "
        "(where the “Memory prompt” button sets its own generation prompt). "
        "0/empty — off (send the whole history).",
    "temperature":
        "How random the next-word choice is. Lower (0.2–0.5) — predictable and "
        "dry, close to the most likely continuation. Higher (0.9–1.3) — more "
        "varied and lively, but the risk of incoherence grows. For roleplay "
        "usually 0.7–1.0.",
    "top_p":
        "Keep only the most likely words until their probabilities add up to "
        "p, drop the rest of the tail. 0.9 is a soft cut. Lower — stricter and "
        "safer; closer to 1.0 — allow more unexpected moves.",
    "top_k":
        "Consider only the K most likely words at each step. 20–40 is typical. "
        "0 — no count limit (only temperature / top_p / min_p apply).",
    "min_p":
        "Drop words whose probability is below min_p of the top word's "
        "probability. A modern alternative to top_p: 0.05–0.1 keeps coherence "
        "well at high temperature. 0 — off.",
    "repeat_penalty":
        "How much to lower the probability of words seen recently. 1.0 — no "
        "penalty. 1.03–1.08 — slightly fewer loops. Above 1.1 it often works "
        "against you: it also suppresses common function words and can push "
        "the model toward broken phrasing or another language. If you see "
        "mixed languages, drop it to 1.03–1.05 and narrow the window below.",
    "repeat_last_n":
        "How many recent tokens the repeat penalty looks at. 32–64 is safe. A "
        "wide window (256+) provokes language mixing more strongly. 0 — off, "
        "-1 — the whole context.",
    "num_predict":
        "Upper limit on the length of a single reply. -1 — no limit (until the "
        "thought ends or a stop string). Set e.g. 300–600 to cut off walls of "
        "text. ~1 token ≈ 0.75 of a word.",
    "num_ctx":
        "How many tokens the model sees at all: the system prompt plus the "
        "whole dialogue. Anything that does not fit is silently dropped from "
        "the start by Ollama. Larger (8192, 16384) — remembers longer, but "
        "noticeably more RAM/VRAM and a model reload when the value changes. "
        "Do not set it above what the model itself supports.",
    "seed":
        "Random generator seed. Empty — every reply is different. A fixed "
        "number — with the same input the reply reproduces exactly (handy for "
        "comparing settings).",
    "stop":
        "If any of these strings appears in the reply, generation stops right "
        "there. One string per line. Example: “You:” so the model does not "
        "continue the dialogue for you. Empty — not used.",
    "think":
        "“as in the model” — auto: a model with official reasoning support "
        "(the “Reasoning: enabled” badge by the model list) thinks; the rest "
        "are left alone. “force on” — make it think: a supported model gets "
        "the think parameter, a model WITHOUT support gets a prompt "
        "instruction to reason in <think>…</think> (as e.g. Ministral-Reasoning "
        "from HuggingFace does). “force off” — forbid it (for supported "
        "models; e.g. qwen3 thinks by default). The reasoning always goes to "
        "the Logs panel, never to the chat.",
    "keep_alive":
        "How long the model stays loaded after a reply. “5m” — default, "
        "“30m”, “-1” — keep loaded permanently (faster next replies, memory "
        "stays used), “0” — unload immediately.",
    "stall_timeout":
        "If a reply that has already started (including the “thinking” stage) "
        "goes silent — the model sends no token for longer than this many "
        "seconds — it is considered hung: the request is aborted and sent "
        "again (up to 3 times, then an error). While the model keeps sending "
        "tokens (thinking or writing) the timer does not fire; the time before "
        "the very first token (model loading, long-prompt processing) does not "
        "count. Empty — 30 s, 0 — off. Every resend is visible in the "
        "generation status and in Logs (an upper-case heading).",
    "dyn_memory_limit":
        "Maximum size of a character's dynamic memory (the checkbox in the "
        "character's “Manage” form). The memory never grows beyond it: the model "
        "is told to fit in, and the app cuts any excess itself (oldest items "
        "first). A larger limit — the character remembers more, but the memory "
        "takes more context on every reply. Empty — 4000, allowed 500 to 20000.",
}


def block_title(block: str) -> str:
    from blocks import BLOCK_SPECS
    if _lang == "en":
        return _BLOCK_TITLE_EN.get(block, BLOCK_SPECS[block]["title"])
    return BLOCK_SPECS[block]["title"]


def field_label(block: str, attr: str) -> str:
    from blocks import BLOCK_SPECS
    if _lang == "en":
        if (block, attr) in _FIELD_LABEL_EN:
            return _FIELD_LABEL_EN[(block, attr)]
    for a, label, _w in BLOCK_SPECS[block]["fields"]:
        if a == attr:
            return label
    return attr


def field_labels(block: str) -> dict:
    from blocks import BLOCK_SPECS
    return {a: field_label(block, a) for a, _l, _w in BLOCK_SPECS[block]["fields"]}


def think_labels() -> dict:
    from inference_spec import THINK_LABELS
    return dict(_THINK_LABELS_EN) if _lang == "en" else dict(THINK_LABELS)


def think_from_label() -> dict:
    return {label: value for value, label in think_labels().items()}


def story_size_choices(none_choice: str) -> list:
    body = _STORY_SIZE_EN if _lang == "en" else _STORY_SIZE_RU
    return [none_choice] + list(body)


def inf_label(attr: str, ru_default: str) -> str:
    if _lang == "en":
        return _INF_LABEL_EN.get(attr, ru_default)
    return ru_default


def inf_help(attr: str, ru_default: str) -> str:
    if _lang == "en":
        return _INF_HELP_EN.get(attr, ru_default)
    return ru_default
