// Design state with undo/redo history. No DOM access; usable from node.
import { tapePins } from "./geometry.js";

export const MAX_HISTORY = 100;
let _uid = 0;
export const uid = (prefix = "e") => `${prefix}${Date.now().toString(36)}${(_uid++).toString(36)}`;
const clone = (o) => JSON.parse(JSON.stringify(o));

export function emptyDesign() {
  return { version: 1, name: "New label", length_mm: null, padding_dots: 6, variables: {}, elements: [] };
}

/** Defaults for a new element of `type` placed after the current content. */
export function newElement(type, design, tapeMm, imageInfo, pinsByTape) {
  const H = tapePins(tapeMm, pinsByTape);
  let x = 0;
  for (const e of design.elements) x = Math.max(x, e.x + e.w + 6);
  const base = { id: uid(), type, x, y: 0, w: H, h: H, rotation: 0, invert: false };
  switch (type) {
    case "text": return { ...base, w: 120, text: "Text", font: "", weight: 400, italic: false, size: "auto", align: "center", valign: "middle", line_spacing: 1.0 };
    case "icon": return { ...base, icon: "mdi:tag" };
    case "qr": return { ...base, data: "https://example.com", ecc: "m", quiet: 1 };
    case "barcode": return { ...base, w: 170, format: "code128", data: "12345678", show_text: true };
    case "rect": return { ...base, w: 80, stroke: 2, fill: false };
    case "line": return { ...base, type: "rect", w: 80, h: 2, y: Math.round(H / 2) - 1, stroke: 2, fill: true };
    case "image": {
      const iw = imageInfo?.w || H, ih = imageInfo?.h || H;
      const h = Math.min(H, ih), w = Math.max(1, Math.round((iw * h) / ih));
      return { ...base, w, h, src: imageInfo?.src || "", dither: true };
    }
    default: throw new Error(`unknown element type ${type}`);
  }
}

export class Store {
  constructor(design = emptyDesign()) {
    this.listeners = new Set();
    this.load(design);
  }
  subscribe(fn) { this.listeners.add(fn); return () => this.listeners.delete(fn); }
  _emit(what = "design") { for (const fn of this.listeners) fn(what); }

  load(design, { saved = true } = {}) {
    this.design = clone(design);
    this.design.elements = this.design.elements || [];
    this.design.variables = this.design.variables || {};
    for (const e of this.design.elements) if (!e.id) e.id = uid();
    this.selection = null;
    this.undoStack = []; this.redoStack = [];
    this._savedJSON = saved ? JSON.stringify(this.design) : null;
    this._lastKey = null; this._lastTime = 0; this._gesture = null;
    this._emit("load");
  }
  markSaved(design) {
    // adopt server-assigned fields (id, name, updated) without touching history
    if (design) { this.design.id = design.id; this.design.updated = design.updated; }
    this._savedJSON = JSON.stringify(this.design);
    this._emit("meta");
  }
  get dirty() { return JSON.stringify(this.design) !== this._savedJSON; }
  get canUndo() { return this.undoStack.length > 0; }
  get canRedo() { return this.redoStack.length > 0; }
  get selected() { return this.design.elements.find((e) => e.id === this.selection) || null; }
  element(id) { return this.design.elements.find((e) => e.id === id) || null; }

  _snapshot() { return JSON.stringify({ d: this.design, s: this.selection }); }
  _push(coalesceKey) {
    const now = Date.now();
    if (this._gesture) return; // gesture pushes once at the end
    if (coalesceKey && coalesceKey === this._lastKey && now - this._lastTime < 900) { this._lastTime = now; return; }
    this.undoStack.push(this._snapshot());
    if (this.undoStack.length > MAX_HISTORY) this.undoStack.shift();
    this.redoStack = [];
    this._lastKey = coalesceKey || null; this._lastTime = now;
  }
  _restore(json) {
    const { d, s } = JSON.parse(json);
    this.design = d; this.selection = d.elements.some((e) => e.id === s) ? s : null;
    this._lastKey = null;
  }
  undo() {
    if (!this.canUndo) return;
    this.redoStack.push(this._snapshot()); this._restore(this.undoStack.pop()); this._emit("design");
  }
  redo() {
    if (!this.canRedo) return;
    this.undoStack.push(this._snapshot()); this._restore(this.redoStack.pop()); this._emit("design");
  }

  /** Start a drag-like gesture: all changes until endGesture() are one undo step. */
  beginGesture() { if (!this._gesture) this._gesture = this._snapshot(); }
  endGesture() {
    if (!this._gesture) return;
    const before = this._gesture; this._gesture = null;
    if (before !== this._snapshot()) { this.undoStack.push(before); this.redoStack = []; if (this.undoStack.length > MAX_HISTORY) this.undoStack.shift(); this._lastKey = null; this._emit("design"); }
  }

  select(id) { if (this.selection !== id) { this.selection = id; this._emit("selection"); } }

  setMeta(patch, coalesceKey) {
    this._push(coalesceKey || "meta:" + Object.keys(patch).join(","));
    Object.assign(this.design, patch); this._emit("design");
  }
  setVariables(vars, coalesceKey = "vars") {
    this._push(coalesceKey); this.design.variables = { ...vars }; this._emit("design");
  }
  updateElement(id, patch, coalesceKey) {
    const el = this.element(id); if (!el) return;
    let changed = false;
    for (const k of Object.keys(patch)) if (JSON.stringify(el[k]) !== JSON.stringify(patch[k])) changed = true;
    if (!changed) return;
    this._push(coalesceKey);
    Object.assign(el, patch); this._emit("design");
  }
  addElement(el) {
    this._push(); this.design.elements.push(el); this.selection = el.id; this._emit("design");
    return el;
  }
  removeElement(id) {
    const i = this.design.elements.findIndex((e) => e.id === id); if (i < 0) return;
    this._push(); this.design.elements.splice(i, 1);
    if (this.selection === id) this.selection = null;
    this._emit("design");
  }
  duplicateElement(id, offset = 8) {
    const el = this.element(id); if (!el) return null;
    this._push();
    const copy = { ...clone(el), id: uid(), x: el.x + offset, y: el.y };
    this.design.elements.push(copy); this.selection = copy.id; this._emit("design");
    return copy;
  }
  /** Move element in z-order by delta (+1 = towards front/later in list). */
  reorder(id, delta) {
    const els = this.design.elements, i = els.findIndex((e) => e.id === id);
    const j = i + delta; if (i < 0 || j < 0 || j >= els.length) return;
    this._push(); [els[i], els[j]] = [els[j], els[i]]; this._emit("design");
  }
}
