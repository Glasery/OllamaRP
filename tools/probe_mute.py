import sys, os
SP = os.path.dirname(os.path.abspath(__file__))
src = open(SP + "/probe_group.py", encoding="utf-8").read()
head = src.split("# ---------- 1) проверка состава ----------")[0]
exec(head)

# 0) порядок вкладок: Диалог, Группа, История, Чат
tabs = list(app._chat_tabs._tab_dict.keys())
check("порядок вкладок: Диалог, Группа, История, Чат", tabs == ["Диалог", "Группа", "История", "Чат"], tabs)

# 1) стрелки: «→ все» видно, даже когда персонаж обращается ко всем
PLAN.clear(); PLAN["Ксана"] = ["все"]; PLAN["Лайрис"] = ["Виктар"]
app._group_turns_var.set("4")
n0 = hero("Привет всем", "Всем")
pump(lambda: idle() and len(REQS) > n0 + 1, 600)
chat = app.chat_box.get("1.0", "end")
check("в чате у реплики ко «все» есть стрелка «Ксана → все»", "Ксана → все" in chat, chat[-400:])
check("реплика героя ко всем: «Виктар → все»", "Виктар → все" in chat, chat[:300])
check("реплика к герою: «Лайрис → Виктар»", "Лайрис → Виктар" in chat, chat[-300:])
check("в стенограмме для модели адресат тоже виден", "Ксана → все:" in REQS[-1]["user"] or "Виктар → все:" in REQS[-1]["user"], REQS[-1]["user"][:300])
check("в формате ответа просим указывать конкретного адресата", "ВСЕГДА указывай его имя" in REQS[-1]["system"])

# 2) мьют Лайрис
app._on_clear_all(); REQS.clear()
PLAN.clear(); PLAN["Ксана"] = ["Лайрис"]
app._mute_vars["character2"].set(True); app._on_group_mute("character2")
check("мьют включён: адресаты = только Ксана (без «Всем» и Лайрис)", list(app._group_to_menu.cget("values")) == ["Ксана"], app._group_to_menu.cget("values"))
check("кнопки ▶ Авто и » Шаг нажимаются (не серые) - клик даёт алерт", str(app._group_auto_btn.cget("state")) == "normal" and str(app._group_step_btn.cget("state")) == "normal")
check("статус объясняет мьют", "заглушён" in app.gen_status.cget("text"), app.gen_status.cget("text"))
check("в строке сцены у Лайрис значок мьюта", "Лайрис 🔇" in app.active_label.cget("text"), app.active_label.cget("text"))
n1 = len(REQS); MSG.clear(); app._on_group_auto(); pump(lambda: True, 10)
check("«▶ Авто» при мьюте: алерт про мьют, запросов нет", len(REQS) == n1 and idle() and len(MSG) == 1 and "заглушён" in MSG[0] and "автодиалог" in MSG[0] and "Ксана" in MSG[0] and "Лайрис" in MSG[0], MSG)
MSG.clear(); app._on_group_step(); pump(lambda: True, 10)
check("«» Шаг» при мьюте: тот же алерт, запросов нет", len(REQS) == n1 and idle() and len(MSG) == 1 and "заглушён" in MSG[0], MSG)

n2 = hero("Привет!", "Всем")                 # «Всем» при мьюте = только Ксана
pump(lambda: idle() and len(REQS) > n2, 400)
check("при мьюте отвечает только Ксана (одна реплика, цепочки нет)", speakers(n2) == ["Ксана"], speakers(n2))
check("при мьюте адресат ТОЛЬКО герой: ни «все», ни Лайрис в списке нет", REQS[n2]["enum"] == ["Виктар"], REQS[n2]["enum"])
check("в промпте сказано, что других персонажей в сцене нет", "обращайся только к герою" in REQS[n2]["system"])
import group_chat as gc
check("в запросе реплики задан потолок токенов (по классу длины)", REQS[n2]["num_predict"] in {np for _c, np in gc.LENGTHS.values()}, REQS[n2]["num_predict"])
check("в промпте нет карточки заглушённой Лайрис", "надменная эльфийка" not in REQS[n2]["system"] and "Ксана" in REQS[n2]["system"])
check("Ксана обратилась к заглушённой Лайрис (to=Лайрис не прошло): цепочка закончилась, интерфейс свободен", idle() and not app._group["running"])
check("в истории только герой и Ксана", [e["speaker"] for e in app.history] == ["Виктар", "Ксана"], [e["speaker"] for e in app.history])

PLAN["Ксана"] = ["Виктар"]
n3 = hero("Как дела, Ксана?", "Ксана")
pump(lambda: idle() and len(REQS) > n3, 400)
check("Ксана обратилась к герою при мьюте: ожидание героя", speakers(n3) == ["Ксана"] and "обращается к вам" in app.gen_status.cget("text"), app.gen_status.cget("text"))

# 3) динамическая память заглушённой не копится
dm.set_state(KS, "update"); dm.set_state(LA, "update"); st.upsert_character(KS); st.upsert_character(LA)
app.active["character"], app.active["character2"] = KS, LA
setw("digest_window", "2"); PLAN["Ксана"] = ["Виктар"]
for i in range(6):
    hero(f"Реплика героя {i}", "Ксана"); pump(lambda: idle(), 400)
check("сводки копятся только у Ксаны, у заглушённой Лайрис - нет", KS.id in app.dyn_q and LA.id not in app.dyn_q, list(app.dyn_q))

# 4) оба заглушить нельзя
MSG.clear(); app._mute_vars["character"].set(True); app._on_group_mute("character")
check("заглушить обоих нельзя: предупреждение, переключатель вернулся", MSG and not app._mute_vars["character"].get() and not app._group_muted["character"], MSG)

# 5) сессия хранит мьют
meta = app.sessions.save(app._session_snapshot(), "mute")
app._mute_vars["character2"].set(False); app._on_group_mute("character2")
MSG.clear()
check("размьют: «Всем» и Лайрис снова в списке", list(app._group_to_menu.cget("values")) == ["Ксана", "Лайрис", "Всем"], app._group_to_menu.cget("values"))
ok = app._session_load(meta["id"])
check("загрузка сессии вернула мьют Лайрис", ok and app._group_muted == {"character": False, "character2": True} and app._mute_vars["character2"].get() and list(app._group_to_menu.cget("values")) == ["Ксана"], (app._group_muted, app._group_to_menu.cget("values")))

# 6) размьют и автодиалог идёт
app._mute_vars["character2"].set(False); app._on_group_mute("character2")
PLAN.clear(); PLAN["Ксана"] = ["Лайрис"]; PLAN["Лайрис"] = ["Ксана"]
app._group_turns_var.set("4"); n4 = len(REQS); app._on_group_auto()
pump(lambda: idle() and len(REQS) >= n4 + 4, 600)
check("после размьюта автодиалог снова идёт (обе говорят)", set(speakers(n4)) == {"Ксана", "Лайрис"} and len(REQS) - n4 == 4, speakers(n4))

# 7) мьют посреди автодиалога - цепочка встаёт после текущей
DELAY["v"] = 0.2; app._group_turns_var.set("10"); n5 = len(REQS); app._on_group_auto()
pump(lambda: len(REQS) >= n5 + 1, 300)
app._mute_vars["character2"].set(True); app._on_group_mute("character2")
pump(lambda: idle(), 400)
check("мьют во время автодиалога: цепочка остановлена после текущей реплики", idle() and len(REQS) - n5 <= 3, len(REQS) - n5)
DELAY["v"] = 0.0

# 8) язык
app._lang_seg.set("EN"); app._on_lang_change("EN"); pump(lambda: True, 40)
check("EN: переключатель мьюта и значок на месте", app._mute_rows["character2"].winfo_ismapped() and "🔇" in app.active_label.cget("text"), app.active_label.cget("text"))
app._lang_seg.set("RU"); app._on_lang_change("RU"); pump(lambda: True, 40)
app._on_mode_change("dialogue")
check("в «Диалоге» переключатели мьюта скрыты", not app._mute_rows["character"].winfo_ismapped() and not app._mute_rows["character2"].winfo_ismapped())

print("\nисключений Tk:", len(TK), TK[:2])
print("ИТОГ: багов:", len(BUGS), BUGS)
try: app._on_close()
except Exception: pass
