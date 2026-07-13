# Сборка из исходников

[← Оглавление документации](../README.md)

Для разработчиков, кто хочет запускать приложение из клона. **Только Windows.**

## Требования

- **Python 3.12+** в `PATH`.
- **Установленный Team Fortress 2** (нужен для сборки модов, и `vpk.exe` берётся из `<TF2>\bin\`).

## Сторонние тулзы

Crowbar и VTF-тулзы (`VTFCmd.exe`, `VTFLib.dll`, `HLLib.dll`, `DevIL.dll`) **закоммичены в
`tools/`** — качать нечего. Их лицензии (CC BY-SA 3.0 / LGPL / GPL) разрешают редистрибуцию;
см. [`THIRD_PARTY_LICENSES.md`](../../THIRD_PARTY_LICENSES.md).

Единственная тулза **не** в репо — **`vpk.exe`**: это проприетарный бинарь Valve. Приложение берёт
его из установленной TF2 (`<TF2>\bin\vpk.exe`) автоматически; при желании положи копию в
`tools/VPK/` как запасной вариант.

## Настройка и запуск

```bat
python -m venv .venv
.venv\Scripts\python -m pip install -r requirements.txt
.venv\Scripts\python main.py
```

`requirements.txt` = рантайм-зависимости (PySide6 Essentials + Addons, Pillow, `vpk`, `srctools`,
NumPy). `requirements-dev.txt` добавляет dev/тест-оснастку.

## Структура проекта

```
main.py                 точка входа (логи, сплэш, запуск MainWindow)
src/
  ui/                   виджеты PySide6 — главное окно, панели, диалоги, превью
  services/             конвейер сборки: VTF/VMT/VPK, декомпиляция/компиляция модели, диагностика
  data/                 статические таблицы (оружие, шапки, персонажи, небо…)
  config/, shared/      конфиг, логирование, версия, константы
tools/
  crowbar/, VTF/        декомпилятор Crowbar + VTF-тулзы (в репозитории)
  VPK/                  опциональный запасной vpk.exe (иначе берётся из TF2)
  Model/                пустые заглушки по классам (.gitkeep)
requirements*.txt       рантайм- и dev-зависимости
```

Версия — в `src/shared/version.py` (единственный источник правды).

## Релизные сборки

Windows-релиз собирается **PyInstaller** (`--onedir --windowed`), с копированием `tools/` в корень
вывода, чтобы frozen-приложение находило их по относительным путям. Скрипты сборки автора и
установщик Inno Setup **не** входят в репозиторий (`.gitignore`) — это справка, а не шаг, который
ты запускаешь из клона.

## Заметки

- Логи — в `tf2sg.log` рядом с приложением (в корне репозитория при запуске из исходников).
- Конфиг хранится по пользователю (`AppConfig` в `src/config/app_config.py`); создаётся с дефолтами
  при первом запуске. В репозитории — только примеры (`config/*.example.json`).
- Лицензии сторонних тулз: см. [`THIRD_PARTY_LICENSES.md`](../../THIRD_PARTY_LICENSES.md).
