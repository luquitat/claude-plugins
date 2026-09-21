# Requirements Pipeline — Plugin de Claude Code

Plugin que convierte material de dominio en una linea de base de requisitos trazable,
aplicando el metodo **LEL y Escenarios** de Leite, Hadad, Kaplan y Doorn — de forma
**iterativa e incremental**: descubris el mapa del producto, elaboras las features por
incrementos, y absorbes material nuevo en cualquier momento sin romper lo construido.

Acepta como entrada documentos (`.docx`, `.pdf`, `.md`, `.txt`), carpetas enteras, o
**ningun documento** (arrancas de una vision conversada y una entrevista de
elicitacion).

## Que tenes que poner en tu proyecto

**Nada.** El plugin se instala una vez y queda disponible en todos tus proyectos. Lo
unico que aparece en cada proyecto son las **salidas**, en `.dev/requirements/`.

## Los cuatro comandos

| Comando | Para que | Cuando |
|---|---|---|
| `/requerimientos:descubrir [rutas]` | Pasada panoramica: LEL + mapa del producto (features y escenarios stub priorizados) | Al arrancar, y cada vez que llega material nuevo |
| `/requerimientos:incremento <FG-xx ...>` | Elabora y baselinea las features elegidas: escenarios, requisitos, inspeccion, diseno | Cuando decidis que construir a continuacion |
| `/requerimientos:cambio <descripcion-o-doc>` | Cambio puntual sobre lo baselineado, con veredictos y confirmacion previa | Un pedido del stakeholder, un mail, un ajuste |
| `/requerimientos <rutas>` | Modo completo clasico: descubrir + un incremento con todo | Proyectos chicos o documentos cerrados |

## Como se usa: la vida de un proyecto

**Momento 0 — arrancas con los documentos del MVP (uno, varios o una carpeta):**

```
/requerimientos:descubrir docs/vision.docx docs/anexos/
/requerimientos:incremento FG-01 FG-02 FG-05      (las features del MVP)
/planificar                                        (plugin planning-pipeline)
```

El descubrimiento construye el LEL y el **mapa del producto**: todas las features
candidatas con sus escenarios en `stub` (titulo, objetivo, actores — sin profundidad),
priorizadas. Marcas cuales son el MVP, las elaboras con un incremento, y el planning
arma los lotes para que los agentes de build arranquen. El resto del mapa queda en
stub: registrado y trazable, sin esfuerzo gastado.

**Momento 0 (variante) — no tenes ningun documento:**

```
/requerimientos:descubrir
```

Contas la vision (que problema resuelve, para quien) y el pipeline te entrevista: el
cuestionario de elicitacion va a ser **mas largo** de lo habitual — es esperable,
porque tus respuestas son la fuente del dominio. Las respuestas quedan archivadas en
`sources/` con la misma trazabilidad que un documento.

**Momento 1 — el MVP se esta construyendo y llega material nuevo:**

```
/requerimientos:descubrir docs/facturacion.docx
/requerimientos:incremento FG-09
```

Re-ejecutar el descubrimiento es siempre seguro: agrega features nuevas al mapa,
enriquece el LEL, y si el documento se solapa con algo ya baselineado **no lo aplica**:
lo deja como propuesta y te la muestra. Despues elaboras lo nuevo cuando decidas, y el
planning lo integra al plan sin frenar lo que esta en construccion.

**Momento 2 — el MVP no termino y siguen llegando documentos o pedidos:**

Mismo circuito, sin restricciones: el pipeline nunca exige que algo termine para
aceptar material nuevo. Las modificaciones a lo baselineado siempre pasan por tu
confirmacion (antes/despues, una por una), lo deprecado nunca se borra, y el
`changelog.json` ordena la historia: cada corrida (`DSC`/`INC`/`CR`) registra que
agrego, que modifico, que ya estaba cubierto y que versiones quedaron.

## Estructura del plugin

```
requirements-pipeline/
  .claude-plugin/
    plugin.json                  manifiesto del plugin
  agents/                        los 10 subagentes del pipeline
    requirements-intake.md       clasifica el material (multi-fuente, incremental)
    lel-authoring.md             construye/actualiza el LEL
    lel-inspection.md            checklist de defectos del LEL
    stakeholder-questionnaire.md preguntas + entrevista de elicitacion
    product-mapping.md           mapa del producto (features y stubs)
    scenario-modeling.md         elabora escenarios por incremento
    requirements-specification.md especifica requisitos por incremento
    requirements-inspection.md   inspeccion de los requisitos
    technical-design.md          modelo de datos y diseno (incremental)
    design-inspection.md         inspeccion del diseno y normalizacion
  skills/
    requirements-pipeline/
      SKILL.md                   orquestacion de los 4 modos
      scripts/                   deterministas, solo stdlib, cero tokens
        check_pipeline_version.py version cargada y avisos de desfase (transversal a la suite)
        extract_document.py      extrae texto de .docx / .pdf / .md / .txt
        slice_increment_context.py una tajada de contexto por feature (+ indice compacto)
        apply_delta.py           merge de deltas paralelos, renumeracion de ids, summary
        validate_baseline.py     checks mecanicos de LEL / requisitos / diseno
        render_baseline_docs.py  todos los .md derivados (artefactos, inspecciones, cuestionario)
        check_closure.py         compuerta de cierre (layout, inspecciones, versiones, vistas, baseline)
        render_index.py          indice .dev/README.md
  commands/
    requerimientos.md            modo completo (clasico)
    descubrir.md                 modo descubrir
    incremento.md                modo incremento
    cambio.md                    modo cambio
  PIPELINE.md                    diagrama y reglas del flujo
  README.md                      este archivo
```

## Como gasta tokens (y como no)

El orquestador no carga artefactos de contenido en su contexto: los scripts hacen lo
mecanico y los subagentes leen **tajadas** por feature, no la linea de base entera.

- **Inspecciones en dos mitades**: `validate_baseline.py` corre los checks de
  integridad (ids, enums, ciclos, cobertura, version refs, sincronia de vistas) en
  milisegundos e itera hasta verde; recien entonces el subagente inspector corre en
  **modo juicio** sobre lo que un script no puede evaluar. Las re-pasadas son
  `focused`: solo los ids corregidos.
- **Paralelismo por feature**: escenarios y requisitos se elaboran con un agente por
  feature al mismo tiempo, cada uno con su tajada (`slice_increment_context.py`) y
  escribiendo un delta con ids provisionales; `apply_delta.py` mergea, renumera y
  recalcula. El intake tambien corre en paralelo por fuente.
- **Etapas independientes en paralelo**: el mapa del producto no espera al
  cuestionario; el diseno tecnico no espera al lazo de inspeccion de requisitos.
- **Modelo por modo**: generacion en opus donde hay juicio (LEL inicial, escenarios,
  requisitos, diseno, y el mapa del producto); correccion y actualizacion en sonnet;
  inspeccion del LEL en haiku sobre los restos que deja el script.
- **Vistas `.md` por script**, incluidas inspecciones y cuestionario, y siempre
  **antes** de inspeccionar (asi la sincronia nunca sale en rojo por orden).
- **Cierre por exit code**: `check_closure.py` verifica layout cerrado, inspecciones
  en verde y vigentes, versiones que solo crecen, vistas sincronizadas y
  `validate_baseline.py` completo en verde.

## Instalacion

Este plugin se distribuye en el marketplace `lpadularrosa-dev-plugins`. Con el
marketplace agregado:

```bash
claude plugin install requerimientos@lpadularrosa-dev-plugins
```

Por defecto queda disponible en todos los proyectos. Los comandos exactos del CLI
pueden variar segun la version de Claude Code: verificalos con `/plugin`.

## Requisitos

- **Claude Code** con soporte de plugins, subagentes y skills.
- **Python 3.8+** para el script de extraccion.
- Para leer **PDF**: `pip install pypdf` (o `pdfminer.six`). Word (`.docx`), Markdown y
  texto plano no necesitan dependencias.

## Garantias de auditoria

- **Ids estables**: `FG-xx` y `SCN-xx` nacen en el mapa y nunca se renumeran; nada se
  borra, lo eliminado se deprecia.
- **Trazabilidad bidireccional**: requisito -> escenario -> simbolo del LEL -> seccion
  de la fuente (documento, entrevista o CR); y al reves, cada corrida del changelog
  dice que produjo.
- **Nada baselineado cambia sin tu confirmacion.**
- **Versionado**: cada artefacto incrementa su `version` al reescribirse; el pipeline
  de planificacion (`planning-pipeline`) detecta por el changelog que incrementos aun
  no absorbio.

## Salidas (en `.dev/requirements/` del proyecto)

| Archivo | Contenido |
|---|---|
| `sources/` | Toda fuente archivada: documentos extraidos, vision, entrevistas, CRs |
| `source-inventory.json` | Inventario de secciones (acumulativo, multi-fuente) |
| `lel-candidates.json` | Candidatos a simbolos del LEL |
| `supporting-context.json` | Contexto de soporte (modelo de datos, API, UI, stack) |
| `lel.json` / `lel.md` | Lexico Extendido del Lenguaje (vivo) |
| `lel-inspection.json` / `.md` | Checklist de defectos del LEL |
| `stakeholder-questions.json` / `.md` | Cuestionario (defectos + elicitacion + checklist de no funcionales con supuestos por defecto) |
| `stakeholder-answers.md` | Respuestas del stakeholder (una por QST-xxx), tambien archivadas en `sources/` |
| `product-map.json` / `.md` | Mapa del producto: features y stubs con estado, prioridad y valor de negocio |
| `changelog.json` | Historia: DSC / INC / CR / REC con veredictos y versiones |
| `scenarios.json` / `scenarios.md` | Escenarios elaborados (acumulativo) |
| `requirements.json` / `requirements.md` | Requisitos funcionales y no funcionales + reglas de negocio `BR-xxx` (acumulativo) |
| `requirements-inspection.json` / `.md` | Inspeccion de los requisitos |
| `data-model.json` / `data-model.md` | Modelo de datos: entidades, campos y relaciones |
| `technical-design.json` / `technical-design.md` | Arquitectura, API, pantallas y decisiones (ADRs) |
| `design-inspection.json` / `design-inspection.md` | Inspeccion del diseno y normalizacion |

Ver `PIPELINE.md` para el diagrama completo y las reglas de orquestacion.
