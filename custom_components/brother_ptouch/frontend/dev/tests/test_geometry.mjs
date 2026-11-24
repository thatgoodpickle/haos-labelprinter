import assert from "node:assert/strict";
import * as G from "../../lib/geometry.js";
import { Store, newElement, emptyDesign } from "../../lib/store.js";
import { Previewer } from "../../lib/api.js";

let n = 0; const t = async (name, fn) => { await fn(); n++; console.log("ok -", name); };

await t("tapePins / labels", () => {
  assert.equal(G.tapePins(12), 70); assert.equal(G.tapePins(4), 24); assert.equal(G.tapePins(24), 128);
  assert.equal(G.tapeLabel(4), "3.5 mm");
  // a printer's own tape_pins row wins; missing widths fall back
  const own = { 4: 24, 6: 32, 9: 50, 12: 64, 18: 112, 24: 128 };
  assert.equal(G.tapePins(12, own), 64); assert.equal(G.tapePins(9, own), 50);
  assert.equal(G.tapePins(12, { 4: 24 }), 70); assert.equal(G.tapePins(12, null), 70);
});
await t("mm/dots", () => { assert.equal(G.mmToDots(25.4), 180); assert.ok(Math.abs(G.dotsToMm(180) - 25.4) < 1e-9); });
await t("label length auto/fixed", () => {
  assert.equal(G.labelLengthDots({ elements: [{ x: 10, w: 50 }], padding_dots: 6 }), 72);
  assert.equal(G.labelLengthDots({ elements: [], padding_dots: 6 }), 12);
  assert.equal(G.labelLengthDots({ elements: [], length_mm: 25.4 }), 180);
});
await t("resizeBox corners and min", () => {
  const b = { x: 10, y: 10, w: 40, h: 20 };
  assert.deepEqual(G.resizeBox(b, "se", 10, 5), { x: 10, y: 10, w: 50, h: 25 });
  assert.deepEqual(G.resizeBox(b, "nw", 5, 5), { x: 15, y: 15, w: 35, h: 15 });
  assert.deepEqual(G.resizeBox(b, "e", -100, 0, { min: 2 }), { x: 10, y: 10, w: 2, h: 20 });
  assert.deepEqual(G.resizeBox(b, "w", 100, 0, { min: 2 }), { x: 48, y: 10, w: 2, h: 20 });
});
await t("resizeBox keepAspect", () => {
  const r = G.resizeBox({ x: 0, y: 0, w: 40, h: 20 }, "se", 20, 0, { keepAspect: true });
  assert.deepEqual(r, { x: 0, y: 0, w: 60, h: 30 });
  const e = G.resizeBox({ x: 0, y: 0, w: 40, h: 20 }, "e", 40, 0, { keepAspect: true });
  assert.equal(e.w, 80); assert.equal(e.h, 40); assert.equal(e.y, -10);
});
await t("snapMove edges/centre/others", () => {
  const bounds = { w: 200, h: 70 };
  let s = G.snapMove({ x: 3, y: 2, w: 40, h: 20 }, bounds, [], 4);
  assert.deepEqual([s.x, s.y], [0, 0]);
  s = G.snapMove({ x: 78, y: 24, w: 40, h: 20 }, bounds, [], 4); // centre x=98 -> 100, centre y=34 -> 35
  assert.deepEqual([s.x, s.y], [80, 25]);
  assert.equal(s.guides.length, 2);
  s = G.snapMove({ x: 150, y: 40, w: 50, h: 20 }, bounds, [], 4);
  assert.equal(s.x, 150); // right edge already 200
  s = G.snapMove({ x: 63, y: 10, w: 10, h: 10 }, bounds, [{ x: 60, y: 40, w: 30, h: 10 }], 4);
  assert.equal(s.x, 65); // right edge 73 -> centre 75 of other (closest)
  s = G.snapMove({ x: 30, y: 30, w: 10, h: 10 }, bounds, [], 2); assert.deepEqual([s.x, s.y], [30, 30]);
});
await t("nudge", () => {
  assert.deepEqual(G.nudge({ x: 5, y: 5 }, "ArrowLeft", false), { x: 4, y: 5 });
  assert.deepEqual(G.nudge({ x: 5, y: 5 }, "ArrowDown", true), { x: 5, y: 15 });
  assert.equal(G.nudge({ x: 5, y: 5 }, "a", false), null);
});
await t("fitZoom / rulerStep / rotateStep", () => {
  assert.equal(G.fitZoom(100, 650), 6); assert.equal(G.fitZoom(300, 650), 2); assert.equal(G.fitZoom(1300, 650), 0.5);
  assert.ok(G.rulerStep(1) >= 5); assert.equal(G.rotateStep(270), 0); assert.equal(G.rotateStep(0), 90);
});
await t("store: add/update/undo/redo", () => {
  const s = new Store(emptyDesign()); assert.equal(s.dirty, false);
  const e = s.addElement(newElement("text", s.design, 12)); assert.equal(s.selection, e.id); assert.ok(s.dirty);
  s.updateElement(e.id, { x: 20 }); assert.equal(s.element(e.id).x, 20);
  s.undo(); assert.equal(s.element(e.id).x, 0);
  s.undo(); assert.equal(s.design.elements.length, 0); assert.equal(s.dirty, false);
  s.redo(); s.redo(); assert.equal(s.element(e.id).x, 20);
  s.undo(); s.updateElement(e.id, { x: 3 }); assert.equal(s.canRedo, false);
});
await t("store: coalescing and gestures", () => {
  const s = new Store(emptyDesign()); const e = s.addElement(newElement("text", s.design, 12));
  const base = s.undoStack.length;
  s.updateElement(e.id, { text: "a" }, "k"); s.updateElement(e.id, { text: "ab" }, "k"); s.updateElement(e.id, { text: "abc" }, "k");
  assert.equal(s.undoStack.length, base + 1); s.undo(); assert.equal(s.element(e.id).text, "Text");
  s.redo();
  const b2 = s.undoStack.length;
  s.beginGesture(); for (let i = 1; i <= 5; i++) s.updateElement(e.id, { x: i * 10 }); s.endGesture();
  assert.equal(s.undoStack.length, b2 + 1); s.undo(); assert.equal(s.element(e.id).x, 0);
  s.beginGesture(); s.endGesture(); // no change: no history entry
  const b3 = s.undoStack.length; s.beginGesture(); s.endGesture(); assert.equal(s.undoStack.length, b3);
});
await t("store: remove/duplicate/reorder/variables/markSaved", () => {
  const s = new Store(emptyDesign());
  const a = s.addElement(newElement("text", s.design, 12)), b = s.addElement(newElement("qr", s.design, 12));
  assert.ok(b.x > a.x);
  s.reorder(a.id, 1); assert.equal(s.design.elements[1].id, a.id);
  const c = s.duplicateElement(a.id); assert.notEqual(c.id, a.id); assert.equal(s.design.elements.length, 3);
  s.removeElement(c.id); assert.equal(s.selection, null); s.undo(); assert.equal(s.selection, c.id);
  s.setVariables({ name: "x" }); assert.equal(s.design.variables.name, "x");
  s.markSaved({ id: "foo", updated: "now" }); assert.equal(s.dirty, false); assert.equal(s.design.id, "foo");
});
await t("newElement defaults per type", () => {
  const d = emptyDesign();
  for (const ty of ["text", "icon", "qr", "barcode", "rect", "line", "image"]) {
    const e = newElement(ty, d, 24, { w: 400, h: 256, src: "data:" }); assert.ok(e.w > 0 && e.h > 0 && e.id);
  }
  assert.equal(newElement("image", d, 24, { w: 400, h: 256, src: "x" }).h, 128);
  assert.equal(newElement("line", d, 12).type, "rect");
  assert.equal(newElement("icon", d, 12, null, { 12: 64 }).h, 64);
});
await t("previewer drops stale responses", async () => {
  const got = []; let call = 0;
  const p = new Previewer(async () => { const n = ++call; await new Promise((r) => setTimeout(r, n === 1 ? 60 : 5)); return n; }, (m) => { if (m.result) got.push(m.result); }, { delay: 5, maxWait: 20 });
  p.request(); await new Promise((r) => setTimeout(r, 15)); p.request(); await new Promise((r) => setTimeout(r, 150));
  assert.deepEqual(got, [2]);
});

await t("pinchView keeps anchor under fingers", () => {
  const a = { z0: 2, d0: 100, d1: 200, c0: { x: 150, y: 80 }, c1: { x: 150, y: 80 }, scroll0: { x: 300, y: 0 }, pad: { x: 20, y: 10 } };
  const r = G.pinchView(a);
  assert.equal(r.zoom, 4);
  const anchorBefore = (300 + 150 - 20) / 2, anchorAfter = (r.scrollX + 150 - 20) / r.zoom;
  assert.ok(Math.abs(anchorBefore - anchorAfter) < 1e-9);
  const pan = G.pinchView({ ...a, d1: 100, c1: { x: 100, y: 80 } });   // two-finger pan by 50px left
  assert.equal(pan.zoom, 2); assert.equal(pan.scrollX, 350);
});
await t("pinchView clamps zoom", () => {
  const base = { z0: 2, d0: 10, c0: { x: 0, y: 0 }, c1: { x: 0, y: 0 }, scroll0: { x: 0, y: 0 } };
  assert.equal(G.pinchView({ ...base, d1: 1000 }).zoom, 8);
  assert.equal(G.pinchView({ ...base, d1: 0.1 }).zoom, 0.25);
  assert.equal(G.pinchView({ ...base, d0: 0, d1: 5 }).zoom, 2);
});
await t("pointDist / pointMid", () => {
  assert.equal(G.pointDist({ x: 0, y: 0 }, { x: 3, y: 4 }), 5);
  assert.deepEqual(G.pointMid({ x: 0, y: 2 }, { x: 4, y: 6 }), { x: 2, y: 4 });
});
await t("mobileZoom default", () => {
  assert.equal(G.mobileZoom(500, 340), 2);        // long label: scrolls
  assert.equal(G.mobileZoom(100, 340), 3.25);     // short label: larger
  assert.equal(G.mobileZoom(20, 340), 4);
  assert.equal(G.mobileZoom(0, 340), 2);
});
await t("handlesFor keeps 44px boxes apart", () => {
  assert.equal(G.handlesFor(300, 200).list.length, 8);
  assert.deepEqual(G.handlesFor(300, 60).list.sort(), ["ne", "nw", "se", "sw", "n", "s"].sort());
  assert.equal(G.handlesFor(60, 60).list.length, 4);
  assert.equal(G.handlesFor(60, 60).outside, true);
  assert.equal(G.handlesFor(300, 200).outside, false);
});
await t("hitPad / revealRange", () => {
  assert.equal(G.hitPad(10), 17); assert.equal(G.hitPad(80), 0);
  assert.equal(G.revealRange(100, 150, 0, 300), 0);          // already visible
  assert.equal(G.revealRange(400, 450, 0, 300), 166);        // scroll right
  assert.equal(G.revealRange(20, 60, 100, 300), 4);          // scroll left
  assert.equal(G.revealRange(0, 500, 50, 300), 0);           // too big: align start
});
console.log(`${n} tests passed`);
