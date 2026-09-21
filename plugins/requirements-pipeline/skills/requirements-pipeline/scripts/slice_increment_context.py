#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Pre-cortador de contexto para un incremento: una tajada JSON por feature.

Los agentes de elaboracion (scenario-modeling, requirements-specification,
technical-design) corren en paralelo, uno por feature, y cada uno necesita solo la
porcion de la linea de base que toca su feature. Este script extrae esa tajada de
forma determinista, cruzando por ids, y la escribe en
`.dev/requirements/.inc-context/FG-xx.json`. Asi cada agente lee un archivo chico en
vez de releer la linea de base completa: el paralelismo no multiplica el input y el
costo por incremento deja de crecer con los incrementos anteriores.

Que incluye cada tajada:
  - la feature del product-map con sus escenarios stub
  - los simbolos del LEL que la feature cita (y los que sus stubs nombran), completos,
    mas un indice compacto (id, nombre, tipo) de TODOS los simbolos, para citar sin leer
  - sus escenarios ya elaborados (si los hay) y un indice de todos los escenarios
  - sus requisitos, los vecinos por depends_on, las reglas que los hacen cumplir, sus
    feature_groups, y un indice de todos los requisitos
  - el diseno que la toca: entidades (por simbolo o requisito), relaciones, modulos,
    API, pantallas, ADRs y el stack completo, mas indices de entidades y modulos
  - el contexto de soporte del intake completo (es chico y es la fuente tecnica)
  - las secciones de fuente que la feature cita (solo resumen)
  - las preguntas del cuestionario que la afectan y toda la checklist de no
    funcionales, con las respuestas del stakeholder si estan
  - las versiones vigentes de cada artefacto y el proximo numero libre por prefijo
    de id (para ids globales) o la convencion de ids provisionales (en paralelo)

Con --indice escribe ademas `.inc-context/index.json`: un indice compacto de TODA la
linea de base (ids, nombres, estados, enunciados de una linea) para que
`product-mapping` detecte solapamientos y las inspecciones de juicio verifiquen
vocabulario y referencias sin abrir los canonicos. Solo con --indice (sin --features)
product-map.json es opcional: en el primer descubrimiento la inspeccion del LEL corre
en paralelo con `product-mapping`, que es quien lo crea, y el indice sale sin
features ni propuestas.

Los artefactos ausentes se saltean con aviso. La carpeta `.inc-context/` es temporal:
se borra en el cierre con --limpiar.

Solo stdlib, Python 3.8+. No modifica los artefactos canonicos.

Uso:
  python slice_increment_context.py [carpeta] --features FG-01 FG-02 [--corrida INC-003]
                                    [--pipeline-version X.Y.Z] [--indice]
  python slice_increment_context.py [carpeta] --indice
  python slice_increment_context.py [carpeta] --limpiar
  python slice_increment_context.py --self-test

  carpeta  por defecto .dev/requirements

Exit 0 con las tajadas escritas; exit 1 si falta una feature, o product-map.json
cuando se piden tajadas (--features).
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import sys
import unicodedata
from pathlib import Path

CONTEXT_DIR = ".inc-context"
GLOBAL_ID = re.compile(r"^((?:[A-Z]+-)*[A-Z]+)-(\d+)$")
ID_PREFIXES = ["SCN", "EP", "ACT", "RES", "EXC", "RF", "RNF", "AC", "BR", "Q", "ENT", "REL", "MOD", "API", "SCR", "ADR", "PBC"]


def load(path, required=False):
    if not path.is_file():
        if required:
            print("ERROR: no existe %s" % path)
            sys.exit(1)
        print("aviso: no existe %s — la tajada sale sin esa fuente" % path)
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except (ValueError, OSError) as exc:
        if required:
            print("ERROR: %s ilegible: %s" % (path, exc))
            sys.exit(1)
        print("aviso: %s ilegible (%s) — la tajada sale sin esa fuente" % (path, exc))
        return None


def norm(s):
    return unicodedata.normalize("NFKD", str(s or "")).encode("ascii", "ignore").decode("ascii").lower()


def req_items(doc):
    return (doc.get("functional_requirements") or []) + (doc.get("non_functional_requirements") or [])


def max_ids(docs):
    maxes = {p: 0 for p in ID_PREFIXES}

    def walk(obj):
        if isinstance(obj, str):
            m = GLOBAL_ID.match(obj)
            if m and m.group(1) in maxes:
                maxes[m.group(1)] = max(maxes[m.group(1)], int(m.group(2)))
        elif isinstance(obj, list):
            for x in obj:
                walk(x)
        elif isinstance(obj, dict):
            for v in obj.values():
                walk(v)
    for d in docs:
        if d is not None:
            walk(d)
    return {p: n + 1 for p, n in maxes.items()}


def answers_for(answers_text, qids):
    """Bloques de stakeholder-answers.md por QST-xxx (texto entre una cita y la siguiente)."""
    if not answers_text:
        return {}
    parts = re.split(r"(?m)^(?=.*\bQST-\d+\b)", answers_text)
    out = {}
    for part in parts:
        m = re.search(r"\bQST-\d+\b", part)
        if m and m.group(0) in qids:
            out[m.group(0)] = part.strip()
    return out


def slice_feature(fid, docs, corrida, pipeline_version, parallel):
    pmap, lel, scn, reqs, dm, td, ctx, inv, qst, answers = docs
    feature = next((f for f in pmap.get("features") or [] if f.get("id") == fid), None)
    if feature is None:
        print("ERROR: la feature %s no existe en product-map.json" % fid)
        sys.exit(1)
    stub_ids = {s.get("id") for s in feature.get("scenario_stubs") or []}
    evidence = set(feature.get("evidence_refs") or [])
    for s in feature.get("scenario_stubs") or []:
        evidence |= set(s.get("evidence_refs") or [])

    # LEL
    sym_ids = set(feature.get("lel_symbol_ids") or [])
    lel_symbols, lel_index = [], []
    if lel is not None:
        stub_text = norm(" ".join(
            "%s %s %s" % (s.get("title", ""), s.get("goal", ""), " ".join(s.get("actors") or []))
            for s in feature.get("scenario_stubs") or []) + " " + feature.get("name", "") + " " + feature.get("description", ""))
        for s in lel.get("symbols") or []:
            names = [s.get("canonical_name")] + list(s.get("names") or []) + list(s.get("aliases") or [])
            if s.get("id") not in sym_ids and any(norm(n) and norm(n) in stub_text for n in names if n):
                sym_ids.add(s.get("id"))
        for s in lel.get("symbols") or []:
            lel_index.append({"id": s.get("id"), "canonical_name": s.get("canonical_name"), "type": s.get("type"), "status": s.get("status", "active")})
            if s.get("id") in sym_ids:
                lel_symbols.append(s)

    # escenarios
    scenarios, scenario_index = [], []
    if scn is not None:
        for s in scn.get("scenarios") or []:
            scenario_index.append({"id": s.get("id"), "title": s.get("title"), "status": s.get("status", "active")})
            if s.get("id") in stub_ids:
                scenarios.append(s)
        related = {r for s in scenarios for r in (s.get("related_scenario_ids") or [])}
        related |= {e.get("referenced_scenario_id") for s in scenarios for e in (s.get("episodes") or []) if e.get("referenced_scenario_id")}
        for s in scn.get("scenarios") or []:
            if s.get("id") in related and s.get("id") not in stub_ids:
                scenarios.append(s)

    # requisitos
    requirements, req_index, rules, groups = [], [], [], []
    own_req_ids = set()
    if reqs is not None:
        items = req_items(reqs)
        own = [r for r in items if r.get("feature_group") == fid or (set(r.get("source_scenario_ids") or []) & stub_ids)]
        own_req_ids = {r.get("id") for r in own}
        neighbor_ids = {d for r in own for d in (r.get("depends_on") or [])} - own_req_ids
        neighbor_ids |= {r.get("id") for r in items if set(r.get("depends_on") or []) & own_req_ids} - own_req_ids
        for r in items:
            req_index.append({"id": r.get("id"), "title": r.get("title"), "feature_group": r.get("feature_group"), "status": r.get("status", "active")})
            if r.get("id") in own_req_ids:
                requirements.append(r)
            elif r.get("id") in neighbor_ids:
                requirements.append({k: r.get(k) for k in ("id", "title", "statement", "feature_group", "status", "depends_on", "acceptance_criteria") if k in r})
        for br in reqs.get("business_rules") or []:
            if any(str(ref).split("/", 1)[0] in own_req_ids for ref in br.get("enforced_by") or []) \
                    or set(br.get("source_scenario_ids") or []) & stub_ids:
                rules.append(br)
        groups = [g for g in reqs.get("feature_groups") or [] if g.get("id") == fid]
        req_sym = {sid for r in own for sid in r.get("lel_symbol_ids") or []}
        if lel is not None:
            for s in lel.get("symbols") or []:
                if s.get("id") in req_sym and s.get("id") not in sym_ids:
                    lel_symbols.append(s)
                    sym_ids.add(s.get("id"))

    # diseno
    design = {"entities": [], "relationships": [], "modules": [], "api_contracts": [], "screens": [], "decisions": [], "stack": []}
    entity_index, module_index = [], []
    ent_ids = set()
    if dm is not None:
        for e in dm.get("entities") or []:
            entity_index.append({"id": e.get("id"), "name": e.get("name"), "lel_symbol_id": e.get("lel_symbol_id")})
            if e.get("lel_symbol_id") in sym_ids or set(e.get("source_requirement_ids") or []) & own_req_ids:
                design["entities"].append(e)
                ent_ids.add(e.get("id"))
        design["relationships"] = [r for r in dm.get("relationships") or []
                                   if r.get("from_entity_id") in ent_ids or r.get("to_entity_id") in ent_ids]
    if td is not None:
        design["stack"] = td.get("stack") or []
        for m in td.get("modules") or []:
            module_index.append({"id": m.get("id"), "name": m.get("name"), "feature_group": m.get("feature_group")})
            if m.get("feature_group") == fid or set(m.get("requirement_ids") or []) & own_req_ids or set(m.get("entity_ids") or []) & ent_ids:
                design["modules"].append(m)
        for key in ("api_contracts", "screens", "decisions"):
            design[key] = [x for x in td.get(key) or [] if set(x.get("requirement_ids") or []) & own_req_ids]

    # fuentes y contexto
    sections = []
    if inv is not None:
        sections = [{k: s.get(k) for k in ("id", "title", "source", "original_source", "content_type", "summary")}
                    for s in inv.get("sections") or [] if s.get("id") in evidence]
    context_items = (ctx.get("items") or []) if ctx is not None else []

    # cuestionario
    questions = []
    if qst is not None:
        for q in qst.get("questions") or []:
            if q.get("source_kind") == "nfr_checklist" or set(q.get("related_symbol_ids") or []) & sym_ids:
                questions.append(q)
    qids = {q.get("id") for q in questions}
    answered = answers_for(answers, qids)

    versions = {name: (doc or {}).get("version") for name, doc in (
        ("lel", lel), ("scenarios", scn), ("requirements", reqs), ("data-model", dm),
        ("technical-design", td), ("product-map", pmap), ("stakeholder-questions", qst))}

    return {
        "pipeline_version": pipeline_version,
        "run_id": corrida,
        "feature_id": fid,
        "feature": feature,
        "id_policy": {
            "mode": "parallel" if parallel else "sequential",
            "next_free": max_ids([scn, reqs, dm, td, pmap]),
            "provisional_format": "PREFIJO-%s#n (ej. SCN-%s#1, RF-%s#2, AC-%s#7); apply_delta.py los renumera al mergear"
                                  % ((fid.replace("-", ""),) * 4),
            "note": "en modo parallel NO uses ids globales nuevos: escribi un delta con ids provisionales; "
                    "los ids que ya existen (stubs SCN-xx, FG-xx, requisitos previos) se citan tal cual",
        },
        "versions": versions,
        "lel": {"symbols": lel_symbols, "index": lel_index},
        "scenarios": {"items": scenarios, "index": scenario_index, "stub_ids": sorted(stub_ids)},
        "requirements": {"items": requirements, "own_ids": sorted(own_req_ids), "feature_groups": groups,
                         "business_rules": rules, "index": req_index},
        "design": dict(design, entity_index=entity_index, module_index=module_index),
        "supporting_context": context_items,
        "source_sections": sections,
        "questionnaire": {"questions": questions, "answers": answered},
    }


def build_index(docs, pipeline_version):
    pmap, lel, scn, reqs, dm, td, ctx, inv, qst, answers = docs
    pick = lambda item, keys: {k: item.get(k) for k in keys if k in item}
    index = {
        "pipeline_version": pipeline_version,
        "versions": {name: (doc or {}).get("version") for name, doc in (
            ("product-map", pmap), ("lel", lel), ("scenarios", scn), ("requirements", reqs),
            ("data-model", dm), ("technical-design", td))},
        "features": [dict(pick(f, ("id", "name", "status", "priority", "value")),
                          scenario_stubs=[pick(s, ("id", "title", "status")) for s in f.get("scenario_stubs") or []])
                     for f in (pmap.get("features") or [])] if pmap else [],
        "pending_proposals": [pick(p, ("id", "affects_id", "summary", "status")) for p in (pmap.get("pending_proposals") or [])] if pmap else [],
        "lel": [pick(s, ("id", "canonical_name", "type", "status", "aliases")) for s in (lel.get("symbols") or [])] if lel else [],
        "scenarios": [pick(s, ("id", "title", "goal", "status", "scenario_type")) for s in (scn.get("scenarios") or [])] if scn else [],
        "requirements": [pick(r, ("id", "title", "statement", "feature_group", "status", "priority", "depends_on"))
                         for r in req_items(reqs)] if reqs else [],
        "business_rules": [pick(b, ("id", "statement", "kind", "status")) for b in (reqs.get("business_rules") or [])] if reqs else [],
        "entities": [pick(e, ("id", "name", "lel_symbol_id")) for e in (dm.get("entities") or [])] if dm else [],
        "modules": [pick(m, ("id", "name", "feature_group")) for m in (td.get("modules") or [])] if td else [],
        "decisions": [pick(d, ("id", "title", "status")) for d in (td.get("decisions") or [])] if td else [],
    }
    return index


# ------------------------------------------------------------------ main


def run(folder, features, corrida, pipeline_version, parallel, indice=False):
    # el indice solo no necesita el mapa: en el DSC inicial todavia no existe
    pmap = load(folder / "product-map.json", required=bool(features))
    docs = (
        pmap,
        load(folder / "lel.json"),
        load(folder / "scenarios.json"),
        load(folder / "requirements.json"),
        load(folder / "data-model.json"),
        load(folder / "technical-design.json"),
        load(folder / "supporting-context.json"),
        load(folder / "source-inventory.json"),
        load(folder / "stakeholder-questions.json"),
        (folder / "stakeholder-answers.md").read_text(encoding="utf-8-sig") if (folder / "stakeholder-answers.md").is_file() else "",
    )
    ctx_dir = folder / CONTEXT_DIR
    ctx_dir.mkdir(parents=True, exist_ok=True)
    if indice:
        dest = ctx_dir / "index.json"
        dest.write_text(json.dumps(build_index(docs, pipeline_version), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print("indice: %s" % dest)
    for fid in features or []:
        data = slice_feature(fid, docs, corrida, pipeline_version, parallel)
        dest = ctx_dir / ("%s.json" % fid)
        dest.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print("tajada: %s (%d simbolos, %d escenarios, %d requisitos, %d entidades)" % (
            dest, len(data["lel"]["symbols"]), len(data["scenarios"]["items"]),
            len(data["requirements"]["items"]), len(data["design"]["entities"])))
    print("Listo: %d tajada(s) en %s — carpeta temporal, borrar con --limpiar en el cierre." % (len(features or []), ctx_dir))
    return 0


def clean(folder):
    ctx_dir = folder / CONTEXT_DIR
    if ctx_dir.exists():
        shutil.rmtree(ctx_dir)
        print("borrado: %s" % ctx_dir)
    else:
        print("nada que borrar: %s no existe" % ctx_dir)
    return 0


def self_test():
    import tempfile
    failures = 0

    def check(cond, label):
        nonlocal failures
        print("self-test %s: %s" % ("ok" if cond else "FALLO", label))
        if not cond:
            failures += 1

    tmp = Path(tempfile.mkdtemp(prefix="slice-inc-"))
    try:
        w = lambda name, doc: (tmp / name).write_text(json.dumps(doc), encoding="utf-8")
        w("product-map.json", {"version": 2, "features": [
            {"id": "FG-01", "name": "Turnos", "status": "stub", "lel_symbol_ids": ["LEL-001"], "evidence_refs": ["SRC-SEC-001"],
             "scenario_stubs": [{"id": "SCN-001", "title": "Reservar turno", "goal": "g", "actors": ["socio"], "evidence_refs": ["SRC-SEC-002"]}]},
            {"id": "FG-02", "name": "Pagos", "status": "baselined", "lel_symbol_ids": ["LEL-003"],
             "scenario_stubs": [{"id": "SCN-002", "title": "Pagar cuota", "goal": "g", "actors": []}]}]})
        w("lel.json", {"version": 5, "symbols": [
            {"id": "LEL-001", "canonical_name": "turno", "type": "objeto"},
            {"id": "LEL-002", "canonical_name": "socio", "type": "sujeto"},
            {"id": "LEL-003", "canonical_name": "cuota", "type": "objeto"}]})
        w("scenarios.json", {"version": 3, "scenarios": [
            {"id": "SCN-002", "title": "Pagar cuota", "status": "active", "related_scenario_ids": []}]})
        w("requirements.json", {"version": 4, "feature_groups": [{"id": "FG-02", "requirement_ids": ["RF-001"]}],
                                "functional_requirements": [{"id": "RF-001", "feature_group": "FG-02", "source_scenario_ids": ["SCN-002"],
                                                             "lel_symbol_ids": ["LEL-003"], "depends_on": [],
                                                             "acceptance_criteria": [{"id": "AC-004"}]}],
                                "non_functional_requirements": [], "business_rules": [{"id": "BR-001", "enforced_by": ["RF-001/AC-004"]}]})
        w("data-model.json", {"version": 1, "entities": [{"id": "ENT-001", "name": "Turno", "lel_symbol_id": "LEL-001"},
                                                          {"id": "ENT-002", "name": "Cuota", "lel_symbol_id": "LEL-003"}],
                              "relationships": [{"id": "REL-001", "from_entity_id": "ENT-001", "to_entity_id": "ENT-002"}]})
        w("technical-design.json", {"version": 1, "stack": [{"layer": "db", "technology": "pg"}],
                                    "modules": [{"id": "MOD-001", "feature_group": "FG-02", "requirement_ids": ["RF-001"]}],
                                    "api_contracts": [], "screens": [], "decisions": []})
        w("supporting-context.json", {"version": 1, "items": [{"id": "CTX-001"}]})
        w("source-inventory.json", {"version": 1, "sections": [{"id": "SRC-SEC-001", "title": "a"}, {"id": "SRC-SEC-002", "title": "b"}, {"id": "SRC-SEC-003", "title": "c"}]})
        w("stakeholder-questions.json", {"version": 1, "questions": [
            {"id": "QST-001", "source_kind": "nfr_checklist"}, {"id": "QST-002", "source_kind": "defect", "related_symbol_ids": ["LEL-003"]},
            {"id": "QST-003", "source_kind": "defect", "related_symbol_ids": ["LEL-001"]}]})
        (tmp / "stakeholder-answers.md").write_text("## QST-001\nmenos de 500\n## QST-003\nsi, con anticipo\n", encoding="utf-8")

        code = run(tmp, ["FG-01"], "INC-002", "9.9.9", True, indice=True)
        check(code == 0, "corrida sobre fixture (exit 0)")
        idx = json.loads((tmp / CONTEXT_DIR / "index.json").read_text(encoding="utf-8"))
        check(len(idx["features"]) == 2 and len(idx["lel"]) == 3 and idx["requirements"][0]["id"] == "RF-001"
              and "acceptance_criteria" not in idx["requirements"][0], "--indice: indice compacto de toda la linea de base")
        s = json.loads((tmp / CONTEXT_DIR / "FG-01.json").read_text(encoding="utf-8"))
        check({x["id"] for x in s["lel"]["symbols"]} == {"LEL-001", "LEL-002"}, "simbolos citados + nombrados en el stub (socio), sin cuota")
        check(len(s["lel"]["index"]) == 3, "indice compacto de todos los simbolos")
        check(s["scenarios"]["items"] == [] and s["scenarios"]["stub_ids"] == ["SCN-001"], "sin escenarios previos propios; stub ids presentes")
        check(s["requirements"]["items"] == [] and len(s["requirements"]["index"]) == 1, "sin requisitos propios; indice global")
        check([e["id"] for e in s["design"]["entities"]] == ["ENT-001"] and len(s["design"]["relationships"]) == 1, "entidad por simbolo y su relacion")
        check(s["design"]["modules"] == [] and s["design"]["stack"], "sin modulos ajenos; stack completo")
        check([x["id"] for x in s["source_sections"]] == ["SRC-SEC-001", "SRC-SEC-002"], "secciones citadas por la feature y sus stubs")
        check({q["id"] for q in s["questionnaire"]["questions"]} == {"QST-001", "QST-003"}, "nfr_checklist + preguntas de sus simbolos")
        check(set(s["questionnaire"]["answers"]) == {"QST-001", "QST-003"}, "respuestas del stakeholder recortadas")
        check(s["id_policy"]["next_free"]["SCN"] == 3 and s["id_policy"]["next_free"]["AC"] == 5, "proximo id libre por prefijo")
        check(s["id_policy"]["mode"] == "parallel" and "SCN-FG01#1" in s["id_policy"]["provisional_format"], "politica de ids provisionales")
        check(s["versions"]["lel"] == 5 and s["run_id"] == "INC-002" and s["pipeline_version"] == "9.9.9", "versiones y estampas")
        # primer descubrimiento: el mapa todavia no existe y el indice igual sale
        (tmp / "product-map.json").unlink()
        code = run(tmp, None, None, "9.9.9", True, indice=True)
        idx = json.loads((tmp / CONTEXT_DIR / "index.json").read_text(encoding="utf-8"))
        check(code == 0 and idx["features"] == [] and len(idx["lel"]) == 3,
              "--indice sin product-map.json: indice sin features (DSC inicial)")
        code = clean(tmp)
        check(code == 0 and not (tmp / CONTEXT_DIR).exists(), "--limpiar borra la carpeta temporal")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    print("SELF-TEST: %d fallo(s)" % failures)
    return 1 if failures else 0


def main(argv):
    if "--self-test" in argv:
        return self_test()
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("carpeta", nargs="?", default=".dev/requirements")
    ap.add_argument("--features", nargs="+", default=None, help="features del incremento (FG-xx)")
    ap.add_argument("--corrida", default=None, help="id de la corrida (INC-xxx / CR-xxx)")
    ap.add_argument("--pipeline-version", default=None)
    ap.add_argument("--secuencial", action="store_true", help="un solo agente: puede usar ids globales directamente")
    ap.add_argument("--indice", action="store_true", help="escribir ademas .inc-context/index.json (indice compacto de toda la linea de base)")
    ap.add_argument("--limpiar", action="store_true", help="borrar .inc-context/ y salir")
    args = ap.parse_args(argv)
    folder = Path(args.carpeta)
    if args.limpiar:
        return clean(folder)
    if not folder.is_dir():
        print("No existe la carpeta: %s" % folder)
        return 1
    if not args.features and not args.indice:
        print("ERROR: indica las features con --features FG-01 FG-02 (o --indice)")
        return 1
    return run(folder, args.features, args.corrida, args.pipeline_version, not args.secuencial, args.indice)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
