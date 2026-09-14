"""
Утилиты для работы с путями TF2
"""

import os
import re
import string
from pathlib import Path
from typing import List, Optional, Tuple
from src.shared.paths import install_dir

#: Номер TF2 в Steam: по нему в библиотеке лежит appmanifest_440.acf.
TF2_APP_ID = "440"

#: Имя папки игры по умолчанию — то, что Steam пишет в `installdir`.
TF2_DEFAULT_DIR = "Team Fortress 2"


def _steam_from_registry() -> List[str]:
    """Папки Steam из реестра — так же, как их находит сам Steam.

    Ключей три, потому что записывают их разные вещи: HKCU ставит клиент при
    каждом запуске, HKLM — установщик (32-битная ветка на 64-битной системе).
    """
    out: List[str] = []
    try:
        import winreg  # только Windows; на другой ОС приложение не работает
    except ImportError:
        return out
    for hive, key, name in (
        (winreg.HKEY_CURRENT_USER, r"Software\Valve\Steam", "SteamPath"),
        (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\WOW6432Node\Valve\Steam",
         "InstallPath"),
        (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Valve\Steam", "InstallPath"),
    ):
        try:
            with winreg.OpenKey(hive, key) as handle:
                value = str(winreg.QueryValueEx(handle, name)[0] or "")
        except OSError:
            continue
        if value:
            out.append(os.path.normpath(value))
    return out


def _steam_guesses() -> List[str]:
    """Запасные места на случай, когда реестра нет (портативный Steam).

    Дешёвая проверка: пара `exists` на каждый существующий диск, а не обход
    файловой системы.
    """
    out: List[str] = []
    for letter in string.ascii_uppercase:
        drive = f"{letter}:\\"
        if not os.path.exists(drive):
            continue
        for name in ("Steam", "SteamLibrary", os.path.join("Games", "Steam")):
            out.append(os.path.join(drive, name))
    out.append(os.path.join(os.environ.get("ProgramFiles(x86)", ""), "Steam"))
    return [p for p in out if p and os.path.isdir(p)]


def _steam_libraries() -> List[str]:
    """Библиотеки Steam: папка клиента плюс всё из libraryfolders.vdf.

    Игру ставят на любой диск, и путь к ней в реестре не лежит — только
    список библиотек рядом с клиентом.
    """
    out: List[str] = []
    seen: set = set()

    def add(path: str) -> None:
        # Реестр отдаёт путь как записал клиент ('d:\steam'), догадки — как
        # собрали мы ('D:\Steam'). Для файловой системы это одно и то же, и
        # читать один и тот же libraryfolders.vdf дважды незачем.
        key = os.path.normcase(path)
        if path and key not in seen:
            seen.add(key)
            out.append(path)

    for steam in _steam_from_registry() + _steam_guesses():
        add(steam)
        vdf = os.path.join(steam, "steamapps", "libraryfolders.vdf")
        try:
            with open(vdf, encoding="utf-8", errors="replace") as handle:
                text = handle.read()
        except OSError:
            continue
        # Формат менялся: до 2021 путь стоял значением номера
        # («"1"  "D:\Games"»), сейчас — ключом "path" внутри блока. Оба
        # варианта встречаются на живых машинах, поэтому берём и тот, и этот.
        # У старой формы значение обязано выглядеть путём: те же «"440"
        # "12345"» из блока apps иначе приезжают библиотеками.
        for pattern in (r'"path"\s*"([^"]+)"',
                        r'"\d+"\s*"([A-Za-z]:[^"]*)"'):
            for match in re.finditer(pattern, text):
                add(os.path.normpath(match.group(1).replace("\\\\", "\\")))
    return out


def _tf2_dir_in(library: str) -> str:
    """Куда в этой библиотеке Steam положил бы TF2.

    Имя папки берём из appmanifest_440.acf: обычно это «Team Fortress 2», но
    у переехавшей или перенесённой вручную установки оно другое, и жёстко
    вписанное имя такую копию не находит.
    """
    apps = os.path.join(library, "steamapps")
    name = TF2_DEFAULT_DIR
    manifest = os.path.join(apps, f"appmanifest_{TF2_APP_ID}.acf")
    try:
        with open(manifest, encoding="utf-8", errors="replace") as handle:
            match = re.search(r'"installdir"\s*"([^"]+)"', handle.read())
        if match:
            name = match.group(1)
    except OSError:
        pass
    return os.path.join(apps, "common", name)


class TF2Paths:
    """Класс для разрешения путей TF2"""
    
    #: Бандл рядом с .exe — только чтение (см. src/shared/paths.py).
    CROWBAR_PATH = str(install_dir() / "tools/crowbar/CrowbarCommandLineDecomp.exe")
    
    @staticmethod
    def resolve(tf2_root_dir: str) -> Tuple[str, str, str]:
        """
        Разрешает пути к необходимым файлам TF2
        
        Args:
            tf2_root_dir: Корневая директория TF2 (steamapps/common/Team Fortress 2)
            
        Returns:
            Tuple[studiomdl_exe, tf2_misc_dir_vpk, tf_dir]
            
        Raises:
            FileNotFoundError: Если какой-то файл не найден
        """
        if not os.path.exists(tf2_root_dir):
            raise FileNotFoundError(f"TF2 root directory not found: {tf2_root_dir}")
        
        # Путь к studiomdl.exe
        studiomdl_exe = os.path.join(tf2_root_dir, "bin", "studiomdl.exe")
        if not os.path.exists(studiomdl_exe):
            raise FileNotFoundError(
                f"studiomdl.exe not found at: {studiomdl_exe}\n"
                f"Expected path: <tf2_root_dir>\\bin\\studiomdl.exe"
            )
        
        # Путь к tf2_misc_dir.vpk
        tf_dir = os.path.join(tf2_root_dir, "tf")
        tf2_misc_dir_vpk = os.path.join(tf_dir, "tf2_misc_dir.vpk")
        if not os.path.exists(tf2_misc_dir_vpk):
            raise FileNotFoundError(
                f"tf2_misc_dir.vpk not found at: {tf2_misc_dir_vpk}\n"
                f"Expected path: <tf2_root_dir>\\tf\\tf2_misc_dir.vpk"
            )

        return studiomdl_exe, tf2_misc_dir_vpk, tf_dir
    
    @staticmethod
    def is_valid(tf2_root_dir: str) -> bool:
        """True, если путь TF2 указан и resolve() найдёт все нужные файлы.

        Используется для подсказки-баннера в UI.
        """
        try:
            TF2Paths.resolve(tf2_root_dir)
            return True
        except (FileNotFoundError, OSError):
            return False

    @staticmethod
    def skybox_vpks(tf2_root_dir: str) -> List[str]:
        """VPK, в которых лежат небеса: и tf/, и hl2/.

        TF2 монтирует контент Half-Life 2, и его небеса — законная часть игры:
        карты (в том числе сообществa) ставят в worldspawn `sky_day01_01`,
        `sky_borealis01` и прочие, а в `tf2_*.vpk` их нет вовсе. Пока смотрели
        только в tf/, из 47 небес установленной игры приложение видело 22.

        Порядок важен: tf/ первым — если небо есть в обоих (переопределение
        Valve), в игре главнее контент самой TF2.

        Возвращает только существующие файлы; ни одного — пустой список, а
        решение, что делать, остаётся за вызывающим.
        """
        pairs = (("tf", "tf2_misc_dir.vpk"), ("tf", "tf2_textures_dir.vpk"),
                 ("hl2", "hl2_misc_dir.vpk"), ("hl2", "hl2_textures_dir.vpk"))
        if not tf2_root_dir or not os.path.exists(tf2_root_dir):
            return []
        found = []
        for folder, name in pairs:
            path = os.path.join(tf2_root_dir, folder, name)
            if os.path.exists(path):
                found.append(path)
        return found

    @staticmethod
    def autodetect() -> List[str]:
        r"""Установленные копии TF2 — то, что можно предложить человеку.

        Ищем НЕ обходом диска (это минуты и десятки тысяч папок), а тем же
        путём, каким игру находит сам Steam:

          1. реестр -> папка Steam;
          2. ``steamapps/libraryfolders.vdf`` -> все библиотеки (игра часто
             стоит не на диске со Steam);
          3. ``appmanifest_440.acf`` -> имя папки игры (``installdir``): у
             нестандартной установки она может называться иначе;
          4. запасные места на случай, если реестра нет (портативный Steam):
             ``<диск>:\Steam`` и ``<диск>:\SteamLibrary``.

        Каждый кандидат проверяется `is_valid` — то есть по наличию
        ``bin/studiomdl.exe`` и ``tf/tf2_misc_dir.vpk``, ровно того, без чего
        приложение всё равно не работает. Поэтому «нашлось» здесь значит
        «годится», а не «похоже на игру».

        Порядок ответа — от самого вероятного; обычно в списке одна папка.
        """
        seen: set = set()
        out: List[str] = []
        for library in _steam_libraries():
            root = _tf2_dir_in(library)
            key = os.path.normcase(root)
            if key in seen:
                continue
            seen.add(key)
            if TF2Paths.is_valid(root):
                # Реестр отдаёт путь так, как его записал Steam («d:\steam»).
                # Человеку этот путь показывают и он же уходит в настройки —
                # берём написание, как на диске.
                out.append(str(Path(root).resolve()))
        return out

    @staticmethod
    def resolve_textures_vpk(tf2_root_dir: str) -> Optional[str]:
        """
        Разрешает путь к tf2_textures_dir.vpk для извлечения VMT файлов
        
        Args:
            tf2_root_dir: Корневая директория TF2
            
        Returns:
            Путь к tf2_textures_dir.vpk или None если не найден
        """
        if not os.path.exists(tf2_root_dir):
            return None
        
        tf_dir = os.path.join(tf2_root_dir, "tf")
        tf2_textures_dir_vpk = os.path.join(tf_dir, "tf2_textures_dir.vpk")
        if os.path.exists(tf2_textures_dir_vpk):
            return tf2_textures_dir_vpk
        
        return None
    
    @staticmethod
    def resolve_hl2_vpks(tf2_root_dir: str) -> list:
        """
        Пути к hl2_misc_dir.vpk / hl2_textures_dir.vpk (существующие).

        TF2 монтирует контент HL2 — часть particle-материалов (например
        particle/particle_glow_*) лежит именно там, а не в tf2_misc.
        """
        out = []
        for name in ("hl2_misc_dir.vpk", "hl2_textures_dir.vpk"):
            p = os.path.join(tf2_root_dir, "hl2", name)
            if os.path.exists(p):
                out.append(p)
        return out

    @staticmethod
    def get_crowbar_path() -> str:
        """
        Возвращает путь к Crowbar CLI
        
        Returns:
            Путь к CrowbarCommandLineDecomp.exe
        """
        return TF2Paths.CROWBAR_PATH
    
    @staticmethod
    def check_crowbar() -> Tuple[bool, Optional[str]]:
        """
        Проверяет наличие Crowbar CLI
        
        Returns:
            Tuple[exists, error_message]
        """
        crowbar_path = TF2Paths.get_crowbar_path()
        if not os.path.exists(crowbar_path):
            return False, f"Crowbar CLI missing: {crowbar_path}"
        return True, None



# ── Кандидаты MDL-путей для шапок (единая логика для сборки/превью/извлечения) ──

#: Токены классов в путях к моделям. У подрывника файлы называются `_demo`,
#: но старые моды встречаются и с `_demoman` — держим оба, кандидаты всё равно
#: перебираются по порядку.
_TF2_CLASSES = (
    "heavy", "scout", "soldier", "pyro",
    "demo", "demoman", "engineer", "medic", "sniper", "spy",
)


def build_hat_mdl_candidates(mdl_rel: str) -> list:
    """
    Список путей-кандидатов к MDL шапки внутри VPK (порядок сохранён, без дублей):

      1. Раскрывает %s-плейсхолдер во все 9 классов TF2
         (all_domination_%s.mdl → all_domination_heavy.mdl и т.д.).
      2. Добавляет варианты расположения:
         models/player/items ↔ models/workshop/player/items ↔
         models/workshop_partner/player/items.
      3. Для путей с суффиксом класса (..._heavy.mdl) добавляет остальные классы.

    Все пути приводятся к нижнему регистру (в VPK ключи — lowercase).
    Используется в сборке, 3D-превью и извлечении — раньше дублировалось трижды.
    """
    import re
    norm = mdl_rel.replace("\\", "/").lower()

    # 1. %s → классы
    if "%s" in norm:
        base = []
        for cls in _TF2_CLASSES:
            try:
                v = norm % cls
            except (TypeError, ValueError):
                v = norm.replace("%s", cls)
            if v not in base:
                base.append(v)
    else:
        base = [norm]

    # 2. player/items ↔ workshop ↔ workshop_partner
    paths = []
    for c in base:
        paths.append(c)
        for src, dsts in (
            ("models/player/items",
             ("models/workshop_partner/player/items", "models/workshop/player/items")),
            ("models/workshop/player/items",
             ("models/workshop_partner/player/items", "models/player/items")),
            ("models/workshop_partner/player/items",
             ("models/workshop/player/items", "models/player/items")),
        ):
            if src in c:
                for dst in dsts:
                    v = c.replace(src, dst)
                    if v not in paths:
                        paths.append(v)
                break

    # 3. Суффиксы класса (_heavy → остальные классы)
    cls_pat = re.compile(
        r'_(heavy|scout|soldier|pyro|demoman|engineer|medic|sniper|spy)\.mdl$'
    )
    extra = []
    for c in list(paths):
        if cls_pat.search(c):
            for cls in _TF2_CLASSES:
                # группа всегда оканчивается на .mdl — подставляем явно
                variant = cls_pat.sub(f'_{cls}.mdl', c)
                if variant not in paths and variant not in extra:
                    extra.append(variant)
    paths += extra

    return paths
