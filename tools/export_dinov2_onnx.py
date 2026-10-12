"""Export DINOv2 ViT-S/14 (Apache-2.0) to ONNX for KeepFrame.

Output embedding = concat(CLS token, mean of patch tokens), dim 768.
Requires (one-time, dev only): pip install torch transformers onnx onnxscript

    python tools/export_dinov2_onnx.py [--fp16]
"""

from __future__ import annotations

import argparse
import hashlib
import inspect
import os
import shutil
import sys
from pathlib import Path

OUT = Path(__file__).resolve().parents[1] / "src" / "keepframe" / "models" / "dinov2_vits14.onnx"


def main() -> int:
    import numpy as np
    import torch
    from transformers import AutoModel

    ap = argparse.ArgumentParser()
    ap.add_argument("--fp16", action="store_true", help="convert weights to float16")
    args = ap.parse_args()

    print(f"python {sys.version.split()[0]} · torch {torch.__version__}", flush=True)
    print("Downloading facebook/dinov2-small …", flush=True)
    try:
        base = AutoModel.from_pretrained("facebook/dinov2-small", attn_implementation="eager")
    except TypeError:
        base = AutoModel.from_pretrained("facebook/dinov2-small")
    base.eval()

    class Wrap(torch.nn.Module):
        def __init__(self, m):
            super().__init__()
            self.m = m

        def forward(self, pixel_values):
            h = self.m(pixel_values=pixel_values).last_hidden_state
            return torch.cat([h[:, 0], h[:, 1:].mean(dim=1)], dim=1)

    model = Wrap(base).eval()
    x = torch.randn(2, 3, 224, 224)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    tmp = OUT.with_suffix(".tmp.onnx")
    base_kw = dict(input_names=["pixel_values"], output_names=["embedding"], opset_version=18)
    has_dynamo = "dynamo" in inspect.signature(torch.onnx.export).parameters
    attempts = []
    # 1) classic TorchScript exporter (simple and stable for ViTs)
    classic = dict(base_kw, opset_version=17, do_constant_folding=True,
                   dynamic_axes={"pixel_values": {0: "batch"}, "embedding": {0: "batch"}})
    if has_dynamo:
        classic["dynamo"] = False
    attempts.append(("classic", classic))
    # 2) torch.export based exporter (default in torch >= 2.9, needs onnxscript)
    if has_dynamo:
        batch = torch.export.Dim("batch", min=1, max=256)
        attempts.append(("dynamo", dict(base_kw, dynamo=True,
                                         dynamic_shapes={"pixel_values": {0: batch}})))
    with torch.no_grad():
        ref = model(x).numpy()
        last = None
        for name, kw in attempts:
            print(f"Exporting to ONNX ({name}) …", flush=True)
            try:
                torch.onnx.export(model, (x,), str(tmp), **kw)
                last = None
                break
            except Exception as e:   # try the next exporter
                last = e
                print(f"  {name} exporter failed: {type(e).__name__}: {e}", flush=True)
        if last is not None:
            raise last

    if args.fp16:
        import onnx
        from onnxconverter_common import float16

        m = float16.convert_float_to_float16(onnx.load(str(tmp)), keep_io_types=True)
        onnx.save(m, str(tmp))

    try:   # verify with ONNX Runtime when available
        import onnxruntime as ort

        sess = ort.InferenceSession(str(tmp), providers=["CPUExecutionProvider"])
        out = sess.run(None, {"pixel_values": x.numpy()})[0]
        cos = (out * ref).sum(1) / (np.linalg.norm(out, axis=1) * np.linalg.norm(ref, axis=1))
        print(f"Check vs PyTorch: cosine {cos.min():.5f}", flush=True)
        if cos.min() < 0.999:
            print("ERROR: exported model does not match", file=sys.stderr)
            return 1
    except ImportError:
        print("(onnxruntime not installed: skipped verification)")

    shutil.move(str(tmp), str(OUT))
    digest = hashlib.sha256(OUT.read_bytes()).hexdigest()
    print(f"Saved {OUT} ({OUT.stat().st_size / 1e6:.1f} MB) sha256={digest}")

    local = os.environ.get("LOCALAPPDATA")
    if local:
        dst = Path(local) / "KeepFrame" / "models" / OUT.name
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(OUT, dst)
        print(f"Copied to {dst}")
    print("MODEL READY")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
