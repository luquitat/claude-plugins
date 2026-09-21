# Pipeline: Build (ejecucion del plan)

Pipeline que ejecuta el plan generado por `planning-pipeline`: toma los briefs de
`.dev/features/`, implementa cada feature en su propia rama verificando los criterios
de aceptacion, y construye lotes completos en paralelo (un agente por feature, un
worktree por agente).

**Agnostico de stack por diseno**: todo lo especifico del proyecto sale del perfil de
stack (`stack-profile.json`) y de la base de seguridad (`security-baseline.json`),
descubiertos por evidencia del repo. **Seguridad por construccion**: el implementador
codea con el piso OWASP del baseline y el `security-gate` lo verifica antes del PR; lo
que excede el piso se deriva a `/auditar`. **Documentacion por construccion**: cada
feature sale con su guia de usuario (`.dev/manual/{slug}.md`), escrita en paralelo
con el review y best-effort. **Lo mecanico por script**: verificacion, progreso,
contratos, compuertas, deuda tecnica, indice y resumen los hacen scripts
deterministas; los modelos se reservan para construir, revisar y documentar.

---

## Flujo

```
.dev/features/{b}.md                <- ENTRADA (briefs; {b} = brief_basename FG-xx-{slug})
.dev/plan/execution-plan.json          (lotes y ronda de contratos)
.dev/plan/progress.json                (estado; solo via progress_update.py)
        |
        v  [stack-profiler] (primera vez / stale; modo parcial tras el greenfield)
.dev/build/stack-profile.json + security-baseline.json
        |
        +-----------------------------+------------------------------+
        |                                                            |
   /construir <feature>                                      /construir-lote [BATCH-n]
        |                                                            |
   [feature-implementer, modo plan] (sonnet)                 ronda de contratos si esta
        -> PAUSA: aprobar el plan                            pendiente (implementar,
        |                                                    verify, review+gate, merge)
   rama feature/{slug}                                              |
   [feature-implementer, modo ejecucion] (opus)              un worktree por feature
     tarea por tarea: implementar con piso OWASP             [feature-implementer x N]
     -> tests Gherkin -> lint -> commit [T-xxx]              EN PARALELO (tandas de
     -> desvios/{b}.json si hubo desvios                     max_parallel_degree)
        |                                                            |
   verify.py -> verification/{b}.json                        por feature, apenas termina
   diff capturado -> .diff/{b}.patch                         su implementador (sin esperar
        |                                                    a la mas lenta): verify.py,
   UNA TANDA PARALELA:                                       patch, y la misma tanda
     [build-reviewer] (opus)                                 paralela de tres agentes
     [security-gate] (sonnet; opus si A01/A02/A07)                  |
     [user-docs-writer] (sonnet, especulativo)               lazos por feature (delta
        |                                                    del fix, tope 3 rondas)
   validate_verdict.py por veredicto                                |
   lazo de correccion: fix -> verify.py -> patch             render_cr_input.py
   DEL DELTA -> re-review con ids a cerrar (tope 3)          validate_verdict.py --compuerta
        |                                                    push + PR por feature
   render_cr_input.py (cr-input, tech-debt)                         |
   validate_verdict.py --compuerta                           render_manual_index.py
   PR + render_batch_summary.py                              render_batch_summary.py --lote
        |                                                            |
        +-----------------------------+------------------------------+
                                      v
                    progress.json al dia (done = mergeado; PRs anotados)
```

---

## Agentes y scripts

| Agente | Modelo | Rol |
|---|---|---|
| `stack-profiler` | sonnet | Perfil de stack + base de seguridad por evidencia; modo parcial `--solo-validar-comandos` |
| `feature-implementer` | opus (plan: sonnet) | Construye una feature con piso OWASP; emite `desvios/{b}.json` |
| `build-reviewer` | opus | Diff contra brief y convenciones; consume `verification/{b}.json` |
| `security-gate` | sonnet (opus si A01/A02/A07) | Piso OWASP sobre el diff; audit desde `verification/` |
| `user-docs-writer` | sonnet | Guia de usuario, especulativa y best-effort |

| Script | Rol |
|---|---|
| `verify.py` | test + lint + audit una vez por ronda → `verification/{b}.json`; con `accepted-baseline.json` (`--capturar-baseline`), bloquea ante regresiones, no ante lo heredado |
| `progress_update.py` | unica via de escritura de `progress.json` (`--init`, transiciones, `--estado`) |
| `validate_verdict.py` | contrato de veredictos; `--compuerta` = compuerta dura pre-PR |
| `render_cr_input.py` | `cr-input-{b}.md` + `tech-debt.md` con dedupe |
| `render_manual_index.py` | indice del manual; `--cobertura` para DOCUMENTAR |
| `render_batch_summary.py` | resumen final de lote o feature, con los worktrees en pie |
| `cleanup_worktrees.py` | cierre del lote: limpia worktrees de features cerradas, `prunable` y huerfanos |

La orquestacion comun vive en `skills/build-pipeline/SKILL.md`; cada modo en
`skills/build-pipeline/modes/`. Referencias: `reference/owasp-baseline.md` (solo la
lee el profiler) y `reference/tono.md` (solo modos interactivos).

---

## Reglas de orquestacion

- **Compuerta de lote**: una feature se construye solo con sus `unlocks_after` en
  `done` y la ronda de contratos mergeada.
- **Control asimetrico**: `/construir` pausa una vez (aprobacion del plan);
  `/construir-lote` no pausa (el control queda en los PRs).
- **Verificacion obligatoria y unica**: `verify.py` corre la suite una vez por
  ronda; reviewer y gate leen el resultado. El cierre por requisito
  (`requirements_closure`) lo audita el reviewer. Los PRs se verifican ademas por el
  CI del proyecto (bootstrapeado si falta).
- **Paralelismo obligatorio**: reviewer + gate + docs en una sola tanda; en LOTE,
  cada feature entra a review apenas termina su implementador.
- **Lazo de correccion por delta**: la re-review recibe el diff del fix y los ids a
  cerrar, no el diff completo. Tope 3 rondas; lo no corregible se bloquea y escala.
- **Compuerta dura por script**: `validate_verdict.py --compuerta` antes de cada PR.
- **`progress.json` solo por script**: `done` = mergeado; es el insumo de
  `/replanificar`.
- **Trazabilidad**: `[T-xxx]` en commits, `FG-xx`/`T-xxx`/`RF-xxx` en PRs, ids
  namespaced `FG-xx/FIND-nnn` y `FG-xx/SGATE-nnn` en veredictos y commits de fix,
  vocabulario del LEL en los identificadores. Los desvios del implementador salen
  estructurados y terminan en `cr-input-{b}.md` para `/requerimientos:cambio`.

---

## Como iniciar

```
/construir importacion-padron        (una feature, con aprobacion del plan)
/construir-lote                      (el proximo lote desbloqueado, en paralelo)
/construir-lote BATCH-2              (un lote especifico)
/documentar                          (guias de usuario retroactivas)
```

## Estructura resultante

```
.dev/build/
  stack-profile.json  security-baseline.json
  verification/{b}.json    reviews/{b}.json    security/{b}.json    desvios/{b}.json
  cr-input-{b}.md          tech-debt.md        .diff/{b}.patch (no se commitea)
.dev/plan/progress.json    solo via progress_update.py
.dev/manual/{slug}.md      guia por feature;  .dev/manual/README.md indice derivado
ramas feature/{slug}       una por feature -> PR a la rama de integracion
```
