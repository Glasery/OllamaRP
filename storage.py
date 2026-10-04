"""
Хранилище пресетов: сохраняет и загружает списки персонажей, окружений,
сценариев и конфигурационных промптов в обычные JSON-файлы. База данных
не нужна - для личного использования пары десятков пресетов JSON более
чем достаточно, а код при этом проще читать и отлаживать.

Каждый тип лежит в своём файле и управляется независимо:
characters.json / protagonists.json / environments.json / scenarios.json /
system_configs.json.
"""
import json
import os
import sys
import time
from pathlib import Path
from typing import List, TypeVar

import photos

from models import (Character, Protagonist, Environment, Scenario, SystemConfig,
                    InferenceConfig)


def get_data_dir() -> Path:
    """
    Папка для хранения данных приложения.
    Windows: %APPDATA%/OllamaRP
    Остальные ОС: ~/.ollama_rp
    """
    if sys.platform == "win32":
        base = os.environ.get("APPDATA", str(Path.home()))
        data_dir = Path(base) / "OllamaRP"
    else:
        data_dir = Path.home() / ".ollama_rp"
    data_dir.mkdir(parents=True, exist_ok=True)
    return data_dir


_T = TypeVar("_T")


def _upsert(items: list, new_item) -> list:
    """
    Вставить или обновить пресет в списке. Матчим сначала по id (чтобы
    переименование уже сохранённого пресета не плодило дубль), потом по
    name (чтобы повторное "Сохранить" под тем же именем перезаписывало).
    Возвращает тот же список (мутирует его на месте).
    """
    for i, existing in enumerate(items):
        if existing.id == new_item.id or (
            new_item.name and existing.name == new_item.name
        ):
            items[i] = new_item
            return items
    items.append(new_item)
    return items


class PresetStore:
    def __init__(self, data_dir: Path = None):
        self.data_dir = data_dir or get_data_dir()
        self.characters_file = self.data_dir / "characters.json"
        self.protagonists_file = self.data_dir / "protagonists.json"
        self.environments_file = self.data_dir / "environments.json"
        self.scenarios_file = self.data_dir / "scenarios.json"
        self.system_configs_file = self.data_dir / "system_configs.json"
        self.settings_file = self.data_dir / "settings.json"
        self.photos_dir = self.data_dir / "photos"      # создаётся при первом фото

    @staticmethod
    def _quarantine(path: Path) -> None:
        """Файл данных повреждён (оборванная запись, правка вручную): не
        падаем при запуске и НЕ даём следующему сохранению молча затереть
        то, что в нём ещё можно спасти - откладываем его рядом как
        `<имя>.corrupt-<время>`."""
        try:
            os.replace(path, path.with_name(f"{path.name}.corrupt-{time.strftime('%Y%m%d-%H%M%S')}"))
        except OSError:
            pass

    @classmethod
    def _read_json(cls, path: Path):
        """JSON-файл -> объект или None (нет файла / пусто / повреждён - в
        этом случае файл откладывается, см. _quarantine). BOM допустим
        (Блокнот Windows добавляет его при ручной правке)."""
        if not path.exists():
            return None
        try:
            with open(path, "r", encoding="utf-8-sig") as f:
                return json.load(f)
        except (ValueError, UnicodeDecodeError):
            cls._quarantine(path)
            return None
        except OSError:
            return None

    @classmethod
    def _load(cls, path: Path) -> list:
        """Список записей-словарей (повреждённое/не список -> [], мусорные
        элементы пропускаются)."""
        data = cls._read_json(path)
        if data is None:
            return []
        if not isinstance(data, list):
            cls._quarantine(path)
            return []
        return [d for d in data if isinstance(d, dict)]

    @staticmethod
    def _write_json(path: Path, obj) -> None:
        """Атомарная запись: во временный файл и os.replace - оборванное
        сохранение (сбой питания, закончилось место) не оставляет
        половину JSON на месте рабочего файла."""
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_name(path.name + ".tmp")
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(obj, f, ensure_ascii=False, indent=2)
        os.replace(tmp, path)

    @classmethod
    def _save(cls, path: Path, items: list) -> None:
        cls._write_json(path, items)

    # --- персонажи ---
    def load_characters(self) -> List[Character]:
        return [Character.from_dict(d) for d in self._load(self.characters_file)]

    def save_characters(self, characters: List[Character]) -> None:
        self._save(self.characters_file, [c.to_dict() for c in characters])

    def upsert_character(self, character: Character) -> None:
        self.save_characters(_upsert(self.load_characters(), character))
        self.cleanup_photos()

    def delete_character(self, char_id: str) -> None:
        self.save_characters([c for c in self.load_characters() if c.id != char_id])
        self.cleanup_photos()

    # --- главные герои (Вы) ---
    def load_protagonists(self) -> List[Protagonist]:
        return [Protagonist.from_dict(d) for d in self._load(self.protagonists_file)]

    def save_protagonists(self, protagonists: List[Protagonist]) -> None:
        self._save(self.protagonists_file, [p.to_dict() for p in protagonists])

    def upsert_protagonist(self, protagonist: Protagonist) -> None:
        self.save_protagonists(_upsert(self.load_protagonists(), protagonist))
        self.cleanup_photos()

    def delete_protagonist(self, prot_id: str) -> None:
        self.save_protagonists([p for p in self.load_protagonists() if p.id != prot_id])
        self.cleanup_photos()

    # --- фото персонажей / героев ---
    def import_photo(self, src_path: str) -> str:
        """Скопировать выбранную картинку в photos/ (уменьшив) -> имя файла.
        Бросает photos.PhotoError, если это не картинка / нет Pillow."""
        return photos.import_photo(src_path, self.photos_dir)

    def import_emote(self, src_path: str) -> str:
        """Как import_photo, но файл обязан быть PNG на прозрачном фоне
        (photos.EmoteError, если нет - вызывающий показывает алерт)."""
        return photos.import_emote(src_path, self.photos_dir)

    def photo_path(self, name: str):
        """Путь к файлу фото по имени из пресета или None (нет/удалён)."""
        return photos.photo_file(self.photos_dir, name)

    def cleanup_photos(self) -> int:
        """Убрать из photos/ файлы, на которые не ссылается ни один персонаж
        или герой: после удаления пресета, замены фото и отменённого
        редактирования (там фото импортируется сразу при выборе). Зовётся
        после каждого сохранения/удаления - папка не копит мусор."""
        used = []
        for o in self.load_characters() + self.load_protagonists():
            used += [o.photo, *o.gallery, *o.emotes]
        return photos.cleanup_unused(self.photos_dir, used)

    # --- окружения ---
    def load_environments(self) -> List[Environment]:
        return [Environment.from_dict(d) for d in self._load(self.environments_file)]

    def save_environments(self, environments: List[Environment]) -> None:
        self._save(self.environments_file, [e.to_dict() for e in environments])

    def upsert_environment(self, environment: Environment) -> None:
        self.save_environments(_upsert(self.load_environments(), environment))

    def delete_environment(self, env_id: str) -> None:
        self.save_environments([e for e in self.load_environments() if e.id != env_id])

    # --- сценарии ---
    def load_scenarios(self) -> List[Scenario]:
        return [Scenario.from_dict(d) for d in self._load(self.scenarios_file)]

    def save_scenarios(self, scenarios: List[Scenario]) -> None:
        self._save(self.scenarios_file, [s.to_dict() for s in scenarios])

    def upsert_scenario(self, scenario: Scenario) -> None:
        self.save_scenarios(_upsert(self.load_scenarios(), scenario))

    def delete_scenario(self, scn_id: str) -> None:
        self.save_scenarios([s for s in self.load_scenarios() if s.id != scn_id])

    # --- конфигурационные промпты ---
    def load_system_configs(self) -> List[SystemConfig]:
        return [SystemConfig.from_dict(d) for d in self._load(self.system_configs_file)]

    def save_system_configs(self, configs: List[SystemConfig]) -> None:
        self._save(self.system_configs_file, [c.to_dict() for c in configs])

    def upsert_system_config(self, config: SystemConfig) -> None:
        self.save_system_configs(_upsert(self.load_system_configs(), config))

    def delete_system_config(self, cfg_id: str) -> None:
        self.save_system_configs(
            [c for c in self.load_system_configs() if c.id != cfg_id])

    # --- параметры генерации (один объект на приложение) ---
    def load_settings(self) -> InferenceConfig:
        if not self.settings_file.exists():
            # первый запуск - сразу рекомендованные значения
            return InferenceConfig.optimal()
        data = self._read_json(self.settings_file)
        # повреждённый/не-объект -> дефолты (файл отложен в .corrupt-*)
        if data is not None and not isinstance(data, dict):
            self._quarantine(self.settings_file)
            data = None
        return InferenceConfig.from_dict(data or {})

    def save_settings(self, cfg: InferenceConfig) -> None:
        self._write_json(self.settings_file, cfg.to_dict())
