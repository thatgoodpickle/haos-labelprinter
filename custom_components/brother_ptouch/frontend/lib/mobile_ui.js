// Phone UI (< 900 px wide): a home screen of saved labels, an editor view with a bottom toolbar and a
// bottom sheet for properties, a print confirmation sheet, and the Back-button history handling.
// It re-uses the panel's own nodes (canvas, inspector, name, print button ...) by moving them into
// place, so desktop and phone share one set of controls. Pure decisions live in mobile.js.
import { h, icon, iconButton } from "./ui.js";
import * as M from "./mobile.js";
import * as PL from "./printer_logic.js";
import * as G from "./geometry.js";
import { ThumbCache } from "./templates.js";
import { connectOutcome, failureSentence, canRetry } from "./reasons.js";

const TYPE_ICONS = { text: "mdi:format-text", icon: "mdi:emoticon-outline", qr: "mdi:qrcode", barcode: "mdi:barcode", rect: "mdi:rectangle-outline", image: "mdi:image-outline" };
const TYPE_NAMES = { text: "Text", icon: "Icon", qr: "QR code", barcode: "Barcode", rect: "Rectangle", image: "Image" };

/** p = the panel element (see brother-ptouch-panel.js), t = translate. */
export function createMobile(p, t) {
  const $ = p.$;
  const m = { snap: "closed", sheetFor: "label", kb: 0 };

  // ---- history (hardware Back / browser back) -----------------------------------------------------
  const st = new M.NavStack();
  m.enabled = false;
  const stateOf = () => { try { return history.state && typeof history.state === "object" ? history.state : {}; } catch { return {}; } };
  m.push = (kind) => {
    if (!m.enabled || st.has(kind)) return;
    st.push(kind);
    try { history.pushState({ ...stateOf(), bp: kind }, ""); } catch { /* sandboxed: Back just leaves the page */ }
  };
  m.pop = (kind) => {
    const r = st.close(kind);
    if (r.back) try { history.back(); } catch { /* ignore */ }
  };
  m.adopt = (kind) => { if (!st.has(kind)) st.push(kind); };
  m.has = (kind) => st.has(kind);
  m.resetNav = () => st.reset();
  m.expectBack = () => { st.skip++; };
  const onPop = async () => {
    if (!m.enabled) return;
    const r = st.onPopState();
    if (r.ignore) return;
    if (r.again) { try { history.back(); } catch { /* ignore */ } }
    const kind = r.entry.kind;
    if (kind === "layer") { p._closeLayerFromBack(); m.syncLayer(); }
    else if (kind === "sheet") m.setSnap("closed", { fromPop: true });
    else if (kind === "edit") {
      const left = await p._leaveEditor({ fromPop: true });
      if (!left) m.push("edit");   // vetoed (unsaved changes): put the entry back
    }
  };
  window.addEventListener("popstate", onPop);
  m.destroy = () => { window.removeEventListener("popstate", onPop); mo.disconnect(); ro.disconnect(); thumbIO?.disconnect(); };
  /** Keep a history entry for as long as the modal layer is visible. */
  m.syncLayer = () => {
    if (!m.enabled) return;
    const vis = !$.layer.hidden, has = st.has("layer");
    if (vis && !has) m.push("layer"); else if (!vis && has) m.pop("layer");
  };
  const mo = new MutationObserver(() => m.syncLayer());
  m.init = () => mo.observe($.layer, { attributes: true, attributeFilter: ["hidden"] });

  // ---- home -------------------------------------------------------------------------------------------
  const thumbs = new ThumbCache(async (tape, key) => {
    const d = await p.api.getDesign(String(key).split("@")[0]);
    const r = await p.api.preview(d, { tape_mm: tape });
    return { src: `data:image/png;base64,${r.png}`, w: r.width, h: r.height };
  }, { concurrency: 3 });
  m.thumbs = thumbs;
  let thumbIO = null;
  const statusHost = h("div", { class: "hstatus" });
  const grid = h("div", { class: "lgrid", role: "list" });
  const gridHead = h("div", { class: "hhead" });
  const homeScroll = h("div", { class: "mscroll" });
  const cta = h("div", { class: "cta" },
    h("button", { class: "btn big primary", type: "button", onClick: () => p._new() }, icon("mdi:plus"), t("New label")),
    h("button", { class: "btn big", type: "button", "aria-haspopup": "dialog", onClick: (e) => p._openGallery(e.currentTarget) }, icon("mdi:shape-plus-outline"), t("From template")));
  const homeErr = h("div", { class: "strip err", hidden: true, role: "alert" });
  m.homeErr = homeErr;
  homeScroll.append(h("div", { class: "mpad" }, homeErr, statusHost, cta, gridHead, grid));
  const homeTitle = h("h1", { class: "mtitle" }, t("Labels"));
  const homeTop = h("header", { class: "mtop" });
  const home = h("section", { class: "mhome", "aria-label": t("Your labels") }, homeTop, homeScroll);

  let connectState = null;   // { busy, text, kind }
  function statusCard(s) {
    const act = s.action;
    const busy = connectState?.busy;
    const btn = act === "setup" ? h("button", { class: "btn primary", type: "button", onClick: () => p._openWizard(false) }, icon("mdi:printer-settings"), t("Set up printer"))
      : act === "connect" ? h("button", { class: "btn primary", type: "button", disabled: !!busy, onClick: () => connectActive() }, busy ? h("span", { class: "spin" }) : icon("mdi:bluetooth-connect"), busy ? t("Connecting…") : t("Connect"))
        : h("button", { class: "btn", type: "button", onClick: () => p._openPrinters() }, icon("mdi:printer-settings"), t("Printers"));
    const second = act === "connect" ? h("button", { class: "btn", type: "button", onClick: () => p._openPrinters() }, t("Printers")) : null;
    return h("div", { class: `scard ${s.tone}`, role: s.tone === "err" ? "alert" : "status" },
      h("div", { class: "scard-ic" }, icon(s.kind === "setup" ? "mdi:printer-settings" : s.kind === "error" ? "mdi:printer-alert" : "mdi:printer-off-outline")),
      h("div", { class: "scard-t" }, h("strong", {}, t(s.title)), h("span", {}, t(s.text)),
        connectState?.text && h("span", { class: "scard-msg " + connectState.kind }, connectState.text),
        h("div", { class: "scard-acts" }, btn, second)));
  }
  async function connectActive() {
    const pr = p.printer; if (!pr || connectState?.busy) return;
    connectState = { busy: true, text: t("Trying to reach the printer… (up to 20 s)"), kind: "info" }; m.renderHome();
    try {
      const o = connectOutcome(await p.api.btConnect(pr.entry_id));
      connectState = { busy: false, text: t(o.text), kind: o.ok ? "ok" : "err" };
    } catch (e) { const f = failureSentence(e); connectState = { busy: false, text: f.text, kind: "err" }; }
    try { await p._refreshPrinters(); } catch { /* shown elsewhere */ }
    m.renderHome();
    setTimeout(() => { if (connectState && !connectState.busy) { connectState = null; m.renderHome(); } }, 6000);
  }

  function showThumb(c, v) {
    c.done = true; c.thumb.classList.remove("loading", "failed");
    c.thumb.replaceChildren(h("img", { src: v.src, alt: "", draggable: false }));
  }
  function loadThumb(c) {
    if (c.done || c.busy || c.failed) return;
    const tape = p.tape;
    const hit = thumbs.peek(tape, c.key);
    if (hit) { showThumb(c, hit); return; }
    c.busy = true; c.thumb.classList.add("loading");
    thumbs.get(tape, c.key, () => !c.visible || !c.node.isConnected).then((v) => { if (v) showThumb(c, v); })
      .catch(() => { c.failed = true; c.thumb.classList.remove("loading"); c.thumb.classList.add("failed"); c.thumb.replaceChildren(h("span", { class: "gal-fail" }, icon("mdi:image-off-outline"), t("Preview unavailable"))); })
      .finally(() => { c.busy = false; if (!c.done && !c.failed && c.visible && c.node.isConnected) setTimeout(() => loadThumb(c), 0); });
  }
  function observeThumbs() {
    thumbIO?.disconnect();
    if (typeof IntersectionObserver === "undefined") return null;
    thumbIO = new IntersectionObserver((entries) => {
      for (const en of entries) { const c = en.target._card; if (!c) continue; c.visible = en.isIntersecting; if (c.visible) loadThumb(c); }
    }, { root: homeScroll, rootMargin: "160px 0px" });
    return thumbIO;
  }
  function when(updated) {
    if (!updated) return "";
    const d = new Date(updated); if (Number.isNaN(+d)) return "";
    const days = Math.floor((Date.now() - +d) / 86400000);
    if (days <= 0) return t("Today"); if (days === 1) return t("Yesterday"); if (days < 7) return `${days} ${t("days ago")}`;
    return d.toLocaleDateString(undefined, { day: "numeric", month: "short" });
  }
  function labelCard(d) {
    const key = M.designKey(d);
    const thumb = h("div", { class: "lthumb" }, h("span", { class: "lthumb-ph" }, icon("mdi:label-outline")));
    const open = h("button", { class: "lopen", type: "button", "aria-label": `${t("Open")} ${d.name || d.id}`, onClick: () => p._open(d.id) }, thumb);
    const more = iconButton("mdi:dots-vertical", `${t("Options for")} ${d.name || d.id}`, () => labelMenu(d), { class: "ibtn lmore", "aria-haspopup": "dialog" });
    const node = h("div", { class: "lcard", role: "listitem" }, open,
      h("div", { class: "lmeta" }, h("button", { class: "lname", type: "button", onClick: () => p._open(d.id) }, h("strong", {}, d.name || d.id), h("span", {}, when(d.updated))), more));
    const c = { key, node, thumb, visible: !thumbIO, done: false, busy: false, failed: false };
    node._card = c;
    return c;
  }
  function labelMenu(d) {
    p._actionSheet(d.name || d.id, [
      { icon: "mdi:folder-open-outline", label: t("Open"), run: () => p._open(d.id) },
      { icon: "mdi:content-copy", label: t("Duplicate"), run: () => p._duplicateDesign(d.id) },
      { icon: "mdi:delete-outline", label: t("Delete"), danger: true, run: () => p._deleteDesign(d) },
    ]);
  }

  m.renderHome = () => {
    const s = p.s;
    homeTop.replaceChildren($.menu, homeTitle, h("span", { class: "grow" }), $.chip);
    const sc = M.homeStatus(s.printers, s.entryId, s.printersLoaded);
    statusHost.replaceChildren(...(sc ? [statusCard(sc)] : []));
    const io = observeThumbs();
    if (!s.designsLoaded) {
      gridHead.replaceChildren();
      grid.replaceChildren(...[0, 1, 2].map(() => h("div", { class: "lcard sk" }, h("div", { class: "lthumb loading" }), h("div", { class: "lmeta" }, h("span", { class: "sk-line" })))));
      return;
    }
    const list = [...s.designs].sort((a, b) => String(b.updated || "").localeCompare(String(a.updated || "")));
    gridHead.replaceChildren(...(list.length ? [h("h2", {}, t("Your labels")), h("span", { class: "muted" }, String(list.length))] : []));
    if (!list.length) {
      grid.replaceChildren(h("div", { class: "lempty" }, icon("mdi:label-multiple-outline"),
        h("strong", {}, t("No saved labels yet")),
        h("span", {}, t("Create a label or start from a template. Labels you save show up here."))));
      return;
    }
    const cards = list.map(labelCard);
    grid.replaceChildren(...cards.map((c) => c.node));
    if (io) for (const c of cards) io.observe(c.node); else for (const c of cards) loadThumb(c);
  };

  // ---- editor: top bar, sub strip, toolbar -------------------------------------------------------------------
  const back = iconButton("mdi:arrow-left", t("Back to your labels"), () => p._leaveEditor(), { class: "ibtn mback" });
  const undo2 = iconButton("mdi:undo", t("Undo"), () => p.store.undo(), { class: "ibtn u-sub" });
  const redo2 = iconButton("mdi:redo", t("Redo"), () => p.store.redo(), { class: "ibtn u-sub" });
  $.undo.classList.add("u-top"); $.redo.classList.add("u-top");
  const editTop = h("header", { class: "mtop etop" });
  const tapeChip = h("button", { class: "mchip", type: "button", "aria-haspopup": "dialog", onClick: () => { p.store.select(null); m.openSheet("label", "half"); } }, icon("mdi:ruler"), h("span", { class: "tc-a" }), h("span", { class: "tc-b" }));
  const saveChip = h("button", { class: "mchip save", type: "button", "aria-label": t("Save"), onClick: () => p._save() }, icon("mdi:content-save-outline"), t("Save"));
  const zoomChip = $.zoomChip;
  const sub = h("div", { class: "msub" }, tapeChip, saveChip, h("span", { class: "grow" }), undo2, redo2, zoomChip);
  const tbtn = (ic, label, fn, cls = "") => h("button", { class: "tbtn " + cls, type: "button", onClick: fn }, icon(ic), h("span", {}, label));
  const addBar = h("div", { class: "mtool tadd", role: "toolbar", "aria-label": t("Add to label") },
    tbtn("mdi:format-text", t("Text"), () => p._add("text")), tbtn("mdi:emoticon-outline", t("Icon"), () => p._add("icon")),
    tbtn("mdi:qrcode", t("QR code"), () => p._add("qr")), tbtn("mdi:barcode", t("Barcode"), () => p._add("barcode")),
    tbtn("mdi:dots-horizontal-circle-outline", t("More"), () => p._openLayer("add"), "more"));
  const bEdit = tbtn("mdi:pencil-outline", t("Edit"), () => p._editSel(), "main"), bDup = tbtn("mdi:content-copy", t("Copy"), () => p._dupSel()),
    bRot = tbtn("mdi:rotate-right", t("Rotate"), () => p._rotateSel()), bUp = tbtn("mdi:arrow-up-bold-box-outline", t("Raise"), () => p._reorderSel(1)),
    bDown = tbtn("mdi:arrow-down-bold-box-outline", t("Lower"), () => p._reorderSel(-1)), bDel = tbtn("mdi:delete-outline", t("Delete"), () => p._delSel(), "danger");
  const elBar = h("div", { class: "mtool tsel", role: "toolbar", "aria-label": t("Element actions") }, bEdit, bDup, bRot, bUp, bDown, bDel);

  // ---- bottom sheet -------------------------------------------------------------------------------------------
  const sTitle = h("span", { class: "grow" }), sIcon = h("span", { class: "sicon" });
  const sDel = iconButton("mdi:delete-outline", t("Delete element"), () => p._delSel(), { class: "ibtn sdel" });
  const sDone = h("button", { class: "btn primary sdone", type: "button", onClick: () => m.setSnap("closed") }, t("Done"));
  const grab = h("div", { class: "grab", role: "button", tabIndex: 0, "aria-label": t("Resize panel"), onKeydown: (e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); m.setSnap(M.cycleSnap(m.snap)); } } }, h("span", { class: "bar" }));
  const shead = h("div", { class: "shead" }, sIcon, sTitle, sDel, sDone);
  const sheet = h("div", { class: "bsheet", "data-snap": "closed", role: "dialog", "aria-label": t("Properties") }, grab, shead, $.sheetBody);
  const mmain = h("div", { class: "mmain" });
  const mbody = h("div", { class: "mbody" }, mmain, sheet);
  const edit = h("section", { class: "medit", "aria-label": t("Label editor") }, editTop, sub, h("div", { class: "mstrips" }, $.errStrip, $.warnStrip, $.msgStrip, $.printStrip), mbody);

  const side = () => !!window.matchMedia?.("(orientation:landscape) and (max-height:520px)").matches;
  m.snaps = () => M.sheetSnaps(mbody.clientHeight || 400, { minCanvas: m.kb ? 72 : 88 });
  m.applyHeight = () => {
    if (m.snap === "closed" || side()) { sheet.style.height = ""; return; }
    sheet.style.height = `${m.snaps()[m.kb ? "full" : m.snap]}px`;   // keyboard up: use all the room there is
  };
  m.setSnap = (snap, { fromPop = false } = {}) => {
    if (snap === m.snap) return;
    const was = m.snap; m.snap = snap;
    sheet.dataset.snap = snap;
    $.root.classList.toggle("sheet-open", snap !== "closed");
    if (snap === "closed") {
      if (!fromPop) m.pop("sheet");
      sheet.style.height = "";
      if (p.shadowRoot.activeElement && sheet.contains(p.shadowRoot.activeElement)) p.shadowRoot.activeElement.blur();
    } else {
      m.push("sheet");
      if (was === "closed" && !side()) { sheet.style.height = "0px"; void sheet.offsetHeight; }
      m.applyHeight();
    }
    m.renderToolbar();
    p._afterSheet();
  };
  m.openSheet = (mode, snap = "half") => {
    m.sheetFor = mode;
    p._renderInspector(true);
    m.renderSheetHead();
    $.sheetBody.scrollTop = 0;
    m.setSnap(snap);
  };
  m.renderSheetHead = () => {
    const e = p.store.selected;
    sTitle.textContent = e ? t(TYPE_NAMES[e.type] || e.type) : t("Label settings");
    sIcon.replaceChildren(icon(e ? TYPE_ICONS[e.type] || "mdi:shape" : "mdi:ruler"));
    sDel.hidden = !e;
  };
  // drag the grabber / header to resize
  let drag = null;
  const onSheetDown = (ev) => {
    if (side() || ev.target.closest("button:not(.grab)") || (ev.button != null && ev.button > 0)) return;
    const snaps = m.snaps();
    drag = { id: ev.pointerId, y0: ev.clientY, h0: sheet.getBoundingClientRect().height, snaps, samples: [{ t: performance.now(), y: ev.clientY }], moved: false };
    try { ev.currentTarget.setPointerCapture(ev.pointerId); } catch { /* ignore */ }
  };
  const onSheetMove = (ev) => {
    if (!drag || ev.pointerId !== drag.id) return;
    const dy = ev.clientY - drag.y0;
    if (!drag.moved && Math.abs(dy) < 5) return;
    if (!drag.moved) { drag.moved = true; sheet.classList.add("dragging"); }
    const hh = G.clamp(drag.h0 - dy, 40, drag.snaps.full);
    sheet.style.height = `${hh}px`; drag.h = hh;
    drag.samples.push({ t: performance.now(), y: ev.clientY }); if (drag.samples.length > 5) drag.samples.shift();
  };
  const onSheetUp = (ev) => {
    if (!drag || ev.pointerId !== drag.id) return;
    const d = drag; drag = null; sheet.classList.remove("dragging");
    if (!d.moved) { if (ev.currentTarget === grab) m.setSnap(M.cycleSnap(m.snap)); return; }
    const a = d.samples[0], b = d.samples[d.samples.length - 1], dt = Math.max(1, b.t - a.t);
    const vel = -(b.y - a.y) / dt;   // px/ms, positive = up
    const target = M.pickSnap(d.h ?? d.h0, vel, d.snaps);
    if (target === "closed") m.setSnap("closed"); else { if (target === m.snap) m.applyHeight(); else m.setSnap(target); }
  };
  for (const n of [grab, shead]) {
    n.addEventListener("pointerdown", onSheetDown); n.addEventListener("pointermove", onSheetMove);
    n.addEventListener("pointerup", onSheetUp); n.addEventListener("pointercancel", onSheetUp);
  }
  grab.style.touchAction = "none"; shead.style.touchAction = "none";

  // ---- print sheet (inside the modal layer) -------------------------------------------------------------------------
  const pvImg = h("img", { alt: t("Label preview"), draggable: false });
  const pvBox = h("div", { class: "pv" }, pvImg);
  const pbody = h("div", { class: "pbody" });
  const printSheet = h("div", { class: "msheet print-sheet", role: "dialog", "aria-label": t("Print label") },
    h("h3", {}, h("span", { class: "grow" }, t("Print label")), iconButton("mdi:close", t("Close"), () => p._closeLayer())),
    pvBox, pbody);
  m.printSheet = printSheet;
  m.renderPrint = () => {
    if ($.layer.dataset.mode !== "print") return;
    const f = p.printFlow, pr = p.printer, d = p.store.design;
    if (p.s.preview?.png) pvImg.src = `data:image/png;base64,${p.s.preview.png}`;
    const copies = p.s.copies;
    if (f.phase === "waiting") {
      pbody.replaceChildren(
        h("div", { class: "pstate wait", role: "status" }, h("span", { class: "spin big" }), h("strong", {}, t("Printing…")), h("span", {}, PL.waitingText(f))),
        h("button", { class: "btn big", type: "button", onClick: () => p._cancelPrintWait() }, t("Stop waiting")));
      return;
    }
    if (f.phase === "failed") {
      pbody.replaceChildren(
        h("div", { class: "pstate err", role: "alert" }, icon("mdi:alert-circle-outline"), h("strong", {}, t("Couldn't print")), h("span", {}, f.text || t("Printing failed."))),
        h("button", { class: "btn big primary", type: "button", onClick: () => { p.printFlow = PL.dismissPrint(p.printFlow); p._startPrint(); } }, icon("mdi:refresh"), t("Try again")),
        h("button", { class: "btn big", type: "button", onClick: () => { p.printFlow = PL.dismissPrint(p.printFlow); p._openPrinters(); } }, icon("mdi:printer-settings"), t("Printers")));
      return;
    }
    if (p.s.printDone) {
      const held = !!p._lastPrint?.chain;     // chain printing: the label is still inside
      pbody.replaceChildren(
        h("div", { class: "pstate ok", role: "status" }, icon("mdi:check-circle-outline"), h("strong", {}, t("Sent to the printer")),
          h("span", {}, held ? t("The label stays in the printer until the next print or Feed.")
            : p.s.printDone > 1 ? `${p.s.printDone} ${t("labels")}` : t("Take your label from the printer."))),
        ...(held ? [feedButton()] : []),
        h("button", { class: "btn big primary", type: "button", onClick: () => p._closeLayer() }, t("Done")));
      return;
    }
    const chip = PL.chipState(p.s.printers, p.s.entryId, p.s.printersLoaded);
    const tapeMismatch = pr?.tape_mm && p.s.tapeSel !== "auto" && pr.tape_mm !== p.s.tapeSel;
    const tapeOk = pr?.tape_mm && !tapeMismatch;
    const rows = [
      h("button", { class: "prow", type: "button", onClick: () => p._openPrinters() },
        h("span", { class: `dot ${chip.dot}` }), h("span", { class: "prow-t" }, h("strong", {}, chip.name), h("span", {}, t(pr ? PL.stateSentence(pr) : "No printer set up"))), icon("mdi:chevron-right")),
    ];
    if (pr) rows.push(h("div", { class: "prow static " + (tapeMismatch ? "warn" : "") }, icon(tapeMismatch ? "mdi:alert-outline" : tapeOk ? "mdi:check-circle-outline" : "mdi:label-outline"),
      h("span", { class: "prow-t" }, h("strong", {}, tapeMismatch ? t("Tape doesn't match") : tapeOk ? t("Tape matches") : t("Tape")),
        h("span", {}, tapeMismatch ? `${t("The printer has")} ${G.tapeLabel(pr.tape_mm)} ${t("loaded, this label is for")} ${G.tapeLabel(p.s.tapeSel)}.` : pr.tape ? PL.tapeLine(pr.tape) : t("No tape detected yet.")))));
    const minus = h("button", { class: "ibtn step", type: "button", "aria-label": t("Fewer copies"), disabled: copies <= 1, onClick: () => { p.s.copies = M.stepCopies(p.s.copies, -1); p.$.copies.value = p.s.copies; m.renderPrint(); } }, icon("mdi:minus"));
    const plus = h("button", { class: "ibtn step", type: "button", "aria-label": t("More copies"), disabled: copies >= 20, onClick: () => { p.s.copies = M.stepCopies(p.s.copies, 1); p.$.copies.value = p.s.copies; m.renderPrint(); } }, icon("mdi:plus"));
    rows.push(h("div", { class: "prow static" }, h("span", { class: "prow-t" }, h("strong", {}, t("Copies"))), h("div", { class: "stepper" }, minus, h("output", { "aria-live": "polite" }, String(copies)), plus)));
    rows.push(...cuttingRows());
    rows.push(h("button", { class: "btn big primary go", type: "button", disabled: !d.elements.length || !pr, onClick: () => p._startPrint() }, icon("mdi:printer"), tapeMismatch ? t("Print anyway") : copies > 1 ? `${t("Print")} ${copies} ${t("labels")}` : t("Print")));
    pbody.replaceChildren(...rows);
  };
  const cutToggle = (key, label, hint) => {
    const box = h("input", { type: "checkbox", "aria-label": label, onChange: () => p._setCutting(key, box.checked) });
    box.checked = !!p.s[key];
    return h("label", { class: "prow static" }, h("span", { class: "prow-t" }, h("strong", {}, label), h("span", {}, hint)), box);
  };
  const feedButton = () => h("button", { class: "btn big", type: "button", disabled: !!p._feeding, onClick: () => p._feed() },
    icon("mdi:arrow-expand-right"), p._feeding ? t("Feeding…") : t("Feed tape"));
  const cuttingRows = () => {
    const cut = p.cutOption;
    return [cutToggle("chain", t("Chain"), t("No feed between prints. The label stays inside until the next print or Feed.")),
      cutToggle(cut.key, cut.label, cut.hint), feedButton()];
  };

  // ---- cutting and feed sheet (editor menu) ----------------------------------------------------------------------
  const cbody = h("div", { class: "pbody" });
  m.cutSheet = h("div", { class: "msheet cut-sheet", role: "dialog", "aria-label": t("Cutting and feed") },
    h("h3", {}, h("span", { class: "grow" }, t("Cutting and feed")), iconButton("mdi:close", t("Close"), () => p._closeLayer())),
    cbody);
  m.renderCut = () => {
    if ($.layer.dataset.mode !== "cut") return;
    cbody.replaceChildren(...cuttingRows());
  };

  // ---- action sheet (editor menu, label card menu) ---------------------------------------------------------------------------
  // built by the panel into $.menuSheet; see panel._actionSheet

  // ---- toast -----------------------------------------------------------------------------------------------------------------
  const toast = h("div", { class: "toast", role: "status", "aria-live": "polite", hidden: true });
  let toastT = null;
  m.toast = (text, ms = 2600) => {
    toast.textContent = text; toast.hidden = false; toast.classList.remove("show"); void toast.offsetWidth; toast.classList.add("show");
    clearTimeout(toastT); toastT = setTimeout(() => { toast.hidden = true; }, ms);
  };

  // ---- per-state rendering -------------------------------------------------------------------------------------------------------------
  m.renderToolbar = () => {
    const sel = p.store.selected, els = p.store.design.elements;
    const mode = M.toolbarMode({ hasSelection: !!sel, sheetOpen: m.snap !== "closed", keyboard: m.kb > 0 });
    addBar.hidden = mode !== "add"; elBar.hidden = mode !== "element";
    bUp.disabled = !sel || els[els.length - 1] === sel; bDown.disabled = !sel || els[0] === sel;
    $.root.classList.toggle("tool-none", mode === "none");
  };
  m.renderEditor = () => {
    const d = p.store.design;
    editTop.replaceChildren(back, $.name, $.undo, $.redo, $.print, $.more);
    tapeChip.querySelector(".tc-a").textContent = G.tapeLabel(p.tape);
    tapeChip.querySelector(".tc-b").textContent = d.length_mm != null && d.length_mm !== "" ? ` · ${Math.round(Number(d.length_mm))} mm` : ` · ${t("auto length")}`;
    saveChip.hidden = !p.store.dirty;
    saveChip.disabled = !!p.s.busy;
    undo2.disabled = !p.store.canUndo; redo2.disabled = !p.store.canRedo;
    zoomChip.textContent = p.s.fit ? t("Fit") : `${Math.round(p.s.zoom * 100)}%`;
    m.renderToolbar();
  };
  m.render = () => {
    if (!m.enabled) return;
    if (p.s.view === "home") m.renderHome(); else { m.renderEditor(); }
  };

  // ---- placing shared nodes -------------------------------------------------------------------------------------------------------------------
  const mobile = h("div", { class: "mobile" }, home, edit, toast);
  m.el = mobile;
  m.place = (narrow) => {
    if (narrow) {
      mmain.replaceChildren($.scroller, addBar, elBar);
      sheet.insertBefore($.sheetBody, null);
      $.zoomChip.hidden = false;
      m.enabled = true;
    } else {
      $.center.replaceChildren($.ctoolbar, $.msgStrip, $.errStrip, $.warnStrip, $.scroller, $.actionbar);
      $.right.append($.sheetBody);
      m.enabled = false;
      m.setSnap("closed", { fromPop: true });
      st.reset();
    }
  };

  // reveal the selected element and keep the fit zoom when the canvas area changes size (sheet, keyboard, rotation)
  let rafId = 0;
  const ro = new ResizeObserver(() => {
    if (rafId) return;
    rafId = requestAnimationFrame(() => {
      rafId = 0;
      if (!m.enabled || p.s.view !== "edit") return;
      if (m.snap !== "closed" && !side() && !sheet.classList.contains("dragging")) m.applyHeight();
      p._refit(); if (m.snap !== "closed" || m.kb) p._revealSelected();
    });
  });
  ro.observe($.scroller); ro.observe(mbody);

  return m;
}
