#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Limpieza de los worktrees del lote, por script y con red de seguridad.

El modo LOTE crea `../{repo}-wt-{slug}` por feature y los baja al cerrar cada una. Si
el orquestador saltea ese paso (corridas largas), o `git worktree remove` falla por
archivos sin versionar (`node_modules`, el store del gestor, `.env` de test) y alguien
borra la carpeta a mano, quedan tres clases de basura: worktrees enteros de features
ya cerradas, entradas `prunable` (git las tiene registradas pero la carpeta ya no es
un worktree) y carpetas huerfanas (git no las conoce). Este script las encuentra
todas por la convencion de nombre y decide por `progress.json`:

  - feature `done`, o con PR anotado despues de su ultimo BLOQUEADA -> se limpia
  - BLOQUEADA, o en curso sin PR                                     -> queda en pie
  - rama sin feature en progress.json                                -> queda en pie
  - carpeta huerfana o entrada prunable                              -> se limpia
  - carpeta con `.git` propio (un clon, no un worktree)              -> no se toca

Nunca pierde trabajo: un worktree a limpiar que tiene cambios sin commitear, o
commits que no estan en ningun remoto (salvo feature `done`), queda en pie con aviso.

Limpiar = bajar el proyecto compose del directorio (`docker compose down -v`, si hay
compose file y docker; los recursos quedan nombrados por directorio y borrar la
carpeta no los baja), `git worktree remove --force`, borrar lo que quede de la
carpeta y `git worktree prune`. Las ramas no se tocan (tienen PR o estan mergeadas).

Uso:
  python cleanup_worktrees.py <raiz> [--aplicar] [--json]
  python cleanup_worktrees.py --self-test

Sin --aplicar solo muestra el plan. Solo stdlib, Python 3.8+.
Exit 0: plan mostrado o limpieza completa. Exit 1: algo que habia que limpiar no se
pudo. Exit 2: error de uso (la raiz no es un repo git).
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

COMPOSE_FILES = ("compose.yaml", "compose.yml", "docker-compose.yaml", "docker-compose.yml")
PR_RE = re.compile(r"PR\s*#?\d+|https?://\S+/pull/\d+")


def sh(cmd, cwd, timeout=300):
    try:
        p = subprocess.run(cmd, cwd=str(cwd), capture_output=True, text=True, timeout=timeout)
        return p.returncode, ((p.stdout or "") + (p.stderr or "")).strip()
    except (OSError, subprocess.TimeoutExpired) as exc:
        return 1, str(exc)


def load(path):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8-sig"))
    except (OSError, ValueError):
        return None


def registered_worktrees(root):
    code, out = sh(["git", "worktree", "list", "--porcelain"], root)
    if code != 0:
        return None
    items, cur = [], None
    for line in out.splitlines() + [""]:
        if line.startswith("worktree "):
            cur = {"path": Path(line[len("worktree "):]).resolve(), "branch": None, "prunable": False}
        elif cur is not None and line.startswith("branch "):
            cur["branch"] = line[len("branch "):].replace("refs/heads/", "", 1)
        elif cur is not None and line.startswith("prunable"):
            cur["prunable"] = True
        elif line == "" and cur is not None:
            items.append(cur)
            cur = None
    return items


def feature_state(progress, branch):
    """(decision, motivo) para el worktree de `branch` segun progress.json."""
    feat = next((f for f in (progress or {}).get("features") or [] if branch and f.get("branch") == branch), None)
    if feat is None:
        return "keep", "rama sin feature en progress.json"
    fid, notes = feat.get("feature_id"), feat.get("notes") or ""
    if feat.get("status") == "done":
        return "remove", "%s done" % fid
    blocked = notes.rfind("BLOQUEADA")
    prs = [m.start() for m in PR_RE.finditer(notes)]
    if prs and prs[-1] > blocked:
        return "remove", "%s con PR" % fid
    if blocked >= 0:
        return "keep", "%s BLOQUEADA" % fid
    return "keep", "%s en curso sin PR" % fid


def inventory(root):
    """Todo lo que coincide con ../{repo}-wt-*, clasificado. None si root no es git."""
    root = Path(root).resolve()
    regs = registered_worktrees(root)
    if regs is None:
        return None
    progress = load(root / ".dev" / "plan" / "progress.json")
    prefix = root.name + "-wt-"
    items = []
    known = set()
    for w in regs:
        if not w["path"].name.startswith(prefix):
            continue
        known.add(w["path"])
        item = {"path": str(w["path"]), "branch": w["branch"], "kind": "worktree"}
        if w["prunable"]:
            item.update(kind="prunable", decision="remove", reason="entrada prunable (la carpeta ya no es un worktree)")
        else:
            decision, reason = feature_state(progress, w["branch"])
            item.update(decision=decision, reason=reason)
            if decision == "remove":
                _code, dirty = sh(["git", "status", "--porcelain"], w["path"])
                if dirty:
                    item.update(decision="keep", reason=reason + ", pero tiene cambios sin commitear")
                elif not reason.endswith(" done"):
                    _c, remotes = sh(["git", "branch", "-r", "--contains", "HEAD"], w["path"])
                    if not remotes:
                        item.update(decision="keep", reason=reason + ", pero HEAD no esta en ningun remoto")
        items.append(item)
    for d in sorted(root.parent.glob(prefix + "*")):
        if not d.is_dir() or d.resolve() in known:
            continue
        if (d / ".git").is_dir():
            items.append({"path": str(d), "branch": None, "kind": "clone", "decision": "skip",
                          "reason": "tiene .git propio: es un clon, no un worktree del lote"})
        else:
            items.append({"path": str(d), "branch": None, "kind": "orphan", "decision": "remove",
                          "reason": "carpeta huerfana: git no la tiene registrada"})
    return items


def compose_down(path):
    if not any((Path(path) / f).is_file() for f in COMPOSE_FILES):
        return True, None
    if shutil.which("docker") is None:
        return True, "compose file sin docker en el PATH: no hay recursos que bajar desde aca"
    code, out = sh(["docker", "compose", "down", "-v", "--remove-orphans"], path, timeout=180)
    return code == 0, None if code == 0 else "docker compose down fallo: %s" % out[-200:]


def apply(root, items):
    root = Path(root).resolve()
    errors = 0
    for it in items:
        if it["decision"] != "remove":
            continue
        path = Path(it["path"])
        if path.exists():
            ok, note = compose_down(path)
            if note:
                it["note"] = note
            if not ok:
                it.update(decision="keep", result="no se limpio: los recursos del compose siguen arriba")
                errors += 1
                continue
        if it["kind"] == "worktree":
            sh(["git", "worktree", "remove", "--force", str(path)], root)
        if path.exists():
            shutil.rmtree(str(path), ignore_errors=True)
        it["result"] = "limpiado" if not path.exists() else "no se pudo borrar la carpeta"
        errors += path.exists()
    sh(["git", "worktree", "prune"], root)
    return errors


def render(items, applied):
    if not items:
        return "Worktrees del lote: ninguno en pie."
    lines = ["Worktrees del lote (%s):" % ("limpieza aplicada" if applied else "plan; --aplicar para ejecutarlo")]
    label = {"remove": "LIMPIAR", "keep": "queda", "skip": "no se toca"}
    for it in items:
        lines.append("- %s %s%s — %s%s" % (
            it.get("result") or label[it["decision"]],
            it["path"], (" [%s]" % it["branch"]) if it["branch"] else "", it["reason"],
            (" (%s)" % it["note"]) if it.get("note") else ""))
    return "\n".join(lines)


# ------------------------------------------------------------------ self-test

def self_test():
    import tempfile
    failures = 0

    def check(cond, label, detail=""):
        nonlocal failures
        print("self-test %s: %s%s" % ("ok" if cond else "FALLO", label, "" if cond else " -> %s" % detail))
        if not cond:
            failures += 1

    base = Path(tempfile.mkdtemp(prefix="cleanup-wt-")).resolve()
    try:
        g = ["git", "-c", "user.name=t", "-c", "user.email=t@t", "-c", "init.defaultBranch=main"]
        remote, app = base / "remote.git", base / "app"
        sh(g + ["init", "-q", "--bare", str(remote)], base)
        sh(g + ["init", "-q", str(app)], base)
        (app / "README.md").write_text("x\n", encoding="utf-8")
        sh(g + ["add", "."], app)
        sh(g + ["commit", "-q", "-m", "init"], app)
        sh(g + ["remote", "add", "origin", str(remote)], app)
        sh(g + ["push", "-q", "origin", "HEAD:main"], app)
        for slug in ("fg-01", "fg-02", "fg-03", "fg-04", "fg-05", "fg-06"):
            wt = base / ("app-wt-" + slug)
            sh(g + ["worktree", "add", "-q", str(wt), "-b", "feature/" + slug], app)
            (wt / (slug + ".txt")).write_text(slug, encoding="utf-8")
            sh(g + ["add", "."], wt)
            sh(g + ["commit", "-q", "-m", slug], wt)
        sh(g + ["push", "-q", "origin", "feature/fg-01"], base / "app-wt-fg-01")
        sh(g + ["push", "-q", "origin", "feature/fg-06"], base / "app-wt-fg-06")
        (base / "app-wt-fg-06" / "sin-commitear.txt").write_text("x", encoding="utf-8")
        (base / "app-wt-fg-05" / ".git").unlink()                      # limpieza a medias -> prunable
        (base / "app-wt-viejo" / "node_modules").mkdir(parents=True)   # huerfana
        (base / "app-wt-clon" / ".git").mkdir(parents=True)            # un clon ajeno
        (app / ".dev" / "plan").mkdir(parents=True)
        (app / ".dev" / "plan" / "progress.json").write_text(json.dumps({"features": [
            {"feature_id": "FG-01", "status": "in_progress", "branch": "feature/fg-01", "notes": "BLOQUEADA: x | PR #7"},
            {"feature_id": "FG-02", "status": "in_progress", "branch": "feature/fg-02", "notes": "PR #8 | BLOQUEADA: gate"},
            {"feature_id": "FG-03", "status": "done", "branch": "feature/fg-03", "notes": ""},
            {"feature_id": "FG-04", "status": "in_progress", "branch": "feature/fg-04", "notes": "PR #9"},
            {"feature_id": "FG-06", "status": "in_progress", "branch": "feature/fg-06", "notes": "PR #10"}]}),
            encoding="utf-8")

        items = inventory(app)
        by = {Path(i["path"]).name: i for i in items}
        expect = {"app-wt-fg-01": "remove", "app-wt-fg-02": "keep", "app-wt-fg-03": "remove",
                  "app-wt-fg-04": "keep", "app-wt-fg-05": "remove", "app-wt-fg-06": "keep",
                  "app-wt-viejo": "remove", "app-wt-clon": "skip"}
        got = {k: v["decision"] for k, v in by.items()}
        check(got == expect, "clasifica PR, BLOQUEADA, done, sin remoto, prunable, huerfana y clon", got)
        check("sin commitear" in by["app-wt-fg-06"]["reason"], "no limpia un worktree con cambios sin commitear")
        check("ningun remoto" in by["app-wt-fg-04"]["reason"], "no limpia commits que no estan en ningun remoto")
        errors = apply(app, items)
        left = sorted(p.name for p in base.glob("app-wt-*"))
        check(errors == 0 and left == ["app-wt-clon", "app-wt-fg-02", "app-wt-fg-04", "app-wt-fg-06"],
              "--aplicar deja solo lo que tiene que quedar", left)
        regs = [Path(w["path"]).name for w in registered_worktrees(app)]
        check(sorted(regs) == ["app", "app-wt-fg-02", "app-wt-fg-04", "app-wt-fg-06"], "git worktree list sin basura", regs)
        _c, branches = sh(["git", "branch", "--list", "feature/*"], app)
        check("feature/fg-01" in branches and "feature/fg-03" in branches, "las ramas no se tocan")
        check(inventory(base) is None, "raiz que no es repo git -> None")
    finally:
        shutil.rmtree(str(base), ignore_errors=True)
    print("SELF-TEST: %d fallo(s)" % failures)
    return 1 if failures else 0


# ------------------------------------------------------------------------ main

def main(argv):
    if "--self-test" in argv:
        return self_test()
    args = [a for a in argv if not a.startswith("--")]
    unknown = [a for a in argv if a.startswith("--") and a not in ("--aplicar", "--json")]
    if len(args) != 1 or unknown:
        print(__doc__)
        return 2
    root = Path(args[0])
    items = inventory(root)
    if items is None:
        print("error: %s no es un repositorio git" % root)
        return 2
    applied = "--aplicar" in argv
    errors = apply(root, items) if applied else 0
    if "--json" in argv:
        print(json.dumps({"applied": applied, "errors": errors, "worktrees": items}, ensure_ascii=False, indent=2))
    else:
        print(render(items, applied))
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
