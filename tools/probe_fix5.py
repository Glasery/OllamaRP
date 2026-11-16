import sys, os, time
SP = os.path.dirname(os.path.abspath(__file__))
src = open(SP + "/probe_group.py", encoding="utf-8").read()
exec(src.split("# ---------- 1) проверка состава ----------")[0])
import group_chat as gc
PLAN.clear(); PLAN["*"] = ["Лайрис"]
# 1) потолок токенов и меньший лимит из Settings
setw("num_predict", "-1"); n0 = hero("Привет", "Ксана"); pump(lambda: idle() and len(REQS) > n0, 400)
check("num_predict=-1 в Settings -> в запросе потолок класса длины (300/450/600)", REQS[n0]["num_predict"] in {np for _c, np in gc.LENGTHS.values()}, REQS[n0]["num_predict"])
check("в конце запроса - указание длины реплики", "Длина этой реплики" in REQS[n0]["user"] and REQS[n0]["user"].rstrip().endswith("отвечай ещё короче."), REQS[n0]["user"][-200:])
setw("num_predict", "200"); n1 = hero("Ещё", "Ксана"); pump(lambda: idle() and len(REQS) > n1, 400)
check("меньший лимит из Settings (200) сохраняется", REQS[n1]["num_predict"] == 200, REQS[n1]["num_predict"])
setw("num_predict", "9999"); n1 = hero("И ещё", "Ксана"); pump(lambda: idle() and len(REQS) > n1, 400)
check("больший лимит (9999) режется до потолка класса (<= 600)", REQS[n1]["num_predict"] in {np for _c, np in gc.LENGTHS.values()}, REQS[n1]["num_predict"])
setw("num_predict", "")
# 2) «стена текста»: бесконечный повтор внутри JSON
app._on_clear_all(); REQS.clear(); RUNAWAY["on"] = True; PLAN["*"] = ["Виктар"]
t0 = time.time(); n2 = hero("Как дела?", "Ксана"); pump(lambda: idle() and len(REQS) > n2, 600)
dt = time.time() - t0
RUNAWAY["on"] = False
rep = [e for e in app.history if e["speaker"] == "Ксана"]
chat = app.chat_box.get("1.0", "end")
check("стрим оборван, реплика сохранена и КОРОТКАЯ (<= лимита)", rep and len(rep[0]["content"]) <= gc.MAX_SPEECH_CHARS + gc.MAX_ACTION_CHARS + 5, [len(e["content"]) for e in rep])
check("повторяющиеся предложения схлопнуты (не 20 раз «сэр»)", rep and rep[0]["content"].count("Всегда Ваша") <= 1, rep[0]["content"][:200] if rep else None)
check("в чате нет стены текста", len(chat) < 1500, len(chat))
check("после обрыва интерфейс свободен, цепочка не зависла", idle() and dt < 20, round(dt, 1))
check("в Logs пометка об обрыве длинного ответа", "reply too long" in app.logs_box.get("1.0", "end"))
# 3) мьют: ответ только герою, без «ко всем»
app._on_clear_all(); REQS.clear(); PLAN.clear(); PLAN["*"] = ["Виктар"]
app._mute_vars["character2"].set(True); app._on_group_mute("character2")
n3 = hero("Привет, Ксана", "Ксана"); pump(lambda: idle() and len(REQS) > n3, 400)
check("при мьюте адресаты ответа: только герой", REQS[n3]["enum"] == ["Виктар"], REQS[n3]["enum"])
check("в чате «Ксана → Виктар», не «→ все»", "Ксана → Виктар" in app.chat_box.get("1.0", "end") and "Ксана → все" not in app.chat_box.get("1.0", "end"))
# 4) положение «Кому»: в углу формы, над колонкой кнопок, в одной строке с подписью
app.update(); pump(lambda: True, 20)
w = app._group_to_wrap; lbl = app._dlg_action_lbl
send = app.send_btn
cy = lambda x: x.winfo_rooty() + x.winfo_height() / 2
check("«Кому» выше кнопки «Отправить», по правому краю формы",
      w.winfo_ismapped() and w.winfo_rooty() + w.winfo_height() <= send.winfo_rooty() + 2
      and abs((app._group_to_menu.winfo_rootx() + app._group_to_menu.winfo_width()) - (send.winfo_rootx() + send.winfo_width())) <= 4,
      (w.winfo_rootx() + w.winfo_width(), send.winfo_rootx() + send.winfo_width(), w.winfo_rooty() + w.winfo_height(), send.winfo_rooty()))
check("левый край списка «Кому» ровно над левым краем кнопок", abs(app._group_to_menu.winfo_rootx() - send.winfo_rootx()) <= 2, (app._group_to_menu.winfo_rootx(), send.winfo_rootx()))
check("по центру строки подписи «Действие героя» (вертикаль)", abs(cy(w) - cy(lbl)) <= 3, (cy(w), cy(lbl)))
check("меню адресата внутри обёртки выровнено по центру", abs(cy(app._group_to_menu) - cy(w)) <= 3, (cy(app._group_to_menu), cy(w)))
from PIL import ImageGrab
app.attributes("-topmost", True); app.lift(); app.focus_force(); pump(lambda: True, 25)
ImageGrab.grab((0, 0, 1560, 880)).save(SP + "/group_to.png")
app.attributes("-topmost", False)
app._on_mode_change("dialogue")
check("в «Диалоге» поле «Кому» скрыто", not w.winfo_ismapped())
print("\nисключений Tk:", len(TK), TK[:2])
print("ИТОГ: багов:", len(BUGS), BUGS)
try: app._on_close()
except Exception: pass
