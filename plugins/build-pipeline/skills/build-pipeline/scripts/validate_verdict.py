#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Validacion mecanica de los veredictos del build y compuerta dura pre-PR.

Dos usos:

1. Contrato de un veredicto (lo que antes hacia el orquestador clave por clave):
     python validate_verdict.py <veredicto.json> [--tipo review|gate]
   El tipo se infiere del directorio padre (`reviews/` -> review, `security/` -> gate)
   si no se indica. Verifica claves obligatorias, tipos, ids namespaced
   (`FG-xx/FIND-nnn` / `FG-xx/SGATE-nnn`; la ronda de contratos usa el namespace
   `FG-00`), que `summary` cuente lo que `findings`
   contiene y que `passed` sea coherente (true solo sin high/medium).

2. Compuerta pre-PR de una feature:
     python validate_verdict.py <raiz> --compuerta --brief FG-05-carrito
   Exige `reviews/{brief}.json` y `security/{brief}.json` validos y ambos con
   `passed: true`; si existe `verification/{brief}.json`, exige tambien `passed: true`,
   que sea de la misma rama que los veredictos y que no haya salteado ningun comando
   con comando en el perfil (`verify.py --solo` no abre la compuerta: omite un control
   aplicable). Lo heredado de la linea de base ya viene resuelto por `verify.py`.

Solo stdlib. No modifica nada.
Exit 0: valido / compuerta abierta. Exit 1: invalido / compuerta cerrada. Exit 2: uso.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

COMMON = {"version": int, "feature_slug": str, "branch": str, "summary": dict, "findings": list,
          "passed": bool, "warnings": list}
REVIEW_KEYS = dict(COMMON, requirements_closure=list, verification_notes=list, resolved_findings=list)
GATE_KEYS = dict(COMMON, deferred_to_audit=list)
REVIEW_SUMMARY = ("total_findings", "high", "medium", "low", "tests_passed", "lint_passed", "tasks_covered", "tasks_missing")
GATE_SUMMARY = ("total_findings", "high", "medium", "low", "dependency_audit_run", "dependency_audit_passed",
                "applicable_categories", "categories_reviewed")
FINDING_KEYS = {
    "review": ("id", "severity", "category", "description", "evidence_refs", "proposed_correction", "related_task_ids"),
    "gate": ("id", "severity", "owasp_id", "category", "description", "attack_vector", "impact", "evidence_refs",
             "proposed_fix", "related_task_ids"),
}
ID_RE = {"review": re.compile(r"^FG-\d+/FIND-\d{3,}$"), "gate": re.compile(r"^FG-\d+/SGATE-\d{3,}$")}


def load(path):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8-sig")), None
    except OSError as exc:
        return None, "no se pudo leer: %s" % exc
    except ValueError as exc:
        return None, "JSON invalido: %s" % exc


def validate(verdict, tipo):
    errors = []
    keys = REVIEW_KEYS if tipo == "review" else GATE_KEYS
    for k, t in keys.items():
        if k not in verdict:
            errors.append("falta la clave %s" % k)
        elif not isinstance(verdict[k], t):
            errors.append("%s deberia ser %s" % (k, t.__name__))
    if "pipeline_version" not in verdict:
        errors.append("falta la clave pipeline_version (puede ser null, nunca ausente)")
    summary = verdict.get("summary") if isinstance(verdict.get("summary"), dict) else {}
    for k in (REVIEW_SUMMARY if tipo == "review" else GATE_SUMMARY):
        if k not in summary:
            errors.append("summary sin %s" % k)
    findings = verdict.get("findings") if isinstance(verdict.get("findings"), list) else []
    counts = {"high": 0, "medium": 0, "low": 0}
    for i, f in enumerate(findings):
        if not isinstance(f, dict):
            errors.append("findings[%d] no es objeto" % i)
            continue
        for k in FINDING_KEYS[tipo]:
            if k not in f:
                errors.append("%s sin %s" % (f.get("id", "findings[%d]" % i), k))
        sev = f.get("severity")
        if sev in counts:
            counts[sev] += 1
        else:
            errors.append("%s con severidad invalida: %s" % (f.get("id", "findings[%d]" % i), sev))
        fid = f.get("id", "")
        if not ID_RE[tipo].match(str(fid)):
            errors.append("id no namespaced: %r (esperado %s)" % (fid, "FG-xx/FIND-nnn" if tipo == "review" else "FG-xx/SGATE-nnn"))
        if not f.get("evidence_refs"):
            errors.append("%s sin evidence_refs" % fid)
    for sev in counts:
        if sev in summary and summary[sev] != counts[sev]:
            errors.append("summary.%s=%s pero findings tiene %d" % (sev, summary[sev], counts[sev]))
    if "total_findings" in summary and summary["total_findings"] != len(findings):
        errors.append("summary.total_findings=%s pero hay %d findings" % (summary["total_findings"], len(findings)))
    if isinstance(verdict.get("passed"), bool):
        should = (counts["high"] + counts["medium"]) == 0
        if verdict["passed"] != should:
            errors.append("passed=%s incoherente con %d high / %d medium" % (verdict["passed"], counts["high"], counts["medium"]))
    if tipo == "review":
        for rc in verdict.get("requirements_closure") or []:
            if not isinstance(rc, dict) or not rc.get("requirement_id"):
                errors.append("requirements_closure con entrada sin requirement_id")
        if verdict.get("version", 1) > 1 and summary.get("tests_passed") is None and not verdict.get("warnings"):
            errors.append("re-review con tests_passed null y sin warning que lo explique")
    return errors


def infer_tipo(path):
    parent = Path(path).parent.name
    if parent == "reviews":
        return "review"
    if parent == "security":
        return "gate"
    return None


def compuerta(root, brief):
    build = Path(root) / ".dev" / "build"
    problems = []
    branches = set()
    for sub, tipo in (("reviews", "review"), ("security", "gate")):
        path = build / sub / (brief + ".json")
        data, err = load(path)
        if data is None:
            problems.append("%s/%s.json: %s" % (sub, brief, err))
            continue
        errs = validate(data, tipo)
        if errs:
            problems.append("%s/%s.json invalido: %s" % (sub, brief, "; ".join(errs[:5])))
        if data.get("passed") is not True:
            problems.append("%s/%s.json con passed=%s" % (sub, brief, data.get("passed")))
        if data.get("branch"):
            branches.add(data["branch"])
    vpath = build / "verification" / (brief + ".json")
    vdata, _ = load(vpath)
    if vdata is not None:
        if vdata.get("passed") is not True:
            problems.append("verification/%s.json con passed=%s" % (brief, vdata.get("passed")))
        skipped = [n for n, e in (vdata.get("commands") or {}).items()
                   if isinstance(e, dict) and e.get("skipped") and e.get("command")]
        if skipped:
            problems.append("verification/%s.json salteo %s (verify.py --solo): la compuerta exige la verificacion completa"
                            % (brief, ", ".join(sorted(skipped))))
        if vdata.get("branch") and branches and vdata["branch"] not in branches:
            problems.append("verification/%s.json es de la rama %s, los veredictos de %s" % (brief, vdata["branch"], ",".join(sorted(branches))))
    if len(branches) > 1:
        problems.append("los veredictos son de ramas distintas: %s" % ", ".join(sorted(branches)))
    return problems


# ------------------------------------------------------------------ self-test

def _review(passed, bad=False):
    findings = [] if passed else [{
        "id": "FIND-001" if bad else "FG-01/FIND-001", "severity": "high", "category": "coverage",
        "description": "d", "evidence_refs": ["a.py:1"], "proposed_correction": "c", "related_task_ids": ["T-001"]}]
    return {
        "version": 1, "pipeline_version": "1.6.0", "feature_slug": "demo", "branch": "feature/demo",
        "summary": {"total_findings": len(findings), "high": len(findings), "medium": 0, "low": 0,
                    "tests_passed": True, "lint_passed": True, "tasks_covered": ["T-001"], "tasks_missing": []},
        "requirements_closure": [{"requirement_id": "RF-001", "criteria_covered": ["AC-001"], "criteria_missing": [], "verified_by": ["t.py"]}],
        "findings": findings, "verification_notes": [], "resolved_findings": [], "passed": passed, "warnings": [],
    }


def _gate(passed):
    return {
        "version": 1, "pipeline_version": "1.6.0", "feature_slug": "demo", "branch": "feature/demo",
        "summary": {"total_findings": 0, "high": 0, "medium": 0, "low": 0, "dependency_audit_run": True,
                    "dependency_audit_passed": True, "applicable_categories": ["A01"], "categories_reviewed": ["A01"]},
        "findings": [], "passed": passed, "deferred_to_audit": [], "warnings": [],
    }


def self_test():
    import shutil
    import tempfile

    failures = 0
    if validate(_review(True), "review"):
        print("SELF-TEST FALLO (review valido rechazado): %s" % validate(_review(True), "review"))
        failures += 1
    else:
        print("self-test ok (review valido)")
    errs = validate(_review(False, bad=True), "review")
    if not any("namespaced" in e for e in errs):
        print("SELF-TEST FALLO (id sin namespace no detectado)")
        failures += 1
    else:
        print("self-test ok (id sin namespace detectado)")
    broken = _review(True)
    broken["passed"] = True
    broken["findings"] = _review(False)["findings"]
    broken["summary"]["high"] = 1
    broken["summary"]["total_findings"] = 1
    if not any("incoherente" in e for e in validate(broken, "review")):
        print("SELF-TEST FALLO (passed incoherente no detectado)")
        failures += 1
    else:
        print("self-test ok (passed incoherente detectado)")
    incomplete = _gate(True)
    del incomplete["deferred_to_audit"]
    if not any("deferred_to_audit" in e for e in validate(incomplete, "gate")):
        print("SELF-TEST FALLO (gate sin deferred_to_audit aceptado)")
        failures += 1
    else:
        print("self-test ok (gate incompleto detectado)")
    tmp = Path(tempfile.mkdtemp(prefix="verdict-"))
    try:
        build = tmp / ".dev" / "build"
        (build / "reviews").mkdir(parents=True)
        (build / "security").mkdir(parents=True)
        (build / "reviews" / "FG-01-demo.json").write_text(json.dumps(_review(True)), encoding="utf-8")
        (build / "security" / "FG-01-demo.json").write_text(json.dumps(_gate(True)), encoding="utf-8")
        if compuerta(tmp, "FG-01-demo"):
            print("SELF-TEST FALLO (compuerta cerrada con todo verde): %s" % compuerta(tmp, "FG-01-demo"))
            failures += 1
        else:
            print("self-test ok (compuerta abierta)")
        (build / "security" / "FG-01-demo.json").write_text(json.dumps(_gate(False)), encoding="utf-8")
        if not compuerta(tmp, "FG-01-demo"):
            print("SELF-TEST FALLO (compuerta abierta con gate en false)")
            failures += 1
        else:
            print("self-test ok (compuerta cerrada con gate en false)")
        (build / "security" / "FG-01-demo.json").write_text(json.dumps(_gate(True)), encoding="utf-8")
        (build / "verification").mkdir()
        (build / "verification" / "FG-01-demo.json").write_text(json.dumps({"passed": True, "commands": {
            "test": {"command": "npm test", "passed": True},
            "dependency_audit": {"command": "npm audit --json", "passed": None, "skipped": True}}}), encoding="utf-8")
        if not any("salteo dependency_audit" in p for p in compuerta(tmp, "FG-01-demo")):
            print("SELF-TEST FALLO (compuerta abierta con el audit salteado por --solo)")
            failures += 1
        else:
            print("self-test ok (compuerta cerrada con un comando salteado)")
        if not compuerta(tmp, "FG-99-nada"):
            print("SELF-TEST FALLO (compuerta abierta sin veredictos)")
            failures += 1
        else:
            print("self-test ok (compuerta cerrada sin veredictos)")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    return 1 if failures else 0


# ------------------------------------------------------------------------ main

def main(argv):
    if "--self-test" in argv:
        return self_test()
    tipo = None
    brief = None
    gate_mode = False
    target = None
    i = 0
    while i < len(argv):
        a = argv[i]
        if a == "--tipo":
            i += 1
            tipo = argv[i]
        elif a == "--brief":
            i += 1
            brief = argv[i]
        elif a == "--compuerta":
            gate_mode = True
        elif a.startswith("--"):
            print("error: opcion desconocida %s" % a)
            return 2
        else:
            target = a
        i += 1
    if target is None:
        print(__doc__)
        return 2
    if gate_mode:
        if not brief:
            print("error: --compuerta requiere --brief <brief_basename>")
            return 2
        problems = compuerta(target, brief)
        for p in problems:
            print("compuerta: %s" % p)
        print("COMPUERTA: %s" % ("ABIERTA" if not problems else "CERRADA"))
        return 0 if not problems else 1
    tipo = tipo or infer_tipo(target)
    if tipo not in ("review", "gate"):
        print("error: no se pudo inferir el tipo; indica --tipo review|gate")
        return 2
    data, err = load(target)
    if data is None:
        print("invalido: %s" % err)
        return 1
    errors = validate(data, tipo)
    for e in errors:
        print("invalido: %s" % e)
    if errors:
        return 1
    print("valido (%s): passed=%s, %d hallazgo(s)" % (tipo, data.get("passed"), len(data.get("findings") or [])))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
