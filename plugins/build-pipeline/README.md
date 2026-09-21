# Build Pipeline — Plugin de Claude Code

Plugin que **ejecuta el plan**: toma los briefs que genera `planning-pipeline` en
`.dev/features/`, implementa cada feature en su propia rama verificando los criterios
de aceptacion, y construye lotes completos **en paralelo** (un subagente por feature,
cada uno en su git worktree). Cierra el ciclo: requisitos → plan → **build** →
progreso que retroalimenta la replanificacion.

## Agnostico de stack, en serio

El plugin no tiene una linea de Next.js, Laravel, Django ni de ningun framework. Lo
que un build necesita saber del proyecto se **descubre por evidencia** la primera vez
(`stack-profiler`): manifiestos, configs de test y lint, pipelines de CI, `CLAUDE.md` y
el `stack[]` del diseno tecnico. El resultado es `.dev/build/stack-profile.json`:
comandos exactos de test/lint/build, layout, convenciones y rama de integracion —
validados cuando se puede, marcados como deducidos cuando no. Para soportar un stack
nuevo no se modifica el plugin: se corre en el proyecto.

## Seguridad por construccion (piso OWASP)

En la misma pasada, `stack-profiler` deriva la **base de seguridad** del stack en
`.dev/build/security-baseline.json`: superficie de ataque, categorias OWASP Top 10
aplicables, el mecanismo **nativo** del stack para cada una y el comando de audit de
dependencias. Es el unico artefacto de seguridad que leen el `feature-implementer`
(codea con ese piso) y el `security-gate` (lo verifica antes del PR): la referencia
larga `reference/owasp-baseline.md` la lee solo el profiler, una vez por proyecto.
El gate es **prevencion**, no auditoria: corre en sonnet y el orquestador lo escala a
opus solo cuando el diff toca control de acceso, criptografia o autenticacion. La
auditoria profunda sigue siendo `audit-pipeline` (`/auditar`).

## Lo mecanico lo hacen scripts, no modelos

Todo lo derivado, determinista o repetitivo del build vive en
`skills/build-pipeline/scripts/` (stdlib, con `--self-test`):

| Script | Reemplaza |
|---|---|
| `verify.py` | Correr test, lint y audit una vez por ronda y dejar `verification/{b}.json`; reviewer y gate lo leen en vez de re-correr la suite y parsear logs. En proyectos con historia, `--capturar-baseline` fija el rojo heredado y los advisories aceptados, y la verificacion bloquea solo ante regresiones |
| `progress_update.py` | Editar `progress.json` a mano en cada transicion |
| `validate_verdict.py` | Validar el contrato de cada veredicto clave por clave, y la compuerta dura pre-PR (`--compuerta`) |
| `render_cr_input.py` | Redactar `cr-input-{b}.md` desde los desvios del implementador y acumular `tech-debt.md` con dedupe |
| `render_manual_index.py` | Regenerar el indice del manual y cruzar features `done` contra guias (`--cobertura`) |
| `render_batch_summary.py` | El resumen final consolidado de un lote o una feature |
| `cleanup_worktrees.py` | Bajar a mano los worktrees del lote (y sus contenedores) al cerrarlo, y los restos a medio borrar |

Y las decisiones de orquestacion que ahorran contexto: el diff se captura **una
vez** a `.dev/build/.diff/{b}.patch` y se pasa por ruta; la re-review recibe **solo
el delta del fix** y los ids a cerrar; reviewer, gate y docs-writer se lanzan
**siempre en una sola tanda paralela**; el modo plan del implementador corre en
sonnet; y la skill esta partida por modo (`modes/feature.md`, `modes/lote.md`,
`modes/documentar.md`) para cargar solo lo que la corrida usa.

## Documentacion de usuario final

Cada feature sale ademas con su **guia de usuario**: `.dev/manual/{slug}.md`, un
Markdown escrito por `user-docs-writer` para una persona no tecnica, en el
vocabulario del LEL y fiel al comportamiento **real construido**. Se escribe en
paralelo con el review (especulativa: si una correccion cambia comportamiento
visible, se re-invoca) y viaja en el PR de la feature. Es best-effort: nunca bloquea.
El indice del manual lo regenera `render_manual_index.py`; la publicacion HTML es
`/publicar-manual` (plugin `manual-usuario`). `/documentar` genera retroactivamente
las guias de features construidas antes de este paso.

## Modo gastada (el build te va a cargar)

En los modos interactivos el orquestador habla en tono de **gastada rioplatense**:
entre dato y dato te tira comentarios graciosos y un poco denigrantes. Solo en la
conversacion — commits, PRs, veredictos y guias salen impecables — y las malas
noticias serias van en serio. "Modo serio" lo apaga. El registro esta en
`reference/tono.md`.

## Que necesitas antes

La salida de `planning-pipeline`: `.dev/features/*.md` y
`.dev/plan/execution-plan.json` (`progress.json` se inicializa solo). `CLAUDE.md` con
convenciones ayuda, no es obligatorio. Python 3 para los scripts.

## Uso

```
/construir <feature>          una feature, con tu aprobacion del plan de implementacion
/construir-lote [BATCH-n]     un lote completo en paralelo, sin pausas
/documentar [feature]         guias de usuario retroactivas para features ya construidas
```

`/construir` te muestra el plan de implementacion y espera tu OK; despues
implementa tarea por tarea con commits `[T-xxx]`, verifica por script, pasa review y
gate (lazo de correccion con tope de 3 rondas) y abre el PR con el resumen.
`/construir-lote` hace lo mismo para todo un lote sin pausas: ronda de contratos
primero si esta pendiente, un worktree por feature, implementadores en paralelo, y
cada feature entra a su review apenas termina — un bloqueo no frena a las demas.

Tambien podes repartir un lote entre **varias instancias** de Claude Code, cada una
con `/construir <feature>`: `progress.json` coordina el estado si viaja por git
(commitear y pushear el claim al marcar `in_progress`, pullear antes de la compuerta
de lote y antes de marcar `done`).

## Estructura del plugin

```
build-pipeline/
  .claude-plugin/plugin.json
  agents/
    stack-profiler.md        perfil de stack + base de seguridad (por evidencia; modo parcial)
    feature-implementer.md   construye una feature (plan en sonnet / ejecucion / correccion)
    build-reviewer.md        revisa el diff contra el brief; lee verification/, no corre tests
    security-gate.md         piso OWASP (sonnet; opus si toca A01/A02/A07)
    user-docs-writer.md      guia de usuario (especulativa, best-effort)
  skills/build-pipeline/
    SKILL.md                 lo comun: convenciones, scripts, reglas, layout
    modes/{feature,lote,documentar}.md   procedimiento por modo, cargado a demanda
    scripts/*.py             verify, progress_update, validate_verdict, cleanup_worktrees, render_*
  commands/                  /construir, /construir-lote, /documentar
  reference/
    owasp-baseline.md        referencia OWASP (la lee solo stack-profiler)
    tono.md                  registro de la gastada (solo modos interactivos)
  PIPELINE.md  README.md
```

## Garantias

- **Nada sin verificar**: una tarea termina cuando sus criterios Gherkin corren en
  verde, y la suite la corre `verify.py` — ningun agente cree en un reporte, lee un
  exit code.
- **Nada fuera del brief**: sin features extra ni dependencias que el diseno no
  pida; tocar otra feature del lote es hallazgo `high`.
- **Piso de seguridad OWASP** verificado antes del PR; veredictos en
  `.dev/build/security/`.
- **Compuerta dura por script**: ningun PR se abre sin review y gate validos en
  `passed: true` y de la misma rama.
- **Trazabilidad hasta el codigo**: commits `[T-xxx]` → tarea → requisito →
  escenario → LEL → fuente; desvios estructurados que terminan en un CR.
- **`progress.json` siempre al dia y siempre valido**: `done` = mergeado; solo lo
  escribe `progress_update.py`.

Ver `PIPELINE.md` para el diagrama y las reglas de orquestacion. El plugin
`feature-pipeline` (primera generacion, atado a Next.js) esta en `archive/`.
