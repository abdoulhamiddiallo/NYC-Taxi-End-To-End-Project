"""Repository checks, run by the CI on every push and before every deployment.

1. Regenerates the semantic model, the report, the pipelines and docs/measures.md, then fails if any committed
   file changed: the committed artefacts are always exactly what the generators produce.
2. Checks that NB_03_Deploy_Report carries the same report code as report/gen_report.py.
3. Checks that every measure and column used by the report exists in the semantic model.
4. Checks that every visual fits inside its 1600 x 900 page.
5. Checks that every relative link and image of the Markdown pages points to an existing file.
6. Checks text hygiene: UTF-8, LF line endings, no em dash, no personal file paths.
"""
import json
import pathlib
import py_compile
import re
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
REPORT = ROOT / "report" / "RPT_NYC_Taxi.Report" / "definition"
MODEL = ROOT / "semantic-model" / "SM_NYC_Taxi.SemanticModel" / "definition"
TEXT = {".py", ".sql", ".json", ".md", ".tmdl", ".pbism", ".pbir", ".yml", ".txt"}
errors = []


def run(*cmd, cwd=ROOT):
    r = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True)
    if r.returncode:
        errors.append(f"{' '.join(cmd)} failed:\n{r.stdout}{r.stderr}")
    return r


def generators():
    run(sys.executable, "semantic-model/gen_model.py")
    run(sys.executable, "gen_report.py", cwd=ROOT / "report")
    run(sys.executable, "pipelines/gen_pipelines.py")
    run(sys.executable, "tools/gen_docs.py")
    paths = ["semantic-model", "report", "pipelines", "docs/measures.md"]
    changed = subprocess.run(["git", "diff", "--name-only", "--", *paths], cwd=ROOT, capture_output=True, text=True).stdout
    new = subprocess.run(["git", "ls-files", "--others", "--exclude-standard", "--", *paths], cwd=ROOT, capture_output=True, text=True).stdout
    if (changed + new).strip():
        errors.append("generated files differ from the committed ones:\n" + changed + new)


def notebook():
    r = run(sys.executable, "tools/sync_notebook.py", "--check")
    if r.returncode == 0 and "in sync" not in r.stdout:
        errors.append(r.stdout)


def model_objects():
    tables = {}
    for f in (MODEL / "tables").glob("*.tmdl"):
        text = f.read_text(encoding="utf-8")
        name = re.match(r"table (?:'([^']+)'|(\S+))", text)
        name = name.group(1) or name.group(2)
        cols = set(re.findall(r"^\tcolumn (?:'([^']+)'|(\S+))", text, re.M))
        meas = set(re.findall(r"^\tmeasure (?:'([^']+)'|(\S+)) =", text, re.M))
        tables[name] = {a or b for a, b in cols} | {a or b for a, b in meas}
    return tables


def references():
    tables = model_objects()

    def walk(node, found):
        if isinstance(node, dict):
            if ("Column" in node or "Measure" in node) and isinstance(node.get("Column") or node.get("Measure"), dict):
                ref = node.get("Column") or node.get("Measure")
                entity = ref.get("Expression", {}).get("SourceRef", {}).get("Entity")
                if entity and "Property" in ref:
                    found.add((entity, ref["Property"]))
            for v in node.values():
                walk(v, found)
        elif isinstance(node, list):
            for v in node:
                walk(v, found)

    found = set()
    for f in REPORT.rglob("visual.json"):
        walk(json.loads(f.read_text(encoding="utf-8")), found)
    for entity, prop in sorted(found):
        if prop not in tables.get(entity, set()):
            errors.append(f"report uses {entity}[{prop}], which is not in the semantic model")
    return len(found)


def layout():
    count = 0
    for page in (REPORT / "pages").iterdir():
        if not page.is_dir():
            continue
        meta = json.loads((page / "page.json").read_text(encoding="utf-8"))
        for f in (page / "visuals").rglob("visual.json"):
            p = json.loads(f.read_text(encoding="utf-8"))["position"]
            count += 1
            if p["x"] < 0 or p["y"] < 0 or p["x"] + p["width"] > meta["width"] or p["y"] + p["height"] > meta["height"]:
                errors.append(f"{page.name}/{f.parent.name} is outside the page: {p}")
    return count


def links():
    count = 0
    for md in ROOT.rglob("*.md"):
        if ".git" in md.parts:
            continue
        for target in re.findall(r"\]\(([^)\s]+)\)", md.read_text(encoding="utf-8")):
            if re.match(r"[a-z]+:", target) or target.startswith("#"):
                continue
            count += 1
            path = (md.parent / target.split("#")[0].replace("%20", " ")).resolve()
            if not path.exists():
                errors.append(f"{md.relative_to(ROOT)} links to a missing file: {target}")
    return count


def hygiene():
    personal = re.compile(r"[A-Z]:\\Users\\|/Users/[a-z]|/home/[a-z]+/", re.I)
    files = [f for f in subprocess.run(["git", "ls-files", "-z"], cwd=ROOT, capture_output=True, text=True).stdout.split("\0") if f]
    for name in files:
        path = ROOT / name
        if not path.exists():          # deleted in the working tree, the generator check reports it
            continue
        if path.suffix.lower() not in TEXT and path.name not in {"LICENSE", ".gitignore", ".gitattributes", ".editorconfig"}:
            continue
        raw = path.read_bytes()
        try:
            text = raw.decode("utf-8")
        except UnicodeDecodeError:
            errors.append(f"{name} is not UTF-8")
            continue
        if b"\r\n" in raw:
            errors.append(f"{name} has CRLF line endings")
        if chr(0x2014) in text:
            errors.append(f"{name} contains an em dash")
        if personal.search(text):
            errors.append(f"{name} contains a personal file path")
        if path.suffix == ".py":
            try:
                py_compile.compile(str(path), doraise=True)
            except py_compile.PyCompileError as e:
                errors.append(str(e))
    return len(files)


def main():
    generators()
    notebook()
    refs = references()
    visuals = layout()
    nlinks = links()
    files = hygiene()
    if errors:
        print("\n".join("FAIL " + e for e in errors))
        return 1
    print(f"OK: generators reproducible, NB_03 in sync, {refs} model references resolved, {visuals} visuals inside their page, {nlinks} links resolved, {files} files clean")
    return 0


if __name__ == "__main__":
    sys.exit(main())
