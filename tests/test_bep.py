"""Smoke tests for the BEP Builder CLI, checkers, and app parity.

Run:  python tests/test_bep.py      (or: pytest tests/)
Needs openpyxl for the workbook round trip; Node.js (optional) for app/CLI parity.
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CLI = ROOT / "skills/bep-builder-cli/scripts"
NCS = ROOT / "skills/national-cad-standard/scripts"
NUM = ROOT / "skills/ios-numbers-spreadsheets/scripts"
sys.path[:0] = [str(CLI), str(NCS)]

import iso13567  # noqa: E402
import check_names  # noqa: E402


def bep(*args, cwd=None):
    r = subprocess.run([sys.executable, str(CLI / "bep.py"), *map(str, args)], capture_output=True, text=True, cwd=cwd)
    return r.returncode, r.stdout + r.stderr


def test_ncs_names():
    assert check_names.check_layer("A-WALL-FULL") == []
    assert check_names.check_layer("A-WALL-D") == []
    assert check_names.check_layer("a-wall")
    assert check_names.check_layer("A_WALL")
    assert check_names.check_layer("A-WALL-FULL-Q")
    assert check_names.check_layer("A-WALL-2", "status")
    assert check_names.check_sheet("A-101") == [] and check_names.check_sheet("AD101") == []
    assert check_names.check_sheet("S501") and check_names.check_sheet("A-100") and check_names.check_sheet("AD-101")


def test_iso13567_profile():
    p = iso13567.Profile(1, "element", "status")
    assert iso13567.check("A-WALL-FULL-TEXT-N", p) == []
    assert iso13567.check("A-WALL-____-____-N", p) == []
    assert iso13567.check("G-ANNO-TEXT-N", p)            # ANNO banned
    assert iso13567.check("A-TEXT-____-____-N", p)       # annotation code as element
    assert iso13567.check("A-WALL-FULL-TEXT-2", p)       # phase in a status project
    assert iso13567.convert("G-ANNO-TTLB-N", p, None, "SHET")[0] == "G-SHET-____-TTLB-N"
    assert iso13567.convert("A-ANNO-DIMS", p, None, "SHET")[0] is None   # element annotation needs a person
    assert iso13567.convert("A-WALL-FULL-D", p)[0] == "A-WALL-FULL-____-D"
    v = iso13567.Profile(1, "view", "phase")
    assert iso13567.check("A-WALL-ELEV-TEXT-2", v) == []
    assert iso13567.check("A-WALL-FULL-TEXT-2", v)


def test_cli_plan_lifecycle():
    d = Path(tempfile.mkdtemp())
    try:
        assert bep("init", d / "p.json", "--agency", "usace")[0] == 0
        assert bep("set", d / "p.json", "project.cui", "maybe")[0] != 0       # validated
        assert bep("use", d / "p.json", "coord", "--party", "BIM manager")[0] == 0
        code, out = bep("validate", d / "p.json", "--strict")
        assert code == 1 and "TODO items" in out
        code, out = bep("export", d / "p.json")
        assert code == 0 and "USACE / DoD overrides" in out and "```mermaid" in out
        plan = json.loads((d / "p.json").read_text())
        assert plan["standards"]["sheetCode"] == "SHET" and plan["standards"]["iso13567"] is False
    finally:
        shutil.rmtree(d)


def test_process_map_example():
    code, out = bep("process-map", ROOT / "examples/example-plan.json")
    assert code == 0
    assert 'u_authoring -->|"Coordination model · LOD 300 · Weekly"| u_coord' in out
    assert "stub_construction" in out                                  # skipped phase gets a placeholder
    assert 'stub_construction -->|"COBie handover · LOD 500 data · Closeout"| u_cobie' in out


def test_maps_workbook_round_trip():
    try:
        from openpyxl import load_workbook
    except ImportError:
        print("  (skipped: openpyxl not installed)")
        return
    d = Path(tempfile.mkdtemp())
    try:
        shutil.copy(ROOT / "examples/example-plan.json", d / "p.json")
        assert bep("maps-workbook", d / "p.json", "-o", d / "maps.xlsx")[0] == 0
        code, out = bep("apply-maps", d / "p.json", d / "maps.xlsx")
        assert code == 0 and "No changes" in out                       # untouched workbook = no-op
        wb = load_workbook(d / "maps.xlsx")
        ws = wb["Uses"]
        for row in ws.iter_rows(min_row=2):
            if row[2].value == "Phase planning (4D)":
                row[4].value, row[5].value = "Y", "Contractor VDC lead"
        wb.save(d / "edited.xlsx")
        code, out = bep("apply-maps", d / "p.json", d / "edited.xlsx")
        assert code == 0 and "Selected Phase planning (4D)" in out
        plan = json.loads((d / "p.json").read_text())
        assert plan["uses"]["4d"]["on"] and plan["uses"]["4d"]["party"] == "Contractor VDC lead"
        assert "No changes" in bep("apply-maps", d / "p.json", d / "edited.xlsx")[1]   # idempotent
        diff = subprocess.run([sys.executable, str(NUM / "diff_tables.py"), d / "maps.xlsx", d / "edited.xlsx",
                               "--key", "Uses=Project,BIM use"], capture_output=True, text=True).stdout
        assert "Phase planning (4D) | Selected (Y/N) | N | Y" in diff
    finally:
        shutil.rmtree(d)


def test_app_matches_cli():
    node = shutil.which("node")
    if not node:
        print("  (skipped: Node.js not installed)")
        return
    html = (ROOT / "app/index.html").read_text()
    js = html.split("<script>")[1].split("</script>")[0].split("/* ---------- Events ---------- */")[0]
    plan = json.loads((ROOT / "examples/example-plan.json").read_text())
    names = ["A-WALL-FULL-TEXT-N", "G-ANNO-TEXT-N", "A-TEXT-____-____-N", "G-ANNO-TTLB-N", "A-ANNO-DIMS", "A-WALL-FULL-D"]
    harness = js + f"""
plan = normalize({json.dumps(plan)});
const p = profileFor();
const out = {{ map: mapToMermaid(buildMap()), iso: {json.dumps(names)}.map(n => [isoCheck(n, p).length === 0, isoConvert(n, p, null, "SHET")[0]]) }};
console.log(JSON.stringify(out));
"""
    with tempfile.NamedTemporaryFile("w", suffix=".js", delete=False) as fh:
        fh.write(harness)
    try:
        r = subprocess.run([node, fh.name], capture_output=True, text=True)
        assert r.returncode == 0, r.stderr
        app = json.loads(r.stdout)
    finally:
        os.unlink(fh.name)
    assert app["map"] == bep("process-map", ROOT / "examples/example-plan.json")[1]
    prof = iso13567.Profile(1, "element", "status")
    assert app["iso"] == [[iso13567.check(n, prof) == [], iso13567.convert(n, prof, None, "SHET")[0]] for n in names]


if __name__ == "__main__":
    failed = 0
    for name, fn in [(k, v) for k, v in dict(globals()).items() if k.startswith("test_") and callable(v)]:
        try:
            fn()
            print(f"PASS {name}")
        except AssertionError as e:
            failed += 1
            print(f"FAIL {name}: {e}")
    sys.exit(1 if failed else 0)
