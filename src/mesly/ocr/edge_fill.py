import numpy as np

try:
    import cv2
except Exception:
    cv2 = None

try:
    import pyopencl as cl
except Exception:
    cl = None


_KERNEL = r"""
__kernel void sobel_threshold(
    __global const uchar *src,
    __global uchar *dst,
    const int w,
    const int h,
    const int thresh
) {
    int x = get_global_id(0);
    int y = get_global_id(1);
    if (x <= 0 || y <= 0 || x >= w - 1 || y >= h - 1) {
        if (x < w && y < h) dst[y * w + x] = 0;
        return;
    }
    int gx =
        -1 * src[(y - 1) * w + (x - 1)] + 1 * src[(y - 1) * w + (x + 1)] +
        -2 * src[(y) * w + (x - 1)]     + 2 * src[(y) * w + (x + 1)] +
        -1 * src[(y + 1) * w + (x - 1)] + 1 * src[(y + 1) * w + (x + 1)];
    int gy =
        -1 * src[(y - 1) * w + (x - 1)] + -2 * src[(y - 1) * w + x] + -1 * src[(y - 1) * w + (x + 1)] +
         1 * src[(y + 1) * w + (x - 1)] +  2 * src[(y + 1) * w + x] +  1 * src[(y + 1) * w + (x + 1)];
    int mag = abs(gx) + abs(gy);
    dst[y * w + x] = mag > thresh ? 255 : 0;
}

__kernel void dilate3(
    __global const uchar *src,
    __global uchar *dst,
    const int w,
    const int h
) {
    int x = get_global_id(0);
    int y = get_global_id(1);
    if (x >= w || y >= h) return;
    uchar v = 0;
    for (int dy = -1; dy <= 1; dy++) {
        int yy = y + dy;
        if (yy < 0 || yy >= h) continue;
        for (int dx = -1; dx <= 1; dx++) {
            int xx = x + dx;
            if (xx < 0 || xx >= w) continue;
            if (src[yy * w + xx]) { v = 255; }
        }
    }
    dst[y * w + x] = v;
}
"""


class OpenCLEdgeFiller:
    def __init__(self):
        self.available = False
        self.ctx = None
        self.queue = None
        self.program = None
        if cl is None or cv2 is None:
            return
        try:
            self.ctx = cl.create_some_context(interactive=False)
            self.queue = cl.CommandQueue(self.ctx)
            self.program = cl.Program(self.ctx, _KERNEL).build()
            self.available = True
        except Exception:
            self.available = False

    def fill(self, gray: np.ndarray, thresh: int = 80) -> np.ndarray:
        if not self.available:
            return gray
        if gray.ndim != 2:
            return gray
        h, w = gray.shape
        if h < 3 or w < 3:
            return gray
        src = np.ascontiguousarray(gray, dtype=np.uint8)
        edges = np.empty_like(src)
        dil = np.empty_like(src)
        mf = cl.mem_flags
        src_buf = cl.Buffer(self.ctx, mf.READ_ONLY | mf.COPY_HOST_PTR, hostbuf=src)
        edge_buf = cl.Buffer(self.ctx, mf.READ_WRITE, edges.nbytes)
        dil_buf = cl.Buffer(self.ctx, mf.READ_WRITE, dil.nbytes)
        gsize = (w, h)
        self.program.sobel_threshold(
            self.queue, gsize, None, src_buf, edge_buf,
            np.int32(w), np.int32(h), np.int32(thresh))
        self.program.dilate3(self.queue, gsize, None, edge_buf, dil_buf, np.int32(w), np.int32(h))
        self.program.dilate3(self.queue, gsize, None, dil_buf, edge_buf, np.int32(w), np.int32(h))
        cl.enqueue_copy(self.queue, dil, edge_buf).wait()
        contours, _ = cv2.findContours(dil, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        filled = np.zeros_like(dil)
        if contours:
            cv2.drawContours(filled, contours, -1, 255, thickness=cv2.FILLED)
        ys, xs = np.where(filled > 0)
        if xs.size == 0 or ys.size == 0:
            return filled
        pad = 4
        x0 = max(0, int(xs.min()) - pad)
        y0 = max(0, int(ys.min()) - pad)
        x1 = min(w, int(xs.max()) + 1 + pad)
        y1 = min(h, int(ys.max()) + 1 + pad)
        if x1 <= x0 or y1 <= y0:
            return filled
        return filled[y0:y1, x0:x1]
