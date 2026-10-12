"""DINOv2 ViT-S/14 image embeddings via ONNX Runtime.

Provider order: CUDA -> DirectML -> CPU. Each provider is warmed up and checked; a
provider that fails falls through to the next one instead of silently misbehaving.
The ONNX file is produced by ``tools/export_dinov2_onnx.py``.
"""

from __future__ import annotations

import os
import sys
from collections.abc import Sequence
from pathlib import Path

import numpy as np
from PIL import Image

MODEL_NAME = "dinov2_vits14.onnx"
MODEL_VERSION = "dinov2_vits14_cls+mean_letterbox_v2"
INPUT = 224
BATCH = 32
_MEAN = np.array([0.485, 0.456, 0.406], dtype=np.float32).reshape(1, 3, 1, 1)
_STD = np.array([0.229, 0.224, 0.225], dtype=np.float32).reshape(1, 3, 1, 1)
PREFERRED_PROVIDERS = ["CUDAExecutionProvider", "DmlExecutionProvider", "CPUExecutionProvider"]


def model_paths() -> list[Path]:
    here = Path(__file__).resolve().parents[2] / "models" / MODEL_NAME
    out = [here]
    if getattr(sys, "frozen", False):
        out.insert(0, Path(sys.executable).parent / "models" / MODEL_NAME)
    from ..paths import data_dir
    out.append(data_dir() / "models" / MODEL_NAME)
    return out


def model_file() -> Path | None:
    return next((p for p in model_paths() if p.exists()), None)


def available() -> bool:
    try:
        import onnxruntime  # noqa: F401
    except ImportError:
        return False
    return model_file() is not None


def to_input(im: Image.Image) -> np.ndarray:
    """Letterbox to a square (no cropping: edges matter for 'same shot?') -> uint8 HWC."""
    w, h = im.size
    s = INPUT / max(w, h)
    nw, nh = max(1, round(w * s)), max(1, round(h * s))
    canvas = Image.new("RGB", (INPUT, INPUT), (124, 116, 104))
    canvas.paste(im.resize((nw, nh), Image.Resampling.BILINEAR),
                 ((INPUT - nw) // 2, (INPUT - nh) // 2))
    return np.asarray(canvas, dtype=np.uint8)


class Embedder:
    def __init__(self, model_path: Path | None = None, device: str = "auto"):
        import onnxruntime as ort

        try:
            ort.preload_dlls()
        except Exception:
            pass
        path = str(model_path or model_file())
        have = ort.get_available_providers()
        order = ["CPUExecutionProvider"] if device == "cpu" else \
            [p for p in PREFERRED_PROVIDERS if p in have]
        last_err = None
        for prov in order:
            try:
                so = ort.SessionOptions()
                so.log_severity_level = 3
                if prov == "DmlExecutionProvider":
                    so.enable_mem_pattern = False
                    so.execution_mode = ort.ExecutionMode.ORT_SEQUENTIAL
                if prov == "CPUExecutionProvider":
                    so.intra_op_num_threads = max(1, (os.cpu_count() or 4) - 1)
                sess = ort.InferenceSession(path, sess_options=so, providers=[prov])
                self.session, self.provider = sess, prov
                self.input_name = sess.get_inputs()[0].name
                self._run(np.zeros((BATCH, INPUT, INPUT, 3), np.uint8))   # warm-up
                break
            except Exception as e:      # try the next provider
                last_err = e
                self.session = None
        if self.session is None:
            raise RuntimeError(f"No usable ONNX Runtime provider: {last_err}")

    @property
    def device_label(self) -> str:
        return {"CUDAExecutionProvider": "NVIDIA CUDA",
                "DmlExecutionProvider": "GPU (DirectML)"}.get(self.provider, "CPU")

    def _run(self, batch_u8: np.ndarray) -> np.ndarray:
        x = batch_u8.astype(np.float32).transpose(0, 3, 1, 2) / 255.0
        x = (x - _MEAN) / _STD
        return self.session.run(None, {self.input_name: x})[0].astype(np.float32)

    def embed(self, images: Sequence[Image.Image]) -> np.ndarray:
        """Return L2-normalized float16 embeddings, shape (N, D). Fixed batch shape."""
        outs = []
        for i in range(0, len(images), BATCH):
            chunk = [to_input(im) for im in images[i : i + BATCH]]
            n = len(chunk)
            if n < BATCH:   # pad: DirectML recompiles for every new shape
                chunk += [np.zeros_like(chunk[0])] * (BATCH - n)
            y = self._run(np.stack(chunk))[:n]
            y /= np.linalg.norm(y, axis=1, keepdims=True) + 1e-12
            outs.append(y.astype(np.float16))
        return np.concatenate(outs) if outs else np.zeros((0, 0), np.float16)
