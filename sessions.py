"""
Сохранённые диалоги («сессии»): снимок состояния приложения в один JSON-файл,
чтобы продолжить с того же места после следующего запуска.

Чистая логика без tkinter (тестируется отдельно). Что кладётся в снимок -
решает gui.App (`_session_snapshot` / `_session_apply`); здесь только
хранение: папка `<данные>/sessions`, по файлу `<id>.json` на сессию.

- запись атомарная (временный файл + os.replace): оборванное сохранение
  (выключили питание, закончилось место) не портит уже лежащую сессию;
- битый / чужой файл не ломает список - он просто пропускается;
- id проверяется (hex), по нему нельзя выйти из папки sessions.
"""
import json
import os
import re
import time
import uuid
from pathlib import Path

SESSION_VERSION = 1
_ID_RE = re.compile(r"^[0-9a-f]{6,32}$")


class SessionError(Exception):
    """Сессию не удалось прочитать / записать (текст - для показа пользователю)."""


def new_id() -> str:
    return uuid.uuid4().hex[:12]


class SessionStore:
    def __init__(self, data_dir: Path):
        self.dir = Path(data_dir) / "sessions"        # создаётся при первом сохранении

    def _path(self, session_id: str) -> Path:
        if not isinstance(session_id, str) or not _ID_RE.match(session_id):
            raise SessionError(f"bad session id: {session_id!r}")
        return self.dir / f"{session_id}.json"

    def save(self, data: dict, name: str, session_id: str = None) -> dict:
        """Записать снимок `data` под именем `name`. `session_id` задан и такая
        сессия есть - перезапись (id и дата создания сохраняются), иначе новая.
        -> метаданные записанной сессии (как в list())."""
        sid = session_id or new_id()
        path = self._path(sid)
        now = time.strftime("%Y-%m-%dT%H:%M:%S")
        created = now
        if path.exists():
            try:
                created = json.loads(path.read_text(encoding="utf-8")).get("created_at", now)
            except (OSError, ValueError):
                pass
        doc = {"version": SESSION_VERSION, "id": sid, "name": (name or "").strip(),
               "created_at": created, "saved_at": now, "data": data}
        try:
            self.dir.mkdir(parents=True, exist_ok=True)
            tmp = path.with_suffix(".json.tmp")
            tmp.write_text(json.dumps(doc, ensure_ascii=False, indent=1), encoding="utf-8")
            os.replace(tmp, path)
        except (OSError, TypeError, ValueError) as e:     # TypeError/ValueError - несериализуемые данные
            raise SessionError(str(e)) from e
        return self._meta(doc)

    @staticmethod
    def _meta(doc: dict) -> dict:
        d = doc.get("data") or {}
        return {"id": doc.get("id", ""), "name": doc.get("name", ""),
                "saved_at": doc.get("saved_at", ""), "created_at": doc.get("created_at", ""),
                "mode": d.get("mode", ""), "model": d.get("model", ""),
                "turns": len(d.get("history") or [])}

    def list(self) -> list:
        """Метаданные всех читаемых сессий, самые свежие первыми."""
        out = []
        if not self.dir.is_dir():
            return out
        for p in self.dir.glob("*.json"):
            if not _ID_RE.match(p.stem):
                continue
            try:
                doc = json.loads(p.read_text(encoding="utf-8"))
                if isinstance(doc, dict) and doc.get("id") == p.stem:
                    out.append(self._meta(doc))
            except (OSError, ValueError):
                continue                                  # битый файл - пропускаем
        out.sort(key=lambda m: m["saved_at"], reverse=True)
        return out

    def load(self, session_id: str) -> dict:
        """-> снимок (`data`) сессии. SessionError - нет файла / повреждён /
        версия новее, чем понимает эта сборка."""
        path = self._path(session_id)
        try:
            doc = json.loads(path.read_text(encoding="utf-8"))
        except FileNotFoundError as e:
            raise SessionError("not found") from e
        except (OSError, ValueError) as e:
            raise SessionError(str(e)) from e
        if not isinstance(doc, dict) or not isinstance(doc.get("data"), dict):
            raise SessionError("bad format")
        if int(doc.get("version", 0) or 0) > SESSION_VERSION:
            raise SessionError("newer version")
        return doc["data"]

    def delete(self, session_id: str) -> None:
        try:
            self._path(session_id).unlink()
        except FileNotFoundError:
            pass
        except OSError as e:
            raise SessionError(str(e)) from e


# ---- нормализация снимка перед применением ----
_MODES = ("dialogue", "story", "chat")


def _str(v) -> str:
    return v if isinstance(v, str) else ""


def _clamp_int(v, lo, hi) -> int:
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        return lo
    return max(lo, min(hi, int(v)))


def normalize_snapshot(d, max_dyn_new: int = 8) -> dict:
    """Любой JSON-объект -> снимок с ГАРАНТИРОВАННЫМИ типами полей (файл могли
    править руками, повредить или записать другой версией). Применять к
    приложению можно только нормализованное: иначе искажённое поле роняло бы
    загрузку посередине, оставив диалог наполовину загруженным. Лишнее/
    непонятное отбрасывается, индексы зажимаются в допустимые границы."""
    d = d if isinstance(d, dict) else {}
    hist = [{"role": m["role"], "content": m["content"]}
            for m in (d.get("history") if isinstance(d.get("history"), list) else [])
            if isinstance(m, dict) and m.get("role") in ("user", "assistant")
            and isinstance(m.get("content"), str)]
    n = len(hist)
    chat = []
    for seg in (d.get("chat") if isinstance(d.get("chat"), list) else []):
        if not isinstance(seg, dict):
            continue
        if isinstance(seg.get("t"), str):
            tags = seg.get("tags")
            chat.append({"t": seg["t"], "tags": [x for x in tags if isinstance(x, str)]
                         if isinstance(tags, list) else []})
        elif isinstance(seg.get("img"), str):
            chat.append({"img": seg["img"]})
    scene_raw = d.get("scene") if isinstance(d.get("scene"), dict) else {}
    scene = {k: (v if isinstance(v, dict) else None) for k, v in scene_raw.items()
             if isinstance(k, str)}
    draft_raw = d.get("draft") if isinstance(d.get("draft"), dict) else {}
    return {
        "mode": d.get("mode") if d.get("mode") in _MODES else "dialogue",
        "model": _str(d.get("model")),
        "history": hist,
        "mem_head": _str(d.get("mem_head")),
        "mem_segments": [s for s in (d.get("mem_segments")
                                     if isinstance(d.get("mem_segments"), list) else [])
                         if isinstance(s, str)],
        "digested_upto": _clamp_int(d.get("digested_upto"), 0, n),
        "story_recap": _str(d.get("story_recap")),
        "story_recap_upto": _clamp_int(d.get("story_recap_upto"), 0, n),
        "dyn_new": [s for s in (d.get("dyn_new") if isinstance(d.get("dyn_new"), list) else [])
                    if isinstance(s, str)][-max_dyn_new:],
        "chat": chat,
        "scene": scene,
        "story_characters": [c for c in (d.get("story_characters")
                                         if isinstance(d.get("story_characters"), list) else [])
                             if isinstance(c, dict)],
        "story_size": _str(d.get("story_size")),
        "dialogue_details": _str(d.get("dialogue_details")),
        "story_details": _str(d.get("story_details")),
        "draft": {k: _str(draft_raw.get(k)) for k in ("act", "reply", "story", "chat")},
    }
