import cv2
import numpy as np


def deskew(image, min_deg=2.0, max_deg=15.0):
    """Endereza una foto levemente torcida con rotación pura (sin homografía).

    correct_perspective se auto-desactiva en fotos torcidas sin borde de hoja
    claro; el clasificador de líneas H/V estricto pierde entonces los trazos
    oblicuos. Este fallback mide el ángulo dominante de las líneas (Hough) y,
    si está a 2-15° de los ejes, rota la imagen para recuperarlos. Devuelve
    (imagen, grados_aplicados)."""
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    edges = cv2.Canny(gray, 50, 150)
    found = cv2.HoughLines(edges, 1, np.pi / 360, 150)
    if found is None or len(found) < 5:
        return image, 0.0
    devs = []
    for entry in found[:300]:
        deg = np.degrees(entry[0][1]) % 90.0
        devs.append(deg if deg <= 45 else deg - 90.0)   # desvío del eje [-45,45]
    med = float(np.median(devs))
    if abs(med) < min_deg or abs(med) > max_deg:
        return image, 0.0
    h, w = image.shape[:2]
    M = cv2.getRotationMatrix2D((w / 2, h / 2), med, 1.0)
    out = cv2.warpAffine(image, M, (w, h), flags=cv2.INTER_LINEAR,
                         borderMode=cv2.BORDER_REPLICATE)
    return out, med


def correct_perspective(image):
    """Corrige perspectiva encontrando el contorno del documento y aplicando
    transformación de homografía.

    Es CONSERVADORA a propósito: solo aplica la transformación si el
    cuadrilátero detectado cubre buena parte de la imagen (es la hoja, no
    un rectángulo dibujado adentro) y si el resultado conserva dimensiones
    razonables. En cualquier otro caso devuelve la imagen original, porque
    una corrección equivocada destruye el croquis (lo recorta a un pedazo
    diminuto). Para una foto de cuaderno razonablemente plana, no corregir
    es mucho más seguro que corregir mal."""
    img_h, img_w = image.shape[:2]
    img_area = img_h * img_w

    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    blurred = cv2.GaussianBlur(gray, (5, 5), 0)
    edged = cv2.Canny(blurred, 50, 150)

    dilated = cv2.dilate(edged, None, iterations=2)
    contours, _ = cv2.findContours(dilated, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

    if not contours:
        return image

    contours = sorted(contours, key=cv2.contourArea, reverse=True)

    pts = None
    for c in contours:
        # el contorno debe cubrir la mayor parte de la imagen (es la hoja)
        if cv2.contourArea(c) < 0.5 * img_area:
            break  # los siguientes son aún más pequeños
        peri = cv2.arcLength(c, True)
        approx = cv2.approxPolyDP(c, 0.02 * peri, True)
        if len(approx) == 4:
            pts = approx.reshape(4, 2).astype(np.float32)
            break

    if pts is None:
        return image

    # verificar si el cuadrilátero ya es casi un rectángulo
    if _is_nearly_rect(pts, angle_tol=10, aspect_tol=0.3):
        return image

    rect = _order_points(pts)
    (tl, tr, br, bl) = rect
    w = int(max(dist(bl, br), dist(tl, tr)))
    h = int(max(dist(tl, bl), dist(tr, br)))

    # rechazar correcciones que encogen demasiado la imagen (contorno malo)
    if w < 0.5 * img_w or h < 0.5 * img_h:
        return image

    dst = np.array([
        [0, 0],
        [w - 1, 0],
        [w - 1, h - 1],
        [0, h - 1],
    ], dtype=np.float32)

    M = cv2.getPerspectiveTransform(rect, dst)
    return cv2.warpPerspective(image, M, (w, h))


def _is_nearly_rect(pts, angle_tol=10, aspect_tol=0.3):
    """Verifica si 4 puntos forman un rectángulo casi perfecto.

    Calcula los ángulos internos y la relación de aspecto.
    Si todos los ángulos están cerca de 90° y los lados opuestos
    son paralelos, el cuadrilátero ya es un rectángulo."""
    pts = _order_points(pts.astype(np.float32))
    p = [np.array(pt) for pt in pts]

    def angle(a, b, c):
        v1 = a - b
        v2 = c - b
        dot = np.dot(v1, v2)
        norm = np.linalg.norm(v1) * np.linalg.norm(v2)
        if norm < 1e-6:
            return 0
        return abs(np.degrees(np.arccos(dot / norm)))

    angles = [
        angle(p[0], p[1], p[2]),  # en tr
        angle(p[1], p[2], p[3]),  # en br
        angle(p[2], p[3], p[0]),  # en bl
        angle(p[3], p[0], p[1]),  # en tl
    ]

    # todos los ángulos deben estar cerca de 90°
    for ang in angles:
        if abs(ang - 90) > angle_tol:
            return False

    # verificar paralelismo de lados opuestos
    def parallel(a, b, c, d):
        v1 = b - a
        v2 = d - c
        if np.linalg.norm(v1) < 1 or np.linalg.norm(v2) < 1:
            return True
        cross = abs(np.cross(v1, v2))
        norm = np.linalg.norm(v1) * np.linalg.norm(v2)
        return cross / norm < 0.15  # seno del ángulo < 0.15

    if not parallel(p[0], p[1], p[3], p[2]):
        return False
    if not parallel(p[1], p[2], p[0], p[3]):
        return False

    return True


def _order_points(pts):
    """Ordena 4 puntos: tl, tr, br, bl."""
    rect = np.zeros((4, 2), dtype=np.float32)
    s = pts.sum(axis=1)
    rect[0] = pts[np.argmin(s)]
    rect[2] = pts[np.argmax(s)]
    d = np.diff(pts, axis=1)
    rect[1] = pts[np.argmin(d)]
    rect[3] = pts[np.argmax(d)]
    return rect


def dist(a, b):
    return np.linalg.norm(a - b)


def grayscale(image):
    if len(image.shape) == 3:
        return cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    return image


def binarize(gray, method='adaptive'):
    """Binariza usando Otsu o adaptive thresholding.

    Para croquis dibujados a mano, adaptive thresholding suele dar mejor
    resultado porque se adapta a la iluminación no uniforme del papel."""
    blurred = cv2.GaussianBlur(gray, (3, 3), 0)

    if method == 'otsu':
        _, binary = cv2.threshold(blurred, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
    else:
        binary = cv2.adaptiveThreshold(
            blurred, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
            cv2.THRESH_BINARY_INV, 21, 6,
        )
    return binary


def denoise(binary):
    """Limpia ruido con operaciones morfológicas.

    - closing para cerrar pequeños huecos en las líneas (común en croquis
      dibujados a mano donde el trazo no es continuo)
    - opening para eliminar puntitos de ruido aislados
    - elimina componentes conectados muy pequeños"""
    kernel = np.ones((3, 3), np.uint8)
    cleaned = cv2.morphologyEx(binary, cv2.MORPH_CLOSE, kernel, iterations=2)
    cleaned = cv2.morphologyEx(cleaned, cv2.MORPH_OPEN, kernel, iterations=1)

    n_labels, labels, stats, _ = cv2.connectedComponentsWithStats(cleaned, connectivity=8)
    min_area = 30
    for i in range(1, n_labels):
        if stats[i, cv2.CC_STAT_AREA] < min_area:
            cleaned[labels == i] = 0

    return cleaned


def resize_to_canvas(binary, target_w=1320, target_h=864):
    """Redimensiona manteniendo aspect ratio y centra en canvas oficio.

    Reserva una banda arriba para el título 'PLANO VECTORIZADO', de modo que
    el plano nunca se monte sobre el texto."""
    h, w = binary.shape
    # banda superior reservada para el título
    top_reserve = int(target_h * 0.08)  # ~70 px
    avail_h = target_h - top_reserve
    scale = min(target_w / w, avail_h / h)
    nw, nh = int(w * scale), int(h * scale)
    resized = cv2.resize(binary, (nw, nh), interpolation=cv2.INTER_NEAREST)

    canvas = np.zeros((target_h, target_w), dtype=np.uint8)
    # Alinear a la IZQUIERDA (con un margen) en vez de centrar: así el plano
    # llena el alto de la página y todo el espacio libre queda a la DERECHA,
    # donde el usuario puede colocar cosas después (espacio de respeto).
    free_x = target_w - nw
    margin = int(target_w * 0.02)
    x_off = min(margin, free_x) if free_x > 0 else 0
    y_off = top_reserve + (avail_h - nh) // 2
    canvas[y_off:y_off + nh, x_off:x_off + nw] = resized

    scale_info = {
        'scale': scale,
        'offset_x': x_off,
        'offset_y': y_off,
        'orig_w': w,
        'orig_h': h,
        'canvas_w': target_w,
        'canvas_h': target_h,
    }
    return canvas, scale_info


# ── Segmentación por color ─────────────────────────────────

# Mapa de colores BGR → tipo de elemento.
#
# Esta es la ÚNICA fuente de verdad de los colores que el usuario debe usar
# al dibujar el croquis en papel. La leyenda que se muestra en la web
# (pantalla de subida y editor) se genera a partir de aquí — ver
# drawing_legend() — para que nunca se desfase de lo que el pipeline detecta.
#
# Cada entrada incluye:
#   display  → color hex para mostrar en la interfaz (aprox. del color real)
#   label    → color que dibuja la persona, en palabras
#   purpose  → qué representa ese color en el plano
COLOR_MAP = {
    'pared': {
        'color': (30, 30, 30),
        'hsv_ranges': [
            ((0, 0, 0), (180, 120, 120)),      # grises
            ((0, 0, 0), (180, 255, 70)),       # negros
        ],
        'stroke': '#777777',
        'stroke_width': 8,
        'display': '#1f2937',
        'label': 'Negro',
        'purpose': 'Paredes (bloquean el paso)',
    },
    'puerta': {
        'color': (200, 130, 20),
        'hsv_ranges': [
            ((85, 20, 20), (145, 255, 255)),   # azul (más tolerante en S/V)
        ],
        'stroke': '#000000',
        'stroke_width': 3,
        'display': '#1d4ed8',
        'label': 'Azul',
        'purpose': 'Puertas con arco (abren el paso)',
    },
    'mueble': {
        'color': (50, 50, 200),
        'hsv_ranges': [
            ((0, 20, 20), (14, 255, 255)),     # rojo (más tolerante en S/V)
            ((165, 20, 20), (180, 255, 255)),  # rojo (HSV envuelve)
        ],
        'stroke': '#000000',
        'stroke_width': 2,
        'display': '#dc2626',
        'label': 'Rojo',
        'purpose': 'Muebles / obstáculos (bloquean el paso)',
    },
    'vano': {
        'color': (50, 180, 50),
        'hsv_ranges': [
            ((30, 20, 20), (90, 255, 255)),    # verde (más tolerante en S/V)
        ],
        'stroke': '#000000',
        'stroke_width': 3,
        'display': '#059669',
        'label': 'Verde',
        'purpose': 'Vanos / aberturas (abren el paso)',
    },
}

# Orden recomendado para mostrar la leyenda al usuario.
_LEGEND_ORDER = ['pared', 'puerta', 'vano', 'mueble']


def drawing_legend():
    """Devuelve la leyenda de colores para dibujar el croquis, derivada de
    COLOR_MAP. Cada item: {'display', 'label', 'purpose'}.

    Es la fuente única que consume la interfaz (pantalla de subida), de modo
    que la guía para el usuario y lo que el pipeline detecta nunca se desfasen."""
    return [
        {
            'display': COLOR_MAP[k]['display'],
            'label': COLOR_MAP[k]['label'],
            'purpose': COLOR_MAP[k]['purpose'],
        }
        for k in _LEGEND_ORDER if k in COLOR_MAP
    ]


def _page_mask_by_border_floodfill(gray, h, w):
    """Fallback cuando Otsu no aísla una hoja clara y grande (fondo también
    claro, sombra fuerte desparejando el brillo...). Asume que el FONDO de
    la foto es lo que toca sus 4 esquinas y crece por similitud de brillo
    (flood-fill); la hoja es el complemento. Devuelve None si tampoco esto
    cubre una porción creíble de la imagen (mejor no restringir a ciegas
    que recortar la hoja real)."""
    ff = gray.copy()
    ffmask = np.zeros((h + 2, w + 2), np.uint8)
    for sx, sy in [(0, 0), (w - 1, 0), (0, h - 1), (w - 1, h - 1)]:
        cv2.floodFill(ff, ffmask, (sx, sy), 255, loDiff=18, upDiff=18)
    bg = (ffmask[1:-1, 1:-1] > 0).astype(np.uint8) * 255
    page_candidate = cv2.bitwise_not(bg)
    if cv2.countNonZero(page_candidate) < 0.25 * h * w:
        return None
    n, labels, stats, _ = cv2.connectedComponentsWithStats(page_candidate, connectivity=8)
    if n <= 1:
        return None
    idx = 1 + int(np.argmax(stats[1:, cv2.CC_STAT_AREA]))
    out = np.zeros((h, w), dtype=np.uint8)
    out[labels == idx] = 255
    erode_k = max(5, int(min(h, w) * 0.012)) | 1
    return cv2.erode(out, np.ones((erode_k, erode_k), np.uint8))


def detect_page_mask(bgr_image):
    """Aísla la hoja de papel del fondo (escritorio, sombras, dedos).

    La hoja es la región clara grande y conexa. Devuelve una máscara
    binaria (255 dentro de la hoja) o None si no se puede determinar.

    Esto es crítico: sin esto, la detección de paredes (negro/gris)
    confunde el fondo oscuro de la foto con muros. Restringiendo todo
    al interior de la hoja, solo quedan los trazos del dibujo."""
    h, w = bgr_image.shape[:2]
    gray = cv2.cvtColor(bgr_image, cv2.COLOR_BGR2GRAY)
    gray = cv2.GaussianBlur(gray, (5, 5), 0)

    # aplanar iluminación: una sombra suave sobre la hoja hacía que Otsu
    # clasificara media página como "fondo" (se perdía todo el dibujo de esa
    # zona). Dividir por el fondo desenfocado elimina el gradiente y deja el
    # contraste hoja/escritorio, que es lo que Otsu debe separar.
    bg = cv2.GaussianBlur(gray, (0, 0), sigmaX=min(h, w) / 12)
    flat = cv2.divide(gray, bg, scale=192)

    # umbral Otsu: separa la hoja brillante del fondo más oscuro
    _, bright = cv2.threshold(flat, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)

    # cerrar agujeros (trazos del dibujo dentro de la hoja)
    k = max(15, int(min(h, w) * 0.02)) | 1
    bright = cv2.morphologyEx(bright, cv2.MORPH_CLOSE, np.ones((k, k), np.uint8))

    n, labels, stats, _ = cv2.connectedComponentsWithStats(bright, connectivity=8)
    idx = 1 + int(np.argmax(stats[1:, cv2.CC_STAT_AREA])) if n > 1 else -1
    page_area = stats[idx, cv2.CC_STAT_AREA] if idx > 0 else 0

    # la hoja debe ocupar buena parte de la imagen; si no, Otsu no sirvió
    # (fondo claro, sombra fuerte...) — probar flood-fill desde las esquinas
    # asumiendo que el FONDO es lo que toca los 4 bordes de la foto.
    if idx < 0 or page_area < 0.25 * h * w:
        fallback = _page_mask_by_border_floodfill(gray, h, w)
        return fallback

    mask = np.zeros((h, w), dtype=np.uint8)
    mask[labels == idx] = 255

    # convex hull: la hoja es convexa (rectangular). El hull recupera la
    # parte inferior que queda en sombra y Otsu descarta, sin tragarse el
    # escritorio (que está fuera del componente brillante).
    cnts, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    hull = cv2.convexHull(np.vstack([c for c in cnts]))
    filled = np.zeros_like(mask)
    cv2.drawContours(filled, [hull], -1, 255, -1)

    # erosionar un poco para descartar el borde de la hoja y su sombra
    erode_k = max(5, int(min(h, w) * 0.012)) | 1
    filled = cv2.erode(filled, np.ones((erode_k, erode_k), np.uint8))
    return filled


def _detect_walls(gray, hsv, page, colored, radius_factor=1.0):
    """Detecta trazos de pared (lápiz negro/gris) sobre papel cuadriculado.

    El reto: la cuadrícula azul es tan fina como el lápiz, así que un umbral
    de color no las separa. La clave es el GROSOR: la cuadrícula es de ~2px,
    los trazos a lápiz de ~4px o más.

    Pasos:
    1. Umbral adaptativo → toda la tinta más oscura que el papel local
       (robusto a iluminación despareja; no depende de un valor fijo).
    2. Quitar los píxeles de color (puertas/muebles/vanos) ya detectados.
    3. Filtro de grosor por distance transform: conserva solo trazos cuyo
       núcleo supera un radio mínimo (descarta la cuadrícula fina).
    4. Restringir al interior de la hoja.

    `radius_factor` ajusta la sensibilidad: <1 detecta trazos más tenues
    (arriesga colar la cuadrícula), >1 es más estricto (arriesga perder
    lápiz claro)."""
    h, w = gray.shape[:2]
    scale = min(h, w)

    block = max(31, int(scale * 0.05)) | 1
    ink = cv2.adaptiveThreshold(
        gray, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
        cv2.THRESH_BINARY_INV, block, 10,
    )

    # quitar lo que ya es color (dilatado para cubrir el borde del trazo)
    ink[colored > 0] = 0

    # filtro de grosor: la cuadrícula (~2px) tiene radio ~1; el lápiz ~2+
    dist = cv2.distanceTransform(ink, cv2.DIST_L2, 3)
    radius_thr = max(1.0, scale * 0.00125 * radius_factor)  # ~1.5 px en una foto de ~1200px
    core = (dist >= radius_thr).astype(np.uint8) * 255
    # reconstruir el trazo completo a partir del núcleo grueso
    seed_k = max(7, int(scale * 0.0075)) | 1
    seed = cv2.dilate(core, np.ones((seed_k, seed_k), np.uint8))
    walls = cv2.bitwise_and(ink, seed)

    if page is not None:
        walls = cv2.bitwise_and(walls, page)

    # descartar componentes chicos: el margen impreso del cuaderno y el logo
    # quedan en fragmentos punteados/pequeños (la tinta impresa es fina y el
    # filtro de grosor la deja entrecortada), mientras que los muros a lápiz
    # son trazos largos y continuos que sobreviven.
    min_area = int(scale * scale * 0.00025)  # ~360 px en una foto de ~1200px
    walls = _keep_large_components(walls, min_abs=min_area)

    return walls


def _keep_large_components(binary, min_abs=480):
    """Conserva solo componentes conectados con área >= min_abs px.

    Descarta ruido aislado (logo del cuaderno, fragmentos del margen impreso,
    sombras) sin tocar los muros, que son trazos largos."""
    n, labels, stats, _ = cv2.connectedComponentsWithStats(binary, connectivity=8)
    if n <= 1:
        return binary
    out = np.zeros_like(binary)
    for i in range(1, n):
        if stats[i, cv2.CC_STAT_AREA] >= min_abs:
            out[labels == i] = 255
    return out


def _channel_dominance_fallback(bgr_image, gray, page, already_classified):
    """Clasifica por canal BGR dominante (en vez de matiz HSV) la tinta que
    el umbral de color no cubrió. Rescata esferos desaturados o de un tono
    que cae fuera de los rangos fijos de COLOR_MAP, sin tocar lo que el
    inRange ya clasificó bien."""
    h, w = gray.shape[:2]
    scale = min(h, w)
    block = max(31, int(scale * 0.05)) | 1
    ink = cv2.adaptiveThreshold(
        gray, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
        cv2.THRESH_BINARY_INV, block, 8,
    )
    if page is not None:
        ink = cv2.bitwise_and(ink, page)
    ink = cv2.bitwise_and(ink, cv2.bitwise_not(already_classified))

    b, g, r = cv2.split(bgr_image.astype(np.int16))
    maxc = np.maximum(np.maximum(b, g), r)
    minc = np.minimum(np.minimum(b, g), r)
    # descartar tinta casi neutra (gris/negro = pared, no color)
    colorish = ((maxc - minc) > 18).astype(np.uint8) * 255
    ink = cv2.bitwise_and(ink, colorish)

    dom = np.argmax(np.stack([b, g, r], axis=-1), axis=-1)  # 0=B azul,1=G verde,2=R rojo
    out = {}
    for elem_type, channel_idx in (('puerta', 0), ('vano', 1), ('mueble', 2)):
        m = ((dom == channel_idx).astype(np.uint8) * 255)
        out[elem_type] = cv2.bitwise_and(m, ink)
    return out


# Sensibilidad: cuánto tolerar tinta tenue/desaturada a costa de más ruido.
# 'radius': factor del grosor mínimo de pared (más chico = más tolerante).
# 'sat_min': saturación HSV mínima para puerta/vano/mueble (más chico = más tolerante).
SENSITIVITY_PRESETS = {
    'alta':  {'radius': 0.7, 'sat_min': 10},
    'media': {'radius': 1.0, 'sat_min': 20},
    'baja':  {'radius': 1.4, 'sat_min': 32},
}


def segment_by_color(bgr_image, sensitivity='media'):
    """Segmenta la imagen por rangos de color HSV.

    Cada píxel se clasifica como pared, puerta, mueble o fondo
    según su color. Devuelve un dict con máscaras binarias y
    configuraciones para cada tipo.

    Toda la detección se restringe al interior de la hoja de papel
    (ver detect_page_mask), de modo que el fondo de la foto nunca se
    confunde con elementos del plano.

    `sensitivity`: 'alta' | 'media' (default) | 'baja' — ver SENSITIVITY_PRESETS."""
    prefs = SENSITIVITY_PRESETS.get(sensitivity, SENSITIVITY_PRESETS['media'])
    hsv = cv2.cvtColor(bgr_image, cv2.COLOR_BGR2HSV)
    gray = cv2.cvtColor(bgr_image, cv2.COLOR_BGR2GRAY)
    page = detect_page_mask(bgr_image)

    kernel = np.ones((3, 3), np.uint8)

    # ── 1. Elementos de color (puerta=azul, mueble=rojo, vano=verde) ──
    color_masks = {}
    colored_union = np.zeros(bgr_image.shape[:2], dtype=np.uint8)
    for elem_type, cfg in COLOR_MAP.items():
        if elem_type == 'pared':
            continue
        combined = np.zeros(bgr_image.shape[:2], dtype=np.uint8)
        for low, high in cfg['hsv_ranges']:
            low = (low[0], prefs['sat_min'], low[2])
            combined = cv2.bitwise_or(
                combined, cv2.inRange(hsv, np.array(low), np.array(high)),
            )
        if page is not None:
            combined = cv2.bitwise_and(combined, page)
        combined = cv2.morphologyEx(combined, cv2.MORPH_CLOSE, kernel, iterations=1)
        combined = cv2.morphologyEx(combined, cv2.MORPH_OPEN, kernel, iterations=1)
        combined = denoise(combined)
        color_masks[elem_type] = combined
        colored_union = cv2.bitwise_or(colored_union, combined)

    # ── 1b. Rescate por dominancia de canal ──────────────────────
    # Tinta de baja saturación (esferos pálidos) o tonos fuera de los rangos
    # HSV fijos no pasa el inRange y desaparece en silencio. Para lo que
    # quedó SIN clasificar, se prueba una segunda vía: si es tinta (más
    # oscura que el papel local) y tiene algo de color (no es gris/negro,
    # eso es pared), el canal BGR dominante indica la familia de color.
    fallback = _channel_dominance_fallback(bgr_image, gray, page, colored_union)
    for elem_type, fb in fallback.items():
        fb = cv2.bitwise_and(fb, cv2.bitwise_not(color_masks[elem_type]))
        if cv2.countNonZero(fb) < 20:
            continue
        merged = cv2.bitwise_or(color_masks[elem_type], fb)
        merged = cv2.morphologyEx(merged, cv2.MORPH_CLOSE, kernel, iterations=1)
        color_masks[elem_type] = denoise(merged)
        colored_union = cv2.bitwise_or(colored_union, fb)

    # dilatar el color para que su borde no se cuele en las paredes
    colored_dil = cv2.dilate(colored_union, np.ones((9, 9), np.uint8))

    # ── 2. Paredes (lápiz negro/gris) con filtro de grosor ──
    wall_binary = _detect_walls(gray, hsv, page, colored_dil, radius_factor=prefs['radius'])
    wall_binary = cv2.morphologyEx(wall_binary, cv2.MORPH_CLOSE, kernel, iterations=1)
    wall_binary = denoise(wall_binary)

    # ── 3. Ensamblar resultado ──
    masks = {}
    for elem_type, cfg in COLOR_MAP.items():
        if elem_type == 'pared':
            binary = wall_binary
        else:
            binary = color_masks[elem_type]
        masks[elem_type] = {
            'binary': binary,
            'stroke': cfg['stroke'],
            'stroke_width': cfg['stroke_width'],
            'sr_type': elem_type,
        }

    return masks


def _content_bbox(ref_binary, full_shape, pad_frac=0.008):
    """Bounding box del contenido (las paredes) con padding, para recortar
    los márgenes en blanco y que el plano llene la página.

    Robusto a fragmentos espurios lejanos (paredes tenues sueltas en un borde):
    parte del componente conectado más grande y solo suma los componentes
    cercanos (que forman parte del edificio), descartando los aislados. Así el
    recorte queda pegado al edificio y no deja un hueco vacío al costado."""
    if ref_binary is None or cv2.countNonZero(ref_binary) == 0:
        return None
    h, w = full_shape
    ys, xs = np.where(ref_binary > 0)
    x1, y1, x2, y2 = int(xs.min()), int(ys.min()), int(xs.max()), int(ys.max())
    pad = int(min(h, w) * pad_frac)
    x1 = max(0, int(x1) - pad)
    y1 = max(0, int(y1) - pad)
    x2 = min(w, int(x2) + pad)
    y2 = min(h, int(y2) + pad)
    if x2 - x1 < 10 or y2 - y1 < 10:
        return None
    return (x1, y1, x2, y2)


def resize_mask_to_canvas(mask_dict, target_w=1320, target_h=864):
    """Redimensiona todas las máscaras al canvas oficio.

    Antes de escalar, recorta todas las máscaras al bounding box de las
    paredes (el edificio): así el plano LLENA la página en vez de quedar
    chico con mucho blanco alrededor, y de paso descarta artefactos que
    queden fuera del edificio (logo, margen impreso). Si no hay paredes,
    usa la unión de todo el contenido."""
    # referencia de recorte: paredes; si no hay, unión de todo
    ref = mask_dict.get('pared', {}).get('binary')
    if ref is None or cv2.countNonZero(ref) == 0:
        ref = None
        for data in mask_dict.values():
            b = data['binary']
            ref = b.copy() if ref is None else cv2.bitwise_or(ref, b)

    crop = None
    if ref is not None:
        any_binary = next(iter(mask_dict.values()))['binary']
        crop = _content_bbox(ref, any_binary.shape)

    result = {}
    for elem_type, data in mask_dict.items():
        b = data['binary']
        if crop is not None:
            x1, y1, x2, y2 = crop
            b = b[y1:y2, x1:x2]
        binary, info = resize_to_canvas(b, target_w, target_h)
        result[elem_type] = {
            'binary': binary,
            'stroke': data['stroke'],
            'stroke_width': data['stroke_width'],
            'sr_type': data['sr_type'],
            'scale_info': info,
        }
    return result
