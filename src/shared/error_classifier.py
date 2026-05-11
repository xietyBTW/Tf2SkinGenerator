"""
Классификатор ошибок: сопоставляет технические сообщения с понятными объяснениями
для обычных пользователей.
"""

from typing import Callable, List, Tuple


# (predicate, ru_title, ru_desc, en_title, en_desc)
_RULES: List[Tuple[Callable, str, str, str, str]] = [

    # ── Путь к TF2 не настроен ────────────────────────────────────────────
    (
        lambda m: any(x in m for x in [
            "не указана папка tf2", "tf2 folder not specified", "tf2 path not specified",
        ]),
        "Не настроен путь к TF2",
        (
            "Перейдите в настройки программы и укажите папку, куда установлен "
            "Team Fortress 2.\n\n"
            "Обычно это:\n"
            "C:\\Program Files (x86)\\Steam\\steamapps\\common\\Team Fortress 2"
        ),
        "TF2 path not configured",
        (
            "Go to application settings and specify the Team Fortress 2 installation folder.\n\n"
            "Usually it is:\n"
            "C:\\Program Files (x86)\\Steam\\steamapps\\common\\Team Fortress 2"
        ),
    ),

    # ── Папка TF2 не существует ───────────────────────────────────────────
    (
        lambda m: any(x in m for x in [
            "директория tf2 не найдена", "tf2 directory not found",
        ]),
        "Папка TF2 не существует",
        (
            "Указанный путь к Team Fortress 2 не найден на диске.\n\n"
            "Убедитесь, что игра установлена, и укажите верный путь в настройках."
        ),
        "TF2 folder doesn't exist",
        (
            "The specified TF2 path was not found on disk.\n\n"
            "Make sure the game is installed and set the correct path in settings."
        ),
    ),

    # ── Путь ведёт на файл, а не папку ───────────────────────────────────
    (
        lambda m: any(x in m for x in [
            "указанный путь не является директорией", "specified path is not a directory",
        ]),
        "Неверный путь к TF2",
        (
            "Указанный путь ведёт на файл, а не на папку.\n\n"
            "Укажите корневую папку Team Fortress 2 (не exe-файл, а папку)."
        ),
        "Invalid TF2 path",
        (
            "The specified path points to a file, not a folder.\n\n"
            "Specify the root folder of Team Fortress 2 (not the exe file, but the folder)."
        ),
    ),

    # ── Crowbar не найден ─────────────────────────────────────────────────
    (
        lambda m: "crowbar" in m,
        "Декомпилятор Crowbar не найден",
        (
            "Crowbar.exe необходим для декомпиляции моделей TF2.\n\n"
            "Поместите Crowbar.exe в папку tools программы и попробуйте снова.\n"
            "Скачать: https://steamcommunity.com/groups/CrowbarTool"
        ),
        "Crowbar decompiler not found",
        (
            "Crowbar.exe is required to decompile TF2 models.\n\n"
            "Place Crowbar.exe in the program's tools folder and try again.\n"
            "Download: https://steamcommunity.com/groups/CrowbarTool"
        ),
    ),

    # ── Файл модели (.mdl) не найден в VPK ────────────────────────────────
    (
        lambda m: any(x in m for x in [
            "mdl file not found", "не найден .mdl файл", "не найден mdl файл",
        ]),
        "Модель оружия не найдена в файлах TF2",
        (
            "Программа перебрала все возможные пути внутри VPK-архивов TF2 "
            "и не нашла 3D-модель этого оружия.\n\n"
            "Возможные причины:\n"
            "• Игра обновилась и файлы были переименованы или перемещены\n"
            "• Неверно указан путь к TF2 в настройках\n"
            "• Это оружие пока не поддерживается программой"
        ),
        "Weapon model not found in TF2 files",
        (
            "The program searched all possible paths inside TF2 VPK archives "
            "and couldn't find the 3D model for this weapon.\n\n"
            "Possible reasons:\n"
            "• The game updated and files were renamed or moved\n"
            "• Incorrect TF2 path in settings\n"
            "• This weapon is not yet supported"
        ),
    ),

    # ── Модель нашлась, но не извлеклась ─────────────────────────────────
    (
        lambda m: any(x in m for x in [
            "mdl file was not extracted", "mdl файл не был извлечен",
        ]),
        "Не удалось извлечь файл модели",
        (
            "Файл модели был найден в архиве TF2, но извлечь его не получилось.\n\n"
            "Возможные причины:\n"
            "• Архив VPK повреждён\n"
            "• Нет прав на запись во временную папку"
        ),
        "Failed to extract model file",
        (
            "The model file was found in TF2's archive but couldn't be extracted.\n\n"
            "Possible reasons:\n"
            "• VPK archive is corrupted\n"
            "• No write permission in the temp folder"
        ),
    ),

    # ── Оружие не в базе данных ───────────────────────────────────────────
    (
        lambda m: any(x in m for x in [
            "not found in model paths", "не найдено в списке путей",
            "weapon_key", "weapon not found",
        ]),
        "Оружие не поддерживается",
        (
            "Это оружие отсутствует в базе данных программы — "
            "для него не настроен путь к 3D-модели.\n\n"
            "Попробуйте выбрать другое оружие или обновите программу до последней версии."
        ),
        "Weapon not supported",
        (
            "This weapon is not in the program's database — "
            "it has no configured model path.\n\n"
            "Try selecting a different weapon or update the program to the latest version."
        ),
    ),

    # ── Ошибка чтения QC-файла ────────────────────────────────────────────
    (
        lambda m: any(x in m for x in [
            "$cdmaterials", "$texturegroup", "$modelname", "qc file",
            "cdmaterials_not_extracted", "texturegroup_not_extracted",
            "modelname_not_extracted",
        ]),
        "Ошибка чтения файла модели",
        (
            "Не удалось разобрать декомпилированный QC-файл модели.\n\n"
            "Это может происходить если:\n"
            "• Декомпиляция прошла с ошибками (посмотрите технические детали)\n"
            "• Модель имеет нестандартную структуру\n"
            "• Антивирус удалил временные файлы"
        ),
        "Model file parse error",
        (
            "Failed to parse the decompiled QC model file.\n\n"
            "This can happen if:\n"
            "• Decompilation had errors (check technical details)\n"
            "• The model has a non-standard structure\n"
            "• Antivirus removed temporary files"
        ),
    ),

    # ── Ошибка компиляции studiomdl ───────────────────────────────────────
    (
        lambda m: any(x in m for x in [
            "studiomdl", "error compiling", "ошибка компиляции",
            "compile_dir_not_found", "директория компила",
            "model files not found", "файлы модели не найдены",
        ]),
        "Ошибка компиляции модели",
        (
            "studiomdl.exe не смог скомпилировать модель оружия.\n\n"
            "Возможные причины:\n"
            "• Если вы загружаете свою модель — проверьте, что она "
            "экспортирована в формате SMD и не содержит ошибок геометрии\n"
            "• Файлы TF2 были изменены обновлением игры\n"
            "• Антивирус заблокировал работу studiomdl.exe\n\n"
            "Подробности ошибки studiomdl смотрите в «Технических деталях»."
        ),
        "Model compilation failed",
        (
            "studiomdl.exe failed to compile the weapon model.\n\n"
            "Possible reasons:\n"
            "• If using a custom model — make sure it's exported in SMD format "
            "and has no geometry errors\n"
            "• TF2 files were changed by a game update\n"
            "• Antivirus blocked studiomdl.exe\n\n"
            "Check the 'Technical Details' section for studiomdl error output."
        ),
    ),

    # ── Ошибка конвертации текстуры (VTFCmd) ──────────────────────────────
    (
        lambda m: any(x in m for x in [
            "vtf creation failed", "vtf создание не удалось",
            "vtfcmd", "error_vtf_creation",
        ]),
        "Ошибка создания текстуры",
        (
            "VTFCmd.exe не смог конвертировать изображение в формат VTF.\n\n"
            "Проверьте:\n"
            "• Присутствует ли VTFCmd.exe в папке tools программы\n"
            "• Поддерживается ли формат вашего изображения (PNG, JPEG, TGA, BMP)\n"
            "• Совместим ли выбранный формат сжатия (DXT1/DXT5) с размером изображения — "
            "размер должен быть кратен 4"
        ),
        "Texture creation failed",
        (
            "VTFCmd.exe failed to convert the image to VTF format.\n\n"
            "Check:\n"
            "• Is VTFCmd.exe present in the program's tools folder\n"
            "• Is your image format supported (PNG, JPEG, TGA, BMP)\n"
            "• Is the selected compression (DXT1/DXT5) compatible with your image size — "
            "dimensions must be multiples of 4"
        ),
    ),

    # ── Ошибка упаковки VPK ───────────────────────────────────────────────
    (
        lambda m: any(x in m for x in [
            "vpk creation failed", "vpk создание не удалось",
            "error_vpk_creation_failed",
        ]),
        "Ошибка создания VPK файла",
        (
            "Утилита vpk.exe не смогла упаковать файлы в мод.\n\n"
            "Проверьте:\n"
            "• Достаточно ли места на диске\n"
            "• Правильно ли указана папка для экспорта в настройках\n"
            "• Есть ли у программы права на запись в папку экспорта"
        ),
        "VPK creation failed",
        (
            "The vpk.exe tool failed to pack files into a mod.\n\n"
            "Check:\n"
            "• Is there enough free disk space\n"
            "• Is the export folder path correct in settings\n"
            "• Does the program have write access to the export folder"
        ),
    ),

    # ── VPK файл не появился после сборки ────────────────────────────────
    (
        lambda m: any(x in m for x in [
            "vpkroot.vpk не найден", "vpkroot.vpk not found",
            "root.vpk не найден", "root.vpk not found",
            "error_vpkroot_not_found",
        ]),
        "Готовый VPK файл не создан",
        (
            "Команда упаковки выполнилась, но результирующий .vpk файл не появился.\n\n"
            "Возможные причины:\n"
            "• Недостаточно места на диске\n"
            "• Нет прав на запись в папку экспорта\n"
            "• vpk.exe завершился с ошибкой (см. технические детали)"
        ),
        "VPK file was not created",
        (
            "The packaging command ran but the resulting .vpk file didn't appear.\n\n"
            "Possible reasons:\n"
            "• Not enough disk space\n"
            "• No write permission in the export folder\n"
            "• vpk.exe exited with an error (see technical details)"
        ),
    ),

    # ── Слишком длинный путь (Windows ограничение) ────────────────────────
    (
        lambda m: any(x in m for x in [
            "путь слишком длинный", "path too long", "error_path_too_long",
        ]),
        "Слишком длинный путь к файлам",
        (
            "Windows не поддерживает пути длиннее 260 символов.\n\n"
            "Решение: переместите программу ближе к корню диска, "
            "например в C:\\TF2Skin или D:\\Mods, и попробуйте снова."
        ),
        "File path is too long",
        (
            "Windows doesn't support file paths longer than 260 characters.\n\n"
            "Solution: move the program closer to the root of the drive, "
            "e.g. C:\\TF2Skin or D:\\Mods, and try again."
        ),
    ),

    # ── Изображение не найдено ────────────────────────────────────────────
    (
        lambda m: any(x in m for x in [
            "изображение не найдено", "image not found",
            "image path not specified", "не указан путь к изображению",
        ]),
        "Изображение не найдено",
        (
            "Файл изображения был перемещён, переименован или удалён "
            "после того как был загружен в программу.\n\n"
            "Загрузите изображение заново."
        ),
        "Image not found",
        (
            "The image file was moved, renamed, or deleted "
            "after being loaded into the program.\n\n"
            "Please load the image again."
        ),
    ),

    # ── Пользовательский VTF не найден ───────────────────────────────────
    (
        lambda m: any(x in m for x in [
            "custom vtf", "vtf файл не найден", "vtf file not found",
            "custom_vtf_not_found",
        ]),
        "VTF файл не найден",
        (
            "Выбранный VTF файл был перемещён или удалён.\n\n"
            "Выберите файл заново."
        ),
        "Custom VTF file not found",
        (
            "The selected VTF file was moved or deleted.\n\n"
            "Please select the file again."
        ),
    ),

    # ── Отказано в доступе ────────────────────────────────────────────────
    (
        lambda m: any(x in m for x in [
            "access is denied", "access denied", "permission denied",
            "отказано в доступе", "permissionerror",
        ]),
        "Отказано в доступе к файлу",
        (
            "Windows заблокировал доступ к файлу или папке.\n\n"
            "Попробуйте:\n"
            "• Запустить программу от имени администратора "
            "(правой кнопкой на exe → «Запуск от имени администратора»)\n"
            "• Убедиться, что файл не открыт другой программой\n"
            "• Временно отключить антивирус"
        ),
        "Access denied",
        (
            "Windows blocked access to a file or folder.\n\n"
            "Try:\n"
            "• Running the program as administrator "
            "(right-click exe → 'Run as administrator')\n"
            "• Making sure the file is not open in another program\n"
            "• Temporarily disabling your antivirus"
        ),
    ),

    # ── Мало места на диске ───────────────────────────────────────────────
    (
        lambda m: any(x in m for x in [
            "no space left", "not enough space", "недостаточно места",
            "disk full", "oserror: [errno 28]",
        ]),
        "Закончилось место на диске",
        (
            "На диске недостаточно свободного места для создания мода.\n\n"
            "Освободите место на диске и попробуйте снова."
        ),
        "Not enough disk space",
        (
            "There is not enough free disk space to create the mod.\n\n"
            "Free up some disk space and try again."
        ),
    ),

    # ── Объединение VPK модов ─────────────────────────────────────────────
    (
        lambda m: any(x in m for x in [
            "merging vpk", "объединен", "error_merging_vpk",
            "error_extracting_vpk", "error_creating_merged",
        ]),
        "Ошибка объединения модов",
        (
            "Не удалось объединить VPK файлы.\n\n"
            "Убедитесь, что выбранные файлы являются корректными модами TF2 "
            "и не повреждены."
        ),
        "Mod merge failed",
        (
            "Failed to merge VPK files.\n\n"
            "Make sure the selected files are valid, non-corrupted TF2 mods."
        ),
    ),

    # ── Общая ошибка при работе с моделью ────────────────────────────────
    (
        lambda m: any(x in m for x in [
            "ошибка при работе с моделью", "error while working with model",
            "error_model_work",
        ]),
        "Ошибка при обработке модели",
        (
            "Произошла ошибка во время работы с моделью оружия.\n\n"
            "Это может быть связано с декомпиляцией, заменой геометрии "
            "или компиляцией модели. Подробности — в «Технических деталях»."
        ),
        "Model processing error",
        (
            "An error occurred while processing the weapon model.\n\n"
            "This may be related to decompilation, geometry replacement, "
            "or model compilation. See 'Technical Details' for more."
        ),
    ),
]


def classify(message: str, language: str = "ru") -> Tuple[str, str]:
    """
    Возвращает (понятный_заголовок, понятное_описание) по тексту технической ошибки.

    Args:
        message: Техническое сообщение об ошибке (на любом языке).
        language: Язык интерфейса ('ru' или 'en').

    Returns:
        (title, description) — пара строк для отображения пользователю.
    """
    m = message.lower()
    is_ru = (language == "ru")

    for pred, ru_title, ru_desc, en_title, en_desc in _RULES:
        try:
            if pred(m):
                return (ru_title, ru_desc) if is_ru else (en_title, en_desc)
        except Exception:
            continue

    if is_ru:
        return (
            "Произошла непредвиденная ошибка",
            "Программа столкнулась с неожиданной ситуацией.\n\n"
            "Подробности смотрите в разделе «Технические детали» ниже.",
        )
    return (
        "An unexpected error occurred",
        "The program encountered an unexpected situation.\n\n"
        "See the 'Technical Details' section below for more information.",
    )
