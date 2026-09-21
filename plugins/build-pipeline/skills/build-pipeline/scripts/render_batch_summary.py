#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Resumen consolidado de un lote (o de una feature), derivado de los artefactos.

El orquestador no retiene en contexto los veredictos de N features para redactar el
resumen final: este script lee `progress.json`, `execution-plan.json`, los briefs,
`reviews/`, `security/`, `verification/`, `desvios/`, `cr-input-*.md`, `tech-debt.md` y
`.dev/manual/` y emite el Markdown del resumen. El orquestador lo muestra tal cual y
solo agrega el proximo paso. Cierra con los worktrees `../{repo}-wt-*` que siguen en
pie (de `cleanup_worktrees.py`): si la limpieza del lote no corrio, se ve aca.

Uso:
  python render_batch_summary.py <raiz> [--lote BATCH-2] [--features FG-01 FG-02] [--json]
  python render_batch_summary.py --self-test

Sin --lote ni --features resume todas las features que no esten en pending.
Solo stdlib. No modifica nada. Exit 0; 2 en error de uso.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import cleanup_worktrees  # noqa: E402  (hermano en la misma carpeta de scripts)


def load(path):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8-sig"))
    except (OSError, ValueError):
        return None


def brief_index(root):
    """FG-xx -> brief_basename, por el nombre de archivo de .dev/features/."""
    idx = {}
    featdir = root / ".dev" / "features"
    if featdir.is_dir():
        for p in sorted(featdir.glob("FG-*.md")):
            m = re.match(r"^(FG-\d+)", p.stem)
            if m:
                idx[m.group(1)] = p.stem
    return idx


def manual_index(root):
    """FG-xx -> ruta de la guia, por el frontmatter `fg`."""
    idx = {}
    manual = root / ".dev" / "manual"
    if manual.is_dir():
        for p in manual.glob("*.md"):
            if p.name.lower() == "readme.md":
                continue
            head = p.read_text(encoding="utf-8")[:600]
            m = re.search(r"^fg:\s*(FG-\d+)", head, flags=re.MULTILINE)
            if m:
                idx[m.group(1)] = ".dev/manual/" + p.name
    return idx


def select_features(root, lote, features):
    progress = load(root / ".dev" / "plan" / "progress.json") or {}
    plan = load(root / ".dev" / "plan" / "execution-plan.json") or {}
    if features:
        chosen = list(features)
    elif lote:
        chosen = []
        for b in plan.get("batches") or []:
            if b.get("id") == lote:
                chosen = [f.get("feature_id") for f in b.get("features") or []]
    else:
        chosen = [f["feature_id"] for f in progress.get("features") or [] if f.get("status") != "pending"]
    return chosen, progress


def collect(root, lote=None, features=None):
    chosen, progress = select_features(root, lote, features)
    build = root / ".dev" / "build"
    briefs = brief_index(root)
    manuals = manual_index(root)
    pfeat = {f.get("feature_id"): f for f in progress.get("features") or []}
    ptasks = progress.get("tasks") or []
    out = []
    for fid in chosen:
        brief = briefs.get(fid, fid)
        review = load(build / "reviews" / (brief + ".json"))
        gate = load(build / "security" / (brief + ".json"))
        verification = load(build / "verification" / (brief + ".json"))
        desvios = load(build / "desvios" / (brief + ".json")) or {}
        tasks = [t for t in ptasks if t.get("feature_id") == fid]
        entry = {
            "feature_id": fid,
            "brief": brief,
            "status": (pfeat.get(fid) or {}).get("status", "desconocido"),
            "branch": (pfeat.get(fid) or {}).get("branch", ""),
            "notes": (pfeat.get(fid) or {}).get("notes", ""),
            "tasks": {"done": [t["task_id"] for t in tasks if t.get("status") == "done"],
                      "blocked": [t["task_id"] for t in tasks if t.get("status") == "blocked"],
                      "otras": [t["task_id"] for t in tasks if t.get("status") not in ("done", "blocked")]},
            "review": None, "gate": None, "verification": None,
            "desvios": desvios.get("desvios") or [],
            "cr_input": ".dev/build/cr-input-%s.md" % brief if (build / ("cr-input-%s.md" % brief)).is_file() else None,
            "guia": manuals.get(fid),
            "low_findings": [],
        }
        if review:
            s = review.get("summary") or {}
            entry["review"] = {
                "passed": review.get("passed"), "version": review.get("version"),
                "high": s.get("high", 0), "medium": s.get("medium", 0), "low": s.get("low", 0),
                "tests_passed": s.get("tests_passed"), "lint_passed": s.get("lint_passed"),
                "tasks_missing": s.get("tasks_missing") or [],
                "closure": [{"id": rc.get("requirement_id"), "missing": rc.get("criteria_missing") or []}
                            for rc in review.get("requirements_closure") or []],
                "open": [(f.get("id"), f.get("severity"), (f.get("description") or "")[:90])
                         for f in review.get("findings") or [] if f.get("severity") in ("high", "medium")],
            }
            entry["low_findings"] += [f.get("id") for f in review.get("findings") or [] if f.get("severity") == "low"]
        if gate:
            s = gate.get("summary") or {}
            entry["gate"] = {
                "passed": gate.get("passed"), "version": gate.get("version"),
                "high": s.get("high", 0), "medium": s.get("medium", 0), "low": s.get("low", 0),
                "audit_run": s.get("dependency_audit_run"), "audit_passed": s.get("dependency_audit_passed"),
                "deferred": gate.get("deferred_to_audit") or [],
                "open": [(f.get("id"), f.get("severity"), (f.get("description") or "")[:90])
                         for f in gate.get("findings") or [] if f.get("severity") in ("high", "medium")],
            }
            entry["low_findings"] += [f.get("id") for f in gate.get("findings") or [] if f.get("severity") == "low"]
        if verification:
            c = verification.get("commands") or {}
            entry["verification"] = {k: (v or {}).get("passed") for k, v in c.items()}
            entry["verification"]["passed"] = verification.get("passed")
        out.append(entry)
    return out


def _pr_from_notes(notes):
    m = re.search(r"(PR\s*#?\d+|https?://\S+/pull/\d+)", notes or "")
    return m.group(1) if m else None


def render(entries, lote=None):
    lines = ["# Resumen del %s" % (lote or "build"), ""]
    if not entries:
        lines.append("_Sin features para resumir._")
        return "\n".join(lines) + "\n"
    ok = [e for e in entries if e["review"] and e["gate"] and e["review"]["passed"] and e["gate"]["passed"]]
    blocked = [e for e in entries if "BLOQUEADA" in (e["notes"] or "") or e["tasks"]["blocked"]]
    lines.append("- Features: %d | con review y gate en verde: %d | bloqueadas: %d" % (len(entries), len(ok), len(blocked)))
    lines.append("")
    for e in entries:
        pr = _pr_from_notes(e["notes"])
        lines.append("## %s (%s) — %s%s" % (e["feature_id"], e["brief"], e["status"], (" — " + pr) if pr else ""))
        lines.append("")
        t = e["tasks"]
        lines.append("- **Tareas**: %d done%s%s" % (
            len(t["done"]),
            (", bloqueadas: " + ", ".join(t["blocked"])) if t["blocked"] else "",
            (", sin cerrar: " + ", ".join(t["otras"])) if t["otras"] else ""))
        r = e["review"]
        if r:
            missing = [c["id"] + " (faltan " + ", ".join(c["missing"]) + ")" for c in r["closure"] if c["missing"]]
            closed = [c["id"] for c in r["closure"] if not c["missing"]]
            lines.append("- **Review** v%s: %s — high %d, medium %d, low %d; tests %s, lint %s%s" % (
                r["version"], "PASSED" if r["passed"] else "FAILED", r["high"], r["medium"], r["low"],
                r["tests_passed"], r["lint_passed"],
                ("; tareas sin cubrir: " + ", ".join(r["tasks_missing"])) if r["tasks_missing"] else ""))
            lines.append("- **Cierre por requisito**: cerrados %s%s" % (
                ", ".join(closed) or "ninguno", ("; sin cerrar: " + "; ".join(missing)) if missing else ""))
            for fid, sev, desc in r["open"]:
                lines.append("  - abierto %s [%s]: %s" % (fid, sev, desc))
        else:
            lines.append("- **Review**: sin veredicto")
        g = e["gate"]
        if g:
            lines.append("- **Seguridad** v%s: %s — high %d, medium %d, low %d; audit de dependencias %s" % (
                g["version"], "PASSED" if g["passed"] else "FAILED", g["high"], g["medium"], g["low"],
                ("no corrido" if not g["audit_run"] else ("ok" if g["audit_passed"] else "con vulnerabilidades"))))
            for fid, sev, desc in g["open"]:
                lines.append("  - abierto %s [%s]: %s" % (fid, sev, desc))
            for d in g["deferred"]:
                lines.append("  - derivado a /auditar: %s" % d)
        else:
            lines.append("- **Seguridad**: sin veredicto")
        if e["verification"]:
            v = e["verification"]
            lines.append("- **Verificacion (script)**: test %s, lint %s, audit %s" % (
                v.get("test"), v.get("lint"), v.get("dependency_audit")))
        if e["desvios"]:
            lines.append("- **Desvios del brief**: %d (%s)%s" % (
                len(e["desvios"]), ", ".join(d.get("id", "?") for d in e["desvios"]),
                (" -> `/requerimientos:cambio %s`" % e["cr_input"]) if e["cr_input"] else ""))
        if e["low_findings"]:
            lines.append("- **Hallazgos low (tech-debt.md)**: %s" % ", ".join(e["low_findings"]))
        if e["guia"]:
            lines.append("- **Guia de usuario**: %s" % e["guia"])
        else:
            m = re.search(r"SIN GUIA:\s*([^|]+)", e["notes"] or "")
            lines.append("- **Guia de usuario**: no generada%s" % ((" — " + m.group(1).strip()) if m else ""))
        if "BLOQUEADA" in (e["notes"] or ""):
            m = re.search(r"BLOQUEADA:\s*([^|]+)", e["notes"])
            lines.append("- **BLOQUEADA**: %s (rama `%s`; retomar con /construir-lote)" % (m.group(1).strip() if m else "", e["branch"]))
        lines.append("")
    return "\n".join(lines)


def worktrees_section(root):
    items = cleanup_worktrees.inventory(root)
    if items is None:
        return ""
    lines = ["## Worktrees en pie", ""]
    if not items:
        return "\n".join(lines + ["Ninguno.", ""])
    pending = [i for i in items if i["decision"] == "remove"]
    for it in items:
        lines.append("- `%s`%s — %s" % (Path(it["path"]).name, (" (%s)" % it["branch"]) if it["branch"] else "", it["reason"]))
    if pending:
        lines += ["", "**%d sin limpiar**: correr `cleanup_worktrees.py <raiz> --aplicar`." % len(pending)]
    return "\n".join(lines + [""])


# ------------------------------------------------------------------ self-test

def self_test():
    import shutil
    import tempfile

    tmp = Path(tempfile.mkdtemp(prefix="batch-summary-"))
    failures = 0
    try:
        dev = tmp / ".dev"
        (dev / "features").mkdir(parents=True)
        (dev / "plan").mkdir()
        (dev / "build" / "reviews").mkdir(parents=True)
        (dev / "build" / "security").mkdir()
        (dev / "manual").mkdir()
        (dev / "features" / "FG-01-alta.md").write_text("# brief", encoding="utf-8")
        (dev / "features" / "FG-02-carrito.md").write_text("# brief", encoding="utf-8")
        (dev / "plan" / "execution-plan.json").write_text(json.dumps({"batches": [
            {"id": "BATCH-1", "features": [{"feature_id": "FG-01"}, {"feature_id": "FG-02"}]}]}), encoding="utf-8")
        (dev / "plan" / "progress.json").write_text(json.dumps({
            "features": [{"feature_id": "FG-01", "status": "in_progress", "branch": "feature/alta", "notes": "PR #7"},
                         {"feature_id": "FG-02", "status": "in_progress", "branch": "feature/carrito", "notes": "BLOQUEADA: migracion falla"}],
            "tasks": [{"task_id": "T-001", "feature_id": "FG-01", "status": "done"},
                      {"task_id": "T-002", "feature_id": "FG-02", "status": "blocked"}]}), encoding="utf-8")
        (dev / "build" / "reviews" / "FG-01-alta.json").write_text(json.dumps({
            "version": 2, "passed": True, "summary": {"high": 0, "medium": 0, "low": 1, "tests_passed": True, "lint_passed": True},
            "requirements_closure": [{"requirement_id": "RF-001", "criteria_missing": []}],
            "findings": [{"id": "FG-01/FIND-002", "severity": "low"}]}), encoding="utf-8")
        (dev / "build" / "security" / "FG-01-alta.json").write_text(json.dumps({
            "version": 1, "passed": True, "summary": {"high": 0, "medium": 0, "low": 0, "dependency_audit_run": True, "dependency_audit_passed": True},
            "findings": [], "deferred_to_audit": ["revisar flujo de tokens"]}), encoding="utf-8")
        (dev / "manual" / "alta.md").write_text("---\nfeature: alta\nfg: FG-01\ntitulo: Alta\n---\n", encoding="utf-8")
        entries = collect(tmp, lote="BATCH-1")
        md = render(entries, "BATCH-1")
        checks = ["PR #7" in md, "BLOQUEADA**: migracion falla" in md, "FG-01/FIND-002" in md,
                  "derivado a /auditar" in md, ".dev/manual/alta.md" in md, "sin veredicto" in md,
                  "cerrados RF-001" in md]
        if all(checks):
            print("self-test ok (resumen de lote con %d features)" % len(entries))
        else:
            print("SELF-TEST FALLO: %s\n%s" % (checks, md))
            failures += 1
        if worktrees_section(tmp) != "":
            print("SELF-TEST FALLO: seccion de worktrees fuera de un repo git")
            failures += 1
        else:
            print("self-test ok (sin repo git no hay seccion de worktrees)")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    return 1 if failures else 0


# ------------------------------------------------------------------------ main

def main(argv):
    if "--self-test" in argv:
        return self_test()
    root = None
    lote = None
    features = []
    as_json = "--json" in argv
    i = 0
    while i < len(argv):
        a = argv[i]
        if a == "--lote":
            i += 1
            lote = argv[i]
        elif a == "--features":
            i += 1
            while i < len(argv) and not argv[i].startswith("--"):
                features.append(argv[i])
                i += 1
            continue
        elif a == "--json":
            pass
        elif a.startswith("--"):
            print("error: opcion desconocida %s" % a)
            return 2
        else:
            root = a
        i += 1
    if not root:
        print(__doc__)
        return 2
    entries = collect(Path(root), lote, features)
    if as_json:
        print(json.dumps(entries, ensure_ascii=False, indent=2))
    else:
        print(render(entries, lote))
        section = worktrees_section(Path(root))
        if section:
            print(section)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
