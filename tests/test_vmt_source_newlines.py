"""Оригинал VMT из игры не должен удваивать строки при извлечении."""

from tests.fake_vpk import fake_reader, vmt


def test_extracted_vmt_keeps_single_line_breaks(tmp_path, monkeypatch):
    # В игре VMT лежат с CRLF. Запись в текстовом режиме на Windows давала
    # CR CR LF, и редактор показывал каждый файл через строку.
    from src.services import game_vpk_reader, vmt_source_service

    monkeypatch.chdir(tmp_path)
    qc = tmp_path / "model.qc"
    qc.write_text('$cdmaterials "models\\weapons\\c_models\\c_test\\"\n', encoding="utf-8")
    files = {"materials/models/weapons/c_models/c_test/c_test.vmt":
             vmt(basetexture="models/weapons/c_models/c_test/c_test", phong="1")}
    reader = fake_reader(files)      # до подмены: он сам создаёт GameVpkReader
    monkeypatch.setattr(game_vpk_reader, "GameVpkReader", lambda paths: reader)

    path = vmt_source_service._extract_from_qc(str(qc), str(tmp_path), ["c_test"])

    assert path
    with open(path, encoding="utf-8") as f:
        text = f.read()
    assert "\n\n" not in text
    assert text.splitlines()[:2] == ['"VertexLitGeneric"', "{"]
