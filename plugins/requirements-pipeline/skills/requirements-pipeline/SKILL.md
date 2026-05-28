---
name: requirements-pipeline
description: Genera un flujo completo de ingenieria de requisitos (LEL, inspeccion, preguntas a stakeholders, escenarios, requisitos funcionales y no funcionales, y diseno tecnico con modelo de datos y arquitectura) a partir de un documento de dominio en Word, PDF o Markdown. Usar cuando el usuario quiere convertir documentacion o una especificacion en requisitos estructurados y trazables.
---

# Pipeline de Ingenieria de Requisitos (LEL y Escenarios)

Esta skill orquesta la conversion de un documento de dominio en una linea de base de
requisitos trazable, aplicando el metodo LEL y Escenarios de Leite, Hadad, Kaplan y Doorn.

Vos, el agente principal, sos el orquestador: ejecutas el script de extraccion y delegas
cada etapa al subagente correspondiente con la herramienta Task. Cada subagente lee y
escribe archivos; vos encadenas las etapas y manejas la pausa con el stakeholder.

## Subagentes (en `.claude/agents/`)

| Orden | Subagente | Lee | Escribe |
|---|---|---|---|
| 1 | `requirements-intake` | texto del documento | `source-inventory.json`, `lel-candidates.json`, `supporting-context.json` |
| 2 | `lel-authoring` | los 3 archivos de intake | `lel.json`, `lel.md` |
| 3 | `lel-inspection` | `lel.json` | `lel-inspection.json`, `lel-inspection.md` |
| 4 | `stakeholder-questionnaire` | `lel.json`, `lel-inspection.json` | `stakeholder-questions.json`, `stakeholder-questions.md` |
| 5 | `scenario-modeling` | `lel.json`, `lel-inspection.json` | `scenarios.json`, `scenarios.md` |
| 6 | `requirements-specification` | `scenarios.json`, `lel.json` | `requirements.json`, `requirements.md` |
| 7 | `technical-design` | `requirements.json`, `supporting-context.json`, `lel.json`, mockups de UI (opcional) | `data-model.json`, `technical-design.json` (+ `.md`) |
| 8 | `design-inspection` | `data-model.json`, `technical-design.json`, `requirements.json` | `design-inspection.json`, `design-inspection.md` |

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
   Si responde no: crea el mismo archivo con `"opt_in": false`. En ambos casos
   no preguntes mas en futuras corridas.

2. **Existe con `opt_in: true`**: continua silenciosamente; al cierre vas a
   ofrecer experiments.

3. **Existe con `opt_in: false`**: continua silenciosamente; saltea el prompt
   de cierre.

No bloquees el flujo por esto: si el usuario no responde rapido o el archivo
no se puede leer, asume `opt_in: false` y segui.

### Paso 0 - Documento de entrada

Identifica la ruta del documento (Word, PDF, Markdown o texto). Si el usuario no la dio,
preguntala antes de seguir.

### Paso 1 - Extraer el texto

Crea `.dev/requirements/sources/` y extrae el texto con el script de esta skill. El script
vive en la subcarpeta `scripts/` de la skill; usa la variable `${CLAUDE_SKILL_DIR}`, que
apunta a la carpeta de la skill tanto si esta instalada como plugin como si esta suelta
en `.claude/skills/`:

```bash
python3 "${CLAUDE_SKILL_DIR}/scripts/extract_document.py" \
  "<ruta-del-documento>" ".dev/requirements/sources/<nombre>.txt"
```

Si `${CLAUDE_SKILL_DIR}` no estuviera definida, ubica `extract_document.py` dentro de la
carpeta `scripts/` de esta skill y ejecutalo igual.

Si el documento es PDF y el script informa que falta una biblioteca, instala una:
`pip install pypdf`. Para `.md` o `.txt` el script solo copia el texto.

### Paso 2 - Etapas 1 a 4 (intake -> LEL -> inspeccion -> preguntas)

Invoca, en orden y de a una, las etapas 1 a 4 con la herramienta Task, delegando al
subagente por su nombre. A cada subagente pasale: la ruta del archivo de texto extraido
(solo a `requirements-intake`) y la instruccion de leer sus entradas y escribir sus
salidas en `.dev/requirements/`. Espera a que cada subagente termine antes de lanzar el
siguiente: cada etapa consume el archivo de la anterior.

### Paso 3 - PAUSA OBLIGATORIA con el stakeholder

Cuando `stakeholder-questionnaire` termina, NO sigas automaticamente. Mostrale al usuario
el contenido de `.dev/requirements/stakeholder-questions.md` y pedile que lo responda o
que lo lleve al stakeholder.

- Si el usuario aporta respuestas: guardalas en `.dev/requirements/stakeholder-answers.md`
  (una respuesta por `QST-xxx`). Volve a invocar `lel-authoring` en modo actualizacion,
  indicandole que lea el `lel.json` previo, el `lel-inspection.json` y el
  `stakeholder-answers.md`, y que aplique TODAS las respuestas y TODOS los defectos
  confirmados. Despues volve a invocar `lel-inspection` sobre el LEL actualizado.
  Verifica el cierre del lazo: si la nueva inspeccion reporta referencias colgadas a
  preguntas resueltas o respuestas `QST-xxx` sin aplicar, volve a invocar `lel-authoring`
  con ese detalle hasta que el lazo cierre. Recien entonces segui.
- Si el usuario dice que no hay dudas o pide continuar: segui sin el lazo de respuestas.

Nunca inventes respuestas del stakeholder.

### Paso 4 - Etapas 5 a 8 (escenarios -> requisitos -> diseno -> inspeccion de diseno)

Invoca, en orden y de a una: `scenario-modeling` y luego `requirements-specification`,
sobre la ultima version de `lel.json`.

Antes de invocar `technical-design`, PREGUNTALE al usuario si tiene assets de diseno de
UI para usar en las pantallas: mockups HTML, wireframes, hojas de estilo CSS o capturas.
Pueden estar en cualquier carpeta; lo mas probable es que esten junto al documento de
entrada o en una subcarpeta.

- Si el usuario indica una ubicacion: pasasela a `technical-design` para que tome esos
  mockups como diseno autoritativo de las pantallas.
- Si el usuario dice que no hay: invoca `technical-design` igual, sin assets de UI; las
  pantallas se proponen de forma abstracta.

`technical-design` lee `requirements.json`, `supporting-context.json`, `lel.json` y, si
los hay, los assets de UI; reconecta el contexto de soporte que el intake habia separado
para esta etapa.

Cuando `technical-design` termina, invoca `design-inspection` sobre `data-model.json` y
`technical-design.json`. Es el segundo par de ojos del diseno: revisa la estructura del
modelo de datos y, cuando el stack es relacional, la normalizacion en formas normales.

- Si la inspeccion devuelve `passed: true`, el diseno cierra.
- Si reporta defectos `high` o `medium`, volve a invocar `technical-design` en modo
  correccion, indicandole que lea `design-inspection.json` y aplique las correcciones
  propuestas. Despues volve a invocar `design-inspection`. Repeti hasta que el diseno
  pase o solo queden defectos `low`.

### Paso 5 - Cierre

Informa al usuario los archivos generados en `.dev/requirements/` y resalta el conteo de
simbolos del LEL, defectos del LEL y del diseno, escenarios, requisitos, entidades del
modelo de datos y decisiones de diseno, mas las preguntas abiertas que siguen bloqueando.

### Paso 5b - Registro en .dev/.experiments.json + prompt opcional de experiments

Despues del cierre normal, actualiza `.dev/.experiments.json` agregando una
entrada a `runs[]`:

```json
{
  "plugin": "requirements-pipeline",
  "ran_at": "<iso8601>",
  "outputs_path": ".dev/requirements/",
  "baseline_ref": null,
  "notes": "<resumen 1 linea: counts del LEL/escenarios/requisitos y defectos>"
}
```

Despues:
- Si `opt_in: true`: mostrale al usuario este texto explicativo y la pregunta
  > "El plugin `experiments` puede medir esta corrida (cobertura de
  > requisitos, refs colgadas, tamano del output, tiempo) y compararla
  > contra una baseline para detectar drift o sugerir mejoras al plugin.
  > **¿Correr `/exp-bench requirements-pipeline` ahora? (s/n, default n)**"
  >
  > "Si decis si: se genera `.dev/experiments/requirements-pipeline/bench-<fecha>.md`
  > con metricas + observaciones, sin tocar tu output. Si decis no, queda
  > para despues; podes correrlo en cualquier momento."

  Si responde si: dispara `/exp-bench requirements-pipeline` (asume que el
  plugin existe; si no, avisar al usuario que no esta instalado).
  Si responde no o no responde: cierra.

- Si `opt_in: false`: cierra sin preguntar nada.

## Reglas de orquestacion

- El pipeline es estrictamente secuencial: no lances una etapa sin el archivo de entrada
  de la anterior.
- La pausa del Paso 3 nunca se saltea.
- Ningun paso debe inventar vocabulario: los escenarios usan simbolos del LEL y los
  requisitos trazan a escenarios.
- Si un subagente falla o produce un archivo vacio, detene el pipeline e informa al
  usuario en vez de continuar con datos incompletos.
- Despues de cada etapa, valida que el archivo de salida sea JSON valido y que los ids
  que referencia (simbolos, escenarios, episodios, requisitos) existan. Si hay
  referencias colgadas o el subagente se salteo un paso, volve a invocarlo con el
  detalle del problema antes de continuar.

## Estructura `.dev/requirements/` resultante

```
.dev/requirements/
  sources/                      texto extraido del documento (entrada)
  source-inventory.json         inventario de secciones
  lel-candidates.json           candidatos a simbolos del LEL
  supporting-context.json       contexto de soporte
  lel.json / lel.md             Lexico Extendido del Lenguaje
  lel-inspection.json / .md     checklist de defectos del LEL
  stakeholder-questions.json/.md cuestionario para el stakeholder
  stakeholder-answers.md        respuestas del stakeholder (si las hubo)
  scenarios.json / scenarios.md Escenarios trazables al LEL
  requirements.json / .md       requisitos funcionales y no funcionales
  data-model.json / .md         modelo de datos (entidades y relaciones)
  technical-design.json / .md   arquitectura, API, pantallas y decisiones (ADRs)
  design-inspection.json / .md  inspeccion del diseno y normalizacion
```
