import cv2
import numpy as np


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
    cleaned = cv2.morphologyEx(binary, cv2.MORPH_CLOSE, kernel, iterations=1)
    cleaned = cv2.morphologyEx(cleaned, cv2.MORPH_OPEN, kernel, iterations=1)

    n_labels, labels, stats, _ = cv2.connectedComponentsWithStats(cleaned, connectivity=8)
    min_area = 50
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
        'stroke': '#1f2937',
        'stroke_width': 8,
    },
    'puerta': {
        'color': (200, 130, 20),
        'hsv_ranges': [
            ((90, 50, 50), (140, 255, 255)),   # azul
        ],
        'stroke': '#1d4ed8',
        'stroke_width': 3,
    },
    'mueble': {
        'color': (50, 50, 200),
        'hsv_ranges': [
            ((0, 60, 60), (12, 255, 255)),     # rojo
            ((168, 60, 60), (180, 255, 255)),  # rojo (HSV envuelve)
        ],
        'stroke': '#dc2626',
        'stroke_width': 2,
    },
    'vano': {
        'color': (50, 180, 50),
        'hsv_ranges': [
            ((35, 50, 50), (85, 255, 255)),    # verde
        ],
        'stroke': '#059669',
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
    """Redimensiona todas las máscaras al canvas oficio."""
    result = {}
    for elem_type, data in mask_dict.items():
        binary, info = resize_to_canvas(data['binary'], target_w, target_h)
        result[elem_type] = {
            'binary': binary,
            'stroke': data['stroke'],
            'stroke_width': data['stroke_width'],
            'sr_type': data['sr_type'],
            'scale_info': info,
        }
    return result
