#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Validacion mecanica del plan: los PLAN-CHECK que no requieren juicio, sin tokens.

Corre la mitad automatizable del checklist de `plan-inspection` en milisegundos:
cobertura, huerfanas, formato y ciclos de dependencias, features validas, staleness
contra el changelog, completitud y orden de los lotes, metricas, sincronia de las
vistas derivadas y consistencia del summary de tasks.json. Los checks de juicio
(granularidad real de una tarea, coherencia semantica de criterios) siguen siendo
del subagente `plan-inspection`, que recibe estos resultados como pre-verificados.

Checks mecanicos que cubre (mismos ids del checklist de plan-inspection):
  PLAN-CHECK-001 cobertura de requisitos active
  PLAN-CHECK-002 tareas huerfanas y contratos que citan dos features
  PLAN-CHECK-003 dependencias: formato objeto, existencia, kinds, ciclos
  PLAN-CHECK-004 (parte mecanica) complexity valida; requisito xl en una sola tarea
  PLAN-CHECK-005 features validas; regla de la sintetica FG-00
  PLAN-CHECK-006 (parte mecanica) tarea sin ningun criterio de aceptacion
  PLAN-CHECK-007 staleness: version refs y changelog absorbido
  PLAN-CHECK-008 completitud de lotes (toda tarea activa en exactamente un lote)
  PLAN-CHECK-009 orden de lotes y task_order vs dependencias
  PLAN-CHECK-010 metricas del summary vs lotes emitidos
  PLAN-CHECK-011 serializacion por arista unica sin warning accionable
  PLAN-CHECK-012 (parte mecanica) lote serial cuyo rationale no cita tareas
  PLAN-CHECK-013 invariante de replanificacion (solo con --previa y --afectadas)
  PLAN-CHECK-014 sincronia de tasks.md / execution-plan.md
  PLAN-CHECK-015 summary de tasks.json consistente con su contenido (red de
                 seguridad de las correcciones quirurgicas con Edit)

Con --inyectar-checks fusiona sus resultados en `.dev/plan/plan-inspection.json`
(escrito por `plan-inspection` en modo juicio con solo los checks de juicio): agrega
una entrada por check mecanico a `checks_applied` (ok / defect / skipped con motivo
"verificado mecanicamente por validate_plan.py"), suma sus defectos y recalcula el
summary y `passed`. Asi el subagente no gasta output enumerando 14 checks.

Con --briefs valida ademas los briefs de .dev/features/: nombre de archivo,
encabezados obligatorios, toda tarea y todo requisito de la feature presentes, y
todo criterio RF-xxx/AC-xxx de la feature mapeado o listado (un criterio sin dueno
es un brief incompleto).

Solo stdlib, Python 3.8+. No modifica nada.

Uso:
  python validate_plan.py [raiz] [--briefs] [--previa TASKS_PREVIO.json]
                          [--afectadas FG-01 FG-02] [--json] [--inyectar-checks]
  python validate_plan.py --self-test

Exit 0: sin defectos high/medium (los low se listan). Exit 1: hay high/medium.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import unicodedata
from pathlib import Path

ID_T = re.compile(r"^T-\d+$")
ID_FG = re.compile(r"^FG-\d+$")
COMPLEXITIES = {"low", "medium", "high"}
DEP_KINDS = {"hard", "contract"}
DERIVED_HEADER = re.compile(r"Derivado de `(?P<json>[\w.-]+)` version (?P<version>\d+)")

defects = []
checks_ok = set()
checks_failed = set()
checks_skipped = {}

ALL_CHECKS = ["PLAN-CHECK-%03d" % i for i in range(1, 16) if i != 13]


def defect(check, severity, target, description, bounce):
    defects.append({
        "check_id": check, "severity": severity, "target_id": target,
        "description": description, "bounce": bounce,
    })
    checks_failed.add(check)


def skip(check, reason):
    checks_skipped[check] = reason


def load(path):
    if not path.is_file():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except (ValueError, OSError) as exc:
        defect("PLAN-CHECK-003", "high", path.name, "JSON ilegible: %s" % exc, "task-derivation")
        return None


def norm(s):
    return unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode("ascii")


# ------------------------------------------------------------- checks de tasks


def check_tasks(tasks_doc, reqs_doc, changelog_doc):
    tasks = tasks_doc.get("tasks") or []
    features = tasks_doc.get("features") or []
    fids = {f.get("id") for f in features}
    tids = {t.get("id") for t in tasks}
    by_id = {t.get("id"): t for t in tasks}
    active_tasks = [t for t in tasks if t.get("status", "pending") != "cancelled"]

    req_feature = {}
    active_reqs = set()
    xl_reqs = set()
    if reqs_doc is not None:
        for r in (reqs_doc.get("functional_requirements") or []) + (reqs_doc.get("non_functional_requirements") or []):
            req_feature[r.get("id")] = r.get("feature_group")
            if r.get("status") == "active":
                active_reqs.add(r.get("id"))
            if r.get("estimated_effort") == "xl":
                xl_reqs.add(r.get("id"))

    # PLAN-CHECK-001 cobertura
    if reqs_doc is None:
        skip("PLAN-CHECK-001", "requirements.json no disponible")
    else:
        covered = {rid for t in active_tasks for rid in t.get("requirement_ids") or []}
        for rid in sorted(active_reqs - covered):
            defect("PLAN-CHECK-001", "high", rid,
                   "requisito active sin tarea no cancelada que lo cubra", "task-derivation")
        declared = set((tasks_doc.get("summary") or {}).get("uncovered_requirement_ids") or [])
        real_uncovered = active_reqs - covered
        if declared != real_uncovered:
            defect("PLAN-CHECK-015", "medium", "summary.uncovered_requirement_ids",
                   "declara %s pero el contenido da %s" % (sorted(declared), sorted(real_uncovered)),
                   "task-derivation")

    # PLAN-CHECK-002 huerfanas y contratos
    for t in tasks:
        rids = t.get("requirement_ids") or []
        if not rids:
            defect("PLAN-CHECK-002", "high", t.get("id"), "tarea sin requirement_ids: huerfana", "task-derivation")
            continue
        if reqs_doc is not None:
            unknown = [r for r in rids if r not in req_feature]
            for r in unknown:
                defect("PLAN-CHECK-002", "high", t.get("id"), "cita requisito inexistente %s" % r, "task-derivation")
            if t.get("type") == "contract":
                feats = {req_feature[r] for r in rids if r in req_feature}
                if len(feats) < 2:
                    defect("PLAN-CHECK-002", "medium", t.get("id"),
                           "tarea-contrato que no cita requisitos de dos features distintas", "task-derivation")

    # PLAN-CHECK-003 dependencias
    for t in tasks:
        for dep in t.get("depends_on") or []:
            if not isinstance(dep, dict) or dep.get("kind") not in DEP_KINDS:
                defect("PLAN-CHECK-003", "high", t.get("id"),
                       "depends_on en formato viejo o kind invalido (%r): migrar al formato objeto {task_id, kind}" % (dep,),
                       "task-derivation")
                continue
            target = dep.get("task_id")
            if target not in tids:
                defect("PLAN-CHECK-003", "high", t.get("id"), "depende de %s que no existe" % target, "task-derivation")
                continue
            if dep["kind"] == "contract" and by_id[target].get("type") != "contract":
                defect("PLAN-CHECK-003", "high", t.get("id"),
                       "dependencia kind=contract apunta a %s que no es type=contract" % target, "task-derivation")
            if dep["kind"] == "hard" and t.get("type") == "contract":
                defect("PLAN-CHECK-003", "medium", t.get("id"),
                       "tarea-contrato con dependencia hard a %s" % target, "task-derivation")
    # ciclos entre tareas (DFS con colores)
    color = {}

    def has_cycle(tid, stack):
        color[tid] = 1
        for dep in by_id.get(tid, {}).get("depends_on") or []:
            nxt = dep.get("task_id") if isinstance(dep, dict) else None
            if nxt not in by_id:
                continue
            if color.get(nxt) == 1:
                stack.append((tid, nxt))
                return True
            if color.get(nxt, 0) == 0 and has_cycle(nxt, stack):
                return True
        color[tid] = 2
        return False

    for tid in sorted(tids - {None}):
        if color.get(tid, 0) == 0:
            stack = []
            if has_cycle(tid, stack):
                defect("PLAN-CHECK-003", "high", stack[0][0],
                       "ciclo de dependencias que incluye %s -> %s" % stack[0], "task-derivation")
                break

    # PLAN-CHECK-004 mecanico
    for t in tasks:
        if t.get("complexity") not in COMPLEXITIES:
            defect("PLAN-CHECK-004", "medium", t.get("id"),
                   "complexity invalida %r" % t.get("complexity"), "task-derivation")
    for rid in sorted(xl_reqs & active_reqs):
        covering = [t.get("id") for t in active_tasks if rid in (t.get("requirement_ids") or [])]
        if len(covering) == 1:
            defect("PLAN-CHECK-004", "medium", rid,
                   "requisito xl cubierto por una sola tarea (%s): partirlo" % covering[0], "task-derivation")

    # PLAN-CHECK-005 features
    synthetics = [f for f in features if f.get("synthetic")]
    if len(synthetics) > 1 or any(f.get("id") != "FG-00" for f in synthetics):
        defect("PLAN-CHECK-005", "high", ",".join(f.get("id", "?") for f in synthetics),
               "feature sintetica invalida: a lo sumo una, con id FG-00", "task-derivation")
    for t in tasks:
        if t.get("feature_group") not in fids:
            defect("PLAN-CHECK-005", "high", t.get("id"),
                   "feature_group %r no existe" % t.get("feature_group"), "task-derivation")

    # PLAN-CHECK-006 mecanico
    for t in active_tasks:
        if t.get("type") != "contract" and not t.get("acceptance_criteria"):
            defect("PLAN-CHECK-006", "high", t.get("id"),
                   "tarea sin criterios de aceptacion: un agente de build no puede verificarla", "task-derivation")

    # PLAN-CHECK-007 staleness
    meta = tasks_doc.get("metadata") or {}
    if reqs_doc is None and changelog_doc is None:
        skip("PLAN-CHECK-007", "sin requirements.json ni changelog.json: el check no corrio")
    if reqs_doc is not None:
        if str(meta.get("requirements_version_ref")) != str(reqs_doc.get("version")):
            defect("PLAN-CHECK-007", "high", "requirements_version_ref",
                   "el plan cita la version %s pero requirements.json esta en %s: correr /replanificar"
                   % (meta.get("requirements_version_ref"), reqs_doc.get("version")), "orquestador")
    if changelog_doc is not None:
        applied = set(meta.get("applied_changelog_ids") or [])
        deferred = set(meta.get("deferred_changelog_ids") or [])
        for e in changelog_doc.get("entries") or []:
            eid = e.get("id", "")
            if e.get("status") == "applied" and re.match(r"^(INC|CR|REC)-\d+$", eid):
                if eid not in applied and eid not in deferred:
                    defect("PLAN-CHECK-007", "high", eid,
                           "entrada aplicada del changelog no absorbida por el plan: correr /replanificar", "orquestador")
                elif eid in deferred:
                    defect("PLAN-CHECK-007", "low", eid, "entrada postergada a proposito (informativo)", "orquestador")

    # PLAN-CHECK-015 summary de tasks.json
    summary = tasks_doc.get("summary") or {}
    real = {
        "feature_count": len(features),
        "task_count": len(tasks),
    }
    for key, val in real.items():
        if summary.get(key) is not None and summary.get(key) != val:
            defect("PLAN-CHECK-015", "medium", "summary.%s" % key,
                   "declara %s pero el contenido da %s" % (summary.get(key), val), "task-derivation")
    declared_cx = summary.get("complexity_breakdown") or {}
    real_cx = {c: sum(1 for t in active_tasks if t.get("complexity") == c) for c in COMPLEXITIES}
    if declared_cx and any(declared_cx.get(c) != real_cx[c] for c in COMPLEXITIES):
        defect("PLAN-CHECK-015", "medium", "summary.complexity_breakdown",
               "declara %s pero el contenido da %s" % (declared_cx, real_cx), "task-derivation")

    return by_id, fids


# ---------------------------------------------------- checks de execution-plan


def check_execution_plan(plan_doc, by_id, fids, tasks_doc):
    tasks = tasks_doc.get("tasks") or []
    active = {t.get("id") for t in tasks if t.get("status", "pending") != "cancelled"}
    contract_tasks = {t.get("id") for t in tasks if t.get("type") == "contract" and t.get("id") in active}
    feat_of = {t.get("id"): t.get("feature_group") for t in tasks}

    contract = plan_doc.get("contract_round") or {}
    contract_ids = list(contract.get("task_ids") or [])
    batches = plan_doc.get("batches") or []

    batch_index = {}
    if contract:
        batch_index[contract.get("id", "BATCH-0")] = 0
    placed = list(contract_ids)
    feature_batches = {}
    for i, b in enumerate(batches, start=1):
        bid = b.get("id")
        batch_index[bid] = i
        for e in b.get("features") or []:
            fid = e.get("feature_id")
            feature_batches.setdefault(fid, []).append(bid)
            placed += list(e.get("task_ids") or [])
            if sorted(e.get("task_ids") or []) != sorted(e.get("task_order") or []):
                defect("PLAN-CHECK-009", "high", "%s/%s" % (bid, fid),
                       "task_order no es una permutacion de task_ids", "execution-planning")

    completed = set((plan_doc.get("metadata") or {}).get("completed_feature_ids") or [])

    # PLAN-CHECK-008 completitud
    feats_with_tasks = {feat_of[t] for t in active if feat_of.get(t)}
    for fid in sorted(feats_with_tasks):
        n = len(feature_batches.get(fid, []))
        if fid in completed:
            continue
        if n != 1:
            defect("PLAN-CHECK-008", "high", fid,
                   "feature con tareas en %d lotes (esperado exactamente 1)" % n, "execution-planning")
    dupes = sorted({t for t in placed if placed.count(t) > 1})
    for t in dupes:
        defect("PLAN-CHECK-008", "high", t, "la tarea aparece en mas de un lote", "execution-planning")
    completed_tasks = {t for t in active if feat_of.get(t) in completed}
    for t in sorted(active - set(placed) - completed_tasks):
        defect("PLAN-CHECK-008", "high", t, "tarea activa fuera de todo lote: no la construye nadie", "execution-planning")
    for t in sorted(set(placed) - active):
        defect("PLAN-CHECK-008", "high", t, "tarea cancelada o inexistente colocada en un lote", "execution-planning")
    for t in sorted(contract_tasks - set(contract_ids)):
        if t in set(placed):
            continue  # contrato en lote posterior: lo cubre el caso de replanificacion
        defect("PLAN-CHECK-008", "high", t, "tarea type=contract fuera de la ronda de contratos", "execution-planning")

    # PLAN-CHECK-009 orden
    for b in batches:
        bid = b.get("id")
        feats_here = {e.get("feature_id") for e in b.get("features") or []}
        for e in b.get("features") or []:
            fid = e.get("feature_id")
            for t in e.get("task_ids") or []:
                for dep in (by_id.get(t) or {}).get("depends_on") or []:
                    if not isinstance(dep, dict) or dep.get("kind") != "hard":
                        continue
                    pt = dep.get("task_id")
                    pf = feat_of.get(pt)
                    if pf and pf != fid and pf in feats_here:
                        defect("PLAN-CHECK-009", "high", "%s/%s" % (bid, fid),
                               "comparte lote con %s de la que depende hard (%s -> %s)" % (pf, t, pt),
                               "execution-planning")
            for w in e.get("waits_for") or []:
                wb = w.get("batch_id")
                if wb in batch_index and batch_index[wb] >= batch_index.get(bid, 0):
                    defect("PLAN-CHECK-009", "high", "%s/%s" % (bid, fid),
                           "waits_for cita %s que no es un lote anterior" % wb, "execution-planning")
            # task_order respeta dependencias intra-feature
            order = e.get("task_order") or []
            pos = {t: i for i, t in enumerate(order)}
            for t in order:
                for dep in (by_id.get(t) or {}).get("depends_on") or []:
                    if isinstance(dep, dict) and dep.get("task_id") in pos and pos[dep["task_id"]] > pos[t]:
                        defect("PLAN-CHECK-009", "high", "%s/%s" % (bid, e.get("feature_id")),
                               "task_order pone %s antes que su dependencia %s" % (t, dep["task_id"]),
                               "execution-planning")
        for prev in b.get("unlocks_after") or []:
            if prev not in batch_index:
                defect("PLAN-CHECK-009", "high", bid, "unlocks_after cita %s que no existe" % prev, "execution-planning")
            elif batch_index[prev] >= batch_index[bid]:
                defect("PLAN-CHECK-009", "high", bid, "unlocks_after cita %s que no es anterior" % prev, "execution-planning")

    # PLAN-CHECK-010 metricas
    s = plan_doc.get("summary") or {}
    sizes = [sum(1 for e in (b.get("features") or []) if not e.get("groupable")) for b in batches]
    expected = {
        "max_parallel_degree": max(sizes, default=0),
        "critical_path_length": len(batches) + (1 if contract else 0),
        "batch_count": len(batches),
        "feature_count": sum(len(b.get("features") or []) for b in batches),
        "contract_task_count": len(contract_ids),
        "truly_serial_batches": sum(1 for n in sizes if n == 1),
    }
    for key, val in expected.items():
        if s.get(key) is not None and s.get(key) != val:
            defect("PLAN-CHECK-010", "medium", "summary.%s" % key,
                   "declara %s pero los lotes dan %s" % (s.get(key), val), "execution-planning")

    # PLAN-CHECK-011 serializacion por arista unica sin warning
    warn_text = " ".join(plan_doc.get("warnings") or [])
    for b in batches:
        for e in b.get("features") or []:
            fid = e.get("feature_id")
            hard_waits = [w for w in e.get("waits_for") or []
                          if any(x.get("kind") == "hard" for x in w.get("edges") or [])]
            if len(hard_waits) != 1:
                continue
            edges = [x for x in hard_waits[0].get("edges") or [] if x.get("kind") == "hard"]
            if len(edges) == 1:
                to_t = edges[0].get("to_task", "")
                if to_t and to_t not in warn_text:
                    defect("PLAN-CHECK-011", "medium", fid,
                           "serializada por la unica arista hard %s -> %s sin warning que sugiera extraer el contrato"
                           % (edges[0].get("from_task"), to_t), "execution-planning")

    # PLAN-CHECK-012 mecanico: lote serial cuyo rationale no cita tareas
    for b in batches:
        feats = b.get("features") or []
        if len(feats) == 1:
            rationale = b.get("rationale") or ""
            has_deps = any(e.get("waits_for") for e in feats)
            if has_deps and not re.search(r"T-\d+", rationale):
                defect("PLAN-CHECK-012", "low", b.get("id"),
                       "lote serial sin rationale que cite las tareas que lo aislaron", "execution-planning")


# ---------------------------------------------------------- vistas y replan


def check_views(plan_dir, tasks_doc, plan_doc):
    for md_name, doc in (("tasks.md", tasks_doc), ("execution-plan.md", plan_doc)):
        if doc is None:
            continue
        path = plan_dir / md_name
        if not path.is_file():
            defect("PLAN-CHECK-014", "medium", md_name,
                   "vista derivada ausente: re-correr render_plan_docs.py", "orquestador")
            continue
        m = DERIVED_HEADER.search(path.read_text(encoding="utf-8-sig")[:500])
        if not m or m.group("version") != str(doc.get("version")):
            defect("PLAN-CHECK-014", "medium", md_name,
                   "encabezado de sincronia ausente o con version distinta de %s: re-correr render_plan_docs.py"
                   % doc.get("version"), "orquestador")


def check_replan_invariant(tasks_doc, previa_path, afectadas):
    try:
        prev = json.loads(Path(previa_path).read_text(encoding="utf-8-sig"))
    except (ValueError, OSError) as exc:
        skip("PLAN-CHECK-013", "version previa ilegible: %s" % exc)
        return
    prev_tasks = {t.get("id"): t for t in prev.get("tasks") or []}
    cur_tasks = {t.get("id"): t for t in tasks_doc.get("tasks") or []}
    affected = set(afectadas or [])
    for tid, t in sorted(prev_tasks.items()):
        if t.get("feature_group") in affected:
            continue
        cur = cur_tasks.get(tid)
        if cur is None:
            defect("PLAN-CHECK-013", "high", tid,
                   "tarea de feature no afectada desaparecio en la replanificacion", "task-derivation")
        elif cur != t:
            changed = sorted(k for k in set(t) | set(cur) if t.get(k) != cur.get(k))
            defect("PLAN-CHECK-013", "high", tid,
                   "tarea de feature no afectada cambio (campos: %s)" % ", ".join(changed), "task-derivation")
    checks_ok.add("PLAN-CHECK-013") if "PLAN-CHECK-013" not in checks_failed else None


# -------------------------------------------------------------------- briefs


def slug_matches(fid, path_name):
    return re.match(r"^%s-[a-z0-9][a-z0-9-]*\.md$" % fid, path_name) is not None


def check_briefs(root, tasks_doc, reqs_doc):
    featdir = root / ".dev" / "features"
    features = tasks_doc.get("features") or []
    tasks = tasks_doc.get("tasks") or []
    reqs = []
    if reqs_doc is not None:
        reqs = (reqs_doc.get("functional_requirements") or []) + (reqs_doc.get("non_functional_requirements") or [])
    reqs_by_feature = {}
    for r in reqs:
        reqs_by_feature.setdefault(r.get("feature_group"), []).append(r)

    for f in features:
        fid = f.get("id")
        ftasks = [t for t in tasks if t.get("feature_group") == fid and t.get("status", "pending") != "cancelled"]
        if not ftasks:
            continue
        candidates = sorted(p for p in featdir.glob("%s-*.md" % fid)) if featdir.is_dir() else []
        candidates = [p for p in candidates if slug_matches(fid, p.name)]
        if len(candidates) != 1:
            defect("BRIEF-LINT", "high", fid,
                   "se esperaba exactamente un brief FG-xx-{slug}.md y hay %d" % len(candidates), "feature-brief")
            continue
        body = candidates[0].read_text(encoding="utf-8-sig")
        if "CANCELADO" in body[:300]:
            continue
        leftovers = re.findall(r"<!--\s*LLM:.*?-->", body)
        if leftovers:
            defect("BRIEF-LINT", "high", "%s (%s)" % (fid, candidates[0].name),
                   "quedaron marcadores sin reemplazar: %s" % ", ".join(leftovers), "feature-brief")
        plain = norm(body)
        for head in ("Seguridad", "Vocabulario", "Criterios de cierre de feature"):
            if head not in plain:
                defect("BRIEF-LINT", "high", "%s (%s)" % (fid, candidates[0].name),
                       "falta el encabezado obligatorio '%s'" % head, "feature-brief")
        for t in ftasks:
            if t.get("id") not in body:
                defect("BRIEF-LINT", "high", "%s (%s)" % (fid, candidates[0].name),
                       "la tarea %s no aparece en el brief" % t.get("id"), "feature-brief")
        for r in reqs_by_feature.get(fid, []):
            if r.get("status") != "active":
                continue
            rid = r.get("id")
            if rid not in body:
                defect("BRIEF-LINT", "high", "%s (%s)" % (fid, candidates[0].name),
                       "el requisito %s no aparece en el brief" % rid, "feature-brief")
                continue
            for ac in r.get("acceptance_criteria") or []:
                combo = "%s/%s" % (rid, ac.get("id"))
                if combo not in body:
                    defect("BRIEF-LINT", "high", "%s (%s)" % (fid, candidates[0].name),
                           "criterio %s sin dueno: ni mapeado a una tarea ni en Criterios de cierre" % combo,
                           "feature-brief")


# ------------------------------------------------------------------ self-test


def self_test():
    import shutil
    import tempfile

    def fixture(root, break_it):
        req = root / ".dev" / "requirements"
        req.mkdir(parents=True)
        (req / "requirements.json").write_text(json.dumps({
            "version": 2,
            "feature_groups": [{"id": "FG-01", "requirement_ids": ["RF-001"]}],
            "functional_requirements": [{
                "id": "RF-001", "feature_group": "FG-01", "status": "active",
                "estimated_effort": "m",
                "acceptance_criteria": [{"id": "AC-001", "given": "g", "when": "w", "then": "t"}],
            }],
            "non_functional_requirements": [],
        }), encoding="utf-8")
        plan = root / ".dev" / "plan"
        plan.mkdir(parents=True)
        tasks = {
            "version": 1,
            "metadata": {"requirements_version_ref": "2"},
            "summary": {"feature_count": 1, "task_count": 1,
                        "uncovered_requirement_ids": [],
                        "complexity_breakdown": {"low": 1, "medium": 0, "high": 0}},
            "features": [{"id": "FG-01", "task_ids": ["T-001"]}],
            "tasks": [{"id": "T-001", "feature_group": "FG-01", "type": "feature",
                       "complexity": "low", "status": "pending", "depends_on": [],
                       "requirement_ids": ["RF-001"],
                       "acceptance_criteria": [{"id": "AC-001", "given": "g", "when": "w", "then": "t"}]}],
        }
        if break_it:
            tasks["tasks"][0]["requirement_ids"] = []          # 002 huerfana -> 001 sin cobertura
            tasks["summary"]["task_count"] = 9                  # 015 summary
        (plan / "tasks.json").write_text(json.dumps(tasks), encoding="utf-8")
        (plan / "execution-plan.json").write_text(json.dumps({
            "version": 1,
            "summary": {"max_parallel_degree": 1, "critical_path_length": 1, "batch_count": 1,
                        "feature_count": 1, "contract_task_count": 0, "truly_serial_batches": 1},
            "contract_round": None,
            "batches": [{"id": "BATCH-1", "unlocks_after": [], "rationale": "Lote serial: unica feature.",
                         "features": [{"feature_id": "FG-01", "task_ids": ["T-001"],
                                       "task_order": ["T-001"], "waits_for": []}]}],
            "warnings": [],
        }), encoding="utf-8")
        for name, version in (("tasks.md", 1), ("execution-plan.md", 1)):
            (plan / name).write_text("# x\n\n> Derivado de `%s` version %d — no editar a mano.\n"
                                     % (name.replace(".md", ".json"), version), encoding="utf-8")
        feat = root / ".dev" / "features"
        feat.mkdir(parents=True)
        body = ("# FG-01 — Demo\n\n## Requisitos\nRF-001 (RF-001/AC-001)\n\n"
                "## Plan\nT-001\n\n## Seguridad\npiso del stack\n\n## Vocabulario\n- demo\n\n"
                "## Criterios de cierre de feature\ntodos cubiertos\n")
        if break_it:
            body = body.replace("## Vocabulario\n- demo\n\n", "")
        (feat / "FG-01-demo.md").write_text(body, encoding="utf-8")

    failures = 0
    for break_it, expect_fail in ((False, False), (True, True)):
        tmp = Path(tempfile.mkdtemp(prefix="validate-plan-"))
        try:
            fixture(tmp, break_it)
            code, found = run_checks(tmp, briefs=True, previa=None, afectadas=None, as_json=False, quiet=True)
            label = "fixture rota" if break_it else "fixture consistente"
            got_fail = code != 0
            if got_fail != expect_fail:
                print("SELF-TEST FALLO (%s): exit=%d defectos=%s" % (label, code, found))
                failures += 1
            else:
                print("self-test ok (%s): %d defecto(s), exit %d" % (label, len(found), code))
            if not break_it:
                (tmp / ".dev" / "plan" / "plan-inspection.json").write_text(json.dumps({
                    "version": 1, "summary": {}, "passed": False,
                    "checks_applied": [{"check_id": "PLAN-CHECK-004", "result": "ok", "reason": "juicio"}],
                    "defects": []}), encoding="utf-8")
                rc = inject_checks(tmp, found)
                inj = json.loads((tmp / ".dev" / "plan" / "plan-inspection.json").read_text(encoding="utf-8"))
                ok_ids = {c["check_id"] for c in inj["checks_applied"]}
                if rc != 0 or not inj["passed"] or "PLAN-CHECK-001" not in ok_ids or "PLAN-CHECK-004" not in ok_ids:
                    print("SELF-TEST FALLO (inyectar checks): %s" % inj)
                    failures += 1
                else:
                    print("self-test ok (inyectar checks: %d checks, passed)" % len(inj["checks_applied"]))
                # un marcador que sobrevive (p. ej. el resumen escrito encima) es defecto
                brief = tmp / ".dev" / "features" / "FG-01-demo.md"
                brief.write_text(brief.read_text(encoding="utf-8") + "\n<!-- LLM: resumen -->\n", encoding="utf-8")
                code, found = run_checks(tmp, briefs=True, previa=None, afectadas=None, as_json=False, quiet=True)
                if code == 0 or not any(d["check_id"] == "BRIEF-LINT" and "marcadores" in d["description"] for d in found):
                    print("SELF-TEST FALLO (marcador LLM sobreviviente no detectado): %s" % found)
                    failures += 1
                else:
                    print("self-test ok (marcador LLM sobreviviente detectado)")
            if break_it:
                got_checks = {d["check_id"] for d in found}
                expected = {"PLAN-CHECK-001", "PLAN-CHECK-002", "PLAN-CHECK-015", "BRIEF-LINT"}
                if not expected <= got_checks:
                    print("SELF-TEST FALLO: esperaba %s, encontro %s" % (sorted(expected), sorted(got_checks)))
                    failures += 1
                else:
                    print("self-test ok (checks detectados: %s)" % ", ".join(sorted(got_checks)))
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
    print("SELF-TEST: %d fallo(s)" % failures)
    return 1 if failures else 0


# ----------------------------------------------------------------------- main


def run_checks(root, briefs, previa, afectadas, as_json, quiet=False):
    del defects[:]
    checks_ok.clear()
    checks_failed.clear()
    checks_skipped.clear()

    plan_dir = root / ".dev" / "plan"
    tasks_doc = load(plan_dir / "tasks.json")
    plan_doc = load(plan_dir / "execution-plan.json")
    reqs_doc = load(root / ".dev" / "requirements" / "requirements.json")
    changelog_doc = load(root / ".dev" / "requirements" / "changelog.json")

    if tasks_doc is None:
        defect("PLAN-CHECK-003", "high", "tasks.json", "no existe o no parsea", "task-derivation")
        for c in ALL_CHECKS:
            if c != "PLAN-CHECK-003":
                skip(c, "tasks.json no disponible: el check no corrio")
    else:
        by_id, fids = check_tasks(tasks_doc, reqs_doc, changelog_doc)
        if plan_doc is None:
            defect("PLAN-CHECK-008", "high", "execution-plan.json", "no existe o no parsea", "execution-planning")
            for c in ("PLAN-CHECK-009", "PLAN-CHECK-010", "PLAN-CHECK-011", "PLAN-CHECK-012"):
                skip(c, "execution-plan.json no disponible: el check no corrio")
        else:
            check_execution_plan(plan_doc, by_id, fids, tasks_doc)
        check_views(plan_dir, tasks_doc, plan_doc)
        if previa:
            check_replan_invariant(tasks_doc, previa, afectadas)
        else:
            skip("PLAN-CHECK-013", "solo aplica en replanificacion (usar --previa y --afectadas)")
        if briefs:
            check_briefs(root, tasks_doc, reqs_doc)

    for c in ALL_CHECKS:
        if c not in checks_failed and c not in checks_skipped:
            checks_ok.add(c)

    blocking = [d for d in defects if d["severity"] in ("high", "medium")]
    if not quiet:
        if as_json:
            print(json.dumps({
                "passed": not blocking,
                "checks_ok": sorted(checks_ok),
                "checks_skipped": checks_skipped,
                "defects": defects,
            }, ensure_ascii=False, indent=2))
        else:
            for d in defects:
                print("DEF [%s][%s] %s: %s (rebota a %s)"
                      % (d["check_id"], d["severity"], d["target_id"], d["description"], d["bounce"]))
            for c, reason in sorted(checks_skipped.items()):
                print("skip %s: %s" % (c, reason))
            print("checks ok: %s" % (", ".join(sorted(checks_ok)) or "ninguno"))
            if blocking:
                print("NO PASA: %d defecto(s) high/medium." % len(blocking))
            else:
                print("PASA la validacion mecanica (%d defecto(s) low informativos)."
                      % len(defects))
    return (1 if blocking else 0), list(defects)


def inject_checks(root, found):
    """Fusiona los resultados mecanicos en plan-inspection.json (modo juicio)."""
    path = root / ".dev" / "plan" / "plan-inspection.json"
    if not path.is_file():
        print("ERROR: no existe %s para inyectar los checks" % path)
        return 1
    try:
        doc = json.loads(path.read_text(encoding="utf-8-sig"))
    except (ValueError, OSError) as exc:
        print("ERROR: %s ilegible: %s" % (path, exc))
        return 1
    reason = "verificado mecanicamente por validate_plan.py"
    applied = [c for c in doc.get("checks_applied") or [] if c.get("check_id") not in set(ALL_CHECKS) | {"PLAN-CHECK-013"}
               or c.get("check_id") in ("PLAN-CHECK-004", "PLAN-CHECK-006", "PLAN-CHECK-012")]
    judged = {c.get("check_id") for c in applied}
    for c in ALL_CHECKS + ["PLAN-CHECK-013"]:
        if c in judged:
            continue
        if c in checks_failed:
            applied.append({"check_id": c, "result": "defect", "reason": reason})
        elif c in checks_skipped:
            applied.append({"check_id": c, "result": "skipped", "reason": "%s: %s" % (reason, checks_skipped[c])})
        else:
            applied.append({"check_id": c, "result": "ok", "reason": reason})
    applied.sort(key=lambda c: str(c.get("check_id")))
    defects_doc = [d for d in doc.get("defects") or [] if not str(d.get("id", "")).startswith("MEC-")]
    for i, d in enumerate(found, 1):
        defects_doc.append({
            "id": "MEC-%03d" % i, "check_id": d["check_id"], "target_kind": "task", "target_id": d["target_id"],
            "type": "discrepancy", "severity": d["severity"], "description": d["description"],
            "evidence_refs": [d["target_id"]], "proposed_correction": "rebota a %s" % d["bounce"], "confirmed": True,
        })
    confirmed = [d for d in defects_doc if d.get("confirmed")]
    doc["checks_applied"] = applied
    doc["defects"] = defects_doc
    summary = doc.get("summary") or {}
    summary.update({
        "total_defects": len(defects_doc), "confirmed_defects": len(confirmed),
        "high_severity": sum(1 for d in defects_doc if d.get("severity") == "high"),
        "medium_severity": sum(1 for d in defects_doc if d.get("severity") == "medium"),
        "low_severity": sum(1 for d in defects_doc if d.get("severity") == "low"),
    })
    doc["summary"] = summary
    doc["passed"] = not [d for d in confirmed if d.get("severity") in ("high", "medium")]
    path.write_text(json.dumps(doc, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print("inyectado: %s (%d checks, passed=%s)" % (path, len(applied), doc["passed"]))
    return 0


def main(argv):
    if "--self-test" in argv:
        return self_test()
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("raiz", nargs="?", default=".")
    ap.add_argument("--briefs", action="store_true", help="validar tambien los briefs de .dev/features/")
    ap.add_argument("--previa", default=None, help="tasks.json previo (activa PLAN-CHECK-013)")
    ap.add_argument("--afectadas", nargs="*", default=None, help="features afectadas por el delta (con --previa)")
    ap.add_argument("--json", action="store_true", help="salida JSON estructurada")
    ap.add_argument("--inyectar-checks", action="store_true", help="fusionar los resultados en plan-inspection.json")
    args = ap.parse_args(argv)
    root = Path(args.raiz).resolve()
    code, found = run_checks(root, args.briefs, args.previa, args.afectadas, args.json)
    if args.inyectar_checks:
        rc = inject_checks(root, found)
        return rc or code
    return code


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
