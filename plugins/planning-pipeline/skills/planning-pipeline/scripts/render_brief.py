#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Render determinista de los briefs de feature: tajada JSON -> .dev/features/FG-xx-{slug}.md

Reemplaza al subagente `feature-brief` en todo lo que es proyeccion de campos: el
brief es, en un 90%, la tajada de `slice_brief_context.py` reescrita como Markdown.
Este script emite el brief completo (todas las secciones que el linter de
`validate_plan.py --briefs` exige) sin tokens de modelo; el subagente `feature-brief`
(haiku) solo completa despues las dos partes que requieren redaccion: el resumen en
prosa y la superficie OWASP de la seccion Seguridad, marcadas con `<!-- LLM: ... -->`.

Secciones del brief (mismo contrato que antes):
  1 Titulo y resumen      6 Seguridad (requisitos/ADRs/API con auth + piso del stack)
  2 Requisitos + BR       7 Contratos (produce / consume)
  3 Plan de ejecucion     8 Lote de ejecucion
  4 Criterios (+ cierre)  9 Dependencias entre features
  5 Diseno relevante     10 Trazabilidad y vocabulario

Nombre de archivo: `FG-xx-{slug}.md` con el slug kebab-case del nombre de la feature.
Es ESTABLE: si ya existe un brief de esa FG-xx se reutiliza su nombre aunque la
feature se haya renombrado (los agentes de build derivan el nombre del veredicto).

Solo stdlib, Python 3.8+. Lee las tajadas de `.dev/plan/.brief-context/`; no toca
los artefactos canonicos.

Uso:
  python render_brief.py [raiz] [--features FG-01 FG-02] [--cambio INC-002]
  python render_brief.py --self-test

  --cambio   en replanificacion: entradas del changelog que motivaron la regeneracion
             (se citan en la linea de actualizacion del brief)

Exit 0 con los briefs escritos; exit 1 si falta la carpeta de tajadas o una tajada.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import unicodedata
from pathlib import Path

CONTEXT_DIR = ".brief-context"
LLM_SUMMARY = "<!-- LLM: resumen -->"
LLM_OWASP = "<!-- LLM: superficie owasp -->"


def slugify(name):
    s = unicodedata.normalize("NFKD", name or "").encode("ascii", "ignore").decode("ascii").lower()
    s = re.sub(r"[^a-z0-9]+", "-", s).strip("-")
    return s or "feature"


def ids(seq):
    return ", ".join(str(s) for s in seq if s) if seq else "—"


def gherkin(ac):
    return "given %s / when %s / then %s" % (ac.get("given", ""), ac.get("when", ""), ac.get("then", ""))


def dep_str(dep):
    if isinstance(dep, dict):
        return "%s (%s)" % (dep.get("task_id"), dep.get("kind"))
    return str(dep)


def brief_name(featdir, fid, name):
    if featdir.is_dir():
        for p in sorted(featdir.glob("%s-*.md" % fid)):
            if re.match(r"^%s-[a-z0-9][a-z0-9-]*\.md$" % fid, p.name):
                return p.name
    return "%s-%s.md" % (fid, slugify(name))


def render(ctx, cambio=None):
    f = ctx.get("feature") or {}
    fid = f.get("id", "FG-??")
    tasks = ctx.get("tasks") or []
    batch = ctx.get("batch") or {}
    order = batch.get("task_order") or [t.get("id") for t in tasks]
    by_id = {t.get("id"): t for t in tasks}
    active = [by_id[i] for i in order if i in by_id and by_id[i].get("status", "pending") != "cancelled"]
    active += [t for t in tasks if t.get("id") not in order and t.get("status", "pending") != "cancelled"]
    cancelled = [t for t in tasks if t.get("status") == "cancelled"]
    reqs = ctx.get("requirements") or []
    own_reqs = [r for r in reqs if r.get("feature_group") == fid]
    design = ctx.get("design") or {}
    out = []

    if not active:
        out += ["# CANCELADO — %s %s" % (fid, f.get("name", "")), "",
                "Esta feature no tiene tareas activas en el plan (todas canceladas o feature deprecada). "
                "Ningun build debe tomar este brief como vigente.", ""]
        if cambio:
            out += ["Motivo: %s." % ids(cambio), ""]
        for t in cancelled:
            out.append("- `%s` %s — cancelada" % (t.get("id"), t.get("title", "")))
        return "\n".join(out) + "\n"

    # 1 Titulo y resumen
    out += ["# %s — %s" % (fid, f.get("name", "")), ""]
    if cambio or batch.get("adjustment"):
        line = "> **Actualizacion**"
        if cambio:
            line += " por %s" % ids(cambio)
        if batch.get("adjustment"):
            line += ": la construccion original esta mergeada; las tareas de este brief ajustan sobre esa base"
        if cancelled:
            line += "; tareas canceladas: %s" % ids(t.get("id") for t in cancelled)
        out += [line + ".", ""]
    out += ["Feature `%s` del plan (tasks.json v%s, execution-plan v%s)."
            % (fid, (ctx.get("source_versions") or {}).get("tasks"), (ctx.get("source_versions") or {}).get("execution_plan")), ""]
    if f.get("description"):
        out += [f["description"], ""]
    out += [LLM_SUMMARY, ""]

    # 2 Requisitos
    out += ["## Requisitos", ""]
    for r in reqs:
        tag = "" if r.get("feature_group") == fid else " _(de %s, citado por una tarea-contrato)_" % r.get("feature_group")
        out.append("### %s — %s%s" % (r.get("id"), r.get("title") or r.get("statement", "")[:80], tag))
        out.append("")
        if r.get("statement"):
            out += [r["statement"], ""]
        out.append("Prioridad: %s. Esfuerzo estimado: %s. Estado: %s." % (r.get("priority", "—"), r.get("estimated_effort", "—"), r.get("status", "—")))
        acs = r.get("acceptance_criteria") or []
        if acs:
            out += ["", "Criterios de aceptacion:"]
            for ac in acs:
                out.append("- `%s/%s`: %s" % (r.get("id"), ac.get("id"), gherkin(ac)))
        out.append("")
    rules = ctx.get("business_rules") or []
    out += ["### Reglas de negocio", ""]
    if rules:
        out.append("Invariantes que la feature respeta en TODO su codigo, no solo donde un criterio las muestrea:")
        out.append("")
        for br in rules:
            out.append("- `%s`: %s (aplican: %s)" % (br.get("id"), br.get("statement") or br.get("description", ""), ids(br.get("enforced_by") or [])))
    else:
        out.append("Ningun requisito de la feature hace cumplir una regla de negocio registrada.")
    out.append("")

    # 3 Plan de ejecucion
    out += ["## Plan de ejecucion de las tareas", "",
            "En el `task_order` del execution-plan; el agente las ejecuta en este orden.", ""]
    for i, t in enumerate(active, 1):
        out.append("### %d. `%s` — %s" % (i, t.get("id"), t.get("title", "")))
        out.append("")
        if t.get("description"):
            out += [t["description"], ""]
        out.append("Tipo: %s. Complejidad: %s. Prioridad: %s. Estado: %s. Depende de: %s."
                   % (t.get("type"), t.get("complexity"), t.get("priority"), t.get("status", "pending"),
                      ids(dep_str(d) for d in t.get("depends_on") or [])))
        if t.get("adjusts_task_id"):
            out.append("Ajusta la tarea ya construida `%s`." % t["adjusts_task_id"])
        out.append("Requisitos: %s. Modulos: %s. Entidades: %s."
                   % (ids(t.get("requirement_ids")), ids(t.get("module_ids")), ids(t.get("entity_ids"))))
        out.append("")
    if cancelled:
        out += ["### Tareas canceladas", ""]
        for t in cancelled:
            out.append("- `%s` %s" % (t.get("id"), t.get("title", "")))
        out.append("")

    # 4 Criterios
    out += ["## Criterios de aceptacion", "",
            "Definicion de verificado por tarea (Gherkin). Cada tarea cubre los criterios de los requisitos que cita, acotados a su alcance.", ""]
    for t in active:
        out.append("### `%s` (cubre %s)" % (t.get("id"), ids(t.get("requirement_ids"))))
        out.append("")
        for ac in t.get("acceptance_criteria") or []:
            out.append("- `%s`: %s" % (ac.get("id"), gherkin(ac)))
        if not t.get("acceptance_criteria"):
            out.append("- (sin criterios registrados: defecto de derivacion)")
        out.append("")
    out += ["### Criterios de cierre de feature", "",
            "Mapeo requisito -> tareas. Todo criterio de requisito lo cubren las tareas que citan su requisito; "
            "el flujo punta a punta lo demuestra el implementador al cerrar la feature, antes del review.", ""]
    for r in own_reqs:
        if r.get("status", "active") != "active":
            continue
        owners = [t.get("id") for t in active if r.get("id") in (t.get("requirement_ids") or [])]
        for ac in r.get("acceptance_criteria") or []:
            out.append("- `%s/%s` -> %s" % (r.get("id"), ac.get("id"), ids(owners) if owners else "**sin tarea: criterio de cierre punta a punta**"))
    if not any(r.get("acceptance_criteria") for r in own_reqs):
        out.append("Todos los criterios de requisito quedan cubiertos por tareas.")
    out.append("")

    # 5 Diseno
    out += ["## Diseno relevante", ""]
    if design.get("stack"):
        out += ["Stack: %s." % ids(s if isinstance(s, str) else (s.get("name") or s.get("id")) for s in design["stack"]), ""]
    for title, key, fmt in (
        ("Modulos", "modules", lambda m: "`%s` %s — %s" % (m.get("id"), m.get("name", ""), m.get("responsibility") or m.get("description", ""))),
        ("Contratos de API", "api_contracts", lambda a: "`%s` %s %s — auth_required: %s" % (a.get("id"), a.get("method", ""), a.get("path") or a.get("name", ""), a.get("auth_required"))),
        ("Pantallas", "screens", lambda s: "`%s` %s — %s" % (s.get("id"), s.get("name", ""), s.get("description", ""))),
        ("Decisiones", "decisions", lambda d: "`%s` %s — %s" % (d.get("id"), d.get("title", ""), d.get("decision") or d.get("description", ""))),
    ):
        items = design.get(key) or []
        if items:
            out += ["### %s" % title, ""] + ["- %s" % fmt(x) for x in items] + [""]
    ents = ctx.get("entities") or []
    if ents:
        out += ["### Entidades", ""]
        for e in ents:
            attrs = ids(a.get("name") if isinstance(a, dict) else a for a in e.get("attributes") or [])
            out.append("- `%s` %s — atributos: %s" % (e.get("id"), e.get("name", ""), attrs))
        out.append("")
    if not any(design.get(k) for k in ("modules", "api_contracts", "screens", "decisions")) and not ents:
        out += ["Sin elementos de diseno asociados a esta feature en la linea de base.", ""]

    # 6 Seguridad
    out += ["## Seguridad", ""]
    sec_reqs = [r for r in reqs if r.get("category") == "security"]
    sec_dec = [d for d in design.get("decisions") or [] if "segur" in json.dumps(d, ensure_ascii=False).lower() or d.get("category") == "security"]
    auth_api = [a for a in design.get("api_contracts") or [] if a.get("auth_required")]
    out += ["### Superficie OWASP", "", LLM_OWASP, ""]
    out += ["### Requisitos y criterios de seguridad especificos", ""]
    if sec_reqs:
        for r in sec_reqs:
            out.append("- `%s`: %s" % (r.get("id"), r.get("statement") or r.get("title", "")))
            for ac in r.get("acceptance_criteria") or []:
                out.append("  - `%s/%s`: %s" % (r.get("id"), ac.get("id"), gherkin(ac)))
    else:
        out.append("La feature no tiene requisitos de seguridad propios (RNF `category: security`).")
    out.append("")
    if sec_dec:
        out += ["ADRs de seguridad que la afectan:"] + ["- `%s` %s" % (d.get("id"), d.get("title", "")) for d in sec_dec] + [""]
    if auth_api:
        out += ["Contratos de API con `auth_required`:"] + ["- `%s` %s %s" % (a.get("id"), a.get("method", ""), a.get("path") or a.get("name", "")) for a in auth_api] + [""]
    out += ["### Piso de seguridad del stack", "",
            "El implementador aplica el piso de seguridad del stack (`.dev/build/security-baseline.json`) con los "
            "mecanismos nativos del framework; el `security-gate` lo verifica. No se inventan controles fuera del piso "
            "y de los requisitos citados arriba.", ""]

    # 7 Contratos
    contracts = ctx.get("contracts") or {}
    out += ["## Contratos", ""]
    prod = contracts.get("produces") or []
    cons = contracts.get("consumes") or []
    out.append("La ronda de contratos (`%s`) ya esta mergeada cuando esta feature arranca." % ((ctx.get("contract_round") or {}).get("id") or "sin ronda"))
    out.append("")
    out += ["### Produce", ""] + (["- `%s` %s" % (t.get("id"), t.get("title", "")) for t in prod] or ["- ninguno"]) + [""]
    out += ["### Consume", ""] + (["- `%s` %s (de %s)" % (c["task"].get("id"), c["task"].get("title", ""), c.get("producer_feature_id")) for c in cons] or ["- ninguno"]) + [""]

    # 8 Lote
    out += ["## Lote de ejecucion", ""]
    if batch:
        peers = batch.get("parallel_feature_ids") or []
        out.append("Lote `%s`. %s" % (batch.get("batch_id"), ("Corre en paralelo con: %s." % ids(peers)) if peers else
                                       "Es la unica feature del lote (quedo aislada por dependencias hard; ver rationale)."))
        if batch.get("groupable"):
            out.append("Ajuste trivial (`groupable`): conviene construirla compartiendo rama/agente con otra feature del lote.")
        if batch.get("rationale"):
            out.append("Rationale: %s" % batch["rationale"])
        out.append("Arranca despues de: %s." % ids(batch.get("unlocks_after") or []))
        waits = batch.get("waits_for") or []
        if waits:
            out += ["", "Espera:"]
            for w in waits:
                edges = "; ".join("%s -> %s (%s)" % (e.get("from_task"), e.get("to_task"), e.get("kind")) for e in w.get("edges") or [])
                out.append("- `%s` (%s): %s" % (w.get("feature_id"), w.get("batch_id"), edges))
    else:
        out.append("La feature no figura en ningun lote del execution-plan (revisar el plan).")
    out.append("")

    # 9 Dependencias entre features
    out += ["## Dependencias entre features", ""]
    own_ids = {t.get("id") for t in tasks}
    cross = []
    for t in active:
        for d in t.get("depends_on") or []:
            if isinstance(d, dict) and d.get("task_id") not in own_ids:
                cross.append("- `%s` depende **%s** de `%s`" % (t.get("id"), d.get("kind"), d.get("task_id")))
    out += (cross or ["Ninguna tarea de la feature depende de tareas de otra feature."]) + [""]
    out += ["`hard` = necesita el codigo mergeado; `contract` = alcanza con la firma mergeada en la ronda de contratos.", ""]

    # 10 Trazabilidad y vocabulario
    out += ["## Trazabilidad y vocabulario", ""]
    scen = sorted({s for r in own_reqs for s in (r.get("scenario_ids") or r.get("source_scenario_ids") or [])})
    out += ["Escenarios de origen: %s." % ids(scen), ""]
    out += ["### Vocabulario", ""]
    syms = ctx.get("lel_symbols") or []
    if syms:
        out.append("Un simbolo, un nombre: el codigo se nombra con estos terminos.")
        out.append("")
        for s in syms:
            notion = (s.get("notions") or [""])[0]
            out.append("- **%s** (`%s`, %s): %s" % (s.get("canonical_name"), s.get("id"), s.get("type"), notion))
    else:
        out.append("Los requisitos de la feature no citan simbolos del LEL.")
    out.append("")
    qs = ctx.get("open_questions") or []
    out += ["### Preguntas abiertas", ""]
    out += (["- `%s`%s: %s" % (q.get("id"), " (bloqueante)" if q.get("blocking") else "", q.get("question")) for q in qs]
            or ["Ninguna pregunta abierta afecta a esta feature."]) + [""]
    return "\n".join(out) + "\n"


def run(root, only, cambio):
    ctx_dir = root / ".dev" / "plan" / CONTEXT_DIR
    if not ctx_dir.is_dir():
        print("ERROR: no existe %s — correr antes slice_brief_context.py" % ctx_dir)
        return 1
    featdir = root / ".dev" / "features"
    featdir.mkdir(parents=True, exist_ok=True)
    targets = only or sorted(p.stem for p in ctx_dir.glob("FG-*.json"))
    failed = 0
    for fid in targets:
        path = ctx_dir / ("%s.json" % fid)
        if not path.is_file():
            print("ERROR: falta la tajada %s" % path)
            failed += 1
            continue
        ctx = json.loads(path.read_text(encoding="utf-8-sig"))
        name = brief_name(featdir, fid, (ctx.get("feature") or {}).get("name"))
        dest = featdir / name
        dest.write_text(render(ctx, cambio), encoding="utf-8")
        print("brief: %s" % dest)
    print("Listo: %d brief(s) en %s. Pendiente del subagente feature-brief: los marcadores %s y %s."
          % (len(targets) - failed, featdir, LLM_SUMMARY, LLM_OWASP))
    return 1 if failed else 0


def self_test():
    import shutil
    import tempfile
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import slice_brief_context as sbc  # noqa: E402
    import validate_plan as vp  # noqa: E402

    failures = 0

    def check(cond, label):
        nonlocal failures
        print(("self-test ok: %s" if cond else "SELF-TEST FALLO: %s") % label)
        if not cond:
            failures += 1

    tmp = Path(tempfile.mkdtemp(prefix="render-brief-"))
    try:
        # reutiliza la fixture del slicer: corre su self-test en modo silencioso construyendo la misma estructura
        req = tmp / ".dev" / "requirements"
        plan = tmp / ".dev" / "plan"
        req.mkdir(parents=True)
        plan.mkdir(parents=True)
        (plan / "tasks.json").write_text(json.dumps({
            "version": 4, "project": {"name": "demo"},
            "metadata": {"requirements_version_ref": "2"},
            "summary": {"feature_count": 1, "task_count": 2, "uncovered_requirement_ids": [],
                        "complexity_breakdown": {"low": 2, "medium": 0, "high": 0}},
            "features": [{"id": "FG-01", "name": "Alta de socios", "description": "d", "requirement_ids": ["RF-001"], "task_ids": ["T-001", "T-002"]}],
            "tasks": [
                {"id": "T-001", "title": "contrato", "feature_group": "FG-01", "type": "contract", "complexity": "low",
                 "priority": "high", "status": "pending", "depends_on": [], "requirement_ids": ["RF-001"],
                 "acceptance_criteria": [{"id": "AC-001", "given": "g", "when": "w", "then": "t"}]},
                {"id": "T-002", "title": "alta", "feature_group": "FG-01", "type": "feature", "complexity": "low",
                 "priority": "high", "status": "pending", "depends_on": [{"task_id": "T-001", "kind": "contract"}],
                 "requirement_ids": ["RF-001"], "module_ids": ["MOD-001"],
                 "acceptance_criteria": [{"id": "AC-001", "given": "g", "when": "w", "then": "t"}]},
            ],
            "open_questions": [{"id": "Q-001", "question": "q", "blocking": False, "related_task_ids": ["T-002"]}],
        }), encoding="utf-8")
        (plan / "execution-plan.json").write_text(json.dumps({
            "version": 2, "summary": {}, "contract_round": {"id": "BATCH-0", "task_ids": ["T-001"]},
            "batches": [{"id": "BATCH-1", "unlocks_after": ["BATCH-0"], "rationale": "r",
                         "features": [{"feature_id": "FG-01", "task_ids": ["T-002"], "task_order": ["T-002"], "waits_for": []}]}],
        }), encoding="utf-8")
        (req / "requirements.json").write_text(json.dumps({
            "version": 2,
            "functional_requirements": [{"id": "RF-001", "title": "Alta", "feature_group": "FG-01", "status": "active",
                                         "priority": "high", "estimated_effort": "s", "lel_symbol_ids": ["LEL-001"],
                                         "acceptance_criteria": [{"id": "AC-001", "given": "g", "when": "w", "then": "t"},
                                                                 {"id": "AC-002", "given": "g", "when": "w", "then": "t"}]}],
            "non_functional_requirements": [],
            "business_rules": [{"id": "BR-001", "statement": "s", "enforced_by": ["RF-001/AC-001"]}],
        }), encoding="utf-8")
        (req / "technical-design.json").write_text(json.dumps({
            "version": 1, "stack": ["python"],
            "modules": [{"id": "MOD-001", "name": "socios", "requirement_ids": ["RF-001"]}],
            "api_contracts": [{"id": "API-001", "method": "POST", "path": "/socios", "auth_required": True, "requirement_ids": ["RF-001"]}],
            "screens": [], "decisions": [],
        }), encoding="utf-8")
        (req / "lel.json").write_text(json.dumps({"version": 1, "symbols": [
            {"id": "LEL-001", "canonical_name": "socio", "type": "sujeto", "notions": [{"id": "N", "statement": "persona"}]}]}), encoding="utf-8")
        check(sbc.run(tmp, None, "9.9.9") == 0, "tajada generada")
        check(run(tmp, None, None) == 0, "brief renderizado")
        brief = tmp / ".dev" / "features" / "FG-01-alta-de-socios.md"
        check(brief.is_file(), "nombre FG-xx-{slug}.md")
        body = brief.read_text(encoding="utf-8")
        check(LLM_SUMMARY in body and LLM_OWASP in body, "marcadores para el subagente")
        check("RF-001/AC-002" in body, "todo criterio de requisito figura en Criterios de cierre")
        check("auth_required" in body and "API-001" in body, "API con auth en Seguridad")
        # recien renderizado, el linter solo objeta los marcadores (4c corre despues de 4b)
        code, found = vp.run_checks(tmp, briefs=True, previa=None, afectadas=None, as_json=False, quiet=True)
        lint = [d["description"] for d in found if d["check_id"] == "BRIEF-LINT"]
        check(len(lint) == 1 and "marcadores" in lint[0], "sin completar, el linter solo objeta los marcadores (%s)" % lint)
        brief.write_text(body.replace(LLM_SUMMARY, "Resumen.").replace(LLM_OWASP, "- A01"), encoding="utf-8")
        code, found = vp.run_checks(tmp, briefs=True, previa=None, afectadas=None, as_json=False, quiet=True)
        check(not [d for d in found if d["check_id"] == "BRIEF-LINT"], "completado, pasa el linter de briefs (%s)" % [d["description"] for d in found if d["check_id"] == "BRIEF-LINT"])
        # nombre estable tras renombrar la feature
        tj = json.loads((plan / "tasks.json").read_text(encoding="utf-8"))
        tj["features"][0]["name"] = "Registro de socios"
        (plan / "tasks.json").write_text(json.dumps(tj), encoding="utf-8")
        sbc.run(tmp, None, None)
        run(tmp, ["FG-01"], ["INC-002"])
        check(brief.is_file() and not (tmp / ".dev" / "features" / "FG-01-registro-de-socios.md").exists(), "nombre estable en replanificacion")
        check("Actualizacion" in brief.read_text(encoding="utf-8") and "INC-002" in brief.read_text(encoding="utf-8"), "linea de actualizacion con --cambio")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    print("SELF-TEST: %d fallo(s)" % failures)
    return 1 if failures else 0


def main(argv):
    if "--self-test" in argv:
        return self_test()
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("raiz", nargs="?", default=".")
    ap.add_argument("--features", nargs="+", default=None)
    ap.add_argument("--cambio", nargs="+", default=None, help="ids del changelog que motivan la regeneracion")
    args = ap.parse_args(argv)
    return run(Path(args.raiz).resolve(), args.features, args.cambio)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
