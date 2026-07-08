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
    # La puerta se dibuja del tamaño de su segmento (el hueco real del muro);
    # no se agranda para que no sobresalga de la pared ni cruce las uniones.

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

    # dirección del vano para routing
    sr_dir = 'h' if abs(dx) >= abs(dy) else 'v'
    gap_cx = (x1 + ax) / 2.0
    gap_cy = (y1 + ay) / 2.0

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
        'srGapX': gap_cx,
        'srGapY': gap_cy,
        'srDir': sr_dir,
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

    gap_cx = (x1 + x2) / 2.0
    gap_cy = (y1 + y2) / 2.0
    sr_dir = 'h' if abs(dx) >= abs(dy) else 'v'

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
        'srGapX': gap_cx,
        'srGapY': gap_cy,
        'srDir': sr_dir,
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


def rooms_to_fabric_zones(rooms, fill='transparent',
                           stroke='transparent', stroke_width=0):
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
            # 'recinto' = fondo decorativo de una habitación detectada: es
            # TRANSITABLE (a diferencia de 'zona', que el editor trata como
            # obstáculo). No es interactivo para no estorbar al corregir
            # paredes/puertas encima.
            'srType': 'recinto',
            'srCat': 'shape',
            'selectable': False,
            'evented': False,
            'hasControls': False,
            'hasBorders': False,
        }
        objects.append(obj)

    return objects


def _obj_bounds(o):
    """(x1,y1,x2,y2) del objeto en coordenadas de canvas."""
    t = o['type']
    l = o.get('left', 0.0)
    tp = o.get('top', 0.0)
    if t == 'ellipse':  # originX/originY = center
        rx, ry = o.get('rx', 0), o.get('ry', 0)
        return (l - rx, tp - ry, l + rx, tp + ry)
    w = o.get('width', 0)
    h = o.get('height', 0)
    return (l, tp, l + w, tp + h)


def _scale_obj(o, s):
    """Escala la geometría interna de un objeto por el factor s (la posición
    left/top la ajusta el llamador). No toca strokeWidth (grosor constante)."""
    t = o['type']
    for k in ('width', 'height', 'rx', 'ry', 'x1', 'y1', 'x2', 'y2'):
        if k in o and isinstance(o[k], (int, float)):
            o[k] *= s
    if t == 'path' and isinstance(o.get('path'), list):
        for cmd in o['path']:
            for i in range(1, len(cmd)):
                if isinstance(cmd[i], (int, float)):
                    cmd[i] *= s
    if t == 'group' and isinstance(o.get('objects'), list):
        for ch in o['objects']:
            # los hijos tienen coords relativas al centro del grupo
            for k in ('left', 'top'):
                if isinstance(ch.get(k), (int, float)):
                    ch[k] *= s
            _scale_obj(ch, s)


def refit_objects(objects, doc_w, doc_h, top_band=78, margin=26):
    """Re-encuadra todos los objetos para que el plano LLENE el lienzo
    (dejando una banda arriba para el título y un margen). Opera sobre los
    objetos finales y limpios, así que es inmune al ruido de las máscaras.
    Escala uniforme (sin deformar) y centra en el área disponible."""
    if not objects:
        return objects
    bxs = [_obj_bounds(o) for o in objects]
    ox1 = min(b[0] for b in bxs)
    oy1 = min(b[1] for b in bxs)
    ox2 = max(b[2] for b in bxs)
    oy2 = max(b[3] for b in bxs)
    bw, bh = ox2 - ox1, oy2 - oy1
    if bw < 1 or bh < 1:
        return objects

    avail_w = doc_w - 2 * margin
    avail_h = doc_h - top_band - margin
    s = min(avail_w / bw, avail_h / bh)
    # centrar el contenido escalado en el área disponible
    nx1 = margin + (avail_w - bw * s) / 2
    ny1 = top_band + (avail_h - bh * s) / 2

    for o in objects:
        o['left'] = (o.get('left', 0.0) - ox1) * s + nx1
        o['top'] = (o.get('top', 0.0) - oy1) * s + ny1
        # srGapX/srGapY (centro del hueco de la puerta) es el DESTINO de las
        # rutas de evacuación. Está en coordenadas pre-reencuadre, así que hay
        # que mapearlo con la misma transformación o las flechas apuntarían a
        # un punto desplazado y no llegarían a la salida.
        if isinstance(o.get('srGapX'), (int, float)):
            o['srGapX'] = (o['srGapX'] - ox1) * s + nx1
        if isinstance(o.get('srGapY'), (int, float)):
            o['srGapY'] = (o['srGapY'] - oy1) * s + ny1
        _scale_obj(o, s)
    return objects


def build_canvas_json(objects, extra_objects=None, doc_w=1320, doc_h=864):
    # NO se agrega título aquí: el editor (ensureHeader/titleFor) coloca el
    # título correcto con el nombre de la droguería + la ruta. Si lo pusiéramos
    # acá, el editor no lo reemplazaría y quedaría "PLANO VECTORIZADO".
    all_objects = list(objects)
    # re-encuadrar para que el plano llene el lienzo (deja banda para el título)
    refit_objects(all_objects, doc_w, doc_h)

    return {
        'version': '5.3.1',
        'objects': all_objects,
        'background': '#ffffff',
    }
