"""
Тонкий клиент для локального Ollama API (http://localhost:11434).

Вся сетевая логика собрана здесь и только здесь, чтобы остальной код
(GUI, промпт-билдер) вообще не знал, как устроен протокол Ollama.
Если Ollama обновит API - править нужно будет только этот файл.
"""
import json
import re
import socket
import threading
from typing import Iterator, Optional

import requests

OLLAMA_URL = "http://localhost:11434"


class OllamaError(Exception):
    """Не удалось связаться с Ollama - обычно значит, что она не запущена."""
    pass


class OllamaStallError(OllamaError):
    """Поток ответа начался, но модель замолчала дольше `stall_timeout` секунд
    (типичное «зависла на этапе размышлений»). Отдельный класс, чтобы вызывающий
    отличил зависание от обычной ошибки связи и мог перезапросить."""
    pass


def _arm_read_timeout(resp, seconds) -> bool:
    """Сузить таймаут чтения сокета УЖЕ идущего ответа до `seconds`.
    `requests` задаёт один таймаут на весь запрос (у нас 120 с - нужен, чтобы
    дождаться загрузки модели и обработки длинного промпта до первого токена);
    после того как пошли первые данные, тишина дольше `seconds` = зависание.
    Достаём сокет у urllib3-ответа; не вышло (другая версия/фейковый ответ
    в тестах) -> False, и работает прежний таймаут."""
    try:
        sock = getattr(getattr(resp.raw, "_connection", None), "sock", None)
        if sock is None:
            fp = getattr(getattr(resp.raw, "_fp", None), "fp", None)
            sock = getattr(getattr(fp, "raw", None), "_sock", None)
        if sock is None:
            return False
        sock.settimeout(float(seconds))
        return True
    except Exception:
        return False


def _is_read_timeout(exc) -> bool:
    """Это обрыв по таймауту чтения (а не разрыв связи)? Смотрим цепочку
    исключений: requests оборачивает ReadTimeoutError urllib3 в ConnectionError."""
    seen = set()
    stack = [exc]
    while stack:
        e = stack.pop()
        if e is None or id(e) in seen:
            continue
        seen.add(id(e))
        if isinstance(e, (socket.timeout, TimeoutError,
                          requests.exceptions.ReadTimeout)):
            return True
        if type(e).__name__ == "ReadTimeoutError":
            return True
        stack.append(e.__cause__)
        stack.append(e.__context__)
        stack.extend(a for a in getattr(e, "args", ()) if isinstance(a, BaseException))
    return False


def list_models() -> list:
    """Возвращает список названий моделей, уже скачанных в Ollama (ollama pull ...)."""
    try:
        resp = requests.get(f"{OLLAMA_URL}/api/tags", timeout=5)
        resp.raise_for_status()
        data = resp.json()
        models = data.get("models") if isinstance(data, dict) else None
        return [m["name"] for m in (models if isinstance(models, list) else [])
                if isinstance(m, dict) and isinstance(m.get("name"), str) and m["name"]]
    except (requests.exceptions.RequestException, ValueError) as e:
        try:
            import i18n
            msg = i18n.t("ollama_unreachable")
        except Exception:
            msg = ("Не удалось подключиться к Ollama. Проверь, что она запущена "
                   "(команда 'ollama serve' или иконка в трее).")
        raise OllamaError(msg) from e


def model_capabilities(model: str) -> set:
    """
    Множество возможностей модели по POST /api/show, например
    {"completion", "tools", "thinking", "vision", "insert"}.

    Пустое множество, если не удалось получить (старая Ollama без поля
    `capabilities`, модель недоступна, сеть недоступна) - вызывающий
    трактует это как «не знаем, официального reasoning нет».
    """
    if not model:
        return set()
    try:
        resp = requests.post(f"{OLLAMA_URL}/api/show", json={"model": model}, timeout=4)
        resp.raise_for_status()
        data = resp.json()
    except (requests.exceptions.RequestException, ValueError):
        return set()
    caps = data.get("capabilities") if isinstance(data, dict) else None
    return {c for c in caps if isinstance(c, str)} if isinstance(caps, list) else set()


def parse_stream_line(line) -> Optional[str]:
    """
    Разбирает одну строку потокового ответа Ollama (один JSON-объект на строку)
    и возвращает кусочек текста ответа (message.content), либо None.

    Вынесено отдельной чистой функцией специально, чтобы её можно было
    протестировать без реальной сети (см. test_logic.py).
    """
    return _stream_field(line, "content")


def _stream_json(line):
    """Строка стрима -> dict или None (пусто / не JSON / не объект)."""
    if not line or not isinstance(line, (str, bytes, bytearray)):
        return None
    try:
        data = json.loads(line)
    except ValueError:                 # в т.ч. UnicodeDecodeError и JSONDecodeError
        return None
    return data if isinstance(data, dict) else None


def _stream_field(line, field):
    data = _stream_json(line)
    msg = data.get("message") if data else None
    val = msg.get(field) if isinstance(msg, dict) else None
    return val if isinstance(val, str) and val else None


def parse_stream_error(line) -> Optional[str]:
    """Текст ошибки, если строка стрима - {"error": "..."}. Ollama присылает
    такую строку ПОСРЕДИ уже начавшегося ответа (HTTP 200), когда модель
    упала (нехватка памяти, сбой раннера): без её обработки обрыв выглядел бы
    как нормально законченный ответ."""
    data = _stream_json(line)
    err = data.get("error") if data else None
    return str(err) if err else None


def normalize_messages(messages: list) -> list:
    """
    Схлопывает подряд идущие сообщения одной роли в одно (через "\\n\\n").

    Многие chat-шаблоны (Mistral/Ministral, Gemma и др.) требуют строгого
    чередования user/assistant после system и падают с Jinja-ошибкой на
    двух user подряд. Такое бывает, когда предыдущая генерация ничего не
    вернула (ошибка / «Стоп» до первого токена) и реплика assistant не
    добавилась в историю. Возвращает НОВЫЙ список (вход не мутируется).
    """
    out = []
    for m in messages:
        role = m.get("role", "")
        content = m.get("content", "") or ""
        if out and out[-1]["role"] == role:
            prev = out[-1]["content"]
            sep = "\n\n" if prev and content else ""
            out[-1] = {"role": role, "content": prev + sep + content}
        else:
            out.append({"role": role, "content": content})
    return out


_PARTIAL_FIELD = re.compile(r'"(action|speech)"\s*:\s*"((?:[^"\\]|\\.)*)', re.S)


def _partial_json_fields(text: str):
    """Достать поля action/speech из ОБОРВАННОГО JSON-объекта (стрим упал на
    полуслове, ответ обрезан по num_predict): `{"action": "a", "speech": "Приве`
    -> {"action": "a", "speech": "Приве"}. None - это не похоже на JSON-объект
    или полей не нашлось."""
    t = (text or "").strip()
    if t.startswith("```"):
        t = re.sub(r"^```[a-zA-Z]*\s*", "", t)
    if not t.startswith("{"):
        return None
    found = {}
    for m in _PARTIAL_FIELD.finditer(t):
        raw = m.group(2)
        # оборвано посреди экранирования (`\` или `\u04`) - хвост отбрасываем
        raw = re.sub(r"\\(u[0-9a-fA-F]{0,3})?$", "", raw)
        try:
            val = json.loads('"' + raw + '"')
        except ValueError:
            val = raw.replace('\\"', '"').replace("\\n", "\n")
        found.setdefault(m.group(1), val)
    return found or None


def parse_structured_reply(text: str):
    """
    Разбирает JSON-ответ модели в режиме structured_dialogue -> (action, speech).
    Оборванный JSON (обрыв связи, лимит num_predict) разбирается терпимо: берём
    то, что успело прийти, а не показываем пользователю сырой обрубок.
    Если это вообще не JSON-объект - ("", text.strip()), т.е. весь текст
    трактуется как реплика (мягкий фолбэк, без исключений).
    """
    try:
        data = json.loads(text)
    except (ValueError, TypeError):
        part = _partial_json_fields(text) if isinstance(text, str) else None
        if part:
            return (str(part.get("action") or "").strip(),
                    str(part.get("speech") or "").strip())
        return "", (text or "").strip()
    if not isinstance(data, dict):
        return "", (text or "").strip()
    return (str(data.get("action") or "").strip(),
            str(data.get("speech") or "").strip())


def parse_stream_thinking(line) -> Optional[str]:
    """
    Возвращает кусок «размышлений» reasoning-модели из строки стрима
    (поле message.thinking), либо None. Отдельно от parse_stream_line,
    чтобы content и thinking можно было развести по разным местам UI.
    """
    return _stream_field(line, "thinking")


# Инлайновые теги размышлений, которые многие reasoning-GGUF пишут прямо
# в текст ответа (в message.content), а не в отдельное поле message.thinking.
_THINK_OPEN = ("<think>", "<thinking>")
_THINK_CLOSE = ("</think>", "</thinking>")


class _ThinkSplitter:
    """
    Потоковый фильтр: убирает из message.content инлайновые
    <think>...</think> и отдаёт их текст в on_thinking, а наружу пропускает
    только «видимый» ответ. Теги могут быть разорваны между чанками -
    поэтому держим хвост буфера, который ещё может оказаться началом тега.
    """

    def __init__(self, on_thinking):
        self._on_thinking = on_thinking
        self._buf = ""
        self._in_think = False
        self._maxtag = max(len(t) for t in _THINK_OPEN + _THINK_CLOSE)

    @staticmethod
    def _find_first(low, tags):
        best_i, best_tag = -1, None
        for t in tags:
            i = low.find(t)
            if i != -1 and (best_i == -1 or i < best_i):
                best_i, best_tag = i, t
        return best_i, best_tag

    def _hold_tail(self, low, tags):
        """Сколько символов с конца придержать: возможный префикс тега."""
        for keep in range(min(self._maxtag - 1, len(low)), 0, -1):
            frag = low[-keep:]
            if any(t.startswith(frag) for t in tags):
                return keep
        return 0

    def feed(self, text):
        self._buf += text
        visible = []
        while True:
            low = self._buf.lower()
            if self._in_think:
                idx, tag = self._find_first(low, _THINK_CLOSE)
                if idx == -1:
                    keep = self._hold_tail(low, _THINK_CLOSE)
                    cut = len(self._buf) - keep
                    if cut > 0:
                        self._on_thinking(self._buf[:cut])
                        self._buf = self._buf[cut:]
                    break
                if idx > 0:
                    self._on_thinking(self._buf[:idx])
                self._buf = self._buf[idx + len(tag):]
                self._in_think = False
            else:
                idx, tag = self._find_first(low, _THINK_OPEN)
                if idx == -1:
                    keep = self._hold_tail(low, _THINK_OPEN)
                    cut = len(self._buf) - keep
                    if cut > 0:
                        visible.append(self._buf[:cut])
                        self._buf = self._buf[cut:]
                    break
                if idx > 0:
                    visible.append(self._buf[:idx])
                self._buf = self._buf[idx + len(tag):]
                self._in_think = True
        return visible

    def flush(self):
        rest, self._buf = self._buf, ""
        if self._in_think:
            if rest:
                self._on_thinking(rest)
            return ""
        return rest


def _error_detail(resp) -> str:
    """Достаёт человекочитаемую причину из тела ошибочного ответа Ollama."""
    try:
        body = resp.json()
        if isinstance(body, dict) and body.get("error"):
            return str(body["error"])
    except ValueError:
        pass
    try:
        txt = (resp.text or "").strip()
        return txt[:300] if txt else "нет деталей"
    except Exception:
        return "нет деталей"


def chat_stream(model: str, messages: list, options: "Optional[dict]" = None,
                think: "Optional[bool]" = None, keep_alive: "Optional[str]" = None,
                stop_event: "Optional[threading.Event]" = None,
                on_request=None, on_thinking=None,
                response_format=None, strip_inline_think: bool = True,
                stall_timeout: "Optional[float]" = None) -> Iterator[str]:
    """
    Отправляет диалог в Ollama и построчно отдаёт кусочки ответа по мере
    их генерации (это генератор - используй в цикле `for chunk in ...`).

    messages - список словарей {"role": "system"|"user"|"assistant", "content": "..."}

    options    - dict для payload["options"] (temperature, top_p, top_k,
                 min_p, repeat_penalty, repeat_last_n, num_predict, num_ctx,
                 seed, stop). Пустой/None -> ключ не отправляется.
    think      - None: не отправлять поле; True/False: явно вкл/выкл.
                 Работает только на моделях с capability "thinking"
                 (см. model_capabilities); иначе Ollama вернёт 400,
                 текст причины попадёт в OllamaError.
    keep_alive - строка "5m" / "-1" / "0" или None (не отправлять).
    stop_event - выставленный из другого потока -> генерация прерывается.
    on_request(payload) - вызывается РОВНО с тем словарём, что уходит в
                 requests.post(json=...), перед отправкой (панель Logs).
    on_thinking(text)   - если задан, получает размышления: из поля
                 message.thinking всегда, а из инлайновых <think>...</think>
                 в message.content - только при strip_inline_think=True.
    response_format     - значение payload["format"]: "json" или JSON-схема
                 (structured outputs). None -> не отправлять.
    strip_inline_think  - вырезать ли инлайновые <think>...</think> из
                 текста ответа (в structured-режиме выключаем - там контент
                 это чистый JSON).
    stall_timeout       - секунды тишины, после которых уже начавшийся ответ
                 считается зависшим -> OllamaStallError (None/0 - не следить).
                 Отсчёт включается с ПЕРВЫХ полученных данных, поэтому долгая
                 загрузка модели и обработка длинного промпта до первого
                 токена сюда не входят; пока модель шлёт токены (в том числе
                 размышления), таймер не срабатывает.
    """
    payload = {"model": model, "messages": normalize_messages(messages),
               "stream": True}
    if options:
        payload["options"] = options
    if think is not None:
        payload["think"] = think
    if keep_alive:
        payload["keep_alive"] = keep_alive
    if response_format is not None:
        payload["format"] = response_format
    if on_request is not None:
        on_request(payload)

    try:
        resp = requests.post(f"{OLLAMA_URL}/api/chat", json=payload,
                             stream=True, timeout=120)
    except requests.exceptions.RequestException as e:
        raise OllamaError("Не удалось связаться с Ollama во время генерации ответа.") from e

    try:
        if resp.status_code >= 400:
            # тело читаем ЗДЕСЬ, пока соединение живо
            raise OllamaError(f"Ollama отклонила запрос ({resp.status_code}): "
                              f"{_error_detail(resp)}")

        splitter = (_ThinkSplitter(on_thinking)
                    if (on_thinking is not None and strip_inline_think) else None)
        armed = False
        try:
            for raw_line in resp.iter_lines():
                if not armed and stall_timeout and stall_timeout > 0:
                    armed = _arm_read_timeout(resp, stall_timeout)
                if stop_event is not None and stop_event.is_set():
                    break
                err = parse_stream_error(raw_line)
                if err:
                    raise OllamaError(f"Ollama: {err}")
                if on_thinking is not None:
                    t = parse_stream_thinking(raw_line)
                    if t:
                        on_thinking(t)
                chunk = parse_stream_line(raw_line)
                if not chunk:
                    continue
                if splitter is None:
                    yield chunk
                else:
                    for visible in splitter.feed(chunk):
                        if visible:
                            yield visible
        except requests.exceptions.RequestException as e:
            if armed and _is_read_timeout(e):
                raise OllamaStallError(
                    f"Модель не присылала данные {stall_timeout:g} с "
                    "(зависла посреди ответа).") from e
            raise OllamaError("Обрыв связи с Ollama во время генерации ответа.") from e

        if splitter is not None:
            tail = splitter.flush()
            if tail:
                yield tail
    finally:
        resp.close()
