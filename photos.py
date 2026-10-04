"""
Фото персонажей и главных героев: импорт в папку приложения и аватарки
для чата.

Чистая логика на Pillow, без tkinter - импортируется и в GUI, и в тестах.
Pillow - необязательная зависимость: нет его - `AVAILABLE = False`, приложение
работает как раньше, а кнопки фото подскажут, что поставить.

Фото лежат в `<папка данных>/photos/photo_<id>.png`, в пресете хранится только
ИМЯ файла (не путь) - папку данных можно переносить целиком.
"""
import uuid
from pathlib import Path
from typing import Iterable, Optional

try:
    from PIL import Image, ImageDraw, ImageOps, ImageTk
    AVAILABLE = True
except Exception:                     # Pillow не установлен
    Image = ImageDraw = ImageOps = ImageTk = None
    AVAILABLE = False

PREFIX = "photo_"
MAX_SIDE = 1024                        # импортированное фото сжимаем до этого (хватает и для панели «Фото»)
EXTENSIONS = ("png", "jpg", "jpeg", "gif", "bmp", "webp")


EMOTE_MAX_SIDE = 1600                  # эмотиконы - высокие силуэты, держим побольше
EMOTE_MIN_TRANSPARENT = 0.05           # доля (почти) прозрачных пикселей, чтобы считать фон прозрачным
EMOTE_ALPHA_THRESHOLD = 32             # альфа ниже этого - «прозрачный» пиксель


class PhotoError(Exception):
    """Файл не удалось прочитать как картинку (или нет Pillow)."""


class EmoteError(PhotoError):
    """Файл не годится в эмотиконы. `.code`: "not_png" (не PNG), "no_alpha"
    (PNG без альфа-канала), "not_transparent" (канал есть, но фон не
    прозрачный: прозрачных пикселей меньше EMOTE_MIN_TRANSPARENT)."""

    def __init__(self, code, message=""):
        super().__init__(message or code)
        self.code = code


def import_photo(src_path: str, dest_dir: Path, max_side: int = MAX_SIDE) -> str:
    """Скопировать картинку в `dest_dir` как photo_<id>.png, уменьшив длинную
    сторону до `max_side` (оригинал не трогаем). Возвращает ИМЯ файла.
    Учитывает EXIF-поворот (снимки с телефона), прозрачность сохраняет."""
    if not AVAILABLE:
        raise PhotoError("Pillow is not installed")
    try:
        with Image.open(src_path) as im:
            im = ImageOps.exif_transpose(im)
            im = im.convert("RGBA" if "A" in im.getbands() or im.mode == "P"
                            else "RGB")
            im.thumbnail((max_side, max_side), Image.LANCZOS)
            dest_dir.mkdir(parents=True, exist_ok=True)
            name = f"{PREFIX}{uuid.uuid4().hex[:10]}.png"
            im.save(dest_dir / name, format="PNG", optimize=True)
            return name
    except PhotoError:
        raise
    except Exception as e:
        raise PhotoError(str(e)) from e


def check_emote(src_path) -> None:
    """Эмотикон = ТОЛЬКО PNG-силуэт на прозрачном фоне. Проверяем по
    содержимому, а не по расширению: JPEG, переименованный в .png, не пройдёт;
    PNG без альфы (обычный скриншот/фото) - тоже; PNG с альфой, но
    сплошным фоном - тоже (прозрачных пикселей < EMOTE_MIN_TRANSPARENT).
    Бросает EmoteError(code), иначе возвращает None."""
    if not AVAILABLE:
        raise PhotoError("Pillow is not installed")
    try:
        with Image.open(src_path) as im:
            if im.format != "PNG":
                raise EmoteError("not_png")
            has_alpha = "A" in im.getbands() or (im.mode == "P" and "transparency" in im.info)
            if not has_alpha:
                raise EmoteError("no_alpha")
            alpha = im.convert("RGBA").getchannel("A")
            hist = alpha.histogram()
            total = alpha.width * alpha.height
            transparent = sum(hist[:EMOTE_ALPHA_THRESHOLD])
            if total <= 0 or transparent / total < EMOTE_MIN_TRANSPARENT:
                raise EmoteError("not_transparent")
    except PhotoError:
        raise
    except Exception as e:
        raise PhotoError(str(e)) from e


def import_emote(src_path: str, dest_dir: Path, max_side: int = EMOTE_MAX_SIDE) -> str:
    """Проверить (check_emote) и скопировать эмотикон в `dest_dir` как
    photo_<id>.png (прозрачность сохраняется). -> имя файла. EmoteError - файл
    не годится; PhotoError - не читается."""
    check_emote(src_path)
    return import_photo(src_path, dest_dir, max_side=max_side)


def load_rgba(path):
    """Открыть фото как RGBA С СОХРАНЕНИЕМ прозрачности (PNG на прозрачном
    фоне) - для панели «Фото», где картинка рисуется целиком. -> PIL.Image или
    None, если файл не открылся / нет Pillow."""
    if not AVAILABLE or not path:
        return None
    try:
        with Image.open(path) as im:
            return ImageOps.exif_transpose(im).convert("RGBA")
    except Exception:
        return None


def make_avatar(path: Path, size: int, gap: int = 0):
    """Круглая аватарка `size`x`size` (центральный квадрат фото, обрезанный
    по кругу) + `gap` прозрачных пикселей справа - отступ до текста реплики
    зашит в саму картинку, чтобы текст ровно ложился в левое поле абзаца.
    -> PIL.Image RGBA или None, если файл не открылся."""
    if not AVAILABLE or size <= 0:
        return None
    try:
        with Image.open(path) as im:
            im = im.convert("RGBA")
            side = min(im.size)
            left, top = (im.width - side) // 2, (im.height - side) // 2
            im = im.crop((left, top, left + side, top + side))
            im = im.resize((size, size), Image.LANCZOS)
    except Exception:
        return None
    # круглая маска со сглаживанием: рисуем в 4x и уменьшаем
    big = Image.new("L", (size * 4, size * 4), 0)
    ImageDraw.Draw(big).ellipse((0, 0, size * 4 - 1, size * 4 - 1), fill=255)
    mask = big.resize((size, size), Image.LANCZOS)
    alpha = Image.composite(im.getchannel("A"), Image.new("L", (size, size), 0), mask)
    im.putalpha(alpha)
    if gap <= 0:
        return im
    out = Image.new("RGBA", (size + gap, size), (0, 0, 0, 0))
    out.paste(im, (0, 0))
    return out


def to_tk(pil_image, master=None):
    """PIL.Image -> tkinter-картинка для Text.image_create (None, если нет
    Pillow). Вызывающий ОБЯЗАН держать на неё ссылку - иначе Tk её уберёт."""
    if not AVAILABLE or pil_image is None:
        return None
    return ImageTk.PhotoImage(pil_image, master=master)


def cleanup_unused(photo_dir: Path, used_names: Iterable[str]) -> int:
    """Удалить из `photo_dir` файлы photo_*.png, на которые не ссылается ни один
    пресет (остались после удаления пресета, замены фото или отменённого
    редактирования). Чужие файлы не трогаем - только наш префикс. -> сколько
    удалено."""
    if not photo_dir.is_dir():
        return 0
    used = {n for n in used_names if n}
    removed = 0
    for p in photo_dir.glob(f"{PREFIX}*.png"):
        if p.name not in used:
            try:
                p.unlink()
                removed += 1
            except OSError:
                pass
    return removed


def photo_file(photo_dir: Path, name: str) -> Optional[Path]:
    """Путь к фото по имени из пресета, если файл существует (иначе None -
    например, файл удалили руками; приложение просто покажет реплику без фото)."""
    if not name or not isinstance(name, str):
        return None
    p = photo_dir / Path(name).name           # только имя, без путей наружу
    return p if p.is_file() else None
