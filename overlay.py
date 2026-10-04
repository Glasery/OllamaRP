"""
Фото «поверх интерфейса»: отдельное безрамочное окно с настоящей попиксельной
прозрачностью (Windows, слоистое окно + UpdateLayeredWindow).

Tk сам так не умеет: его `-alpha` - прозрачность всего окна, а
`-transparentcolor` - цветовой ключ без полупрозрачных пикселей (мягкие края
PNG получили бы рваную кромку). Поэтому здесь через ctypes создаётся
Win32-окно, в которое мы сами кладём готовый кадр (BGRA с предумноженной
альфой), а ОС его компонует поверх всего остального.

Свойства окна:
  * владелец - главное окно приложения: всегда над ним, но под чужими
    программами; сворачивается и прячется вместе с ним; в панели задач нет;
  * не активируется и ПРОПУСКАЕТ мышь целиком (WS_EX_TRANSPARENT) - фигура
    чисто декоративная и не мешает кликать по интерфейсу под ней;
  * положение/размер задаёт вызывающий в экранных (физических) пикселях.

Модуль безопасен для импорта на любой ОС: не Windows / нет Pillow ->
`AVAILABLE = False`, класс не создаётся, приложение показывает обычную
панель «Фото».
"""
import sys

try:
    import photos
    _HAVE_PIL = photos.AVAILABLE
except Exception:
    photos = None
    _HAVE_PIL = False

AVAILABLE = sys.platform == "win32" and _HAVE_PIL

if AVAILABLE:
    import ctypes
    from ctypes import wintypes

    _user32 = ctypes.windll.user32
    _gdi32 = ctypes.windll.gdi32

    GWL_EXSTYLE = -20
    GWLP_HWNDPARENT = -8
    WS_EX_TRANSPARENT = 0x00000020
    WS_EX_TOOLWINDOW = 0x00000080
    WS_EX_LAYERED = 0x00080000
    WS_EX_NOACTIVATE = 0x08000000
    GA_ROOT = 2
    SW_HIDE = 0
    SW_SHOWNOACTIVATE = 4
    ULW_ALPHA = 0x00000002
    AC_SRC_OVER = 0x00
    AC_SRC_ALPHA = 0x01
    DIB_RGB_COLORS = 0
    SWP_NOSIZE, SWP_NOMOVE, SWP_NOACTIVATE = 0x0001, 0x0002, 0x0010

    class _BLENDFUNCTION(ctypes.Structure):
        _fields_ = [("BlendOp", ctypes.c_ubyte), ("BlendFlags", ctypes.c_ubyte),
                    ("SourceConstantAlpha", ctypes.c_ubyte),
                    ("AlphaFormat", ctypes.c_ubyte)]

    class _BITMAPINFOHEADER(ctypes.Structure):
        _fields_ = [("biSize", wintypes.DWORD), ("biWidth", wintypes.LONG),
                    ("biHeight", wintypes.LONG), ("biPlanes", wintypes.WORD),
                    ("biBitCount", wintypes.WORD), ("biCompression", wintypes.DWORD),
                    ("biSizeImage", wintypes.DWORD), ("biXPelsPerMeter", wintypes.LONG),
                    ("biYPelsPerMeter", wintypes.LONG), ("biClrUsed", wintypes.DWORD),
                    ("biClrImportant", wintypes.DWORD)]

    class _BITMAPINFO(ctypes.Structure):
        _fields_ = [("bmiHeader", _BITMAPINFOHEADER), ("bmiColors", wintypes.DWORD * 3)]

    # Явные сигнатуры: на 64-битной Windows по умолчанию ctypes режет
    # указатели/HWND до int и ломает вызовы.
    _user32.GetAncestor.argtypes = [wintypes.HWND, wintypes.UINT]
    _user32.GetAncestor.restype = wintypes.HWND
    _user32.GetWindowLongW.argtypes = [wintypes.HWND, ctypes.c_int]
    _user32.GetWindowLongW.restype = wintypes.LONG
    _user32.SetWindowLongW.argtypes = [wintypes.HWND, ctypes.c_int, wintypes.LONG]
    _user32.SetWindowLongW.restype = wintypes.LONG
    _set_ptr = getattr(_user32, "SetWindowLongPtrW", None)
    if _set_ptr is not None:
        _set_ptr.argtypes = [wintypes.HWND, ctypes.c_int, ctypes.c_void_p]
        _set_ptr.restype = ctypes.c_void_p
    _user32.ShowWindow.argtypes = [wintypes.HWND, ctypes.c_int]
    _user32.GetDC.argtypes = [wintypes.HWND]
    _user32.GetDC.restype = wintypes.HDC
    _user32.ReleaseDC.argtypes = [wintypes.HWND, wintypes.HDC]
    _user32.SetWindowPos.argtypes = [wintypes.HWND, wintypes.HWND, ctypes.c_int,
                                     ctypes.c_int, ctypes.c_int, ctypes.c_int,
                                     wintypes.UINT]
    _user32.UpdateLayeredWindow.argtypes = [
        wintypes.HWND, wintypes.HDC, ctypes.POINTER(wintypes.POINT),
        ctypes.POINTER(wintypes.SIZE), wintypes.HDC, ctypes.POINTER(wintypes.POINT),
        wintypes.COLORREF, ctypes.POINTER(_BLENDFUNCTION), wintypes.DWORD]
    _user32.UpdateLayeredWindow.restype = wintypes.BOOL
    _gdi32.CreateCompatibleDC.argtypes = [wintypes.HDC]
    _gdi32.CreateCompatibleDC.restype = wintypes.HDC
    _gdi32.CreateDIBSection.argtypes = [wintypes.HDC, ctypes.POINTER(_BITMAPINFO),
                                        wintypes.UINT, ctypes.POINTER(ctypes.c_void_p),
                                        wintypes.HANDLE, wintypes.DWORD]
    _gdi32.CreateDIBSection.restype = wintypes.HBITMAP
    _gdi32.SelectObject.argtypes = [wintypes.HDC, wintypes.HGDIOBJ]
    _gdi32.SelectObject.restype = wintypes.HGDIOBJ
    _gdi32.DeleteObject.argtypes = [wintypes.HGDIOBJ]
    _gdi32.DeleteDC.argtypes = [wintypes.HDC]

    class _RECT(ctypes.Structure):
        _fields_ = [("left", ctypes.c_long), ("top", ctypes.c_long),
                    ("right", ctypes.c_long), ("bottom", ctypes.c_long)]

    class _MONITORINFO(ctypes.Structure):
        _fields_ = [("cbSize", wintypes.DWORD), ("rcMonitor", _RECT),
                    ("rcWork", _RECT), ("dwFlags", wintypes.DWORD)]

    _user32.MonitorFromWindow.argtypes = [wintypes.HWND, wintypes.DWORD]
    _user32.MonitorFromWindow.restype = wintypes.HANDLE
    _user32.GetMonitorInfoW.argtypes = [wintypes.HANDLE, ctypes.POINTER(_MONITORINFO)]
    _user32.GetMonitorInfoW.restype = wintypes.BOOL

    def _set_owner(hwnd, owner):
        if _set_ptr is not None:
            _set_ptr(hwnd, GWLP_HWNDPARENT, owner)
        else:                                      # 32-бит
            _user32.SetWindowLongW(hwnd, GWLP_HWNDPARENT, owner)


def monitor_bounds(tk_widget):
    """(left, top, right, bottom) МОНИТОРА, на котором сейчас окно приложения,
    в физических пикселях. Эмотиконы выравниваются по `bottom` - нижнему краю
    экрана (а не окна приложения). Не вышло / не Windows - основной экран
    по данным Tk."""
    try:
        if AVAILABLE:
            hwnd = _user32.GetAncestor(tk_widget.winfo_id(), GA_ROOT)
            hmon = _user32.MonitorFromWindow(hwnd, 2)          # MONITOR_DEFAULTTONEAREST
            info = _MONITORINFO()
            info.cbSize = ctypes.sizeof(_MONITORINFO)
            if hmon and _user32.GetMonitorInfoW(hmon, ctypes.byref(info)):
                r = info.rcMonitor
                return (r.left, r.top, r.right, r.bottom)
    except Exception:
        pass
    return (0, 0, tk_widget.winfo_screenwidth(), tk_widget.winfo_screenheight())


def _premultiplied_bgra(pil_rgba):
    """PIL RGBA -> байты BGRA с ПРЕДУМНОЖЕННОЙ альфой (так требует AC_SRC_ALPHA)."""
    return pil_rgba.convert("RGBa").tobytes("raw", "BGRa")


class PhotoOverlay:
    """Одно такое окно = одна фигура. Методы зовутся из главного (Tk) потока."""

    def __init__(self, master):
        import tkinter as tk
        assert AVAILABLE, "overlay недоступен на этой платформе"
        self._master = master
        self._tk = tk.Toplevel(master)
        self._tk.overrideredirect(True)
        self._tk.geometry("1x1+-32000+-32000")       # за экраном: без мигания при создании
        self._tk.update_idletasks()
        self._hwnd = _user32.GetAncestor(self._tk.winfo_id(), GA_ROOT)
        owner = _user32.GetAncestor(master.winfo_id(), GA_ROOT)
        style = _user32.GetWindowLongW(self._hwnd, GWL_EXSTYLE)
        _user32.SetWindowLongW(
            self._hwnd, GWL_EXSTYLE,
            style | WS_EX_LAYERED | WS_EX_TRANSPARENT | WS_EX_TOOLWINDOW | WS_EX_NOACTIVATE)
        _set_owner(self._hwnd, owner)
        self._visible = False
        self._frame = None            # (ключ, bgra-байты, w, h) последнего кадра
        self._pos = (0, 0)

    # ---------------------------------------------------------- кадр ----
    def _present(self, bgra, w, h, x, y):
        bmi = _BITMAPINFO()
        bmi.bmiHeader.biSize = ctypes.sizeof(_BITMAPINFOHEADER)
        bmi.bmiHeader.biWidth = w
        bmi.bmiHeader.biHeight = -h                # сверху вниз
        bmi.bmiHeader.biPlanes = 1
        bmi.bmiHeader.biBitCount = 32
        bmi.bmiHeader.biCompression = 0            # BI_RGB
        screen = _user32.GetDC(None)
        mem = _gdi32.CreateCompatibleDC(screen)
        bits = ctypes.c_void_p()
        bmp = _gdi32.CreateDIBSection(mem, ctypes.byref(bmi), DIB_RGB_COLORS,
                                      ctypes.byref(bits), None, 0)
        ok = False
        try:
            if bmp and bits.value:
                ctypes.memmove(bits, bgra, w * h * 4)
                old = _gdi32.SelectObject(mem, bmp)
                blend = _BLENDFUNCTION(AC_SRC_OVER, 0, 255, AC_SRC_ALPHA)
                ok = bool(_user32.UpdateLayeredWindow(
                    self._hwnd, screen, ctypes.byref(wintypes.POINT(x, y)),
                    ctypes.byref(wintypes.SIZE(w, h)), mem,
                    ctypes.byref(wintypes.POINT(0, 0)), 0, ctypes.byref(blend),
                    ULW_ALPHA))
                _gdi32.SelectObject(mem, old)
        finally:
            if bmp:
                _gdi32.DeleteObject(bmp)
            _gdi32.DeleteDC(mem)
            _user32.ReleaseDC(None, screen)
        return ok

    def render(self, pil_rgba, width, height):
        """Подготовить кадр нужного размера (кэш: тот же объект и размер - тот же кадр)."""
        key = (id(pil_rgba), width, height)
        if self._frame is None or self._frame[0] != key:
            im = pil_rgba.resize((width, height), photos.Image.LANCZOS)
            self._frame = (key, _premultiplied_bgra(im), width, height)
        return self._frame

    def show(self, frame, x, y):
        """Показать готовый кадр с левым верхним углом в экранных (x, y)."""
        _key, bgra, w, h = frame
        if not self._present(bgra, w, h, int(x), int(y)):
            return False
        self._pos = (int(x), int(y))
        if not self._visible:
            _user32.ShowWindow(self._hwnd, SW_SHOWNOACTIVATE)
            self._visible = True
        return True

    def move(self, x, y):
        if self._frame is not None and self._visible:
            self.show(self._frame, x, y)

    def hide(self):
        if self._visible:
            _user32.ShowWindow(self._hwnd, SW_HIDE)
            self._visible = False

    @property
    def visible(self):
        return self._visible

    def destroy(self):
        try:
            self.hide()
            self._tk.destroy()
        except Exception:
            pass
