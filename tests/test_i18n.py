from __future__ import annotations

import string

import pytest

pytest.importorskip("PySide6")

from keepframe.core import ranking  # noqa: E402
from keepframe.ui import i18n  # noqa: E402


def _fields(s: str) -> set[str]:
    return {f for _, f, _, _ in string.Formatter().parse(s) if f}


@pytest.mark.parametrize("lang", [k for k in i18n.CATALOGS if k != "en"])
def test_same_keys_and_placeholders(lang):
    cat = i18n.CATALOGS[lang]
    assert set(cat) == set(i18n.EN), set(i18n.EN) ^ set(cat)
    for k, v in i18n.EN.items():
        assert _fields(v) == _fields(cat[k]), k


def test_every_reason_key_is_translated():
    import inspect

    src = inspect.getsource(ranking)
    for key in ("sharpest", "eyes_open", "highest_resolution", "best_overall", "blurrier",
                "eyes_closed", "lower_resolution", "similar_to_best", "protected",
                "original", "copy"):
        assert f'"{key}"' in src
        assert f"reason.{key}" in i18n.EN
