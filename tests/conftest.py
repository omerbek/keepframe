from __future__ import annotations

import numpy as np
import pytest
from PIL import Image


def make_scene(seed: int, shift: int = 0, blur: bool = False, size=(320, 240)) -> Image.Image:
    """Synthetic 'photo': random shapes, optionally shifted (burst) or blurred."""
    from PIL import ImageDraw, ImageFilter

    rng = np.random.default_rng(seed)
    im = Image.new("RGB", (size[0] + 40, size[1] + 40), tuple(rng.integers(0, 255, 3).tolist()))
    d = ImageDraw.Draw(im)
    for _ in range(40):
        x, y = rng.integers(0, size[0], 2)
        r = int(rng.integers(5, 40))
        d.ellipse([x, y, x + r, y + r], fill=tuple(rng.integers(0, 255, 3).tolist()))
    im = im.crop((20 + shift, 20, 20 + shift + size[0], 20 + size[1]))
    if blur:
        im = im.filter(ImageFilter.GaussianBlur(4))
    return im


@pytest.fixture
def scene():
    return make_scene
