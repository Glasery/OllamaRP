import sys, os, time
SP = os.path.dirname(os.path.abspath(__file__))
src = open(SP + "/probe_group.py", encoding="utf-8").read()
exec(src.split("# ---------- 1) проверка состава ----------")[0])
import group_chat as gc
from prompt_builder import estimate_tokens

NPS = {np for _c, np in gc.LENGTHS.values()}

# 1) случайная длина - у ОБОИХ персонажей; в Logs видно класс длины
PLAN.clear(); PLAN["*"] = ["все"]
app._group_turns_var.set("24")
n0 = len(REQS); app._on_group_auto()
pump(lambda: idle() and len(REQS) >= n0 + 24, 1500)
per = {}
for r in REQS[n0:]:
    per.setdefault(r["speaker"], []).append(r["num_predict"])
check("автодиалог: 24 реплики, говорят оба", len(REQS) - n0 == 24 and set(per) == {"Ксана", "Лайрис"}, {k: len(v) for k, v in per.items()})
check("у Ксаны длина меняется от хода к ходу", len(set(per.get("Ксана", []))) >= 2, per.get("Ксана"))
check("у Лайрис длина меняется от хода к ходу", len(set(per.get("Лайрис", []))) >= 2, per.get("Лайрис"))
check("все num_predict - из классов длины", all(v in NPS for vs in per.values() for v in vs), per)
check("каждый ход - указание длины в конце запроса", all("Длина этой реплики" in r["user"] for r in REQS[n0:]))
logs = app.logs_box.get("1.0", "end")
check("в Logs строка «GROUP: Лайрис - length ...»", "GROUP: Лайрис - length" in logs and "GROUP: Ксана - length" in logs)
check("ключ адресата в схеме - «To» (идёт первым у Ollama)", "\"To\"" in logs)

# 2) адресат не пришёл (ответ оборван до поля): по обращению в тексте
app._on_clear_all(); REQS.clear(); PLAN.clear(); PLAN["*"] = ["Виктар"]
OMIT_TO["on"] = True; OMIT_TO["speech"] = "Лайрис, ты слышала? Хозяин здесь."
app._group_turns_var.set("2")
n1 = hero("Ксана, скажи что-нибудь", "Ксана"); pump(lambda: idle() and len(REQS) > n1 + 1, 600)
h = [e for e in app.history if e.get("speaker") == "Ксана"]
check("нет поля адресата, в речи «Лайрис, ...» -> адресат Лайрис", h and h[0]["to"] == "Лайрис", [(e["speaker"], e["to"]) for e in app.history])
check("и отвечает Лайрис (цепочка пошла дальше)", speakers(n1)[:2] == ["Ксана", "Лайрис"], speakers(n1))
check("в Logs пометка «addressee taken from the text»", "addressee taken from the text" in app.logs_box.get("1.0", "end"))
# без обращения - тому, кто говорил последним (герою)
app._on_clear_all(); REQS.clear()
OMIT_TO["speech"] = "Как скажете. Я готова."
n2 = hero("Ксана, ты готова?", "Ксана"); pump(lambda: idle() and len(REQS) > n2, 600)
h = [e for e in app.history if e.get("speaker") == "Ксана"]
check("нет поля адресата, нет обращения -> адресат = последний говоривший (герой)", h and h[0]["to"] == "Виктар", [(e["speaker"], e["to"]) for e in app.history])
check("в чате «Ксана → Виктар», не «→ все»", "Ксана → Виктар" in app.chat_box.get("1.0", "end"))
OMIT_TO["on"] = False; OMIT_TO["speech"] = ""

# 3) мьют: «все» в ответе невозможно - адресат всегда герой
app._on_clear_all(); REQS.clear(); PLAN.clear(); PLAN["*"] = ["все"]   # модель «нарушила» enum
app._mute_vars["character2"].set(True); app._on_group_mute("character2")
n3 = hero("Привет", "Ксана"); pump(lambda: idle() and len(REQS) > n3, 600)
h = [e for e in app.history if e.get("speaker") == "Ксана"]
check("при мьюте ответ «все» -> адресат герой", h and h[0]["to"] == "Виктар", [(e["speaker"], e["to"]) for e in app.history])
check("в чате нет «Ксана → все»", "Ксана → все" not in app.chat_box.get("1.0", "end"))
app._mute_vars["character2"].set(False); app._on_group_mute("character2")

# 4) окно «мало контекста»: запас = реальный num_predict, без «поднять до текущего»
ASK = []
app._ask_context_choice = lambda need, ctx, sug, allow_compress=True: (ASK.append((need, ctx, sug)), "proceed")[1]
setw("num_ctx", "16384"); setw("num_predict", "")
inf = app._collect_inference_config()
def msgs(tokens):
    return [{"role": "user", "content": "я" * int((tokens - 12) * 2.5)}]
m = msgs(15000)                          # 15000 + 300 <= 0.95*16384, а с запасом 2048 - нет
r = app._preflight_context(m, inf, {"num_predict": 300}, allow_compress=False)
check("запрос 15000 ток. + ответ 300 при num_ctx 16384: окна нет", r is None and not ASK, (r, ASK))
app._ctx_proceed = None
m = msgs(15800)
r = app._preflight_context(m, inf, {"num_predict": 300}, allow_compress=False)
check("у границы 16384: предлагается 32768, а не 16384", ASK and ASK[-1][2] == 32768, ASK)
r2 = app._preflight_context(m, inf, {"num_predict": 300}, allow_compress=False)
check("выбрали «как есть» - на следующей реплике окно не повторяется", len(ASK) == 1 and r2 is None, ASK)
r3 = app._preflight_context(msgs(15800 * 1.2), inf, {"num_predict": 300}, allow_compress=False)
check("запрос вырос на 20% - окно снова", len(ASK) == 2, ASK)
app._ctx_proceed = None; setw("num_ctx", "")

# 5) ползунок «Средняя длина реплики»
sec = app.group_params_section
check("ползунок виден в «Группе» на панели «Сцена»", app._group_len_slider.winfo_ismapped() and sec.winfo_ismapped())
check("по умолчанию 340, подпись «~340 симв.»", app._group_len_var.get() == 340 and app._group_len_val_lbl.cget("text") == "~340 симв.", (app._group_len_var.get(), app._group_len_val_lbl.cget("text")))
app._group_len_slider.set(903); app._on_group_len()             # как при перетаскивании
check("значение округляется до шага 10 и в пределах (900)", app._group_len_var.get() == 900 and app._group_len_val_lbl.cget("text") == "~900 симв.", app._group_len_var.get())
pump(lambda: app.store.load_settings().group_reply_len == 900, 120)
check("через ~1 с значение сохранено в settings.json", app.store.load_settings().group_reply_len == 900, app.store.load_settings().group_reply_len)
app._on_clear_all(); REQS.clear(); PLAN.clear(); PLAN["*"] = ["Виктар"]
n5 = hero("Расскажи что-нибудь", "Ксана"); pump(lambda: idle() and len(REQS) > n5, 600)
big = {gc.length_limits(k, 900)[1] for k in gc.LENGTHS}
check("следующая реплика - с лимитами для 900 (num_predict из большой таблицы)", REQS[n5]["num_predict"] in big, (REQS[n5]["num_predict"], big))
check("в задании хода больше предложений", any(f"не больше {n} предложений" in REQS[n5]["user"] for n in (6, 11, 15)), REQS[n5]["user"][-260:])
app._group_len_slider.set(150); app._on_group_len()
n6 = hero("Ещё", "Ксана"); pump(lambda: idle() and len(REQS) > n6, 600)
small = {gc.length_limits(k, 150)[1] for k in gc.LENGTHS}
check("150: лимиты маленькой таблицы", REQS[n6]["num_predict"] in small, (REQS[n6]["num_predict"], small))
app._group_len_slider.set(620); app._on_group_len()
app._on_lang_change("EN"); pump(lambda: True, 30)
check("смена языка: значение ползунка сохранилось (620), подпись по-английски", app._group_len_var.get() == 620 and app._group_len_val_lbl.cget("text") == "~620 chars", (app._group_len_var.get(), app._group_len_val_lbl.cget("text")))
app._on_lang_change("RU"); pump(lambda: True, 30)
from PIL import ImageGrab
app._preset_panel._parent_canvas.yview_moveto(1.0)
app.attributes("-topmost", True); app.lift(); app.focus_force(); pump(lambda: True, 25)
ImageGrab.grab((0, 0, 1560, 880)).save(SP + "/group_len.png")
app.attributes("-topmost", False)
app._group_len_slider.set(340); app._on_group_len(save=False)

print("\nисключений Tk:", len(TK), TK[:2])
print("ИТОГ: багов:", len(BUGS), BUGS)
try: app._on_close()
except Exception: pass
