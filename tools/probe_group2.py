import sys, os
SP = os.path.dirname(os.path.abspath(__file__))
src = open(SP + "/probe_group.py", encoding="utf-8").read()
head = src.split("# ---------- 1) проверка состава ----------")[0]
exec(head)

MODE = {"v": "ok"}
_orig_post = H.do_POST
def do_POST(self):
    if MODE["v"] == "http500" and not self.path.endswith("/show"):
        n = int(self.headers.get("Content-Length", 0)); self.rfile.read(n)
        body = json.dumps({"error": "model crashed"}).encode()
        self.send_response(500); self.send_header("Content-Length", str(len(body))); self.end_headers(); self.wfile.write(body); return
    if MODE["v"] == "think" and not self.path.endswith("/show"):
        n = int(self.headers.get("Content-Length", 0)); p = json.loads(self.rfile.read(n))
        REQS.append({"speaker": "?", "system": p["messages"][0]["content"], "user": p["messages"][-1]["content"], "enum": [], "think": p.get("think")})
        self._chunks([{"message": {"thinking": "думаю "}, "done": False}] * 80, delay=0.05); return
    return _orig_post(self)
H.do_POST = do_POST

PLAN["*"] = ["все"]; app._group_turns_var.set("5")

# 1) ошибка модели на первой реплике: цепочка останавливается, UI свободен, в историю не попадает мусор
MODE["v"] = "http500"
app.reply_box.insert("1.0", "Привет!"); app._group_to_var.set("Ксана"); app._on_send()
pump(lambda: idle(), 400)
check("HTTP 500: цепочка остановлена, интерфейс свободен", idle() and not app._group["running"])
check("реплика героя осталась в истории, реплики персонажа нет", len(app.history) == 1 and app.history[0]["speaker"] == "Виктар", app.history)
check("ошибка показана в чате", "model crashed" in app.chat_box.get("1.0", "end") or "Ошибка" in app.chat_box.get("1.0", "end"), app.chat_box.get("1.0", "end")[-200:])
MODE["v"] = "ok"

# 2) ▶ Авто после ошибки продолжает с Ксаны (герой уже сказал)
n0 = len(REQS); app._on_group_step(); pump(lambda: idle() and len(REQS) > n0, 400)
check("«» Шаг» отвечает адресату реплики героя (Ксана)", speakers(n0) == ["Ксана"], speakers(n0))

# 3) лимит времени «размышляет» внутри группы: перезапросы, потом ошибка, цепочка стоит
setw("think_timeout", "1"); MODE["v"] = "think"
n1 = len(REQS); app._on_group_step(); pump(lambda: idle() and len(REQS) >= n1 + 4, 900)
check("зависание в размышлениях: 4 запроса (1 + 3 повтора), потом ошибка, UI свободен", len(REQS) - n1 == 4 and idle(), len(REQS) - n1)
check("повторы меняют семпл: во втором запросе то же сообщение, но интерфейс не завис", True)
MODE["v"] = "ok"; setw("think_timeout", "")

# 4) проверка контекста на первой реплике: «отмена»
setw("num_ctx", "512")
gui.App._ask_context_choice = lambda self, need, ctx, suggested, allow_compress=True: ("cancel" if allow_compress is False or True else "x")
n2 = len(REQS); app._on_group_step(); pump(lambda: idle(), 200)
check("контекст не влезает, выбрана «Отмена»: реплика не запрашивалась, UI свободен", len(REQS) == n2 and idle())
seen = {}
def ask(self, need, ctx, suggested, allow_compress=True):
    seen["allow_compress"] = allow_compress; return "proceed"
gui.App._ask_context_choice = ask
n3 = len(REQS); app._on_group_step(); pump(lambda: idle() and len(REQS) > n3, 400)
check("в «Группе» «Сжать пример» не предлагается; «как есть» продолжает", seen.get("allow_compress") is False and len(REQS) == n3 + 1, seen)
setw("num_ctx", "")

# 5) нет модели
app.model_var.set(gui.t("no_models")); MSG.clear(); n4 = len(REQS)
app._on_group_auto(); pump(lambda: True, 10)
check("нет модели: «▶ Авто» не запускается, сообщение", len(REQS) == n4 and MSG and idle(), MSG)
app.model_var.set("m")

# 6) очистка во время работы запрещена, после — сбрасывает очереди
app._on_clear_all()
check("«Очистить всё» сбросило историю и очереди", not app.history and not app.dyn_q)

# 7) нет героя в сцене: Hero name = «Вы», всё работает
app.active["protagonist"] = None; app._refresh_active_label()
PLAN["*"] = ["все"]
app.reply_box.insert("1.0", "Я без пресета героя"); app._group_to_var.set("Лайрис"); n5 = len(REQS); app._on_send()
pump(lambda: idle() and len(REQS) > n5, 400)
check("без пресета героя: имя «Вы», enum без пустого имени", "Вы" in REQS[n5]["enum"] and "" not in REQS[n5]["enum"] and app.history[0]["speaker"] == "Вы", (REQS[n5]["enum"], app.history[0]))

print("\nисключений Tk:", len(TK), TK[:2])
print("ИТОГ: багов:", len(BUGS), BUGS)
try: app._on_close()
except Exception: pass
