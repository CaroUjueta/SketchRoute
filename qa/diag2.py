"""Inspeccionar valores HSV del dibujo dentro de la hoja."""
import sys
import cv2
import numpy as np
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from apps.processing.services import preprocessing

IMG = r"C:\Users\Julian\.claude\image-cache\16d78e5e-5fa8-4c12-88f9-4a5c23f31f99\2.png"
OUT = Path(__file__).resolve().parent / "out"

img = cv2.imread(IMG)
page = preprocessing.detect_page_mask(img)
cv2.imwrite(str(OUT / "page_mask.png"), page if page is not None else np.zeros(img.shape[:2], np.uint8))
print("page px:", 0 if page is None else cv2.countNonZero(page))

hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)
gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)

inside = page > 0
V = hsv[:, :, 2][inside]
S = hsv[:, :, 1][inside]
print("inside page V percentiles:", np.percentile(V, [1, 5, 25, 50, 75, 95]))
print("inside page S percentiles:", np.percentile(S, [1, 5, 25, 50, 75, 95]))

# pixeles oscuros dentro de la hoja (candidatos a tinta negra)
dark = inside & (gray < 150)
print("dark (<150) inside page:", int(np.sum(dark)))
for thr in (90, 110, 130, 150, 170):
    print(f"  gray<{thr}: {int(np.sum(inside & (gray < thr)))} px")

# guardar visual de tinta oscura
ink = np.zeros(img.shape[:2], np.uint8)
ink[inside & (gray < 150)] = 255
cv2.imwrite(str(OUT / "ink_lt150.png"), ink)
