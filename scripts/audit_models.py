"""
Аудит детекта моделей: для каждой модели оружия/персонажа/снаряда/пикапа/насмешки
определяет, что приложение «думает» про неё —
  • сколько будет карточек материалов (editable_material_cards по мешу),
  • нужен ли переключатель команд RED/BLU (layout.blu_is_team),
  • есть ли австралий/вариант (pick_preview_variant),
и помечает подозрительные случаи (ложный австралий, команда при 1 материале и т.п.).

Запуск:
  python scripts/audit_models.py            # все модели (декомпилирует недостающие)
  python scripts/audit_models.py --cached   # только уже декомпилированные (быстро)

Результат печатается и пишется в scripts/audit_report.tsv.
"""
import os
import sys
import glob

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from src.config.app_config import AppConfig
from src.data.weapons import TF2_WEAPONS
from src.data.projectiles import PROJECTILES
from src.data.pickups import PICKUPS
from src.data.taunt_props import TAUNT_PROPS
from src.data.player_characters import PLAYER_CHARACTERS
from src.services import decompile_cache
from src.services.smd_service import SMDService
from src.ui.material_cards import editable_material_cards
from src.services import qc_skin_parser as qsp

CACHED_ONLY = "--cached" in sys.argv


def targets():
    """[(label, weapon_key, mode)] всех анализируемых моделей."""
    out = []
    for cls, slots in TF2_WEAPONS.items():
        for slot, items in slots.items():
            if slot in ("Hands", "PlayerSkin"):
                continue
            for wkey in items:
                out.append((f"weapon/{cls}/{wkey}", wkey, f"scout_{wkey}"))
    for key, d in PLAYER_CHARACTERS.items():
        out.append((f"body/{key}", d["mdl_path"], key))
    for key in PROJECTILES:
        out.append((f"projectile/{key}", key, f"scout_{key}"))
    for key in PICKUPS:
        out.append((f"pickup/{key}", key, f"scout_{key}"))
    for key in TAUNT_PROPS:
        out.append((f"taunt/{key}", key, f"scout_{key}"))
    # уберём дубли weapon_key (одно оружие у нескольких классов)
    seen, uniq = set(), []
    for label, wkey, mode in out:
        if wkey in seen:
            continue
        seen.add(wkey)
        uniq.append((label, wkey, mode))
    return uniq


def find_qc(tf2_root, wkey, mode):
    """QC-путь: сперва кэш, иначе декомпиляция (если не --cached)."""
    qc = decompile_cache.find_cached_qc_for_weapon(wkey)
    if qc:
        return qc, os.path.dirname(qc)
    if CACHED_ONLY:
        return None, None
    from src.services.extract_model_service import ExtractModelService
    ok, msg, _, data = ExtractModelService.prepare_decompiled_model_files_with_progress(
        tf2_root, mode, wkey, language="en"
    )
    if not ok or not data:
        return None, None
    ddir = data.get("decompile_dir")
    if not ddir:
        return None, None
    qcs = glob.glob(os.path.join(ddir, "*.qc"))
    return (qcs[0], ddir) if qcs else (None, ddir)


def analyze(label, wkey, mode, tf2_root):
    qc, ddir = find_qc(tf2_root, wkey, mode)
    row = {"label": label, "key": wkey, "cols": 0, "skins": 0,
           "team": "", "variant": "", "styles": "", "mats": 0, "cards": 0, "note": ""}
    if not qc:
        row["note"] = "нет QC (не в кэше)" if CACHED_ONLY else "декомпиляция не удалась"
        return row
    layout = qsp.parse_skin_layout(qc)
    rows = layout.all_rows or []
    row["cols"] = max((len(r) for r in rows), default=0)
    row["skins"] = len(layout.unique_base_rows or rows)
    # Единый авторитет селекторов (как будет видеть UI после унификации).
    spec = qsp.selector_spec(layout)
    row["team"] = "TEAM" if spec.team else ""
    row["variant"] = spec.variant or ""
    row["styles"] = ",".join(lbl for lbl, _ in spec.styles)

    smd = None
    try:
        smd = SMDService.find_reference_smd(ddir, os.path.basename(wkey).replace(".mdl", ""))
    except Exception:
        pass
    if smd:
        try:
            mats = SMDService.ordered_unique_materials(smd)
            row["mats"] = len(mats)
            row["cards"] = len(editable_material_cards(mats))
        except Exception:
            row["note"] = "SMD прочитать не удалось"
    else:
        row["note"] = "reference SMD не найден"

    # подозрительные эвристики
    flags = []
    base = os.path.basename(wkey).lower()
    if row["variant"] == "festive" and base.endswith("_xmas"):
        flags.append("ЛОЖНЫЙ festive (натив-xmas)")
    if row["team"] and row["cards"] and row["cards"] <= 1 and row["cols"] <= 1:
        flags.append("команда при 1 материале")
    if flags:
        row["note"] = (row["note"] + "; " if row["note"] else "") + "; ".join(flags)
    return row


def main():
    tf2_root = AppConfig.load_config().get("tf2_game_folder", "")
    tgts = targets()
    print(f"Моделей к проверке: {len(tgts)} | режим: {'кэш' if CACHED_ONLY else 'полный'}")
    out_path = os.path.join(os.path.dirname(__file__), "audit_report.tsv")
    rows = []
    susp = []
    done = 0
    with open(out_path, "w", encoding="utf-8") as f:
        f.write("label\tkey\tcols\tskins\tteam\tvariant\tstyles\tmats\tcards\tnote\n")
        for label, wkey, mode in tgts:
            r = analyze(label, wkey, mode, tf2_root)
            f.write("\t".join(str(r[k]) for k in
                    ["label", "key", "cols", "skins", "team", "variant", "styles", "mats", "cards", "note"]) + "\n")
            f.flush()
            rows.append(r)
            done += 1
            if r["variant"] or r["styles"] or "ЛОЖНЫЙ" in r["note"] or "команда при" in r["note"]:
                susp.append(r)
            if done % 25 == 0:
                print(f"  ...{done}/{len(tgts)}")

    analyzed = [r for r in rows if not r["note"].startswith(("нет QC", "декомпиляция"))]
    print(f"\nПроанализировано: {len(analyzed)} / {len(rows)}")
    print(f"С командой (TEAM): {sum(1 for r in analyzed if r['team'])}")
    print(f"С вариантом (австралий/festive/...): {sum(1 for r in analyzed if r['variant'])}")
    print(f"Со стилями (bloody/clean/...): {sum(1 for r in analyzed if r['styles'])}")
    print(f"\n=== ВАРИАНТЫ / СТИЛИ / ПОДОЗРИТЕЛЬНОЕ ({len(susp)}) ===")
    for r in susp:
        print(f"  {r['label']:<34} cards={r['cards']} team={r['team'] or '-':<4} "
              f"variant={r['variant'] or '-':<10} styles=[{r['styles']}] {r['note']}")
    print(f"\nПолный отчёт: {out_path}")


if __name__ == "__main__":
    main()
