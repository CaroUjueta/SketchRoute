"""Generación de JSON compatible con Fabric.js 5.x.

Convierte segmentos de pared, puertas y muebles en objetos
Fabric.js que el editor web puede cargar mediante canvas.loadFromJSON().

Todo el dibujo se renderiza en blanco y negro (stroke #000000)
excepto las paredes (stroke #777777). Los únicos elementos que
pueden tener color son las flechas de ruta y las canecas,
añadidas posteriormente en el editor.

Objetos Fabric.js por tipo:
- Paredes: Line, strokeWidth 8
- Puertas: Path (rectángulo outline del vano), strokeWidth 3
- Vanos: Group (jambas + línea punteada), strokeWidth 6/1.5
- Muebles: Line, strokeWidth 2
- Recintos: Rect semitransparente como zona"""

import math


def _make_line_obj(x1_rel, y1_rel, x2_rel, y2_rel, left, top,
                     stroke, stroke_width, sr_type):
    w = abs(x2_rel - x1_rel)
    h = abs(y2_rel - y1_rel)
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
    left = float(min(ax1, ax2))
    top = float(min(ay1, ay2))
    x1 = float(ax1 - left)
    y1 = float(ay1 - top)
    x2 = float(ax2 - left)
    y2 = float(ay2 - top)
    return _make_line_obj(x1, y1, x2, y2, left, top, color, stroke_width, sr_type)


def _make_door(x1, y1, x2, y2, color='#000000', stroke_width=3):
    """Genera un rectángulo outline que marca el vano de la puerta.

    El segmento (x1,y1)-(x2,y2) define la hoja de la puerta.
    Se dibuja un rectángulo con relleno blanco y borde negro,
    centrado en el muro, con la dimensión perpendicular igual al
    grosor de la pared (8 px). Así la puerta "corta" la pared
    visualmente mostrando el vano."""
    dx = x2 - x1
    dy = y2 - y1
    s = max(abs(dx), abs(dy))
    if s < 5:
        return None
    s *= 1.3

    sx = 1 if dx >= 0 else -1
    sy = 1 if dy >= 0 else -1

    if abs(dx) >= abs(dy):
        hx, hy = x1, y1 + sy * s
        ax, ay = x1 + sx * s, y1
    else:
        hx, hy = x1 + sx * s, y1
        ax, ay = x1, y1 + sy * s

    wt = 4
    ux = (hx - x1) / s * wt if s > 0 else 0
    uy = (hy - y1) / s * wt if s > 0 else 0
    mx = x1 + ux
    my = y1 + uy
    amx = ax + ux
    amy = ay + uy
    c1x, c1y = mx - ux, my - uy
    c2x, c2y = amx - ux, amy - uy
    c3x, c3y = amx + ux, amy + uy
    c4x, c4y = mx + ux, my + uy

    all_x = [c1x, c2x, c3x, c4x]
    all_y = [c1y, c2y, c3y, c4y]
    min_x = min(all_x)
    min_y = min(all_y)
    max_x = max(all_x)
    max_y = max(all_y)

    left = float(min_x)
    top = float(min_y)

    r_c1x = float(c1x - left)
    r_c1y = float(c1y - top)
    r_c2x = float(c2x - left)
    r_c2y = float(c2y - top)
    r_c3x = float(c3x - left)
    r_c3y = float(c3y - top)
    r_c4x = float(c4x - left)
    r_c4y = float(c4y - top)

    pw = float(max_x - min_x)
    ph = float(max_y - min_y)

    path_data = [
        ['M', r_c1x, r_c1y],
        ['L', r_c2x, r_c2y],
        ['L', r_c3x, r_c3y],
        ['L', r_c4x, r_c4y],
        ['Z'],
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
        'fill': '#ffffff',
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

    La posición del grupo es la esquina superior izquierda del bounding box.
    Los hijos (Line) tienen coordenadas relativas al centro del grupo."""
    dx = x2 - x1
    dy = y2 - y1
    length = math.hypot(dx, dy)
    if length < 5:
        return None

    px = -dy / length
    py = dx / length
    j = 7

    # absolute geometry points
    pts_x = [x1 + px * j, x1 - px * j, x2 + px * j, x2 - px * j, x1, x2]
    pts_y = [y1 + py * j, y1 - py * j, y2 + py * j, y2 - py * j, y1, y2]

    min_x = min(pts_x)
    max_x = max(pts_x)
    min_y = min(pts_y)
    max_y = max(pts_y)

    cx = (min_x + max_x) / 2.0
    cy = (min_y + max_y) / 2.0
    group_left = float(min_x)
    group_top = float(min_y)

    left_obj = _make_line_obj(
        px * j, py * j,
        -px * j, -py * j,
        x1 - cx, y1 - cy,
        '#000000', 6, 'vano',
    )

    right_obj = _make_line_obj(
        px * j, py * j,
        -px * j, -py * j,
        x2 - cx, y2 - cy,
        '#000000', 6, 'vano',
    )

    dcx = (x1 + x2) / 2.0 - cx
    dcy = (y1 + y2) / 2.0 - cy
    dashed_obj = _make_line_obj(
        -dx / 2.0, -dy / 2.0,
        dx / 2.0, dy / 2.0,
        dcx, dcy,
        '#000000', 1.5, 'vano',
    )
    dashed_obj['strokeDashArray'] = [5, 4]

    gw = float(max_x - min_x)
    gh = float(max_y - min_y)

    return {
        'type': 'group',
        'version': '5.3.1',
        'originX': 'left',
        'originY': 'top',
        'left': group_left,
        'top': group_top,
        'width': gw,
        'height': gh,
        'objects': [left_obj, right_obj, dashed_obj],
        'srType': 'vano',
        'srCat': 'shape',
        'selectable': True,
        'evented': True,
        'hasControls': True,
        'hasBorders': True,
    }


def circle_to_fabric(cx, cy, r, sr_type='mueble', color='#000000', stroke_width=2):
    return {
        'type': 'ellipse',
        'version': '5.3.1',
        'originX': 'center',
        'originY': 'center',
        'left': float(cx),
        'top': float(cy),
        'rx': float(r),
        'ry': float(r),
        'fill': 'transparent',
        'stroke': color,
        'strokeWidth': stroke_width,
        'srType': sr_type,
        'srCat': 'shape',
        'selectable': True,
        'evented': True,
    }


def rect_to_fabric(x, y, w, h, sr_type='mueble', color='#000000', stroke_width=2):
    return {
        'type': 'rect',
        'version': '5.3.1',
        'originX': 'left',
        'originY': 'top',
        'left': float(x),
        'top': float(y),
        'width': float(w),
        'height': float(h),
        'fill': 'transparent',
        'stroke': color,
        'strokeWidth': stroke_width,
        'srType': sr_type,
        'srCat': 'shape',
        'selectable': True,
        'evented': True,
    }


def rooms_to_fabric_zones(rooms, fill='rgba(0,0,0,0.04)',
                           stroke='#777777', stroke_width=1):
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
        'fill': '#000000',
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
