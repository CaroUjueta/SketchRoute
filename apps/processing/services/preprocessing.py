import cv2
import numpy as np
from sklearn.cluster import KMeans


# ── Filtros para fotos de croquis ────────────────────────────

def bilateral_filter(gray, d=9, sigma_color=75, sigma_space=75):
    """Filtro bilateral: reduce textura del papel sin borrar bordes.
    Esencial para fotos de croquis donde el grano del papel
    genera ruido de alta frecuencia."""
    return cv2.bilateralFilter(gray, d, sigma_color, sigma_space)


def difference_of_gaussians(gray, sigma1=0.5, sigma2=2.0):
    """Difference of Gaussians: extrae trazos de lápiz/pluma
    suprimiendo el fondo del papel.

    La resta de dos desenfoques gaussianos con sigma distinto
    actúa como filtro pasa-banda: conserva las frecuencias del
    trazo y elimina tanto el ruido fino (grano) como las
    variaciones lentas (sombras)."""
    blur1 = cv2.GaussianBlur(gray, (0, 0), sigma1)
    blur2 = cv2.GaussianBlur(gray, (0, 0), sigma2)
    dog = blur1 - blur2
    dog = cv2.normalize(dog, None, 0, 255, cv2.NORM_MINMAX)
    return dog.astype(np.uint8)


def sauvola_threshold(gray, window_size=31, k=0.2, r=128):
    """Binarización Sauvola para documentos con iluminación no uniforme.

    Calcula un umbral local para cada píxel basado en la media
    y desviación estándar de la ventana circundante:

        T(x,y) = m(x,y) * (1 + k * (s(x,y)/R - 1))

    donde m = media local, s = std local, k = factor de sensibilidad,
    R = rango dinámico de la std (128 para uint8).

    Para fotos de croquis con sombras, Sauvola da mucho mejor
    resultado que adaptive thresholding de OpenCV.

    Args:
        gray: imagen en escala de grises (uint8)
        window_size: tamaño de la ventana local (impar)
        k: parámetro de sensibilidad (0.2-0.5, default 0.2)
        r: rango dinámico (default 128 para imágenes de 8 bits)

    Returns:
        imagen binaria (255 = trazo, 0 = fondo)
    """
    gray = gray.astype(np.float32)
    mean = cv2.boxFilter(gray, -1, (window_size, window_size),
                         normalize=True, borderType=cv2.BORDER_REFLECT)

    sqr_mean = cv2.boxFilter(gray ** 2, -1, (window_size, window_size),
                             normalize=True, borderType=cv2.BORDER_REFLECT)
    variance = sqr_mean - mean ** 2
    variance = np.maximum(variance, 0)
    std = np.sqrt(variance)

    threshold = mean * (1.0 + k * (std / r - 1.0))
    threshold = np.clip(threshold, 0, 255)

    binary = (gray < threshold).astype(np.uint8) * 255
    return binary


def stroke_confidence_filter(binary, min_area=30, max_area_ratio=0.3):
    """Filtra componentes conectados conservando solo aquellos
    con forma de trazo (alargados, delgados).

    Calcula la "confianza de trazo" como la relación entre el
    área del componente y el área de su bounding box.  Los trazos
    ocupan poca fracción de su bounding box (son delgados);
    las sombras/manchas ocupan casi todo su bounding box.

    Args:
        binary: imagen binaria (255 = trazo)
        min_area: área mínima en píxeles
        max_area_ratio: fracción máxima del bounding box que
            debe ocupar el componente (default 0.3 = 30%)

    Returns:
        imagen binaria filtrada
    """
    n_labels, labels, stats, _ = cv2.connectedComponentsWithStats(
        binary, connectivity=8,
    )
    result = np.zeros_like(binary)
    for i in range(1, n_labels):
        x, y, w, h, area = stats[i]
        if area < min_area:
            continue
        bbox_area = w * h
        if bbox_area <= 0:
            continue
        fill_ratio = area / bbox_area
        # los trazos auténticos ocupan poca fracción de su bbox
        # (son largos y delgados).  Manchas/sombras lo llenan.
        if fill_ratio <= max_area_ratio:
            result[labels == i] = 255
    return result


def enhance_contrast(gray):
    """Aplica CLAHE para mejorar el contraste local.
    Fundamental para fotos de croquis con iluminación no uniforme."""
    clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
    return clahe.apply(gray)


def correct_perspective(image):
    """Corrige perspectiva encontrando el contorno del documento y aplicando
    transformación de homografía. Si no encuentra un cuadrilátero válido
    o si el cuadrilátero ya forma un rectángulo casi perfecto (sin
    distorsión), devuelve la imagen original."""
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    blurred = cv2.GaussianBlur(gray, (5, 5), 0)
    edged = cv2.Canny(blurred, 50, 150)

    dilated = cv2.dilate(edged, None, iterations=2)
    contours, _ = cv2.findContours(dilated, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

    if not contours:
        return image

    contours = sorted(contours, key=cv2.contourArea, reverse=True)

    for c in contours:
        peri = cv2.arcLength(c, True)
        approx = cv2.approxPolyDP(c, 0.02 * peri, True)
        if len(approx) == 4:
            pts = approx.reshape(4, 2).astype(np.float32)
            break
    else:
        return image

    # verificar si el cuadrilátero ya es casi un rectángulo
    if _is_nearly_rect(pts, angle_tol=10, aspect_tol=0.3):
        return image

    rect = _order_points(pts)
    (tl, tr, br, bl) = rect
    w = int(max(dist(bl, br), dist(tl, tr)))
    h = int(max(dist(tl, bl), dist(tr, br)))

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
        cross = abs(v1[0]*v2[1] - v1[1]*v2[0])
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


def grayscale(image, method='luminosity'):
    """Convierte a escala de grises.

    Para fotos de croquis con lápiz negro sobre papel blanco,
    el canal L de LAB o el método 'luminosity' (BT.601) da mejor
    separación que el simple promedio (CV2 default).

    Args:
        image: imagen BGR (H, W, 3)
        method: 'luminosity' (BT.601), 'lab_l' (canal L de LAB),
                o 'gray' (promedio simple)

    Returns:
        imagen en escala de grises (H, W)
    """
    if len(image.shape) != 3:
        return image

    if method == 'lab_l':
        lab = cv2.cvtColor(image, cv2.COLOR_BGR2LAB)
        return lab[:, :, 0]
    elif method == 'luminosity':
        return cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    return cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)


def binarize(gray, method='sauvola'):
    """Binariza usando Sauvola, Otsu o adaptive thresholding.

    Para fotos de croquis con iluminación no uniforme (sombras,
    reflejos), Sauvola da el mejor resultado.  Adaptive thresholding
    es el fallback.  Otsu solo para imágenes digitales limpias.

    Args:
        gray: imagen en escala de grises (uint8)
        method: 'sauvola', 'adaptive', 'otsu', o 'dog' (Difference of Gaussians)

    Returns:
        imagen binaria (255 = trazo, 0 = fondo)
    """
    blurred = cv2.GaussianBlur(gray, (3, 3), 0)

    if method == 'otsu':
        _, binary = cv2.threshold(blurred, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
    elif method == 'adaptive':
        binary = cv2.adaptiveThreshold(
            blurred, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
            cv2.THRESH_BINARY_INV, 21, 6,
        )
    elif method == 'dog':
        dog = difference_of_gaussians(gray, sigma1=0.5, sigma2=2.0)
        _, binary = cv2.threshold(dog, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
    else:  # sauvola (default)
        binary = sauvola_threshold(blurred, window_size=31, k=0.2, r=128)

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
    """Redimensiona manteniendo aspect ratio y centra en canvas oficio."""
    h, w = binary.shape
    scale = min(target_w / w, target_h / h)
    nw, nh = int(w * scale), int(h * scale)
    resized = cv2.resize(binary, (nw, nh), interpolation=cv2.INTER_NEAREST)

    canvas = np.zeros((target_h, target_w), dtype=np.uint8)
    x_off = (target_w - nw) // 2
    y_off = (target_h - nh) // 2
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

# Mapa de colores BGR → tipo de elemento
COLOR_MAP = {
    'pared': {
        'color': (30, 30, 30),
        'hsv_ranges': [
            ((0, 0, 0), (180, 120, 120)),      # grises
            ((0, 0, 0), (180, 255, 70)),       # negros
        ],
        'stroke': '#777777',
        'stroke_width': 8,
    },
    'puerta': {
        'color': (200, 130, 20),
        'hsv_ranges': [
            ((90, 50, 50), (140, 255, 255)),   # azul
        ],
        'stroke': '#000000',
        'stroke_width': 3,
    },
    'mueble': {
        'color': (50, 50, 200),
        'hsv_ranges': [
            ((0, 60, 60), (12, 255, 255)),     # rojo
            ((168, 60, 60), (180, 255, 255)),  # rojo (HSV envuelve)
        ],
        'stroke': '#000000',
        'stroke_width': 2,
    },
    'vano': {
        'color': (50, 180, 50),
        'hsv_ranges': [
            ((35, 50, 50), (85, 255, 255)),    # verde
        ],
        'stroke': '#000000',
        'stroke_width': 3,
    },
}


def segment_by_color(bgr_image):
    """Segmenta la imagen por rangos de color HSV.

    Cada píxel se clasifica como pared, puerta, mueble o fondo
    según su color. Devuelve un dict con máscaras binarias y
    configuraciones para cada tipo."""
    hsv = cv2.cvtColor(bgr_image, cv2.COLOR_BGR2HSV)

    masks = {}
    for elem_type, cfg in COLOR_MAP.items():
        combined = np.zeros(bgr_image.shape[:2], dtype=np.uint8)
        for low, high in cfg['hsv_ranges']:
            mask = cv2.inRange(hsv, np.array(low), np.array(high))
            combined = cv2.bitwise_or(combined, mask)

        # limpiar la máscara
        kernel = np.ones((3, 3), np.uint8)
        combined = cv2.morphologyEx(combined, cv2.MORPH_CLOSE, kernel, iterations=1)
        combined = cv2.morphologyEx(combined, cv2.MORPH_OPEN, kernel, iterations=1)

        masks[elem_type] = {
            'binary': denoise(combined),
            'stroke': cfg['stroke'],
            'stroke_width': cfg['stroke_width'],
            'sr_type': elem_type,
        }

    return masks


def resize_mask_to_canvas(mask_dict, target_w=1320, target_h=864):
    """Redimensiona todas las máscaras al canvas oficio (direct resize, no letterbox)."""
    result = {}
    for elem_type, data in mask_dict.items():
        m = data['binary']
        h, w = m.shape
        binary = cv2.resize(m, (target_w, target_h), interpolation=cv2.INTER_NEAREST)
        result[elem_type] = {
            'binary': binary,
            'stroke': data['stroke'],
            'stroke_width': data['stroke_width'],
            'sr_type': data['sr_type'],
            'scale_info': {
                'scale': min(target_w / w, target_h / h),
                'offset_x': 0,
                'offset_y': 0,
                'orig_w': w,
                'orig_h': h,
                'canvas_w': target_w,
                'canvas_h': target_h,
            },
        }
    return result


# ── Segmentación adaptativa por clustering ──────────────────

# Colores aproximados en BGR para los tipos de elemento (usados
# para mapear clusters de k-means a tipos semánticos).  El orden
# es importante: se asigna cada cluster al tipo cuya referencia
# esté más cerca en espacio BGR.
CLUSTER_REFERENCES = {
    'pared':  np.array([30, 30, 30]),     # negro / gris oscuro (trazos de lápiz)
    'mueble': np.array([60, 60, 200]),    # rojo (muebles)
    'puerta': np.array([180, 120, 30]),   # azul (puertas)
    'vano':   np.array([50, 180, 50]),    # verde (vanos)
}

CLUSTER_MAX_DIST = 150  # distancia máxima BGR para asignar un cluster a un tipo


def segment_by_clustering(bgr_image, n_clusters=5):
    """Segmenta la imagen agrupando colores con k-means.

    Cada píxel se clasifica en uno de `n_clusters` clusters de color.
    Luego se asigna cada cluster al tipo semántico más cercano
    (pared/mueble/puerta/vano) según distancia euclidiana en BGR
    a los colores de referencia.  Los clusters que no coinciden con
    ningún tipo se marcan como fondo.

    Esto es mucho más robusto que rangos HSV fijos porque se adapta
    a las variaciones de iluminación, balance de blancos y tono
    real de cada foto.

    Args:
        bgr_image: imagen en BGR
        n_clusters: número de clusters de color (default 5).
            Un cluster extra para fondo/líneas finas evita que
            se mezclen con paredes.

    Returns:
        dict con la misma estructura que segment_by_color():
            {tipo: {'binary': máscara, 'stroke': ..., 'stroke_width': ..., 'sr_type': ...}}
    """
    h, w = bgr_image.shape[:2]
    pixels = bgr_image.reshape(-1, 3).astype(np.float32)

    # k-means
    kmeans = KMeans(n_clusters=n_clusters, random_state=0, n_init='auto')
    labels = kmeans.fit_predict(pixels)
    centers = kmeans.cluster_centers_.astype(np.int32)

    # asignar cada cluster al tipo semántico más cercano
    type_for_cluster = {}
    for cluster_id, center in enumerate(centers):
        best_type = 'fondo'
        best_dist = float('inf')
        for elem_type, ref_color in CLUSTER_REFERENCES.items():
            dist = np.linalg.norm(center - ref_color)
            if dist < best_dist:
                best_dist = dist
                best_type = elem_type
        if best_dist > CLUSTER_MAX_DIST:
            best_type = 'fondo'
        type_for_cluster[cluster_id] = best_type

    # construir máscaras por tipo
    masks = {}
    for elem_type in CLUSTER_REFERENCES:
        mask = np.zeros(h * w, dtype=np.uint8)
        for cluster_id, assigned_type in type_for_cluster.items():
            if assigned_type == elem_type:
                mask[labels == cluster_id] = 255
        mask = mask.reshape(h, w)

        # limpiar ruido
        kernel = np.ones((3, 3), np.uint8)
        mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel, iterations=2)
        mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, kernel, iterations=1)

        # determinar stroke config basado en tipo
        cfg = COLOR_MAP.get(elem_type, {})
        masks[elem_type] = {
            'binary': mask,
            'stroke': cfg.get('stroke', '#000000'),
            'stroke_width': cfg.get('stroke_width', 3),
            'sr_type': elem_type,
        }

    return masks


def segment_by_color_or_clustering(bgr_image, use_clustering=True, n_clusters=5):
    """Elige el método de segmentación según disponibilidad.

    Primero intenta k-means (use_clustering=True). Independientemente,
    siempre detecta puertas por HSV azul y las fusiona con la máscara
    de k-means, ya que las líneas azules finas de puerta suelen perderse
    en el clustering (quedan absorbidas por el cluster de pared o fondo).
    """
    masks = None
    if use_clustering:
        try:
            masks = segment_by_clustering(bgr_image, n_clusters)
        except Exception:
            pass

    if masks is None:
        masks = segment_by_color(bgr_image)

    # Fusionar máscara HSV de puerta (azul) sobre el resultado de k-means
    hsv = cv2.cvtColor(bgr_image, cv2.COLOR_BGR2HSV)
    door_hsv = np.zeros(bgr_image.shape[:2], dtype=np.uint8)
    for low, high in COLOR_MAP.get('puerta', {}).get('hsv_ranges', []):
        mask = cv2.inRange(hsv, np.array(low), np.array(high))
        door_hsv = cv2.bitwise_or(door_hsv, mask)
    kernel = np.ones((3, 3), np.uint8)
    door_hsv = cv2.morphologyEx(door_hsv, cv2.MORPH_CLOSE, kernel, iterations=1)

    puerta_data = masks.get('puerta', {})
    existing = puerta_data.get('binary', np.zeros(bgr_image.shape[:2], dtype=np.uint8))
    cfg = COLOR_MAP.get('puerta', {})
    masks['puerta'] = {
        'binary': cv2.bitwise_or(existing, door_hsv),
        'stroke': cfg.get('stroke', '#000000'),
        'stroke_width': cfg.get('stroke_width', 3),
        'sr_type': 'puerta',
    }

    return masks


# ── Separación por ancho de trazo ────────────────────────────
# Para croquis en blanco y negro (fotos de lápiz/pluma sobre
# papel), la separación por color no funciona porque todo es
# del mismo color.  En su lugar, separamos por grosor de trazo:
#   - Trazos gruesos (>3px) → paredes
#   - Trazos finos (≤3px)   → muebles/detalles
#   - Gaps entre paredes    → puertas/vanos (detectados después)

def separate_by_stroke_width(binary, thick_threshold=4):
    """Separa una imagen binaria en máscaras de trazo grueso y fino.

    Usa distance transform para medir el ancho de cada trazo.
    Los píxeles con distancia > thick_threshold/2 son "gruesos"
    (paredes), los demás son "finos" (muebles, detalles).

    Args:
        binary: imagen binaria (255 = trazo)
        thick_threshold: ancho mínimo en píxeles para considerar
            un trazo como "grueso" (default 4px)

    Returns:
        (thick_mask, thin_mask) — ambas binarias (255/0)
    """
    dist = cv2.distanceTransform(binary, cv2.DIST_L2, 3)
    thick = (dist >= thick_threshold / 2).astype(np.uint8) * 255
    thin = cv2.bitwise_and(binary, 255 - thick)
    return thick, thin


def build_masks_from_strokes(binary, stroke_config=None):
    """Construye el dict de máscaras a partir de una binaria
    de croquis en blanco y negro, separando por ancho de trazo.

    Esto es el reemplazo de segment_by_color() para fotos de
    croquis sin color (lápiz/bolígrafo sobre papel).

    Args:
        binary: imagen binaria (255 = trazo)
        stroke_config: dict opcional con:
            thick_threshold: ancho mínimo para pared (default 4)
            thin_as_mueble: tratar trazos finos como muebles (default True)

    Returns:
        dict con misma estructura que segment_by_color():
            {'pared': {...}, 'mueble': {...}, 'puerta': {}, 'vano': {}}
    """
    cfg = stroke_config or {}
    thick_threshold = cfg.get('thick_threshold', 4)
    thin_as_mueble = cfg.get('thin_as_mueble', True)

    thick, thin = separate_by_stroke_width(binary, thick_threshold)

    masks = {}

    # paredes = trazos gruesos
    cfg_pared = COLOR_MAP.get('pared', {})
    masks['pared'] = {
        'binary': thick,
        'stroke': cfg_pared.get('stroke', '#777777'),
        'stroke_width': cfg_pared.get('stroke_width', 8),
        'sr_type': 'pared',
    }

    # muebles = trazos finos
    if thin_as_mueble:
        cfg_mueble = COLOR_MAP.get('mueble', {})
        masks['mueble'] = {
            'binary': thin,
            'stroke': cfg_mueble.get('stroke', '#000000'),
            'stroke_width': cfg_mueble.get('stroke_width', 2),
            'sr_type': 'mueble',
        }
    else:
        masks['mueble'] = {
            'binary': np.zeros_like(binary),
            'stroke': '#000000',
            'stroke_width': 2,
            'sr_type': 'mueble',
        }

    # puertas y vanos vacíos (se detectan como gaps en paredes)
    for elem in ('puerta', 'vano'):
        cfg_elem = COLOR_MAP.get(elem, {})
        masks[elem] = {
            'binary': np.zeros_like(binary),
            'stroke': cfg_elem.get('stroke', '#000000'),
            'stroke_width': cfg_elem.get('stroke_width', 3),
            'sr_type': elem,
        }

    return masks
