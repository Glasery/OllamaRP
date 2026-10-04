"""
Окна управления пресетами.

- PresetEditDialog - форма создания/редактирования одного пресета.
- PresetManager   - список пресетов одного типа с кнопками
                    Создать / Редактировать / Удалить.

Оба - модальные CTkToplevel. grab_set откладывается через after(), т.к.
только что созданное окно ещё не "viewable" и немедленный grab бросает
исключение. Все конкретные различия между типами блоков берутся из
blocks.BLOCK_SPECS, здесь только общий каркас UI.
"""
import json
import queue
import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox

import customtkinter as ctk

import i18n
import photos
from i18n import t
from blocks import BLOCK_SPECS
from ollama_client import chat_stream, OllamaError
from prompt_builder import build_field_generation_messages

TEXTBOX_HEIGHT = 150
PHOTO_PREVIEW = 96          # сторона круглого превью фото в форме пресета, px
# Радиус скругления заглушки «нет фото»: CTkLabel добавляет к ширине текста
# отступ по радиусу, и при радиусе в пол-превью заглушка растягивалась в
# широкую «таблетку»; небольшой радиус держит её квадратом PHOTO_PREVIEW.
PHOTO_PLACEHOLDER_RADIUS = 10
MEDIA_BTN_W = 190           # ширина кнопки добавления/выбора - ОДНА у аватара, галереи и эмотиконов

# Та же шкала отступов, что и в gui.py (дублируется, чтобы не заводить
# зависимость gui <- preset_ui). PAD_TIGHT - плотно, PAD - базовый,
# PAD_SEC - между смысловыми группами / поля модалок.
PAD_TIGHT = 4
PAD = 8
PAD_SEC = 16


class _ModalToplevel(ctk.CTkToplevel):
    """Общая логика: transient + отложенный grab + аккуратное закрытие."""

    def _init_modal(self, master):
        self.transient(master)
        self.protocol("WM_DELETE_WINDOW", self._close)
        self.after(90, self._grab)

    def _grab(self):
        try:
            self.grab_set()
        except tk.TclError:
            pass
        self.lift()
        self.focus_force()

    def _close(self):
        try:
            self.grab_release()
        except tk.TclError:
            pass
        self.destroy()


class TextEditDialog(_ModalToplevel):
    """Простое модальное окно правки одного многострочного текста.
    После закрытия: result = строка (в т.ч. пустая) или None (отмена).
    Кнопка «Сбросить к стандартному» ставит default_text."""

    def __init__(self, master, title, text, default_text="", help_text=""):
        super().__init__(master)
        self.result = None
        self._default = default_text
        self.title(title)
        self.geometry("640x480")

        if help_text:
            ctk.CTkLabel(self, text=help_text, justify="left", wraplength=600,
                         text_color="gray", font=ctk.CTkFont(size=11)).pack(
                anchor="w", padx=PAD_SEC, pady=(PAD_SEC, PAD_TIGHT))

        self._box = ctk.CTkTextbox(self, wrap="word")
        self._box.pack(fill="both", expand=True, padx=PAD_SEC, pady=(PAD_TIGHT, PAD))
        self._box.insert("1.0", text or "")

        bar = ctk.CTkFrame(self, fg_color="transparent")
        bar.pack(fill="x", padx=PAD_SEC, pady=(0, PAD_SEC))
        ctk.CTkButton(bar, text=t("save"), command=self._save).pack(side="right")
        ctk.CTkButton(bar, text=t("cancel"), fg_color="gray30", hover_color="gray40",
                      command=self._close).pack(side="right", padx=(0, PAD_TIGHT))
        if default_text:
            ctk.CTkButton(bar, text=t("reset_default"), fg_color="gray30",
                          hover_color="gray40", command=self._reset).pack(side="left")

        self._init_modal(master)

    def _reset(self):
        self._box.delete("1.0", "end")
        self._box.insert("1.0", self._default)

    def _save(self):
        self.result = self._box.get("1.0", "end").strip()
        self._close()


class _PhotoListSection:
    """Список фото в форме пресета (галерея / эмотиконы): заголовок, подсказка,
    кнопка добавления (можно выбрать сразу несколько файлов) и ряд превью с
    кнопкой «убрать» под каждым. Хранит ТОЛЬКО имена файлов (`self.names`);
    сами файлы импортирует `add_cb(path) -> имя` (бросает PhotoError)."""
    THUMB = 64            # максимальная сторона превью, px
    PER_ROW = 6

    def __init__(self, dlg, parent, title, hint, add_text, names, add_cb, png_only=False):
        self.dlg = dlg
        self.names = list(names or [])
        self._add_cb = add_cb
        self._png_only = png_only
        self._imgs = []                       # держим CTkImage, пока превью на экране
        box = ctk.CTkFrame(parent, fg_color="transparent")
        box.pack(fill="x", pady=(PAD, PAD))
        head = ctk.CTkFrame(box, fg_color="transparent")
        head.pack(fill="x")
        ctk.CTkLabel(head, text=title, anchor="w", justify="left",
                     wraplength=330).pack(side="left", anchor="w")
        ctk.CTkButton(head, text=add_text, width=MEDIA_BTN_W, command=self._add).pack(
            side="right", anchor="n")
        if hint:
            ctk.CTkLabel(box, text=hint, anchor="w", justify="left", wraplength=470,
                         text_color="gray", font=ctk.CTkFont(size=11)).pack(
                fill="x", pady=(PAD_TIGHT, 0))
        self._grid = ctk.CTkFrame(box, fg_color="transparent")
        self._grid.pack(fill="x", pady=(PAD_TIGHT, 0))
        self.render()

    def render(self):
        for w in self._grid.winfo_children():
            w.destroy()
        self._imgs = []
        store = self.dlg._store
        if not self.names:
            ctk.CTkLabel(self._grid, text=t("list_empty"), text_color="gray").grid(
                row=0, column=0, sticky="w")
            return
        for i, name in enumerate(self.names):
            cell = ctk.CTkFrame(self._grid, fg_color="transparent")
            cell.grid(row=i // self.PER_ROW, column=i % self.PER_ROW,
                      padx=PAD_TIGHT, pady=PAD_TIGHT, sticky="n")
            path = store.photo_path(name)
            pil = photos.load_rgba(path) if path else None
            if pil is not None:
                k = self.THUMB / max(pil.width, pil.height)
                size = (max(1, int(pil.width * k)), max(1, int(pil.height * k)))
                img = ctk.CTkImage(light_image=pil, dark_image=pil, size=size)
                self._imgs.append(img)
                lbl = ctk.CTkLabel(cell, text="", image=img, width=self.THUMB,
                                   height=self.THUMB)
            else:                              # файл пропал
                lbl = ctk.CTkLabel(cell, text="?", width=self.THUMB, height=self.THUMB,
                                   fg_color=("gray85", "gray20"), corner_radius=6)
            lbl.pack()
            ctk.CTkButton(cell, text="×", width=self.THUMB, height=20,
                          fg_color="gray30", hover_color="#a33333",
                          command=lambda n=name: self.remove(n)).pack(pady=(2, 0))

    def remove(self, name):
        if name in self.names:
            self.names.remove(name)
        self.render()

    def _add(self):
        if not photos.AVAILABLE:
            messagebox.showinfo(t("photo_err_title"), t("photo_need_pillow"),
                                parent=self.dlg)
            return
        exts = "*.png" if self._png_only else " ".join(f"*.{e}" for e in photos.EXTENSIONS)
        paths = filedialog.askopenfilenames(
            parent=self.dlg, title=t("photo_dlg_title"),
            filetypes=[(t("ft_images"), exts)] + ([] if self._png_only else [("*", "*.*")]))
        if not paths:
            return
        errors = []
        for path in paths:
            try:
                self.names.append(self._add_cb(path))
            except photos.EmoteError as e:     # не PNG / нет прозрачности - алерт
                errors.append(t(f"emote_err_{e.code}", name=Path(path).name))
            except photos.PhotoError as e:
                errors.append(t("emote_err_other", name=Path(path).name, err=e))
        self.render()
        if errors:
            title = t("emote_err_title") if self._png_only else t("photo_err_title")
            messagebox.showwarning(
                title, "\n".join(errors) + (t("emote_err_footer")
                                            if len(errors) < len(paths) else ""),
                parent=self.dlg)


class PresetEditDialog(_ModalToplevel):
    """Форма одного пресета. После закрытия result = объект или None."""

    def __init__(self, master, block, obj=None, gen_context=None, store=None):
        super().__init__(master)
        self.spec = BLOCK_SPECS[block]
        self._store = store                   # нужен для импорта фото
        self.block = block
        self.result = None
        self._base = obj                      # None => создаём новый

        # Контекст кнопки «Сгенерировать»: callable -> dict (модель, опции
        # семплинга, приёмник лога) либо None (кнопок не будет). Вызывается
        # в момент нажатия, чтобы модель/настройки были актуальными.
        self._gen_context = gen_context
        self._field_labels = i18n.field_labels(block)
        self._gen_btns = {}                   # attr -> кнопка «Сгенерировать»
        self._gen_q = queue.Queue()          # (attr, text|None, err|None) из потока
        self._gen_active = None              # attr, который сейчас генерится

        verb = t("editing") if obj is not None else t("new_preset")
        self.title(t("preset_win_title", verb=verb, title=i18n.block_title(block)))
        self.geometry("560x700")

        frame = ctk.CTkScrollableFrame(self)
        frame.pack(fill="both", expand=True, padx=PAD_SEC, pady=PAD_SEC)

        # Необязательное фото (персонаж / главный герой) - блок сверху формы.
        self._photo_name = getattr(obj, "photo", "") if obj is not None else ""
        self._photo_ctk = None                # держим ссылку, иначе превью пропадёт
        self._gallery = self._emotes = None
        if self.spec.get("photo") and store is not None:
            self._build_photo_row(frame)                       # АВАТАР (одно фото)
            self._gallery = _PhotoListSection(                 # ГАЛЕРЕЯ (несколько)
                self, frame, t("gallery_label"), "", t("gallery_add"),
                getattr(obj, "gallery", []) if obj is not None else [],
                add_cb=store.import_photo)
            self._emotes = _PhotoListSection(                  # ЭМОТИКОНЫ (PNG-силуэты)
                self, frame, t("emotes_label"), t("emotes_hint"), t("emotes_add"),
                getattr(obj, "emotes", []) if obj is not None else [],
                add_cb=store.import_emote, png_only=True)

        self._widgets = {}                    # attr -> (widget, wtype)
        for attr, _label, wtype in self.spec["fields"]:
            head = ctk.CTkFrame(frame, fg_color="transparent")
            head.pack(fill="x", pady=(PAD, PAD_TIGHT))
            ctk.CTkLabel(head, text=self._field_labels.get(attr, attr),
                         anchor="w").pack(side="left")
            # «Сгенерировать» - у всех полей, кроме имени/названия пресета
            # (имя пользователь всегда задаёт вручную).
            if gen_context is not None and attr != "name":
                b = ctk.CTkButton(head, text=t("generate"), width=118, height=24,
                                  command=lambda a=attr: self._generate_field(a))
                b.pack(side="right")
                self._gen_btns[attr] = b
            current = getattr(obj, attr, "") if obj is not None else ""
            if wtype == "textbox":
                widget = ctk.CTkTextbox(frame, height=TEXTBOX_HEIGHT, wrap="word")
                if current:
                    widget.insert("1.0", current)
            else:
                widget = ctk.CTkEntry(frame)
                if current:
                    widget.insert(0, current)
            widget.pack(fill="x")
            self._widgets[attr] = (widget, wtype)

        if self.spec.get("dynamic_memory"):
            self._build_dynamic_memory(frame, obj)

        bar = ctk.CTkFrame(self, fg_color="transparent")
        bar.pack(fill="x", padx=PAD_SEC, pady=(0, PAD_SEC))
        ctk.CTkButton(bar, text=t("save"), command=self._save).pack(side="right")
        ctk.CTkButton(bar, text=t("cancel"), fg_color="gray30", hover_color="gray40",
                      command=self._close).pack(side="right", padx=(0, PAD_TIGHT))

        self._init_modal(master)

    def _value(self, attr):
        widget, wtype = self._widgets[attr]
        if wtype == "textbox":
            return widget.get("1.0", "end").strip()
        return widget.get().strip()

    def _save(self):
        values = {attr: self._value(attr) for attr, _, _ in self.spec["fields"]}
        if self.spec.get("dynamic_memory"):
            values["dyn_enabled"] = bool(self._dyn_var.get())
            values["dyn_memory"] = self._dyn_text_to_save()
        if self.spec.get("photo") and self._store is not None:
            values["photo"] = self._photo_name
            values["gallery"] = list(self._gallery.names)
            values["emotes"] = list(self._emotes.names)
        if not values.get("name"):
            messagebox.showwarning(t("preset_name_title"), t("preset_name_msg"),
                                   parent=self)
            return
        obj = self.spec["model"](**values)
        if self._base is not None:
            obj.id = self._base.id            # правка на месте, не дубль
        self.result = obj
        self._close()

    # --- динамическая память (только персонаж-собеседник) -------------------
    def _build_dynamic_memory(self, frame, obj):
        self._dyn_initial = (getattr(obj, "dyn_memory", "") or "") if obj is not None else ""
        self._dyn_var = tk.BooleanVar(
            value=bool(getattr(obj, "dyn_enabled", False)) if obj is not None else False)
        ctk.CTkCheckBox(frame, text=t("dyn_enable"), variable=self._dyn_var).pack(
            anchor="w", pady=(PAD_SEC, PAD_TIGHT))
        ctk.CTkLabel(frame, text=t("dyn_hint"), anchor="w",
                     justify="left", wraplength=470, text_color="gray",
                     font=ctk.CTkFont(size=11)).pack(fill="x")
        self._dyn_box = ctk.CTkTextbox(frame, height=TEXTBOX_HEIGHT, wrap="word")
        if self._dyn_initial:
            self._dyn_box.insert("1.0", self._dyn_initial)
        self._dyn_box.pack(fill="x", pady=(PAD_TIGHT, 0))
        ctk.CTkButton(frame, text=t("dyn_clear"), width=220, fg_color="#8a3a3a",
                      hover_color="#a34a4a",
                      command=lambda: self._dyn_box.delete("1.0", "end")).pack(
            anchor="w", pady=(PAD_TIGHT, PAD))

    def _dyn_text_to_save(self) -> str:
        """Текст динамической памяти для сохранения. Приложение обновляет её
        в фоне, пока форма открыта: если текст в поле не трогали (равен тому,
        что был при открытии), берём САМОЕ СВЕЖЕЕ из хранилища, иначе
        сохранение формы затёрло бы фоновое обновление."""
        text = self._dyn_box.get("1.0", "end").strip()
        if (text == self._dyn_initial.strip() and self._base is not None
                and self._store is not None):
            try:
                fresh = next((p for p in getattr(self._store, self.spec["load"])()
                              if p.id == self._base.id), None)
            except Exception:
                fresh = None
            if fresh is not None:
                return getattr(fresh, "dyn_memory", "") or ""
        return text

    # --- фото (необязательное) ---------------------------------------------
    def _build_photo_row(self, frame):
        """АВАТАР - по той же схеме, что галерея и эмотиконы: заголовок слева,
        кнопка выбора справа (одной ширины), ниже превью с «×» под ним."""
        box = ctk.CTkFrame(frame, fg_color="transparent")
        box.pack(fill="x", pady=(PAD, PAD))
        head = ctk.CTkFrame(box, fg_color="transparent")
        head.pack(fill="x")
        ctk.CTkLabel(head, text=t("photo_label"), anchor="w", justify="left",
                     wraplength=330).pack(side="left", anchor="w")
        self._photo_pick_btn = ctk.CTkButton(head, text=t("photo_pick"),
                                             width=MEDIA_BTN_W, command=self._pick_photo)
        self._photo_pick_btn.pack(side="right", anchor="n")
        cell = ctk.CTkFrame(box, fg_color="transparent")
        cell.pack(anchor="w", padx=PAD_TIGHT, pady=(PAD_TIGHT, 0))
        # круглое превью ровно того вида, как фото будет выглядеть в чате
        self._photo_lbl = ctk.CTkLabel(cell, text=t("photo_none"), width=PHOTO_PREVIEW,
                                       height=PHOTO_PREVIEW, text_color="gray",
                                       fg_color=("gray85", "gray20"),
                                       corner_radius=PHOTO_PLACEHOLDER_RADIUS)
        self._photo_lbl.pack()
        self._photo_rm_btn = ctk.CTkButton(cell, text="×", width=PHOTO_PREVIEW, height=20,
                                           fg_color="gray30", hover_color="#a33333",
                                           command=self._remove_photo)
        self._photo_rm_btn.pack(pady=(2, 0))
        self._refresh_photo()

    def _refresh_photo(self):
        """Показать текущее фото в превью (или заглушку «нет фото»).
        Старое CTkImage держим, пока метка не переключена: если его
        PhotoImage соберёт GC раньше, tk.Label ссылается на несуществующую
        картинку и любой следующий configure падает TclError."""
        path = self._store.photo_path(self._photo_name) if self._photo_name else None
        pil = photos.make_avatar(path, PHOTO_PREVIEW * 2) if path else None
        old = self._photo_ctk
        if pil is None:
            self._photo_lbl.configure(image="", text=t("photo_none"),
                                      fg_color=("gray85", "gray20"),
                                      corner_radius=PHOTO_PLACEHOLDER_RADIUS)
            self._photo_ctk = None
            self._photo_pick_btn.configure(text=t("photo_pick"))
            self._photo_rm_btn.configure(state="disabled")
        else:
            new = ctk.CTkImage(light_image=pil, dark_image=pil,
                               size=(PHOTO_PREVIEW, PHOTO_PREVIEW))
            self._photo_lbl.configure(image=new, text="", fg_color="transparent")
            self._photo_ctk = new
            self._photo_pick_btn.configure(text=t("photo_change"))
            self._photo_rm_btn.configure(state="normal")
        del old

    def _pick_photo(self):
        if not photos.AVAILABLE:
            messagebox.showinfo(t("photo_err_title"), t("photo_need_pillow"), parent=self)
            return
        exts = " ".join(f"*.{e}" for e in photos.EXTENSIONS)
        path = filedialog.askopenfilename(
            parent=self, title=t("photo_dlg_title"),
            filetypes=[(t("ft_images"), exts), ("*", "*.*")])
        if not path:
            return
        try:
            name = self._store.import_photo(path)
        except photos.PhotoError as e:
            messagebox.showwarning(t("photo_err_title"),
                                   t("photo_err_msg", err=e), parent=self)
            return
        self._photo_name = name               # на диске лежит уже сейчас; если
        self._refresh_photo()                 # не сохранят - уберёт cleanup_photos

    def _remove_photo(self):
        self._photo_name = ""
        self._refresh_photo()

    # --- генерация значения поля моделью ----------------------------------
    def _generate_field(self, attr):
        """Кнопка «Сгенерировать» напротив поля: скрытый запрос к модели
        «придумай это поле», с учётом уже заполненных полей объекта."""
        if self._gen_active is not None:
            return
        ctx = self._gen_context() if callable(self._gen_context) else self._gen_context
        if not ctx or not ctx.get("model"):
            messagebox.showwarning(
                t("gen_title"), t("gen_pick_model"), parent=self)
            return
        values = {a: self._value(a) for a, _, _ in self.spec["fields"]}
        short = self._widgets[attr][1] == "entry"     # однострочное поле
        messages = build_field_generation_messages(
            self.block, attr, self._field_labels.get(attr, attr),
            values, self._field_labels, short=short, lang=i18n.get_lang())
        if short:
            # бэкстоп на случай, если модель всё равно уйдёт в прозу
            opts = dict(ctx.get("options") or {})
            opts["num_predict"] = 64
            ctx = {**ctx, "options": opts}

        self._gen_active = attr
        for b in self._gen_btns.values():
            b.configure(state="disabled")
        self._gen_btns[attr].configure(text="…")
        threading.Thread(target=self._gen_worker,
                         args=(ctx, messages, attr), daemon=True).start()
        self.after(100, self._poll_gen)

    def _gen_worker(self, ctx, messages, attr):
        model = ctx["model"]
        log, fmt = ctx.get("log"), ctx.get("fmt_log")
        if log is not None and fmt is not None:
            log.put(fmt(t("log_field_request", attr=attr, model=model),
                        json.dumps(messages, ensure_ascii=False, indent=2)))
        parts = []
        try:
            for ch in chat_stream(model, messages,
                                  options=ctx.get("options") or None,
                                  think=ctx.get("think"),
                                  keep_alive=ctx.get("keep_alive"),
                                  on_thinking=lambda _t: None):
                parts.append(ch)
        except OllamaError as e:
            if log is not None and fmt is not None:
                log.put(fmt(t("log_field_error", attr=attr, model=model), str(e)))
            self._gen_q.put((attr, None, str(e)))
            return
        text = "".join(parts).strip()
        if log is not None and fmt is not None:
            log.put(fmt(t("log_field_response", attr=attr, model=model),
                        text or t("log_empty")))
        self._gen_q.put((attr, text, None))

    def _poll_gen(self):
        if not self.winfo_exists():
            return
        try:
            attr, text, err = self._gen_q.get_nowait()
        except queue.Empty:
            if self._gen_active is not None:
                self.after(100, self._poll_gen)
            return
        self._gen_active = None
        try:
            for b in self._gen_btns.values():
                b.configure(state="normal")
            if attr in self._gen_btns:
                self._gen_btns[attr].configure(text=t("generate"))
        except tk.TclError:
            return                            # окно уже закрыли
        if err:
            messagebox.showwarning(
                t("gen_title"), t("gen_field_err", err=err), parent=self)
            return
        if not text:
            messagebox.showinfo(
                t("gen_title"), t("gen_empty"), parent=self)
            return
        self._set_field(attr, text)

    def _set_field(self, attr, text):
        widget, wtype = self._widgets[attr]
        if wtype == "textbox":
            widget.delete("1.0", "end")
            widget.insert("1.0", text)
        else:
            # entry - одной строкой: берём первую непустую строку ответа
            # (если модель всё же прислала несколько), схлопываем пробелы,
            # снимаем обрамляющие кавычки и точку в конце.
            line = next((s.strip() for s in text.splitlines() if s.strip()), "")
            line = " ".join(line.split()).strip('"«»').rstrip(" .")
            widget.delete(0, "end")
            widget.insert(0, line)


class PresetManager(_ModalToplevel):
    """Список пресетов одного типа. on_change() зовётся после каждой правки."""

    def __init__(self, master, store, block, on_change=None, gen_context=None):
        super().__init__(master)
        self.store = store
        self.block = block
        self.spec = BLOCK_SPECS[block]
        self.on_change = on_change
        self.gen_context = gen_context        # прокидывается в PresetEditDialog

        self.title(t("presets_win_title", title=i18n.block_title(block)))
        self.geometry("440x480")

        ctk.CTkLabel(self, text=i18n.block_title(block),
                     font=ctk.CTkFont(size=15, weight="bold")).pack(
            anchor="w", padx=PAD_SEC, pady=(PAD_SEC, PAD_TIGHT))
        ctk.CTkLabel(self, text=t("dbl_click_edit"),
                     font=ctk.CTkFont(size=11), text_color="gray").pack(
            anchor="w", padx=PAD_SEC)

        self.listbox = tk.Listbox(
            self, activestyle="none", exportselection=False, borderwidth=0,
            bg="#2b2b2b", fg="#dcdcdc", highlightthickness=0, relief="flat",
            selectbackground="#1f6aa5", selectforeground="#ffffff",
            font=("Segoe UI", 11))
        self.listbox.pack(fill="both", expand=True, padx=PAD_SEC, pady=PAD)
        self.listbox.bind("<Double-Button-1>", lambda e: self._edit())

        bar = ctk.CTkFrame(self, fg_color="transparent")
        bar.pack(fill="x", padx=PAD_SEC, pady=(0, PAD_SEC))
        ctk.CTkButton(bar, text=t("create"), width=84, command=self._create).pack(side="left")
        ctk.CTkButton(bar, text=t("edit"), width=118,
                      command=self._edit).pack(side="left", padx=PAD_TIGHT)
        ctk.CTkButton(bar, text=t("delete"), width=84, fg_color="#a33333",
                      hover_color="#c44444", command=self._delete).pack(side="left")
        ctk.CTkButton(bar, text=t("close"), width=84, fg_color="gray30",
                      hover_color="gray40", command=self._close).pack(side="right")

        self._items = []
        self._reload()
        self._init_modal(master)

    # --- данные ---
    def _load(self):
        return getattr(self.store, self.spec["load"])()

    def _reload(self, select_id=None):
        self._items = self._load()
        self.listbox.delete(0, "end")
        for obj in self._items:
            self.listbox.insert("end", obj.name or t("unnamed"))
        if select_id is not None:
            for i, obj in enumerate(self._items):
                if obj.id == select_id:
                    self.listbox.selection_set(i)
                    self.listbox.see(i)
                    break

    def _selected(self):
        sel = self.listbox.curselection()
        return self._items[sel[0]] if sel else None

    def _notify(self):
        if self.on_change:
            self.on_change()

    # --- действия ---
    def _create(self):
        self._run_editor(None)

    def _edit(self):
        obj = self._selected()
        if obj is None:
            messagebox.showinfo(t("pick_preset_title"), t("pick_preset_msg"),
                                parent=self)
            return
        self._run_editor(obj)

    def _run_editor(self, obj):
        dlg = PresetEditDialog(self, self.block, obj=obj,
                               gen_context=self.gen_context, store=self.store)
        self.wait_window(dlg)
        self.after(50, self._grab)            # вернуть grab менеджеру
        if dlg.result is not None:
            getattr(self.store, self.spec["upsert"])(dlg.result)
            self._reload(select_id=dlg.result.id)
            self._notify()

    def _delete(self):
        obj = self._selected()
        if obj is None:
            messagebox.showinfo(t("pick_preset_title"), t("pick_preset_msg"),
                                parent=self)
            return
        if not messagebox.askyesno(
                t("delete_preset_title"),
                t("delete_preset_msg", name=obj.name or t("unnamed")), parent=self):
            return
        getattr(self.store, self.spec["delete"])(obj.id)
        self._reload()
        self._notify()
