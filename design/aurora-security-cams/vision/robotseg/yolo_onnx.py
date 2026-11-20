"""Run the one-class Epson segmentation model (models/epson_t6_seg.onnx, a YOLO11n-seg) with onnxruntime and
numpy only, as on the Pi 5: no torch, no ultralytics.

    from yolo_onnx import EpsonSeg
    seg = EpsonSeg()                                  # default model, 1 thread
    mask = seg(bgr_crop)                              # uint8 0/255, same size as the crop

The model takes a 448 x 256 letterboxed image. Overhead 1's robot zone (1350 x 700 px at 1080p) maps to
448 x 232 in it.
"""
import os

import cv2
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
DEFAULT = os.path.join(HERE, "models", "epson_t6_seg.onnx")


def _sigmoid(x):
    return 1.0 / (1.0 + np.exp(-x))


class EpsonSeg:
    def __init__(self, path=DEFAULT, threads=1, conf=0.25, iou=0.6, mask_thr=0.5):
        import onnxruntime as ort
        so = ort.SessionOptions()
        so.intra_op_num_threads = threads
        so.inter_op_num_threads = 1
        self.s = ort.InferenceSession(path, so, providers=["CPUExecutionProvider"])
        self.inp = self.s.get_inputs()[0]
        self.h, self.w = self.inp.shape[2], self.inp.shape[3]
        self.conf, self.iou, self.mask_thr = conf, iou, mask_thr

    def letterbox(self, img):
        h, w = img.shape[:2]
        r = min(self.w / w, self.h / h)
        nw, nh = int(round(w * r)), int(round(h * r))
        px, py = (self.w - nw) // 2, (self.h - nh) // 2
        canvas = np.full((self.h, self.w, 3), 114, np.uint8)
        canvas[py:py + nh, px:px + nw] = cv2.resize(img, (nw, nh), interpolation=cv2.INTER_AREA)
        return canvas, r, px, py, nw, nh

    def raw(self, img):
        """(instance masks at model resolution [n, h, w] float 0..1, boxes, scores, letterbox params)."""
        lb, r, px, py, nw, nh = self.letterbox(img)
        x = lb[:, :, ::-1].transpose(2, 0, 1)[None].astype(np.float32) / 255.0
        out0, protos = self.s.run(None, {self.inp.name: np.ascontiguousarray(x)})
        p = out0[0].T                                   # [N, 4 + 1 + 32]
        scores = p[:, 4]
        keep = scores > self.conf
        p, scores = p[keep], scores[keep]
        if len(p) == 0:
            return np.zeros((0, self.h, self.w), np.float32), np.zeros((0, 4)), scores, (r, px, py, nw, nh)
        xywh = p[:, :4]
        boxes = np.c_[xywh[:, 0] - xywh[:, 2] / 2, xywh[:, 1] - xywh[:, 3] / 2, xywh[:, 2], xywh[:, 3]]
        idx = cv2.dnn.NMSBoxes(boxes.tolist(), scores.tolist(), self.conf, self.iou)
        idx = np.array(idx).reshape(-1)
        p, scores, boxes = p[idx], scores[idx], boxes[idx]
        pr = protos[0]                                  # [32, h/4, w/4]
        c, mh, mw = pr.shape
        m = _sigmoid(p[:, 5:] @ pr.reshape(c, -1)).reshape(-1, mh, mw)
        ms = np.stack([cv2.resize(k, (self.w, self.h), interpolation=cv2.INTER_LINEAR) for k in m])
        for k, (x0, y0, bw, bh) in enumerate(boxes):    # each mask only inside its own box
            box = np.zeros((self.h, self.w), bool)
            box[max(0, int(y0)):int(np.ceil(y0 + bh)), max(0, int(x0)):int(np.ceil(x0 + bw))] = True
            ms[k][~box] = 0
        return ms, boxes, scores, (r, px, py, nw, nh)

    def __call__(self, img):
        ms, _, _, (r, px, py, nw, nh) = self.raw(img)
        if len(ms) == 0:
            return np.zeros(img.shape[:2], np.uint8)
        m = (ms.max(axis=0)[py:py + nh, px:px + nw] > self.mask_thr).astype(np.uint8) * 255
        return cv2.resize(m, (img.shape[1], img.shape[0]), interpolation=cv2.INTER_NEAREST)
