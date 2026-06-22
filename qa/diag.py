"""Diagnóstico del pipeline sobre una imagen real de croquis."""
import sys
import cv2
import numpy as np
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from apps.processing.services import preprocessing, lines
from apps.processing.services.pipeline import ProcessingPipeline

IMG = r"C:\Users\Julian\.claude\image-cache\16d78e5e-5fa8-4c12-88f9-4a5c23f31f99\2.png"
OUT = Path(__file__).resolve().parent / "out"
OUT.mkdir(exist_ok=True)

img = cv2.imread(IMG)
print("input shape:", img.shape)

# perspectiva
corr = preprocessing.correct_perspective(img)
print("after perspective:", corr.shape)
cv2.imwrite(str(OUT / "01_perspective.png"), corr)

# segmentacion
masks = preprocessing.segment_by_color(corr)
for k, v in masks.items():
    nz = cv2.countNonZero(v['binary'])
    print(f"mask {k}: {nz} px")
    cv2.imwrite(str(OUT / f"02_mask_{k}.png"), v['binary'])

# resize
rmasks = preprocessing.resize_mask_to_canvas(masks, 1320, 864)
for k, v in rmasks.items():
    nz = cv2.countNonZero(v['binary'])
    print(f"resized mask {k}: {nz} px")
    cv2.imwrite(str(OUT / f"03_rmask_{k}.png"), v['binary'])

# pipeline completo
p = ProcessingPipeline()
res = p.process(IMG)
print("\n=== PIPELINE RESULT ===")
print("success:", res['success'])
print("walls:", res['walls'], "doors:", res['doors'], "furniture:", res['furniture'], "rooms:", res['rooms'])
print("error:", res['error'])
import json
print("debug:", json.dumps(res['debug'], indent=2, default=str))
