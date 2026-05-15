"""
Версия приложения — единственный источник правды.

Используется:
  - в UI (About, update checker)
  - в build.ps1 (инжектируется в ISS-файлы при сборке)
  - в заголовке окна (опционально)
"""

__version__ = "1.0.0"

# GitHub repo для проверки обновлений
GITHUB_OWNER = "xietyBTW"
GITHUB_REPO  = "Tf2SkinGenerator"
RELEASES_URL = f"https://github.com/{GITHUB_OWNER}/{GITHUB_REPO}/releases/latest"
