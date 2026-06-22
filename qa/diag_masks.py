import sys, cv2, numpy as np
from pathlib import Path
sys.path.insert(0, '.')
from apps.processing.services import preprocessing
from apps.processing.services.pipeline import ProcessingPipeline

OUT = Path('qa/out')
img = cv2.imread('media/croquis_cuadricula.jpeg')
img = preprocessing.correct_perspective(img)
print('rotation: disabled')
masks = preprocessing.segment_by_color(img)
masks = preprocessing.resize_mask_to_canvas(masks, 1320, 864)
for k, v in masks.items():
    b = v['binary']
    cv2.imwrite(str(OUT / f'mask_{k}.png'), b)
    print(k, 'nonzero=', cv2.countNonZero(b))
