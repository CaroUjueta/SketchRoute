# SketchRoute — Generador de Planos de Evacuación y Rutas Sanitarias

> **Estado (2026-06-22):** Funcional de extremo a extremo — foto de croquis → vectorización (OpenCV) → editor web (Fabric.js) → rutas de evacuación/sanitarias → export PDF.
> **Cronograma:** 12 Jun — 30 Jul 2026 · **Entrega final:** 30 de Julio de 2026

---

## ¿Qué es SketchRoute?

SketchRoute convierte un **croquis dibujado a mano** (foto de una hoja) en un **plano de evacuación profesional**: detecta paredes, puertas y muebles, los vectoriza, y en el editor traza automáticamente las flechas de evacuación hacia la salida. Está pensado para brigadistas, ingenieros y cualquiera que necesite un plano de rutas sin usar CAD.

Hay **dos formas de trabajar**, y se combinan:

1. **Automática (foto → plano):** subes una foto del croquis y el pipeline de visión la vectoriza sola.
2. **Manual (editor):** dibujas o corriges paredes/puertas/muebles a mano en el editor del navegador.

En ambos casos, el editor genera las rutas y el PDF final.

---

## Cómo dibujar el croquis (colores)

> **Fuente de verdad:** los colores los define el pipeline en `apps/processing/services/preprocessing.py`. La misma leyenda se muestra en la web (pantalla de subida y editor).

| Elemento | Color a dibujar | Efecto en la ruta | Notas |
|---|---|---|---|
| **Paredes** | **Negro / lápiz** | Bloquea | Trazo continuo y recto |
| **Puertas** | **Azul** | Abre el paso | Es el único cruce válido de una pared |
| **Vanos / aberturas** | **Verde** | Abre el paso | Abertura básica sin arco |
| **Muebles / obstáculos** | **Rojo** | Bloquea | Contorno del mueble |

**Recomendaciones de foto:** papel cuadriculado o blanco, buena luz, sin sombras ni reflejos, encuadrando toda la hoja. El pipeline filtra la cuadrícula impresa por grosor de trazo, así que el cuaderno cuadriculado funciona bien.

---

## El pipeline de visión (servidor, OpenCV)

Todo el procesamiento de imagen vive en **`apps/processing/services/`** y lo orquesta `ProcessingPipeline.process()` (`pipeline.py`). Son **5 módulos**:

| Módulo | Rol |
|---|---|
| `preprocessing.py` | Carga, corrección de perspectiva, detección de la hoja, segmentación por color y reescalado al lienzo |
| `lines.py` | Detección y limpieza de líneas (Hough, fusión colineal, extensión, recorte, cierre de contorno, cortes de puertas…) |
| `rooms.py` | Detección de recintos a partir del grafo de muros (ciclos del grafo planar) |
| `fabric.py` | Conversión de segmentos a objetos Fabric.js + reencuadre para llenar la hoja |
| `pipeline.py` | Orquestador que encadena todo y devuelve el `canvas_data` |

### Etapas, en orden

1. **Perspectiva** (`correct_perspective`): endereza la hoja solo si el resultado es confiable (conservador, no destruye la imagen).
2. **Orientación de salida** (`_orient_exit_right`): rota el plano en múltiplos de 90° para que **la salida principal quede a la derecha**. La salida = la puerta con mayor `área × (1 + exterioridad)` — la más grande **y** más pegada al perímetro (la única forma de salir a la calle).
3. **Segmentación por color** (`segment_by_color`): separa negro/azul/verde/rojo en HSV, con un **rescate por dominancia de canal** para tinta desaturada o de un tono fuera de rango que el HSV solo no detecta. Las paredes a lápiz se detectan con **umbral adaptativo + transformada de distancia** (filtro por grosor que descarta la cuadrícula azul impresa). La sensibilidad (Alta/Media/Baja, elegible al subir la foto) ajusta ambos umbrales. La hoja se aísla con `detect_page_mask` (Otsu) y, si el fondo también es claro, con un **flood-fill desde los bordes** como respaldo.
4. **Detección de líneas** (`lines.py`): Hough probabilístico sobre las máscaras esqueletizadas, luego:
   - fusión de segmentos colineales, extensión a intersecciones y recorte de colgajos en esquinas;
   - **cierre del contorno exterior como rectángulo** (completa paredes demasiado tenues para detectarse);
   - **muebles** como figuras limpias: se podan las colitas cortas y los extremos libres se estiran hasta la pared cercana (no quedan "volando").
5. **Recintos** (`rooms.py`): arma el grafo de intersecciones de muros y extrae los ciclos = habitaciones; descarta el recinto envolvente.
6. **Puertas → huecos reales** (`lines.cut_walls_at_doors`): las puertas que caen sobre un muro **lo cortan**, dejando una abertura real en vez de dibujarse encima de una pared continua. Las puertas que flotan (sin muro) o los fragmentos diminutos se descartan (`keep_doors_on_walls`). Esto es lo que permite que las flechas crucen por la puerta.
7. **Generación Fabric.js** (`fabric.py`): cada segmento → objeto tipado (`pared`, `puerta`, `vano`, `mueble`, `recinto`) y se **reencuadra** todo para llenar la hoja dejando banda para el título.

> El título NO se incrusta en el pipeline: lo pone el editor.

---

## El editor web (cliente, Fabric.js)

El editor (`/plans/<id>/editor/`) corre **100% en el navegador** sobre **Fabric.js**, en formato **oficio horizontal (330 × 216 mm)**. Toda la lógica está en **`static/js/canvas.js`** (+ `icons.js` para los SVG).

> Importante: el **ruteo de flechas y la exportación a PDF son del lado del cliente** (en `canvas.js`). Las apps Django `routing/`, `signaling/` y `export/services/` son stubs reservados para una futura versión en servidor.

### Flujo en el editor

1. El plano vectorizado se carga automáticamente (o empiezas en blanco y dibujas).
2. **Dibuja / corrige:** pared (gruesa, bloquea), mueble (delgada, bloquea), puerta (arco) o vano (abertura) que abren el paso. Los extremos se enganchan (snap) a líneas cercanas.
3. **Coloca elementos** del panel (sección "3 · Puntos clave" y los iconos de evacuación/sanitaria/estructura): extintor, botiquín, punto de encuentro, salida, camilla, baño, entrada/salida y 4 canecas (ordinaria, reciclable, biosanitaria, cortopunzantes).
4. **Genera rutas automáticamente** (sección "4 · Rutas automáticas"): marcá opcionalmente un **punto de partida** por herramienta dedicada (si no lo hacés, cada ruta sale del centro del recinto/caneca) y una salida, y tocá **Generar**:
   - **Evacuación:** cada recinto (u origen marcado) traza una flecha **verde** hasta la salida.
   - **Sanitaria:** cada caneca traza una flecha **de su color** hasta la salida.
   - Las rutas generadas son seleccionables, movibles y borrables; "Borrar rutas generadas" limpia solo las automáticas.
5. **Rutas manuales** (sección "5 · Rutas manuales") quedan como respaldo para dibujar o retocar un tramo a mano (clics o mano alzada).
6. **Exporta a PDF** oficio horizontal — incluye tanto las rutas generadas como las manuales.

### Cómo se calculan las rutas (en el cliente)

- El lienzo se rasteriza en una **grilla** (`GRID = 10 px`); paredes y muebles marcan celdas bloqueadas con holgura (`CLEAR = 20 px`), y las puertas/vanos **liberan** el paso por su abertura.
- **A\*** con movimientos en 4 direcciones → rutas base en ángulos de 90° que solo cruzan por puertas/vanos.
- **String-pulling** (línea de visión) sobre la ruta del A\* colapsa la "escalera" de celdas en tramos largos, con diagonales donde hay espacio libre; en pasillos angostos el resultado queda ortogonal, como antes.
- El destino de cada ruta es el **centro del hueco** de la puerta de salida (`srGapX/srGapY`).
- **Fusión:** rutas del mismo color al mismo destino comparten tronco. **Carriles:** rutas de distinto color que comparten pasillo corren paralelas, sin encimarse (con reintentos de desfase si el pasillo es angosto).
- Cada ruta se dibuja como un único trazo continuo con **esquinas redondeadas**, **una sola punta de flecha** al final y marcas de dirección sutiles a lo largo del recorrido.

> La señalización automática (extintores por cobertura / señales NTC) está prevista en el roadmap (FASE 6) pero **no está activa** en el editor actual. Los iconos sí se pueden colocar a mano desde el panel.

---

## Stack tecnológico

| Capa | Tecnología | Propósito |
|---|---|---|
| Backend | **Django 5** | Web, ORM, admin, auth, templates |
| Base de datos | **SQLite3** (dev) | Proyectos, planos, jobs |
| Visión artificial | **OpenCV + NumPy** | Segmentación por color, detección de líneas, recintos |
| Editor / ruteo / export | **Fabric.js 5.x** (navegador) | Dibujo, A\*, PDF — todo cliente |
| Frontend | **Django Templates + CSS** | Sin SPA |

---

## Estructura real del proyecto

```
SketchRoute/
├── manage.py
├── db.sqlite3
├── requirements.txt
│
├── sketchroute/                 # Config Django (settings, urls, wsgi, asgi)
│
├── apps/
│   ├── accounts/                # Registro / login / perfiles (User con phone/company)
│   ├── plans/                   # Modelo Plan (dueño = user) + vista del editor
│   │   └── models.py            # Plan (imagen, escala, orientación, canvas_data…)
│   ├── processing/              # ⭐ Pipeline de visión (servidor)
│   │   ├── models.py            # ProcessingJob (estado, resultado)
│   │   ├── views.py             # upload_image, reprocess, job_status
│   │   └── services/
│   │       ├── preprocessing.py # perspectiva, hoja, color, reescalado
│   │       ├── lines.py         # Hough, fusión, cortes de pared, muebles
│   │       ├── rooms.py         # recintos por grafo
│   │       ├── fabric.py        # → objetos Fabric.js + reencuadre
│   │       └── pipeline.py      # orquestador
│   ├── routing/                 # (stub) reservado para ruteo en servidor
│   ├── signaling/               # (stub) reservado para señalización en servidor
│   └── export/                  # (stub) reservado para export en servidor
│
├── templates/
│   ├── plans/editor.html        # Editor Fabric.js (carga icons.js + canvas.js)
│   ├── processing/upload.html   # Subida de croquis
│   ├── projects/ · accounts/ · export/
│
├── static/
│   ├── js/
│   │   ├── canvas.js            # ⭐ Editor: dibujo, A* de rutas, export PDF
│   │   ├── icons.js             # Biblioteca de iconos SVG
│   │   └── main.js
│   └── css/  (style.css, editor.css)
│
├── media/                       # Fotos de croquis subidas
└── qa/                          # Scripts de prueba/diagnóstico del pipeline
    ├── render.py                # Renderiza el canvas_data a PNG para verificar
    ├── route_test.py            # Simula buildGrid+A* del editor (rutas → salida)
    └── diag_*.py                # Volcado de máscaras / componentes
```

---

## Modelo de datos (activo)

```
User (AbstractUser)  → phone, company

Plan                 → user, name, original_image, scale (px/cm),
                       orientation, canvas_data (JSON Fabric.js),
                       is_vectorized, created_at, updated_at

ProcessingJob        → plan (1:1), status (pending/processing/completed/failed),
                       processed_image, vector_data (JSON), error_message,
                       created_at, updated_at
```

### Cuentas y visibilidad

No importa de qué cuenta salió un plano: si sos **admin** en Systefarma podés
ver cualquier ruta hecha por cualquier persona — todos los planos son
públicos entre admins. Lo que sí importa de las cuentas es que **quede
registrado quién lo hizo** (autoría), no restringir quién puede verlo.

> Los modelos `EvacuationRoute` y `Signal` existen pero **no se usan**: el ruteo y la señalización ocurren en el cliente y se guardan dentro de `Plan.canvas_data`.

### Subida de foto: procesamiento en segundo plano

Subir una foto lanza el pipeline en un **hilo aparte** (sin bloquear el request ni depender de Celery) y redirige a una pantalla de **progreso** (`/processing/progress/<plan_id>/`) que hace polling al estado cada 1.5s. Al terminar, muestra los conteos (paredes/puertas/muebles/recintos) y un **overlay** con lo detectado antes de entrar al editor; si falla, ofrece reintentar, subir otra foto o entrar igual al editor. `ProcessingJob.vector_data` guarda la sensibilidad usada, los conteos y el `debug` del pipeline (antes se descartaba). "Reprocesar" reutiliza la última sensibilidad elegida.

---

## Cómo empezar

### Prerrequisitos
- Python 3.10+
- pip

### Instalación

```bash
# 1. Clonar
git clone https://github.com/tu-usuario/SketchRoute.git
cd SketchRoute

# 2. Entorno virtual
python -m venv .venv
.venv\Scripts\activate          # Windows
# source .venv/bin/activate     # Linux/Mac

# 3. Dependencias
pip install -r requirements.txt

# 4. Migrar
python manage.py migrate

# 5. Superusuario
python manage.py createsuperuser

# 6. Servidor de desarrollo
python manage.py runserver
# → http://127.0.0.1:8000/
```

### Notas de desarrollo

- En desarrollo se suele correr en el puerto **8001 con `--noreload`** (`python manage.py runserver 8001 --noreload`); al ser `--noreload` hay que **reiniciar** el servidor para que tome cambios del pipeline.
- **Caché del navegador:** al editar `static/js/canvas.js` o `icons.js` hay que **subir el `?v=N`** en `templates/plans/editor.html` (o recargar con Ctrl+F5). Si no, el navegador sirve el JS viejo y "sale igual".
- **Verificar el pipeline sin navegador:** `.venv/Scripts/python qa/render.py` genera `qa/out/RESULT.png`; `qa/route_test.py` confirma que todos los recintos llegan a la salida.

---

## Roadmap (Fases)

| Fase | Descripción | Fechas | % |
|---|---|---|---|
| **FASE 0** | Planificación & Setup | 12–17 Jun | 9% |
| **FASE 1** | Diseño UX/UI | 17–18 Jun | 12% |
| **FASE 2** | Motor de Canvas (Fabric.js) | 18–23 Jun | 24% |
| **FASE 3** | Visión artificial (OpenCV) | 24 Jun–3 Jul | 42% |
| **FASE 4** | Corrección asistida | 6–7 Jul | 52% |
| **FASE 5** | Rutas de evacuación | 8–15 Jul | 67% |
| **FASE 6** | Señalización automática (NTC) | 15–21 Jul | 79% |
| **FASE 7** | Exportación, backend & deploy | 22–30 Jul | 100% |

---

## Licencia

Uso educativo — Proyecto universitario.

## Créditos

Desarrollado por **p1p2gamer26** y **Carito Uwu** para el proyecto de Rutas Sanitarias y Evacuación.
