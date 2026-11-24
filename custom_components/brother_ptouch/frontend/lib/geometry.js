// Pure geometry helpers. Units are printer dots at 180 dpi unless noted.
export const DOTS_PER_MM = 180 / 25.4;
export const TAPES = [
  { value: 4, label: "3.5 mm", pins: 24 },
  { value: 6, label: "6 mm", pins: 32 },
  { value: 9, label: "9 mm", pins: 50 },
  { value: 12, label: "12 mm", pins: 70 },
  { value: 18, label: "18 mm", pins: 112 },
  { value: 24, label: "24 mm", pins: 128 },
];

export const mmToDots = (mm) => Math.round(mm * DOTS_PER_MM);
export const dotsToMm = (d) => d / DOTS_PER_MM;
export const clamp = (v, lo, hi) => Math.min(hi, Math.max(lo, v));

/** Printable dots across `tapeMm` tape. `pinsByTape` is a printer's `tape_pins` row
 *  ({"12": 64, ...}), for models whose print head differs from the PT-P7xx defaults. */
export function tapePins(tapeMm, pinsByTape) {
  const own = pinsByTape?.[Number(tapeMm)];
  if (own) return own;
  const t = TAPES.find((x) => x.value === Number(tapeMm));
  return t ? t.pins : 70;
}

/** tape_mm as reported by printers: 4 means 3.5 mm. */
export function tapeLabel(tapeMm) {
  const t = TAPES.find((x) => x.value === Number(tapeMm));
  return t ? t.label : `${tapeMm} mm`;
}

/**
 * Offset (dots) of design x=0 inside the rendered label. Auto length labels
 * get padding_dots in front of the content; fixed length labels start at 0.
 * Isolated here so it can be adjusted if the renderer differs.
 */
export function contentOffsetX(design) {
  return 0; // renderer paints elements at their x (padding only extends the end)
}

/** Extent (max x+w) of all elements, 0 when empty. */
export function contentExtent(design) {
  let m = 0;
  for (const e of design.elements || []) m = Math.max(m, (e.x || 0) + (e.w || 0));
  return m;
}

/** Label length in dots as the renderer computes it (best estimate). */
export function labelLengthDots(design) {
  if (design.length_mm != null && design.length_mm !== "") return Math.max(1, mmToDots(Number(design.length_mm)));
  const pad = design.padding_dots ?? 6;
  return Math.max(1, contentExtent(design) + 2 * pad);
}

export const HANDLES = ["nw", "n", "ne", "e", "se", "s", "sw", "w"];
export const HANDLE_CURSORS = { nw: "nwse-resize", se: "nwse-resize", ne: "nesw-resize", sw: "nesw-resize", n: "ns-resize", s: "ns-resize", e: "ew-resize", w: "ew-resize" };

/** Position of a handle on a box, as fractions (0, .5, 1). */
export function handleFraction(h) {
  return [h.includes("w") ? 0 : h.includes("e") ? 1 : 0.5, h.includes("n") ? 0 : h.includes("s") ? 1 : 0.5];
}

/**
 * Resize `box` by dragging `handle` by (dx, dy) dots. Returns a new integer
 * box with at least `min` size. With keepAspect the corner/edge drag keeps
 * the original aspect ratio (anchored to the opposite side).
 */
export function resizeBox(box, handle, dx, dy, { min = 2, keepAspect = false } = {}) {
  let x1 = box.x, y1 = box.y, x2 = box.x + box.w, y2 = box.y + box.h;
  if (handle.includes("w")) x1 += dx;
  if (handle.includes("e")) x2 += dx;
  if (handle.includes("n")) y1 += dy;
  if (handle.includes("s")) y2 += dy;
  if (keepAspect && box.w > 0 && box.h > 0) {
    const ratio = box.w / box.h;
    let w = x2 - x1, h = y2 - y1;
    const movesX = handle.includes("w") || handle.includes("e");
    const movesY = handle.includes("n") || handle.includes("s");
    if (movesX && movesY) {
      // pick the larger relative change
      if (Math.abs(w / box.w - 1) >= Math.abs(h / box.h - 1)) h = w / ratio; else w = h * ratio;
    } else if (movesX) h = w / ratio; else w = h * ratio;
    w = Math.max(min, w); h = Math.max(min, h);
    // anchor on the opposite side (centre on the free axis for edge handles)
    if (handle.includes("w")) x1 = x2 - w; else if (handle.includes("e")) x2 = x1 + w;
    else { const c = (box.x + box.x + box.w) / 2; x1 = c - w / 2; x2 = c + w / 2; }
    if (handle.includes("n")) y1 = y2 - h; else if (handle.includes("s")) y2 = y1 + h;
    else { const c = box.y + box.h / 2; y1 = c - h / 2; y2 = c + h / 2; }
  } else {
    if (x2 - x1 < min) { if (handle.includes("w")) x1 = x2 - min; else x2 = x1 + min; }
    if (y2 - y1 < min) { if (handle.includes("n")) y1 = y2 - min; else y2 = y1 + min; }
  }
  const x = Math.round(x1), y = Math.round(y1);
  return { x, y, w: Math.max(min, Math.round(x2) - x), h: Math.max(min, Math.round(y2) - y) };
}

/**
 * Snap a moving box. bounds = {w, h} of the label; others = boxes of other
 * elements. Returns the snapped {x, y} and guide lines (in dots).
 */
export function snapMove(box, bounds, others = [], threshold = 4) {
  const axis = (pos, size, limit, key) => {
    const feats = [pos, pos + size / 2, pos + size];
    const targets = [0, limit / 2, limit];
    for (const o of others) {
      const p = key === "x" ? o.x : o.y, s = key === "x" ? o.w : o.h;
      targets.push(p, p + s / 2, p + s);
    }
    let best = null;
    for (const f of feats) for (const t of targets) {
      const d = t - f;
      if (Math.abs(d) <= threshold && (best === null || Math.abs(d) < Math.abs(best.d))) best = { d, t };
    }
    return best ? { pos: pos + best.d, guide: best.t } : { pos, guide: null };
  };
  const sx = axis(box.x, box.w, bounds.w, "x");
  const sy = axis(box.y, box.h, bounds.h, "y");
  const guides = [];
  if (sx.guide !== null) guides.push({ axis: "x", pos: sx.guide });
  if (sy.guide !== null) guides.push({ axis: "y", pos: sy.guide });
  return { x: Math.round(sx.pos), y: Math.round(sy.pos), guides };
}

export function nudge(box, key, big) {
  const s = big ? 10 : 1;
  const d = { ArrowLeft: [-s, 0], ArrowRight: [s, 0], ArrowUp: [0, -s], ArrowDown: [0, s] }[key];
  return d ? { x: box.x + d[0], y: box.y + d[1] } : null;
}

/** Zoom that fits `contentW` dots into `availPx`, clamped to [min, max]. */
export function fitZoom(contentW, availPx, min = 0.25, max = 6) {
  if (!contentW) return 1;
  const z = availPx / contentW;
  return clamp(z >= 1 ? Math.floor(z) : Math.floor(z * 4) / 4, min, max) || min;
}

/** Tick spacing in mm for a ruler at the given zoom (px per dot). */
export function rulerStep(zoom) {
  const pxPerMm = zoom * DOTS_PER_MM;
  for (const s of [1, 2, 5, 10, 20, 50]) if (s * pxPerMm >= 28) return s;
  return 100;
}

export const rotateStep = (r) => (((Number(r) || 0) + 90) % 360 + 360) % 360;

// ---- touch / pinch helpers (pure) ------------------------------------------
export const TOUCH_HIT = 44; // minimum effective hit size in css px

export const pointDist = (a, b) => Math.hypot(a.x - b.x, a.y - b.y);
export const pointMid = (a, b) => ({ x: (a.x + b.x) / 2, y: (a.y + b.y) / 2 });

/**
 * Pinch zoom + two-finger pan. The content point (in content px, including the
 * `pad` offset of the canvas inside the scroller) that was under the start
 * centre c0 stays under the current centre c1. c0/c1 are relative to the
 * scroller's visible box. Returns the new zoom and desired scroll offsets
 * (the caller clamps them to the scrollable range).
 */
export function pinchView({ z0, d0, d1, c0, c1, scroll0, pad = { x: 0, y: 0 }, minZ = 0.25, maxZ = 8 }) {
  const ratio = d0 > 0 ? d1 / d0 : 1;
  const zoom = clamp(z0 * ratio, minZ, maxZ);
  const px = (scroll0.x + c0.x - pad.x) / z0, py = (scroll0.y + c0.y - pad.y) / z0;
  return { zoom, scrollX: px * zoom + pad.x - c1.x, scrollY: py * zoom + pad.y - c1.y };
}

/**
 * Default zoom for narrow (phone) screens: at least `min` so elements stay
 * touchable, up to `max`; long labels simply scroll horizontally.
 */
export function mobileZoom(contentW, availPx, { min = 2, max = 4 } = {}) {
  if (!contentW || availPx <= 0) return min;
  const fit = Math.floor((availPx / contentW) * 4) / 4;
  return clamp(fit, min, max);
}

/**
 * Which resize handles to offer for an element of the given on-screen size
 * (css px). Edge handles need room so their 44px hit boxes do not overlap the
 * corner ones; `outside` means the element is so small that handles must sit
 * outside its box to leave the body draggable.
 */
export function handlesFor(wPx, hPx, hit = TOUCH_HIT) {
  const list = ["nw", "ne", "se", "sw"];
  if (hPx >= 2 * hit) list.push("e", "w");
  if (wPx >= 2 * hit) list.push("n", "s");
  return { list, outside: Math.min(wPx, hPx) < 1.5 * hit };
}

/** Extra hit padding (css px per side) so that a box is at least `hit` wide/high. */
export const hitPad = (sizePx, hit = TOUCH_HIT) => Math.max(0, (hit - sizePx) / 2);

/** Scroll offset that brings [lo,hi] (content px) into a viewport of `size` starting at `scroll`, with margin. */
export function revealRange(lo, hi, scroll, size, margin = 16) {
  if (hi - lo + 2 * margin > size) return Math.max(0, lo - margin);
  if (lo - margin < scroll) return Math.max(0, lo - margin);
  if (hi + margin > scroll + size) return hi + margin - size;
  return scroll;
}
