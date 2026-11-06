import os
import re

import pytest

from ptouch.design import DesignError, design_warnings, normalize_design, render_design
from ptouch.protocol import MODEL_P300BT, tape_pins
from ptouch.templates import (CATEGORIES, FONTS_USED, ICONS, TEMPLATE_VERSION, TemplateError,
                              build_template, list_templates, used_variables)

TEMPLATES = list_templates()
CASES = [(t["id"], tape) for t in TEMPLATES for tape in t["tapes"]]
VAR_RE = re.compile(r"\{\{\s*([^{}\s]+)\s*\}\}")


def ink(img):
    return img.convert("L").histogram()[0]


def test_catalogue_shape():
    assert TEMPLATE_VERSION == 1
    assert len(TEMPLATES) >= 25
    ids = [t["id"] for t in TEMPLATES]
    assert len(ids) == len(set(ids))
    for t in TEMPLATES:
        assert t["category"] in CATEGORIES
        assert t["name"] and t["description"]
        assert t["tape_mm_hint"] in t["tapes"]
        assert set(t["tapes"]) <= {4, 6, 9, 12, 18, 24}
        assert 12 in t["tapes"] or t["tape_mm_hint"] == 18
        for name, v in t["variables"].items():
            assert set(v) == {"label", "default"} and v["default"] != ""
    assert {t["category"] for t in TEMPLATES} == set(CATEGORIES)


@pytest.mark.parametrize("tid,tape", CASES)
def test_render_each(tid, tape):
    d = build_template(tid, tape)
    n = normalize_design(d)
    assert len(n["elements"]) == len(d["elements"])
    img = render_design(d, tape, variables={})
    assert img.mode == "1" and img.height == tape_pins(tape)
    assert ink(img) > 50
    # offline (assets=None) icons are legitimately unavailable; everything else must be clean
    assert [w for w in design_warnings(d, tape, variables={}) if "not available" not in w] == []


@pytest.mark.parametrize("tid", [t["id"] for t in TEMPLATES if 12 in t["tapes"]])
def test_render_each_p300bt(tid):
    d = build_template(tid, 12, MODEL_P300BT)
    img = render_design(d, 12, variables={}, model=MODEL_P300BT)
    assert img.height == 64 and ink(img) > 50
    assert [w for w in design_warnings(d, 12, variables={}, model=MODEL_P300BT)
            if "not available" not in w] == []


@pytest.mark.parametrize("tid,tape", CASES)
def test_variables_and_legibility(tid, tape):
    t = next(x for x in TEMPLATES if x["id"] == tid)
    d = build_template(tid, tape)
    assert set(d["variables"]) == set(t["variables"])
    assert used_variables(d) == set(t["variables"])
    for el in d["elements"]:
        if el["type"] == "text" and not VAR_RE.sub("", el["text"]).isspace():
            lines = el["text"].count("\n") + 1
            assert el["h"] / lines >= 19, (tid, tape, el["id"])
        if el["type"] == "qr":
            import segno
            data = VAR_RE.sub(lambda m: d["variables"][m.group(1)], el["data"])
            n = len(segno.make(data, error=el["ecc"], micro=False).matrix) + 2 * el["quiet"]
            assert min(el["w"], el["h"]) // n >= 3, (tid, tape)
        if el["type"] == "barcode":
            assert el["h"] >= 40


def test_all_tapes_render_for_supported_and_reject_others():
    with pytest.raises(TemplateError):
        build_template("wifi-qr", 12)
    with pytest.raises(TemplateError):
        build_template("nope", 12)
    assert build_template("pantry-jar", 3.5)["elements"]


def test_fonts_and_icons_declared():
    fams = {el.get("font") for t in TEMPLATES for tape in t["tapes"]
            for el in build_template(t["id"], tape)["elements"] if el["type"] == "text"}
    assert fams <= set(FONTS_USED)
    used_icons = {el["icon"] for t in TEMPLATES for tape in t["tapes"]
                  for el in build_template(t["id"], tape)["elements"] if el["type"] == "icon"}
    assert used_icons <= set(ICONS.values())


@pytest.mark.skipif(os.environ.get("PTOUCH_LIVE") != "1", reason="PTOUCH_LIVE=1 for network test")
def test_live_fonts_icons(tmp_path):
    from ptouch.assets import AssetManager
    am = AssetManager(tmp_path)
    names = set(am.icon_names())
    for icon in ICONS.values():
        assert icon in names, icon
    catalog = {f["family"]: f for f in am.font_catalog()}
    used = {}
    for t in TEMPLATES:
        for tape in t["tapes"]:
            for el in build_template(t["id"], tape)["elements"]:
                if el["type"] == "text" and el.get("font"):
                    used.setdefault(el["font"], set()).add(el["weight"])
    for fam, weights in used.items():
        assert fam in catalog, fam
        for w in weights:
            assert w in catalog[fam]["weights"], (fam, w)
            assert am.font_path(fam, w) is not None
    for t in TEMPLATES:
        for tape in t["tapes"]:
            d = build_template(t["id"], tape)
            img = render_design(d, tape, variables={}, assets=am)
            assert img.height == tape_pins(tape) and ink(img) > 50
            assert design_warnings(d, tape, variables={}, assets=am) == [], (t["id"], tape)
