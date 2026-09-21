#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Verificacion determinista de una feature: test, lint y audit de dependencias.

Corre una sola vez los comandos del perfil de stack (`commands.test`, `commands.lint`)
y el `tooling.dependency_audit` de la base de seguridad, y deja el resultado en
`.dev/build/verification/{brief_basename}.json`. El reviewer y el gate consumen ese
JSON en vez de re-correr la suite y parsear logs con un modelo: la suite corre una
vez por ronda, el resultado es el mismo para todos los agentes y ningun agente
"cree" en un reporte, lee un exit code.

Contrato del artefacto:
  {
    "version": 1, "brief_basename": "FG-05-carrito", "generated_at": "...",
    "git_sha": "abc123", "branch": "feature/carrito",
    "baseline": {"path": ".dev/build/accepted-baseline.json", "git_sha": "...", "captured_at": "..."} | null,
    "commands": {
      "test":             {"command": "...", "exit_code": 0, "passed": true, "duration_s": 1.2, "tail": ["..."],
                           "failing": [], "inherited_failures": [], "new_failures": []},
      "lint":             {"command": "...", "exit_code": 0, "passed": true, ...},
      "dependency_audit": {"command": "...", "exit_code": 0, "passed": true,
                           "severities": {"critical": 0, "high": 0, "moderate": 0, "low": 0},
                           "accepted": [{"key": "...", "severity": "high"}], "new": [...], ...}
    },
    "passed": true
  }

Un comando ausente en el perfil queda como `{"command": null, "passed": null}` con un
aviso. El audit "pasa" si no reporta vulnerabilidades critical/high (el exit code de
los auditores varia por ecosistema, por eso se normaliza por severidad). En npm/pnpm
la unidad es la del propio auditor (`metadata.vulnerabilities`: paquetes afectados por
severidad), la misma que reporta `npm audit` en consola.

Linea de base (proyectos con historia). En un repo que ya tiene tests en rojo o
vulnerabilidades critical/high, la verificacion absoluta nunca pasa, por bueno que sea
el trabajo nuevo. `--capturar-baseline` corre test y audit UNA vez sobre la rama de
integracion (arbol limpio, antes de la primera feature) y deja
`.dev/build/accepted-baseline.json` con los tests que ya fallaban y los advisories ya
presentes. Con ese archivo, la verificacion bloquea ante **regresiones**, no ante lo
heredado:
  - test: pasa si el exit es 0, o si todo lo que falla ya fallaba en la linea de base
    (tests identificados por la salida de jest/vitest, pytest, go test, cargo test y
    rspec; en jest/vitest la unidad es el archivo). Si falla y no se puede identificar
    que falla, no pasa.
  - audit: pasa si no aparece ningun advisory critical/high que no este en la linea de
    base. Sin salida JSON (sin identidades), compara conteos critical+high.
Lo heredado queda a la vista en el artefacto (`inherited_failures`, `accepted`).
`lint` no tiene linea de base: se sigue exigiendo en verde.

Solo stdlib, Python 3.8+. Solo ejecuta los comandos del perfil: nunca un comando
sugerido por el codigo del proyecto.

Uso:
  python verify.py <raiz-del-proyecto> --brief FG-05-carrito [--solo test lint audit]
                   [--timeout 900] [--cwd <worktree>]
  python verify.py <raiz-del-proyecto> --capturar-baseline [--reemplazar] [--timeout 900] [--cwd <dir>]
  python verify.py --self-test

Exit 0: todo lo corrido paso (o la linea de base quedo escrita). Exit 1: algo fallo.
Exit 2: error de uso, de perfil, o captura rechazada (arbol sucio, ya existe).
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

SEVERITIES = ("critical", "high", "moderate", "low")
BLOCKING = ("critical", "high")
TAIL_LINES = 40
BASELINE_FILE = "accepted-baseline.json"
ANSI = re.compile(r"\x1b\[[0-9;]*[A-Za-z]")
# que test fallo, por runner; la unidad es la que el runner reporta de forma estable
FAILING_PATTERNS = [
    re.compile(r"^\s*FAIL\s+(\S+)"),                    # jest / vitest (archivo); go test (paquete)
    re.compile(r"^FAILED\s+(\S+)"),                     # pytest -rf (nodo)
    re.compile(r"^ERROR\s+(\S+\.py\S*)"),               # pytest (error de coleccion)
    re.compile(r"^\s*--- FAIL:\s+(\S+)"),               # go test (funcion)
    re.compile(r"^test\s+(\S+)\s+\.\.\.\s+FAILED"),     # cargo test
    re.compile(r"^rspec\s+(\./\S+)"),                   # rspec
]


def fail(msg):
    print("error: %s" % msg)
    return 2


def load_json(path):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8-sig"))
    except (OSError, ValueError):
        return None


def run(command, cwd, timeout):
    start = time.time()
    try:
        proc = subprocess.run(command, shell=True, cwd=str(cwd), capture_output=True,
                              text=True, timeout=timeout)
        out = (proc.stdout or "") + (proc.stderr or "")
        code = proc.returncode
    except subprocess.TimeoutExpired as exc:
        out = ((exc.stdout or b"").decode("utf-8", "replace") if isinstance(exc.stdout, bytes) else (exc.stdout or "")) \
            + "\n[timeout tras %ss]" % timeout
        code = 124
    lines = out.splitlines()
    return code, out, lines[-TAIL_LINES:], round(time.time() - start, 2)


# ------------------------------------------------------------------ audit

def _walk(obj, found):
    """Recorre un JSON de auditoria y acumula conteos por severidad, sea cual sea el
    ecosistema (pip-audit: vulns por dependencia; composer: advisories; cargo-audit:
    vulnerabilities.list). npm/pnpm no pasan por aca: tienen su propio resumen."""
    if isinstance(obj, dict):
        sev = obj.get("severity")
        if isinstance(sev, str) and sev.lower() in SEVERITIES and ("id" in obj or "title" in obj or "name" in obj or "via" in obj):
            found[sev.lower()] += 1
        for v in obj.values():
            _walk(v, found)
    elif isinstance(obj, list):
        for v in obj:
            _walk(v, found)


def parse_audit(output):
    text = output.strip()
    # el JSON puede venir precedido de warnings del gestor: buscar la primera llave
    for start in (text.find("{"), text.find("[")):
        if start >= 0:
            try:
                return json.loads(text[start:])
            except ValueError:
                continue
    return None


def _npm_summary(parsed):
    """npm (v6 y v7+) y pnpm traen su resumen en metadata.vulnerabilities. Es LA unidad:
    recorrer el arbol ademas cuenta cada paquete y cada advisory de `via` otra vez."""
    meta = (parsed.get("metadata") or {}).get("vulnerabilities") if isinstance(parsed, dict) else None
    if isinstance(meta, dict) and meta and all(isinstance(v, int) for v in meta.values()):
        return meta
    return None


def normalize_audit(output):
    found = {k: 0 for k in SEVERITIES}
    parsed = parse_audit(output)
    if parsed is not None:
        summary = _npm_summary(parsed)
        if summary is not None:
            for k in SEVERITIES:
                found[k] = summary.get(k, 0)
            return found, True
        _walk(parsed, found)
        if sum(found.values()) == 0:
            # pip-audit: sin severidad; cada vuln cuenta como high (conservador)
            for dep in _pip_deps(parsed):
                found["high"] += len(dep.get("vulns") or [])
        return found, True
    # sin JSON: contar menciones textuales (npm audit sin --json, cargo audit, etc.)
    for sev in SEVERITIES:
        found[sev] += len(re.findall(r"\b%s\b" % sev, output, flags=re.IGNORECASE))
    return found, False


def _pip_deps(parsed):
    deps = parsed.get("dependencies") if isinstance(parsed, dict) else parsed
    return [d for d in deps or [] if isinstance(d, dict)] if isinstance(deps, list) else []


def audit_findings(parsed):
    """Identidad estable de cada advisory, para compararla con la linea de base:
    [{"key": "paquete:advisory", "severity": "high"}]. Vacio si no hay JSON."""
    out = {}

    def add(pkg, ident, sev):
        if ident in (None, ""):
            return
        sev = str(sev or "high").lower()
        key = "%s:%s" % (pkg or "", ident)
        if key not in out or SEVERITIES.index(sev if sev in SEVERITIES else "high") < SEVERITIES.index(out[key]):
            out[key] = sev if sev in SEVERITIES else "high"

    if parsed is None:
        return []
    vul = parsed.get("vulnerabilities") if isinstance(parsed, dict) else None
    if isinstance(vul, dict) and vul and all(isinstance(v, dict) for v in vul.values()):
        # npm v7+: el advisory vive en `via` (objeto) del paquete vulnerable; los `via`
        # string son solo el camino transitivo y no agregan identidad
        for pkg, entry in vul.items():
            for via in entry.get("via") or []:
                if isinstance(via, dict):
                    add(pkg, via.get("url") or via.get("source") or via.get("title"), via.get("severity"))
    elif isinstance(parsed, dict) and isinstance(parsed.get("advisories"), dict):
        # npm v6 / pnpm: {"advisories": {id: {module_name, severity, url}}}
        for aid, adv in parsed["advisories"].items():
            if isinstance(adv, dict):
                add(adv.get("module_name"), adv.get("url") or aid, adv.get("severity"))
            elif isinstance(adv, list):  # composer: {"advisories": {paquete: [...]}}
                for a in adv:
                    if isinstance(a, dict):
                        add(aid, a.get("advisoryId") or a.get("cve") or a.get("link"), a.get("severity"))
    elif _pip_deps(parsed):
        for dep in _pip_deps(parsed):
            for v in dep.get("vulns") or []:
                if isinstance(v, dict):
                    add(dep.get("name"), v.get("id"), v.get("severity"))
    else:
        def walk(obj, pkg):
            if isinstance(obj, dict):
                pkg = obj.get("package") if isinstance(obj.get("package"), str) else pkg
                if isinstance(obj.get("package"), dict):
                    pkg = obj["package"].get("name") or pkg
                ident = obj.get("id") or obj.get("ghsa_id") or obj.get("cve")
                if ident and ("severity" in obj or "title" in obj):
                    add(pkg or obj.get("name"), ident, obj.get("severity"))
                for v in obj.values():
                    walk(v, pkg)
            elif isinstance(obj, list):
                for v in obj:
                    walk(v, pkg)
        walk(parsed, None)
    return [{"key": k, "severity": s} for k, s in sorted(out.items())]


# ------------------------------------------------------------------ tests

def failing_tests(output):
    found = set()
    for line in ANSI.sub("", output).splitlines():
        for pat in FAILING_PATTERNS:
            m = pat.match(line)
            if m:
                found.add(m.group(1).rstrip(":"))
                break
    return sorted(found)


# ------------------------------------------------------------------ git

def git(cwd, *args):
    try:
        return subprocess.run(["git"] + list(args), cwd=str(cwd), capture_output=True,
                              text=True).stdout.strip()
    except OSError:
        return ""


def git_rc(cwd, *args):
    try:
        return subprocess.run(["git"] + list(args), cwd=str(cwd), capture_output=True, text=True).returncode
    except OSError:
        return None


def load_context(root):
    dev = Path(root) / ".dev" / "build"
    profile = load_json(dev / "stack-profile.json")
    if profile is None:
        return None, "no se pudo leer %s" % (dev / "stack-profile.json")
    security = load_json(dev / "security-baseline.json") or {}
    cmds = profile.get("commands") or {}
    return {
        "test": (cmds.get("test") or {}).get("command"),
        "lint": (cmds.get("lint") or {}).get("command"),
        "dependency_audit": ((security.get("tooling") or {}).get("dependency_audit") or {}).get("command"),
    }, None


# ------------------------------------------------------------------ verificacion

def judge_test(entry, out, code, accepted, warnings):
    """Rojo heredado vs regresion. `accepted` es la seccion tests de la linea de base."""
    if code == 0:
        entry["passed"] = True
        return
    entry["passed"] = False
    if code == 124 or accepted is None:
        return
    failing = failing_tests(out)
    known = set(accepted.get("known_failing") or [])
    entry["failing"] = failing
    if not failing:
        warnings.append("test fallo y no se pudo identificar que tests fallan: sin eso el rojo "
                        "no se puede comparar con la linea de base (se toma como regresion)")
        return
    entry["inherited_failures"] = [t for t in failing if t in known]
    entry["new_failures"] = [t for t in failing if t not in known]
    if not entry["new_failures"]:
        entry["passed"] = True
        warnings.append("test en rojo heredado: %d fallo(s) que ya estaban en la linea de base (%s)"
                        % (len(failing), ", ".join(failing[:5]) + (" ..." if len(failing) > 5 else "")))


def judge_audit(entry, out, code, accepted, warnings):
    sev, structured = normalize_audit(out)
    entry["severities"] = sev
    entry["structured_output"] = structured
    if code == 124:
        entry["passed"] = False
        return
    if accepted is None:
        entry["passed"] = (sev["critical"] + sev["high"]) == 0
        return
    findings = audit_findings(parse_audit(out))
    acc_keys = {a.get("key") for a in accepted.get("accepted") or []}
    # comparar por identidad exige JSON hoy y en la linea de base (si no, por conteo)
    if findings and accepted.get("structured_output"):
        entry["accepted"] = [f for f in findings if f["key"] in acc_keys]
        entry["new"] = [f for f in findings if f["key"] not in acc_keys]
        entry["passed"] = not [f for f in entry["new"] if f["severity"] in BLOCKING]
        if entry["accepted"]:
            warnings.append("audit: %d advisory(s) aceptados en la linea de base; nuevos critical/high: %d"
                            % (len(entry["accepted"]), len([f for f in entry["new"] if f["severity"] in BLOCKING])))
    else:
        base = accepted.get("severities") or {}
        now_bad = sev["critical"] + sev["high"]
        entry["passed"] = now_bad <= base.get("critical", 0) + base.get("high", 0)
        warnings.append("audit sin identidades de advisory: se comparo por conteo critical+high (%d, linea de base %d)"
                        % (now_bad, base.get("critical", 0) + base.get("high", 0)))


def verify(root, brief, only, timeout, cwd):
    root = Path(root)
    cwd = Path(cwd) if cwd else root
    dev = root / ".dev" / "build"
    wanted, err = load_context(root)
    if wanted is None:
        return None, err
    aliases = {"audit": "dependency_audit"}
    selected = set(aliases.get(o, o) for o in only) if only else set(wanted)
    base_path = dev / BASELINE_FILE
    base = load_json(base_path) if base_path.is_file() else None

    result = {
        "version": 1,
        "brief_basename": brief,
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "git_sha": git(cwd, "rev-parse", "--short", "HEAD") or None,
        "branch": git(cwd, "rev-parse", "--abbrev-ref", "HEAD") or None,
        "baseline": None,
        "commands": {},
        "warnings": [],
        "passed": True,
    }
    if base_path.is_file() and base is None:
        result["warnings"].append("%s no parsea: se verifica sin linea de base" % BASELINE_FILE)
    if base is not None:
        result["baseline"] = {"path": ".dev/build/" + BASELINE_FILE, "git_sha": base.get("git_sha"),
                              "captured_at": base.get("captured_at")}
        if base.get("git_sha") and git_rc(cwd, "merge-base", "--is-ancestor", base["git_sha"], "HEAD") == 1:
            result["warnings"].append("la linea de base (%s) no es ancestro de HEAD: fue capturada en otra historia"
                                      % base["git_sha"])
    for name, command in wanted.items():
        entry = {"command": command, "exit_code": None, "passed": None, "duration_s": None, "tail": []}
        if name not in selected:
            entry["skipped"] = True
        elif not command:
            result["warnings"].append("sin comando de %s en el perfil" % name)
        else:
            code, out, tail, dur = run(command, cwd, timeout)
            entry.update({"exit_code": code, "duration_s": dur, "tail": tail})
            if name == "dependency_audit":
                judge_audit(entry, out, code, (base or {}).get("dependency_audit"), result["warnings"])
            elif name == "test":
                judge_test(entry, out, code, (base or {}).get("tests"), result["warnings"])
            else:
                entry["passed"] = code == 0
            if entry["passed"] is False:
                result["passed"] = False
        result["commands"][name] = entry

    outdir = dev / "verification"
    outdir.mkdir(parents=True, exist_ok=True)
    outpath = outdir / (brief + ".json")
    outpath.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return outpath, result


def capture_baseline(root, timeout, cwd, replace):
    root = Path(root)
    cwd = Path(cwd) if cwd else root
    dest = root / ".dev" / "build" / BASELINE_FILE
    wanted, err = load_context(root)
    if wanted is None:
        return None, err
    if dest.is_file() and not replace:
        return None, "%s ya existe: re-capturar solo con --reemplazar (y solo sobre la rama de integracion)" % dest
    if git(cwd, "status", "--porcelain", "--untracked-files=no"):
        return None, "el arbol tiene cambios sin commitear: la linea de base se captura sobre la rama de integracion limpia"
    base = {
        "version": 1,
        "captured_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "git_sha": git(cwd, "rev-parse", "--short", "HEAD") or None,
        "branch": git(cwd, "rev-parse", "--abbrev-ref", "HEAD") or None,
        "tests": None,
        "dependency_audit": None,
        "warnings": [],
    }
    if wanted["test"]:
        code, out, tail, _ = run(wanted["test"], cwd, timeout)
        failing = failing_tests(out) if code not in (0, 124) else []
        base["tests"] = {"command": wanted["test"], "exit_code": code, "known_failing": failing, "tail": tail}
        if code == 124:
            base["warnings"].append("test excedio el timeout: sin tests rojos conocidos")
        elif code != 0 and not failing:
            base["warnings"].append("test en rojo sin tests identificables: la linea de base no cubre tests")
    if wanted["dependency_audit"]:
        code, out, tail, _ = run(wanted["dependency_audit"], cwd, timeout)
        sev, structured = normalize_audit(out)
        base["dependency_audit"] = {"command": wanted["dependency_audit"], "exit_code": code, "severities": sev,
                                    "structured_output": structured,
                                    "accepted": audit_findings(parse_audit(out)), "tail": tail}
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(json.dumps(base, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return dest, base


def summarize(result):
    parts = []
    for name, e in result["commands"].items():
        if e.get("skipped"):
            continue
        state = "sin comando" if e["passed"] is None else ("ok" if e["passed"] else "FALLO exit %s" % e["exit_code"])
        if name == "test" and e.get("inherited_failures") and e["passed"]:
            state = "ok (rojo heredado: %d)" % len(e["inherited_failures"])
        if name == "test" and e.get("new_failures"):
            state += " (regresion: %s)" % ", ".join(e["new_failures"][:5])
        if name == "dependency_audit" and e.get("severities"):
            s = e["severities"]
            state += " (critical %d, high %d, moderate %d, low %d)" % (s["critical"], s["high"], s["moderate"], s["low"])
            if "new" in e:
                state += " [nuevos: %d, aceptados: %d]" % (len(e["new"]), len(e.get("accepted") or []))
        parts.append("%s: %s" % (name, state))
    return "; ".join(parts)


# ------------------------------------------------------------------ self-test

NPM_V7 = {
    "auditReportVersion": 2,
    "vulnerabilities": {
        "next-auth": {"name": "next-auth", "severity": "critical", "via": [
            {"source": 1001, "name": "next-auth", "title": "t", "url": "https://github.com/advisories/GHSA-aaaa",
             "severity": "critical"}, "@auth/core"]},
        "@auth/core": {"name": "@auth/core", "severity": "high", "via": [
            {"source": 1002, "name": "@auth/core", "title": "t", "url": "https://github.com/advisories/GHSA-bbbb",
             "severity": "high"},
            {"source": 1003, "name": "@auth/core", "title": "t", "url": "https://github.com/advisories/GHSA-cccc",
             "severity": "moderate"}]},
    },
    "metadata": {"vulnerabilities": {"info": 0, "low": 0, "moderate": 0, "high": 1, "critical": 1, "total": 2}},
}


def self_test():
    import shutil
    import tempfile

    py = sys.executable.replace("\\", "/")
    failures = 0

    def check(cond, label, detail=""):
        nonlocal failures
        print("self-test %s: %s%s" % ("ok" if cond else "FALLO", label, "" if cond else " -> %s" % detail))
        if not cond:
            failures += 1

    def fixture(tmp, test_out, test_code, audit_doc, lint_ok=True):
        build = tmp / ".dev" / "build"
        build.mkdir(parents=True, exist_ok=True)
        test_script = tmp / "test_cmd.py"
        test_script.write_text("import sys\nprint(%r)\nsys.exit(%d)\n" % (test_out, test_code), encoding="utf-8")
        audit_script = tmp / "audit.py"
        audit_script.write_text("print(%r)\n" % json.dumps(audit_doc), encoding="utf-8")
        (build / "stack-profile.json").write_text(json.dumps({
            "version": 1,
            "commands": {
                "test": {"command": '"%s" "%s"' % (py, str(test_script).replace("\\", "/"))},
                "lint": {"command": '"%s" -c "import sys; sys.exit(%d)"' % (py, 0 if lint_ok else 1)},
            },
        }), encoding="utf-8")
        (build / "security-baseline.json").write_text(json.dumps({
            "tooling": {"dependency_audit": {"command": '"%s" "%s"' % (py, str(audit_script).replace("\\", "/"))}},
        }), encoding="utf-8")

    clean_audit = {"metadata": {"vulnerabilities": {"info": 0, "low": 1, "moderate": 0, "high": 0, "critical": 0}}}

    # 1. sin linea de base: el comportamiento absoluto de siempre
    for lint_ok in (True, False):
        tmp = Path(tempfile.mkdtemp(prefix="verify-"))
        try:
            fixture(tmp, "1 passed", 0, clean_audit, lint_ok)
            path, res = verify(tmp, "FG-01-demo", [], 60, None)
            ok = path is not None and res["passed"] == lint_ok and res["baseline"] is None \
                and res["commands"]["dependency_audit"]["severities"]["low"] == 1 \
                and res["commands"]["dependency_audit"]["passed"] is True \
                and res["commands"]["test"]["passed"] is True \
                and json.loads(path.read_text(encoding="utf-8"))["brief_basename"] == "FG-01-demo"
            check(ok, "sin linea de base, lint %s: passed=%s" % ("ok" if lint_ok else "falla", res["passed"]), res)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    # 2. npm v7: la unidad es metadata.vulnerabilities (antes: paquetes + via + metadata)
    sev, structured = normalize_audit(json.dumps(NPM_V7))
    check(structured and sev == {"critical": 1, "high": 1, "moderate": 0, "low": 0},
          "npm v7 cuenta con metadata.vulnerabilities, sin doble conteo", sev)
    keys = [f["key"] for f in audit_findings(NPM_V7)]
    check(keys == ["@auth/core:https://github.com/advisories/GHSA-bbbb", "@auth/core:https://github.com/advisories/GHSA-cccc",
                   "next-auth:https://github.com/advisories/GHSA-aaaa"], "identidades de advisory npm v7", keys)
    sev, structured = normalize_audit("found 2 vulnerabilities (1 high, 1 critical)")
    check(not structured and sev["high"] == 1 and sev["critical"] == 1, "audit textual", sev)
    check(failing_tests("\x1b[31mFAIL\x1b[39m tests/a.test.ts\nPASS tests/b.test.ts\nFAILED tests/t.py::test_x - boom\n"
                        "--- FAIL: TestFoo (0.00s)\ntest mod::caso ... FAILED\n")
          == ["TestFoo", "mod::caso", "tests/a.test.ts", "tests/t.py::test_x"], "identifica tests rojos por runner",
          failing_tests("FAIL tests/a.test.ts"))

    # 3. brownfield: linea de base con rojo heredado y vulnerabilidades preexistentes
    tmp = Path(tempfile.mkdtemp(prefix="verify-bf-"))
    try:
        fixture(tmp, "FAIL tests/integration/objetivos.test.ts\nTests: 1 failed, 117 passed", 1, NPM_V7)
        dest, base = capture_baseline(tmp, 60, None, False)
        check(dest is not None and base["tests"]["known_failing"] == ["tests/integration/objetivos.test.ts"]
              and len(base["dependency_audit"]["accepted"]) == 3, "captura la linea de base", base)
        again, err = capture_baseline(tmp, 60, None, False)
        check(again is None and "--reemplazar" in err, "no pisa una linea de base existente sin --reemplazar", err)

        _, res = verify(tmp, "FG-02-heredado", [], 60, None)
        t, a = res["commands"]["test"], res["commands"]["dependency_audit"]
        check(res["passed"] and t["passed"] and t["inherited_failures"] and not t["new_failures"]
              and a["passed"] and len(a["accepted"]) == 3 and a["new"] == [] and res["baseline"],
              "rojo heredado y vulnerabilidades aceptadas: la compuerta puede abrir", res)

        fixture(tmp, "FAIL tests/integration/objetivos.test.ts\nFAIL tests/nuevo.test.ts", 1, NPM_V7)
        _, res = verify(tmp, "FG-03-regresion", [], 60, None)
        t = res["commands"]["test"]
        check(not res["passed"] and t["new_failures"] == ["tests/nuevo.test.ts"], "un test nuevo en rojo es regresion", t)

        fixture(tmp, "algo exploto sin formato", 1, NPM_V7)
        _, res = verify(tmp, "FG-04-opaco", [], 60, None)
        check(not res["commands"]["test"]["passed"], "rojo no identificable no se da por heredado", res["commands"]["test"])

        nuevo = json.loads(json.dumps(NPM_V7))
        nuevo["vulnerabilities"]["lodash"] = {"name": "lodash", "severity": "high", "via": [
            {"source": 2001, "name": "lodash", "title": "t", "url": "https://github.com/advisories/GHSA-dddd", "severity": "high"}]}
        fixture(tmp, "1 passed", 0, nuevo)
        _, res = verify(tmp, "FG-05-dep-nueva", [], 60, None)
        a = res["commands"]["dependency_audit"]
        check(not res["passed"] and [f["key"] for f in a["new"]] == ["lodash:https://github.com/advisories/GHSA-dddd"],
              "un advisory high nuevo cierra la compuerta", a)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    print("SELF-TEST: %d fallo(s)" % failures)
    return 1 if failures else 0


# ------------------------------------------------------------------------ main

def main(argv):
    if "--self-test" in argv:
        return self_test()
    root = None
    brief = None
    only = []
    timeout = 900
    cwd = None
    capture = False
    replace = False
    i = 0
    while i < len(argv):
        a = argv[i]
        if a == "--brief":
            i += 1
            brief = argv[i]
        elif a == "--solo":
            i += 1
            while i < len(argv) and not argv[i].startswith("--"):
                only.append(argv[i])
                i += 1
            continue
        elif a == "--timeout":
            i += 1
            timeout = int(argv[i])
        elif a == "--cwd":
            i += 1
            cwd = argv[i]
        elif a == "--capturar-baseline":
            capture = True
        elif a == "--reemplazar":
            replace = True
        elif a.startswith("--"):
            return fail("opcion desconocida %s" % a)
        else:
            root = a
        i += 1
    if capture and root:
        dest, base = capture_baseline(root, timeout, cwd, replace)
        if dest is None:
            return fail(base)
        t, a = base["tests"] or {}, base["dependency_audit"] or {}
        s = a.get("severities") or {}
        print("linea de base: %s (sha %s, rama %s)" % (dest, base["git_sha"], base["branch"]))
        print("tests rojos conocidos: %d%s" % (len(t.get("known_failing") or []),
                                               (" — " + ", ".join(t["known_failing"][:10])) if t.get("known_failing") else ""))
        print("advisories aceptados: %d (critical %d, high %d)" % (
            len(a.get("accepted") or []), s.get("critical", 0), s.get("high", 0)))
        for w in base["warnings"]:
            print("aviso: %s" % w)
        return 0
    if not root or not brief:
        return fail("uso: verify.py <raiz> --brief <brief_basename> [--solo test lint audit] [--cwd <worktree>]"
                    " | verify.py <raiz> --capturar-baseline [--reemplazar]")
    path, result = verify(root, brief, only, timeout, cwd)
    if path is None:
        return fail(result)
    print("verificacion: %s" % path)
    print(summarize(result))
    for w in result["warnings"]:
        print("aviso: %s" % w)
    print("RESULTADO: %s" % ("PASSED" if result["passed"] else "FAILED"))
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
