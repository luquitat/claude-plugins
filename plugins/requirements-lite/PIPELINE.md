# Pipeline: Requirements Lite (sketch)

Pipeline liviano para producir una linea de base de requisitos compatible con
`planning-pipeline`, **sin LEL, sin escenarios, sin inspecciones automaticas**.
Pensado para MVPs, proyectos chicos, refresh de existentes y encargos con
scope acotado.

---

## Flujo

```
modo documento:                       modo conversacional:
.docx / .pdf / .md                    usuario responde 5-8 preguntas en chat
        |                                     |
        v  [extract_document.py]              |
.dev/requirements/sources/{doc}.txt           |
        \____________   __________/
                     \ /
                      v  [brief-intake]
.dev/requirements/brief.json + .md
                      |
                      v  [requirements-sketch]
.dev/requirements/requirements.json + .md   (formato compat planning-pipeline)
                      |
                      v  [design-sketch]   (+ mockups opcionales)
.dev/requirements/data-model.json + .md
.dev/requirements/technical-design.json + .md

        PAUSA OPCIONAL AL FINAL
             -> consolidar open_questions de los 4 artefactos
             -> mostrar .dev/requirements/open-questions.md
             -> opcion A: responder dudas (re-run selectivo)
             -> opcion B: continuar con asunciones
             -> opcion C: iterar mas tarde
        <- FIN
```

---

## Agentes del pipeline

| Agente | Rol | Dispatch | Definicion |
|---|---|---|---|
| `brief-intake` | Captura vision, actores, scope, restricciones, glosario, capacidades y dudas en un brief compacto | Secuencial | `agents/brief-intake.md` |
| `requirements-sketch` | Deriva RF/RNF y feature_groups desde el brief, con formato compat planning-pipeline | Secuencial | `agents/requirements-sketch.md` |
| `design-sketch` | Produce modelo de datos + diseno tecnico (modulos, API, pantallas, ADRs) sin inspeccion | Secuencial | `agents/design-sketch.md` |

La orquestacion vive en `skills/requirements-lite/SKILL.md`.

---

## Reglas de orquestacion

### Dispatch secuencial
- Cada etapa consume el archivo que produjo la anterior. No hay paralelismo.
- No invocar una etapa si falta el archivo de entrada que necesita.

### Sin pausa intermedia
- A diferencia del pipeline pesado, no hay pausa obligatoria con stakeholder
  despues del brief. Las dudas se acumulan en `open_questions[]` dentro de cada
  artefacto.

### Consulta de mockups de UI - antes del diseno
- Antes de invocar `design-sketch`, el orquestador SIEMPRE le pregunta al
  usuario si tiene mockups, wireframes, CSS o capturas.
- Si los hay, `design-sketch` los toma como diseno autoritativo de las
  pantallas. Si no, propone pantallas abstractas.

### Pausa opcional al final
- Al cierre, el orquestador consolida los `open_questions[]` de los 4
  artefactos (brief + requirements + data-model + technical-design) en
  `open-questions.md`.
- Le ofrece al usuario: responder (con re-run selectivo), continuar con
  asunciones, o iterar mas tarde.

### Re-run selectivo
- Si el usuario responde dudas que afectan **el brief** (vision, scope,
  actores, capacidades): re-corre los 3 agentes en cadena.
- Si afectan solo **requirements** (RF/RNF, acceptance criteria): re-corre
  `requirements-sketch` → `design-sketch`.
- Si afectan solo **diseno** (entidad, modulo, ADR, pantalla, API): re-corre
  solo `design-sketch`.

### Sin inspecciones automaticas
- No hay agente equivalente a `lel-inspection` o `design-inspection`. La
  revision del modelo de datos (normalizacion, completitud) es visual, a cargo
  del usuario.
- Si el usuario necesita garantia de normalizacion en 3FN o auditoria
  lingüistica, debe usar el pipeline pesado (`requirements-pipeline`).

### Trazabilidad
- Cada RF cita `source_capability_ids[]` del brief.
- Cada entidad/modulo/ADR cita `requirement_ids[]` de `requirements.json`.
- No hay trazabilidad a escenarios/episodios/simbolos LEL (esos artefactos no
  existen en el pipeline liviano).

---

## Como iniciar el pipeline

Con el slash command:

```
/req-lite ruta/al/documento.docx    # modo documento
/req-lite                            # modo conversacional
```

O en lenguaje natural (la skill se activa sola):

```
"Genera los requisitos en modo liviano a partir de: ruta/al/documento.pdf"
"Necesito hacer un sketch rapido de requisitos para un MVP"
```

El agente principal:
1. Extrae el texto del documento si lo hay; si no, hace una entrevista corta.
2. Encadena `brief-intake` → `requirements-sketch` → `design-sketch`.
3. Pregunta si hay mockups de UI antes del diseno.
4. Consolida dudas al final en `open-questions.md`.
5. Lista los archivos generados.

---

## Cuando NO usar este pipeline

Usa el pipeline pesado (`/requerimientos`) si:
- Necesitas trazabilidad RF → escenario → episodio → simbolo LEL.
- El proyecto es regulado o tiene compliance estricto.
- Hay stakeholder externo que valida requisitos formalmente.
- Necesitas inspeccion automatica del LEL o del diseno (normalizacion 3FN).
- El equipo es grande (5+) y el vocabulario unificado del LEL paga su costo.

---

## Estructura esperada en cada proyecto

```
.claude/
  agents/         3 subagentes (si el plugin no esta instalado globalmente)
  skills/
    requirements-lite/   skill de orquestacion + script de extraccion
  commands/
    req-lite.md          slash command de entrada

.dev/
  requirements/   <- salidas generadas por el pipeline (mismo path que el pesado)
```

## Compatibilidad con planning-pipeline

Los archivos `requirements.json`, `data-model.json` y `technical-design.json`
emitidos por este pipeline tienen el **mismo shape** que los del pipeline
pesado. `planning-pipeline` los consume sin cambios. Lo unico que cambia es:

- El volumen (menos RF/RNF/entidades/ADRs).
- Algunos campos auxiliares (`source_scenario_ids`, `source_episode_ids`,
  `lel_symbol_ids`) quedan como arrays vacios — estan presentes para no romper
  consumidores que los chequean.
- `metadata.pipeline_variant: "lite"` permite identificar el origen.
