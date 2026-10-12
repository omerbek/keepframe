"""Face signals for best-shot ranking (v0.2).

Plan:
  * Detection: YuNet (OpenCV Zoo, MIT) via ``cv2.FaceDetectorYN``.
  * Eyes open / smile: MediaPipe Face Landmarker blendshapes
    (``eyeBlinkLeft/Right``, ``mouthSmileLeft/Right``), Apache-2.0.
  * Fallback: eye-aspect-ratio from landmarks.
Only run on assets that ended up in a candidate group (lazy).
"""

from __future__ import annotations

from dataclasses import dataclass

from PIL import Image


@dataclass
class FaceInfo:
    box: tuple[int, int, int, int]
    eyes_open: float   # 0 = closed, 1 = open
    smile: float       # 0..1


def analyze(im: Image.Image) -> list[FaceInfo]:
    """Return detected faces. Not implemented yet: returns []."""
    return []
