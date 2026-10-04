"""
Модели данных приложения: Персонаж, Главный герой (Вы), Окружение,
Сценарий, Конфигурационный промпт.

Простые dataclass'ы - минимум магии, чтобы было легко читать и менять.
У каждого блока есть id + name, каждый сохраняется/загружается
независимо от остальных.
"""
from dataclasses import dataclass, field, asdict
from typing import Optional
import uuid

from dynamic_memory import DYN_MEMORY_LIMIT, clamp_limit


def _new_id() -> str:
    return uuid.uuid4().hex[:8]


def _s(v) -> str:
    """Строковое поле из JSON: str как есть, число -> строка, остальное
    (None/список/dict/bool) -> "" - руками правленый или повреждённый файл не
    должен ронять сборку промпта на .strip()."""
    if isinstance(v, str):
        return v
    if isinstance(v, (int, float)) and not isinstance(v, bool):
        return str(v)
    return ""


def _id(v) -> str:
    """id пресета из JSON; нет/пусто/не строка -> новый (иначе у записей без id
    все совпали бы по "" и upsert затирал бы друг друга)."""
    return v if isinstance(v, str) and v.strip() else _new_id()


def _str_list(v) -> list:
    """Список непустых строк из JSON (мусор/не список -> [])."""
    return [x for x in v if isinstance(x, str) and x] if isinstance(v, list) else []


@dataclass
class Character:
    id: str = field(default_factory=_new_id)
    name: str = ""
    appearance: str = ""
    personality: str = ""
    biography: str = ""          # предыстория персонажа
    speech_style: str = ""       # опционально: манера речи
    typical_phrases: str = ""    # опционально: характерные реплики персонажа
                                  # (ориентир для модели при генерации ответов)
    photo: str = ""              # АВАТАР (одно фото, рядом с репликами в чате):
                                  # ИМЯ файла в папке photos/ (см. photos.py)
    gallery: list = field(default_factory=list)   # ГАЛЕРЕЯ: имена файлов, только вкладка «Фото»
    emotes: list = field(default_factory=list)    # ЭМОТИКОНЫ: PNG-силуэты на прозрачном
                                                  # фоне, меняются на каждый ответ; поверх интерфейса
    # Фото в промпт модели НЕ попадают.
    dyn_enabled: bool = False    # ДИНАМИЧЕСКАЯ ПАМЯТЬ включена (только у собеседника;
                                  # см. dynamic_memory.py)
    dyn_memory: str = ""         # её текст: самое важное, что с персонажем случилось;
                                  # подставляется в его блок промпта, обновляется приложением

    def to_dict(self) -> dict:
        return asdict(self)

    @staticmethod
    def from_dict(d: dict) -> "Character":
        keys = ("id", "name", "appearance", "personality", "biography",
                "speech_style", "photo")
        kwargs = {k: _s(d.get(k)) for k in keys}
        kwargs["id"] = _id(d.get("id"))
        kwargs["dyn_enabled"] = d.get("dyn_enabled") is True
        kwargs["dyn_memory"] = _s(d.get("dyn_memory")) if isinstance(d.get("dyn_memory"), str) else ""
        kwargs["gallery"] = _str_list(d.get("gallery"))
        kwargs["emotes"] = _str_list(d.get("emotes"))
        # typical_phrases заменило неиспользовавшееся first_message; старые
        # записи на диске читаем как задел (пусто у всех, кто его не трогал).
        kwargs["typical_phrases"] = _s(d.get("typical_phrases")) or _s(d.get("first_message"))
        return Character(**kwargs)


@dataclass
class Protagonist:
    """
    Главный герой, которым управляет пользователь ("Вы"). Модель НЕ
    отыгрывает его - он нужен, чтобы персонажи/рассказ знали, с кем
    имеют дело.
    """
    id: str = field(default_factory=_new_id)
    name: str = ""
    biography: str = ""
    appearance: str = ""
    personality: str = ""
    photo: str = ""              # АВАТАР (одно фото в чате), как у Character
    gallery: list = field(default_factory=list)   # ГАЛЕРЕЯ (вкладка «Фото»)
    emotes: list = field(default_factory=list)    # ЭМОТИКОНЫ (PNG на прозрачном фоне)

    def to_dict(self) -> dict:
        return asdict(self)

    @staticmethod
    def from_dict(d: dict) -> "Protagonist":
        keys = ("id", "name", "biography", "appearance", "personality", "photo")
        kwargs = {k: _s(d.get(k)) for k in keys}
        kwargs["id"] = _id(d.get("id"))
        kwargs["gallery"] = _str_list(d.get("gallery"))
        kwargs["emotes"] = _str_list(d.get("emotes"))
        return Protagonist(**kwargs)


@dataclass
class Environment:
    id: str = field(default_factory=_new_id)
    name: str = ""
    location: str = ""
    time_of_day: str = ""
    weather: str = ""
    atmosphere: str = ""         # свободные заметки про атмосферу

    def to_dict(self) -> dict:
        return asdict(self)

    @staticmethod
    def from_dict(d: dict) -> "Environment":
        keys = ("id", "name", "location", "time_of_day", "weather", "atmosphere")
        return Environment(**{**{k: _s(d.get(k)) for k in keys}, "id": _id(d.get("id"))})


@dataclass
class Scenario:
    id: str = field(default_factory=_new_id)
    name: str = ""
    base_scenario: str = ""
    additional_params: str = ""

    def to_dict(self) -> dict:
        return asdict(self)

    @staticmethod
    def from_dict(d: dict) -> "Scenario":
        keys = ("id", "name", "base_scenario", "additional_params")
        return Scenario(**{**{k: _s(d.get(k)) for k in keys}, "id": _id(d.get("id"))})


@dataclass
class SystemConfig:
    """
    Общие правила поведения модели, не зависящие от конкретного
    персонажа/сцены (язык ответа, длина, стиль и т.п.). Четвёртый
    независимый блок конструктора.
    """
    id: str = field(default_factory=_new_id)
    name: str = ""
    content: str = ""            # свободный текст правил

    def to_dict(self) -> dict:
        return asdict(self)

    @staticmethod
    def from_dict(d: dict) -> "SystemConfig":
        keys = ("id", "name", "content")
        return SystemConfig(**{**{k: _s(d.get(k)) for k in keys}, "id": _id(d.get("id"))})


# Рекомендованные значения для ролплея/историй. Применяются при первом
# запуске (нет settings.json) и по кнопке «Optimal» во вкладке Settings.
# seed / stop / think / keep_alive намеренно НЕ заданы:
#   seed   - пусто = каждый ответ разный (для RP это плюс);
#   stop   - стоп-строки ситуативны, общий дефолт может навредить;
#   think  - «как у модели» = не ломать не-reasoning модели;
#   keep_alive - пусто = дефолт Ollama (5m).
OPTIMAL_INFERENCE = {
    "temperature": 0.75,
    "top_p": 0.9,
    "top_k": 40,
    "min_p": 0.08,               # жёстче режем «хвост» -> меньше переходов на англ.
    "repeat_penalty": 1.05,      # выше 1.05 на русском провоцирует смешение языков
    "repeat_last_n": 64,         # узкое окно штрафа - не давит частотные русские слова
    "num_predict": -1,
    "num_ctx": 8192,
    "structured_dialogue": True,   # раздельный вывод действие/речь через JSON
    "digest_window": 6,           # сколько последних ходов слать дословно
    "stall_timeout": 30,         # секунд тишины -> считаем, что модель зависла
}

# Дефолт таймаута «модель замолчала» (секунды); 0 в настройках = выключено.
STALL_TIMEOUT_DEFAULT = 30

# Режимы показа эмотиконов (кнопка вверху, по кругу): все / только собеседник /
# скрыты. Порядок = порядок переключения.
EMOTES_MODES = ("all", "companion", "hidden")


@dataclass
class InferenceConfig:
    """
    Параметры генерации, уходящие в Ollama с КАЖДЫМ запросом (и в
    диалоге, и в истории). Числовое поле == None -> не отправлять, пусть
    решает модель/Modelfile. `stop` - сырой многострочный текст (одна
    стоп-строка на строку). `think`: None = не навязывать, True/False =
    явно вкл/выкл размышления. `keep_alive` - строка вида "5m" / "-1" / "0".

    Это НЕ пресет: одна на приложение, лежит в settings.json.
    `InferenceConfig.optimal()` - рекомендованный набор (OPTIMAL_INFERENCE).
    """
    temperature: Optional[float] = None
    top_p: Optional[float] = None
    top_k: Optional[int] = None
    min_p: Optional[float] = None
    repeat_penalty: Optional[float] = None
    repeat_last_n: Optional[int] = None
    num_predict: Optional[int] = None
    num_ctx: Optional[int] = None
    seed: Optional[int] = None
    stop: str = ""
    think: Optional[bool] = None
    keep_alive: str = ""
    structured_dialogue: bool = False   # ответ модели строго: действие + речь (JSON)
    digest_window: Optional[int] = None  # N: пересборка памяти каждые N ходов; 0/None -> выкл
    digest_prompt: str = ""             # свой system-промпт генерации памяти ("" -> дефолт)
    right_panel_hidden: bool = False    # UI: панель Logs/Память свёрнута
    left_panel_hidden: bool = False     # UI: левая панель (Сцена/Settings) свёрнута
    ui_language: str = "ru"             # UI: язык интерфейса ("ru" / "en")
    stall_timeout: Optional[int] = STALL_TIMEOUT_DEFAULT  # сек тишины -> перезапрос; 0 -> выкл
    show_avatars: bool = True           # АВАТАРЫ: фото рядом с репликами в чате (диалог)
    show_gallery: bool = True           # ГАЛЕРЕЯ: вкладки «Фото» в боковых панелях (диалог)
    show_emotes: bool = False           # ЭМОТИКОНЫ поверх интерфейса (экспериментально, Windows)
    emotes_mode: str = "all"            # UI: кнопка вверху - "all" / "companion" (только
                                        # собеседник) / "hidden" (свёрнуты)
    dyn_memory_limit: Optional[int] = DYN_MEMORY_LIMIT  # предел динамической памяти, симв.
    last_model: str = ""                # UI: последняя выбранная модель (список моделей)

    # какие поля идут в payload["options"] (остальное - верхний уровень)
    _OPTION_KEYS = ("temperature", "top_p", "top_k", "min_p", "repeat_penalty",
                    "repeat_last_n", "num_predict", "num_ctx", "seed")

    @classmethod
    def optimal(cls) -> "InferenceConfig":
        """Рекомендованный набор параметров (см. OPTIMAL_INFERENCE)."""
        return cls(**OPTIMAL_INFERENCE)

    def to_dict(self) -> dict:
        return asdict(self)

    def dyn_limit(self) -> int:
        """Предел динамической памяти персонажа (символов): пусто/мусор ->
        дефолт, иначе в границах dynamic_memory.DYN_LIMIT_MIN..MAX. НЕ в
        options для Ollama - поведение самого приложения."""
        return clamp_limit(self.dyn_memory_limit)

    def stall_seconds(self) -> int:
        """Таймаут «модель замолчала» в секундах: пустое поле (None) -> дефолт,
        0 и меньше -> 0 (выключено). НЕ входит в options для Ollama - это
        поведение самого приложения (см. App._generate_worker)."""
        v = self.stall_timeout
        return STALL_TIMEOUT_DEFAULT if v is None else max(0, int(v))

    @staticmethod
    def from_dict(d: dict) -> "InferenceConfig":
        d = d or {}

        def _num(key):
            v = d.get(key)
            # bool - подкласс int, его сюда пускать нельзя
            return v if isinstance(v, (int, float)) and not isinstance(v, bool) else None

        think = d.get("think")
        sd = d.get("structured_dialogue")
        # нет ключа (старый settings.json) / мусор / null -> дефолт, а не None
        st = d.get("stall_timeout")
        # Старые имена (до разделения фото на 3 вида): show_photos -> аватары,
        # photo_overlay -> эмотиконы. Нет ключа / мусор -> дефолт.
        sa = d.get("show_avatars", d.get("show_photos"))
        sg = d.get("show_gallery")
        se = d.get("show_emotes", d.get("photo_overlay"))
        # режим кнопки эмотиконов; старый bool emotes_hidden: True -> "hidden"
        em = d.get("emotes_mode")
        if em not in EMOTES_MODES:
            em = "hidden" if d.get("emotes_hidden") is True else "all"
        if isinstance(st, (int, float)) and not isinstance(st, bool):
            st = int(st)
        else:
            st = STALL_TIMEOUT_DEFAULT
        return InferenceConfig(
            temperature=_num("temperature"), top_p=_num("top_p"), top_k=_num("top_k"),
            min_p=_num("min_p"), repeat_penalty=_num("repeat_penalty"),
            repeat_last_n=_num("repeat_last_n"), num_predict=_num("num_predict"),
            num_ctx=_num("num_ctx"), seed=_num("seed"),
            stop=_s(d.get("stop")),
            think=think if isinstance(think, bool) else None,
            keep_alive=_s(d.get("keep_alive")),
            structured_dialogue=sd if isinstance(sd, bool) else False,
            digest_window=_num("digest_window"),
            digest_prompt=_s(d.get("digest_prompt")),
            right_panel_hidden=bool(d.get("right_panel_hidden")),
            left_panel_hidden=bool(d.get("left_panel_hidden")),
            ui_language="en" if str(d.get("ui_language")).lower() == "en" else "ru",
            stall_timeout=st,
            show_avatars=sa if isinstance(sa, bool) else True,
            show_gallery=sg if isinstance(sg, bool) else True,
            show_emotes=se if isinstance(se, bool) else False,
            emotes_mode=em,
            dyn_memory_limit=clamp_limit(d.get("dyn_memory_limit")),
            last_model=d.get("last_model") if isinstance(d.get("last_model"), str) else "",
        )

    def to_options(self) -> dict:
        """Словарь для payload['options'] - только реально заданные поля."""
        opts = {}
        for k in self._OPTION_KEYS:
            v = getattr(self, k)
            if v is not None:
                opts[k] = v
        stops = [s.strip() for s in self.stop.splitlines() if s.strip()]
        if stops:
            opts["stop"] = stops
        return opts
