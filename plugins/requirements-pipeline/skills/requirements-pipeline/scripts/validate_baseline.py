#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Validacion mecanica de la linea de base de requisitos: los checks que no requieren
juicio, sin tokens.

Corre en milisegundos la mitad automatizable de los tres checklists de inspeccion
(LEL, requisitos y diseno): integridad referencial, enums, ciclos, cobertura por ids,
desactualizacion de version refs, coherencia con el mapa y sincronia de las vistas
derivadas. Los checks de juicio (redaccion, atomicidad, metricas inventadas, formas
normales, coherencia semantica) siguen siendo de los subagentes `lel-inspection`,
`requirements-inspection` y `design-inspection`, que reciben estos resultados como
pre-verificados y corren en "modo juicio".

Checks mecanicos que cubre (mismos ids de los checklists):
  LEL-CHECK-001 id, nombre canonico y tipo permitido
  LEL-CHECK-002 nocion o pregunta abierta por simbolo
  LEL-CHECK-003 (parte mecanica) sujeto/objeto/verbo sin ningun impacto
  LEL-CHECK-005 alias_map apunta a simbolos existentes
  LEL-CHECK-006 (parte mecanica) alias del alias_map apuntando a mas de un simbolo
  LEL-CHECK-007 related_symbol_ids y referenced_symbol_ids existentes
  LEL-CHECK-008 preguntas bloqueantes con target_role o reason
  LEL-CHECK-011 (parte mecanica) simbolo sin ninguna evidencia
  LEL-CHECK-012 (parte mecanica) duplicados por singular/plural o variante de escritura
  REQ-CHECK-001 cobertura de escenarios active y summary coherente
  REQ-CHECK-002 trazabilidad: source_scenario_ids / lel_symbol_ids existentes
  REQ-CHECK-003 feature_group existente y requirement_ids exactos
  REQ-CHECK-004 depends_on existente, sin auto-dependencias ni ciclos
  REQ-CHECK-005 priority / estimated_effort / verification_method validos
  REQ-CHECK-006 (parte mecanica) al menos un criterio con given/when/then; AC-xxx unicos
  REQ-CHECK-008 (parte mecanica) category valida en los RNF
  REQ-CHECK-010 lel_version_ref / scenario_version_ref vigentes
  REQ-CHECK-011 (parte mecanica) preguntas bloqueantes con target_role y reason
  REQ-CHECK-012 coherencia con product-map.json y PBC pendientes
  REQ-CHECK-013 (parte mecanica) kind valido y enforced_by con criterios existentes
  REQ-CHECK-014 sincronia de requirements.md / scenarios.md
  DB-CHECK-001  clave primaria definida
  DB-CHECK-005  relaciones a entidades existentes con cardinalidad valida
  DB-CHECK-006  many_to_many directo
  DB-CHECK-007  (parte mecanica) entidad sin traza y nombres duplicados
  DB-CHECK-009  modulos, API y pantallas con requirement_ids existentes
  DB-CHECK-011  entity_ids de los modulos existentes
  DB-CHECK-013  sincronia de data-model.md / technical-design.md
  DB-CHECK-010  (parte mecanica) requirements_version_ref / data_model_version_ref vigentes

Solo stdlib, Python 3.8+. No modifica nada.

Uso:
  python validate_baseline.py [carpeta] [--solo lel requirements design] [--json]
  python validate_baseline.py --self-test

  carpeta  por defecto .dev/requirements

Exit 0: sin defectos high/medium (los low se listan). Exit 1: hay high/medium.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import unicodedata
from pathlib import Path

DERIVED_HEADER = re.compile(r"Derivado de `?(?P<json>[\w.-]+)`? version (?P<version>\d+)")
LEL_TYPES = {"sujeto", "objeto", "verbo", "estado"}
PRIORITIES = {"high", "medium", "low"}
EFFORTS = {"xs", "s", "m", "l", "xl"}
VERIFICATIONS = {"test", "demonstration", "inspection", "analysis"}
NFR_CATEGORIES = {"performance", "security", "usability", "reliability", "availability",
                  "maintainability", "portability", "scalability", "compliance", "other"}
BR_KINDS = {"invariant", "constraint", "derivation"}
REL_TYPES = {"one_to_one", "one_to_many", "many_to_one", "many_to_many"}

GROUPS = {
    "lel": ["LEL-CHECK-%03d" % i for i in (1, 2, 3, 5, 6, 7, 8, 11, 12)],
    "requirements": ["REQ-CHECK-%03d" % i for i in (1, 2, 3, 4, 5, 6, 8, 10, 11, 12, 13, 14)],
    "design": ["DB-CHECK-%03d" % i for i in (1, 5, 6, 7, 9, 10, 11, 13)],
}
JUDGMENT = {
    "lel": ["LEL-CHECK-%03d" % i for i in (4, 9, 10, 13, 14)],
    "requirements": ["REQ-CHECK-%03d" % i for i in (7, 9, 15)],
    "design": ["DB-CHECK-%03d" % i for i in (2, 3, 4, 8, 12)],
}

defects = []
checks_failed = set()
checks_skipped = {}


def defect(check, severity, target, description, bounce):
    defects.append({"check_id": check, "severity": severity, "target_id": target,
                    "description": description, "bounce": bounce})
    checks_failed.add(check)


def skip(check, reason):
    checks_skipped[check] = reason


def load(path, check, bounce):
    if not path.is_file():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except (ValueError, OSError) as exc:
        defect(check, "high", path.name, "JSON ilegible: %s" % exc, bounce)
        return None


def norm(s):
    s = unicodedata.normalize("NFKD", str(s or "")).encode("ascii", "ignore").decode("ascii").lower().strip()
    s = re.sub(r"[^a-z0-9]+", " ", s).strip()
    words = []
    for w in s.split():
        if len(w) > 3 and w.endswith("es"):
            w = w[:-2]
        elif len(w) > 2 and w.endswith("s"):
            w = w[:-1]
        words.append(w)
    return " ".join(words)


def req_items(doc):
    return (doc.get("functional_requirements") or []) + (doc.get("non_functional_requirements") or [])


def check_view(folder, md_name, doc, check, bounce="orquestador"):
    path = folder / md_name
    if not path.is_file():
        defect(check, "medium", md_name, "vista derivada ausente: re-correr render_baseline_docs.py", bounce)
        return
    m = DERIVED_HEADER.search(path.read_text(encoding="utf-8-sig")[:600])
    if not m or m.group("version") != str(doc.get("version")):
        defect(check, "medium", md_name,
               "encabezado de sincronia ausente o con version distinta de %s: re-correr render_baseline_docs.py"
               % doc.get("version"), bounce)


# ------------------------------------------------------------------------ LEL


def check_lel(lel):
    bounce = "lel-authoring"
    symbols = lel.get("symbols") or []
    sids = {s.get("id") for s in symbols}
    seen_ids = set()
    names_index = {}
    for s in symbols:
        sid = s.get("id")
        if not sid or not s.get("canonical_name") or s.get("type") not in LEL_TYPES:
            defect("LEL-CHECK-001", "high", sid or "?", "simbolo sin id, nombre canonico o con tipo invalido %r" % s.get("type"), bounce)
        if sid in seen_ids:
            defect("LEL-CHECK-001", "high", sid, "id de simbolo duplicado", bounce)
        seen_ids.add(sid)
        if not (s.get("notions") or s.get("open_questions")):
            defect("LEL-CHECK-002", "medium", sid, "simbolo sin nocion ni pregunta abierta que justifique el faltante", bounce)
        if s.get("type") in ("sujeto", "objeto", "verbo") and not s.get("impacts") and s.get("status", "active") == "active":
            defect("LEL-CHECK-003", "low", sid, "simbolo operativo sin ningun impacto (confirmar en modo juicio)", bounce)
        for ref in s.get("related_symbol_ids") or []:
            if ref not in sids:
                defect("LEL-CHECK-007", "high", sid, "related_symbol_ids cita %s inexistente" % ref, bounce)
        for imp in s.get("impacts") or []:
            for ref in imp.get("referenced_symbol_ids") or []:
                if ref not in sids:
                    defect("LEL-CHECK-007", "high", sid, "impacto %s cita %s inexistente" % (imp.get("id"), ref), bounce)
        evidence = any((e.get("evidence_refs") for e in (s.get("notions") or []) + (s.get("impacts") or [])))
        if not evidence and not (s.get("revision") or {}).get("created_from"):
            defect("LEL-CHECK-011", "low", sid, "simbolo sin ninguna evidencia (evidence_refs ni created_from)", bounce)
        for name in [s.get("canonical_name")] + list(s.get("names") or []) + list(s.get("aliases") or []):
            key = norm(name)
            if not key:
                continue
            names_index.setdefault(key, set()).add(sid)
    for key, owners in sorted(names_index.items()):
        if len(owners) > 1:
            defect("LEL-CHECK-012", "medium", ",".join(sorted(str(o) for o in owners)),
                   "posible duplicado por variante de escritura: '%s' aparece en mas de un simbolo" % key, bounce)
    alias_owner = {}
    for a in lel.get("alias_map") or []:
        if a.get("symbol_id") not in sids:
            defect("LEL-CHECK-005", "high", a.get("alias", "?"), "alias_map cita %s inexistente" % a.get("symbol_id"), bounce)
        alias_owner.setdefault(norm(a.get("alias")), set()).add(a.get("symbol_id"))
    for alias, owners in sorted(alias_owner.items()):
        if len(owners) > 1:
            defect("LEL-CHECK-006", "medium", alias, "alias apunta a mas de un simbolo: %s" % ", ".join(sorted(str(o) for o in owners)), bounce)
    for q in lel.get("open_questions") or []:
        if q.get("blocking") and not (q.get("target_role") or q.get("reason")):
            defect("LEL-CHECK-008", "medium", q.get("id", "?"), "pregunta bloqueante sin target_role ni reason", bounce)


# --------------------------------------------------------------- requisitos


def check_requirements(folder, reqs, scenarios, lel, pmap):
    bounce = "requirements-specification"
    items = req_items(reqs)
    rids = {r.get("id") for r in items}
    by_id = {r.get("id"): r for r in items}
    groups = reqs.get("feature_groups") or []
    gids = {g.get("id") for g in groups}
    scn_ids = {s.get("id") for s in (scenarios.get("scenarios") or [])} if scenarios else set()
    ep_ids = {e.get("id") for s in (scenarios.get("scenarios") or []) for e in (s.get("episodes") or [])} if scenarios else set()
    sym_ids = {s.get("id") for s in (lel.get("symbols") or [])} if lel else set()

    # 001 cobertura
    if scenarios is None:
        skip("REQ-CHECK-001", "scenarios.json no disponible")
    else:
        active_scn = {s.get("id") for s in scenarios.get("scenarios") or [] if s.get("status", "active") == "active"}
        covered = {sid for r in items if r.get("status", "active") != "deprecated" for sid in r.get("source_scenario_ids") or []}
        for sid in sorted(active_scn - covered):
            defect("REQ-CHECK-001", "high", sid, "escenario active sin requisito que lo cubra", bounce)
        summary = reqs.get("summary") or {}
        declared_unc = set(summary.get("uncovered_scenario_ids") or [])
        if declared_unc != (active_scn - covered):
            defect("REQ-CHECK-001", "medium", "summary.uncovered_scenario_ids",
                   "declara %s pero el contenido da %s" % (sorted(declared_unc), sorted(active_scn - covered)), bounce)

    ac_owner = {}
    for r in items:
        rid = r.get("id")
        functional = rid and rid.startswith("RF-")
        # 002 trazabilidad
        if functional:
            srcs = list(r.get("source_scenario_ids") or []) + list(r.get("source_episode_ids") or [])
            if not srcs:
                defect("REQ-CHECK-002", "high", rid, "requisito funcional sin source_scenario_ids ni source_episode_ids", bounce)
            if scenarios is not None:
                for s in r.get("source_scenario_ids") or []:
                    if s not in scn_ids:
                        defect("REQ-CHECK-002", "high", rid, "cita escenario %s inexistente" % s, bounce)
                for e in r.get("source_episode_ids") or []:
                    if e not in ep_ids:
                        defect("REQ-CHECK-002", "medium", rid, "cita episodio %s inexistente" % e, bounce)
        if lel is not None:
            for sym in r.get("lel_symbol_ids") or []:
                if sym not in sym_ids:
                    defect("REQ-CHECK-002", "medium", rid, "cita simbolo %s inexistente" % sym, bounce)
        # 003 feature
        if r.get("feature_group") not in gids:
            defect("REQ-CHECK-003", "high", rid, "feature_group %r no existe en feature_groups" % r.get("feature_group"), bounce)
        # 004 dependencias
        for dep in r.get("depends_on") or []:
            if dep == rid:
                defect("REQ-CHECK-004", "high", rid, "auto-dependencia", bounce)
            elif dep not in rids:
                defect("REQ-CHECK-004", "high", rid, "depends_on cita %s inexistente" % dep, bounce)
        # 005 campos de planificacion
        if r.get("status", "active") != "deprecated":
            if r.get("priority") not in PRIORITIES or r.get("estimated_effort") not in EFFORTS \
                    or r.get("verification_method") not in VERIFICATIONS:
                defect("REQ-CHECK-005", "high", rid, "priority/estimated_effort/verification_method faltante o invalido", bounce)
            # 006 mecanico
            acs = r.get("acceptance_criteria") or []
            if not any(ac.get("given") and ac.get("when") and ac.get("then") for ac in acs):
                defect("REQ-CHECK-006", "high", rid, "sin ningun criterio de aceptacion completo (given/when/then)", bounce)
        for ac in r.get("acceptance_criteria") or []:
            acid = ac.get("id")
            if acid in ac_owner and ac_owner[acid] != rid:
                defect("REQ-CHECK-006", "high", "%s/%s" % (rid, acid), "id de criterio repetido (ya usado en %s): la secuencia AC-xxx es global" % ac_owner[acid], bounce)
            ac_owner.setdefault(acid, rid)
        # 008 mecanico
        if not functional and r.get("category") not in NFR_CATEGORIES:
            defect("REQ-CHECK-008", "medium", rid, "category invalida %r" % r.get("category"), bounce)
    # ciclos
    color = {}

    def has_cycle(node, stack):
        color[node] = 1
        for nxt in by_id.get(node, {}).get("depends_on") or []:
            if nxt not in by_id:
                continue
            if color.get(nxt) == 1:
                stack.append((node, nxt))
                return True
            if color.get(nxt, 0) == 0 and has_cycle(nxt, stack):
                return True
        color[node] = 2
        return False

    for rid in sorted(r for r in rids if r):
        if color.get(rid, 0) == 0:
            stack = []
            if has_cycle(rid, stack):
                defect("REQ-CHECK-004", "high", stack[0][0], "ciclo de dependencias %s -> %s" % stack[0], bounce)
                break
    # 003 requirement_ids exactos
    for g in groups:
        declared = set(g.get("requirement_ids") or [])
        # las reglas de negocio con feature_group tambien forman parte del contenido del grupo
        real = {r.get("id") for r in items + (reqs.get("business_rules") or []) if r.get("feature_group") == g.get("id")}
        if declared != real:
            defect("REQ-CHECK-003", "medium", g.get("id", "?"),
                   "requirement_ids declara %s pero el contenido da %s" % (sorted(declared), sorted(real)), bounce)
    # 010 version refs
    meta = reqs.get("metadata") or {}
    if lel is not None and str(meta.get("lel_version_ref")) != str(lel.get("version")):
        defect("REQ-CHECK-010", "high", "lel_version_ref", "cita %s pero lel.json esta en %s" % (meta.get("lel_version_ref"), lel.get("version")), bounce)
    if scenarios is not None and str(meta.get("scenario_version_ref")) != str(scenarios.get("version")):
        defect("REQ-CHECK-010", "high", "scenario_version_ref", "cita %s pero scenarios.json esta en %s" % (meta.get("scenario_version_ref"), scenarios.get("version")), bounce)
    # 011 mecanico
    for q in reqs.get("open_questions") or []:
        if q.get("blocking") and not (q.get("target_role") and q.get("reason")):
            defect("REQ-CHECK-011", "medium", q.get("id", "?"), "pregunta bloqueante sin target_role o reason", bounce)
    # 012 mapa
    if pmap is None:
        skip("REQ-CHECK-012", "product-map.json no disponible")
    else:
        feats = {f.get("id"): f for f in pmap.get("features") or []}
        for g in groups:
            if g.get("id") not in feats:
                defect("REQ-CHECK-012", "high", g.get("id", "?"), "feature_group no existe en product-map.json", bounce)
        for r in items:
            f = feats.get(r.get("feature_group"))
            if f and f.get("status") in ("stub", "deprecated"):
                defect("REQ-CHECK-012", "medium", "product-map.json/%s" % f.get("id"),
                       "requisito %s pertenece a una feature en estado %s (defecto de orquestacion del mapa)" % (r.get("id"), f.get("status")), "orquestador")
        with_reqs = {r.get("feature_group") for r in items}
        for fid, f in sorted(feats.items()):
            if f.get("status") in ("elaborated", "baselined") and fid not in with_reqs:
                defect("REQ-CHECK-012", "medium", fid, "feature %s sin ningun requisito" % f.get("status"), bounce)
        for pbc in reqs.get("proposed_baseline_changes") or []:
            if pbc.get("status") == "pending":
                defect("REQ-CHECK-012", "medium", pbc.get("id", "?"), "cambio propuesto sobre lo baselineado sin resolver (falta la confirmacion del usuario)", "orquestador")
    # 013 mecanico
    for br in reqs.get("business_rules") or []:
        if "kind" in br and br.get("kind") not in BR_KINDS:  # sin kind: artefacto de una version anterior, lo evalua el modo juicio
            defect("REQ-CHECK-013", "medium", br.get("id", "?"), "kind invalido %r" % br.get("kind"), bounce)
        for ref in br.get("enforced_by") or []:
            rid, _, acid = str(ref).partition("/")
            if rid not in rids or (acid and ac_owner.get(acid) != rid):
                defect("REQ-CHECK-013", "medium", br.get("id", "?"), "enforced_by cita %s que no existe" % ref, bounce)
    # 014 vistas
    check_view(folder, "requirements.md", reqs, "REQ-CHECK-014")
    if scenarios is not None:
        check_view(folder, "scenarios.md", scenarios, "REQ-CHECK-014")


# ------------------------------------------------------------------- diseno


def check_design(folder, dm, td, reqs, lel):
    bounce = "technical-design"
    rids = {r.get("id") for r in req_items(reqs)} if reqs else set()
    # las reglas de negocio (RN-xxx) tambien son citables desde el diseno
    rids |= {br.get("id") for br in (reqs.get("business_rules") or [])} if reqs else set()
    gids = {g.get("id") for g in (reqs.get("feature_groups") or [])} if reqs else set()
    sym_ids = {s.get("id") for s in (lel.get("symbols") or [])} if lel else set()
    ent_ids = set()
    if dm is not None:
        entities = dm.get("entities") or []
        ent_ids = {e.get("id") for e in entities}
        names = {}
        for e in entities:
            eid = e.get("id")
            if not e.get("primary_key"):
                defect("DB-CHECK-001", "high", eid, "entidad sin clave primaria", bounce)
            if not (e.get("source_requirement_ids") or e.get("lel_symbol_id")):
                defect("DB-CHECK-007", "medium", eid, "entidad sin traza a requisito ni simbolo del LEL", bounce)
            if reqs is not None:
                for rid in e.get("source_requirement_ids") or []:
                    if rid not in rids:
                        defect("DB-CHECK-007", "medium", eid, "source_requirement_ids cita %s inexistente" % rid, bounce)
            if lel is not None and e.get("lel_symbol_id") and e.get("lel_symbol_id") not in sym_ids:
                defect("DB-CHECK-007", "medium", eid, "lel_symbol_id %s inexistente" % e.get("lel_symbol_id"), bounce)
            names.setdefault(norm(e.get("name")), []).append(eid)
        for key, owners in sorted(names.items()):
            if len(owners) > 1:
                defect("DB-CHECK-007", "medium", ",".join(owners), "entidades con el mismo nombre normalizado '%s'" % key, bounce)
        for rel in dm.get("relationships") or []:
            relid = rel.get("id", "?")
            if rel.get("from_entity_id") not in ent_ids or rel.get("to_entity_id") not in ent_ids:
                defect("DB-CHECK-005", "high", relid, "relacion a entidad inexistente", bounce)
            if rel.get("type") not in REL_TYPES:
                defect("DB-CHECK-005", "high", relid, "cardinalidad invalida %r" % rel.get("type"), bounce)
            elif rel.get("type") == "many_to_many":
                # resuelta si declara la entidad intermedia (campo via/through/join_entity o "(via X)" en el nombre)
                resolved = any(rel.get(k) for k in ("via", "through", "join_entity", "intermediate_entity")) \
                    or "via " in str(rel.get("name", "")).lower()
                if not resolved:
                    defect("DB-CHECK-006", "medium", relid, "many_to_many directo: resolver con una entidad intermedia", bounce)
        meta = dm.get("metadata") or {}
        if reqs is not None and str(meta.get("requirements_version_ref")) != str(reqs.get("version")):
            defect("DB-CHECK-010", "high", "data-model.json/requirements_version_ref",
                   "cita %s pero requirements.json esta en %s" % (meta.get("requirements_version_ref"), reqs.get("version")), bounce)
        check_view(folder, "data-model.md", dm, "DB-CHECK-013")
    if td is not None:
        mod_ids = {m.get("id") for m in td.get("modules") or []}
        for kind, key in (("module", "modules"), ("api", "api_contracts"), ("screen", "screens"), ("decision", "decisions")):
            for item in td.get(key) or []:
                iid = item.get("id", "?")
                cited = item.get("requirement_ids") or []
                if not cited and kind != "decision":
                    defect("DB-CHECK-009", "medium", iid, "%s sin requirement_ids" % kind, bounce)
                if reqs is not None:
                    for rid in cited:
                        if rid not in rids:
                            defect("DB-CHECK-009", "high", iid, "cita requisito %s inexistente" % rid, bounce)
        for m in td.get("modules") or []:
            mid = m.get("id", "?")
            if dm is not None:
                for eid in m.get("entity_ids") or []:
                    if eid not in ent_ids:
                        defect("DB-CHECK-011", "high", mid, "entity_ids cita %s inexistente" % eid, bounce)
            for dep in m.get("depends_on") or []:
                if dep not in mod_ids:
                    defect("DB-CHECK-011", "medium", mid, "depends_on cita modulo %s inexistente" % dep, bounce)
            if reqs is not None and m.get("feature_group") and m.get("feature_group") not in gids:
                defect("DB-CHECK-009", "medium", mid, "feature_group %s no existe en requirements.json" % m.get("feature_group"), bounce)
        meta = td.get("metadata") or {}
        if reqs is not None and str(meta.get("requirements_version_ref")) != str(reqs.get("version")):
            defect("DB-CHECK-010", "high", "technical-design.json/requirements_version_ref",
                   "cita %s pero requirements.json esta en %s" % (meta.get("requirements_version_ref"), reqs.get("version")), bounce)
        if dm is not None and str(meta.get("data_model_version_ref")) != str(dm.get("version")):
            defect("DB-CHECK-010", "high", "technical-design.json/data_model_version_ref",
                   "cita %s pero data-model.json esta en %s" % (meta.get("data_model_version_ref"), dm.get("version")), bounce)
        check_view(folder, "technical-design.md", td, "DB-CHECK-013")


# ------------------------------------------------------------------ corrida


def run_checks(folder, groups, as_json, quiet=False):
    del defects[:]
    checks_failed.clear()
    checks_skipped.clear()
    folder = Path(folder)
    lel = load(folder / "lel.json", "LEL-CHECK-001", "lel-authoring")
    scenarios = load(folder / "scenarios.json", "REQ-CHECK-001", "scenario-modeling")
    reqs = load(folder / "requirements.json", "REQ-CHECK-002", "requirements-specification")
    pmap = load(folder / "product-map.json", "REQ-CHECK-012", "product-mapping")
    dm = load(folder / "data-model.json", "DB-CHECK-001", "technical-design")
    td = load(folder / "technical-design.json", "DB-CHECK-009", "technical-design")

    if "lel" in groups:
        if lel is None:
            for c in GROUPS["lel"]:
                skip(c, "lel.json no disponible")
        else:
            check_lel(lel)
    if "requirements" in groups:
        if reqs is None:
            for c in GROUPS["requirements"]:
                skip(c, "requirements.json no disponible")
        else:
            check_requirements(folder, reqs, scenarios, lel, pmap)
    if "design" in groups:
        if dm is None and td is None:
            for c in GROUPS["design"]:
                skip(c, "data-model.json / technical-design.json no disponibles")
        else:
            check_design(folder, dm, td, reqs, lel)

    checks_ok = []
    for g in groups:
        for c in GROUPS[g]:
            if c not in checks_failed and c not in checks_skipped:
                checks_ok.append(c)
    judgment = [c for g in groups for c in JUDGMENT[g]]
    blocking = [d for d in defects if d["severity"] in ("high", "medium")]
    if not quiet:
        if as_json:
            print(json.dumps({"passed": not blocking, "checks_ok": checks_ok, "checks_skipped": checks_skipped,
                              "checks_judgment": judgment, "defects": defects}, ensure_ascii=False, indent=2))
        else:
            for d in defects:
                print("DEF [%s][%s] %s: %s (rebota a %s)" % (d["check_id"], d["severity"], d["target_id"], d["description"], d["bounce"]))
            for c, reason in sorted(checks_skipped.items()):
                print("skip %s: %s" % (c, reason))
            print("checks ok: %s" % (", ".join(checks_ok) or "ninguno"))
            print("checks de juicio (los evalua el subagente): %s" % ", ".join(judgment))
            print("NO PASA: %d defecto(s) high/medium." % len(blocking) if blocking
                  else "PASA la validacion mecanica (%d defecto(s) low informativos)." % len(defects))
    return (1 if blocking else 0), list(defects)


# ---------------------------------------------------------------- self-test


def self_test():
    import shutil
    import tempfile

    def fixture(root, break_it):
        root.mkdir(parents=True, exist_ok=True)
        lel = {"version": 2, "symbols": [
            {"id": "LEL-001", "canonical_name": "socio", "type": "sujeto", "status": "active",
             "notions": [{"id": "NOT-001", "statement": "n", "evidence_refs": ["SRC-SEC-001"]}],
             "impacts": [{"id": "IMP-001", "statement": "i", "evidence_refs": ["SRC-SEC-001"], "referenced_symbol_ids": []}]},
            {"id": "LEL-002", "canonical_name": "cuota", "type": "objeto", "status": "active",
             "notions": [{"id": "NOT-002", "statement": "n", "evidence_refs": ["SRC-SEC-001"]}],
             "impacts": [{"id": "IMP-002", "statement": "i", "evidence_refs": ["SRC-SEC-001"]}]}],
            "alias_map": [{"alias": "afiliado", "symbol_id": "LEL-001"}], "open_questions": []}
        scn = {"version": 3, "scenarios": [{"id": "SCN-001", "status": "active", "episodes": [{"id": "EP-001"}]}],
               "summary": {}}
        reqs = {"version": 4, "metadata": {"lel_version_ref": "2", "scenario_version_ref": "3"},
                "summary": {"uncovered_scenario_ids": []},
                "feature_groups": [{"id": "FG-01", "requirement_ids": ["RF-001", "RNF-001"]}],
                "functional_requirements": [{"id": "RF-001", "feature_group": "FG-01", "status": "active",
                                             "priority": "high", "estimated_effort": "m", "verification_method": "test",
                                             "depends_on": [], "source_scenario_ids": ["SCN-001"], "lel_symbol_ids": ["LEL-001"],
                                             "acceptance_criteria": [{"id": "AC-001", "given": "g", "when": "w", "then": "t"}]}],
                "non_functional_requirements": [{"id": "RNF-001", "feature_group": "FG-01", "status": "active", "category": "security",
                                                 "priority": "medium", "estimated_effort": "s", "verification_method": "analysis",
                                                 "acceptance_criteria": [{"id": "AC-002", "given": "g", "when": "w", "then": "t"}]}],
                "business_rules": [{"id": "BR-001", "kind": "invariant", "enforced_by": ["RF-001/AC-001"]}],
                "open_questions": [], "proposed_baseline_changes": []}
        pmap = {"version": 1, "features": [{"id": "FG-01", "status": "elaborated"}]}
        dm = {"version": 1, "metadata": {"requirements_version_ref": "4"},
              "entities": [{"id": "ENT-001", "name": "Socio", "lel_symbol_id": "LEL-001", "primary_key": ["id"], "source_requirement_ids": ["RF-001"]}],
              "relationships": []}
        td = {"version": 1, "metadata": {"requirements_version_ref": "4", "data_model_version_ref": "1"},
              "modules": [{"id": "MOD-001", "feature_group": "FG-01", "requirement_ids": ["RF-001"], "entity_ids": ["ENT-001"], "depends_on": []}],
              "api_contracts": [], "screens": [], "decisions": []}
        if break_it:
            lel["alias_map"].append({"alias": "x", "symbol_id": "LEL-999"})          # LEL-005
            reqs["functional_requirements"][0]["depends_on"] = ["RF-001"]             # REQ-004
            reqs["non_functional_requirements"][0]["category"] = "magia"              # REQ-008
            dm["entities"][0]["primary_key"] = []                                     # DB-001
            td["modules"][0]["entity_ids"] = ["ENT-404"]                              # DB-011
        for name, doc in (("lel", lel), ("scenarios", scn), ("requirements", reqs), ("product-map", pmap),
                          ("data-model", dm), ("technical-design", td)):
            (root / ("%s.json" % name)).write_text(json.dumps(doc), encoding="utf-8")
            (root / ("%s.md" % name)).write_text("# x\n\n> Derivado de `%s.json` version %s — no editar a mano.\n"
                                                 % (name, doc["version"]), encoding="utf-8")

    failures = 0
    for break_it, expect_fail in ((False, False), (True, True)):
        tmp = Path(tempfile.mkdtemp(prefix="validate-baseline-"))
        try:
            fixture(tmp, break_it)
            code, found = run_checks(tmp, ["lel", "requirements", "design"], False, quiet=True)
            label = "fixture rota" if break_it else "fixture consistente"
            if (code != 0) != expect_fail:
                print("SELF-TEST FALLO (%s): exit=%d defectos=%s" % (label, code, found))
                failures += 1
            else:
                print("self-test ok (%s): %d defecto(s), exit %d" % (label, len(found), code))
            if break_it:
                got = {d["check_id"] for d in found}
                expected = {"LEL-CHECK-005", "REQ-CHECK-004", "REQ-CHECK-008", "DB-CHECK-001", "DB-CHECK-011"}
                if not expected <= got:
                    print("SELF-TEST FALLO: esperaba %s, encontro %s" % (sorted(expected), sorted(got)))
                    failures += 1
                else:
                    print("self-test ok (checks detectados: %s)" % ", ".join(sorted(got)))
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
    print("SELF-TEST: %d fallo(s)" % failures)
    return 1 if failures else 0


def main(argv):
    if "--self-test" in argv:
        return self_test()
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("carpeta", nargs="?", default=".dev/requirements")
    ap.add_argument("--solo", nargs="+", choices=sorted(GROUPS), default=None, help="validar solo estos grupos")
    ap.add_argument("--json", action="store_true", help="salida JSON estructurada")
    args = ap.parse_args(argv)
    folder = Path(args.carpeta)
    if not folder.is_dir():
        print("No existe la carpeta: %s" % folder)
        return 1
    code, _ = run_checks(folder, args.solo or ["lel", "requirements", "design"], args.json)
    return code


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
