import os
import sys

import cv2
import numpy as np


def order_points(pts):
    pts = np.array(pts, dtype="float32")
    rect = np.zeros((4, 2), dtype="float32")
    s = pts.sum(axis=1)
    rect[0] = pts[np.argmin(s)]
    rect[2] = pts[np.argmax(s)]
    diff = np.diff(pts, axis=1)
    rect[1] = pts[np.argmin(diff)]
    rect[3] = pts[np.argmax(diff)]
    return rect

def grabcut_quad(img, inset=0.04, proc_size=900):
    h, w = img.shape[:2]
    scale = proc_size / max(h, w)
    small = cv2.resize(img, (int(w * scale), int(h * scale)))
    sh, sw = small.shape[:2]

    mask = np.zeros((sh, sw), np.uint8)
    bgd = np.zeros((1, 65), np.float64)
    fgd = np.zeros((1, 65), np.float64)
    rect = (int(sw * inset), int(sh * inset), int(sw * (1 - 2 * inset)), int(sh * (1 - 2 * inset)))
    cv2.grabCut(small, mask, rect, bgd, fgd, 5, cv2.GC_INIT_WITH_RECT)
    mask2 = np.where((mask == 2) | (mask == 0), 0, 1).astype('uint8')
    mask2 = cv2.morphologyEx(mask2, cv2.MORPH_CLOSE, np.ones((17, 17), np.uint8))
    mask2 = cv2.morphologyEx(mask2, cv2.MORPH_OPEN, np.ones((11, 11), np.uint8))

    contours, _ = cv2.findContours(mask2, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    if not contours:
        return None
    c = max(contours, key=cv2.contourArea)
    peri = cv2.arcLength(c, True)
    approx = None
    for eps in [0.01, 0.015, 0.02, 0.025, 0.03, 0.04, 0.05, 0.06]:
        a = cv2.approxPolyDP(c, eps * peri, True)
        if len(a) == 4 and cv2.isContourConvex(a):
            approx = a
            break
    if approx is None:
        rect_ = cv2.minAreaRect(c)
        approx = cv2.boxPoints(rect_).reshape(4, 1, 2).astype(np.int32)

    return approx.reshape(4, 2).astype("float32") / scale

def warp(img, rect):
    (tl, tr, br, bl) = rect
    wA = np.linalg.norm(br - bl)
    wB = np.linalg.norm(tr - tl)
    maxW = int(max(wA, wB))
    hA = np.linalg.norm(tr - br)
    hB = np.linalg.norm(tl - bl)
    maxH = int(max(hA, hB))
    dst = np.array([[0, 0], [maxW - 1, 0], [maxW - 1, maxH - 1], [0, maxH - 1]], dtype="float32")
    M = cv2.getPerspectiveTransform(rect, dst)
    return cv2.warpPerspective(img, M, (maxW, maxH))

def background_reference(img, margin_frac=0.03):
    h, w = img.shape[:2]
    mh, mw = int(h * margin_frac), int(w * margin_frac)
    patches = [
        img[0:mh, 0:mw], img[0:mh, w - mw:w],
        img[h - mh:h, 0:mw], img[h - mh:h, w - mw:w],
    ]
    samples = np.vstack([p.reshape(-1, 3) for p in patches]).astype(np.float32)
    return np.median(samples, axis=0)  # BGR

def corner_patch(warped, corner_idx, frac):
    h, w = warped.shape[:2]
    ph, pw = max(6, int(h * frac)), max(6, int(w * frac))
    if corner_idx == 0:
        return warped[0:ph, 0:pw]
    if corner_idx == 1:
        return warped[0:ph, w - pw:w]
    if corner_idx == 2:
        return warped[h - ph:h, w - pw:w]
    return warped[h - ph:h, 0:pw]

def is_flat_bright_patch(patch, std_thresh=11, bright_thresh=205):
    """Detects flat, bright, low-texture regions (printed labels, paper tags,
    blown highlights on the floor) that a painted canvas corner rarely produces,
    regardless of what the surrounding background color is."""
    gray = cv2.cvtColor(patch, cv2.COLOR_BGR2GRAY)
    return gray.std() < std_thresh and gray.mean() > bright_thresh

def refine_corners(img, rect, bg_ref, frac=0.02, dist_thresh=45, step=0.025, max_iters=60):
    centroid = rect.mean(axis=0)
    work = rect.copy()
    history = []
    dists = []
    for it in range(max_iters):
        warped = warp(img, work)
        flags = []
        dists = []
        for i in range(4):
            patch = corner_patch(warped, i, frac)
            patch_f = patch.reshape(-1, 3).astype(np.float32)
            d = np.linalg.norm(patch_f.mean(axis=0) - bg_ref)
            dists.append(d)
            flags.append(d < dist_thresh or is_flat_bright_patch(patch))
        history.append(dists)
        if not any(flags):
            return work, warped, True, it, dists
        for i in range(4):
            if flags[i]:
                work[i] = work[i] + step * (centroid - work[i])
    return work, warp(img, work), False, max_iters, dists

def process(path, outdir, debugdir=None):
    name = os.path.splitext(os.path.basename(path))[0]
    img = cv2.imread(path)
    if img is None:
        print(f"[{name}] could not read file")
        return

    quad = grabcut_quad(img)
    if quad is None:
        print(f"[{name}] NO QUAD FOUND - needs manual crop")
        return

    rect = order_points(quad)
    bg_ref = background_reference(img)
    final_rect, warped, ok, iters, dists = refine_corners(img, rect, bg_ref)

    outpath = os.path.join(outdir, f"{name}_corrected.jpg")
    cv2.imwrite(outpath, warped, [cv2.IMWRITE_JPEG_QUALITY, 95])

    status = "clean" if ok else "COULD NOT FULLY CLEAR - please review"
    print(f"[{name}] -> {outpath}  size={warped.shape[1]}x{warped.shape[0]}  "
          f"corner_bg_dist={[round(d,1) for d in dists]}  refine_iters={iters}  status={status}")

    if debugdir:
        vis = img.copy()
        h, w = img.shape[:2]
        pts = final_rect.astype(int)
        cv2.polylines(vis, [pts], True, (0, 0, 255), 6)
        for p in pts:
            cv2.circle(vis, tuple(p), 14, (0, 255, 0), -1)
        small_vis = cv2.resize(vis, (w // 4, h // 4))
        cv2.imwrite(os.path.join(debugdir, f"{name}_final_quad.jpg"), small_vis)

    return outpath

if __name__ == "__main__":
    indir = sys.argv[1]
    outdir = sys.argv[2]
    debugdir = sys.argv[3] if len(sys.argv) > 3 else None
    os.makedirs(outdir, exist_ok=True)
    if debugdir:
        os.makedirs(debugdir, exist_ok=True)
    for f in sorted(os.listdir(indir)):
        if f.lower().endswith(('.jpg', '.jpeg', '.png')):
            process(os.path.join(indir, f), outdir, debugdir)
