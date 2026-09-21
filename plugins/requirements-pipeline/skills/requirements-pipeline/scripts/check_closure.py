#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Compuerta de cierre de una corrida de requisitos, por exit code y sin tokens.

Reemplaza las verificaciones que el orquestador hacia leyendo archivos en su
contexto: layout cerrado, inspecciones en verde, versiones que solo crecen y vistas
derivadas sincronizadas. Si algo falla, el cierre no procede y el script dice que.

Que verifica:
  1. Layout cerrado: en .dev/requirements/ (y .dev/plan/ si existe) no quedan
     `*delta*`, `*patch*`, archivos `_*` ni la carpeta temporal `.inc-context/`;
     ningun archivo fuera del layout definido (sources/ se acepta entera).
  2. Inspecciones en verde: cada inspeccion exigida (--inspecciones lel requirements
     design) existe, tiene `passed: true` y su `*_version_ref` cita la version
     ACTUAL del artefacto inspeccionado (una inspeccion vieja no vale).
  3. Versiones monotonas: la `version` en disco de cada artefacto es >= la ultima
     `after` registrada en changelog.json (un retroceso significa que una reescritura
     perdio el contador).
  4. Vistas derivadas: cada `.md` gemelo existe y su encabezado cita la version
     vigente del `.json` (re-correr render_baseline_docs.py si no).
  5. Ninguna entrada del changelog distinta de la corrida en curso (--corrida) queda
     en `in_progress`.
  6. Coherencia artefacto <-> artefacto: corre validate_baseline.py completo (los tres
     grupos; lo que no existe todavia se saltea) y bloquea ante cualquier defecto
     high/medium. Las inspecciones del punto 2 miran inspeccion <-> artefacto; esto
     cubre, p. ej., un data-model.json que sigue citando un requirements.json viejo
     despues de un CR.

Solo stdlib, Python 3.8+. No modifica nada.

Uso:
  python check_closure.py [carpeta] [--inspecciones lel requirements design]
                          [--corrida INC-003] [--json]
  python check_closure.py --self-test

  carpeta  por defecto .dev/requirements

Exit 0: el cierre puede proceder. Exit 1: hay bloqueos (listados).
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import validate_baseline  # noqa: E402  (hermano en la misma carpeta de scripts)

DERIVED_HEADER = re.compile(r"Derivado de `?(?P<json>[\w.-]+)`? version (?P<version>\d+)")

LAYOUT = {
    "source-inventory.json", "lel-candidates.json", "supporting-context.json",
    "lel.json", "lel.md", "lel-inspection.json", "lel-inspection.md",
    "stakeholder-questions.json", "stakeholder-questions.md", "stakeholder-answers.md",
    "product-map.json", "product-map.md", "changelog.json",
    "scenarios.json", "scenarios.md", "requirements.json", "requirements.md",
    "requirements-inspection.json", "requirements-inspection.md",
    "data-model.json", "data-model.md", "technical-design.json", "technical-design.md",
    "design-inspection.json", "design-inspection.md",
    "README.md",  # indice local que dejaron versiones anteriores del pipeline
}
DERIVED = ["lel", "product-map", "scenarios", "requirements", "data-model", "technical-design"]
INSPECTIONS = {
    "lel": ("lel-inspection.json", {"lel_version_ref": "lel.json"}),
    "requirements": ("requirements-inspection.json", {"requirements_version_ref": "requirements.json"}),
    "design": ("design-inspection.json", {"data_model_version_ref": "data-model.json",
                                          "technical_design_version_ref": "technical-design.json"}),
}


def load(path):
    try:
        return json.loads(path.read_text(encoding="utf-8-sig")) if path.is_file() else None
    except (ValueError, OSError):
        return "ILEGIBLE"


def run(folder, inspections, corrida, as_json=False, quiet=False):
    folder = Path(folder)
    problems = []
    warnings = []

    def bad(msg):
        problems.append(msg)

    # 1. layout
    for sub in (folder, folder.parent / "plan"):
        if not sub.is_dir():
            continue
        for p in sub.rglob("*"):
            rel = p.relative_to(sub)
            name = p.name
            if p.is_dir() and name in (".inc-context", ".brief-context"):
                bad("carpeta temporal sin borrar: %s (correr el script de slice con --limpiar)" % p)
            if p.is_file() and ("delta" in name or "patch" in name or name.startswith("_")):
                bad("archivo de trabajo sin mergear/borrar: %s" % p)
    for p in folder.iterdir():
        if p.is_dir():
            if p.name not in ("sources", ".inc-context", "increments"):
                bad("carpeta fuera del layout: %s" % p)
            continue
        if p.name not in LAYOUT:
            bad("archivo fuera del layout cerrado: %s" % p)

    # 2. inspecciones
    for key in inspections:
        fname, refs = INSPECTIONS[key]
        doc = load(folder / fname)
        if doc is None:
            bad("falta %s (la inspeccion no corrio)" % fname)
            continue
        if doc == "ILEGIBLE":
            bad("%s no parsea" % fname)
            continue
        if doc.get("passed") is not True:
            bad("%s tiene passed=%r: volver al lazo de correccion" % (fname, doc.get("passed")))
        for ref, target in refs.items():
            tdoc = load(folder / target)
            if isinstance(tdoc, dict) and str(doc.get(ref)) != str(tdoc.get("version")):
                bad("%s cita %s=%s pero %s esta en version %s: la inspeccion es vieja"
                    % (fname, ref, doc.get(ref), target, tdoc.get("version")))

    # 3. versiones monotonas + 5. in_progress
    changelog = load(folder / "changelog.json")
    if isinstance(changelog, dict):
        last_after = {}
        for e in changelog.get("entries") or []:
            for art, v in (e.get("artifact_versions") or {}).items():
                try:
                    last_after[art] = max(last_after.get(art, 0), int(v.get("after") or 0))
                except (TypeError, ValueError, AttributeError):
                    pass
            if e.get("status") == "in_progress" and e.get("id") != corrida:
                bad("entrada %s del changelog sigue in_progress (corrida interrumpida sin cerrar)" % e.get("id"))
        for art, after in sorted(last_after.items()):
            doc = load(folder / art)
            if isinstance(doc, dict):
                try:
                    cur = int(doc.get("version") or 0)
                except (TypeError, ValueError):
                    cur = 0
                if cur < after:
                    bad("%s esta en version %s pero el changelog registro %s: el contador retrocedio" % (art, cur, after))
    elif changelog == "ILEGIBLE":
        bad("changelog.json no parsea")

    # 4. vistas derivadas
    for name in DERIVED:
        doc = load(folder / ("%s.json" % name))
        if not isinstance(doc, dict):
            continue
        md = folder / ("%s.md" % name)
        if not md.is_file():
            bad("vista derivada ausente: %s.md (correr render_baseline_docs.py)" % name)
            continue
        m = DERIVED_HEADER.search(md.read_text(encoding="utf-8-sig")[:600])
        if not m or m.group("version") != str(doc.get("version")):
            bad("%s.md desincronizado de %s.json version %s (correr render_baseline_docs.py)" % (name, name, doc.get("version")))

    # 6. coherencia entre artefactos (validate_baseline completo)
    _, found = validate_baseline.run_checks(folder, list(validate_baseline.GROUPS), False, quiet=True)
    for d in found:
        msg = "validate_baseline [%s][%s] %s: %s (rebota a %s)" % (
            d["check_id"], d["severity"], d["target_id"], d["description"], d["bounce"])
        if d["severity"] in ("high", "medium"):
            bad(msg)
        else:
            warnings.append(msg)

    if not quiet:
        if as_json:
            print(json.dumps({"ok": not problems, "problems": problems, "warnings": warnings}, ensure_ascii=False, indent=2))
        else:
            for p in problems:
                print("BLOQUEO: %s" % p)
            for w in warnings:
                print("aviso: %s" % w)
            print("CIERRE BLOQUEADO: %d problema(s)." % len(problems) if problems else "Cierre OK: layout cerrado, inspecciones en verde, versiones, vistas y baseline coherentes.")
    return (1 if problems else 0), problems


def self_test():
    import shutil
    import tempfile
    failures = 0

    def check(cond, label):
        nonlocal failures
        print("self-test %s: %s" % ("ok" if cond else "FALLO", label))
        if not cond:
            failures += 1

    tmp = Path(tempfile.mkdtemp(prefix="check-closure-")) / ".dev" / "requirements"
    tmp.mkdir(parents=True)
    try:
        w = lambda name, doc: (tmp / name).write_text(json.dumps(doc), encoding="utf-8")
        md = lambda name, v: (tmp / ("%s.md" % name)).write_text("# x\n\n> Derivado de `%s.json` version %s — no editar a mano.\n" % (name, v), encoding="utf-8")
        w("requirements.json", {"version": 4})
        md("requirements", 4)
        w("requirements-inspection.json", {"passed": True, "requirements_version_ref": "4"})
        w("changelog.json", {"entries": [{"id": "INC-001", "status": "applied", "artifact_versions": {"requirements.json": {"before": "3", "after": "4"}}},
                                         {"id": "INC-002", "status": "in_progress"}]})
        code, probs = run(tmp, ["requirements"], "INC-002", quiet=True)
        check(code == 0, "fixture consistente pasa: %s" % probs)

        # un CR sube requirements.json y el diseno sigue citando la version vieja:
        # las inspecciones pueden estar al dia y aun asi la baseline es incoherente
        w("data-model.json", {"version": 1, "metadata": {"requirements_version_ref": "2"}, "entities": []})
        md("data-model", 1)
        code, probs = run(tmp, ["requirements"], "INC-002", quiet=True)
        check(code == 1 and any("DB-CHECK-010" in p for p in probs),
              "detecta version ref vieja entre artefactos (validate_baseline): %s" % probs)
        (tmp / "data-model.json").unlink()
        (tmp / "data-model.md").unlink()

        md("requirements", 3)                                             # vista vieja
        (tmp / "scenarios.FG-01.delta.json").write_text("{}", encoding="utf-8")   # delta sin mergear
        w("requirements-inspection.json", {"passed": True, "requirements_version_ref": "3"})  # inspeccion vieja
        w("requirements.json", {"version": 2})                            # retroceso
        (tmp / "notas.txt").write_text("x", encoding="utf-8")            # fuera del layout
        code, probs = run(tmp, ["requirements", "design"], "INC-002", quiet=True)
        check(code == 1, "fixture rota bloquea")
        text = " | ".join(probs)
        for needle in ("delta", "fuera del layout", "inspeccion es vieja", "retrocedio", "desincronizado", "falta design-inspection.json"):
            check(needle in text, "detecta '%s'" % needle)
    finally:
        shutil.rmtree(tmp.parent.parent, ignore_errors=True)
    print("SELF-TEST: %d fallo(s)" % failures)
    return 1 if failures else 0


def main(argv):
    if "--self-test" in argv:
        return self_test()
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("carpeta", nargs="?", default=".dev/requirements")
    ap.add_argument("--inspecciones", nargs="*", choices=sorted(INSPECTIONS), default=[], help="inspecciones que deben estar en verde")
    ap.add_argument("--corrida", default=None, help="id de la corrida en curso (se permite in_progress)")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)
    folder = Path(args.carpeta)
    if not folder.is_dir():
        print("No existe la carpeta: %s" % folder)
        return 1
    code, _ = run(folder, args.inspecciones, args.corrida, args.json)
    return code


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
