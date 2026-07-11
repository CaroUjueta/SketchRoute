"""Overlay de verificación: renderiza el `canvas_data` (salida del pipeline)
a una imagen PNG, para que el usuario vea qué detectó el pipeline antes de
entrar al editor (sin esto, la única señal era un mensaje de texto con
conteos). Reutiliza la misma lógica de dibujo que `qa/render.py`."""
import cv2
import numpy as np

COLORS = {  # BGR
    'pared': (60, 60, 60),
    'puerta': (210, 80, 30),
    'vano': (90, 160, 10),
    'mueble': (40, 40, 210),
    'recinto': (230, 230, 230),
}


def _color_of(obj):
    return COLORS.get(obj.get('srType'), (120, 120, 120))


def render_canvas_preview(canvas_data, doc_w=1320, doc_h=864):
    """Devuelve un array BGR (uint8) con las paredes/puertas/vanos/muebles
    detectados, sobre fondo blanco. `canvas_data` es el dict tal como lo
    arma `fabric.build_canvas_json`."""
    canvas = np.full((doc_h, doc_w, 3), 255, np.uint8)
    for o in canvas_data.get('objects', []):
        t = o.get('type')
        st = o.get('srType')
        color = _color_of(o)
        if t == 'line':
            l, tp = o['left'], o['top']
            cv2.line(
                canvas, (int(l + o['x1']), int(tp + o['y1'])),
                (int(l + o['x2']), int(tp + o['y2'])), color,
                max(2, int(o.get('strokeWidth', 2))),
            )
        elif t == 'rect':
            if st == 'recinto':
                continue  # el recinto es solo una zona lógica, no se dibuja
            x, y, w, h = int(o['left']), int(o['top']), int(o['width']), int(o['height'])
            cv2.rectangle(canvas, (x, y), (x + w, y + h), color, 2)
        elif t == 'ellipse':
            cv2.ellipse(
                canvas, (int(o['left']), int(o['top'])),
                (int(o['rx']), int(o['ry'])), 0, 0, 360, color, 2,
            )
        elif t == 'path':
            l, tp = o['left'], o['top']
            pts = [(int(l + p[1]), int(tp + p[2])) for p in o.get('path', []) if p[0] in ('M', 'L')]
            if len(pts) >= 2:
                cv2.polylines(canvas, [np.array(pts)], True, color, 2)
        elif t == 'group':
            gl, gt = o['left'], o['top']
            gw, gh = o.get('width', 0), o.get('height', 0)
            cx, cy = gl + gw / 2, gt + gh / 2
            for ch in o.get('objects', []):
                cl, ct = cx + ch.get('left', 0), cy + ch.get('top', 0)
                if 'x1' not in ch:
                    continue
                cv2.line(
                    canvas, (int(cl + ch['x1']), int(ct + ch['y1'])),
                    (int(cl + ch['x2']), int(ct + ch['y2'])), _color_of({'srType': 'vano'}),
                    max(2, int(ch.get('strokeWidth', 2))),
                )
    return canvas


def render_canvas_preview_png(canvas_data, doc_w=1320, doc_h=864):
    """Como render_canvas_preview pero ya codificado a bytes PNG."""
    img = render_canvas_preview(canvas_data, doc_w, doc_h)
    ok, buf = cv2.imencode('.png', img)
    if not ok:
        raise RuntimeError('No se pudo codificar el overlay a PNG')
    return buf.tobytes()
