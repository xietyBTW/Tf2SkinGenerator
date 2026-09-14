"""
Автопоиск установленной TF2.

Ищем так, как игру находит сам Steam: реестр -> папка клиента ->
`libraryfolders.vdf` -> `appmanifest_440.acf`. Обхода диска здесь нет
намеренно: это минуты работы и десятки тысяч папок, а ответ всё равно лежит
в двух файлах.

Реестр в тестах не читаем — подменяем `_steam_from_registry`: на машине
сборки Steam может не стоять вовсе, а проверять надо разбор путей.
"""

import io
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from src.services import tf2_paths as mod


def _fake_game(root: Path) -> None:
    """Минимальная установка: ровно то, что проверяет `is_valid`."""
    (root / "bin").mkdir(parents=True, exist_ok=True)
    (root / "bin" / "studiomdl.exe").write_bytes(b"")
    (root / "tf").mkdir(parents=True, exist_ok=True)
    (root / "tf" / "tf2_misc_dir.vpk").write_bytes(b"")


class AutodetectTests(unittest.TestCase):
    def _run(self, steam_dirs):
        """Автопоиск с подменёнными реестром и догадками по диску."""
        with mock.patch.object(mod, '_steam_from_registry',
                               return_value=list(steam_dirs)), \
             mock.patch.object(mod, '_steam_guesses', return_value=[]):
            return mod.TF2Paths.autodetect()

    def test_game_in_the_steam_folder_itself(self):
        with tempfile.TemporaryDirectory() as tmp:
            steam = Path(tmp) / "Steam"
            game = steam / "steamapps" / "common" / "Team Fortress 2"
            _fake_game(game)
            self.assertEqual(self._run([str(steam)]),
                             [os.path.normpath(str(game))])

    def test_game_in_another_library(self):
        """Игру ставят на второй диск, и в реестре этого пути нет.

        Единственный источник — список библиотек рядом с клиентом. Формат VDF
        здесь новый: путь лежит ключом "path" внутри блока.
        """
        with tempfile.TemporaryDirectory() as tmp:
            steam = Path(tmp) / "Steam"
            other = Path(tmp) / "Games" / "SteamLibrary"
            game = other / "steamapps" / "common" / "Team Fortress 2"
            _fake_game(game)
            (steam / "steamapps").mkdir(parents=True)
            io.open(steam / "steamapps" / "libraryfolders.vdf", 'w',
                    encoding='utf-8').write(
                '"libraryfolders"\n{\n\t"0"\n\t{\n'
                f'\t\t"path"\t\t"{str(other).replace(os.sep, os.sep * 2)}"\n'
                '\t\t"apps"\n\t\t{\n\t\t\t"440"\t\t"12345678"\n\t\t}\n'
                '\t}\n}\n')
            self.assertEqual(self._run([str(steam)]),
                             [os.path.normpath(str(game))])

    def test_old_vdf_format(self):
        """До 2021 путь стоял значением номера: «"1" "D:\\\\Games"».

        Такие файлы живы на машинах, где Steam давно не переустанавливали.
        """
        with tempfile.TemporaryDirectory() as tmp:
            steam = Path(tmp) / "Steam"
            other = Path(tmp) / "Lib2"
            game = other / "steamapps" / "common" / "Team Fortress 2"
            _fake_game(game)
            (steam / "steamapps").mkdir(parents=True)
            io.open(steam / "steamapps" / "libraryfolders.vdf", 'w',
                    encoding='utf-8').write(
                '"LibraryFolders"\n{\n\t"TimeNextStatsReport"\t\t"1500000000"\n'
                f'\t"1"\t\t"{str(other).replace(os.sep, os.sep * 2)}"\n}}\n')
            self.assertEqual(self._run([str(steam)]),
                             [os.path.normpath(str(game))])

    def test_folder_name_from_the_manifest(self):
        """Папка игры называется так, как записано в installdir.

        У перенесённой вручную установки это не «Team Fortress 2», и вписанное
        жёстко имя такую копию не находит.
        """
        with tempfile.TemporaryDirectory() as tmp:
            steam = Path(tmp) / "Steam"
            apps = steam / "steamapps"
            game = apps / "common" / "TF2 Moved"
            _fake_game(game)
            io.open(apps / "appmanifest_440.acf", 'w', encoding='utf-8').write(
                '"AppState"\n{\n\t"appid"\t\t"440"\n'
                '\t"installdir"\t\t"TF2 Moved"\n}\n')
            self.assertEqual(self._run([str(steam)]),
                             [os.path.normpath(str(game))])

    def test_broken_install_is_not_offered(self):
        """Папка есть, игры в ней нет — предлагать нечего.

        Проверка та же, по которой работает приложение: без studiomdl.exe и
        tf2_misc_dir.vpk путь бесполезен, и «нашёл» здесь означало бы ошибку
        на первой же сборке.
        """
        with tempfile.TemporaryDirectory() as tmp:
            steam = Path(tmp) / "Steam"
            (steam / "steamapps" / "common" / "Team Fortress 2").mkdir(
                parents=True)
            self.assertEqual(self._run([str(steam)]), [])

    def test_same_game_reported_once(self):
        """Реестр и догадки дают ту же папку разным регистром.

        Для файловой системы Windows это один путь, и показывать человеку две
        одинаковые строки незачем.
        """
        with tempfile.TemporaryDirectory() as tmp:
            steam = Path(tmp) / "Steam"
            _fake_game(steam / "steamapps" / "common" / "Team Fortress 2")
            found = self._run([str(steam), str(steam).lower()])
            self.assertEqual(len(found), 1)

    def test_no_steam_no_crash(self):
        """Steam не стоит: пустой ответ, а не исключение."""
        self.assertEqual(self._run([]), [])


if __name__ == "__main__":
    unittest.main()
