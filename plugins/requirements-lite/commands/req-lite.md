---
description: Pipeline liviano de requisitos. Convierte un documento o una sesion conversacional en requirements + data-model + technical-design compatibles con planning-pipeline, sin LEL ni escenarios.
argument-hint: [ruta-al-documento.docx|.pdf|.md]   (omitir para modo conversacional)
---

Genera la linea de base de requisitos en modo liviano: `$ARGUMENTS`

Segui la skill `requirements-lite` de punta a punta:

1. **Modo de entrada**:
   - Si `$ARGUMENTS` apunta a un documento (.docx, .pdf, .md): modo documento.
     Extrae el texto a `.dev/requirements/sources/` con el script de la skill.
   - Si `$ARGUMENTS` esta vacio: modo conversacional. Hace una entrevista corta
     al usuario (5-8 preguntas: que es el sistema, actores, scope, restricciones
     de stack/performance/seguridad, dudas conocidas) y guarda las respuestas
     para pasarselas a `brief-intake`.

2. Encadena los subagentes en orden: `brief-intake` → `requirements-sketch` →
   `design-sketch`.

3. Antes de `design-sketch`, preguntame si tengo mockups HTML/CSS/wireframes.
   Si los tengo, pasaselos como diseno autoritativo de las pantallas.

4. **Pausa opcional al final**: consolida `open_questions[]` de los 4
   artefactos en `.dev/requirements/open-questions.md`. Mostramelo y ofreceme:
   responder dudas (con re-run selectivo de etapas afectadas), continuar con
   asunciones, o iterar luego. Si dije "sin pausa" al arrancar, salta este paso
   pero igual escribi el `open-questions.md`.

5. Al cierre, lista los archivos generados en `.dev/requirements/` con el
   conteo de capacidades, feature_groups, RF, RNF, entidades, modulos, ADRs y
   open_questions. Mencioname que podes encadenar `/planificar` despues.

Si no especifique modo y no aporte documento, asume conversacional y arranca
la entrevista.
