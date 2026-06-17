"""Generación de JSON compatible con Fabric.js 5.x.

Convierte segmentos de pared, puertas y muebles en objetos
Fabric.js que el editor web puede cargar mediante canvas.loadFromJSON().

Cada tipo de elemento tiene su propio color y objeto Fabric.js:
- Paredes (negro): Line, stroke #1f2937, strokeWidth 8
- Puertas (azul): Path (línea + arco), stroke #1d4ed8, strokeWidth 3
- Vanos (verde): Group (jambas + línea punteada), stroke #374151
- Muebles (rojo): Line, stroke #dc2626, strokeWidth 2
- Recintos: Rect semitransparente como zona"""

import math


def _make_line_obj(x1_rel, y1_rel, x2_rel, y2_rel, left, top,
                     stroke, stroke_width, sr_type):
    """Crea un objeto dict Fabric.js Line."""
    w = max(abs(x2_rel - x1_rel), stroke_width)
    h = max(abs(y2_rel - y1_rel), stroke_width)
    return {
        'type': 'line',
        'version': '5.3.1',
        'originX': 'left',
        'originY': 'top',
        'left': float(left),
        'top': float(top),
        'width': float(w),
        'height': float(h),
        'fill': 'rgb(0,0,0)',
        'stroke': stroke,
        'strokeWidth': stroke_width,
        'strokeLineCap': 'round',
        'strokeUniform': True,
        'x1': float(x1_rel),
        'y1': float(y1_rel),
        'x2': float(x2_rel),
        'y2': float(y2_rel),
        'srType': sr_type,
        'srCat': 'shape',
        'selectable': True,
        'evented': True,
        'hasControls': True,
        'hasBorders': True,
    }


def segments_to_fabric_lines(segments, sr_type='pared', color='#1f2937',
                              stroke_width=8):
    """Convierte segmentos en objetos Fabric.js.

    Para paredes y muebles: genera Line.
    Para puertas (sr_type='puerta'): genera Path con arco.
    Para vanos (sr_type='vano'): genera Group con jambas + línea punteada."""
    objects = []
    for seg in segments:
        ax1, ay1, ax2, ay2 = [float(v) for v in seg]

        if abs(ax2 - ax1) < 1 and abs(ay2 - ay1) < 1:
            continue

        if sr_type == 'puerta':
            obj = _make_door(ax1, ay1, ax2, ay2, color, stroke_width)
        elif sr_type == 'vano':
            obj = _make_vano(ax1, ay1, ax2, ay2)
        else:
            obj = _make_line(ax1, ay1, ax2, ay2, color, stroke_width, sr_type)

        if obj:
            objects.append(obj)

    return objects


def _make_line(ax1, ay1, ax2, ay2, color, stroke_width, sr_type):
    """Genera un objeto Line simple (paredes, muebles)."""
    left = float(min(ax1, ax2))
    top = float(min(ay1, ay2) - stroke_width / 2)
    x1 = float(ax1 - left)
    y1 = float(ay1 - top)
    x2 = float(ax2 - left)
    y2 = float(ay2 - top)
    return _make_line_obj(x1, y1, x2, y2, left, top, color, stroke_width, sr_type)


def _make_door(x1, y1, x2, y2, color='#1d4ed8', stroke_width=3):
    """Genera un objeto Path con la forma de puerta (línea + arco).

    Sigue la misma lógica que makeDoor() en canvas.js:
    - Si el segmento es horizontal, la hoja abre vertical.
    - Si es vertical, la hoja abre horizontal."""
    dx = x2 - x1
    dy = y2 - y1
    s = max(abs(dx), abs(dy))
    if s < 5:
        return None

    sx = 1 if dx >= 0 else -1
    sy = 1 if dy >= 0 else -1

    if abs(dx) >= abs(dy):
        # puerta horizontal: hoja abre vertical
        hx, hy = x1, y1 + sy * s
        ax, ay = x1 + sx * s, y1
        sweep = 0 if (sx * sy > 0) else 1
    else:
        # puerta vertical: hoja abre horizontal
        hx, hy = x1 + sx * s, y1
        ax, ay = x1, y1 + sy * s
        sweep = 1 if (sx * sy > 0) else 0

    all_x = [x1, hx, ax]
    all_y = [y1, hy, ay]
    min_x = min(all_x)
    min_y = min(all_y)
    max_x = max(all_x)
    max_y = max(all_y)

    left = float(min_x)
    top = float(min_y - stroke_width / 2)
    pw = float(max_x - min_x)
    ph = float(max_y - min_y + stroke_width)

    # coordenadas del path relativas a (left, top)
    r_x1 = float(x1 - left)
    r_y1 = float(y1 - top)
    r_hx = float(hx - left)
    r_hy = float(hy - top)
    r_ax = float(ax - left)
    r_ay = float(ay - top)

    path_data = [
        ['M', r_x1, r_y1],
        ['L', r_hx, r_hy],
        ['M', r_hx, r_hy],
        ['A', s, s, 0, 0, sweep, r_ax, r_ay],
    ]

    return {
        'type': 'path',
        'version': '5.3.1',
        'originX': 'left',
        'originY': 'top',
        'left': left,
        'top': top,
        'width': float(max(pw, stroke_width)),
        'height': float(max(ph, stroke_width)),
        'fill': 'transparent',
        'stroke': color,
        'strokeWidth': stroke_width,
        'strokeLineCap': 'round',
        'strokeUniform': True,
        'path': path_data,
        'srType': 'puerta',
        'srCat': 'shape',
        'selectable': True,
        'evented': True,
        'hasControls': True,
        'hasBorders': True,
    }


def _make_vano(x1, y1, x2, y2):
    """Genera un Group con dos jambas y línea punteada (vano).

    Sigue la misma lógica que makeVano() en canvas.js."""
    dx = x2 - x1
    dy = y2 - y1
    length = math.hypot(dx, dy)
    if length < 5:
        return None

    px = -dy / length
    py = dx / length
    j = 7  # media jamba

    min_x = min(x1, x2) - j
    min_y = min(y1, y2) - j
    max_x = max(x1, x2) + j
    max_y = max(y1, y2) + j

    left = float(min_x)
    top = float(min_y)
    w = float(max_x - min_x)
    h = float(max_y - min_y)

    left_obj = _make_line_obj(
        (x1 + px * j) - left, (y1 + py * j) - top,
        (x1 - px * j) - left, (y1 - py * j) - top,
        left, top, '#1f2937', 6, 'vano',
    )

    right_obj = _make_line_obj(
        (x2 + px * j) - left, (y2 + py * j) - top,
        (x2 - px * j) - left, (y2 - py * j) - top,
        left, top, '#1f2937', 6, 'vano',
    )

    dashed_obj = _make_line_obj(
        x1 - left, y1 - top,
        x2 - left, y2 - top,
        left, top, '#9ca3af', 1.5, 'vano',
    )
    dashed_obj['strokeDashArray'] = [5, 4]

    return {
        'type': 'group',
        'version': '5.3.1',
        'objects': [left_obj, right_obj, dashed_obj],
        'left': left,
        'top': top,
        'width': w,
        'height': h,
        'srType': 'vano',
        'srCat': 'shape',
        'selectable': True,
        'evented': True,
        'hasControls': True,
        'hasBorders': True,
    }


def rooms_to_fabric_zones(rooms, fill='rgba(107,114,128,0.06)',
                           stroke='#6b7280', stroke_width=1):
    objects = []
    for room in rooms:
        polygon = room['polygon']
        xs = [p[0] for p in polygon]
        ys = [p[1] for p in polygon]
        left = min(xs)
        top = min(ys)
        width = max(xs) - left
        height = max(ys) - top

        if width < 30 or height < 30:
            continue

        obj = {
            'type': 'rect',
            'version': '5.3.1',
            'originX': 'left',
            'originY': 'top',
            'left': left,
            'top': top,
            'width': width,
            'height': height,
            'fill': fill,
            'stroke': stroke,
            'strokeWidth': stroke_width,
            'srType': 'zona',
            'srCat': 'shape',
            'selectable': True,
            'evented': True,
            'hasControls': True,
            'hasBorders': True,
        }
        objects.append(obj)

    return objects


def build_canvas_json(objects, extra_objects=None, doc_w=1320, doc_h=864):
    title_obj = {
        'type': 'i-text',
        'version': '5.3.1',
        'left': doc_w / 2,
        'top': 22,
        'fontFamily': 'Syne',
        'fontSize': 38,
        'fontWeight': 'bold',
        'fill': '#111827',
        'textAlign': 'center',
        'originX': 'center',
        'originY': 'top',
        'text': 'PLANO VECTORIZADO',
        'srType': 'titulo',
        'srCat': 'title',
    }

    all_objects = list(objects)
    all_objects.append(title_obj)

    return {
        'version': '5.3.1',
        'objects': all_objects,
        'background': '#ffffff',
    }
