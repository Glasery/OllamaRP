"""
Окно «Сохранённые диалоги»: имя + «Сохранить как новое» и список сохранений
с кнопками «Загрузить» / «Перезаписать» / «Удалить».

Само окно ничего не знает про состояние приложения - всё делают колбэки
gui.App (см. `App._open_sessions`):
    save_cb(name, session_id_or_None) -> bool   записать текущий диалог
    load_cb(session_id) -> bool                 загрузить; True - окно закрыть
"""
import time
from tkinter import messagebox

import customtkinter as ctk

from i18n import t
from preset_ui import _ModalToplevel, PAD, PAD_SEC, PAD_TIGHT
from sessions import SessionError


def format_saved(iso: str) -> str:
    """'2026-10-02T19:30:05' -> '02.10.2026 19:30' (не разобралось - как есть)."""
    try:
        return time.strftime("%d.%m.%Y %H:%M", time.strptime(iso, "%Y-%m-%dT%H:%M:%S"))
    except (ValueError, TypeError):
        return iso or ""


class SessionsDialog(_ModalToplevel):
    def __init__(self, master, store, default_name, save_cb, load_cb):
        super().__init__(master)
        self._store = store
        self._save_cb = save_cb
        self._load_cb = load_cb
        self.title(t("sess_title"))
        self.geometry("620x560")
        self.minsize(520, 420)

        ctk.CTkLabel(self, text=t("sess_intro"), justify="left", anchor="w",
                     wraplength=580, text_color="gray",
                     font=ctk.CTkFont(size=11)).pack(
            fill="x", padx=PAD_SEC, pady=(PAD_SEC, PAD_TIGHT))

        ctk.CTkLabel(self, text=t("sess_name_label"), anchor="w").pack(
            fill="x", padx=PAD_SEC)
        row = ctk.CTkFrame(self, fg_color="transparent")
        row.pack(fill="x", padx=PAD_SEC, pady=(PAD_TIGHT, PAD))
        self._name = ctk.CTkEntry(row)
        self._name.pack(side="left", fill="x", expand=True)
        self._name.insert(0, default_name)
        ctk.CTkButton(row, text=t("sess_save_new"), width=170,
                      command=self._save_new).pack(side="left", padx=(PAD, 0))

        self._list = ctk.CTkScrollableFrame(self)
        self._list.pack(fill="both", expand=True, padx=PAD_SEC, pady=(0, PAD_SEC))
        self._init_modal(master)
        self.render()

    # ---- список ----
    def render(self):
        for w in self._list.winfo_children():
            w.destroy()
        try:
            metas = self._store.list()
        except SessionError:
            metas = []
        if not metas:
            ctk.CTkLabel(self._list, text=t("sess_empty"), text_color="gray").pack(
                anchor="w", padx=PAD, pady=PAD)
            return
        modes = i18n_mode_labels()
        for m in metas:
            card = ctk.CTkFrame(self._list)
            card.pack(fill="x", pady=(0, PAD_TIGHT))
            ctk.CTkLabel(card, text=m["name"] or "—", anchor="w",
                         font=ctk.CTkFont(weight="bold")).pack(
                fill="x", padx=PAD, pady=(PAD_TIGHT, 0))
            info = t("sess_info", mode=modes.get(m["mode"], m["mode"] or "?"),
                     turns=m["turns"], saved=format_saved(m["saved_at"]))
            if m["model"]:
                info += f" · {m['model']}"
            ctk.CTkLabel(card, text=info, anchor="w", text_color="gray",
                         wraplength=540, justify="left",
                         font=ctk.CTkFont(size=11)).pack(fill="x", padx=PAD)
            btns = ctk.CTkFrame(card, fg_color="transparent")
            btns.pack(fill="x", padx=PAD, pady=(PAD_TIGHT, PAD_TIGHT))
            sid, name = m["id"], m["name"]
            ctk.CTkButton(btns, text=t("sess_load"), width=110,
                          command=lambda s=sid: self._load(s)).pack(side="left")
            ctk.CTkButton(btns, text=t("sess_overwrite"), width=110,
                          fg_color="gray30", hover_color="gray40",
                          command=lambda s=sid, n=name: self._overwrite(s, n)).pack(
                side="left", padx=(PAD_TIGHT, 0))
            ctk.CTkButton(btns, text=t("sess_delete"), width=90,
                          fg_color="#a33333", hover_color="#c44444",
                          command=lambda s=sid, n=name: self._delete(s, n)).pack(
                side="right")

    # ---- действия ----
    def _save_new(self):
        name = self._name.get().strip()
        if not name:
            self._name.focus_set()
            return
        if self._save_cb(name, None):
            self.render()

    def _overwrite(self, sid, name):
        if messagebox.askyesno(t("sess_title"), t("sess_overwrite_q", name=name or "—"),
                               parent=self):
            if self._save_cb(name, sid):
                self.render()

    def _delete(self, sid, name):
        if not messagebox.askyesno(t("sess_title"), t("sess_delete_q", name=name or "—"),
                                   parent=self):
            return
        try:
            self._store.delete(sid)
        except SessionError as e:
            messagebox.showerror(t("sess_title"), t("sess_err", err=e), parent=self)
        self.render()

    def _load(self, sid):
        if self._load_cb(sid):
            self._close()


def i18n_mode_labels() -> dict:
    """Подписи режимов (dialogue/story/chat) на текущем языке."""
    return {"dialogue": t("mode_dialogue"), "story": t("mode_story"),
            "chat": t("mode_chat")}
