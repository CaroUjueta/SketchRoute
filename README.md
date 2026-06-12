# SketchRoute — Editor Web de Rutas Sanitarias y Evacuación

> **Estado:** MVP — Fase 0 (Planificación & Setup)
> **Cronograma:** 12 Jun — 30 Jul 2026
> **Entrega final:** Jueves 30 de Julio de 2026

---

## ¿Qué es SketchRoute?

SketchRoute es una aplicación web que convierte croquis dibujados a mano en **planos de evacuación profesionales**, listos para imprimir en formato horizontal carta. Está diseñada para ingenieros, arquitectos, brigadistas y cualquier persona que necesite generar planos de rutas sanitarias y de evacuación de forma rápida, sin usar software CAD.

### ¿Qué problema resuelve?

Hoy en día, hacer un plano de evacuación implica:
1. Dibujar el plano a mano o en AutoCAD
2. Calcular manualmente las rutas de evacuación
3. Ubicar extintores y señales según normativa (NTC 2885 en Colombia)
4. Dibujar las flechas de ruta
5. Exportar a PDF con las medidas y cotas

SketchRoute automatiza todo esto: **dibujas en papel, tomas una foto y el sistema hace el resto.**

---

## Flujo de trabajo completo

```
┌─────────────────────────────────────────────────────────────────┐
│  1. DIBUJO EN PAPEL                                              │
│  • Papel blanco (tamaño carta, horizontal)                       │
│  • Paredes de un color (ej: negro/azul)                          │
│  • Puertas de otro color (ej: rojo)                              │
│  • Muebles de otro color (ej: verde)                             │
│  • Señalizar salidas existentes                                  │
└──────────────────────────┬──────────────────────────────────────┘
                           ↓
┌─────────────────────────────────────────────────────────────────┐
│  2. FOTO & SUBIDA                                                │
│  • Tomar foto con el celular                                     │
│  • Subir a la web                                                │
│  • El sistema procesa con OpenCV                                 │
└──────────────────────────┬──────────────────────────────────────┘
                           ↓
┌─────────────────────────────────────────────────────────────────┐
│  3. VISIÓN ARTIFICIAL (OpenCV)                                   │
│  • Corrección de perspectiva                                     │
│  • Segmentación por colores (pared/puerta/mueble)                │
│  • Detección de muros (Hough Lines / LSD)                        │
│  • Detección de puertas y ventanas                               │
│  • Vectorización a SVG/JSON                                      │
└──────────────────────────┬──────────────────────────────────────┘
                           ↓
┌─────────────────────────────────────────────────────────────────┐
│  4. EDITOR WEB (Fabric.js)                                       │
│  • Carga automática del plano vectorizado                        │
│  • Herramientas: seleccionar, pared, puerta, ventana             │
│  • Corrección asistida (comparar original vs detectado)          │
│  • Etiquetado de salidas de emergencia                           │
└──────────────────────────┬──────────────────────────────────────┘
                           ↓
┌─────────────────────────────────────────────────────────────────┐
│  5. RUTAS DE EVACUACIÓN                                           │
│  • Conversión del plano a grafo (NetworkX)                       │
│  • Cálculo de rutas con A* y Dijkstra                            │
│  • Ruta más cercana a salida por zona                            │
│  • Detección de zonas sin ruta de escape                         │
└──────────────────────────┬──────────────────────────────────────┘
                           ↓
┌─────────────────────────────────────────────────────────────────┐
│  6. SEÑALIZACIÓN AUTOMÁTICA (NTC)                                │
│  • Extintores: cobertura cada 15m (NTC 2885)                     │
│  • Señales EXIT / SALIDA en rutas de evacuación                  │
│  • Botiquines, alarmas, detectores de humo                       │
│  • Punto de encuentro exterior                                   │
└──────────────────────────┬──────────────────────────────────────┘
                           ↓
┌─────────────────────────────────────────────────────────────────┐
│  7. EXPORTACIÓN                                                  │
│  • PDF vectorial horizontal carta (con cotas y medidas)          │
│  • PNG de alta resolución                                        │
│  • SVG editable                                                  │
└─────────────────────────────────────────────────────────────────┘
```

---

## Stack tecnológico

| Capa | Tecnología | Propósito |
|---|---|---|
| Backend | **Django 5.0** | Framework web completo (ORM, admin, auth, templates) |
| Base de datos | **SQLite3** (dev) / PostgreSQL (prod) | Persistencia de proyectos y planos |
| Visión artificial | **OpenCV 4.x + NumPy** | Procesamiento de imagen, segmentación por color, detección de líneas |
| Editor canvas | **Fabric.js 5.x** | Editor interactivo de planos en el navegador |
| Rutas | **NetworkX** | Construcción de grafos y algoritmos A*, Dijkstra |
| PDF | **ReportLab** | Generación de PDF vectorial con cotas |
| SVG | **svgwrite + CairoSVG** | Exportación vectorial y rasterización |
| Frontend | **Django Templates + CSS plano** | Interfaz clásica del lado del servidor (sin SPA) |

---

## Estructura del proyecto

```
SketchRoute/
├── manage.py                 # Punto de entrada de Django
├── db.sqlite3                # Base de datos local
├── requirements.txt          # Dependencias del proyecto
├── .gitignore
│
├── sketchroute/              # Configuración principal de Django
│   ├── settings.py           # Configuración global
│   ├── urls.py               # Rutas raíz
│   ├── wsgi.py               # WSGI para producción
│   └── asgi.py               # ASGI (futuro)
│
├── apps/                     # Todas las aplicaciones Django
│   ├── __init__.py
│   │
│   ├── accounts/             # Registro, login, logout, perfiles
│   │   ├── models.py         # User (AbstractUser con teléfono/empresa)
│   │   ├── views.py          # RegisterView, LoginView, LogoutView
│   │   ├── urls.py           # /accounts/register/, /login/, /logout/
│   │   └── admin.py
│   │
│   ├── projects/             # CRUD de proyectos del usuario
│   │   ├── models.py         # Project (user, name, description)
│   │   ├── views.py          # ListView, CreateView, UpdateView, DeleteView
│   │   ├── urls.py           # /projects/, /create/, /<id>/, etc.
│   │   └── admin.py
│   │
│   ├── plans/                # Planos dentro de un proyecto
│   │   ├── models.py         # Plan (imagen, escala, orientación, canvas_data)
│   │   ├── views.py          # Editor canvas
│   │   ├── urls.py           # /<id>/editor/
│   │   └── admin.py
│   │
│   ├── processing/           # Pipeline de visión artificial
│   │   ├── models.py         # ProcessingJob (estado, resultado)
│   │   ├── views.py          # Upload y procesamiento
│   │   ├── urls.py
│   │   ├── admin.py
│   │   └── services/         # Lógica del pipeline
│   │       ├── upload_service.py      # Recepción de imagen
│   │       ├── preprocessing.py       # Binarización, ecualización
│   │       ├── color_segmentation.py  # Separar por colores HSV
│   │       ├── perspective.py         # Corrección de perspectiva
│   │       ├── wall_detection.py      # Detección de muros (Hough)
│   │       ├── room_detection.py      # Segmentación de recintos
│   │       ├── symbol_detection.py    # Puertas, ventanas, escaleras
│   │       ├── vectorizer.py          # Conversión a SVG/JSON
│   │       └── parser.py              # Parseo a objetos del editor
│   │
│   ├── routing/              # Algoritmos de rutas de evacuación
│   │   ├── models.py         # EvacuationRoute (nombre, datos, longitud)
│   │   ├── views.py          # API de cálculo de rutas
│   │   ├── urls.py
│   │   ├── admin.py
│   │   └── services/
│   │       ├── graph_builder.py   # Plano → grafo NetworkX
│   │       ├── pathfinder.py      # A*, Dijkstra, BFS
│   │       ├── nearest_exit.py    # Ruta a salida más cercana
│   │       └── route_renderer.py  # Geometría de flechas/ruta
│   │
│   ├── signaling/            # Motor de señalización NTC
│   │   ├── models.py         # Signal (tipo, posición, rotación)
│   │   ├── views.py          # Colocación automática
│   │   ├── urls.py
│   │   ├── admin.py
│   │   ├── rules_engine.py   # Motor de reglas (JSON configurable)
│   │   ├── coverage.py       # Cobertura de extintores
│   │   └── signal_placer.py  # Inserción automática
│   │
│   └── export/               # Exportación a PDF/PNG/SVG
│       ├── models.py         # ExportedFile (tipo, archivo)
│       ├── views.py          # Opciones de exportación
│       ├── urls.py
│       ├── admin.py
│       └── services/
│           ├── pdf_exporter.py      # ReportLab → PDF horizontal carta
│           ├── png_exporter.py      # CairoSVG → PNG
│           ├── svg_exporter.py      # SVG vectorial
│           └── measure_renderer.py  # Cotas y medidas en el PDF
│
├── templates/                # Templates HTML (Django Template Language)
│   ├── base.html             # Layout base con header, footer, messages
│   ├── accounts/
│   │   ├── login.html
│   │   └── register.html
│   ├── projects/
│   │   ├── list.html
│   │   ├── detail.html
│   │   ├── form.html
│   │   └── confirm_delete.html
│   ├── plans/
│   │   └── editor.html       # Editor con Fabric.js
│   ├── processing/
│   │   └── upload.html
│   └── export/
│       └── export_options.html
│
├── static/                   # Archivos estáticos
│   ├── css/
│   │   └── style.css         # Estilos del sitio
│   ├── js/
│   │   ├── main.js           # Utilidades generales
│   │   └── canvas.js         # Lógica del editor Fabric.js
│   └── img/
│
└── media/                    # Archivos subidos por usuarios
    └── uploads/              # Fotos de croquis
```

---

## Modelo de datos

```
User (AbstractUser)
├── phone: CharField
└── company: CharField

Project
├── user: ForeignKey(User)
├── name: CharField
├── description: TextField
├── created_at: DateTimeField
└── updated_at: DateTimeField

Plan
├── project: ForeignKey(Project)
├── name: CharField
├── original_image: ImageField
├── scale: FloatField (px/cm)
├── orientation: CharField (horizontal/vertical)
├── canvas_data: JSONField (Fabric.js)
├── is_vectorized: BooleanField
├── created_at: DateTimeField
└── updated_at: DateTimeField

ProcessingJob
├── plan: OneToOneField(Plan)
├── status: CharField (pending/processing/completed/failed)
├── processed_image: ImageField
├── vector_data: JSONField
├── error_message: TextField
├── created_at: DateTimeField
└── updated_at: DateTimeField

EvacuationRoute
├── plan: ForeignKey(Plan)
├── name: CharField
├── route_data: JSONField
├── total_length: FloatField (metros)
└── created_at: DateTimeField

Signal
├── plan: ForeignKey(Plan)
├── signal_type: CharField (extinguisher/exit/first_aid/alarm/meeting_point/fire_hose)
├── position_x: FloatField
├── position_y: FloatField
├── rotation: FloatField
├── auto_placed: BooleanField
└── created_at: DateTimeField

ExportedFile
├── plan: ForeignKey(Plan)
├── file_type: CharField (pdf/png/svg)
├── file: FileField
└── created_at: DateTimeField
```

---

## Pipeline de procesamiento de imagen (OpenCV)

El módulo `processing/services/` implementa el pipeline que convierte una foto de un croquis en papel a un plano vectorial:

### 1. `upload_service.py`
Recibe la imagen, la valida (formato, tamaño, resolución) y la guarda en el modelo `Plan`.

### 2. `preprocessing.py`
- Convierte a escala de grises
- Aplica filtro Gaussiano para reducir ruido
- Ecualización del histograma para mejorar contraste
- Binarización adaptativa

### 3. `color_segmentation.py`
Segmenta la imagen por colores usando espacio de color HSV:
- **Paredes:** color oscuro (negro, azul oscuro, gris)
- **Puertas:** color contrastante (rojo, naranja)
- **Muebles:** color diferente (verde, amarillo)
- Cada capa de color se procesa por separado

### 4. `perspective.py`
- Detecta las esquinas del papel (contorno más grande)
- Aplica transformación de perspectiva para enderezar la imagen
- Escala la imagen a las dimensiones esperadas

### 5. `wall_detection.py`
- Aplica Hough Lines Probabilístico o LSD (Line Segment Detector)
- Filtra líneas por longitud mínima
- Agrupa líneas colineales cercanas
- Extiende líneas para formar intersecciones en esquinas
- Devuelve una lista de segmentos de pared

### 6. `room_detection.py`
- Usa los contornos cerrados formados por las paredes
- Aplica flood fill para identificar recintos
- Etiqueta cada habitación detectada
- Calcula el área de cada recinto

### 7. `symbol_detection.py`
- Detecta huecos en las paredes (puertas)
- Detecta rectángulos con patrón de cruz (ventanas)
- Detecta espirales o rectángulos con escalones (escaleras)
- Usa detección de contornos y template matching

### 8. `vectorizer.py`
- Convierte todas las detecciones a coordenadas vectoriales
- Genera un JSON con la estructura de objetos del plano
- También genera un SVG para visualización inmediata

### 9. `parser.py`
- Toma el JSON del vectorizador
- Crea los objetos de Fabric.js correspondientes (líneas, rectángulos)
- Devuelve el `canvas_data` listo para cargar en el editor

---

## Algoritmos de rutas (`routing/services/`)

### `graph_builder.py`
Convierte el plano (paredes, puertas, habitaciones) en un grafo de nodos y aristas usando NetworkX:
- Los nodos son: intersecciones de paredes, centros de puertas, puntos de interés
- Las aristas son los pasillos y espacios transitables
- Peso de arista = distancia euclidiana real en metros

### `pathfinder.py`
Implementa:
- **A\* (A estrella):** Ruta óptima con heurística de distancia Manhattan
- **Dijkstra:** Ruta más corta sin heurística
- **BFS:** Para encontrar todas las rutas posibles en un área

### `nearest_exit.py`
- Para cada zona/habitación, encuentra la salida más cercana
- Genera rutas desde cualquier punto hasta la salida asignada
- Detecta zonas sin ruta de escape válida

### `route_renderer.py`
- Convierte la ruta calculada a geometría (flechas, líneas)
- Genera el JSON para superponer en el canvas
- Incluye puntos de decisión y direcciones

---

## Señalización automática (NTC Colombiana)

El módulo `signaling/` implementa reglas basadas en normativa técnica colombiana:

- **NTC 2885:** Extintores — cobertura de 15m de distancia máxima desde cualquier punto
- **NTC 1461:** Señales de evacuación — ubicación en cada cambio de dirección
- **NTC 170:** Colores y símbolos de seguridad

El motor de reglas (`rules_engine.py`) está diseñado para ser configurable mediante JSON, permitiendo actualizar las normas sin cambiar código.

---

## Exportación (`export/services/`)

### `pdf_exporter.py`
- Usa ReportLab para generar PDF vectorial
- Formato horizontal carta (279.4 × 215.9 mm)
- Incluye: plano, cotas, señales, rutas, leyenda, datos del proyecto
- La cuadrícula de fondo opcional ayuda a verificar escala

### `png_exporter.py`
- Renderiza el canvas a imagen PNG
- Usa CairoSVG si está disponible, o captura del canvas HTML
- Resolución configurable (300 DPI para impresión)

### `svg_exporter.py`
- Genera SVG editable directamente desde los datos del canvas
- Compatible con Illustrator, Inkscape, etc.

### `measure_renderer.py`
- Calcula y dibuja cotas lineales en las paredes
- Muestra las dimensiones de cada habitación
- Escala las medidas según la escala configurada

---

## Cómo empezar

### Prerrequisitos

- Python 3.10+
- pip
- (Opcional) OpenCV instalado en el sistema

### Instalación

```bash
# 1. Clonar el repositorio
git clone https://github.com/tu-usuario/SketchRoute.git
cd SketchRoute

# 2. Crear entorno virtual
python -m venv .venv

# 3. Activar el entorno
# Windows:
.venv\Scripts\activate
# Linux/Mac:
source .venv/bin/activate

# 4. Instalar dependencias
pip install -r requirements.txt

# 5. Migrar la base de datos
python manage.py migrate

# 6. Crear superusuario (admin)
python manage.py createsuperuser

# 7. Iniciar servidor de desarrollo
python manage.py runserver

# 8. Abrir en el navegador
# http://127.0.0.1:8000/
```

### Usuarios de prueba

```bash
# Crear un usuario normal
python manage.py shell -c "from apps.accounts.models import User; User.objects.create_user('test', 'test@test.com', 'test1234')"
```

---

## Roadmap (Fases)

| Fase | Descripción | Fechas | % del proyecto |
|---|---|---|---|
| **FASE 0** | Planificación & Setup | 12–17 Jun | 9% |
| **FASE 1** | Diseño UX/UI (wireframes, prototipo) | 17–18 Jun | 12% |
| **FASE 2** | Motor de Canvas (Fabric.js) | 18–23 Jun | 24% |
| **FASE 3** | IA de Visión Artificial | 24 Jun–3 Jul | 42% |
| **FASE 4** | Corrección Asistida | 6–7 Jul | 52% |
| **FASE 5** | Rutas de Evacuación | 8–15 Jul | 67% |
| **FASE 6** | Señalización Automática (NTC) | 15–21 Jul | 79% |
| **FASE 7** | Exportación, Backend & Deploy | 22–30 Jul | 100% |

Ver el archivo `RoadMap_Editor_Evacuacion.xlsx` para el detalle completo de las 53 tareas.

---

## Convenciones de dibujo (para el croquis en papel)

Para obtener los mejores resultados con el procesamiento de imagen:

| Elemento | Color recomendado | Notas |
|---|---|---|
| Paredes | **Negro** o **Azul oscuro** | Trazo continuo, líneas rectas |
| Puertas | **Rojo** | Arco de apertura + línea de la puerta |
| Ventanas | **Azul claro** | Rectángulo con línea central |
| Muebles | **Verde** | Contorno del mueble |
| Escaleras | **Naranja** | Rectángulo con líneas de escalones |
| Textos | **Negro** | Letra clara, sin adornos |

**Recomendaciones:**
- Usar papel blanco tamaño carta (horizontal)
- Hacer las líneas de paredes continuas y rectas
- Diferenciar bien los colores (sin tonos ambiguos)
- Buena iluminación al tomar la foto
- Evitar sombras y reflejos

---

## Licencia

Uso educativo — Proyecto universitario.

---

## Créditos

Desarrollado por [p1p2gamer26] y [Carito Uwu] como parte del proyecto de Rutas Sanitarias y Evacuación.
