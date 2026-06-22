"""Renderiza el canvas_data del pipeline a una imagen para verificar visualmente."""
import sys
import cv2
import numpy as np
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from apps.processing.services.pipeline import ProcessingPipeline

IMG='media/croquis_cuadricula.jpeg'
OUT = Path(__file__).resolve().parent / "out"

res = ProcessingPipeline().process('media/croquis_cuadricula.jpeg')
data = res['canvas_data']
W, H = 1320, 864
canvas = np.full((H, W, 3), 255, np.uint8)

COLORS = {  # BGR
    'pared': (60, 60, 60),
    'puerta': (210, 80, 30),
    'vano': (90, 160, 10),
    'mueble': (40, 40, 210),
    'recinto': (230, 230, 230),
}

def col(o):
    return COLORS.get(o.get('srType'), (0, 0, 0))

for o in data['objects']:
    t = o['type']
    st = o.get('srType')
    if t == 'line':
        l, tp = o['left'], o['top']
        cv2.line(canvas, (int(l + o['x1']), int(tp + o['y1'])),
                 (int(l + o['x2']), int(tp + o['y2'])), col(o),
                 max(2, int(o.get('strokeWidth', 2))))
    elif t == 'rect':
        x, y, w, h = int(o['left']), int(o['top']), int(o['width']), int(o['height'])
        if st == 'recinto':
            continue  # ahora transparente (sin relleno gris)
        cv2.rectangle(canvas, (x, y), (x+w, y+h), col(o), 2)
    elif t == 'ellipse':
        cv2.ellipse(canvas, (int(o['left']), int(o['top'])),
                    (int(o['rx']), int(o['ry'])), 0, 0, 360, col(o), 2)
    elif t == 'path':
        l, tp = o['left'], o['top']
        pts = [(int(l + p[1]), int(tp + p[2])) for p in o['path'] if p[0] in ('M', 'L')]
        if len(pts) >= 2:
            cv2.polylines(canvas, [np.array(pts)], True, col(o), 2)
    elif t == 'group':
        gl, gt = o['left'], o['top']
        gw, gh = o['width'], o['height']
        cx, cy = gl + gw / 2, gt + gh / 2
        for ch in o['objects']:
            cl, ct = cx + ch['left'], cy + ch['top']
            cv2.line(canvas, (int(cl + ch['x1']), int(ct + ch['y1'])),
                     (int(cl + ch['x2']), int(ct + ch['y2'])), col({'srType': 'vano'}),
                     max(2, int(ch.get('strokeWidth', 2))))

cv2.imwrite(str(OUT / "RESULT.png"), canvas)
print("walls:", res['walls'], "doors:", res['doors'], "furniture:", res['furniture'], "rooms:", res['rooms'])
print("saved RESULT.png")
