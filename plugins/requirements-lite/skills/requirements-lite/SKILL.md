---
name: requirements-lite
description: Pipeline liviano de ingenieria de requisitos. Convierte un documento de dominio (Word, PDF o Markdown) o una sesion conversacional en una linea de base de requisitos compacta y compatible con planning-pipeline (requirements.json + data-model.json + technical-design.json), sin LEL ni escenarios. Usar cuando el proyecto no justifica el rigor del pipeline pesado: MVPs, proyectos chicos, refresh de existentes o encargos con scope acotado.
---

# Pipeline Liviano de Requisitos (sketch)

Esta skill orquesta una version reducida del pipeline de requisitos: 3 etapas
en serie, sin pausa intermedia, con una pausa **opcional al final** para
consolidar dudas. El output es interoperable con `planning-pipeline`.

Vos, el agente principal, sos el orquestador: ejecutas el script de extraccion
si hay documento y delegas cada etapa al subagente correspondiente con la
herramienta Task. Las etapas son secuenciales: cada una consume lo que
escribio la anterior.

## Cuando usar este pipeline (y cuando no)

**Usa este pipeline cuando:**
- El proyecto es un MVP, un prototipo o tiene scope acotado (2-8 semanas).
- No hay stakeholder formal: el usuario es tambien cliente y dev.
- Es un refresh de un proyecto que ya existe (no especificacion desde cero).
- Queres iterar rapido y no pagas auditabilidad lingüistica.

**Usa el pipeline pesado (`requirements-pipeline`) cuando:**
- El proyecto es regulado o tiene compliance estricto.
- Hay un stakeholder externo que necesita validar requisitos formalmente.
- La trazabilidad RF → escenario → episodio → simbolo del LEL es un entregable.
- El equipo es grande (5+ devs) y el vocabulario unificado del LEL paga.

## Subagentes (en `.claude/agents/` o cargados por el plugin)

| Orden | Subagente | Lee | Escribe |
|---|---|---|---|
| 1 | `brief-intake` | texto extraido o input conversacional | `brief.json`, `brief.md` |
| 2 | `requirements-sketch` | `brief.json` | `requirements.json`, `requirements.md` |
| 3 | `design-sketch` | `requirements.json`, `brief.json`, mockups opcionales | `data-model.json`/`.md`, `technical-design.json`/`.md` |

Todos los archivos se generan en `.dev/requirements/` del proyecto actual.

## Procedimiento

### Paso 0a - Opt-in del plugin experiments (chequeo por proyecto)

Antes de arrancar, lee `.dev/.experiments.json` del proyecto. Tres casos:

1. **El archivo no existe**: es la primera vez que un plugin participa de
   este flujo en este proyecto. Preguntale al usuario:
   > "Hay un plugin opcional `experiments` que puede medir esta corrida
   > (cobertura, refs colgadas, tamano, tiempo), guardarla como evidencia y,
   > cuando junte varias, sugerir mejoras al plugin actual. No corre nada
   > sin tu permiso explicito. Activarlo solo agrega una pregunta al cierre
   > de cada corrida. **¿Activar para este proyecto? (s/n, default n)**"

   Si responde si: crea `.dev/.experiments.json` con
   `{"version": 1, "opt_in": true, "created_at": "<iso8601>", "updated_at": "<iso8601>", "runs": []}`.
   Si responde no: crea el mismo archivo con `"opt_in": false`. En ambos
   casos no preguntes mas en futuras corridas.

2. **Existe con `opt_in: true`**: continua silenciosamente; al cierre vas a
   ofrecer experiments.

3. **Existe con `opt_in: false`**: continua silenciosamente; saltea el
   prompt de cierre.

No bloquees el flujo por esto: si el usuario no responde rapido o el archivo
no se puede leer, asume `opt_in: false` y segui.

### Paso 0 - Modo de entrada

Pregunta o detecta:
- **Modo documento**: el usuario te pasa una ruta `.docx`, `.pdf` o `.md`. Vas
  al Paso 1.
- **Modo conversacional**: el usuario no tiene documento. Salta al Paso 2 sin
  extraer nada; el orquestador hace una entrevista corta (5-8 preguntas
  cubriendo: que es el sistema, quien lo usa, scope, restricciones de stack,
  performance, dudas conocidas) y guarda las respuestas pegadas en el prompt
  para pasarselas a `brief-intake`.

### Paso 1 - Extraer el texto (solo modo documento)

Crea `.dev/requirements/sources/` y extrae el texto con el script de esta
skill, igual que el pipeline pesado:

```bash
python3 "${CLAUDE_SKILL_DIR}/scripts/extract_document.py" \
  "<ruta-del-documento>" ".dev/requirements/sources/<nombre>.txt"
```

Si `${CLAUDE_SKILL_DIR}` no esta definida, ubica `extract_document.py` dentro
de la carpeta `scripts/` de esta skill y ejecutalo igual. Para PDF, si falta
biblioteca: `pip install pypdf`.

### Paso 2 - Etapa 1: `brief-intake`

Invoca `brief-intake` con la herramienta Task:
- En modo documento: pasale la ruta del texto extraido.
- En modo conversacional: pegale en el prompt el contenido conversado (vision,
  actores, scope, restricciones, dudas).

Espera a que termine. Verifica que `.dev/requirements/brief.json` existe y es
JSON valido. Si no, frena el pipeline e informa al usuario.

### Paso 3 - Etapa 2: `requirements-sketch`

Invoca `requirements-sketch`. Lee `brief.json` y escribe `requirements.json` +
`.md`. Verifica que el JSON es valido y que cada `feature_group` tiene
`requirement_ids` no vacios.

### Paso 4 - Consulta de mockups y Etapa 3: `design-sketch`

Antes de invocar `design-sketch`, PREGUNTALE al usuario si tiene assets de
diseno de UI (mockups HTML, wireframes, CSS, capturas). Pueden estar en
cualquier carpeta del proyecto.

- Si los hay: pasale la ruta a `design-sketch`. Toma los mockups como diseno
  autoritativo.
- Si no: invoca `design-sketch` sin assets. Las pantallas se proponen
  abstractamente.

Cuando `design-sketch` termina, verifica que `data-model.json` y
`technical-design.json` son JSON validos.

### Paso 5 - Pausa OPCIONAL: consolidacion de dudas

Junta los `open_questions[]` de los 4 artefactos (`brief.json`,
`requirements.json`, `data-model.json`, `technical-design.json`) en un archivo
`.dev/requirements/open-questions.md` con esta estructura:

```markdown
# Preguntas abiertas - <nombre del proyecto>

## Bloqueantes (blocking: true)
- **Q-001** (de brief.json): <pregunta>
  - target_role: <quien deberia responder>
  - reason: <que se asume si no se responde>
  - related: <ids referenciados>

## No bloqueantes (blocking: false)
- ...
```

Mostrale al usuario el `open-questions.md` y ofrecele tres opciones:

1. **Responder dudas**: el usuario aporta respuestas; vos guardalas en
   `.dev/requirements/open-questions-answers.md` (una respuesta por Q-XXX) y
   hace un **re-run selectivo** solo de las etapas afectadas:
   - Si la duda afecta el brief (vision, scope, actores, capacidades):
     re-corre `brief-intake` → `requirements-sketch` → `design-sketch` (cadena
     completa, porque cambia la base).
   - Si afecta solo `requirements.json` (RF/RNF/AC): re-corre
     `requirements-sketch` → `design-sketch`.
   - Si afecta solo `data-model.json` o `technical-design.json` (ADR,
     entidad, modulo, pantalla): re-corre solo `design-sketch`.
2. **Continuar con las asunciones**: cierra el pipeline. Las dudas quedan
   marcadas en cada artefacto y en `open-questions.md`.
3. **Iterar luego**: el usuario puede volver a correr la skill mas tarde con
   respuestas; el pipeline detecta `open-questions-answers.md` si existe y
   propaga las respuestas.

No pauses si el usuario, al arrancar la skill, indica explicitamente "sin
pausa" o "no me preguntes". En ese modo, escribi `open-questions.md` igual
pero cierra el pipeline sin esperar respuesta.

### Paso 6 - Cierre

Informa al usuario los archivos generados en `.dev/requirements/`. Resaltale:
- Cantidad de capacidades (`brief.json`), feature_groups (`FG-XX`), RF, RNF,
  entidades, modulos y ADRs.
- Cantidad total de open_questions y cuantas son bloqueantes.
- Si hay siguiente paso natural: "podes ejecutar `/planificar` para derivar el
  plan de tareas y sprints sobre estos requisitos".

### Paso 6b - Registro en .dev/.experiments.json + prompt opcional de experiments

Despues del cierre normal, actualiza `.dev/.experiments.json` agregando una
entrada a `runs[]`:

```json
{
  "plugin": "requirements-lite",
  "ran_at": "<iso8601>",
  "outputs_path": ".dev/requirements/",
  "baseline_ref": null,
  "notes": "<resumen 1 linea: counts y dudas blocking>"
}
```

Despues:
- Si `opt_in: true`: mostrale al usuario este texto explicativo y la pregunta
  > "El plugin `experiments` puede medir esta corrida (cobertura de
  > capabilities, refs colgadas, tamano del output, tiempo) y compararla
  > contra una baseline para detectar drift o sugerir mejoras al plugin.
  > **¿Correr `/exp-bench requirements-lite` ahora? (s/n, default n)**"
  >
  > "Si decis si: se genera `.dev/experiments/requirements-lite/bench-<fecha>.md`
  > con metricas + observaciones, sin tocar tu output. Si decis no, queda
  > para despues; podes correrlo en cualquier momento."

  Si responde si: dispara `/exp-bench requirements-lite` (asume que el plugin
  existe; si no, avisar al usuario que no esta instalado).
  Si responde no o no responde: cierra.

- Si `opt_in: false`: cierra sin preguntar nada.

## Reglas de orquestacion

- El pipeline es estrictamente secuencial: no lances una etapa sin el archivo
  de entrada de la anterior.
- No hay pausa intermedia con stakeholder (la del pipeline pesado): las dudas
  se consolidan al final.
- Ningun agente debe inventar respuestas: si un dato no esta en el brief, lo
  registra como `open_question` con `blocking: true|false`, no completa con
  defaults silenciosos.
- Si un subagente falla o produce un archivo vacio, detene el pipeline e
  informa al usuario.
- Despues de cada etapa, valida que el archivo de salida sea JSON valido y que
  los ids referenciados existan. Si hay referencias colgadas, volve a invocar
  el agente con el detalle del problema antes de continuar.

## Comparacion vs el pipeline pesado

| Aspecto | `requirements-pipeline` (pesado) | `requirements-lite` (este) |
|---|---|---|
| Etapas | 8 + 2 loops de inspeccion | 3, sin loops |
| Artefactos intermedios | LEL, scenarios, inspecciones | brief (1 artefacto) |
| Pausa con stakeholder | Obligatoria en el medio | Opcional al final |
| Trazabilidad | RF → escenario → episodio → simbolo LEL | RF → capability del brief |
| Normalizacion auto | Inspeccion + loop de correccion | No (revision visual) |
| Volumen tipico | 50+ RF, 15+ RNF, 14 features, 20 ADRs | 15-30 RF, 4-10 RNF, 5-10 features, 2-5 ADRs |
| Costo relativo (tokens) | 100% | ~25-35% |
| Salida compatible con `planning-pipeline` | Si | Si (mismo schema minimo) |

## Estructura `.dev/requirements/` resultante

```
.dev/requirements/
  sources/                            texto extraido del documento (si modo doc)
  brief.json / brief.md               brief compacto
  requirements.json / .md             requisitos funcionales y no funcionales
  data-model.json / .md               entidades y relaciones
  technical-design.json / .md         stack, modulos, API, pantallas, ADRs
  open-questions.md                   consolidado de dudas (al cierre)
  open-questions-answers.md           respuestas del usuario (si las hubo)
```

Despues de este pipeline, los outputs son consumibles por
`planning-pipeline` para derivar tareas, sprints y lotes paralelos.
