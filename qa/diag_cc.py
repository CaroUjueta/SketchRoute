import sys, cv2, numpy as np
sys.path.insert(0, '.')
b = cv2.imread('qa/out/mask_mueble.png', cv2.IMREAD_GRAYSCALE)
# dilate slightly to connect broken outlines
k = cv2.getStructuringElement(cv2.MORPH_RECT, (5,5))
bd = cv2.dilate(b, k, 1)
n, lab, stats, cent = cv2.connectedComponentsWithStats(bd, 8)
print('components (incl bg):', n)
for i in range(1, n):
    x,y,w,h,area = stats[i]
    if area < 50: continue
    comp = (lab==i).astype(np.uint8)*255
    comp = cv2.bitwise_and(comp, b)  # original pixels in this comp
    px = cv2.countNonZero(comp)
    # border band ratio
    band = max(4, int(0.12*min(w,h)))
    inner = np.zeros_like(b)
    inner[y+band:y+h-band, x+band:x+w-band] = 1
    inner_px = cv2.countNonZero(cv2.bitwise_and(comp, comp, mask=inner))
    border_ratio = 1 - inner_px/max(px,1)
    print(f"comp{i}: bbox=({x},{y},{w},{h}) area_px={px} aspect={max(w,h)/max(min(w,h),1):.1f} border_ratio={border_ratio:.2f}")
