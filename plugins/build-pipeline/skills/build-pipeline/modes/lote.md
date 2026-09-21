# Modo LOTE (`/construir-lote [BATCH-n]`)

Construye un lote completo en paralelo, **sin pausas de aprobacion** (el control queda
en los PRs). Las convenciones, los scripts y las reglas son las de `SKILL.md`; `{b}`
es el `brief_basename` y `{raiz}` la raiz del repo principal (los scripts se corren
siempre contra `{raiz}`, con `--cwd <worktree>` cuando ejecutan comandos).

1. **Determinar el lote**: el indicado, o el primer lote elegible cuyo
   `unlocks_after` este completo (elegible = features `pending`, o `in_progress` sin
   PR anotado: eso es un **retome**, se reanudan desde sus commits `[T-xxx]`). Si la
   **ronda de contratos** esta pendiente, ejecutala primero: un `feature-implementer`
   con esas tareas (criterios en `tasks.json`; no hay brief) en `contracts/{ronda}`;
   `verify.py`; `build-reviewer` **y** `security-gate` en la misma tanda (la ronda no
   tiene FG: sus veredictos, desvios y hallazgos usan el namespace `FG-00` y el nombre
   `contracts-{ronda}`); merge a la
   rama de integracion (el unico merge directo del pipeline — si el repo exige PR,
   abrilo, avisa que bloquea y espera). `progress_update.py` con sus tareas `done`.
2. **Perfil de stack** (convenciones). **Greenfield sin esqueleto**: construi UNA
   feature del lote en secuencia primero (su primera tarea crea el esqueleto),
   mergeala por PR, y recien despues paraleliza; con ese merge, re-invoca
   `stack-profiler` en modo `--solo-validar-comandos`. **Proyecto con historia** sin
   `accepted-baseline.json`: capturala sobre la integracion antes de cualquier rama
   (convencion **Linea de base**; si hay ronda de contratos, antes de ella).
3. **Un worktree por feature**, y `--status in_progress --branch feature/{slug}`
   recien cuando el worktree quedo listo:
   `git worktree add ../{repo}-wt-{slug} -b feature/{slug} {rama_integracion}`.
   - Restos de corridas anteriores: si retomas, reusalos; si no,
     `cleanup_worktrees.py {raiz} --aplicar` (baja el compose del worktree, lo
     remueve con `--force`, barre `prunable` y huerfanas; nunca pierde trabajo sin
     commitear o sin pushear).
   - Bootstrap: corre `commands.install` del perfil en cada worktree y copia la
     config local no versionada que los tests necesiten (`.env` de test). Usa la
     cache del gestor para no descargar N veces (`npm ci --prefer-offline`, el store
     de pnpm, `GOMODCACHE`, `pip --cache-dir`; si el gestor lo permite, enlaza el
     arbol de dependencias del repo principal).
   - Tandas: si el lote supera `max_parallel_degree` del plan, lanza en tandas de
     ese tamano. Recursos compartidos de test (una DB local, puertos fijos): si las
     suites colisionan, `verify.py` de esas features en secuencia y anotalo.
4. **Implementadores en paralelo**: una sola llamada con N Task de
   `feature-implementer` en **modo ejecucion** (sin modo plan), cada uno con su
   worktree como ruta de trabajo.
5. **Pipeline por feature, sin esperar a la mas lenta**: apenas termina cada
   implementador (y sin esperar a los demas de la tanda): `progress_update.py` con
   sus tareas; `verify.py {raiz} --brief {b} --cwd <worktree>` (si falla, vuelve al
   implementador con la `tail` antes de gastar review); patch del diff; y **en una
   sola tanda** `build-reviewer` + `security-gate` (opus solo si toca A01/A02/A07) +
   `user-docs-writer` especulativo. Las tandas de review de distintas features
   tambien van en paralelo entre si. `validate_verdict.py` sobre cada veredicto.
6. **Lazo de correccion** (tope 3 rondas por feature): `high`/`medium` de cualquiera
   → `feature-implementer` en modo correccion con ambos veredictos; `verify.py`;
   patch **del delta del fix**; re-review de `build-reviewer` (y `security-gate` si
   aplica) con la lista de ids a cerrar. Si no pasa, o hay `no_corregible`:
   `--note "BLOQUEADA: <motivo>"`, rama y worktree quedan en pie, y segui — un
   bloqueo no frena a las demas.
7. **Cierre por feature** (review y gate en verde): commit de la guia si la hubo (o
   `--note "SIN GUIA: <motivo>"`); `render_cr_input.py {raiz} --brief {b}`;
   `validate_verdict.py {raiz} --compuerta --brief {b}` — si esta CERRADA, la
   feature no abre PR: `--note "BLOQUEADA: <salida del script>"`. Con la compuerta
   ABIERTA: push, PR contra la rama de integracion, `--note "PR #n"`, baja los
   recursos externos que ese worktree haya levantado — contenedores y volumenes de
   su proyecto compose (`docker compose down -v` corrido en el worktree), DBs
   efimeras de test — y recien entonces `git worktree remove` (borrar la carpeta no
   los borra: quedan nombrados por directorio y sobreviven como basura). Los
   worktrees de features bloqueadas quedan en pie, con sus recursos.
   **Narracion dosificada**: al cerrar cada feature, 2-3 lineas al usuario (estado,
   PR, dato saliente) mas el puntero a sus veredictos. Nada de hallazgos ni cierres
   por requisito en el medio del lote: el detalle vive en los artefactos.
8. **Cierre del lote**: `cleanup_worktrees.py {raiz} --aplicar` siempre, aunque
   hayas limpiado feature por feature (es la red: barre lo que el paso 7 no bajo y
   restos de lotes anteriores); `render_manual_index.py {raiz}` (commit en la primera rama de
   la corrida si cambio; ofrece regenerarlo si los PRs mergearon en sesion);
   `render_index.py .dev`; y el **resumen final** es la salida de
   `render_batch_summary.py {raiz} --lote BATCH-n` tal cual, mas: worktrees de
   features bloqueadas y como retomarlas (resolver el motivo y re-correr
   `/construir-lote`), y el proximo paso (mergear los PRs y, con las features `done`,
   el siguiente lote; `/replanificar` si llegaron cambios de requisitos; `/auditar`
   si el gate dejo `deferred_to_audit`; `/publicar-manual` si hay guias nuevas).
