"""
Единое описание блоков конструктора сцены: Главный герой (Вы) / Персонаж /
Локация / Сценарий / Конфигурационный промпт.

Здесь и только здесь связаны вместе: заголовок блока, его dataclass,
имена методов PresetStore (load/upsert/delete), набор редактируемых
полей и стартовые примеры ("seed" - русский, "seed_en" - английский). GUI и менеджер пресетов ходят сюда,
а не хардкодят это у себя. Модуль намеренно без зависимостей от
customtkinter/tkinter - чтобы его можно было импортировать в тестах.

Формат поля: (attr, label, widget) где widget - "entry" (однострочное)
или "textbox" (многострочное). attr обязан совпадать с полем dataclass.
Ключ "photo": True - у блока есть необязательное фото (поле `photo` dataclass,
выбор файла в форме; в `fields` его нет - это не текстовое поле).

BLOCK_ORDER - все блоки с одиночным выбором пресета. В story-режиме
GUI прячет "environment" и разрешает несколько "character"; это логика
GUI, здесь перечислены все блоки как есть.
"""
from models import Character, Protagonist, Environment, Scenario, SystemConfig

BLOCK_ORDER = ("protagonist", "character", "environment", "scenario", "system_config")

BLOCK_SPECS = {
    "protagonist": {
        "title": "Главный герой (Вы)",
        "model": Protagonist,
        "load": "load_protagonists",
        "upsert": "upsert_protagonist",
        "delete": "delete_protagonist",
        "photo": True,           # у блока есть необязательное фото (см. photos.py)
        "fields": [
            ("name", "Имя", "entry"),
            ("biography", "Биография", "textbox"),
            ("appearance", "Внешность", "textbox"),
            ("personality", "Характер", "textbox"),
        ],
        "seed": lambda: Protagonist(
            name="Я",
            biography="",
            appearance="",
            personality="",
        ),
        "seed_en": lambda: Protagonist(
            name='Me',
            biography='A wandering scholar and former soldier, raised in the shadow of a dying empire. Served with honor but left with debts and a burning desire to see the world beyond the war’s reach. Now seeks knowledge and peace in equal measure.',
            appearance='Tall and lean with sun-bronzed skin from long years under open skies; piercing gray eyes that once saw battlefields but now seek wisdom; dark, slightly unkempt hair streaked with silver, tied back with a leather thong; wears a worn-out soldier’s coat patched with mismatched fabric, the left sleeve embroidered with faded symbols of his old unit.',
            personality='Skeptical yet open-minded, with a sharp wit that hides deep empathy. Driven by curiosity but weary of blind faith; values honesty above all, even when it stings. Has a dry sense of humor to soften the weight of the past, and an unshakable belief in second chances—for others, if not always for himself.',
        ),
    },
    "character": {
        "title": "Персонаж",
        "model": Character,
        "dynamic_memory": True,      # форма: галка + текст динамической памяти
        "load": "load_characters",
        "upsert": "upsert_character",
        "delete": "delete_character",
        "photo": True,
        "fields": [
            ("name", "Имя", "entry"),
            ("biography", "Биография", "textbox"),
            ("appearance", "Внешность", "textbox"),
            ("personality", "Характер", "textbox"),
            ("speech_style", "Манера речи", "textbox"),
            ("typical_phrases", "Типичные фразы (необязательно, по одной в строке)", "textbox"),
        ],
        "seed": lambda: Character(
            name="Ксана",
            appearance="высокая тёмноглазая брюнетка",
            personality="стервозный, любит грубить",
            biography="выросла в порту, рано осталась одна, привыкла добиваться своего",
            speech_style="коротко, с сарказмом, иногда переходит на колкости",
        ),
        "seed_en": lambda: Character(
            name='Girl',
            appearance='Tall and lean with a wild, messy mane of dark brown hair streaked with silver, her left eyebrow often inked with swirling patterns that shift like smoke. Wears fingerless gloves and fingerless socks to conceal hidden blades on her knuckles and feet, with exposed scars across her knuckles that glow faintly under the ring lights.',
            personality='Quick-tempered but fiercely loyal; hates being underestimated; sees beauty in chaos, embraces it like a second art form; sarcastic wit when annoyed, poetic when reflecting; struggles to let go of grudges but secretly admires those who do.',
            biography='A former street artist who turned to underground fighting after her paintings were vandalized by rival gangs. Now she uses her agility and sharp visual perception to outmaneuver opponents in the ring, often drawing patterns in the air with her fists that distract and confuse her foes.',
            speech_style='Sarcastic with dry humor, often laced with edgy metaphors; switches to rhythmic, almost lyrical cadence when describing art or battles; voice is a mix of growl and whisper, depending on mood—sharp like a blade when enraged, melodic when reminiscing about old paintings.',
            typical_phrases='*"So you want to talk about art now? Cool. First, let me show you how it looks when it hits back—no brushes, no canvas, just my knuckles and a grudge to paint with."*',
        ),
    },
    "environment": {
        "title": "Локация",
        "model": Environment,
        "load": "load_environments",
        "upsert": "upsert_environment",
        "delete": "delete_environment",
        "fields": [
            ("name", "Название пресета", "entry"),
            ("location", "Локация", "entry"),
            ("time_of_day", "Время суток", "entry"),
            ("weather", "Погода", "entry"),
            ("atmosphere", "Атмосфера (необязательно)", "textbox"),
        ],
        "seed": lambda: Environment(
            name="старинный ресторан",
            location="старинный ресторан",
            time_of_day="вечер",
            weather="дождливо",
        ),
        "seed_en": lambda: Environment(
            name='Old town',
            location='Narrow cobblestone streets',
            time_of_day='Midday',
            weather='Partly cloudy',
            atmosphere='Sunlight filters through patches of fog, casting long shadows and a soft golden glow on the buildings. The air smells of damp stone, baking bread, and the distant tang of salt from the nearby docks. A faint hum of conversation and the occasional clatter of carts echoes through the alleys, but everything has a quiet, measured rhythm like a city that knows its time is running out.',
        ),
    },
    "scenario": {
        "title": "Сценарий",
        "model": Scenario,
        "load": "load_scenarios",
        "upsert": "upsert_scenario",
        "delete": "delete_scenario",
        "fields": [
            ("name", "Название пресета", "entry"),
            ("base_scenario", "Базовый сценарий", "textbox"),
            ("additional_params", "Доп. параметры", "textbox"),
        ],
        "seed": lambda: Scenario(
            name="свидание",
            base_scenario="я пришёл на свидание с девушкой в ресторан",
            additional_params="свидание должно закончиться успешно",
        ),
        "seed_en": lambda: Scenario(
            name='Sudden encounter',
            base_scenario="A lone traveler stumbles upon a forgotten village on the edge of a dense forest, where the locals live under the shadow of an ancient, rumored-to-be-haunted mountain. Strange lights flicker in its peaks at night, and some say it's the spirits of the past warning visitors away.",
            additional_params='The mountain is said to be a prison for something that was once human, bound by dark magic; the villagers perform rituals at dusk to keep the chains strong, but even they whisper that the locks are weakening, and the thing inside is learning to whisper back.',
        ),
    },
    "system_config": {
        "title": "Конфигурационный промпт",
        "model": SystemConfig,
        "load": "load_system_configs",
        "upsert": "upsert_system_config",
        "delete": "delete_system_config",
        "fields": [
            ("name", "Название пресета", "entry"),
            ("content", "Общие правила поведения модели", "textbox"),
        ],
        "seed": lambda: SystemConfig(
            name="базовые правила",
            content="Всегда отвечай по-русски. Не больше 3 абзацев за ответ.",
        ),
        "seed_en": lambda: SystemConfig(
            name='Basic rules',
            content='Always answer in English; Do not use non-English words; Do not use any language other than English; Write in a literary style; Think before answering; Answer to the point; Do not repeat the same words; Do not repeat the same actions; Do not break character; Reply only as the CHARACTER; Never reply as the Protagonist.',
        ),
    },
}

# Короткие подписи для строки активных пресетов над чатом.
SHORT_LABELS = {
    "protagonist": "Вы",
    "character": "Персонаж",
    "environment": "Локация",
    "scenario": "Сценарий",
    "system_config": "Конфигурация",
}
