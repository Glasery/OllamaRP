"""
Тексты справочных окон «О приложении», «Помощь» и «FAQ» на двух языках.

Формат: список блоков. Блок - кортеж:
  ("h",  "Заголовок раздела")
  ("q",  "Вопрос (в FAQ)")
  ("p",  "Абзац обычного текста")
  ("li", "Пункт списка")
Рендер живёт в gui.App._open_info_window. `blocks(name)` отдаёт список
под текущий язык (i18n.get_lang()).
"""
import i18n


def blocks(name: str) -> list:
    """name: 'about' | 'help' | 'faq' | 'cheatsheet'. Список блоков под язык."""
    lang = i18n.get_lang()
    return _DATA[name].get(lang) or _DATA[name]["ru"]


# ========================= О ПРИЛОЖЕНИИ (RU) ==============================
_ABOUT_RU = [
    ("h", "Что это"),
    ("p", "Ollama RP — настольное приложение для ролевых игр и генерации "
          "историй с локальными языковыми моделями через Ollama. Всё "
          "работает на вашем компьютере: ничего не уходит в интернет, нет "
          "подписок, лимитов по количеству сообщений и внешней цензуры."),

    ("h", "Зачем нужно"),
    ("li", "Удобный интерфейс вместо голой командной строки «ollama run»."),
    ("li", "Персонажи, локации, сценарии и правила хранятся как "
           "переиспользуемые пресеты — собрал один раз, подключаешь в любой "
           "сцене в любом сочетании."),
    ("li", "Видно всё, что реально уходит в модель, и её полный ответ — "
           "панель Logs справа. Никакой скрытой «магии промпта»."),
    ("li", "Отдельно хранится «бегущая память», чтобы длинный диалог не "
           "упирался в размер контекста модели."),

    ("h", "Три режима работы"),
    ("p", "Режим переключается вкладками над центральной колонкой."),
    ("li", "Диалог — общение с одним персонажем по очереди. Вы вводите своё "
           "действие и/или реплику, модель отвечает от лица персонажа. Ответ "
           "делится на действие/чувства (курсивом) и прямую речь."),
    ("li", "История — генерация цельного текста по заданным параметрам: "
           "главный герой, один или несколько персонажей, сценарий, желаемый "
           "объём. Пошаговый ввод не нужен — можно просто просить продолжать."),
    ("li", "Чат — режим без ролевых промптов и сцены. System-промпт не "
           "отправляется, влияют только параметры генерации и сама модель. "
           "Удобно тестировать поведение модели «как есть»."),

    ("h", "Из чего собирается сцена"),
    ("p", "Вкладка «Сцена» — независимые блоки: Главный герой (Вы), "
          "Персонаж(и), Локация, Сценарий, Конфигурация (общие правила "
          "поведения модели). У каждого блока свой список сохранённых "
          "пресетов; выбранный вариант подставляется в промпт."),
    ("li", "Поле «Дополнительные детали» — свободные заметки к конкретной "
           "сцене. Не сохраняются в пресет и добавляются в промпт, только "
           "если заполнены."),
    ("li", "Кнопка «Сгенерировать» рядом с полями конструктора просит "
           "модель заполнить поле, опираясь на уже введённые. Имя персонажа "
           "всегда вводится вручную."),

    ("h", "Память (режим «Диалог»)"),
    ("p", "Раз в N ходов приложение отдельным скрытым запросом сжимает всё, "
          "что вышло за пределы «Размера истории», в короткую сводку и "
          "подставляет её в начало промпта. Так контекст не разрастается "
          "бесконечно. Промпт сжатия, готовую сводку и ручную пересборку "
          "можно посмотреть на вкладке «Память» справа."),

    ("h", "Параметры генерации"),
    ("p", "Вкладка «Настройки»: температура, top_p / top_k, min_p, штрафы за "
          "повтор, длина ответа (num_predict), размер контекста (num_ctx), "
          "seed, стоп-строки, reasoning, keep_alive. У каждого поля есть "
          "пояснение простым языком."),
    ("li", "Пустое поле = параметр не отправляется, действует значение по "
           "умолчанию модели."),
    ("li", "«Optimal» возвращает рекомендованные значения, «Очистить» — "
           "убирает всё (модель решает сама)."),

    ("h", "Язык интерфейса"),
    ("p", "Переключатель RU / EN в правом верхнем углу меняет язык всего "
          "интерфейса на лету, а также переписывает скрытые промпты: в режиме "
          "EN модель просят писать по-английски, а не по-русски. Уже "
          "сохранённые пресеты-примеры не переводятся — это ваши данные."),

    ("h", "Reasoning (размышления)"),
    ("p", "Индикатор в верхней части окна показывает, поддерживает ли "
          "выбранная модель официальный режим размышлений (enabled) или нет "
          "(disabled). Для моделей без него приложение может мягко попросить "
          "модель рассуждать прямо в тексте промпта."),

    ("h", "Где лежат данные"),
    ("p", "Пресеты, настройки и служебные файлы — обычные JSON в папке "
          "пользователя (в Windows это %APPDATA%\\OllamaRP). Экспорт диалога/"
          "истории — текстовый файл туда, куда укажете. Интернет нужен только "
          "для скачивания самой Ollama и моделей."),
]

# ========================= ABOUT (EN) ===================================
_ABOUT_EN = [
    ("h", "What this is"),
    ("p", "Ollama RP is a desktop app for roleplay and story generation with "
          "local language models via Ollama. Everything runs on your computer: "
          "nothing goes to the internet, there are no subscriptions, message "
          "limits or third-party censorship."),

    ("h", "Why it exists"),
    ("li", "A convenient interface instead of the bare “ollama run” command line."),
    ("li", "Characters, locations, scenarios and rules are stored as reusable "
           "presets — build one once, plug it into any scene in any combination."),
    ("li", "You can see everything that actually goes to the model and its full "
           "reply — the Logs panel on the right. No hidden “prompt magic”."),
    ("li", "A separate “running memory” keeps a long dialogue from hitting the "
           "model's context limit."),

    ("h", "Three working modes"),
    ("p", "The mode is switched by the tabs above the centre column."),
    ("li", "Dialogue — turn-by-turn exchange with one character. You enter your "
           "action and/or line, the model replies as the character. The reply "
           "is split into action/feelings (italic) and direct speech."),
    ("li", "Story — generation of a whole text from preset parameters: the "
           "protagonist, one or more characters, a scenario, the desired "
           "length. No step-by-step input needed — you can just ask it to "
           "continue."),
    ("li", "Chat — a mode with no roleplay prompts and no scene. No system "
           "prompt is sent; only the generation parameters and the model "
           "itself matter. Handy for testing the model's behaviour as is."),

    ("h", "What a scene is built from"),
    ("p", "The “Scene” tab holds independent blocks: Protagonist (You), "
          "Character(s), Location, Scenario, Configuration (general rules for "
          "the model). Each block has its own list of saved presets; the "
          "selected one is inserted into the prompt."),
    ("li", "The “Additional details” field is free-form notes for a specific "
           "scene. It is not saved into a preset and is added to the prompt "
           "only when filled in."),
    ("li", "The “Generate” button next to the builder fields asks the model to "
           "fill a field based on the ones already entered. A character's name "
           "is always typed by hand."),

    ("h", "Memory (Dialogue mode)"),
    ("p", "Every N turns the app uses a separate hidden request to compress "
          "everything that has scrolled past the “Story length” window into a "
          "short summary and prepends it to the prompt. This keeps the context "
          "from growing without bound. The compression prompt, the current "
          "summary and a manual rebuild are on the “Memory” tab on the right."),

    ("h", "Generation parameters"),
    ("p", "The “Settings” tab: temperature, top_p / top_k, min_p, repeat "
          "penalties, reply length (num_predict), context size (num_ctx), "
          "seed, stop strings, reasoning, keep_alive. Every field has a "
          "plain-language explanation."),
    ("li", "An empty field = the parameter is not sent and the model's default "
           "applies."),
    ("li", "“Optimal” restores the recommended values, “Clear” removes "
           "everything (the model decides on its own)."),

    ("h", "Interface language"),
    ("p", "The RU / EN switch in the top-right corner changes the language of "
          "the whole interface on the fly, and also rewrites the hidden "
          "prompts: in EN mode the model is asked to write in English rather "
          "than Russian. Already-saved example presets are not translated — "
          "they are your data."),

    ("h", "Reasoning"),
    ("p", "The indicator at the top of the window shows whether the selected "
          "model supports an official reasoning mode (enabled) or not "
          "(disabled). For models without it the app can gently ask the model "
          "to reason right in the prompt text."),

    ("h", "Where the data lives"),
    ("p", "Presets, settings and helper files are plain JSON in the user "
          "folder (on Windows that is %APPDATA%\\OllamaRP). Exporting a "
          "dialogue/story writes a text file wherever you point it. The "
          "internet is only needed to download Ollama itself and the models."),
]

# ========================= ПОМОЩЬ (RU) ==================================
_HELP_RU = [
    ("h", "Коротко"),
    ("p", "Нужны три вещи: Python (на нём работает это приложение), Ollama "
          "(локальный сервер моделей) и хотя бы одна скачанная модель. Ниже — "
          "по шагам, от нуля до первого диалога."),

    ("h", "Шаг 1. Python"),
    ("li", "Скачайте Python 3.10 или новее с python.org. Для Windows — "
           "«Windows installer (64-bit)»."),
    ("li", "В начале установки отметьте галочку «Add python.exe to PATH»."),
    ("li", "Проверка: откройте командную строку (cmd / PowerShell) и введите "
           "python --version — должна показаться версия."),

    ("h", "Шаг 2. Зависимости приложения"),
    ("li", "Откройте командную строку в папке приложения."),
    ("li", "Установите библиотеки: pip install -r requirements.txt "
           "(если файла нет — pip install customtkinter requests pillow)."),
    ("li", "Если приложение идёт с папкой venv — сначала активируйте "
           "окружение (venv\\Scripts\\activate в Windows)."),

    ("h", "Шаг 3. Ollama"),
    ("li", "Скачайте установщик с ollama.com/download и установите его."),
    ("li", "После установки Ollama сама работает фоновым сервером по адресу "
           "http://localhost:11434."),
    ("li", "Проверка: откройте этот адрес в браузере — должно быть написано "
           "«Ollama is running»."),

    ("h", "Шаг 4. Модель"),
    ("li", "Скачайте модель командой, например: ollama pull qwen2.5:7b"),
    ("li", "Посмотреть скачанное: ollama list. Модели лежат локально и "
           "работают без интернета."),
    ("li", "Неплохо стартуют для русскоязычного ролплея: qwen2.5:7b, "
           "qwen2.5:14b, gemma2:9b, saiga_llama3_8b, Vikhr-Nemo-12B. Для "
           "английского подойдёт почти любая современная модель."),

    ("h", "Шаг 5. Первый запуск"),
    ("li", "Запустите приложение (python gui.py или ярлык)."),
    ("li", "Вверху выберите модель. Если список пуст — нажмите «Обновить "
           "список» (Ollama должна быть запущена)."),
    ("li", "Вкладка «Сцена»: выберите или создайте Главного героя, Персонажа, "
           "при желании Локацию и Сценарий, а также Конфигурацию (общие "
           "правила). Минимум для старта — Персонаж и Конфигурация."),
    ("li", "Режим «Диалог»: напишите своё действие и/или реплику и нажмите "
           "«Отправить» (или Ctrl+Enter). Первый ответ модели появится в "
           "центральном окне."),

    ("h", "Выбор модели под видеокарту"),
    ("p", "Главный ориентир — объём видеопамяти (VRAM). Модель в кванте Q4 "
          "занимает примерно: 7–8B — 5–6 ГБ, 9B — 6–7 ГБ, 12–14B — 8–10 ГБ, "
          "27–32B — 18–22 ГБ, 70B — 40+ ГБ. Плюс запас под контекст."),
    ("li", "6 ГБ (GTX 1060, RTX 2060, RTX 3050): модели 7–8B в Q4."),
    ("li", "8 ГБ (RTX 3060 Ti, RTX 4060): 7–9B свободно, 12–14B в Q4 впритык."),
    ("li", "12 ГБ (RTX 3060 12G, RTX 4070): 12–14B комфортно, контекст "
           "побольше."),
    ("li", "16 ГБ (RTX 4060 Ti 16G, RTX 4070 Ti Super): 14B с большим "
           "контекстом, 27B в Q4."),
    ("li", "24 ГБ (RTX 3090, RTX 4090): 27–32B комфортно, 70B — только "
           "частично / в сильном сжатии."),
    ("li", "Без дискретной видеокарты: модель считается на процессоре и в "
           "ОЗУ — работает, но медленно. Берите 3–8B и небольшой num_ctx."),
    ("li", "Если модель не влезает в VRAM целиком, Ollama переносит часть "
           "слоёв в ОЗУ и скорость резко падает. Тогда уменьшите размер "
           "модели, возьмите более сжатый квант или снизьте num_ctx."),
    ("p", "Разбор частых проблем и вопросов — в отдельном окне «FAQ»."),
]

# ========================= HELP (EN) ===================================
_HELP_EN = [
    ("h", "In short"),
    ("p", "You need three things: Python (this app runs on it), Ollama (a "
          "local model server) and at least one downloaded model. Below — step "
          "by step, from zero to the first dialogue."),

    ("h", "Step 1. Python"),
    ("li", "Download Python 3.10 or newer from python.org. For Windows — the "
           "“Windows installer (64-bit)”."),
    ("li", "At the start of the installer tick “Add python.exe to PATH”."),
    ("li", "Check: open a terminal (cmd / PowerShell) and run python --version "
           "— it should print a version."),

    ("h", "Step 2. App dependencies"),
    ("li", "Open a terminal in the app folder."),
    ("li", "Install the libraries: pip install -r requirements.txt (if there "
           "is no such file — pip install customtkinter requests pillow)."),
    ("li", "If the app ships with a venv folder — activate the environment "
           "first (venv\\Scripts\\activate on Windows)."),

    ("h", "Step 3. Ollama"),
    ("li", "Download the installer from ollama.com/download and install it."),
    ("li", "After installation Ollama runs as a background server at "
           "http://localhost:11434."),
    ("li", "Check: open that address in a browser — it should say “Ollama is "
           "running”."),

    ("h", "Step 4. A model"),
    ("li", "Download a model, e.g.: ollama pull qwen2.5:7b"),
    ("li", "See what is downloaded: ollama list. Models live locally and work "
           "offline."),
    ("li", "Good starting points: qwen2.5:7b, qwen2.5:14b, gemma2:9b, "
           "llama3.1:8b, mistral-nemo. Almost any modern model handles English."),

    ("h", "Step 5. First launch"),
    ("li", "Start the app (python gui.py or a shortcut)."),
    ("li", "Pick a model at the top. If the list is empty — press “Refresh "
           "list” (Ollama must be running)."),
    ("li", "The “Scene” tab: pick or create a Protagonist, a Character, "
           "optionally a Location and Scenario, plus a Configuration (general "
           "rules). The minimum to start — a Character and a Configuration."),
    ("li", "“Dialogue” mode: type your action and/or line and press “Send” (or "
           "Ctrl+Enter). The model's first reply appears in the centre panel."),

    ("h", "Choosing a model for your GPU"),
    ("p", "The main guide is the amount of video memory (VRAM). A model at Q4 "
          "quantization takes roughly: 7–8B — 5–6 GB, 9B — 6–7 GB, 12–14B — "
          "8–10 GB, 27–32B — 18–22 GB, 70B — 40+ GB. Plus headroom for the "
          "context."),
    ("li", "6 GB (GTX 1060, RTX 2060, RTX 3050): 7–8B models at Q4."),
    ("li", "8 GB (RTX 3060 Ti, RTX 4060): 7–9B comfortably, 12–14B at Q4 "
           "tight."),
    ("li", "12 GB (RTX 3060 12G, RTX 4070): 12–14B comfortably, a larger "
           "context."),
    ("li", "16 GB (RTX 4060 Ti 16G, RTX 4070 Ti Super): 14B with a large "
           "context, 27B at Q4."),
    ("li", "24 GB (RTX 3090, RTX 4090): 27–32B comfortably, 70B only "
           "partially / heavily quantized."),
    ("li", "No discrete GPU: the model runs on the CPU and in RAM — it works, "
           "but slowly. Use 3–8B and a small num_ctx."),
    ("li", "If a model does not fit fully in VRAM, Ollama moves some layers to "
           "RAM and speed drops sharply. Then use a smaller model, a more "
           "compressed quant, or lower num_ctx."),
    ("p", "A breakdown of common problems and questions is in the separate "
          "“FAQ” window."),
]

# ========================= FAQ (RU) ====================================
_FAQ_RU = [
    ("p", "Короткие ответы на то, что спрашивают чаще всего. Пошаговая "
          "установка — в окне «Помощь», обзор возможностей — в «О приложении»."),

    ("h", "Установка и запуск"),

    ("q", "Приложение не запускается / ошибка при старте."),
    ("p", "Нужен Python 3.10 или новее и установленные зависимости: в папке "
          "приложения выполните pip install -r requirements.txt (или "
          "pip install customtkinter requests pillow). Запускать — main.py или "
          "gui.py тем же Python, где стоят библиотеки (если есть папка venv — "
          "сначала активируйте окружение)."),

    ("q", "Кнопка «Обновить список» не находит ни одной модели."),
    ("p", "Ollama не запущена или слушает не по адресу http://localhost:11434. "
          "Проверьте: откройте этот адрес в браузере — должно быть «Ollama is "
          "running». Если нет — запустите Ollama. Затем убедитесь, что модели "
          "вообще скачаны: ollama list в командной строке."),

    ("q", "Нужен ли интернет во время игры?"),
    ("p", "Нет. Интернет нужен один раз — скачать Ollama и модели. Дальше всё "
          "работает офлайн, запросы никуда наружу не уходят."),

    ("q", "Мои переписки и персонажи куда-то отправляются?"),
    ("p", "Нет. Всё лежит локально: пресеты и настройки — JSON-файлы в "
          "%APPDATA%\\OllamaRP, экспорт диалога — текстовый файл туда, куда "
          "вы сами укажете. Запрос уходит только на локальную Ollama."),

    ("q", "Долгий первый ответ после запуска — это нормально?"),
    ("p", "Да. На первый запрос модель грузится в память (в VRAM или ОЗУ). "
          "Дальше она держится там время keep_alive и отвечает сразу. Смена "
          "модели снова требует загрузки."),

    ("h", "Язык"),

    ("q", "Как переключить интерфейс на английский?"),
    ("p", "Переключатель RU / EN в правом верхнем углу. Весь текст интерфейса "
          "меняется сразу, без перезапуска, а сцена, история чата и настройки "
          "сохраняются. Выбор языка запоминается между запусками."),

    ("q", "Влияет ли язык на то, как отвечает модель?"),
    ("p", "Да. В режиме EN скрытые промпты переписываются под английский: "
          "требование «пиши только по-русски» заменяется на «пиши только "
          "по-английски», а служебные подписи в промпте (Персонаж, Локация и "
          "т.п.) становятся английскими. Пресеты-примеры остаются на том "
          "языке, на котором были сохранены."),

    ("h", "Модели и производительность"),

    ("q", "Какую модель выбрать под мою видеокарту?"),
    ("p", "Ориентир — объём видеопамяти. Модель в кванте Q4 занимает примерно: "
          "7–8B — 5–6 ГБ, 9B — 6–7 ГБ, 12–14B — 8–10 ГБ, 27–32B — 18–22 ГБ. "
          "6 ГБ → 7–8B; 8 ГБ → 7–9B (12–14B впритык); 12 ГБ → 12–14B; "
          "16 ГБ → 14B с большим контекстом или 27B; 24 ГБ → 27–32B. Без "
          "дискретной GPU — 3–8B на процессоре, медленно. Подробнее — в окне "
          "«Помощь»."),

    ("q", "Что такое «квант» и Q4_K_M, Q5_K_M, Q8_0?"),
    ("p", "Квантизация — сжатие весов модели, чтобы занимала меньше памяти. "
          "Число примерно отражает биты на вес: Q4 — вдвое меньше места, чем "
          "Q8, ценой небольшого падения качества. Практичный выбор — Q4_K_M "
          "или Q5_K_M. Q8 берут, только если памяти с запасом."),

    ("q", "Ответы очень медленные."),
    ("p", "Скорее всего модель не помещается в видеопамять целиком и часть "
          "слоёв считается на процессоре. Возьмите модель меньше или более "
          "сжатый квант, уменьшите num_ctx на вкладке «Настройки». Проверить "
          "загрузку GPU можно командой ollama ps (столбец PROCESSOR)."),

    ("q", "Приложение считает на процессоре, хотя видеокарта есть."),
    ("p", "Ollama использует GPU автоматически для поддерживаемых NVIDIA "
          "(CUDA) и свежих AMD (ROCm). Обновите драйверы видеокарты. Если "
          "модель просто не влезает в VRAM — Ollama откатывается на CPU; "
          "возьмите модель поменьше."),

    ("q", "Где взять другие модели?"),
    ("p", "Каталог — ollama.com/library (ollama pull <имя>). GGUF-модели с "
          "HuggingFace ставятся напрямую: ollama pull hf.co/<автор>/<репо>:"
          "<квант>. Скачанное показывает ollama list."),

    ("h", "Ролевые сцены и промпты"),

    ("q", "Как добавить фото персонажу или своему герою?"),
    ("p", "«Настроить» у блока «Персонаж» или «Главный герой (Вы)» — в форме три "
          "необязательных вида фото, каждый включается своей галкой в Settings. "
          "1) Аватар — одно фото: в режиме «Диалог» рисуется маленькой круглой "
          "аватаркой рядом с репликами. 2) Галерея — несколько фото, видны "
          "только во вкладке «Фото» боковых панелей (слева герой, справа "
          "собеседник), там же стрелки для просмотра. 3) Эмотиконы — только "
          "PNG на прозрачном фоне (другие файлы не загрузятся); показываются "
          "поверх интерфейса, меняются на каждый ответ в чате, стоят на нижней "
          "границе экрана; кнопка «Эмотиконы» вверху переключает режимы: все, только "
          "собеседник, скрыты — чтобы добраться до меню. Эмотиконы — экспериментально, только Windows, "
          "выключены по умолчанию. Фото копируются в папку photos рядом с "
          "пресетами (оригинал не меняется) и в промпт модели не попадают. "
          "Нужен пакет Pillow (pip install pillow); без него всё работает, "
          "просто без фото."),

    ("q", "Как сохранить диалог и продолжить его позже?"),
    ("p", "Кнопка «Сохранения…» под «Экспорт…» в чате. Введите название и "
          "нажмите «Сохранить как новое» — запишется весь диалог: чат, история, "
          "память, выбранные пресеты, режим, модель и недописанные поля ввода. "
          "Позже (в том числе после перезапуска приложения) откройте это окно и "
          "нажмите «Загрузить» — всё вернётся ровно с этого места. «Перезаписать» "
          "обновляет сохранение, «Удалить» убирает. Загрузка заменяет текущий "
          "диалог (сначала сохраните его, если он нужен). Logs и Settings в "
          "сохранение не входят. Файлы лежат в папке sessions рядом с "
          "пресетами."),

    ("q", "Что такое динамическая память персонажа?"),
    ("p", "Галка в «Настроить» у персонажа (только собеседник). Приложение "
          "само ведёт краткий список самого важного, что с персонажем "
          "случилось: события, отношения, статусы, внешность — он хранится в "
          "пресете и переживает отдельные диалоги, так что персонаж помнит "
          "прошлые встречи. Обновляется отдельным запросом в ходе диалога (не в "
          "тот же ход, когда собиралась память диалога) и не растёт выше "
          "лимита (по умолчанию 4000 символов, настраивается в Settings). Текст можно править руками, есть кнопка "
          "«Очистить динамическую память». Нужна включённая память диалога "
          "(Settings → «Размер истории» больше 0). При сохранении диалога "
          "приложение спросит, обновить ли её, чтобы не потерять последние "
          "события."),

    ("q", "Чем отличаются режимы Диалог, История и Чат?"),
    ("p", "Диалог — пошаговый отыгрыш с одним персонажем, ответ делится на "
          "действие (курсивом) и речь. История — генерация цельного текста по "
          "параметрам сцены, можно несколько персонажей и заданный объём. "
          "Чат — без ролевых промптов вообще, чистая проверка модели и "
          "параметров."),

    ("q", "Модель отвечает не на том языке или сбивается."),
    ("p", "Проверьте переключатель RU / EN — он задаёт язык скрытых промптов. "
          "Добавьте явное правило в блок «Конфигурация» (например: «Всегда "
          "отвечай только по-русски»). Держите repeat_penalty мягким "
          "(около 1.05) — высокие значения провоцируют переход на другой "
          "язык. Помогает и выбор модели, обученной на нужном языке."),

    ("q", "Модель игнорирует характер персонажа или правила сцены."),
    ("p", "Частые причины: слишком длинные или противоречивые блоки, "
          "перегруженная «Конфигурация», маленькая модель (7–8B держит "
          "инструкции хуже), малый num_ctx — начало промпта вытесняется. "
          "Сократите описания до главного, поднимите num_ctx, попробуйте "
          "модель побольше."),

    ("q", "Модель повторяется или зацикливается."),
    ("p", "Немного поднимите repeat_penalty (1.05 → 1.1) и temperature, "
          "задайте min_p около 0.05–0.08. Проверьте, что num_ctx не слишком "
          "мал. Иногда достаточно удалить последний зацикленный ответ и "
          "сгенерировать заново."),

    ("q", "Как сделать ответы длиннее или короче?"),
    ("p", "Длина: увеличьте num_predict (или -1 = без лимита), в режиме "
          "«История» задайте «Размер истории», прямо попросите в реплике. "
          "Короче: небольшой num_predict и правило в «Конфигурации» вроде "
          "«не больше 2–3 абзацев за ответ»."),

    ("q", "Ответ пустой или обрывается на полуслове."),
    ("p", "Увеличьте num_predict — скорее всего упёрлись в лимит. Проверьте "
          "стоп-строки в «Настройках»: лишняя стоп-строка может резать ответ "
          "в самом начале."),

    ("q", "Зачем поле «Дополнительные детали» и сохраняется ли оно?"),
    ("p", "Это свободные заметки к текущей сцене (настроение, время, скрытые "
          "обстоятельства). Добавляются в промпт, только если заполнены. В "
          "пресет не сохраняются — при смене сцены очистите вручную."),

    ("q", "Что делает кнопка «Сгенерировать» у полей персонажа?"),
    ("p", "Просит модель придумать содержимое именно этого поля, опираясь на "
          "уже заполненные поля того же пресета. Имя всегда вводится вручную. "
          "Запрос и ответ видны в панели Logs."),

    ("h", "Память и настройки"),

    ("q", "Как работает «бегущая память» и когда её отключать?"),
    ("p", "В режиме «Диалог» раз в N ходов всё, что вышло за пределы «Размера "
          "истории», сжимается скрытым запросом в короткую сводку и "
          "подставляется в начало промпта — так контекст не переполняется. "
          "Для коротких сессий память не нужна: поставьте 0 (поле «Память: "
          "пересборка каждые N ходов» на вкладке «Настройки»)."),

    ("q", "Что выбрать в настройке Reasoning?"),
    ("p", "По умолчанию — «как у модели»: модель с поддержкой размышлений "
          "думает сама, остальные не трогаются. «Включить» полезно для "
          "*-Reasoning сборок без официальной поддержки. «Выключить» — чтобы "
          "запретить размышления модели, которая думает всегда (например "
          "qwen3). Сами размышления идут в Logs, в чат — только ответ."),

    ("q", "Как сбросить параметры генерации к нормальным?"),
    ("p", "Кнопка «Optimal» на вкладке «Настройки» возвращает рекомендованный "
          "для ролплея набор. «Очистить» убирает все значения — тогда всё "
          "решает сама модель."),

    ("q", "Что делает «Очистить всё» под чатом?"),
    ("p", "Стирает текущий диалог, бегущую память и панель Logs. Пресеты, "
          "содержимое блоков сцены и «Настройки» не трогает."),

    ("q", "Можно ли поменять модель посреди диалога?"),
    ("p", "Да — просто выберите другую вверху. История сохранится, но стиль "
          "ответов сменится, а другой модели может понадобиться повторная "
          "загрузка в память."),

    ("q", "Как сохранить готовый диалог или историю?"),
    ("p", "Кнопка «Экспорт…» под чатом — сохраняет всю переписку с шапкой "
          "сцены в текстовый файл."),
]

# ========================= FAQ (EN) ====================================
_FAQ_EN = [
    ("p", "Short answers to the most common questions. Step-by-step setup is "
          "in the “Help” window, a feature overview is in “About”."),

    ("h", "Setup and launch"),

    ("q", "The app will not start / an error on launch."),
    ("p", "You need Python 3.10 or newer and installed dependencies: in the "
          "app folder run pip install -r requirements.txt (or pip install "
          "customtkinter requests pillow). Run main.py or gui.py with the same Python "
          "that has the libraries (if there is a venv folder — activate it "
          "first)."),

    ("q", "“Refresh list” finds no models at all."),
    ("p", "Ollama is not running or is not listening at "
          "http://localhost:11434. Check: open that address in a browser — it "
          "should say “Ollama is running”. If not — start Ollama. Then make "
          "sure models are actually downloaded: ollama list in a terminal."),

    ("q", "Do I need the internet while playing?"),
    ("p", "No. The internet is needed once — to download Ollama and models. "
          "After that everything works offline; requests never leave your "
          "machine."),

    ("q", "Are my chats and characters sent anywhere?"),
    ("p", "No. Everything is local: presets and settings are JSON files in "
          "%APPDATA%\\OllamaRP, a dialogue export is a text file wherever you "
          "point it. The request only goes to your local Ollama."),

    ("q", "A slow first reply after launch — is that normal?"),
    ("p", "Yes. On the first request the model loads into memory (VRAM or "
          "RAM). After that it stays there for keep_alive and replies right "
          "away. Switching models requires loading again."),

    ("h", "Language"),

    ("q", "How do I switch the interface to English?"),
    ("p", "The RU / EN switch in the top-right corner. All interface text "
          "changes at once, with no restart, while the scene, chat history "
          "and settings are kept. The choice is remembered between launches."),

    ("q", "Does the language affect how the model replies?"),
    ("p", "Yes. In EN mode the hidden prompts are rewritten for English: the "
          "“write only in Russian” rule becomes “write only in English”, and "
          "the helper labels in the prompt (Character, Location, etc.) become "
          "English. Example presets stay in the language they were saved in."),

    ("h", "Models and performance"),

    ("q", "Which model should I pick for my GPU?"),
    ("p", "The guide is video memory. A model at Q4 takes roughly: 7–8B — 5–6 "
          "GB, 9B — 6–7 GB, 12–14B — 8–10 GB, 27–32B — 18–22 GB. 6 GB → 7–8B; "
          "8 GB → 7–9B (12–14B tight); 12 GB → 12–14B; 16 GB → 14B with a "
          "large context or 27B; 24 GB → 27–32B. No discrete GPU — 3–8B on "
          "the CPU, slowly. More detail is in the “Help” window."),

    ("q", "What is “quantization” and Q4_K_M, Q5_K_M, Q8_0?"),
    ("p", "Quantization compresses the model's weights so it takes less "
          "memory. The number roughly reflects bits per weight: Q4 is half "
          "the size of Q8 at the cost of a small quality drop. A practical "
          "choice is Q4_K_M or Q5_K_M. Q8 is only worth it with memory to "
          "spare."),

    ("q", "Replies are very slow."),
    ("p", "The model probably does not fit fully in VRAM and some layers run "
          "on the CPU. Use a smaller model or a more compressed quant, lower "
          "num_ctx on the “Settings” tab. Check GPU usage with ollama ps (the "
          "PROCESSOR column)."),

    ("q", "The app runs on the CPU even though I have a GPU."),
    ("p", "Ollama uses the GPU automatically for supported NVIDIA (CUDA) and "
          "recent AMD (ROCm). Update your GPU drivers. If the model simply "
          "does not fit in VRAM, Ollama falls back to the CPU; use a smaller "
          "model."),

    ("q", "Where do I get other models?"),
    ("p", "The catalog is ollama.com/library (ollama pull <name>). GGUF "
          "models from HuggingFace install directly: ollama pull "
          "hf.co/<author>/<repo>:<quant>. ollama list shows what is "
          "downloaded."),

    ("h", "Roleplay scenes and prompts"),

    ("q", "How do I add a photo to a character or to my own hero?"),
    ("p", "“Manage” on the “Character” or “Protagonist (You)” block — the form "
          "has three optional kinds of pictures, each switched on by its own "
          "checkbox in Settings. 1) Avatar — one photo, drawn as a small round "
          "avatar next to the lines in “Dialogue” mode. 2) Gallery — several "
          "photos, shown only in the “Photo” tab of the side panels (hero on "
          "the left, partner on the right) with arrows to browse them. "
          "3) Emoticons — PNG on a transparent background only (other files "
          "will not load); drawn over the interface, switching with every reply "
          "in the chat, standing on the bottom edge of the screen; the "
          "“Emoticons” button at the top cycles the modes: all, companion only, "
          "hidden — so you can reach the menus. Emoticons are experimental, Windows only, off by "
          "default. Pictures are copied into a photos folder next to the "
          "presets (the original is untouched) and never go into the model's "
          "prompt. Needs the Pillow package (pip install pillow); without it "
          "everything works, just without photos."),

    ("q", "How do I save a dialogue and continue it later?"),
    ("p", "The “Saves…” button under “Export…” in the chat. Enter a name and "
          "press “Save as new” — the whole dialogue is stored: chat, history, "
          "memory, selected presets, mode, model and unsent input. Later (also "
          "after restarting the app) open this window and press “Load” — "
          "everything comes back exactly from that point. “Overwrite” updates "
          "a save, “Delete” removes it. Loading replaces the current dialogue "
          "(save it first if you need it). Logs and Settings are not part of a "
          "save. Files live in a sessions folder next to the presets."),

    ("q", "What is a character's dynamic memory?"),
    ("p", "A checkbox in “Manage” of a character (companions only). The app "
          "keeps a brief list of the most important things that happened to "
          "the character: events, relationships, status, appearance — it is "
          "stored in the preset and survives separate dialogues, so the "
          "character remembers past meetings. It is updated by a separate "
          "request during the dialogue (never in the same turn as the dialogue "
          "memory is built) and never grows beyond the limit (4000 "
          "characters by default, adjustable in Settings). You can edit the text by hand; there is a “Clear "
          "dynamic memory” button. Needs the dialogue memory to be on "
          "(Settings → “History size” above 0). When you save a dialogue the "
          "app asks whether to update it, so the latest events are not lost."),

    ("q", "How do Dialogue, Story and Chat differ?"),
    ("p", "Dialogue — turn-by-turn play with one character; the reply splits "
          "into action (italic) and speech. Story — generation of a whole "
          "text from the scene parameters, with several characters and a set "
          "length possible. Chat — no roleplay prompts at all, a clean test "
          "of the model and parameters."),

    ("q", "The model replies in the wrong language or drifts."),
    ("p", "Check the RU / EN switch — it sets the language of the hidden "
          "prompts. Add an explicit rule to the “Configuration” block (e.g. "
          "“Always answer only in English”). Keep repeat_penalty soft (around "
          "1.05) — high values provoke a switch to another language. Picking a "
          "model trained on the target language also helps."),

    ("q", "The model ignores the character or the scene rules."),
    ("p", "Common causes: blocks that are too long or contradictory, an "
          "overloaded “Configuration”, a small model (7–8B holds instructions "
          "worse), a small num_ctx — the start of the prompt gets pushed out. "
          "Trim descriptions to the essentials, raise num_ctx, try a bigger "
          "model."),

    ("q", "The model repeats itself or loops."),
    ("p", "Nudge repeat_penalty up (1.05 → 1.1) and temperature, set min_p "
          "around 0.05–0.08. Check that num_ctx is not too small. Sometimes it "
          "is enough to delete the last looped reply and generate again."),

    ("q", "How do I make replies longer or shorter?"),
    ("p", "Longer: raise num_predict (or -1 = no limit), set “Story length” in "
          "Story mode, ask directly in your line. Shorter: a small num_predict "
          "and a rule in “Configuration” like “no more than 2–3 paragraphs per "
          "reply”."),

    ("q", "The reply is empty or cut off mid-word."),
    ("p", "Raise num_predict — you probably hit the limit. Check the stop "
          "strings in “Settings”: an extra stop string can cut the reply at "
          "the very start."),

    ("q", "What is the “Additional details” field and is it saved?"),
    ("p", "It is free-form notes for the current scene (mood, time, hidden "
          "circumstances). Added to the prompt only when filled in. Not saved "
          "into a preset — clear it by hand when the scene changes."),

    ("q", "What does the “Generate” button on character fields do?"),
    ("p", "It asks the model to invent the content of that specific field "
          "based on the already-filled fields of the same preset. The name is "
          "always typed by hand. The request and reply appear in the Logs "
          "panel."),

    ("h", "Memory and settings"),

    ("q", "How does the “running memory” work and when should I turn it off?"),
    ("p", "In “Dialogue” mode, every N turns everything past the “Story "
          "length” window is compressed by a hidden request into a short "
          "summary and prepended to the prompt — so the context does not "
          "overflow. For short sessions the memory is not needed: set it to 0 "
          "(the “Memory: rebuild every N turns” field on the “Settings” tab)."),

    ("q", "What should I choose for the Reasoning setting?"),
    ("p", "By default — “as in the model”: a model with reasoning support "
          "thinks on its own, the rest are left alone. “Force on” is useful "
          "for *-Reasoning builds without official support. “Force off” "
          "forbids thinking for a model that always thinks (e.g. qwen3). The "
          "reasoning goes to Logs; only the reply goes to the chat."),

    ("q", "How do I reset the generation parameters to sane values?"),
    ("p", "The “Optimal” button on the “Settings” tab restores the set "
          "recommended for roleplay. “Clear” removes all values — then the "
          "model decides everything itself."),

    ("q", "What does “Clear all” under the chat do?"),
    ("p", "It wipes the current dialogue, the running memory and the Logs "
          "panel. Presets, the scene block contents and “Settings” are left "
          "alone."),

    ("q", "Can I change the model in the middle of a dialogue?"),
    ("p", "Yes — just pick another one at the top. The history is kept, but "
          "the reply style changes, and another model may need to be loaded "
          "into memory again."),

    ("q", "How do I save a finished dialogue or story?"),
    ("p", "The “Export…” button under the chat — it saves the whole "
          "conversation with a scene header to a text file."),
]


# ===================== ШПАРГАЛКА ПО КОМАНДАМ (RU) =======================
_CHEAT_RU = [
    ("p", "Основные команды Ollama для командной строки. Модель обозначена "
          "как <модель> — это имя из каталога, например qwen2.5:7b. Всё "
          "работает локально; сервер Ollama должен быть запущен."),

    ("h", "Модели: список и информация"),

    ("q", "ollama list"),
    ("p", "Показать все скачанные модели: имя, размер на диске, дата "
          "изменения. С этого стоит начинать, если приложение «не видит» "
          "моделей."),

    ("q", "ollama ps"),
    ("p", "Показать модели, загруженные в память прямо сейчас, и на чём они "
          "считаются. Столбец PROCESSOR: «100% GPU» — хорошо, «100% CPU» или "
          "«48%/52% CPU/GPU» — модель не поместилась в видеопамять, ответы "
          "будут медленными."),

    ("q", "ollama show <модель>"),
    ("p", "Подробности о модели: число параметров, размер контекста, "
          "квантизация, шаблон промпта, лицензия. Пример: "
          "ollama show qwen2.5:7b"),

    ("h", "Скачивание и удаление"),

    ("q", "ollama pull <модель>"),
    ("p", "Скачать модель из каталога ollama.com/library (или обновить уже "
          "скачанную). Примеры: ollama pull qwen2.5:7b · "
          "ollama pull gemma2:9b · ollama pull llama3.1:8b-instruct-q5_K_M"),

    ("q", "ollama pull hf.co/<автор>/<репозиторий>:<квант>"),
    ("p", "Скачать GGUF-модель напрямую с HuggingFace. Пример: "
          "ollama pull hf.co/IlyaGusev/saiga_llama3_8b_gguf:Q4_K_M"),

    ("q", "ollama rm <модель>"),
    ("p", "Удалить скачанную модель и освободить место на диске. Пример: "
          "ollama rm gemma2:9b"),

    ("q", "ollama cp <источник> <новое-имя>"),
    ("p", "Сделать копию модели под другим именем (удобно перед правкой "
          "Modelfile). Пример: ollama cp qwen2.5:7b qwen-my"),

    ("h", "Запуск и сервер"),

    ("q", "ollama run <модель>"),
    ("p", "Запустить чат с моделью прямо в терминале (и скачать её, если "
          "ещё нет). Выход — команда /bye или Ctrl+D. Пример: "
          "ollama run qwen2.5:7b «Привет!»"),

    ("q", "ollama serve"),
    ("p", "Запустить сервер Ollama вручную на http://localhost:11434. "
          "Обычно он уже работает фоном после установки; команда нужна, если "
          "сервер не поднялся сам."),

    ("q", "ollama --version"),
    ("p", "Показать версию Ollama. Полезно при обновлении и в сообщениях об "
          "ошибках."),

    ("h", "Своя модель (Modelfile)"),

    ("q", "ollama create <имя> -f Modelfile"),
    ("p", "Собрать свою модель из текстового файла Modelfile — например с "
          "увеличенным контекстом или своим system-промптом. Пример "
          "содержимого Modelfile: FROM qwen2.5:7b / PARAMETER num_ctx 8192"),
]

# ===================== OLLAMA COMMAND CHEAT SHEET (EN) ==================
_CHEAT_EN = [
    ("p", "The main Ollama commands for the command line. <model> stands for "
          "a name from the catalog, e.g. qwen2.5:7b. Everything runs locally; "
          "the Ollama server must be running."),

    ("h", "Models: list and info"),

    ("q", "ollama list"),
    ("p", "List every downloaded model: name, on-disk size, modified date. "
          "Start here if the app “sees no models”."),

    ("q", "ollama ps"),
    ("p", "Show the models loaded into memory right now and where they run. "
          "The PROCESSOR column: “100% GPU” is good; “100% CPU” or a "
          "“48%/52% CPU/GPU” split means the model did not fit in VRAM and "
          "replies will be slow."),

    ("q", "ollama show <model>"),
    ("p", "Details about a model: parameter count, context size, "
          "quantization, prompt template, license. Example: "
          "ollama show qwen2.5:7b"),

    ("h", "Downloading and removing"),

    ("q", "ollama pull <model>"),
    ("p", "Download a model from ollama.com/library (or update one already "
          "downloaded). Examples: ollama pull qwen2.5:7b · "
          "ollama pull gemma2:9b · ollama pull llama3.1:8b-instruct-q5_K_M"),

    ("q", "ollama pull hf.co/<author>/<repo>:<quant>"),
    ("p", "Download a GGUF model straight from HuggingFace. Example: "
          "ollama pull hf.co/IlyaGusev/saiga_llama3_8b_gguf:Q4_K_M"),

    ("q", "ollama rm <model>"),
    ("p", "Delete a downloaded model and free disk space. Example: "
          "ollama rm gemma2:9b"),

    ("q", "ollama cp <source> <new-name>"),
    ("p", "Copy a model under another name (handy before editing a "
          "Modelfile). Example: ollama cp qwen2.5:7b qwen-my"),

    ("h", "Running and the server"),

    ("q", "ollama run <model>"),
    ("p", "Start a chat with the model right in the terminal (and download it "
          "if missing). Exit with /bye or Ctrl+D. Example: "
          "ollama run qwen2.5:7b \"Hello!\""),

    ("q", "ollama serve"),
    ("p", "Start the Ollama server manually at http://localhost:11434. It "
          "usually already runs in the background after install; use this if "
          "the server did not come up on its own."),

    ("q", "ollama --version"),
    ("p", "Print the Ollama version. Useful when updating and in bug "
          "reports."),

    ("h", "Your own model (Modelfile)"),

    ("q", "ollama create <name> -f Modelfile"),
    ("p", "Build your own model from a text Modelfile — e.g. with a larger "
          "context or your own system prompt. Sample Modelfile content: "
          "FROM qwen2.5:7b / PARAMETER num_ctx 8192"),
]


_DATA = {
    "about": {"ru": _ABOUT_RU, "en": _ABOUT_EN},
    "help": {"ru": _HELP_RU, "en": _HELP_EN},
    "faq": {"ru": _FAQ_RU, "en": _FAQ_EN},
    "cheatsheet": {"ru": _CHEAT_RU, "en": _CHEAT_EN},
}
