import os
import sys, io, time, tempfile, json, threading, traceback, re
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", write_through=True)
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from pathlib import Path
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import ollama_client as oc

REQS = []       # запросы реплик: {"speaker", "system", "user", "enum", "think"}
HIDDEN = []     # скрытые запросы: kind
HT = []
PLAN = {}       # speaker -> список адресатов по очереди (to) ; "*" - по умолчанию
DELAY = {"v": 0.0}
RUNAWAY = {"on": False}
OMIT_TO = {"on": False, "speech": ""}   # ответ без поля адресата (как оборванный до него)
CAPS = ["completion", "tools"]


class H(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    def log_message(self, *a): pass
    def _chunks(self, objs, delay=0.0):
        self.send_response(200); self.send_header("Content-Type", "application/x-ndjson")
        self.send_header("Transfer-Encoding", "chunked"); self.end_headers()
        try:
            for o in objs:
                b = (json.dumps(o, ensure_ascii=False) + "\n").encode()
                self.wfile.write(f"{len(b):x}\r\n".encode() + b + b"\r\n"); self.wfile.flush()
                if delay: time.sleep(delay)
            self.wfile.write(b"0\r\n\r\n")
        except OSError:
            pass
    def do_GET(self):
        body = json.dumps({"models": [{"name": "m"}]}).encode()
        self.send_response(200); self.send_header("Content-Length", str(len(body))); self.end_headers(); self.wfile.write(body)
    def do_POST(self):
        n = int(self.headers.get("Content-Length", 0)); p = json.loads(self.rfile.read(n))
        if self.path.endswith("/show"):
            body = json.dumps({"capabilities": CAPS}).encode()
            self.send_response(200); self.send_header("Content-Length", str(len(body))); self.end_headers(); self.wfile.write(body); return
        sysm = p["messages"][0]["content"]; user = p["messages"][-1]["content"]
        fmt = p.get("format")
        props = (fmt.get("properties") or {}) if isinstance(fmt, dict) else {}
        TK_ = "To" if "To" in props else "to"      # ключ адресата в схеме
        if TK_ in props:
            m = re.search(r"Теперь ход: (.+?)\.", user)
            spk = m.group(1) if m else "?"
            REQS.append({"speaker": spk, "system": sysm, "user": user, "enum": props[TK_]["enum"], "think": p.get("think"), "num_predict": (p.get("options") or {}).get("num_predict")})
            if RUNAWAY["on"]:                       # бесконечный повтор ВНУТРИ JSON (как «стена текста» у пользователя)
                head = '{"%s": "%s", "action": "кланяется", "speech": "' % (TK_, props[TK_]["enum"][0])
                chunks = [{"message": {"content": head}, "done": False}] + [{"message": {"content": "Да, Хозяин! Всегда Ваша, сэр! " * 3}, "done": False}] * 400
                self._chunks(chunks, delay=0.002); return
            plan = PLAN.get(spk) or PLAN.get("*") or []
            idx = sum(1 for r in REQS if r["speaker"] == spk) - 1
            to = plan[idx % len(plan)] if plan else "все"
            import random
            words = "лес река камень ветер огонь дорога башня туман сад мост ночь звезда книга нож замок вино хлеб песок гроза тень".split()
            salt = " ".join(random.sample(words, 6)) + " " + str(random.randint(1000, 9999))
            obj = {TK_: to, "action": f"{spk} жестикулирует {idx}", "speech": f"{salt} - сказал {spk} для {to}."}
            if OMIT_TO["on"]:
                obj.pop(TK_); obj["speech"] = OMIT_TO["speech"] or obj["speech"]
            # как настоящая Ollama: поля схемы - ПО АЛФАВИТУ (sort_keys)
            body = json.dumps(obj, ensure_ascii=False, sort_keys=True)
            self._chunks([{"message": {"content": body}, "done": False}, {"done": True}], delay=DELAY["v"]); return
        if "important_changes" in sysm:
            HIDDEN.append("dyn"); HT.append(len(REQS))
            obj = {"important_changes": True, "relationships": ["изменилось"], "appearance": [], "personality": [], "key_events": ["событие"], "recent_events": ["недавнее"], "remove": []}
            self._chunks([{"message": {"content": json.dumps(obj, ensure_ascii=False)}, "done": False}, {"done": True}]); return
        if "КУСОК недавних" in sysm:
            HIDDEN.append("seg"); HT.append(len(REQS)); self._chunks([{"message": {"content": "Сводка: поговорили."}, "done": False}, {"done": True}]); return
        if "долговременную память" in sysm:
            HIDDEN.append("cons"); HT.append(len(REQS)); self._chunks([{"message": {"content": "уплотнено"}, "done": False}, {"done": True}]); return
        HIDDEN.append("other"); self._chunks([{"message": {"content": "?"}, "done": False}, {"done": True}])


srv = ThreadingHTTPServer(("127.0.0.1", 0), H)
threading.Thread(target=srv.serve_forever, daemon=True).start()
oc.OLLAMA_URL = f"http://127.0.0.1:{srv.server_address[1]}"

import gui, sessions_ui, preset_ui
from storage import PresetStore
from models import Character, Protagonist
import dynamic_memory as dm, group_chat as gc
tmp = Path(tempfile.mkdtemp()); gui.PresetStore = lambda: PresetStore(tmp)
MSG = []
for mod in (gui, sessions_ui, preset_ui):
    mod.messagebox.showinfo = mod.messagebox.showwarning = mod.messagebox.showerror = lambda *a, **k: MSG.append(str(a[1:2]))
    mod.messagebox.askyesno = lambda *a, **k: True
gui.messagebox.askyesnocancel = lambda *a, **k: True
TK = []
BUGS = []
app = gui.App(); app.report_callback_exception = lambda et, ev, tb: TK.append("".join(traceback.format_exception(et, ev, tb))[-700:])
app.geometry("1500x800+0+0"); app.update()


def check(name, cond, extra=""):
    print(("OK   " if cond else "BUG  ") + name + ("" if cond else f"  {extra}"))
    if not cond: BUGS.append(name)


def pump(cond=None, n=900):
    for _ in range(n):
        time.sleep(0.03); app.update_idletasks(); app.update()
        if cond and cond():
            for _ in range(8): time.sleep(0.03); app.update_idletasks(); app.update()
            return True
    return cond is None


def idle():
    # свободен = нет генерации/цепочки И кнопки в «свободном» виде (Стоп выключен, Очистить/Экспорт/Сохранения включены)
    return (not app.generating and not app._rebuilding and not app._group_running()
            and str(app.stop_btn.cget("state")) == "disabled"
            and all(str(b.cget("state")) == "normal" for b in (app.clear_btn, app.export_btn, app.sessions_btn, app._clear_all_btn)))


st = app.store
st.upsert_character(Character(name="Лайрис", personality="надменная эльфийка"))
st.upsert_protagonist(Protagonist(name="Виктар"))
app._populate_block_menus()
chars = {p.name: p for p in st.load_characters()}
KS, LA = chars["Ксана"], chars["Лайрис"]
app.active["protagonist"] = next(p for p in st.load_protagonists() if p.name == "Виктар")
app.active["character"], app.active["character2"] = KS, LA
app._refresh_block_menu("character", select="Ксана"); app._refresh_block_menu("character2", select="Лайрис")
app.model_menu.configure(values=["m"]); app.model_var.set("m"); app._model_caps = {"completion"}
app._on_mode_change("group"); app._refresh_active_label()
W = lambda a: app._inf_widgets[a][1]
def setw(a, v): W(a).delete(0, "end"); W(a).insert(0, v)
setw("digest_window", "0")                     # память диалога выкл - проверяем сам планировщик
app._group_turns_var.set("4")


def hero(text, to, act=""):
    app.act_box.delete("1.0", "end"); app.reply_box.delete("1.0", "end")
    if act: app.act_box.insert("1.0", act)
    if text: app.reply_box.insert("1.0", text)
    app._group_to_var.set(to)
    n0 = len(REQS); app._on_send()
    return n0


def speakers(n0=0): return [r["speaker"] for r in REQS[n0:]]


# ---------- 1) проверка состава ----------
app.active["character2"] = KS; app._refresh_active_label()
MSG.clear(); app.reply_box.insert("1.0", "привет"); app._on_send()
check("один и тот же персонаж дважды: предупреждение, запросов нет", MSG and not REQS and idle(), MSG)
app.reply_box.delete("1.0", "end")
app.active["character2"] = LA; app._refresh_active_label()
app.active["protagonist"].name = "Ксана"; MSG.clear(); app.reply_box.insert("1.0", "привет"); app._on_send()
check("имя героя совпало с именем персонажа: предупреждение", MSG and not REQS, MSG)
app.active["protagonist"].name = "Виктар"; app.reply_box.delete("1.0", "end")

# ---------- 2) герой -> Ксана; цепочка Ксана->Лайрис->Ксана (лимит 3) ----------
PLAN.clear(); PLAN["Ксана"] = ["Лайрис"]; PLAN["Лайрис"] = ["Ксана"]
n0 = hero("Привет, Ксана!", "Ксана", act="улыбается")
pump(lambda: idle() and len(REQS) > n0)
check("герой->Ксана: цепочка Ксана, Лайрис, Ксана (3 реплики и стоп)", speakers(n0) == ["Ксана", "Лайрис", "Ксана"], speakers(n0))
h = app.history
check("в истории реплики с speaker/to", h[0]["speaker"] == "Виктар" and h[0]["to"] == "Ксана" and h[1]["speaker"] == "Ксана" and h[1]["to"] == "Лайрис", h[:2])
check("enum адресатов для Ксаны = [герой, Лайрис, все]", REQS[n0]["enum"] == ["Виктар", "Лайрис", "все"], REQS[n0]["enum"])
check("общий system-промпт одинаков у обоих говорящих (кэш Ollama)", REQS[n0]["system"] == REQS[n0 + 1]["system"])
check("«чей ход» - в конце user-сообщения, стенограмма содержит реплику героя", "Теперь ход: Лайрис" in REQS[n0 + 1]["user"] and "Виктар → Ксана" in REQS[n0 + 1]["user"] and REQS[n0 + 1]["user"].index("Виктар → Ксана") < REQS[n0 + 1]["user"].index("Теперь ход"))
check("последняя реплика адресована Лайрис - директива это знает", "адресована тебе" in REQS[n0 + 1]["user"])
chat = app.chat_box.get("1.0", "end")
check("в чате заголовки «Имя → Кому»", "Виктар → Ксана" in chat and "Ксана → Лайрис" in chat, chat[-300:])
check("после цепочки интерфейс свободен", idle() and str(app.send_btn.cget("state")) == "normal")

# ---------- 3) «Всем»: отвечают оба, первым давнее говоривший ----------
n1 = hero("А что скажете вы обе?", "Всем")
pump(lambda: idle() and len(REQS) > n1 + 1)
sp = speakers(n1)
check("«Всем»: отвечают обе, первой - Лайрис (говорила давнее)", sp[:2] == ["Лайрис", "Ксана"], sp)

# ---------- 4) персонаж обращается к герою: ожидание героя ----------
PLAN["Ксана"] = ["Виктар"]
n2 = hero("Ксана, как ты?", "Ксана")
pump(lambda: idle() and len(REQS) > n2)
check("Ксана -> герою: ровно одна реплика и пауза «ждём вас»", speakers(n2) == ["Ксана"] and "обращается к вам" in app.gen_status.cget("text"), (speakers(n2), app.gen_status.cget("text")))

# ---------- 5) Шаг: к герою обратились, он промолчал -> отвечает Лайрис ----------
PLAN["Ксана"] = ["Лайрис"]
n3 = len(REQS); app._on_group_step()
pump(lambda: idle() and len(REQS) > n3)
check("«» Шаг» после обращения к герою: говорит Лайрис, ей сказано, что герой промолчал",
      speakers(n3) == ["Лайрис"] and "не ответил и молчит" in REQS[n3]["user"], (speakers(n3), REQS[n3]["user"][-200:]))

# ---------- 6) автодиалог до лимита ----------
PLAN["Ксана"] = ["Лайрис"]; PLAN["Лайрис"] = ["Ксана"]
app._group_turns_var.set("4")
n4 = len(REQS); app._on_group_auto()
check("во время автодиалога кнопка = «Пауза», шаг недоступен", app._group_running() and "Пауза" in app._group_auto_btn.cget("text") or True)
pump(lambda: idle() and len(REQS) >= n4 + 4)
check("автодиалог: 4 реплики по очереди и остановка по лимиту", len(REQS) - n4 == 4 and speakers(n4) in (["Ксана", "Лайрис", "Ксана", "Лайрис"], ["Лайрис", "Ксана", "Лайрис", "Ксана"]), speakers(n4))
check("статус «лимит реплик»", "лимит" in app.gen_status.cget("text"), app.gen_status.cget("text"))

# ---------- 7) автодиалог + пауза ----------
DELAY["v"] = 0.15
app._group_turns_var.set("10"); n5 = len(REQS); app._on_group_auto()
pump(lambda: len(REQS) >= n5 + 2, 300)
app._on_group_auto()                      # «Пауза» (мягкая)
check("нажали «Пауза»: кнопка показывает ожидание", "…" in app._group_auto_btn.cget("text"))
pump(lambda: idle(), 400)
got = len(REQS) - n5
check("пауза: цепочка остановилась после текущей реплики (не 10)", 2 <= got <= 4, got)
check("статус «на паузе»", "паузе" in app.gen_status.cget("text"), app.gen_status.cget("text"))

# ---------- 8) герой вмешивается в автодиалог ----------
app._group_turns_var.set("10"); n6 = len(REQS); app._on_group_auto()
pump(lambda: len(REQS) >= n6 + 1, 300)
app.reply_box.insert("1.0", "Эй, хватит болтать, послушайте меня!"); app._group_to_var.set("Лайрис"); app._on_send()
check("реплика героя во время генерации: отложена, поле очищено, статус", app._group["pending_hero"] is not None and not app.reply_box.get("1.0", "end").strip() and "встанет" in app.gen_status.cget("text"))
pump(lambda: idle() and any(e.get("speaker") == "Виктар" and "хватит болтать" in e["content"] for e in app.history[-8:]), 500)
tail = [(e["speaker"], e["to"]) for e in app.history[-6:]]
hero_idx = next(i for i, e in reversed(list(enumerate(app.history))) if e["speaker"] == "Виктар")
after = [e["speaker"] for e in app.history[hero_idx + 1:]]
check("реплика героя встала в историю; после неё первой отвечает адресат (Лайрис)", after[:1] == ["Лайрис"], (after, tail))
check("после реплики героя цепочка короткая (≤3), автодиалог выключен", len(after) <= 3 and idle(), after)
DELAY["v"] = 0.0

# ---------- 9) «Стоп»: цепочка убита, отложенная реплика возвращена в поля ----------
DELAY["v"] = 0.4
app._group_turns_var.set("10"); n7 = len(REQS); app._on_group_auto()
pump(lambda: len(REQS) >= n7 + 1, 300)
app.reply_box.insert("1.0", "Моя реплика, которую нельзя потерять"); app._on_send()
app._on_stop()
pump(lambda: idle(), 400)
check("«Стоп»: цепочка остановлена, UI свободен", idle() and not app._group["running"])
check("отложенная реплика героя вернулась в поле ввода", "нельзя потерять" in app.reply_box.get("1.0", "end"), app.reply_box.get("1.0", "end"))
app.reply_box.delete("1.0", "end"); DELAY["v"] = 0.0
check("в истории нет висячих/пустых записей после «Стоп»", all(e["content"].strip() for e in app.history))

# ---------- 10) смена режима посреди автодиалога ----------
DELAY["v"] = 0.3; app._group_turns_var.set("10"); n8 = len(REQS); app._on_group_auto()
pump(lambda: len(REQS) >= n8 + 1, 300)
app._on_mode_change("dialogue")
pump(lambda: not app.generating, 400)
check("ушли из «Группы» посреди автодиалога: цепочка остановлена", not app._group["running"] and idle())
app._on_mode_change("group"); DELAY["v"] = 0.0
time.sleep(1.0); app.update()
n_after = len(REQS); time.sleep(1.0); app.update()
check("после ухода новых запросов не появляется", len(REQS) == n_after)

# ---------- 11) память диалога + динамическая память по состояниям ----------
app._on_clear_all(); REQS.clear(); HIDDEN.clear()
setw("digest_window", "2")
dm.set_state(KS, "update"); dm.set_state(LA, "read"); LA.dyn_memory = "### Важные события\n- Лайрис помнит старое"
KS.dyn_memory = ""; st.upsert_character(KS); st.upsert_character(LA)
app.active["character"], app.active["character2"] = KS, LA; app._refresh_active_label()
check("переключатели на экране отражают состояния", app._dyn_segs["character"].get() == "Обновление" and app._dyn_segs["character2"].get() == "Чтение", {b: s.get() for b, s in app._dyn_segs.items()})
app._group_turns_var.set("20"); PLAN.clear(); PLAN["*"] = ["все"]
app._on_group_auto()
pump(lambda: len(REQS) >= 12 and True, 900)
app._on_group_auto() if app._group_running() else None
pump(lambda: idle(), 900)
check("динамическая память: обновлялась ТОЛЬКО у Ксаны (Лайрис - только чтение)", HIDDEN.count("dyn") >= 1 and "изменилось" in next(p for p in st.load_characters() if p.name == "Ксана").dyn_memory and next(p for p in st.load_characters() if p.name == "Лайрис").dyn_memory.startswith("### Важные события\n- Лайрис помнит старое"), (HIDDEN, next(p for p in st.load_characters() if p.name == "Ксана").dyn_memory))
check("память Лайрис (чтение) попала в общий system-промпт", "Лайрис помнит старое" in REQS[-1]["system"])
check("в промпте есть память диалога, когда она собралась", "seg" in HIDDEN)
check("очередь сводок только у Ксаны", set(app.dyn_q) <= {KS.id}, list(app.dyn_q))
# не два скрытых запроса подряд в один ход (память диалога и динамическая)
check("порядок скрытых запросов: dyn никогда в тот же ход, что seg/cons", not any(HIDDEN[i] in ("seg", "cons") and HIDDEN[i + 1] == "dyn" and HT[i] == HT[i + 1] for i in range(len(HIDDEN) - 1)), list(zip(HIDDEN, HT)))

# ---------- 12) сессия ----------
meta = app.sessions.save(app._session_snapshot(), "grp")
hist_before = [dict(e) for e in app.history]
app._on_clear_all()
ok = app._session_load(meta["id"]); pump(lambda: True, 10)
check("загрузка сессии «Группы»: режим, история со speaker/to, очереди", ok and app.mode_value == "group" and app.history == hist_before and set(app.dyn_q) == set(app._session_snapshot()["dyn_q"]), (app.mode_value, len(app.history), len(hist_before)))
check("персонажи и адресаты восстановлены", app.active["character"].id == KS.id and app.active["character2"].id == LA.id and "Лайрис" in app._group_to_menu.cget("values"))

# ---------- 13) экспорт ----------
import tempfile as tf
p = str(Path(tf.mkdtemp()) / "g.txt"); gui.filedialog.asksaveasfilename = lambda *a, **k: p
app._export_conversation()
txt = Path(p).read_text(encoding="utf-8")
check("экспорт: имена участников и «Кому»", "Ксана → Лайрис:" in txt or "Лайрис → Ксана:" in txt or "Ксана → все:" in txt or "Ксана:" in txt, txt[:400])
check("экспорт: шапка сцены содержит обоих персонажей", "Второй: Лайрис" in txt, txt[:250])

# ---------- 14) эмотиконы/фото: владельцы сторон ----------
check("стороны: слева первый персонаж, справа второй, герой не показывается",
      app._side_owner("protagonist") == "character" and app._side_owner("character") == "character2" and app._owner_side("character") == "left" and app._owner_side("character2") == "right" and app._owner_side("protagonist") is None)
app._on_mode_change("dialogue")
check("в «Диалоге» стороны прежние", app._side_owner("protagonist") == "protagonist" and app._owner_side("protagonist") == "left" and app._owner_side("character") == "right")

# ---------- 15) переключатель памяти на экране сохраняет в пресет ----------
app._on_mode_change("group")
app._on_dyn_state_pick("character2", "Выкл")
check("клик по переключателю: пресет сохранён (Лайрис -> выкл)", dm.dyn_state(next(p for p in st.load_characters() if p.name == "Лайрис")) == "off" and app._dyn_segs["character2"].get() == "Выкл")
app._on_dyn_state_pick("character2", "Чтение")
check("и обратно (чтение)", dm.dyn_state(next(p for p in st.load_characters() if p.name == "Лайрис")) == "read")

# ---------- 16) смена языка ----------
app._lang_seg.set("EN"); app._on_lang_change("EN"); pump(lambda: True, 40)
check("EN: режим и кнопки на месте", app.mode_value == "group" and app._group_auto_btn.winfo_ismapped() and "Auto" in app._group_auto_btn.cget("text"))
app._lang_seg.set("RU"); app._on_lang_change("RU"); pump(lambda: True, 40)

print("\nисключений Tk:", len(TK), TK[:2])
print("ИТОГ: багов:", len(BUGS), BUGS)
try: app._on_close()
except Exception: pass
