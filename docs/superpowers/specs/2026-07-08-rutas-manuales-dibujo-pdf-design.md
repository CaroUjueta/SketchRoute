# Spec: Rutas manuales, dibujo mejorado y PDF profesional

**Fecha:** 2026-07-08 · **Alcance:** editor de planos (`static/js/canvas.js`, `templates/plans/editor.html`, `static/css/editor.css`). Sin backend ni migraciones: todo vive en `Plan.canvas_data` (Fabric JSON). M4 (vectorización) queda para un spec aparte.

## Contexto
El usuario apaga la generación automática de rutas (A*) porque prefiere control manual, pero la única herramienta manual actual son flechas sueltas de 72px arrastradas del sidebar. Además dibujar paredes exige un drag por pared, los extremos no se pueden editar, las puertas colocadas se mueven libres (se salen de la pared) y el PDF tiene detalles de calidad.

## M1 — Rutas manuales + apagar auto

### Apagar generación automática
- En `editor.html`, sección "4 · Rutas automáticas": ocultar (comentar/quitar) los botones **Generar ruta de evacuación**, **Generar ruta sanitaria** y **Colocar origen de evacuación**. La sección pasa a llamarse **"4 · Rutas"** y contiene la nueva herramienta + "Limpiar rutas" + "Generar leyenda y cartela".
- El código del generador (`generate`, `astar`, `buildGrid`, …) **queda intacto** y `generateEvac/generateSan` siguen exportados — reactivar = restaurar los botones.
- `clearAll` pasa a borrar también `ruta-manual`? **No**: se agrega confirmación implícita — "Limpiar rutas" borra `ruta-auto` (legacy) **y** `ruta-manual` porque ya no habrá auto; el texto del botón dice "Borrar todas las flechas". (Decisión: sin las auto, "limpiar" solo tendría sentido sobre las manuales.)

### Herramienta "Ruta" (tres gestos en una)
- Cuatro botones en la sección 4, uno por tipo: Evacuación `#16a34a`, Ordinaria `#111827`, Reciclable `#9ca3af`, Biosanitaria `#dc2626`. Cada uno activa `setTool('ruta', tipo)`.
- **Gesto A — polilínea por clics:** cada clic agrega un vértice; preview punteado del tramo en curso siguiendo el cursor con enderezado a 90° (snap al eje dominante). Doble clic / Enter / Esc finaliza (Esc también finaliza, no cancela, si ya hay ≥2 vértices; con <2 cancela).
- **Gesto B — mano alzada:** mousedown + arrastre traza libre; al soltar, el trazo se simplifica (Douglas-Peucker sencillo o el `simplify` existente sobre puntos densos) y se **ortogonaliza** a tramos H/V.
- Detección de gesto: si entre mousedown y mouseup el mouse se movió > 12px ⇒ mano alzada; si no ⇒ clic de polilínea.
- **Render final:** reusar `makeRouteSafe(points, color, modeKey)` (ya dibuja tramos con margen de esquina y punta por tramo, idéntico al generador) pero etiquetando `srCat:'ruta-manual'` y `selectable:true`. Los objetos resultantes se agrupan en un solo `fabric.Group` por ruta para moverla/borrarla como unidad (`srType:'ruta-evac'|'ruta-san'`, `srCat:'ruta-manual'`).
- Reclasificación: el toggle de 4 colores del `#propBar` (`setArrowKind`) debe recorrer los hijos del grupo (hoy recolorea un Path suelto).
- Las **flechitas arrastrables del sidebar quedan igual** (retoque puntual).

## M2 — Dibujo del plano

### Paredes encadenadas
- Herramienta Pared pasa a modo clic-clic: primer clic fija inicio, cada clic siguiente crea una pared desde el punto anterior (con `snapPoint`/`orthoSnap`/cap cuadrado/anclaje a centro actuales) y continúa la cadena. Esc o doble clic corta la cadena. El drag actual sigue funcionando (mousedown+move+up crea una pared y deja la cadena lista para continuar desde su fin).

### Editar extremos de paredes
- Al seleccionar una `pared`/`mueble` (Line), reemplazar los controles estándar por **dos manijas en los extremos** (custom controls de Fabric sobre x1/y1 y x2/y2). Arrastrar una manija mueve ese extremo con snap a extremos de otras paredes (reusar `collectEndpoints`/`snapPoint`). Al terminar, `pushHistory`.

### Puertas esclavas de su pared
- En `object:moving` de una `puerta`/`vano`: proyectar su centro sobre la pared más cercana (`wallAt`, ya existe) y fijar la coordenada perpendicular para que solo se deslice a lo largo; si no hay pared a <30px, se mueve libre (para poder llevarla a otra pared).

## M3 — PDF profesional
- `renderPNG`: `multiplier: 3` (hoy 2).
- Antes de rasterizar, si la leyenda o cartela quedan fuera del bbox de contenido + margen, moverlas dentro (esquina inferior más cercana) y restaurar después.
- Nombre de archivo: `RUTA_<MODOS>_<PLAN>_<yyyy-mm-dd>.pdf` (ej. `RUTA_EVACUACION_SEDE-PRINCIPAL_2026-07-08.pdf`).
- El marco temporal existente (`renderPNG`) se conserva.

## No-objetivos
- No se toca el pipeline de vectorización (M4, spec aparte).
- No se borra el código A*.
- No hay cambios de modelo/BD.

## Verificación (Playwright, patrón smoke*.py, usuario de prueba + plan nuevo)
1. La sección Rutas ya no muestra botones de generar; "Borrar todas las flechas" elimina rutas manuales.
2. Ruta por clics: 3 clics + Enter → polilínea 90° con puntas, color correcto; seleccionable y movible como grupo; reclasificar con propBar recolorea todo el grupo; sobrevive recarga.
3. Ruta a mano alzada: trazo curvo → tramos rectos H/V con puntas.
4. Paredes encadenadas: 4 clics forman 3 paredes conectadas con esquinas perfectas; Esc corta.
5. Extremos: seleccionar pared, arrastrar manija de extremo hasta el extremo de otra → snap y unión exacta.
6. Puerta colocada se desliza solo a lo largo de su pared; alejándola >30px se libera.
7. Export PDF: descarga con nombre nuevo, leyenda visible dentro de la página, nitidez 3×.
