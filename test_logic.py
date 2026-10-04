"""
Тесты логики, которую можно проверить без GUI и без сети: модели данных,
JSON-хранилище, описание блоков, сборка system-промпта, разбор строк
потокового ответа Ollama и прерывание генерации.

Запуск:  python test_logic.py   (или двойной клик по run_tests.bat)

У каждого теста в docstring — человекочитаемое описание: первая строка
показывается в консоли рядом с номером теста, остальное поясняет, что
именно и зачем проверяется. При падении печатается тип ошибки, её текст
и точная строка файла, где сработал assert, а остальные тесты всё равно
доигрываются до конца. Код возврата 1, если хоть один тест упал —
чтобы это было видно в скриптах и .bat.
"""
import json
import re
import shutil
import sys
import tempfile
import threading
import traceback
from dataclasses import fields as dataclass_fields
from pathlib import Path
from unittest import mock

from models import (Character, Protagonist, Environment, Scenario, SystemConfig,
                    InferenceConfig, OPTIMAL_INFERENCE)
from storage import PresetStore
from prompt_builder import (build_system_prompt, build_digest_messages,
                            digest_boundary, role_guard, DIGEST_SYSTEM,
                            build_field_generation_messages,
                            build_segment_summary_messages,
                            build_consolidation_messages, build_compress_messages,
                            SEGMENT_SUMMARY_SYSTEM, CONSOLIDATE_SYSTEM,
                            estimate_tokens, next_num_ctx,
                            is_duplicate_speech, speech_of, norm_line,
                            find_repeat_loop)
from ollama_client import (parse_stream_line, parse_stream_thinking,
                           parse_structured_reply, normalize_messages, chat_stream,
                           model_capabilities, OllamaError, OllamaStallError)
from blocks import BLOCK_SPECS, BLOCK_ORDER
from inference_spec import INFERENCE_FIELDS


# ======================================================================
#  МОДЕЛИ ДАННЫХ  (models.py)
# ======================================================================

def test_character_roundtrip():
    """Персонаж: to_dict -> from_dict возвращает те же данные, включая id.

    Пишем персонажа в словарь (так он уходит в characters.json) и читаем
    обратно. Проверяем, что текстовые поля не потерялись и что id
    сохранился и восстановился — на id завязан upsert (обновление
    пресета на месте вместо создания дубля), поэтому его стабильность
    критична.
    """
    c = Character(name="Ксана", appearance="брюнетка", personality="стервозный",
                  biography="выросла в порту")
    c2 = Character.from_dict(c.to_dict())
    assert c2.name == "Ксана", c2.name
    assert c2.appearance == "брюнетка", c2.appearance
    assert c2.biography == "выросла в порту", c2.biography
    assert c2.id == c.id, "id не сохранился при round-trip"


def test_character_biography_defaults_and_backcompat():
    """Персонаж: поле biography по умолчанию "" и не ломает старые записи.

    biography добавлено позже appearance/personality. Старый
    characters.json без этого ключа должен грузиться: from_dict
    подставит "". Новый пустой Character тоже отдаёт biography == "".
    """
    assert Character().biography == ""
    old = Character.from_dict({"id": "x1", "name": "Марк", "appearance": "лысый"})
    assert old.biography == "" and old.name == "Марк", vars(old)


def test_character_typical_phrases_roundtrip_and_backcompat():
    """typical_phrases: round-trip нового поля + миграция со старого
    неиспользовавшегося first_message (по факту всегда было пустым, но
    на всякий случай подхватываем, если кто-то его всё же заполнил)."""
    c = Character(name="Ксана", typical_phrases="Опять ты.\nНе учи меня жить.")
    c2 = Character.from_dict(c.to_dict())
    assert c2.typical_phrases == "Опять ты.\nНе учи меня жить."
    assert Character().typical_phrases == ""
    # старая запись с first_message, без typical_phrases -> значение переехало
    old = Character.from_dict({"id": "x1", "name": "Марк", "first_message": "Ну?"})
    assert old.typical_phrases == "Ну?", vars(old)
    # обе записи разом -> новое поле в приоритете
    both = Character.from_dict({"typical_phrases": "новое", "first_message": "старое"})
    assert both.typical_phrases == "новое"


def test_protagonist_roundtrip():
    """Главный герой (Вы): round-trip нового dataclass Protagonist.

    Protagonist - отдельный блок «кем играет пользователь». Три поля +
    id должны переживать to_dict/from_dict, id - стабилен (нужен upsert).
    """
    p = Protagonist(name="Алекс", biography="журналист-расследователь",
                    appearance="сутулый, в мятом плаще",
                    personality="дотошный, недоверчивый")
    p2 = Protagonist.from_dict(p.to_dict())
    assert (p2.name, p2.biography, p2.appearance, p2.personality) == (
        "Алекс", "журналист-расследователь", "сутулый, в мятом плаще",
        "дотошный, недоверчивый"), vars(p2)
    assert p2.id == p.id, "id не сохранился при round-trip"
    # backcompat: старая запись без appearance грузится, поле -> ""
    assert Protagonist.from_dict({"id": "z", "name": "Б"}).appearance == ""


def test_environment_roundtrip():
    """Локация: round-trip, в т.ч. добавленное позже поле name.

    Environment раньше не имел имени; теперь имеет. Тест проверяет, что
    новое поле name и остальные (location/atmosphere/id) переживают
    сохранение и загрузку без потерь.
    """
    e = Environment(name="ресторан", location="старинный ресторан",
                    time_of_day="вечер", weather="дождливо", atmosphere="уютно")
    e2 = Environment.from_dict(e.to_dict())
    assert e2.name == "ресторан", e2.name
    assert e2.location == "старинный ресторан", e2.location
    assert e2.atmosphere == "уютно", e2.atmosphere
    assert e2.id == e.id, "id не сохранился при round-trip"


def test_scenario_roundtrip():
    """Сценарий: round-trip, в т.ч. добавленное позже поле name.

    То же самое, что для локации, но для Scenario: имя пресета и тексты
    сценария не должны теряться при записи в scenarios.json и чтении.
    """
    s = Scenario(name="свидание", base_scenario="свидание в ресторане",
                 additional_params="успешный финал")
    s2 = Scenario.from_dict(s.to_dict())
    assert s2.name == "свидание", s2.name
    assert s2.base_scenario == "свидание в ресторане", s2.base_scenario
    assert s2.id == s.id, "id не сохранился при round-trip"


def test_old_records_without_name_still_load():
    """Обратная совместимость: старые записи без ключа "name" грузятся.

    У пользователя на диске уже могут лежать environments.json /
    scenarios.json, сделанные до появления поля name. from_dict должен
    молча подставить name="" и не падать с KeyError. Тест эмулирует
    такие «старые» словари.
    """
    env = Environment.from_dict({"id": "abc123", "location": "лес"})
    scn = Scenario.from_dict({"id": "def456", "base_scenario": "погоня"})
    assert env.name == "" and env.location == "лес", vars(env)
    assert scn.name == "" and scn.base_scenario == "погоня", vars(scn)


def test_system_config_roundtrip():
    """Конфиг-промпт: round-trip нового dataclass SystemConfig.

    SystemConfig — четвёртый блок конструктора (общие правила поведения
    модели). Проверяем, что name/content/id корректно уходят в
    system_configs.json и читаются обратно.
    """
    sc = SystemConfig(name="базовые правила",
                      content="Всегда отвечай по-русски. Не более 3 абзацев.")
    sc2 = SystemConfig.from_dict(sc.to_dict())
    assert sc2.name == "базовые правила", sc2.name
    assert sc2.content == "Всегда отвечай по-русски. Не более 3 абзацев.", sc2.content
    assert sc2.id == sc.id, "id не сохранился при round-trip"


# ======================================================================
#  ХРАНИЛИЩЕ  (storage.py — PresetStore)
# ======================================================================

def test_preset_store_roundtrip():
    """Хранилище: список персонажей пишется на диск и читается как валидный JSON.

    Сохраняем двух персонажей во временную папку, читаем через
    load_characters() и дополнительно проверяем, что на диске лежит
    именно JSON-массив из 2 элементов (а не, скажем, пустой файл).
    """
    tmp = Path(tempfile.mkdtemp())
    try:
        store = PresetStore(data_dir=tmp)
        store.save_characters([Character(name="Ксана"), Character(name="Марк")])

        loaded = store.load_characters()
        assert len(loaded) == 2, len(loaded)
        assert {c.name for c in loaded} == {"Ксана", "Марк"}, [c.name for c in loaded]

        raw = json.loads(store.characters_file.read_text(encoding="utf-8"))
        assert len(raw) == 2, raw
    finally:
        shutil.rmtree(tmp)


def test_system_configs_store_roundtrip():
    """Хранилище: отдельный файл system_configs.json save/load.

    Убеждаемся, что для четвёртого блока заведён свой файл и пара
    методов save_system_configs()/load_system_configs() работает так же,
    как для трёх остальных типов.
    """
    tmp = Path(tempfile.mkdtemp())
    try:
        store = PresetStore(data_dir=tmp)
        store.save_system_configs([
            SystemConfig(name="рус", content="по-русски"),
            SystemConfig(name="кратко", content="кратко"),
        ])

        loaded = store.load_system_configs()
        assert len(loaded) == 2, len(loaded)
        assert {c.name for c in loaded} == {"рус", "кратко"}, [c.name for c in loaded]

        raw = json.loads(store.system_configs_file.read_text(encoding="utf-8"))
        assert len(raw) == 2, raw
    finally:
        shutil.rmtree(tmp)


def test_protagonists_store_roundtrip_and_delete():
    """Хранилище: protagonists.json — save/load, upsert без дублей, delete.

    Пятый тип пресетов («Главный герой (Вы)») лежит в своём файле.
    Проверяем полный набор операций PresetStore для него разом.
    """
    tmp = Path(tempfile.mkdtemp())
    try:
        store = PresetStore(data_dir=tmp)
        a, b = Protagonist(name="A"), Protagonist(name="B")
        store.upsert_protagonist(a)
        store.upsert_protagonist(b)
        store.upsert_protagonist(a)                     # тот же id -> без дубля
        assert {p.name for p in store.load_protagonists()} == {"A", "B"}

        store.delete_protagonist(a.id)
        assert [p.name for p in store.load_protagonists()] == ["B"]

        raw = json.loads(store.protagonists_file.read_text(encoding="utf-8"))
        assert len(raw) == 1, raw
    finally:
        shutil.rmtree(tmp)


def test_upsert_overwrites_instead_of_duplicating():
    """Хранилище: upsert обновляет запись на месте, не плодит дубли.

    Сценарий из реальной жизни: пользователь несколько раз жмёт
    «Сохранить» для одного и того же пресета, потом правит его, потом
    переименовывает. Проверяем по шагам:
      1) повторный upsert того же объекта -> в файле по-прежнему 1 запись;
      2) правка поля при том же id -> запись обновилась, дубля нет;
      3) смена name при том же id -> тоже обновление на месте (matching
         идёт по id, поэтому переименование не создаёт вторую запись);
      4) совсем другой объект с новым именем -> добавляется (теперь 2).
    Если этот тест падает — список пресетов в JSON будет бесконечно
    расти дублями.
    """
    tmp = Path(tempfile.mkdtemp())
    try:
        store = PresetStore(data_dir=tmp)

        c = Character(name="Ксана", appearance="брюнетка")
        store.upsert_character(c)
        store.upsert_character(c)
        assert len(store.load_characters()) == 1, "повторный upsert создал дубль"

        c.appearance = "рыжая"
        store.upsert_character(c)
        chars = store.load_characters()
        assert len(chars) == 1, "правка создала дубль"
        assert chars[0].appearance == "рыжая", chars[0].appearance

        c.name = "Марк"
        store.upsert_character(c)
        chars = store.load_characters()
        assert len(chars) == 1, "переименование создало дубль"
        assert chars[0].name == "Марк", chars[0].name

        store.upsert_character(Character(name="Аня"))
        assert len(store.load_characters()) == 2, "новый объект не добавился"
    finally:
        shutil.rmtree(tmp)


def test_delete_removes_only_target():
    """Хранилище: delete_* убирает ровно один пресет по id.

    Кладём три сценария, удаляем средний по id — остаются первый и
    третий в исходном порядке. Затем вызываем delete с несуществующим
    id и проверяем, что это безопасный no-op (ничего не удалилось, не
    упало). Эта же логика используется кнопкой «Удалить» в менеджере
    пресетов.
    """
    tmp = Path(tempfile.mkdtemp())
    try:
        store = PresetStore(data_dir=tmp)
        a, b, c = Scenario(name="a"), Scenario(name="b"), Scenario(name="c")
        store.save_scenarios([a, b, c])

        store.delete_scenario(b.id)
        left = [s.name for s in store.load_scenarios()]
        assert left == ["a", "c"], left

        store.delete_scenario("no-such-id")
        assert len(store.load_scenarios()) == 2, "no-op delete что-то удалил"
    finally:
        shutil.rmtree(tmp)


# ======================================================================
#  ОПИСАНИЕ БЛОКОВ  (blocks.py — BLOCK_SPECS)
# ======================================================================

def test_block_specs_consistent_with_models():
    """blocks.py: поля формы совпадают с полями dataclass, seed корректен.

    BLOCK_SPECS — единственный источник правды о 4 блоках (какие поля
    показывать в форме редактирования, какой у блока dataclass, какой
    пример создавать при первом запуске). Тест ловит опечатки в этом
    словаре ДО запуска GUI:
      - каждый attr поля реально существует в соответствующем dataclass
        (иначе форма упадёт при сохранении на Model(**values));
      - у каждого блока есть поле "name" (без имени пресет не выбрать);
      - тип виджета только "entry" или "textbox";
      - seed() возвращает объект нужного класса с непустым именем.
    """
    for block in BLOCK_ORDER:
        spec = BLOCK_SPECS[block]
        model_attrs = {f.name for f in dataclass_fields(spec["model"])}
        field_attrs = [attr for attr, _, _ in spec["fields"]]

        assert "name" in field_attrs, f"{block}: в форме нет поля name"
        for attr in field_attrs:
            assert attr in model_attrs, \
                f"{block}: поле '{attr}' отсутствует в {spec['model'].__name__}"
        for _, _, wtype in spec["fields"]:
            assert wtype in ("entry", "textbox"), f"{block}: неизвестный виджет {wtype!r}"

        seeded = spec["seed"]()
        assert isinstance(seeded, spec["model"]), f"{block}: seed() вернул не тот тип"
        assert seeded.name, f"{block}: seed() без имени"


def test_block_specs_store_methods_exist():
    """blocks.py: имена методов load/upsert/delete реально есть в PresetStore.

    В BLOCK_SPECS методы хранилища заданы строками ("load_characters" и
    т.п.), а GUI дёргает их через getattr(store, name). Тест проверяет,
    что все три имени для каждого блока указывают на существующий
    вызываемый метод — иначе «Настроить» упадёт только в рантайме.
    """
    store = PresetStore(data_dir=Path(tempfile.mkdtemp()))
    for block in BLOCK_ORDER:
        spec = BLOCK_SPECS[block]
        for key in ("load", "upsert", "delete"):
            assert callable(getattr(store, spec[key], None)), \
                f"{block}: PresetStore.{spec[key]} не найден"


# ======================================================================
#  СБОРКА ПРОМПТА  (prompt_builder.py — build_system_prompt)
# ======================================================================

def test_prompt_contains_all_blocks():
    """Промпт: в текст попадают все заполненные поля персонажа/локации/сценария.

    Собираем промпт из полностью заполненных блоков в режиме dialogue и
    проверяем, что каждое значение (имя, внешность, характер, локация,
    время, погода, сценарий, доп. условия) присутствует в итоговой
    строке, плюс что подставилась инструкция режима диалога
    («не выходи из роли»).
    """
    char = Character(name="Ксана", appearance="высокая тёмноглазая брюнетка",
                     personality="стервозный, любит грубить")
    env = Environment(location="старинный ресторан", time_of_day="вечер",
                      weather="дождливо")
    scn = Scenario(base_scenario="свидание в ресторане",
                   additional_params="должно закончиться успешно")

    prompt = build_system_prompt(char, env, scn, mode="dialogue")

    for expected in ["Ксана", "высокая тёмноглазая брюнетка", "стервозный",
                     "старинный ресторан", "вечер", "дождливо",
                     "свидание в ресторане", "должно закончиться успешно"]:
        assert expected in prompt, f"'{expected}' не найдено в промпте"
    assert "не выходи из роли" in prompt, "нет инструкции режима dialogue"


def test_prompt_character_field_order():
    """Промпт: в блоке персонажа поля идут Биография → Внешность → Характер.

    Порядок задаётся в _character_block и должен совпадать с порядком
    полей в форме редактирования (blocks.py). Проверяем по позициям
    характерных подстрок.
    """
    c = Character(name="Ксана", biography="выросла в порту",
                  appearance="высокая брюнетка", personality="колючая")
    prompt = build_system_prompt(character=c, environment=Environment(),
                                 scenario=Scenario(), mode="dialogue")
    i_bio = prompt.index("выросла в порту")
    i_app = prompt.index("высокая брюнетка")
    i_per = prompt.index("колючая")
    assert i_bio < i_app < i_per, (i_bio, i_app, i_per)


def test_prompt_character_typical_phrases():
    """Промпт: «Типичные фразы» персонажа попадают в блок персонажа как
    ориентир по голосу/стилю, с явным «не повторяй дословно» (иначе модель
    просто заучивает и повторяет готовую фразу - ровно та проблема, для
    которой сделан анти-повтор в GUI). Пустое поле - блока нет вообще;
    пустые строки внутри поля отфильтрованы.
    """
    c = Character(name="Ксана",
                 typical_phrases="Опять ты.\n\nНе учи меня жить.\n   \n")
    prompt = build_system_prompt(character=c, environment=Environment(),
                                 scenario=Scenario(), mode="dialogue")
    assert '"Опять ты."' in prompt and '"Не учи меня жить."' in prompt
    assert "не повторяй" in prompt.lower() and "дословно" in prompt.lower()

    empty = build_system_prompt(character=Character(name="Ксана"),
                                environment=Environment(), scenario=Scenario(),
                                mode="dialogue")
    assert "Типичные фразы" not in empty

    en = build_system_prompt(character=Character(name="Kai",
                             typical_phrases="Fine.\nWhatever."),
                             environment=Environment(), scenario=Scenario(),
                             mode="dialogue", lang="en")
    assert '"Fine."' in en and '"Whatever."' in en
    assert "verbatim" in en.lower()


def test_prompt_mode_switches_instructions():
    """Промпт: режимы dialogue и story дают разные инструкции.

    В режиме dialogue должна быть ролевая инструкция («не выходи из
    роли»), в режиме story — инструкция писать рассказ, и ролевой
    инструкции там быть не должно. Проверяем, что переключатель режима
    действительно меняет наполнение промпта.
    """
    char, env, scn = Character(name="Ксана"), Environment(), Scenario()
    dialogue = build_system_prompt(char, env, scn, mode="dialogue")
    story = build_system_prompt(char, env, scn, mode="story")
    assert "не выходи из роли" in dialogue, "в dialogue нет ролевой инструкции"
    assert "не выходи из роли" not in story, "ролевая инструкция протекла в story"
    assert "рассказ" in story, "в story нет инструкции про рассказ"


def test_prompt_without_system_config_unchanged():
    """Промпт: без конфиг-промпта (значение по умолчанию) поведение не изменилось.

    Гарантия обратной совместимости: вызов build_system_prompt без
    аргумента system_config и с system_config=None должны давать
    БАЙТ-в-байт одинаковый результат. Если этот тест падает — значит
    новый необязательный блок влияет на промпт даже когда он не задан.
    """
    char, env, scn = Character(name="Ксана"), Environment(), Scenario()
    assert (build_system_prompt(char, env, scn, mode="dialogue")
            == build_system_prompt(char, env, scn, mode="dialogue",
                                   system_config=None)), \
        "None-конфиг изменил промпт"


def test_prompt_with_system_config_goes_first():
    """Промпт: заданный конфиг-промпт идёт ПЕРЕД инструкциями режима и данными.

    Порядок важен: общие правила должны стоять выше специфичных
    инструкций режима, а те — выше данных персонажа. Проверяем и
    наличие текста правил в промпте, и порядок через сравнение
    позиций подстрок (index): правила < инструкция режима < блок
    «Персонаж».
    """
    char = Character(name="Ксана")
    sc = SystemConfig(name="правила", content="ВСЕГДА отвечай по-русски.")
    prompt = build_system_prompt(char, Environment(), Scenario(),
                                 mode="dialogue", system_config=sc)

    assert "ВСЕГДА отвечай по-русски." in prompt, "текст правил не попал в промпт"
    assert prompt.index("ВСЕГДА отвечай по-русски.") < prompt.index("не выходи из роли"), \
        "правила оказались ниже инструкции режима"
    assert prompt.index("не выходи из роли") < prompt.index("Персонаж"), \
        "инструкция режима оказалась ниже данных персонажа"


def test_prompt_empty_system_config_is_ignored():
    """Промпт: конфиг-промпт из одних пробелов игнорируется.

    Если пользователь создал блок конфига, но поле content пустое (или
    только пробелы/переводы строк) — он не должен добавлять в промпт
    пустой блок. Результат обязан совпасть с промптом вообще без
    конфига.
    """
    char, env, scn = Character(name="Ксана"), Environment(), Scenario()
    base = build_system_prompt(char, env, scn, mode="dialogue")
    with_empty = build_system_prompt(char, env, scn, mode="dialogue",
                                     system_config=SystemConfig(content="   "))
    assert base == with_empty, "пустой конфиг всё же изменил промпт"


def test_prompt_protagonist_between_instructions_and_characters():
    """Промпт: блок «Главный герой (Вы)» идёт после инструкций, перед персонажами.

    Главный герой — это тот, кем играет пользователь; модель его не
    отыгрывает, но должна знать, с кем имеет дело. В промпте его блок
    должен стоять после инструкции режима и ДО блока «Персонаж».
    """
    p = Protagonist(name="Алекс", biography="журналист", appearance="в мятом плаще",
                    personality="дерзкий")
    c = Character(name="Ксана")
    prompt = build_system_prompt(character=c, environment=Environment(),
                                 scenario=Scenario(), mode="dialogue", protagonist=p)
    assert "Алекс" in prompt and "дерзкий" in prompt, "данные героя не попали в промпт"
    assert "в мятом плаще" in prompt, "внешность героя не попала в промпт"
    # порядок полей в блоке героя: Биография -> Внешность -> Характер
    assert prompt.index("журналист") < prompt.index("в мятом плаще") < prompt.index("дерзкий"), \
        "поля героя идут не в порядке Биография/Внешность/Характер"
    assert prompt.index("не выходи из роли") < prompt.index("Алекс"), \
        "герой выше инструкции режима"
    assert prompt.index("Алекс") < prompt.index("Персонаж: Ксана"), \
        "герой ниже персонажа"


def test_prompt_no_protagonist_unchanged():
    """Промпт: без главного героя (None или пустой) результат прежний.

    Обратная совместимость: protagonist=None и protagonist=Protagonist()
    (все поля пустые) не должны ничего добавлять в промпт.
    """
    c, e, s = Character(name="Ксана"), Environment(), Scenario()
    base = build_system_prompt(c, e, s, mode="dialogue")
    assert base == build_system_prompt(c, e, s, mode="dialogue", protagonist=None)
    assert base == build_system_prompt(c, e, s, mode="dialogue",
                                       protagonist=Protagonist()), \
        "пустой Protagonist всё же изменил промпт"


def test_role_guard():
    """role_guard: явно называет, за кого писать и за кого НИКОГДА (главный герой).

    Помогает против «модель отвечает за ГГ». Без имён - пустая строка.
    """
    g = role_guard([Character(name="Ксана"), Character(name="Марк")],
                   Protagonist(name="Алекс"))
    assert "Ксана, Марк" in g
    assert "«Алекс»" in g and "НИКОГДА" in g

    assert role_guard([], None) == ""
    assert role_guard([Character(name="Ксана")], Protagonist()) == (
        "В своём ответе ты ведёшь ход ТОЛЬКО за: Ксана.")


def test_prompt_dialogue_has_role_guard():
    """Промпт (dialogue): в тексте есть предупреждение не писать за ГГ; в story - нет."""
    d = build_system_prompt(character=Character(name="Ксана"), environment=Environment(),
                            scenario=Scenario(), mode="dialogue",
                            protagonist=Protagonist(name="Алекс"))
    assert "НИКОГДА не пиши" in d and "«Алекс»" in d
    s = build_system_prompt(characters=[Character(name="Ксана")], scenario=Scenario(),
                            mode="story", protagonist=Protagonist(name="Алекс"))
    assert "НИКОГДА не пиши" not in s


def test_prompt_language_rule():
    """Промпт: в dialogue и story есть жёсткое требование писать только по-русски."""
    for kw in (dict(character=Character(name="X"), environment=Environment(),
                    scenario=Scenario(), mode="dialogue"),
               dict(characters=[Character(name="X")], scenario=Scenario(),
                    mode="story")):
        p = build_system_prompt(**kw)
        assert "ИСКЛЮЧИТЕЛЬНО по-русски" in p, kw["mode"]
        assert "смешения языков" in p


def test_prompt_language_reminder_at_the_end():
    """Промпт: напоминание про язык продублировано в САМОМ КОНЦЕ - после
    персонажа/сценария/параметров истории, а не только в начале рядом с
    LANGUAGE_RULE. Слабые модели теряют вес инструкций из начала промпта
    под грузом данных сцены; то, что прочитано последним перед генерацией,
    влияет сильнее (реальный баг: модель то и дело вставляла "said"/
    "asked"/"smiled" одним словом внутри русской реплики несмотря на явный
    запрет в LANGUAGE_RULE)."""
    p = build_system_prompt(character=Character(name="Ксана", biography="долгая предыстория"),
                            environment=Environment(location="город"),
                            scenario=Scenario(base_scenario="встреча"),
                            mode="dialogue")
    assert p.rstrip().endswith("никогда не вставляй английские глаголы "
                               "(said, asked, smiled, began, wanted и "
                               "подобные) даже одним словом внутри "
                               "русского предложения.")
    # напоминание физически ПОСЛЕ блока персонажа (не только в начале)
    assert p.index("## Персонаж: Ксана") < p.rindex("Напоминание перед ответом")

    s = build_system_prompt(characters=[Character(name="Ксана")], scenario=Scenario(),
                            mode="story", story_size="кратко")
    assert s.rindex("Напоминание перед ответом") > s.index("Желаемый размер")

    en = build_system_prompt(character=Character(name="Kai"), environment=Environment(),
                             scenario=Scenario(), mode="dialogue", lang="en")
    assert en.rstrip().endswith("not even for a single word.")
    assert "Напоминание" not in en and "Reminder before you answer" in en


def test_prompt_language_english():
    """Промпт: lang="en" переписывает языковое правило и заголовки блоков
    на английский, русских маркеров не остаётся."""
    d = build_system_prompt(character=Character(name="Kai", personality="cold"),
                            environment=Environment(location="a pier"),
                            scenario=Scenario(base_scenario="a meeting"),
                            mode="dialogue", protagonist=Protagonist(name="Alex"),
                            lang="en")
    assert "Write EXCLUSIVELY in English" in d
    assert "ИСКЛЮЧИТЕЛЬНО" not in d and "Персонаж:" not in d
    assert "## Character: Kai" in d and "Personality: cold" in d
    assert "## Environment" in d and "Location: a pier" in d
    assert "NEVER write or describe" in d          # role_guard на английском

    s = build_system_prompt(characters=[Character(name="Kai")],
                            scenario=Scenario(), mode="story",
                            story_size="short scene", lang="en")
    assert "coherent third-person" in s
    assert "## Story parameters" in s and "Desired length: short scene" in s

    # digest и field-generation тоже переключаются
    dg = build_digest_messages("old", [{"role": "user", "content": "hi"}], lang="en")
    assert "Write in English" in dg[0]["content"]
    assert "Current memory:" in dg[1]["content"] and "New events:" in dg[1]["content"]


def test_prompt_reasoning_nudge():
    """Промпт: reasoning_nudge=True добавляет просьбу думать в <think>…</think>.

    Для reasoning-моделей без capability "thinking" приложение не может
    послать параметр think - вместо этого просит рассуждать инлайном.
    Просьба должна стоять в самом верху (до инструкций режима), а по
    умолчанию (nudge=False) промпт не меняется.
    """
    c, e, s = Character(name="Ксана"), Environment(), Scenario()
    base = build_system_prompt(c, e, s, mode="dialogue")
    assert base == build_system_prompt(c, e, s, mode="dialogue",
                                       reasoning_nudge=False), "nudge=False изменил промпт"

    nudged = build_system_prompt(c, e, s, mode="dialogue", reasoning_nudge=True)
    assert "<think>" in nudged and "</think>" in nudged, "нет упоминания тегов think"
    assert nudged.index("<think>") < nudged.index("не выходи из роли"), \
        "просьба про think оказалась ниже инструкций режима"
    # работает и в story
    story = build_system_prompt(characters=[c], scenario=s, mode="story",
                                reasoning_nudge=True)
    assert "<think>" in story


def test_build_digest_messages():
    """build_digest_messages: скрытый запрос «обнови память».

    system = DIGEST_SYSTEM; user содержит текущий дайджест и выпавшие
    ходы, помеченные ролями. Пустой старый дайджест -> «(пусто)».
    """
    entries = [{"role": "user", "content": "привет"},
               {"role": "assistant", "content": "*кивает* Здравствуй."}]
    msgs = build_digest_messages("Ксана и герой в баре.", entries)
    assert len(msgs) == 2 and msgs[0]["content"] == DIGEST_SYSTEM
    u = msgs[1]["content"]
    assert "Ксана и герой в баре." in u
    assert "Пользователь: привет" in u
    assert "Ассистент: *кивает* Здравствуй." in u

    empty = build_digest_messages("", entries)
    assert "(пусто)" in empty[1]["content"]

    # свой system-промпт вместо дефолтного
    custom = build_digest_messages("d", entries, system_prompt="МОЙ ПРОМПТ")
    assert custom[0]["content"] == "МОЙ ПРОМПТ"
    assert build_digest_messages("d", entries, system_prompt="  ")[0]["content"] == DIGEST_SYSTEM


def test_estimate_tokens_and_next_num_ctx():
    """estimate_tokens: грубая ВЕРХНЯЯ оценка, растёт с объёмом текста и
    числом сообщений. next_num_ctx: степень двойки не меньше need."""
    small = [{"role": "system", "content": "x" * 100},
             {"role": "user", "content": "y" * 100}]
    big = [{"role": "system", "content": "x" * 100}] + [
        {"role": "user", "content": "реплика игрока " * 40},
        {"role": "assistant", "content": "ответ персонажа " * 40},
    ] * 30
    assert estimate_tokens(small) < estimate_tokens(big)
    # 200 символов / 2.5 + оверхед -> порядка 90-120 токенов
    assert 60 < estimate_tokens(small) < 200
    # пустой список - маленькое неотрицательное число
    assert estimate_tokens([]) >= 0

    assert next_num_ctx(1) == 8192
    assert next_num_ctx(8192) == 8192
    assert next_num_ctx(8193) == 16384
    assert next_num_ctx(40000) == 65536
    assert next_num_ctx(10**9) == 131072      # потолок


def test_build_compress_messages():
    """build_compress_messages: сжать кусок ПОД заданный объём, не «до
    минимума». Ориентир по объёму (слова) и требование максимума деталей
    попадают в system; сам текст - в user."""
    m = build_compress_messages("Виктар покупает Лайрис. Она боится.", 900)
    assert [x["role"] for x in m] == ["system", "user"]
    sys, usr = m[0]["content"], m[1]["content"]
    assert "900" in sys and "900" in usr       # ориентир по объёму подставлен
    assert "конкретики" in sys.lower() or "деталей" in sys.lower()
    assert "НЕ больше" in sys                   # верхняя граница
    assert "Виктар покупает Лайрис. Она боится." in usr

    en = build_compress_messages("Viktar buys Lyris. She is afraid.", 1200, lang="en")
    assert "1200" in en[0]["content"]
    assert "concrete detail" in en[0]["content"].lower()
    assert "Viktar buys Lyris. She is afraid." in en[1]["content"]
    # слишком маленькая цель поднимается до минимума
    assert "40" in build_compress_messages("x", 5)[0]["content"]


def test_layered_memory_messages():
    """Послойная память: сводка одного сегмента и уплотнение.

    build_segment_summary_messages кладёт уже собранную память как контекст
    «не повторяй», а в user - только реплики сегмента. build_consolidation_
    messages вливает старые сводки в долговременную голову. Оба запроса от
    длины диалога не зависят - только фиксированный вход.
    """
    seg = [{"role": "user", "content": "герой заходит в бар"},
           {"role": "assistant", "content": "*Ксана поднимает взгляд* Опять ты."}]

    m = build_segment_summary_messages("Ксана и герой знакомы.", seg)
    assert [x["role"] for x in m] == ["system", "user"]
    assert m[0]["content"] == SEGMENT_SUMMARY_SYSTEM
    u = m[1]["content"]
    assert "Ксана и герой знакомы." in u          # известное - как контекст
    assert "Пользователь: герой заходит в бар" in u
    assert "Ассистент: *Ксана поднимает взгляд* Опять ты." in u
    assert "только новых событий" in u.lower() or "только новых" in u

    # своя инструкция вместо дефолтной; пустая память -> «(пока ничего)»
    assert build_segment_summary_messages("", seg, system_prompt="МОЙ")[0]["content"] == "МОЙ"
    assert "(пока ничего)" in build_segment_summary_messages("", seg)[1]["content"]

    # уплотнение: голова + старые блоки
    c = build_consolidation_messages("Долгая история...", ["блок A", "блок B"])
    assert c[0]["content"] == CONSOLIDATE_SYSTEM
    cu = c[1]["content"]
    assert "Долгая история..." in cu and "блок A" in cu and "блок B" in cu
    assert "(пусто)" in build_consolidation_messages("", ["x"])[1]["content"]

    # английский
    me = build_segment_summary_messages("known stuff", seg, lang="en")
    assert "You keep a brief memory" in me[0]["content"]
    assert "Already known" in me[1]["content"] and "New events:" in me[1]["content"]
    ce = build_consolidation_messages("head", ["b"], lang="en")
    assert "long-term memory" in ce[0]["content"].lower()
    assert "Long-term memory:" in ce[1]["content"]


def test_is_duplicate_speech():
    """is_duplicate_speech: ловит почти дословный повтор РЕЧЕВОЙ части хода
    персонажа в пределах окна, игнорируя действие в *...* и короткие реплики."""
    # speech_of отбрасывает строки-действия целиком в *...*
    assert speech_of("*сжимает кулаки*\nТы думаешь, это меня сломит?") \
        == "Ты думаешь, это меня сломит?"
    assert speech_of("*молчит*") == ""
    assert norm_line("Ты  ДУМАЕШЬ,.. это?!") == "ты думаешь это"

    hist = [
        {"role": "user", "content": "Виктар заносит плеть."},
        {"role": "assistant",
         "content": "*отступает к стене*\nТы думаешь, что плеть сломит меня? "
                    "Я выжила в стае гиен, переживу и тебя."},
        {"role": "user", "content": "Он делает шаг ближе."},
        {"role": "assistant",
         "content": "*поднимает подбородок*\nВиктар усмехается краем губ."},
    ]
    # тот же смысл, чуть переставлены слова -> повтор
    assert is_duplicate_speech(
        "Думаешь, плеть сломит меня? Я выжила в стае гиен, переживу и тебя.",
        hist)
    # совсем другая реплика -> не повтор
    assert not is_duplicate_speech(
        "Бей. Каждый удар только злит меня сильнее.", hist)
    # короткие реплики не проверяем
    assert not is_duplicate_speech("Нет.", [
        {"role": "assistant", "content": "Нет."}])
    # окно ограничено: старый повтор за пределами window не считается
    old = [{"role": "assistant", "content": "Одна и та же длинная фраза "
            "которая повторяется дословно спустя много ходов подряд."}]
    old += [{"role": "assistant", "content": f"Реплика номер {i} совершенно "
             "иная по содержанию и формулировке чем все прочие вокруг."}
            for i in range(10)]
    assert not is_duplicate_speech(
        "Одна и та же длинная фраза которая повторяется дословно спустя "
        "много ходов подряд.", old, window=8)


def test_find_repeat_loop():
    """find_repeat_loop: ловит зацикленную генерацию длинных историй -
    модель гоняет по кругу одни и те же абзацы, пока штраф за повтор её не
    отпускает. НЕ предполагает строгий период - реальный баг-репорт
    показал, что модель может ротировать НЕСКОЛЬКО похожих шаблонов
    вперемешку (а не жёстко по кругу), да ещё и через вставленные
    заголовки глав/разделители, которые сбивают любой фиксированный
    период. Возвращает текст ДО первого абзаца-повтора в хвосте."""
    # период 1: один и тот же абзац подряд много раз -> держим только первый
    # (нужно > LOOP_MIN_HITS+1 повторов, иначе просто не хватит данных -
    # см. отдельную проверку "мало абзацев" ниже)
    para = "Виктар посмотрел на неё с презрением и произнёс что-то резкое."
    text = "\n\n".join([para] * 6)
    kept = find_repeat_loop(text)
    assert kept == para, kept

    # период 2 (как в первом баг-репорте): A,B,A,B,A,B -> держим A+B
    a = "Ты будешь подчиняться мне, — сказал Виктар холодным тоном сейчас."
    b = "Лайрис попробовала вырваться, но хватка была слишком сильна у него."
    text2 = "\n\n".join([a, b] * 3)
    kept2 = find_repeat_loop(text2)
    assert kept2 == f"{a}\n\n{b}", kept2

    # реальный баг-репорт: НЕ строгий период - несколько похожих шаблонов
    # (действие / реплика-1 / фраза-персонажа / реплика-2) ротируются
    # вразнобой, плюс вставлены заголовки глав "**...**" и разделители
    # "---", которые сбивают любой фиксированный период. Старая версия
    # (искала только жёсткий период 1-4) эту форму зацикливания вообще не
    # ловила - именно этот сценарий и был найден в реальном экспорте истории.
    action = "Виктар положил ладонь ей на плечо и слегка сжал пальцы."
    said_v = "Ты будешь учиться, — сказал Виктар, и голос его стал мягче."
    iris = "Она не знала, что это означает, но хотела быть послушной ему."
    said_o = "Ты будешь учиться, — сказал он, и она замерла, боясь вздохнуть."
    chunk = [action, said_v, iris, said_o, iris, action, said_v, iris]
    rotated = "\n\n".join(
        chunk + ["---", "**Финал**"] + chunk + ["---"] + chunk)
    kept3 = find_repeat_loop(rotated)
    assert kept3 is not None
    assert kept3 != rotated          # что-то реально отброшено
    assert action in kept3 and said_v in kept3   # не потеряли всё подряд

    # нормальный, не зацикленный текст (каждый абзац - о своём) -> None
    normal = "\n\n".join([
        "Виктар вышел на рынок ранним утром, когда толпа только собиралась.",
        "Торговцы раскладывали товар, кто-то спорил о цене за старую упряжь.",
        "Лайрис стояла у самой клетки, глядя исподлобья на покупателей вокруг.",
        "Один из охранников грубо толкнул её вперёд, к помосту для осмотра.",
        "Виктар подошёл ближе и внимательно осмотрел пленницу с ног до головы.",
        "Он кивнул торговцу и полез за кошельком, не говоря ни слова больше.",
    ])
    assert find_repeat_loop(normal) is None

    # короткие реплики повторяются естественно (диалог) -> не ловим
    short = "\n\n".join(["Нет.", "Да.", "Нет.", "Да.", "Нет.", "Да."] * 2)
    assert find_repeat_loop(short) is None

    # мало абзацев вообще -> не хватает данных, не ловим
    assert find_repeat_loop("\n\n".join([para] * 3)) is None


def test_build_field_generation_messages():
    """build_field_generation_messages: один запрос модели про ОДНО поле карточки.

    Кнопка «Сгенерировать» напротив поля. Имя и другие НЕпустые поля того
    же объекта попадают в промпт как «уже известно»; само генерируемое
    поле - нет (даже если заполнено: пользователь просит замену). Пустые
    поля пропускаются. Требование писать только по-русски присутствует.
    """
    values = {"name": "Ксана", "appearance": "высокая брюнетка",
              "personality": "старый текст", "biography": ""}
    labels = {"name": "Имя", "appearance": "Внешность",
              "personality": "Характер", "biography": "Биография"}
    msgs = build_field_generation_messages(
        "character", "personality", "Характер", values, labels)
    assert [m["role"] for m in msgs] == ["system", "user"]
    sys_txt, user_txt = msgs[0]["content"], msgs[1]["content"]
    assert "«Характер»" in sys_txt
    assert "по-русски" in sys_txt                       # LANGUAGE_RULE вшит
    assert "персонаж" in sys_txt.lower()                # вступление по типу блока
    assert "Имя: Ксана" in user_txt
    assert "Внешность: высокая брюнетка" in user_txt
    assert "старый текст" not in user_txt               # генерируемое поле не подаём
    assert "Биография" not in user_txt                  # пустое поле пропущено
    assert "Придумай поле «Характер»." in user_txt

    # ничего не заполнено -> подсказка «придумай с нуля»
    empty = build_field_generation_messages(
        "scenario", "base_scenario", "Базовый сценарий",
        {"name": "", "base_scenario": "", "additional_params": ""},
        {"name": "Название пресета", "base_scenario": "Базовый сценарий",
         "additional_params": "Доп. параметры"})
    assert "с нуля" in empty[1]["content"]
    assert "сценари" in empty[0]["content"].lower()     # своё вступление у scenario

    # short=True (однострочные поля: Локация / Время суток / Погода):
    # просим слово/словосочетание без предложения, длинное правило убрано
    sh = build_field_generation_messages(
        "environment", "time_of_day", "Время суток",
        {"name": "", "time_of_day": ""}, {"time_of_day": "Время суток"}, short=True)
    st = sh[0]["content"]
    assert "КОРОТКОЕ поле" in st and "без точки в конце" in st
    assert "1-3 сжатых" not in st
    lng = build_field_generation_messages(
        "environment", "atmosphere", "Атмосфера",
        {"name": ""}, {"atmosphere": "Атмосфера"}, short=False)
    assert "1-3 сжатых" in lng[0]["content"] and "КОРОТКОЕ поле" not in lng[0]["content"]


def test_digest_boundary():
    """digest_boundary: рубеж пересборки памяти двигается раз в N ходов, не каждый ход.

    Именно это чинит «память переписывается каждый ход». Между рубежами
    функция возвращает одно и то же значение → пересборка не запускается.
    """
    assert digest_boundary(0, 6) == 0
    assert digest_boundary(10, 6) == 0     # 5 ходов < 6
    assert digest_boundary(12, 6) == 12    # ровно 6 ходов -> первый рубеж
    assert digest_boundary(14, 6) == 12    # 7 ходов -> рубеж НЕ сдвинулся
    assert digest_boundary(22, 6) == 12    # 11 ходов -> всё ещё 12
    assert digest_boundary(24, 6) == 24    # 12 ходов -> новый рубеж
    assert digest_boundary(24, 0) == 0     # выключено
    assert digest_boundary(13, 6) == 12    # нечётная длина (висячий user) - округляем вниз


def test_prompt_structured_dialogue():
    """Промпт: structured_dialogue=True добавляет JSON-инструкцию (только dialogue).

    В режиме dialogue после инструкций режима появляется требование
    отвечать JSON'ом {action, speech}. В story игнорируется. По
    умолчанию (False) промпт не меняется.
    """
    c, e, s = Character(name="Ксана"), Environment(), Scenario()
    base = build_system_prompt(c, e, s, mode="dialogue")
    assert base == build_system_prompt(c, e, s, mode="dialogue",
                                       structured_dialogue=False)

    d = build_system_prompt(c, e, s, mode="dialogue", structured_dialogue=True)
    assert '"action"' in d and '"speech"' in d, "нет JSON-инструкции"
    assert d.index("не выходи из роли") < d.index('"action"'), \
        "JSON-инструкция должна идти после инструкций режима"

    story = build_system_prompt(characters=[c], scenario=s, mode="story",
                                structured_dialogue=True)
    assert '"speech"' not in story, "в story structured_dialogue не должен влиять"


def test_prompt_story_multiple_characters_no_location():
    """Промпт (story): несколько персонажей, блока «Локация» нет.

    В режиме истории GUI передаёт список characters и НЕ передаёт
    environment (локации по ходу меняются). Проверяем, что все
    переданные персонажи попали в промпт, а блок «## Окружение»
    отсутствует.
    """
    chars = [Character(name="Ксана"), Character(name="Марк")]
    prompt = build_system_prompt(characters=chars,
                                 scenario=Scenario(base_scenario="дуэль на рассвете"),
                                 mode="story")
    assert "Персонаж: Ксана" in prompt, "первый персонаж потерян"
    assert "Персонаж: Марк" in prompt, "второй персонаж потерян"
    assert "дуэль на рассвете" in prompt
    assert "## Окружение" not in prompt, "в story просочился блок локации"


def test_prompt_story_size_and_details_only_in_story():
    """Промпт: «Размер истории» и «Доп. детали» учитываются только в story.

    Эти два поля есть только на story-вью. build_system_prompt должен
    добавлять блок «Параметры истории» при mode="story" и полностью
    игнорировать эти аргументы при mode="dialogue".
    """
    story = build_system_prompt(mode="story", scenario=Scenario(),
                                story_size="очень короткий, 2 абзаца",
                                story_details="финал оставить открытым")
    assert "очень короткий, 2 абзаца" in story
    assert "финал оставить открытым" in story

    dlg = build_system_prompt(character=Character(name="X"), environment=Environment(),
                              scenario=Scenario(), mode="dialogue",
                              story_size="очень короткий, 2 абзаца",
                              story_details="финал оставить открытым")
    assert "очень короткий, 2 абзаца" not in dlg, "параметры истории попали в dialogue"


def test_prompt_dialogue_extra_details():
    """Промпт: extra_details даёт блок «## Дополнительные детали» только в dialogue.

    Это поле «Дополнительные детали» левой панели в режиме диалога
    (аналог story_details для истории). В story-режиме аргумент
    игнорируется, по умолчанию ("") блок не добавляется.
    """
    c, e, s = Character(name="Ксана"), Environment(), Scenario()
    base = build_system_prompt(c, e, s, mode="dialogue")
    assert base == build_system_prompt(c, e, s, mode="dialogue", extra_details="")

    d = build_system_prompt(c, e, s, mode="dialogue",
                            extra_details="на столе лежит письмо с сургучом")
    assert "## Дополнительные детали" in d
    assert "на столе лежит письмо с сургучом" in d

    story = build_system_prompt(characters=[c], scenario=s, mode="story",
                                extra_details="на столе лежит письмо с сургучом")
    assert "письмо с сургучом" not in story, "extra_details просочился в story"


# ======================================================================
#  СЕТЕВОЙ КЛИЕНТ  (ollama_client.py — без реальной сети)
# ======================================================================

class _FakeResp:
    """Заглушка requests.Response для chat_stream (stream=True)."""

    def __init__(self, lines=(), status_code=200, body=None):
        self._lines = list(lines)
        self.status_code = status_code
        self._body = body          # dict -> .json(); иначе .json() кидает ValueError

    def __enter__(self): return self
    def __exit__(self, *a): return False
    def close(self): pass

    def raise_for_status(self):
        if self.status_code >= 400:
            import requests as _rq
            raise _rq.exceptions.HTTPError(response=self)

    def json(self):
        if self._body is None:
            raise ValueError("no json body")
        return self._body

    @property
    def text(self):
        return "" if self._body is None else json.dumps(self._body)

    def iter_lines(self):
        return iter(self._lines)


def test_photo_field_roundtrip_and_backcompat():
    """Character/Protagonist: необязательное поле photo (ИМЯ файла) переживает
    round-trip, у старых записей без него - "", в текст промпта не попадает;
    InferenceConfig.show_avatars: по умолчанию вкл, старый settings.json/мусор
    -> вкл, round-trip, в options для Ollama не идёт; старый ключ show_photos
    читается как show_avatars. Галерея (gallery) и эмотиконы (emotes) - списки
    имён файлов, у старых записей пустые."""
    c = Character(name="Ксана", photo="photo_abc.png",
                  gallery=["photo_g1.png", "photo_g2.png"], emotes=["photo_e1.png"])
    c2 = Character.from_dict(c.to_dict())
    assert c2.photo == "photo_abc.png"
    assert c2.gallery == ["photo_g1.png", "photo_g2.png"] and c2.emotes == ["photo_e1.png"]
    assert Character.from_dict({"id": "x", "name": "Марк"}).gallery == []
    assert Character.from_dict({"id": "x", "gallery": "oops", "emotes": [1, None, "a.png"]}
                               ).emotes == ["a.png"]
    pg = Protagonist(name="Я", gallery=["photo_g.png"], emotes=["photo_e.png"])
    assert Protagonist.from_dict(pg.to_dict()).emotes == ["photo_e.png"]
    assert Character.from_dict({"id": "x", "name": "Марк"}).photo == ""
    p = Protagonist(name="Виктар", photo="photo_def.png")
    assert Protagonist.from_dict(p.to_dict()).photo == "photo_def.png"
    assert Protagonist.from_dict({"id": "x", "name": "Я"}).photo == ""
    assert Character().photo == "" and Protagonist().photo == ""
    prompt = build_system_prompt(character=c, environment=Environment(),
                                 scenario=Scenario(), mode="dialogue", protagonist=p)
    assert "photo_abc" not in prompt and "photo_def" not in prompt

    assert InferenceConfig().show_avatars is True
    assert InferenceConfig().show_gallery is True
    assert InferenceConfig.from_dict({}).show_avatars is True           # старый settings.json
    assert InferenceConfig.from_dict({"show_photos": False}).show_avatars is False  # старое имя
    assert InferenceConfig.from_dict({"show_avatars": False}).show_avatars is False
    assert InferenceConfig.from_dict({"show_avatars": "no"}).show_avatars is True    # мусор
    assert InferenceConfig.from_dict({"show_gallery": False}).show_gallery is False
    assert InferenceConfig.from_dict(
        InferenceConfig(show_avatars=False, show_gallery=False).to_dict()
    ).show_gallery is False
    o = InferenceConfig(show_avatars=False, show_gallery=False, show_emotes=True).to_options()
    assert not {"show_avatars", "show_gallery", "show_emotes", "emotes_mode"} & set(o)
    assert BLOCK_SPECS["character"].get("photo") and BLOCK_SPECS["protagonist"].get("photo")
    assert not BLOCK_SPECS["environment"].get("photo")


def test_photos_import_avatar_and_cleanup():
    """photos.py: импорт уменьшает до MAX_SIDE и кладёт photo_*.png; аватарка -
    круг нужного размера с прозрачным зазором справа; cleanup_unused убирает
    ТОЛЬКО неиспользуемые photo_*.png (чужие файлы не трогает); photo_file не
    выпускает за пределы папки. Без Pillow тест пропускается (фича опциональна)."""
    import photos
    if not photos.AVAILABLE:
        return
    from PIL import Image
    tmp = Path(tempfile.mkdtemp())
    try:
        src = tmp / "big.jpg"
        Image.new("RGB", (1600, 900), (200, 50, 50)).save(src)
        dest = tmp / "photos"
        name = photos.import_photo(str(src), dest)
        assert name.startswith("photo_") and name.endswith(".png")
        with Image.open(dest / name) as im:
            assert max(im.size) == photos.MAX_SIDE, im.size
            assert im.size == (photos.MAX_SIDE, photos.MAX_SIDE * 9 // 16), im.size   # пропорции сохранены

        av = photos.make_avatar(dest / name, 40, gap=8)
        assert av.size == (48, 40) and av.mode == "RGBA"
        assert av.getpixel((0, 0))[3] == 0                     # угол квадрата - прозрачный (круг)
        assert av.getpixel((20, 20))[3] == 255                 # центр - непрозрачный
        assert av.getpixel((44, 20))[3] == 0                   # зазор справа - прозрачный
        assert photos.make_avatar(tmp / "нет_такого.png", 40) is None
        assert photos.make_avatar(dest / name, 0) is None

        # битый файл -> PhotoError, а не падение с чужим исключением
        bad = tmp / "bad.jpg"
        bad.write_bytes(b"not an image")
        try:
            photos.import_photo(str(bad), dest)
            raise AssertionError("битый файл должен дать PhotoError")
        except photos.PhotoError:
            pass

        keep = photos.import_photo(str(src), dest)
        (dest / "notes.txt").write_text("мои заметки", encoding="utf-8")
        removed = photos.cleanup_unused(dest, [keep, "", None])
        assert removed == 1                                    # лишнее (name) убрано
        assert sorted(p.name for p in dest.iterdir()) == sorted([keep, "notes.txt"])

        assert photos.photo_file(dest, keep) == dest / keep
        assert photos.photo_file(dest, "") is None
        assert photos.photo_file(dest, "nope.png") is None
        assert photos.photo_file(dest, "../big.jpg") is None   # наружу не выходим
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_store_photo_lifecycle():
    """PresetStore: фото персонажа/героя живёт, пока на него ссылается пресет.
    Замена фото, удаление пресета и отменённый импорт не копят мусор в
    photos/; у пресета без фото ничего не создаётся."""
    import photos
    if not photos.AVAILABLE:
        return
    from PIL import Image
    tmp = Path(tempfile.mkdtemp())
    try:
        (tmp / "data").mkdir()
        store = PresetStore(tmp / "data")
        src = tmp / "a.png"
        Image.new("RGB", (100, 100), (10, 20, 30)).save(src)

        def files():
            return (sorted(p.name for p in store.photos_dir.iterdir())
                    if store.photos_dir.exists() else [])

        store.upsert_character(Character(name="Без фото"))
        assert files() == []

        n1 = store.import_photo(str(src))
        ch = Character(name="Ксана", photo=n1)
        store.upsert_character(ch)
        assert files() == [n1] and store.photo_path(n1) is not None

        n2 = store.import_photo(str(src))                       # заменили фото
        store.upsert_character(Character(id=ch.id, name="Ксана", photo=n2))
        assert files() == [n2]

        store.import_photo(str(src))                            # импорт, но не сохранили
        pr = Protagonist(name="Виктар", photo=store.import_photo(str(src)))
        store.upsert_protagonist(pr)                            # любое сохранение чистит
        assert files() == sorted([n2, pr.photo])

        store.delete_character(ch.id)
        assert files() == [pr.photo]
        store.delete_protagonist(pr.id)
        assert files() == []
        assert store.photo_path("photo_nope.png") is None

        # галерея и эмотиконы тоже держат файлы живыми, пока на них ссылаются
        em = tmp / "e.png"
        im = Image.new("RGBA", (50, 80), (0, 0, 0, 0))
        for x in range(15, 35):
            for y in range(10, 70):
                im.putpixel((x, y), (200, 40, 40, 255))
        im.save(em)
        g1, g2 = store.import_photo(str(src)), store.import_photo(str(src))
        e1 = store.import_emote(str(em))
        ch2 = Character(name="Мира", gallery=[g1, g2], emotes=[e1])
        store.upsert_character(ch2)
        assert files() == sorted([g1, g2, e1])
        store.upsert_character(Character(id=ch2.id, name="Мира", gallery=[g1], emotes=[e1]))
        assert files() == sorted([g1, e1])                      # g2 убрали из галереи
        store.delete_character(ch2.id)
        assert files() == []
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_emote_validation_png_transparent_only():
    """Эмотикон - ТОЛЬКО PNG на прозрачном фоне; проверка по содержимому:
    JPEG (даже под именем .png), PNG без альфы и PNG со сплошным фоном -
    EmoteError с кодом (GUI показывает алерт, файл не импортируется);
    силуэт с прозрачностью (в т.ч. палитровый PNG) проходит."""
    import photos
    if not photos.AVAILABLE:
        return
    from PIL import Image
    tmp = Path(tempfile.mkdtemp())
    try:
        def code(path):
            try:
                photos.check_emote(path)
            except photos.EmoteError as e:
                return e.code
            return None

        rgb = tmp / "rgb.png"
        Image.new("RGB", (40, 40), (1, 2, 3)).save(rgb)
        assert code(rgb) == "no_alpha"
        solid = tmp / "solid.png"
        Image.new("RGBA", (40, 40), (1, 2, 3, 255)).save(solid)
        assert code(solid) == "not_transparent"
        fake = tmp / "fake.png"
        Image.new("RGB", (40, 40), (9, 9, 9)).save(fake, format="JPEG")
        assert code(fake) == "not_png"
        sil = tmp / "sil.png"
        im = Image.new("RGBA", (40, 40), (0, 0, 0, 0))
        for x in range(10, 30):
            for y in range(5, 35):
                im.putpixel((x, y), (255, 0, 0, 255))
        im.save(sil)
        assert code(sil) is None
        pal = tmp / "pal.png"
        Image.new("P", (40, 40), 0).save(pal, transparency=0)
        assert code(pal) is None

        dest = tmp / "photos"
        name = photos.import_emote(str(sil), dest)
        assert (dest / name).is_file()
        try:
            photos.import_emote(str(rgb), dest)
            assert False, "PNG без прозрачности не должен импортироваться"
        except photos.EmoteError:
            pass
        assert len(list(dest.iterdir())) == 1                   # лишнего не создано
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_photo_overlay_setting_and_frame():
    """show_emotes (ЭКСПЕРИМЕНТ, эмотиконы поверх интерфейса): по умолчанию
    ВЫКЛЮЧЕНО, старый settings.json/мусор -> выкл (старое имя photo_overlay
    читается как show_emotes), round-trip, режим кнопки эмотиконов (emotes_mode) запоминается. В options
    не идёт. overlay._premultiplied_bgra - кадр для UpdateLayeredWindow: байты
    BGRA с ПРЕДУМНОЖЕННОЙ альфой (иначе полупрозрачные края светились бы)."""
    assert InferenceConfig().show_emotes is False
    assert InferenceConfig().emotes_mode == "all"
    assert InferenceConfig.from_dict({}).show_emotes is False
    assert InferenceConfig.from_dict({"show_emotes": "yes"}).show_emotes is False
    assert InferenceConfig.from_dict({"show_emotes": True}).show_emotes is True
    assert InferenceConfig.from_dict({"photo_overlay": True}).show_emotes is True   # старое имя
    cfg = InferenceConfig.from_dict(
        InferenceConfig(show_emotes=True, emotes_mode="companion").to_dict())
    assert cfg.show_emotes is True and cfg.emotes_mode == "companion"
    for mode in ("all", "companion", "hidden"):
        assert InferenceConfig.from_dict({"emotes_mode": mode}).emotes_mode == mode
    for junk in ("x", 5, None, True, [], "ALL"):                       # мусор -> "all"
        assert InferenceConfig.from_dict({"emotes_mode": junk}).emotes_mode == "all"
    assert InferenceConfig.from_dict({"emotes_hidden": True}).emotes_mode == "hidden"   # старый bool
    assert InferenceConfig.from_dict({"emotes_hidden": False}).emotes_mode == "all"
    assert InferenceConfig.from_dict({"emotes_hidden": True, "emotes_mode": "companion"}).emotes_mode == "companion"
    assert InferenceConfig.optimal().show_emotes is False

    import overlay
    import photos
    if not photos.AVAILABLE:
        return
    from PIL import Image
    im = Image.new("RGBA", (2, 1))
    im.putpixel((0, 0), (200, 100, 50, 128))      # полупрозрачный
    im.putpixel((1, 0), (10, 20, 30, 255))        # непрозрачный
    raw = overlay._premultiplied_bgra(im)
    assert len(raw) == 8
    b, g, r, a = raw[0], raw[1], raw[2], raw[3]
    assert a == 128 and abs(r - 100) <= 1 and abs(g - 50) <= 1 and abs(b - 25) <= 1, raw[:4]
    assert tuple(raw[4:8]) == (30, 20, 10, 255)   # непрозрачный пиксель не меняется
    # на не-Windows / без Pillow модуль должен честно сказать "недоступно"
    assert overlay.AVAILABLE == (sys.platform == "win32" and photos.AVAILABLE)


def test_session_store_roundtrip_and_robustness():
    """sessions.SessionStore: сохранить -> список -> загрузить -> перезаписать
    (тот же id, дата создания сохраняется) -> удалить. Битый файл не ломает
    список, id вне hex-формата (попытка выйти из папки) отклоняется, версия
    новее известной - SessionError, незаконченная запись (.tmp) не мешает."""
    from sessions import SessionStore, SessionError, SESSION_VERSION
    tmp = Path(tempfile.mkdtemp())
    try:
        st = SessionStore(tmp)
        assert st.list() == []                                  # папки ещё нет
        snap = {"mode": "dialogue", "model": "m",
                "history": [{"role": "user", "content": "Привет"},
                            {"role": "assistant", "content": "Здравствуй"}],
                "chat": [{"t": "\n\nТы: Привет\n", "tags": ["hang1"]}, {"img": "photo_x.png"}]}
        meta = st.save(snap, "  Вечер у Ксаны ")
        assert meta["name"] == "Вечер у Ксаны" and meta["turns"] == 2
        assert meta["mode"] == "dialogue" and meta["model"] == "m"
        assert st.load(meta["id"]) == snap                      # без потерь, кириллица цела

        meta2 = st.save({**snap, "history": snap["history"][:1]}, "Вечер у Ксаны", meta["id"])
        assert meta2["id"] == meta["id"] and meta2["turns"] == 1
        assert meta2["created_at"] == meta["created_at"]        # перезапись, а не копия
        assert len(st.list()) == 1

        other = st.save(snap, "Другой")
        assert {m["name"] for m in st.list()} == {"Вечер у Ксаны", "Другой"}
        assert st.list()[0]["saved_at"] >= st.list()[1]["saved_at"]   # свежие первыми

        (st.dir / "deadbeef0001.json").write_text("{не json", encoding="utf-8")
        (st.dir / (other["id"] + ".json.tmp")).write_text("{", encoding="utf-8")
        (st.dir / "notes.json").write_text("[]", encoding="utf-8")
        assert len(st.list()) == 2                              # мусор пропущен
        for bad in ("deadbeef0001", "nope", "../x", "..\\x", "", None):
            try:
                st.load(bad)
                assert False, bad
            except SessionError:
                pass

        newer = st.dir / "abcdef123456.json"
        newer.write_text(json.dumps({"version": SESSION_VERSION + 1, "id": "abcdef123456",
                                     "data": {}}), encoding="utf-8")
        try:
            st.load("abcdef123456")
            assert False, "версия новее должна отвергаться"
        except SessionError:
            pass

        st.delete(meta["id"])
        st.delete(meta["id"])                                   # повторно - не ошибка
        assert all(m["id"] != meta["id"] for m in st.list())
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_dynamic_memory_field_and_prompt():
    """Character.dyn_enabled / dyn_memory: round-trip, старые записи -> выкл и
    пусто, мусор отбрасывается. В промпт память попадает ТОЛЬКО при включённой
    галке и непустом тексте (RU и EN), у героя/выключенного персонажа - нет."""
    c = Character(name="Ксана", dyn_enabled=True, dyn_memory="- поцеловались\n- доверяет герою")
    c2 = Character.from_dict(c.to_dict())
    assert c2.dyn_enabled is True and c2.dyn_memory == "- поцеловались\n- доверяет герою"
    old = Character.from_dict({"id": "x", "name": "Марк"})
    assert old.dyn_enabled is False and old.dyn_memory == ""
    junk = Character.from_dict({"id": "x", "dyn_enabled": "yes", "dyn_memory": 5})
    assert junk.dyn_enabled is False and junk.dyn_memory == ""
    assert BLOCK_SPECS["character"].get("dynamic_memory")
    assert not BLOCK_SPECS["protagonist"].get("dynamic_memory")      # только собеседник

    def prompt(ch, lang="ru"):
        return build_system_prompt(character=ch, environment=Environment(),
                                   scenario=Scenario(), mode="dialogue", lang=lang)
    assert "доверяет герою" in prompt(c) and "Динамическая память" in prompt(c)
    assert "доверяет герою" in prompt(c, "en") and "Dynamic memory" in prompt(c, "en")
    off = Character(name="Ксана", dyn_enabled=False, dyn_memory="- секрет")
    assert "секрет" not in prompt(off)
    empty = Character(name="Ксана", dyn_enabled=True, dyn_memory="  ")
    assert "Динамическая память" not in prompt(empty)


def test_dynamic_memory_logic():
    """dynamic_memory: промпт (лимит, имена, события, оба языка), разбор ответа
    (НЕТ_ИЗМЕНЕНИЙ / пусто / код-блок / идентично), жёсткий предел размера
    (режутся самые старые строки), защита от «усыхания» памяти."""
    import dynamic_memory as dm
    m = dm.build_messages("Ксана", "Виктар", "- старое", ["сводка 1", "сводка 2"], limit=1234)
    assert m[0]["role"] == "system" and "1234" in m[0]["content"] and dm.NO_CHANGES in m[0]["content"]
    u = m[1]["content"]
    assert "Ксана" in u and "Виктар" in u and "- старое" in u and "сводка 1" in u and "сводка 2" in u
    assert "(пусто)" in dm.build_messages("К", "", "", ["e"])[1]["content"]
    en = dm.build_messages("Xana", "Vic", "", ["e"], lang="en")
    assert dm.NO_CHANGES_EN in en[0]["content"] and "(empty)" in en[1]["content"]
    many = dm.build_messages("К", "", "", [f"событие-{i}" for i in range(30)])[1]["content"]
    assert "событие-29" in many and "событие-0\n" not in many          # вход ограничен

    cur = "- a\n- b"
    assert dm.interpret_reply("НЕТ_ИЗМЕНЕНИЙ", cur) == ("same", cur)
    assert dm.interpret_reply("  no changes. ", cur) == ("same", cur)
    assert dm.interpret_reply("", cur) == ("fail", cur) and dm.interpret_reply(None, cur) == ("fail", cur)
    assert dm.interpret_reply("- a\n- b", cur) == ("same", cur)       # идентично
    assert dm.interpret_reply("```\n- a\n- b\n- c\n```", cur) == ("changed", "- a\n- b\n- c")
    assert dm.interpret_reply("- a\n- b\n- c", cur) == ("changed", "- a\n- b\n- c")

    # предел размера: лишнее режется с НАЧАЛА (старое), результат <= limit
    text = "\n".join(f"- пункт {i:03d} " + "слово " * 10 for i in range(100))
    fit = dm.fit_to_limit(text, 500)
    assert len(fit) <= 500 and "пункт 099" in fit and "пункт 000" not in fit
    assert dm.fit_to_limit("короткий", 500) == "короткий"
    one = dm.fit_to_limit("слово " * 200, 100)                        # одна длинная строка
    assert len(one) <= 100 and one.endswith("…")
    st, new = dm.interpret_reply(text, "- x", limit=500)
    assert st == "changed" and len(new) <= 500
    # память не вырастает выше предела даже на «раздутом» ответе
    st, new = dm.interpret_reply("- " + "я" * 9000, "- x")
    assert len(new) <= dm.DYN_MEMORY_LIMIT

    # защита: из длинной (но не у предела) памяти не должно «усыхать» до огрызка
    big = "- " + "важное " * 150                                    # ~1000 символов
    assert dm.interpret_reply("- ок", big) == ("same", big.strip())
    # а у самого предела сжатие ожидаемо и принимается
    near = "\n".join(f"- {i} " + "x" * 30 for i in range(110))
    assert len(near) > dm.DYN_MEMORY_LIMIT * 0.9
    st, _new = dm.interpret_reply("- кратко", near)
    assert st == "changed"


def test_dyn_memory_limit_setting():
    """Settings: dyn_memory_limit - предел динамической памяти. Дефолт 4000,
    пусто/мусор/bool/старый settings.json -> 4000, значения зажимаются в
    500..20000, round-trip, в options для Ollama не идёт; предел реально
    применяется (fit_to_limit / interpret_reply / текст промпта)."""
    import dynamic_memory as dm
    assert InferenceConfig().dyn_limit() == 4000
    assert InferenceConfig.from_dict({}).dyn_limit() == 4000
    for bad in ("x", True, None, [], {}):
        assert InferenceConfig.from_dict({"dyn_memory_limit": bad}).dyn_limit() == 4000, bad
    assert InferenceConfig.from_dict({"dyn_memory_limit": 1500}).dyn_limit() == 1500
    assert InferenceConfig.from_dict({"dyn_memory_limit": 10}).dyn_limit() == dm.DYN_LIMIT_MIN
    assert InferenceConfig.from_dict({"dyn_memory_limit": 10**9}).dyn_limit() == dm.DYN_LIMIT_MAX
    assert InferenceConfig(dyn_memory_limit=None).dyn_limit() == 4000     # пустое поле в UI
    c = InferenceConfig(dyn_memory_limit=2500)
    assert InferenceConfig.from_dict(c.to_dict()).dyn_limit() == 2500
    assert "dyn_memory_limit" not in c.to_options()
    assert InferenceConfig.optimal().dyn_limit() == 4000
    assert any(f["attr"] == "dyn_memory_limit" and f["kind"] == "int" for f in INFERENCE_FIELDS)
    # предел действительно применяется
    text = "\n".join(f"- пункт {i:03d} " + "слово " * 10 for i in range(100))
    st, new = dm.interpret_reply(text, "- x", limit=1000)
    assert st == "changed" and len(new) <= 1000 and "пункт 099" in new
    assert "1000" in dm.build_messages("К", "", "", ["e"], limit=1000)[0]["content"]


def test_session_snapshot_normalize_and_storage_resilience():
    """normalize_snapshot: любой мусор -> снимок с гарантированными типами,
    индексы зажаты в [0, len(history)], нет исключений. Хранилище пресетов и
    настроек: повреждённый/неверной формы JSON и BOM не роняют загрузку,
    повреждённый файл откладывается как .corrupt-*, мусорные поля и
    отсутствующий id в записях безопасны."""
    from sessions import normalize_snapshot
    for junk in (None, [], "x", 5, {}, {"history": "x", "chat": 5, "scene": "s", "draft": "d"},
                 {"digested_upto": "x", "story_recap_upto": None, "mode": 5, "model": 5},
                 {"history": [None, 1, {"role": "system", "content": "x"}, {"role": "user", "content": 7}]}):
        n = normalize_snapshot(junk)
        assert n["mode"] == "dialogue" and isinstance(n["history"], list) and n["history"] == []
        assert n["digested_upto"] == 0 and n["story_recap_upto"] == 0
        assert isinstance(n["draft"], dict) and set(n["draft"]) == {"act", "reply", "story", "chat"}
    good = normalize_snapshot({
        "mode": "story", "history": [{"role": "user", "content": "a"}, {"role": "assistant", "content": "b"}],
        "digested_upto": 99, "story_recap_upto": -3, "dyn_new": ["x"] * 20, "mem_segments": ["s", 1],
        "chat": [{"t": "x", "tags": ["a", 5]}, {"img": "f.png"}, {"t": 5}, "z"],
        "scene": {"character": {"name": "К"}, "protagonist": "bad"}})
    assert good["mode"] == "story" and len(good["history"]) == 2
    assert good["digested_upto"] == 2 and good["story_recap_upto"] == 0       # зажато
    assert len(good["dyn_new"]) == 8 and good["mem_segments"] == ["s"]
    assert good["chat"] == [{"t": "x", "tags": ["a"]}, {"img": "f.png"}]
    assert good["scene"]["character"] == {"name": "К"} and good["scene"]["protagonist"] is None

    tmp = Path(tempfile.mkdtemp())
    try:
        st = PresetStore(tmp)
        st.characters_file.write_text('[1, 2, {"name": "Ж"}, null', encoding="utf-8")   # оборванный JSON
        assert st.load_characters() == []
        assert any(".corrupt-" in p.name for p in tmp.iterdir())                       # отложен, не затёрт
        st.protagonists_file.write_text(json.dumps({"x": 1}), encoding="utf-8")        # не список
        assert st.load_protagonists() == []
        st.environments_file.write_text("﻿" + json.dumps([{"name": "Бар"}, "мусор", 5]), encoding="utf-8")
        envs = st.load_environments()                                                   # BOM + мусорные элементы
        assert [e.name for e in envs] == ["Бар"] and envs[0].id                         # id сгенерирован
        st.settings_file.write_text("{битый", encoding="utf-8")
        assert st.load_settings().stall_seconds() == 30                                 # дефолты, не падение
        st.settings_file.write_text(json.dumps({"stop": 5, "keep_alive": [1], "digest_prompt": {}}), encoding="utf-8")
        cfg = st.load_settings(); cfg.to_options()
        assert cfg.stop == "5" and cfg.keep_alive == "" and cfg.digest_prompt == ""
        st.upsert_character(Character(name="Ок"))
        assert not any(p.name.endswith(".tmp") for p in tmp.iterdir())                  # запись атомарна
        # записи без id не склеиваются между собой
        st.characters_file.write_text(json.dumps([{"name": "А"}, {"name": "Б"}]), encoding="utf-8")
        a, b = st.load_characters()
        assert a.id and b.id and a.id != b.id
        # нестроковые поля не роняют сборку промпта
        c = Character.from_dict({"id": "x", "name": 7, "appearance": ["a"], "biography": None})
        assert c.name == "7" and c.appearance == "" and c.biography == ""
        build_system_prompt(character=c, environment=Environment(), scenario=Scenario(), mode="dialogue")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_dynamic_memory_marker_variants():
    """НЕТ_ИЗМЕНЕНИЙ: маркер первой строкой = «без изменений» (пояснение после
    него - не память); маркер среди текста в память не попадает."""
    import dynamic_memory as dm
    assert dm.interpret_reply("НЕТ_ИЗМЕНЕНИЙ.\nНо Ксана теперь замужем.", "- a") == ("same", "- a")
    assert dm.interpret_reply("No changes", "- a") == ("same", "- a")
    st, new = dm.interpret_reply("- a\n- b\nНЕТ_ИЗМЕНЕНИЙ", "- a")
    assert st == "changed" and "НЕТ_ИЗМЕНЕНИЙ" not in new and new == "- a\n- b"


def test_parse_structured_reply_truncated_json():
    """Оборванный JSON (обрыв связи, обрезка по num_predict) разбирается
    терпимо: берём успевшее прийти вместо сырого обрубка в чате/истории.
    Полный JSON и не-JSON работают как раньше."""
    p = parse_structured_reply
    assert p('{"action": "кивает", "speech": "Привет"}') == ("кивает", "Привет")
    assert p('{"action": "a", "speech": "част') == ("a", "част")
    assert p('{"action": "кивает", "speech": "Привет, \\"друг\\"!\\nКак') == ("кивает", 'Привет, "друг"!\nКак')
    assert p('{"action":"x"') == ("x", "")
    assert p('{"speech": "ab\\') == ("", "ab")                      # оборвано посреди экранирования
    assert p('{"speech": "ab\\u04') == ("", "ab")
    assert p('```json\n{"action": "a", "speech": "b') == ("a", "b")  # в блоке кода
    assert p("просто текст") == ("", "просто текст")                 # не JSON - как реплика
    assert p("{") == ("", "{") and p('{"x": 1') == ("", '{"x": 1')   # нечего доставать
    assert p('{"action": null, "speech": "s"}') == ("", "s")
    assert p("") == ("", "") and p(None) == ("", "")


def test_stream_error_line_and_junk_parsing():
    """{"error": ...} посреди потока (модель упала при HTTP 200) распознаётся
    как ошибка, а не как нормальный конец ответа; разбор строк стрима и
    списка моделей переживает мусор (не объект, не те типы)."""
    import ollama_client as oc
    assert oc.parse_stream_error('{"error": "model runner stopped"}') == "model runner stopped"
    assert oc.parse_stream_error('{"message": {"content": "x"}}') is None
    for junk in (None, b"", "", "[]", "null", "5", "{", b"\xff\xfe", 5, '{"error": ""}'):
        assert oc.parse_stream_error(junk) is None
    for junk in (None, b"", "[]", "null", '{"message": 5}', '{"message": {"content": 5}}', b"\xff", 5, "{"):
        assert oc.parse_stream_line(junk) is None and oc.parse_stream_thinking(junk) is None
    assert oc.parse_stream_line('{"message": {"content": "ок"}}') == "ок"
    assert oc.parse_stream_thinking('{"message": {"thinking": "думаю"}}') == "думаю"


def test_default_seed_presets_ru_and_en():
    """Стартовые примеры (первый запуск, build): у КАЖДОГО блока есть русский
    ("seed") и английский ("seed_en") - разные имена, непустые, round-trip через
    to_dict/from_dict; английский пример без кириллицы."""
    cyr = re.compile("[А-Яа-яЁё]")
    for block, spec in BLOCK_SPECS.items():
        ru, en = spec["seed"](), spec["seed_en"]()
        assert ru.name and en.name and ru.name != en.name, block
        assert type(en) is spec["model"] and en.id != ru.id
        back = spec["model"].from_dict(en.to_dict())
        assert back.to_dict() == en.to_dict()
        for k, v in en.to_dict().items():
            if isinstance(v, str):
                assert not cyr.search(v), (block, k)
        assert any(isinstance(v, str) and len(v) > 20 for v in en.to_dict().values()), block   # не заглушка


def test_stall_timeout_config():
    """Settings: stall_timeout - секунды тишины модели до перезапроса.
    Дефолт 30, пустое поле/мусор/старый settings.json без ключа -> 30, 0 -> выкл,
    round-trip, и в payload["options"] для Ollama НЕ попадает (это поведение
    самого приложения)."""
    assert InferenceConfig().stall_seconds() == 30
    assert InferenceConfig.from_dict({}).stall_timeout == 30          # старый settings.json
    assert InferenceConfig.from_dict({"stall_timeout": 45}).stall_seconds() == 45
    assert InferenceConfig.from_dict({"stall_timeout": 0}).stall_seconds() == 0
    assert InferenceConfig.from_dict({"stall_timeout": -5}).stall_seconds() == 0
    assert InferenceConfig.from_dict({"stall_timeout": "x"}).stall_seconds() == 30
    assert InferenceConfig.from_dict({"stall_timeout": True}).stall_seconds() == 30
    assert InferenceConfig.from_dict({"stall_timeout": None}).stall_seconds() == 30
    assert InferenceConfig(stall_timeout=None).stall_seconds() == 30   # пустое поле в UI
    c = InferenceConfig(stall_timeout=12)
    assert InferenceConfig.from_dict(c.to_dict()).stall_seconds() == 12
    assert "stall_timeout" not in InferenceConfig(stall_timeout=12).to_options()
    assert InferenceConfig.optimal().stall_seconds() == 30


def test_chat_stream_stall_timeout_real_socket():
    """chat_stream(stall_timeout): ответ начался (пришла строка с размышлением),
    потом тишина дольше таймаута -> OllamaStallError; быстрый ответ не
    задевается; stall_timeout=0 тишину не отслеживает. Настоящий локальный
    HTTP-сервер: фейковый ответ requests сокета не имеет, а именно на
    сужении таймаута сокета этот механизм и держится."""
    import json as _json, time as _time
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
    import ollama_client as oc

    mode = {"silent_s": 3.0}

    class H(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def log_message(self, *a):
            pass

        def do_POST(self):
            self.rfile.read(int(self.headers.get("Content-Length", 0)))
            self.send_response(200)
            self.send_header("Content-Type", "application/x-ndjson")
            self.send_header("Transfer-Encoding", "chunked")
            self.end_headers()

            def chunk(obj):
                b = (_json.dumps(obj) + "\n").encode()
                self.wfile.write(f"{len(b):x}\r\n".encode() + b + b"\r\n")
                self.wfile.flush()
            try:
                chunk({"message": {"thinking": "hmm"}, "done": False})
                _time.sleep(mode["silent_s"])
                chunk({"message": {"content": "ok"}, "done": False})
                chunk({"message": {"content": ""}, "done": True})
                self.wfile.write(b"0\r\n\r\n")
            except OSError:
                pass            # клиент оборвал соединение - так и задумано

    srv = ThreadingHTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    old_url = oc.OLLAMA_URL
    oc.OLLAMA_URL = f"http://127.0.0.1:{srv.server_address[1]}"
    msgs = [{"role": "user", "content": "x"}]
    try:
        seen = []
        t0 = _time.time()
        try:
            list(oc.chat_stream("m", msgs, on_thinking=seen.append, stall_timeout=1.0))
            raise AssertionError("тишина 3 с при таймауте 1 с должна дать OllamaStallError")
        except OllamaStallError as e:
            assert isinstance(e, OllamaError)
            assert _time.time() - t0 < 2.8, "сорвалось не по таймауту, а по концу тишины"
        assert seen == ["hmm"], seen      # размышление до зависания дошло

        mode["silent_s"] = 0.2           # быстрый ответ - таймер не мешает
        assert list(oc.chat_stream("m", msgs, stall_timeout=1.0)) == ["ok"]

        mode["silent_s"] = 1.5           # 0 = не следить: дожидаемся
        assert list(oc.chat_stream("m", msgs, stall_timeout=0)) == ["ok"]
    finally:
        oc.OLLAMA_URL = old_url
        srv.shutdown()


def test_chat_stream_stops_on_event():
    """chat_stream: выставленный stop_event обрывает выдачу токенов.

    Фейковый поток из 1000 строк; после третьего чанка ставим stop_event.
    Ожидаем ровно ["t0","t1","t2"] — генератор проверяет флаг перед
    каждой строкой и выходит сразу после set(). Это механизм «Стоп».
    """
    lines = [json.dumps({"message": {"content": f"t{i}"}}).encode() for i in range(1000)]
    stop_event = threading.Event()
    with mock.patch("ollama_client.requests.post", return_value=_FakeResp(lines)):
        out = []
        for chunk in chat_stream("m", [], stop_event=stop_event):
            out.append(chunk)
            if len(out) == 3:
                stop_event.set()
    assert out == ["t0", "t1", "t2"], out


def test_chat_stream_reports_request_payload():
    """chat_stream: колбэк on_request получает точный payload ДО отправки.

    on_request(payload) вызывается ровно один раз, до сетевого запроса,
    и получает тот же словарь, что уходит в requests.post(json=...):
    model, messages (тем же объектом), stream и options без правок.
    """
    seen = []
    msgs = [{"role": "system", "content": "S"}, {"role": "user", "content": "привет"}]
    with mock.patch("ollama_client.requests.post", return_value=_FakeResp()):
        list(chat_stream("mymodel", msgs, options={"temperature": 0.5, "num_ctx": 8192},
                         on_request=lambda p: seen.append(p)))

    assert len(seen) == 1, f"on_request вызван {len(seen)} раз, ожидали 1"
    p = seen[0]
    assert p["model"] == "mymodel", p["model"]
    assert p["messages"] == msgs, "содержимое messages изменилось"
    assert p["stream"] is True, p.get("stream")
    assert p["options"] == {"temperature": 0.5, "num_ctx": 8192}, p["options"]
    assert "think" not in p and "keep_alive" not in p, p


def test_chat_stream_passes_options_think_keepalive():
    """chat_stream: options / think / keep_alive в payload только когда заданы."""
    captured = []
    with mock.patch("ollama_client.requests.post", return_value=_FakeResp()):
        list(chat_stream("m", [], options={"num_ctx": 4096}, think=True,
                         keep_alive="-1", on_request=captured.append))
        list(chat_stream("m", [], on_request=captured.append))

    a, b = captured
    assert a["options"] == {"num_ctx": 4096} and a["think"] is True and a["keep_alive"] == "-1", a
    assert "options" not in b and "think" not in b and "keep_alive" not in b, b


def test_chat_stream_splits_thinking_field_from_content():
    """chat_stream: message.thinking -> on_thinking, message.content -> yield."""
    lines = [
        json.dumps({"message": {"thinking": "шаг 1 "}}).encode(),
        json.dumps({"message": {"thinking": "шаг 2"}}).encode(),
        json.dumps({"message": {"content": "Привет"}}).encode(),
        json.dumps({"message": {"content": ", мир"}}).encode(),
    ]
    thoughts = []
    with mock.patch("ollama_client.requests.post", return_value=_FakeResp(lines)):
        out = list(chat_stream("m", [], on_thinking=thoughts.append))
    assert out == ["Привет", ", мир"], out
    assert "".join(thoughts) == "шаг 1 шаг 2", thoughts


def test_chat_stream_strips_inline_think_tags():
    """chat_stream: инлайновые <think>...</think> в content уходят в on_thinking.

    Многие reasoning-GGUF (напр. Ministral-Reasoning с HuggingFace) не
    поддерживают поле think и пишут рассуждения прямо в текст ответа
    тегами <think>...</think>. Их надо вырезать в on_thinking, в чат
    отдать только ответ. Теги разорваны между чанками — проверяем, что
    склейка работает.
    """
    chunks = ["Ладно. <thi", "nk>сначала прики", "ну варианты</th", "ink> Привет, ",
              "как дела?"]
    lines = [json.dumps({"message": {"content": c}}).encode() for c in chunks]
    thoughts = []
    with mock.patch("ollama_client.requests.post", return_value=_FakeResp(lines)):
        out = "".join(chat_stream("m", [], on_thinking=thoughts.append))
    assert out == "Ладно.  Привет, как дела?", repr(out)
    assert "".join(thoughts) == "сначала прикину варианты", thoughts


def test_chat_stream_http_error_reads_body_detail():
    """chat_stream: при HTTP 400 текст {"error": ...} от Ollama виден в OllamaError.

    Так пользователь понимает, ПОЧЕМУ 400 (обычно: модель не
    поддерживает think). Тело читается, пока соединение живо.
    """
    resp = _FakeResp(status_code=400,
                     body={"error": '"hf.co/foo/bar" does not support thinking'})
    with mock.patch("ollama_client.requests.post", return_value=resp):
        try:
            list(chat_stream("hf.co/foo/bar", [], think=True))
        except OllamaError as e:
            assert "does not support thinking" in str(e), str(e)
            assert "400" in str(e), str(e)
        else:
            assert False, "ожидали OllamaError"


def test_model_capabilities():
    """model_capabilities: множество из /api/show; при ошибке — пустое."""
    ok = _FakeResp(body={"capabilities": ["completion", "tools", "thinking"]})
    with mock.patch("ollama_client.requests.post", return_value=ok):
        caps = model_capabilities("some-model")
    assert "thinking" in caps and "tools" in caps

    def _boom(*a, **k):
        import requests as _rq
        raise _rq.exceptions.ConnectionError("down")
    with mock.patch("ollama_client.requests.post", side_effect=_boom):
        assert model_capabilities("x") == set()

    no_field = _FakeResp(body={"details": {}})   # старая Ollama без capabilities
    with mock.patch("ollama_client.requests.post", return_value=no_field):
        assert model_capabilities("x") == set()


def test_think_splitter_unit():
    """_ThinkSplitter: разбор по кусочкам, незакрытый тег, отсутствие тегов."""
    from ollama_client import _ThinkSplitter

    # без тегов - всё видимо
    seen = []
    sp = _ThinkSplitter(seen.append)
    vis = "".join(sum([sp.feed("просто "), sp.feed("текст")], []))
    assert (vis + sp.flush()) == "просто текст" and seen == []

    # тег разорван по буквам
    seen = []
    sp = _ThinkSplitter(seen.append)
    parts = []
    for ch in "A<think>xy</think>B":
        parts += sp.feed(ch)
    parts.append(sp.flush())
    assert "".join(parts) == "AB", "".join(parts)
    assert "".join(seen) == "xy", seen

    # незакрытый <think> - остаток уходит в размышления, в чат ничего
    seen = []
    sp = _ThinkSplitter(seen.append)
    out = "".join(sp.feed("visible <think>tail without close"))
    out += sp.flush()
    assert out == "visible ", repr(out)
    assert "".join(seen) == "tail without close", seen


def test_parse_structured_reply():
    """parse_structured_reply: JSON {action, speech} -> кортеж; иначе фолбэк.

    В structured-режиме модель отвечает JSON'ом. Валидный -> (action,
    speech). Битый JSON / не-объект / отсутствие ключа -> ("", весь
    текст как реплика), без исключений.
    """
    a, s = parse_structured_reply('{"action": "она улыбнулась", "speech": "Привет."}')
    assert a == "она улыбнулась" and s == "Привет."

    a, s = parse_structured_reply('{"speech": "Только речь"}')
    assert a == "" and s == "Только речь"

    a, s = parse_structured_reply("не json вовсе")
    assert a == "" and s == "не json вовсе"

    a, s = parse_structured_reply('["массив"]')
    assert a == "" and s == '["массив"]'


def test_normalize_messages():
    """normalize_messages: подряд идущие роли схлопываются в одну (через \\n\\n).

    Chat-шаблоны Mistral/Ministral и т.п. падают на двух user подряд
    (бывает после ошибочной/пустой генерации). Функция чинит это перед
    отправкой, вход не мутирует.
    """
    src = [
        {"role": "system", "content": "S"},
        {"role": "user", "content": "u1"},
        {"role": "user", "content": "u2"},
        {"role": "assistant", "content": "a1"},
        {"role": "assistant", "content": ""},
        {"role": "user", "content": "u3"},
    ]
    src_copy = [dict(m) for m in src]
    out = normalize_messages(src)
    assert [m["role"] for m in out] == ["system", "user", "assistant", "user"], out
    assert out[1]["content"] == "u1\n\nu2"
    assert out[2]["content"] == "a1"          # пустой хвост без лишнего \n\n
    assert src == src_copy, "вход мутировал"
    assert normalize_messages([]) == []


def test_chat_stream_normalizes_before_send():
    """chat_stream: два user подряд в payload схлопываются в один."""
    seen = []
    with mock.patch("ollama_client.requests.post", return_value=_FakeResp()):
        list(chat_stream("m", [{"role": "system", "content": "S"},
                               {"role": "user", "content": "a"},
                               {"role": "user", "content": "b"}],
                         on_request=seen.append))
    roles = [m["role"] for m in seen[0]["messages"]]
    assert roles == ["system", "user"], roles
    assert seen[0]["messages"][1]["content"] == "a\n\nb"


def test_chat_stream_sends_response_format():
    """chat_stream: response_format -> payload["format"]; None -> ключа нет."""
    seen = []
    schema = {"type": "object", "properties": {"speech": {"type": "string"}}}
    with mock.patch("ollama_client.requests.post", return_value=_FakeResp()):
        list(chat_stream("m", [], response_format=schema, on_request=seen.append))
        list(chat_stream("m", [], on_request=seen.append))
    assert seen[0]["format"] == schema, seen[0]
    assert "format" not in seen[1], seen[1]


def test_chat_stream_no_inline_strip_when_disabled():
    """chat_stream: strip_inline_think=False -> <think> в тексте НЕ трогаем.

    В structured-режиме контент это чистый JSON; резать <think> там не
    нужно (и опасно). Поле message.thinking при этом всё равно ловится.
    """
    lines = [
        json.dumps({"message": {"thinking": "ход мыслей"}}).encode(),
        json.dumps({"message": {"content": '{"action": "<think>x</think>", '}}).encode(),
        json.dumps({"message": {"content": '"speech": "hi"}'}}).encode(),
    ]
    thoughts = []
    with mock.patch("ollama_client.requests.post", return_value=_FakeResp(lines)):
        out = "".join(chat_stream("m", [], on_thinking=thoughts.append,
                                  strip_inline_think=False))
    assert out == '{"action": "<think>x</think>", "speech": "hi"}', repr(out)
    assert thoughts == ["ход мыслей"], thoughts


def test_parse_stream_thinking():
    """parse_stream_thinking: достаёт message.thinking, иначе None.

    Пустой ввод, битый JSON и строка без thinking -> None (без
    исключений). Строка с непустым thinking -> его текст.
    """
    line = json.dumps({"message": {"thinking": "прикидываю", "content": ""}}).encode()
    assert parse_stream_thinking(line) == "прикидываю"
    assert parse_stream_thinking(
        json.dumps({"message": {"content": "текст"}}).encode()) is None
    assert parse_stream_thinking(b"") is None
    assert parse_stream_thinking(b"{ broken json") is None


# ======================================================================
#  ПАРАМЕТРЫ ГЕНЕРАЦИИ  (вкладка Settings — models.InferenceConfig)
# ======================================================================

def test_inference_config_roundtrip_and_unset():
    """Settings: InferenceConfig round-trip; незаданные числа остаются None.

    В settings.json пишется весь объект (в т.ч. null для незаданных
    полей). Проверяем, что заданные значения возвращаются как есть, а
    то, что не трогали, осталось None / "".
    """
    c = InferenceConfig(temperature=0.7, num_ctx=8192, seed=42,
                        stop="Ты:\nUser:", think=True, keep_alive="30m")
    c2 = InferenceConfig.from_dict(c.to_dict())
    assert (c2.temperature, c2.num_ctx, c2.seed) == (0.7, 8192, 42), vars(c2)
    assert c2.stop == "Ты:\nUser:" and c2.think is True and c2.keep_alive == "30m"
    assert c2.top_p is None and c2.top_k is None and c2.min_p is None

    empty = InferenceConfig.from_dict({})
    assert empty.temperature is None and empty.stop == "" and empty.think is None
    assert empty.structured_dialogue is False

    # structured_dialogue переживает round-trip и терпит мусор
    assert InferenceConfig(structured_dialogue=True).to_dict()["structured_dialogue"] is True
    assert InferenceConfig.from_dict({"structured_dialogue": "yes"}).structured_dialogue is False

    # digest_window - число или None, не попадает в options
    assert InferenceConfig.from_dict({"digest_window": 8}).digest_window == 8
    assert InferenceConfig.from_dict({"digest_window": "x"}).digest_window is None
    assert "digest_window" not in InferenceConfig(digest_window=8).to_options()

    # digest_prompt - строка, round-trip, не в options
    assert InferenceConfig.from_dict({"digest_prompt": "мой"}).digest_prompt == "мой"
    assert InferenceConfig.from_dict({}).digest_prompt == ""
    assert "digest_prompt" not in InferenceConfig(digest_prompt="мой").to_options()

    # right_panel_hidden / left_panel_hidden - UI-флаги, round-trip, не в options
    assert InferenceConfig.from_dict({"right_panel_hidden": True}).right_panel_hidden is True
    assert InferenceConfig.from_dict({}).right_panel_hidden is False
    assert "right_panel_hidden" not in InferenceConfig(right_panel_hidden=True).to_options()
    assert InferenceConfig.from_dict({"left_panel_hidden": True}).left_panel_hidden is True
    assert InferenceConfig.from_dict({}).left_panel_hidden is False
    assert "left_panel_hidden" not in InferenceConfig(left_panel_hidden=True).to_options()

    # ui_language - "ru" по умолчанию, round-trip, только "ru"/"en", не в options
    assert InferenceConfig.from_dict({}).ui_language == "ru"
    assert InferenceConfig.from_dict({"ui_language": "en"}).ui_language == "en"
    assert InferenceConfig.from_dict({"ui_language": "xx"}).ui_language == "ru"
    assert "ui_language" not in InferenceConfig(ui_language="en").to_options()

    # last_model - строка, round-trip, мусор -> "", не в options
    assert InferenceConfig.from_dict(
        {"last_model": "hf.co/Vikhrmodels/x:Q4_K_M"}).last_model == "hf.co/Vikhrmodels/x:Q4_K_M"
    assert InferenceConfig.from_dict({}).last_model == ""
    assert InferenceConfig.from_dict({"last_model": 42}).last_model == ""
    assert "last_model" not in InferenceConfig(last_model="m").to_options()


def test_inference_config_to_options():
    """Settings: to_options() кладёт только заданные поля; stop -> список строк.

    think и keep_alive - НЕ параметры options (верхний уровень payload),
    в options их быть не должно. Пустые строки в stop отбрасываются.
    """
    c = InferenceConfig(temperature=0.9, top_k=50, num_ctx=4096,
                        stop="END\n   \n<stop>", think=False, keep_alive="-1")
    assert c.to_options() == {"temperature": 0.9, "top_k": 50, "num_ctx": 4096,
                              "stop": ["END", "<stop>"]}
    assert InferenceConfig().to_options() == {}, "пустой конфиг не должен слать ничего"


def test_inference_config_from_dict_ignores_bad_types():
    """Settings: мусор в JSON (строка вместо числа, bool в seed) -> None, не падаем."""
    c = InferenceConfig.from_dict({"temperature": "hot", "top_k": None,
                                   "seed": True, "num_ctx": 8192,
                                   "think": "maybe"})
    assert c.temperature is None and c.top_k is None and c.seed is None
    assert c.num_ctx == 8192
    assert c.think is None, "нестрогое значение think должно стать None"


def test_settings_store_roundtrip():
    """Хранилище: settings.json — один объект, save_settings / load_settings.

    Файла нет -> рекомендованный набор (InferenceConfig.optimal()), чтобы
    оптимальные значения действовали сразу, без захода во вкладку
    Settings. После save читаем обратно.
    """
    tmp = Path(tempfile.mkdtemp())
    try:
        store = PresetStore(data_dir=tmp)
        default = store.load_settings()
        assert default == InferenceConfig.optimal(), vars(default)
        assert default.num_ctx == 8192, vars(default)

        store.save_settings(InferenceConfig(temperature=1.1, num_ctx=16384,
                                            stop="Ты:"))
        got = store.load_settings()
        assert got.temperature == 1.1 and got.num_ctx == 16384 and got.stop == "Ты:"

        raw = json.loads(store.settings_file.read_text(encoding="utf-8"))
        assert raw["num_ctx"] == 16384, raw
    finally:
        shutil.rmtree(tmp)


def test_inference_config_optimal():
    """Settings: InferenceConfig.optimal() = OPTIMAL_INFERENCE, ключи валидны.

    Кнопка «Optimal» и дефолт первого запуска берут именно этот набор.
    Проверяем: все ключи OPTIMAL_INFERENCE — реальные поля dataclass;
    optimal() их проставляет; seed/stop/think/keep_alive остаются
    незаданными (для RP так и надо); to_options() отдаёт числовые ручки.
    """
    model_attrs = {f.name for f in dataclass_fields(InferenceConfig)}
    for k in OPTIMAL_INFERENCE:
        assert k in model_attrs, f"OPTIMAL_INFERENCE: '{k}' нет в InferenceConfig"

    opt = InferenceConfig.optimal()
    for k, v in OPTIMAL_INFERENCE.items():
        assert getattr(opt, k) == v, (k, getattr(opt, k))
    assert opt.seed is None and opt.stop == "" and opt.think is None
    assert opt.keep_alive == ""

    o = opt.to_options()
    assert o["num_ctx"] == OPTIMAL_INFERENCE["num_ctx"]
    assert o["temperature"] == OPTIMAL_INFERENCE["temperature"]
    assert o["min_p"] == OPTIMAL_INFERENCE["min_p"]
    assert "stop" not in o and "think" not in o


def test_inference_spec_matches_dataclass():
    """inference_spec: каждый attr есть в InferenceConfig, kind валиден, help не пуст.

    Плюс проверяем, что все ходовые ручки варианта B действительно
    выведены в UI.
    """
    model_attrs = {f.name for f in dataclass_fields(InferenceConfig)}
    shown = set()
    for spec in INFERENCE_FIELDS:
        assert spec["attr"] in model_attrs, f"{spec['attr']} нет в InferenceConfig"
        assert spec["kind"] in ("float", "int", "str", "stoplist", "think", "bool"), spec
        assert spec["help"].strip(), f"{spec['attr']}: пустой help"
        shown.add(spec["attr"])
    for must in ("temperature", "top_p", "top_k", "min_p", "repeat_penalty",
                 "repeat_last_n", "num_predict", "num_ctx", "seed", "stop", "think"):
        assert must in shown, f"поле {must} не выведено на вкладку Settings"


def test_parse_stream_line_extracts_text():
    """parse_stream_line: из строки-JSON ответа Ollama достаётся текст чанка.

    Одна строка потока Ollama — это JSON с полем message.content.
    Функция должна вернуть именно этот текст. Разбор вынесен в чистую
    функцию как раз чтобы проверять его без сети.
    """
    line = json.dumps({
        "model": "llama3.2",
        "message": {"role": "assistant", "content": "Привет"},
        "done": False,
    }).encode("utf-8")
    assert parse_stream_line(line) == "Привет", parse_stream_line(line)


def test_parse_stream_line_handles_empty_and_done():
    """parse_stream_line: пустая строка и финальный чанк дают None.

    Пустой ввод -> None. Финальная строка потока (done=True, content="")
    тоже -> None, чтобы в чат не улетал пустой хвост. Вызывающий код
    просто пропускает None.
    """
    assert parse_stream_line(b"") is None, "пустая строка вернула не None"
    done_line = json.dumps({
        "model": "llama3.2", "message": {"role": "assistant", "content": ""},
        "done": True,
    }).encode("utf-8")
    assert parse_stream_line(done_line) is None, "финальный чанк вернул не None"


# ======================================================================
#  РАННЕР
# ======================================================================

def _short_desc(fn) -> str:
    """Первая непустая строка docstring — краткое описание для консоли."""
    doc = (fn.__doc__ or "").strip()
    return doc.splitlines()[0] if doc else "(без описания)"


def run_all() -> int:
    # По порядку определения в файле, а не по алфавиту.
    tests = sorted(
        (v for k, v in globals().items()
         if k.startswith("test_") and callable(v)),
        key=lambda f: f.__code__.co_firstlineno,
    )

    total = len(tests)
    width = len(str(total))
    print("=" * 70)
    print(f"  Тесты Ollama RP  —  {total} шт.")
    print("=" * 70)

    failed = []
    for i, fn in enumerate(tests, 1):
        num = f"[{i:>{width}}/{total}]"
        print(f"\n{num} {fn.__name__}")
        print(f"{' ' * (len(num) + 1)}{_short_desc(fn)}")
        try:
            fn()
        except Exception as e:            # noqa: BLE001 — нам нужны все типы
            failed.append(fn.__name__)
            tb = traceback.extract_tb(e.__traceback__)[-1]
            print(f"{' ' * (len(num) + 1)}... УПАЛО")
            print(f"{' ' * (len(num) + 1)}{type(e).__name__}: {e}")
            print(f"{' ' * (len(num) + 1)}{Path(tb.filename).name}:{tb.lineno}  ->  {tb.line}")
        else:
            print(f"{' ' * (len(num) + 1)}... OK")

    print("\n" + "-" * 70)
    if failed:
        print(f"  ИТОГ: прошло {total - len(failed)} из {total}, УПАЛО {len(failed)}:")
        for name in failed:
            print(f"    - {name}")
        print("-" * 70)
        return 1
    print(f"  ИТОГ: прошло {total} из {total}. Всё зелёное.")
    print("-" * 70)
    return 0


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8")   # ровный вывод и при перенаправлении
    except Exception:
        pass
    sys.exit(run_all())
