# Pipeline: Ingenieria de Requisitos (iterativo)

Pipeline que transforma material de dominio en una linea de base de requisitos
trazable, aplicando el metodo LEL y Escenarios de Leite, Hadad, Kaplan y Doorn — de
forma **iterativa e incremental**: la linea de base evoluciona por rebanadas, en vez de
cerrarse en una unica pasada en cascada.

El principio: **amplitud temprana y barata, profundidad recien cuando hace falta.**
Primero se descubre el mapa completo del producto (features y escenarios stub); despues
se elaboran y baselinean solo las features elegidas, incremento por incremento; el
material nuevo que llega despues entra al mismo circuito sin romper lo construido.

---

## Los cuatro modos

```
                    /requerimientos:descubrir [docs|carpetas|nada]
                    (re-ejecutable cada vez que llega material)
documentos ----+
carpetas ------+--> extraccion -> [requirements-intake] x N fuentes (paralelo, deltas)
vision sin doc-+        -> apply_delta.py -> [lel-authoring]
                        -> validate_baseline.py --solo lel (hasta verde)
                        -> en paralelo: [lel-inspection] (juicio) -> [stakeholder-questionnaire]
                                        [product-mapping]
                              (modo elicitacion: sin documento = entrevista completa)
                        -> PAUSA con el stakeholder -> respuestas = nueva fuente
                        -> [lel-authoring] (update, sonnet) -> reinspeccion focused
                        -> check_closure.py
                                |
                                v
                .dev/requirements/product-map.json
                (features FG-xx y escenarios stub SCN-xx, priorizados;
                 solapamientos con lo baselineado = propuestas, NO se aplican)
                                |
                                |   /requerimientos:incremento FG-01 FG-02 ...
                                v
                slice_increment_context.py (una tajada por feature + indice)
                [scenario-modeling] x N features (paralelo, deltas) -> apply_delta.py
                [requirements-specification] x N features (paralelo, deltas) -> apply_delta.py
                        -> PAUSA DE CONFIRMACION si algo baselineado cambiaria
                render_baseline_docs.py (ANTES de inspeccionar)
                en paralelo: validate_baseline.py --solo requirements (hasta verde)
                               -> [requirements-inspection] (juicio, full/focused, tope 3)
                             consulta de mockups de UI -> [technical-design] (incremental)
                validate_baseline.py --solo design -> [design-inspection] (juicio) -> lazo
                check_closure.py --inspecciones requirements design
                                |
                                v
                features marcadas `baselined` + entrada INC-xxx en changelog.json
                -> listas para /planificar (o re-planificar si ya hay plan)

                    /requerimientos:cambio <descripcion-o-doc>
                (cambios puntuales sobre lo baselineado: veredictos
                 new/modified/deprecated/already_covered -> PAUSA DE
                 CONFIRMACION -> aplicar -> inspecciones -> CR-xxx)

                    /requerimientos <docs>
                (modo completo clasico: descubrir + un incremento con todas
                 las features; util para proyectos chicos)
```

---

## Agentes del pipeline

| Agente | Rol | Participa en | Definicion |
|---|---|---|---|
| `requirements-intake` | Clasifica el material (multi-fuente, incremental) en inventario, candidatos LEL y contexto | descubrir, cambio | `agents/requirements-intake.md` |
| `lel-authoring` | Construye o actualiza el Lexico Extendido del Lenguaje | descubrir, cambio | `agents/lel-authoring.md` |
| `lel-inspection` | Inspecciona el LEL y produce el checklist de defectos | descubrir, cambio | `agents/lel-inspection.md` |
| `stakeholder-questionnaire` | Preguntas al stakeholder; en elicitacion entrevista el dominio | descubrir, cambio | `agents/stakeholder-questionnaire.md` |
| `product-mapping` | Mapa del producto: features y escenarios stub priorizados, con estados | descubrir | `agents/product-mapping.md` |
| `scenario-modeling` | Elabora en profundidad los escenarios de las features del incremento | incremento | `agents/scenario-modeling.md` |
| `requirements-specification` | Especifica los requisitos de las features del incremento | incremento, cambio | `agents/requirements-specification.md` |
| `requirements-inspection` | Audita la especificacion (cobertura de lo elaborado, trazabilidad, campos para planificar, coherencia entre features) | incremento, cambio | `agents/requirements-inspection.md` |
| `technical-design` | Extiende el modelo de datos y el diseno con lo que el incremento necesita | incremento, cambio | `agents/technical-design.md` |
| `design-inspection` | Inspecciona el diseno y la normalizacion del modelo de datos | incremento, cambio | `agents/design-inspection.md` |

La orquestacion vive en la skill `skills/requirements-pipeline/SKILL.md` del plugin.

---

## Reglas de orquestacion

### Estados y baseline
- Las features y escenarios del mapa tienen estado:
  `stub -> elaborated -> baselined` (o `deprecated`).
- El pipeline de planificacion consume lo `baselined`.
- **Nada baselineado cambia sin confirmacion explicita del usuario.** Las
  modificaciones propuestas (por material nuevo o por un CR) se presentan con su
  antes/despues y esperan el OK, una por una.

### Ids estables y auditoria
- Los ids `FG-xx` y `SCN-xx` nacen en el product-map y nunca se renumeran. Los demas
  ids continuan sus secuencias. Nada se borra: lo eliminado se deprecia.
- Toda corrida queda registrada en `changelog.json`: `DSC-xxx` (descubrimientos),
  `INC-xxx` (incrementos), `CR-xxx` (cambios), `REC-xxx` (recuperaciones desde
  codigo, las escribe `recovery-pipeline`), con veredictos
  (`new|modified|deprecated|already_covered`), confirmaciones del usuario y versiones
  antes/despues de cada artefacto.
- La cadena de trazabilidad se conserva en ambas direcciones: requisito -> escenario ->
  simbolo del LEL -> seccion de la fuente (documento, entrevista o CR); y corrida ->
  que produjo (via changelog).

### Pausas - NUNCA saltear
- Despues de `stakeholder-questionnaire`: SIEMPRE presentar las preguntas y esperar
  respuestas explicitas. Sin documento de entrada, el cuestionario es mas largo (las
  respuestas son la fuente). PROHIBIDO inventar respuestas.
- Antes de aplicar cualquier `modified`/`deprecated` sobre lo baselineado: SIEMPRE
  mostrar el antes/despues y esperar la confirmacion del usuario.

### Inspecciones en dos mitades y lazos de correccion
- Primero el script `validate_baseline.py` (checks mecanicos, itera hasta verde, no
  consume pasadas); despues el subagente inspector en modo juicio (`full` la primera
  vez, `focused` en las re-pasadas). Los `.md` se renderizan por script ANTES de
  inspeccionar.
- Los defectos `high`/`medium` rebotan al agente que corresponda en modo correccion
  (invocado con el modelo de la columna `Correccion` de la tabla de la skill: opus
  para los agentes de contenido, por el benchmark SIGEC), con tope de 3 pasadas de
  juicio: los remanentes los decide el usuario, no el lazo. Distinto del modo
  *actualizacion* (aplicar respuestas del stakeholder o propuestas ya confirmadas),
  que es transcripcion guiada y va en `sonnet`.

### Paralelismo y deltas
- Intake por fuente, escenarios y requisitos por feature: agentes en paralelo que
  escriben `*.delta.json` con ids provisionales (`SCN-FG03#1`); `apply_delta.py`
  renumera, mergea, recalcula `summary` y sube `version` una vez. Cada agente lee solo
  su tajada (`slice_increment_context.py`), nunca la linea de base completa.
- Etapas independientes se lanzan juntas: mapa del producto con el cuestionario;
  diseno tecnico con el lazo de requisitos.

### Cierre por script
- `check_closure.py` bloquea el cierre si quedan deltas o carpetas temporales,
  archivos fuera del layout, inspecciones en rojo o viejas, contadores de `version`
  que retrocedieron, vistas `.md` desincronizadas o defectos high/medium de
  `validate_baseline.py` (coherencia artefacto <-> artefacto, p. ej. version refs
  viejos despues de un CR).

### Versionado
- Toda reescritura de un artefacto incrementa su `version`; los `*_version_ref` citan
  la `version` del archivo referenciado; el changelog registra antes/despues por
  corrida. El pipeline de planificacion detecta por el changelog que incrementos aun
  no absorbio.

---

## Como iniciar

```
/requerimientos:descubrir docs/vision.docx docs/anexos/     (archivos y carpetas)
/requerimientos:descubrir                                   (sin documento: entrevista)
/requerimientos:incremento FG-01 FG-02                      (elaborar y baselinear)
/requerimientos:cambio "el login ahora requiere 2FA"        (cambio puntual)
/requerimientos docs/especificacion.docx                    (modo completo clasico)
```

O en lenguaje natural: la skill se activa sola ("genera los requisitos a partir de
estos documentos", "agrega este documento nuevo", "elabora la feature de facturacion").

---

## Estructura del plugin y salidas

```
requirements-pipeline/           (el plugin; se instala una vez)
  agents/         los 10 subagentes del pipeline
  skills/
    requirements-pipeline/   skill de orquestacion + scripts deterministas (extraccion,
                             version, tajadas, deltas, validacion, render, cierre)
  commands/
    requerimientos.md        modo completo (clasico)
    descubrir.md             modo descubrir
    incremento.md            modo incremento
    cambio.md                modo cambio

.dev/                            (en cada proyecto)
  requirements/   <- salidas: ver SKILL.md (incluye product-map.json y changelog.json)
```
