# Modo FEATURE (`/construir <feature>`)

Construye una feature, con aprobacion del plan de implementacion antes de codear.
Las convenciones, los scripts y las reglas son las de `SKILL.md`; `{b}` es el
`brief_basename` y `{raiz}` la raiz del repo.

1. **Resolver la feature** contra `.dev/features/` (slug o nombre; si hay
   ambiguedad, lista y pregunta). Verifica la compuerta de lote y el estado con
   `progress_update.py {raiz} --estado FG-xx`. Si falta la **ronda de contratos**,
   ofrece ejecutarla aca (paso 1 del modo LOTE) y retoma despues. Si la feature esta
   `in_progress`, pregunta si retomar: reusar su rama, leer el log `[T-xxx]` para
   saber que tareas ya estan y seguir desde la primera sin commit. Si esta `done` y lo
   pendiente es un lote de ajuste (`adjustment: true`), construi solo esas tareas en
   `feature/{slug}-ajuste`.
2. **Perfil de stack** (convenciones). Si el proyecto no tiene CI que corra test y
   lint, bootstrapealo en esta rama. En un proyecto con historia sin
   `accepted-baseline.json`, capturala antes de crear la rama (convencion **Linea de
   base**).
3. **Plan de implementacion**: invoca `feature-implementer` en **modo plan** con
   `model: sonnet` (reordena el brief, no razona codigo: no necesita opus). Mostrale
   al usuario el plan (enfoque por tarea, archivos, verificacion) y **espera su
   aprobacion**; si pide cambios, ajusta y volve a mostrar. Sin OK no se toca codigo.
4. **Ejecucion**: crea `feature/{slug}`, `progress_update.py {raiz} --feature FG-xx
   --status in_progress --branch feature/{slug}`, e invoca `feature-implementer` en
   **modo ejecucion** con el plan aprobado. Con su reporte: `progress_update.py` con
   `--task T-xxx=done` por tarea verificada y `--task T-xxx=blocked --task-note
   T-xxx="motivo"` por tarea bloqueada.
5. **Verificacion**: `verify.py {raiz} --brief {b}`. Si falla, re-invoca al
   implementador con la `tail` del comando fallido (es un fix, no un review) y volve
   a correr `verify.py`.
6. **Tanda de review** (una sola llamada con tres Task en paralelo): captura el diff a
   `.dev/build/.diff/{b}.patch` y lanza `build-reviewer`, `security-gate` (con
   `model: opus` si el diff toca A01, A02 o A07 segun las `applicable_categories` del
   baseline y los archivos tocados; si no, el default sonnet) y `user-docs-writer`
   (especulativo). Pasale a los tres la ruta del patch, el brief y
   `verification/{b}.json`. Al recibir cada veredicto: `validate_verdict.py`.
7. **Lazo de correccion** (tope 3 rondas): si review o gate tienen `high`/`medium`,
   re-invoca `feature-implementer` en **modo correccion** con ambos veredictos.
   Despues: `verify.py` de nuevo, patch **del delta del fix**
   (`git diff {sha_previo}..HEAD`) y re-review con `build-reviewer` (y `security-gate`
   solo si tuvo hallazgos), pasandoles la lista de ids a cerrar: verifican
   `resolved_findings` sobre el delta, no re-revisan todo. Re-invoca
   `user-docs-writer` solo si el fix cambio comportamiento visible. Si al tercer
   intento algo sigue sin pasar, o hay un `no_corregible`, `progress_update.py
   --note "BLOQUEADA: <motivo>"` y escalale el caso al usuario. Los
   `deferred_to_audit` no bloquean: se anotan para sugerir `/auditar`.
8. **Cierre de feature**: commitea la guia si la hubo (`docs: guia de usuario
   {slug}`) o `--note "SIN GUIA: <motivo>"`; `render_cr_input.py {raiz} --brief {b}`
   (cr-input y tech-debt); `render_manual_index.py {raiz}` si es la primera rama de
   la corrida.
9. **Compuerta dura pre-PR**: `validate_verdict.py {raiz} --compuerta --brief {b}`.
   Si esta CERRADA, el PR no se abre: mostra la salida del script y volve al paso 7.
   Con la compuerta ABIERTA, crea el PR contra la rama de integracion,
   `progress_update.py --note "PR #n"`, y mostrale al usuario la salida de
   `render_batch_summary.py {raiz} --features FG-xx` mas el link del PR y el proximo
   paso. Si el usuario mergea en la sesion, `--status done`. Al cierre, regenera
   `.dev/README.md` con `render_index.py`.
