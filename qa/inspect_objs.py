import sys
sys.path.insert(0, '.')
from apps.processing.services.pipeline import ProcessingPipeline

res = ProcessingPipeline().process('media/croquis_cuadricula.jpeg')
print('walls:', res['walls'], 'doors:', res['doors'], 'furniture:', res['furniture'], 'rooms:', res['rooms'])
from collections import Counter
objs = res['canvas_data']['objects']
c = Counter(o.get('srType') for o in objs)
print('object counts:', dict(c))
print('\n--- por tipo, bounding boxes ---')
for o in objs:
    st = o.get('srType')
    t = o['type']
    if t == 'line':
        bb = (round(o['left']), round(o['top']), round(o['left']+o['width']), round(o['top']+o['height']))
    elif t in ('rect',):
        bb = (round(o['left']), round(o['top']), round(o['left']+o['width']), round(o['top']+o['height']))
    else:
        bb = (round(o.get('left',0)), round(o.get('top',0)), round(o.get('width',0)), round(o.get('height',0)))
    print(f"{st:10s} {t:8s} bbox={bb}")
