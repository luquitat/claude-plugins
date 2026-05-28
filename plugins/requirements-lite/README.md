# Requirements Lite — Plugin de Claude Code

Plugin liviano para producir una linea de base de requisitos compacta y
compatible con `planning-pipeline`, **sin LEL ni escenarios**. Pensado para
proyectos donde el rigor formal del pipeline pesado no se justifica: MVPs,
prototipos, refresh de proyectos existentes y encargos con scope acotado
(2-8 semanas).

## Idea

El plugin pesado (`requirements-pipeline`) aplica el metodo LEL y Escenarios
de Leite, Hadad, Kaplan y Doorn: 8 etapas con inspecciones automaticas y
trazabilidad lingüistica completa. Es la herramienta correcta para sistemas
regulados, equipos grandes o cuando la auditabilidad es un entregable.

Pero para muchos proyectos, esa profundidad es overkill: pagas mucho costo
(tokens, tiempo, sesion con stakeholder) por una trazabilidad que no vas a
usar. Este plugin es la alternativa para esos casos:

- **3 etapas** en vez de 8 + 2 loops.
- **Sin pausa intermedia** con stakeholder; dudas consolidadas al final.
- **Sin LEL, sin escenarios, sin inspecciones automaticas.**
- **Output compatible con `planning-pipeline`** (mismo schema minimo).
- ~25-35% del costo en tokens del pipeline pesado.

## Que tenes que poner en tu proyecto

**Nada.** Igual que el pipeline pesado, el plugin se instala una vez y queda
disponible en todos tus proyectos. No copias carpetas `.claude/` a cada repo.

Las salidas se escriben en `.dev/requirements/` del proyecto (misma ruta que
el pipeline pesado, para que `planning-pipeline` las encuentre sin cambios).

## Estructura del plugin

```
requirements-lite/
  .claude-plugin/
    plugin.json                  manifiesto
  agents/                        3 subagentes
    brief-intake.md
    requirements-sketch.md
    design-sketch.md
  skills/
    requirements-lite/
      SKILL.md                   orquestacion
      scripts/
        extract_document.py      extrae texto de .docx / .pdf / .md / .txt
  commands/
    req-lite.md                  slash command de entrada
  PIPELINE.md                    diagrama y reglas
  README.md                      este archivo
```

## Instalacion

Este plugin se distribuye en el marketplace `lpadularrosa-dev-plugins`. Con
el marketplace agregado:

```bash
claude plugin install requirements-lite@lpadularrosa-dev-plugins
```

Por defecto el plugin queda disponible de forma global (en todos los
proyectos). Para acotarlo a un proyecto, instalalo con `--scope project`.
Despues de instalar, si hace falta, recarga con `/reload-plugins`.

## Requisitos

- **Claude Code** con soporte de plugins, subagentes y skills.
- **Python 3.8+** para el script de extraccion (solo si vas a usar modo
  documento).
- Para leer **PDF**: `pip install pypdf` (o `pdfminer.six`). Word (`.docx`),
  Markdown y texto plano no necesitan dependencias.

## Uso

En cualquier proyecto, con el plugin instalado:

```
/req-lite docs/especificacion.docx     # modo documento
/req-lite                               # modo conversacional
```

O en lenguaje natural (la skill se activa sola):

```
Genera los requisitos en modo liviano a partir de: docs/especificacion.pdf
Necesito hacer un sketch rapido de requisitos para un MVP
```

El pipeline corre las 3 etapas. Tiene dos puntos de interaccion:
- Una **consulta** sobre si hay mockups de UI antes del diseno.
- Una **pausa opcional al final** para consolidar dudas y permitir re-run
  selectivo si queres responderlas.

Todo se escribe en `.dev/requirements/` del proyecto.

## Etapas

```
documento o entrevista -> brief -> requirements -> data-model + technical-design
```

| # | Subagente | Produce |
|---|---|---|
| 1 | `brief-intake` | brief compacto (vision, actores, scope, restricciones, glosario, capacidades, dudas) |
| 2 | `requirements-sketch` | RF/RNF + feature_groups (compat planning-pipeline) |
| 3 | `design-sketch` | modelo de datos + stack, modulos, API, pantallas, ADRs minimal |

Ver `PIPELINE.md` para el diagrama completo y las reglas de orquestacion.

## Salidas (en `.dev/requirements/` del proyecto)

| Archivo | Contenido |
|---|---|
| `brief.json` / `brief.md` | Brief compacto del proyecto |
| `requirements.json` / `.md` | Requisitos funcionales y no funcionales con feature_groups |
| `data-model.json` / `.md` | Entidades y relaciones |
| `technical-design.json` / `.md` | Stack, modulos, contratos de API, pantallas y ADRs |
| `open-questions.md` | Consolidado de dudas de los 4 artefactos (al cierre) |
| `open-questions-answers.md` | Respuestas del usuario (si las hubo, dispara re-run) |

## Comparacion con `requirements-pipeline` (el pesado)

| Aspecto | Pesado | Lite (este) |
|---|---|---|
| Etapas | 8 + 2 loops | 3 |
| LEL formal | Si | No |
| Escenarios y episodios | Si | No |
| Inspeccion automatica del LEL | Si | No |
| Inspeccion de normalizacion 3FN | Si | No (revision visual) |
| Pausa con stakeholder | Obligatoria, en el medio | Opcional, al final |
| Trazabilidad | RF → escenario → episodio → simbolo LEL | RF → capability del brief |
| Volumen tipico | 50+ RF, 15+ RNF, 14+ features | 15-30 RF, 4-10 RNF, 5-10 features |
| Tokens (aprox) | 100% | 25-35% |
| Output → `planning-pipeline` | Si | Si (mismo schema) |

## Cuando NO usar este plugin

Cambia al pipeline pesado (`/requerimientos`) si:
- El proyecto es regulado, financiero, salud o tiene compliance estricto.
- Hay un stakeholder externo que valida requisitos como entregable.
- Necesitas trazabilidad RF → simbolo LEL para auditoria.
- El equipo es grande y necesita un vocabulario unificado (LEL).
- Queres normalizacion del modelo de datos verificada automaticamente.

## Encadenamiento con planning-pipeline

Cuando el pipeline lite termina, podes correr directo:

```
/planificar
```

`planning-pipeline` consume `requirements.json`, `data-model.json` y
`technical-design.json` con el mismo schema que produce el pipeline pesado.
La metadata `pipeline_variant: "lite"` en cada archivo permite identificar
el origen para futura auditoria.
