// Brother P-touch label editor: Home Assistant custom panel (plain ES module, no build step).
import { Api, Previewer } from "./lib/api.js";
import { Store, emptyDesign, newElement } from "./lib/store.js";
import * as G from "./lib/geometry.js";
import { h, icon, iconButton, storage } from "./lib/ui.js";
import { createFontPicker, createIconPicker, fontInfo, nearestWeight, ALL_WEIGHTS } from "./lib/pickers.js";
import { CSS } from "./lib/styles.js";
import { MOBILE_CSS } from "./lib/styles_mobile.js";
import { createMobile } from "./lib/mobile_ui.js";
import * as M from "./lib/mobile.js";
import { createGallery } from "./lib/gallery.js";
import { createPrinterDrawer, createWizard } from "./lib/printer_ui.js";
import * as PL from "./lib/printer_logic.js";
import { failureSentence, canRetry, reasonText } from "./lib/reasons.js";

const t = (s) => s;
const TYPE_ICONS = { text: "mdi:format-text", icon: "mdi:emoticon-outline", qr: "mdi:qrcode", barcode: "mdi:barcode", rect: "mdi:rectangle-outline", image: "mdi:image-outline" };
const TYPE_NAMES = { text: "Text", icon: "Icon", qr: "QR code", barcode: "Barcode", rect: "Rectangle", image: "Image" };
const ZOOMS = [0.5, 1, 2, 3, 4, 5, 6];
const ECC = ["l", "m", "q", "h"];
const BARCODES = ["code128", "code39", "ean13", "ean8", "upca", "itf", "codabar"];
const NARROW_PX = M.NARROW_PX;
const SESSION_KEY = "brother_ptouch.session";
const ssGet = () => { try { return JSON.parse(sessionStorage.getItem(SESSION_KEY) || "null"); } catch { return null; } };
const ssSet = (v) => { try { if (v) sessionStorage.setItem(SESSION_KEY, JSON.stringify(v)); else sessionStorage.removeItem(SESSION_KEY); } catch { /* ignore */ } };

class BrotherPtouchPanel extends HTMLElement {
  constructor() {
    super();
    this.attachShadow({ mode: "open" });
    this.store = new Store();
    this.api = null;
    this.printFlow = PL.newPrintFlow();
    this.s = {
      tapeSel: storage.get("tape", "auto"), entryId: storage.get("entry", ""), copies: 1,
      chain: storage.get("chain", false), cutMark: storage.get("cutMark", false), autoCut: storage.get("autoCut", true),
      zoom: 3, fit: storage.get("zoomMode", "fit") === "fit", printers: [], printersLoaded: false, designs: [], designsLoaded: false, view: "home", printDone: 0,
      testValues: {}, preview: null, previewUrl: "", error: "", warnings: [],
      busy: "", layout: "wide",
    };
    this.s.zoom = storage.get("zoom", 3);
    this._coarseMQ = window.matchMedia ? window.matchMedia("(pointer: coarse)") : null;
    this._coarse = !!this._coarseMQ?.matches;
    // slower phones: wait longer before asking the server for a new preview
    this.previewer = new Previewer(() => this._runPreview(), (m) => this._onPreview(m), this._coarse ? { delay: 250, maxWait: 800 } : {});
    this._els = new Map(); this._drag = null; this._inspSig = ""; this._sync = [];
    this._ptrs = new Map(); this._pan = null; this._pinch = null; this._placed = ""; this._baseH = 0;
    this._buildShell();
    this.store.subscribe((what) => this._onStore(what));
  }

  // ---- HA integration -------------------------------------------------
  set hass(hass) {
    this._hass = hass;
    if (!this.api) { this.api = new Api(hass); this._init(); } else this.api.hass = hass;
  }
  get hass() { return this._hass; }
  set panel(p) { this._panel = p; }
  set route(_) { /* unused */ }
  set narrow(v) { this._haNarrow = !!v; this._applyLayout(); }
  get narrow() { return this._haNarrow; }

  connectedCallback() {
    this._ro = new ResizeObserver(() => this._applyLayout());
    this._ro.observe(this);
    this.m?.resetNav();
    this._keyHandler = (e) => this._onKey(e);
    this.addEventListener("keydown", this._keyHandler);
    this._vvHandler = () => this._onViewport();
    window.visualViewport?.addEventListener("resize", this._vvHandler);
    window.visualViewport?.addEventListener("scroll", this._vvHandler);
    window.addEventListener("orientationchange", this._vvHandler);
    this._applyLayout();
  }
  disconnectedCallback() {
    this._ro?.disconnect(); this.removeEventListener("keydown", this._keyHandler); this.previewer.cancel();
    window.visualViewport?.removeEventListener("resize", this._vvHandler);
    window.visualViewport?.removeEventListener("scroll", this._vvHandler);
    window.removeEventListener("orientationchange", this._vvHandler);
    this._abortDrag(); cancelAnimationFrame(this._inertiaRaf); clearInterval(this._pTick);
    this.m?.resetNav();
  }

  async _init() {
    this._renderAll();
    const narrow = this._isNarrow();
    const plan = narrow ? M.restorePlan(this._historyBp(), ssGet()) : { view: "wide" };
    if (narrow && plan.fixHistory === "reset") { try { history.replaceState({ ...(history.state || {}), bp: undefined }, ""); } catch { /* ignore */ } }
    this._renderHome();
    await this._refreshPrinters(true);
    await this._refreshDesigns();
    if (!narrow) {
      const last = storage.get("lastDesign", "");
      if (last && this.s.designs.some((d) => d.id === last)) await this._open(last, true);
      else this.previewer.request();
      return;
    }
    if (plan.view === "edit") await this._restoreSession(plan);
  }
  _historyBp() { try { return history.state?.bp; } catch { return undefined; } }
  _isNarrow() { const w = this.clientWidth || this.getBoundingClientRect().width || window.innerWidth; return M.isNarrowWidth(w); }
  async _restoreSession(plan) {
    const ss = ssGet(); if (!ss) return;
    try {
      let d = ss.design;
      if (!d && ss.id) d = await this.api.getDesign(ss.id);
      if (!d) return;
      this.store.load(d, { saved: !ss.dirty });
      if (plan.fixHistory === "back") { this.m.expectBack(); this.m.enabled = true; try { history.back(); } catch { /* ignore */ } }
      this.m.enabled = true;
      this._showEditor({ restore: true });
    } catch { ssSet(null); }
  }

  /** Re-fetch the printer rows (normalised); keeps the active printer if it still exists. */
  async _refreshPrinters(initial = false) {
    const pins = this.pins;
    try { this.s.printers = (await this.api.printers()).map(PL.normalizePrinter); }
    catch (e) { if (initial) this._notify(e.message || String(e), "err"); else throw e; }
    finally { this.s.printersLoaded = true; }
    const id = PL.pickActive(this.s.printers, this.s.entryId);
    if (id !== this.s.entryId) { const had = this.s.entryId; this.s.entryId = id; if (had !== id) this.previewer?.request(); }
    storage.set("entry", this.s.entryId);
    this._renderTop();
    if (this.pins !== pins) this._renderCanvas();   // the printer's dots per tape can differ
    if (this.printerDrawer && !this.$.layer.hidden && this.$.layer.dataset.mode === "printers") this.printerDrawer.render();
  }
  _selectPrinter(id) { this.s.entryId = id; storage.set("entry", id); this._renderTop(); this.previewer.request(); }

  // ---- shell -----------------------------------------------------------
  _buildShell() {
    const sr = this.shadowRoot;
    sr.append(h("style", {}, CSS + MOBILE_CSS));
    this.$ = {};
    const $ = this.$;

    // top bar
    $.menu = iconButton("mdi:menu", t("Menu"), () => this.dispatchEvent(new Event("hass-toggle-menu", { bubbles: true, composed: true })), { class: "ibtn hamburger" });
    $.name = h("input", { type: "text", class: "name", "aria-label": t("Design name"), placeholder: t("Design name"), enterkeyhint: "done", onInput: () => this.store.setMeta({ name: $.name.value }, "name") });
    $.dirty = h("span", { class: "dirty-dot", title: t("Unsaved changes") });
    $.tape = h("select", { "aria-label": t("Tape width"), onChange: () => { this.s.tapeSel = $.tape.value === "auto" ? "auto" : Number($.tape.value); storage.set("tape", this.s.tapeSel); this._refit(); this.previewer.request(); this._renderTop(); } });
    $.lenMode = h("select", { "aria-label": t("Length mode"), onChange: () => {
      if ($.lenMode.value === "auto") this.store.setMeta({ length_mm: null });
      else this.store.setMeta({ length_mm: this.store.design.length_mm ?? Math.max(5, Math.round(G.dotsToMm(G.labelLengthDots(this.store.design)))) });
      this._refit();
    } }, h("option", { value: "auto" }, t("Auto length")), h("option", { value: "fixed" }, t("Fixed length")));
    $.lenMm = h("input", { type: "number", min: 5, max: 1000, step: 1, inputmode: "decimal", "aria-label": t("Length in mm"), onInput: () => { const v = parseFloat($.lenMm.value); if (v > 0) this.store.setMeta({ length_mm: v }, "len"); } });
    $.undo = iconButton("mdi:undo", t("Undo (Ctrl+Z)"), () => this.store.undo());
    $.redo = iconButton("mdi:redo", t("Redo (Ctrl+Y)"), () => this.store.redo());
    $.chipDot = h("span", { class: "dot grey", "aria-hidden": "true" });
    $.chipName = h("span", { class: "chip-name" }); $.chipStatus = h("span", { class: "chip-status" });
    $.chip = h("button", { class: "printer-chip", type: "button", "aria-haspopup": "dialog", onClick: () => this._openPrinters() }, $.chipDot, $.chipName, $.chipStatus, icon("mdi:chevron-down"));
    $.pbar = h("div", { class: "pbar" });
    $.copies = h("input", { type: "number", min: 1, max: 20, value: 1, inputmode: "numeric", "aria-label": t("Copies"), title: t("Copies"), onInput: () => { this.s.copies = Math.min(20, Math.max(1, parseInt($.copies.value) || 1)); } });
    // cutting and feed: chain, auto cut or cut marks (see cutOption), feed
    $.chain = h("input", { type: "checkbox", onChange: () => this._setCutting("chain", $.chain.checked) });
    $.cut = h("input", { type: "checkbox", onChange: () => this._setCutting(this.cutOption.key, $.cut.checked) });
    $.cutText = h("span");
    $.cutLabel = h("label", { class: "small tb-check" }, $.cut, $.cutText);
    $.feed = h("button", { class: "btn", type: "button", title: t("Feed the tape out to cut the last label"), onClick: () => this._feed() },
      icon("mdi:arrow-expand-right"), h("span", { class: "lbl" }, t("Feed")));
    $.cutWrap = h("div", { class: "tb-group" },
      h("label", { class: "small tb-check", title: t("No feed between prints: the next label follows right after this one. The last label stays inside until you print again or feed.") }, $.chain, t("Chain")),
      $.cutLabel, $.feed);
    $.save = h("button", { class: "btn save", type: "button", "aria-label": t("Save"), onClick: () => this._save() }, icon("mdi:content-save-outline"), h("span", { class: "lbl" }, t("Save")));
    $.print = h("button", { class: "btn primary", type: "button", "aria-label": t("Print"), onClick: () => this._print() }, icon("mdi:printer"), h("span", { class: "lbl" }, t("Print")));
    $.setup = h("button", { class: "btn primary setup-btn", type: "button", "aria-haspopup": "dialog", hidden: true, onClick: () => this._openWizard(false) },
      icon("mdi:printer-settings"), h("span", { class: "lbl" }, t("Set up your printer")), h("span", { class: "lbl-s" }, t("Set up printer")));
    $.printStrip = h("div", { class: "pstrip", hidden: true, "aria-live": "polite" });
    $.more = iconButton("mdi:dots-vertical", t("More options"), () => this._openEditorMenu(), { class: "ibtn emore", "aria-haspopup": "dialog" });
    $.copiesWrap = h("div", { class: "tb-group" }, h("label", { class: "small" }, t("Copies")), $.copies);
    $.gTape = h("div", { class: "tb-group" }, $.tape);
    $.gLen = h("div", { class: "tb-group" }, $.lenMode, $.lenMm);
    $.spacer = h("div", { class: "spacer" });
    $.hist = h("div", { class: "tb-group", role: "toolbar", "aria-label": t("History") }, $.undo, $.redo);
    $.topbar = h("div", { class: "topbar" });

    // palette (left pane on desktop, bottom sheet on phones)
    const add = (type, label, ic) => h("button", { class: "btn", type: "button", onClick: () => this._add(type) }, icon(ic), label);
    $.palette = h("div", { class: "palette", role: "toolbar", "aria-label": t("Add element") },
      add("text", t("Text"), "mdi:format-text"), add("icon", t("Icon"), "mdi:emoticon-outline"), add("qr", t("QR code"), "mdi:qrcode"),
      add("barcode", t("Barcode"), "mdi:barcode"), add("rect", t("Rectangle"), "mdi:rectangle-outline"), add("line", t("Line"), "mdi:minus"),
      h("button", { class: "btn", type: "button", onClick: () => $.file.click() }, icon("mdi:image-plus-outline"), t("Image")));
    // not inside a pane that may be display:none; no `capture` attribute so the OS offers camera AND gallery/files
    $.file = h("input", { type: "file", accept: "image/*", class: "sr", tabIndex: -1, "aria-hidden": "true", onChange: () => this._addImage() });
    $.paletteBox = h("div", { class: "section" }, h("h3", {}, t("Add")), $.palette);
    $.designs = h("div", { class: "list" });
    $.tplBtn = h("button", { class: "btn tpl-btn", type: "button", "aria-haspopup": "dialog", onClick: (e) => this._openGallery(e.currentTarget) }, icon("mdi:shape-plus-outline"), t("From template"));
    $.layers = h("div", { class: "list" });
    $.left = h("aside", { class: "pane left", "aria-label": t("Designs and layers") }, $.paletteBox,
      h("div", { class: "section" }, h("h3", {}, h("span", { class: "grow" }, t("Designs"))),
        h("div", { class: "newrow" },
          h("button", { class: "btn", type: "button", onClick: () => this._new() }, icon("mdi:plus"), t("New")),
          $.tplBtn),
        $.designs),
      h("div", { class: "section" }, h("h3", {}, t("Layers")), $.layers));

    // centre
    $.zoomSel = h("select", { class: "zoomsel", "aria-label": t("Zoom"), onChange: () => this._setZoom($.zoomSel.value) },
      h("option", { value: "fit" }, t("Fit")), ZOOMS.map((z) => h("option", { value: z }, `${z * 100}%`)), h("option", { value: "custom", hidden: true }, ""));
    $.zoomChip = h("button", { class: "zoomchip", type: "button", "aria-label": t("Zoom: tap to reset"), title: t("Tap to reset zoom"), onClick: () => this._setZoom("fit") });
    $.zoomOut = iconButton("mdi:magnify-minus-outline", t("Zoom out"), () => this._stepZoom(-1));
    $.zoomIn = iconButton("mdi:magnify-plus-outline", t("Zoom in"), () => this._stepZoom(1));
    $.tRotate = iconButton("mdi:rotate-right", t("Rotate 90° (R)"), () => this._rotateSel());
    $.tDup = iconButton("mdi:content-copy", t("Duplicate (Ctrl+D)"), () => this._dupSel());
    $.tFront = iconButton("mdi:arrow-up-bold-box-outline", t("Bring forward"), () => this._reorderSel(1));
    $.tBack = iconButton("mdi:arrow-down-bold-box-outline", t("Send backward"), () => this._reorderSel(-1));
    $.tDel = iconButton("mdi:delete-outline", t("Delete (Del)"), () => this._delSel());
    $.tools = h("div", { class: "tools" }, $.tRotate, $.tDup, $.tFront, $.tBack, $.tDel);
    $.readout = h("div", { class: "readout", "aria-live": "off" });
    $.sep = h("span", { class: "sep" });
    $.ctoolbar = h("div", { class: "ctoolbar", role: "toolbar", "aria-label": t("Canvas tools") });
    $.actionbar = h("div", { class: "actionbar" });
    $.warnStrip = h("div", { class: "strip warn", hidden: true, role: "status" });
    $.errStrip = h("div", { class: "strip err", hidden: true, role: "alert" });
    $.msgStrip = h("div", { class: "strip info", hidden: true, role: "status" });
    $.ruler = h("div", { class: "ruler" });
    $.img = h("img", { alt: t("Label preview"), draggable: false });
    $.overlay = h("div", { class: "overlay" });
    $.empty = h("div", { class: "empty-hint" }, h("span", {}, t("Add an element to start")),
      h("button", { class: "btn", type: "button", onClick: (e) => this._openGallery(e.currentTarget) }, icon("mdi:shape-plus-outline"), t("Start from a template")));
    $.stage = h("div", { class: "stage", tabIndex: 0, role: "application", "aria-label": t("Label canvas. Arrow keys move the selected element.") }, $.img, $.overlay, $.empty);
    $.scroller = h("div", { class: "scroller" }, h("div", { class: "canvas-wrap" }, $.ruler, $.stage));
    $.center = h("main", { class: "pane center" }, $.ctoolbar, $.msgStrip, $.errStrip, $.warnStrip, $.scroller, $.actionbar);

    // right pane = inspector (becomes a bottom sheet on phones)
    $.insp = h("div", { class: "section" });
    $.vars = h("div", { class: "section" });
    $.sheetBody = h("div", { class: "sheet-body" }, $.insp, $.vars);
    $.right = h("aside", { class: "pane right", "aria-label": t("Properties") }, $.sheetBody);

    // modal layer (phones): add palette, overflow menu, confirm dialog
    $.addSheet = h("div", { class: "msheet add-sheet", role: "dialog", "aria-label": t("Add element") }, h("h3", {}, h("span", { class: "grow" }, t("Add to label")), iconButton("mdi:close", t("Close"), () => this._closeLayer())));
    $.menuSheet = h("div", { class: "msheet menu-sheet", role: "dialog" });
    $.dlgText = h("p"); $.dlgOk = h("button", { class: "btn primary", type: "button" }); $.dlgCancel = h("button", { class: "btn", type: "button" }, t("Cancel"));
    $.dlgAlt = h("button", { class: "btn", type: "button", hidden: true });
    $.dialog = h("div", { class: "dialog", role: "alertdialog", "aria-modal": "true" }, $.dlgText, h("div", { class: "acts" }, $.dlgCancel, $.dlgAlt, $.dlgOk));
    this.m = createMobile(this, t);
    this.gallery = createGallery({ api: { templatesList: () => this.api.templatesList(), buildTemplate: (id, tape) => this.api.buildTemplate(id, tape, this.s.entryId || undefined), preview: (d, o) => this.api.preview(d, { ...o, entry_id: this.s.entryId || undefined }) },
      t, getTape: () => this.tape, onPick: (tpl) => this._newFromTemplate(tpl), onClose: () => this._closeLayer() });
    // the api object is created when hass arrives: components call through this proxy
    const lazy = new Proxy({}, { get: (_, k) => (...a) => this.api[k](...a) });
    this.printerDrawer = createPrinterDrawer({ api: lazy, t, getPrinters: () => this.s.printers, getActive: () => this.s.entryId,
      refresh: () => this._refreshPrinters(), onSelect: (id) => this._selectPrinter(id), onAdd: () => this._openWizard(true),
      onClose: () => this._closeLayer(), confirm: (m, o) => this._confirm(m, o) });
    this.wizard = createWizard({ api: lazy, t, getPrinters: () => this.s.printers, refresh: () => this._refreshPrinters(),
      onClose: () => this._closeWizard(), onDone: (id) => this._wizardDone(id) });
    $.layer = h("div", { class: "layer", hidden: true, onClick: (e) => { if (e.target === $.layer) this._closeLayer(); } }, $.addSheet, $.menuSheet, this.m.printSheet, this.m.cutSheet, this.gallery.el, this.printerDrawer.el, this.wizard.el, $.dialog);

    $.body = h("div", { class: "body" }, $.left, $.center, $.right);
    $.root = h("div", { class: "root", "data-view": "edit" }, $.topbar, $.body, this.m.el, $.layer, $.file);
    sr.append($.root);
    this.m.init();
    this._placeNodes(false);

    this._initGestures();
    sr.addEventListener("focusin", (e) => this._onFocusIn(e));
    sr.addEventListener("focusout", () => setTimeout(() => this._onViewport(), 60));
    this._coarseMQ?.addEventListener?.("change", (e) => { this._coarse = e.matches || this._touchSeen; this._applyLayout(); });
  }

  /** Move shared controls between their desktop and phone homes (same nodes, so state is kept). */
  _placeNodes(narrow) {
    const key = narrow ? "n" : "w";
    if (this._placed === key) return;
    this._placed = key;
    const $ = this.$;
    this._inspSig = "\u0000";
    if (narrow) {
      $.ctoolbar.replaceChildren();
    } else {
      $.topbar.replaceChildren($.menu, $.name, $.dirty, $.gTape, $.gLen, $.spacer, $.hist, $.chip, $.copiesWrap, $.cutWrap, $.save, $.setup, $.print);
      $.hist.replaceChildren($.undo, $.redo);
      $.copiesWrap.append($.copies);
      $.gTape.append($.tape); $.gLen.append($.lenMode, $.lenMm);
      $.ctoolbar.replaceChildren($.zoomOut, $.zoomSel, $.zoomIn, $.sep, $.tools, $.readout);
      $.paletteBox.append($.palette);
      $.zoomChip.hidden = true;
    }
    this.m.place(narrow);
    if (narrow) $.addSheet.append($.palette);
    this._renderInspector(true);
  }

  // ---- view switching (phones): home <-> editor ------------------------------------------------
  _showEditor({ restore = false } = {}) {
    this.s.view = "edit";
    if (this.s.layout === "narrow") {
      if (restore) this.m.adopt("edit"); else this.m.push("edit");
    }
    this._applyLayout();
    this._persistSession(true);
    this.m.renderEditor();
    requestAnimationFrame(() => { this.s.fit = true; this._refit(); this.$.scroller.scrollLeft = 0; this.$.scroller.scrollTop = 0; });
  }
  /** Back arrow / hardware Back in the editor. Resolves true when the editor was left. */
  async _leaveEditor({ fromPop = false } = {}) {
    if (this.s.view !== "edit") return true;
    if (this.printFlow.phase === "waiting") this._cancelPrintWait();
    if (this.store.dirty) {
      const c = await this._choose(t("Save changes to this label before leaving?"), [
        { key: "save", label: t("Save"), primary: true }, { key: "discard", label: t("Discard changes"), danger: true }, { key: "cancel", label: t("Keep editing") }]);
      if (c === "save") { const ok = await this._save(); if (!ok) return false; }
      else if (c !== "discard") return false;
    }
    this._goHome(fromPop);
    return true;
  }
  _goHome(fromPop = false) {
    this.m.setSnap("closed", { fromPop: false });
    if (!fromPop) this.m.pop("edit");
    this.previewer.cancel();
    this.store.load(emptyDesign()); this.s.preview = null;
    this.s.view = "home"; ssSet(null); storage.set("lastDesign", "");
    this.p_homeScroll = true;
    this._applyLayout(); this._renderHome();
    this._refreshDesigns();
  }
  _renderHome() { this.m.renderHome(); }
  _persistSession(now = false) {
    if (this.s.view !== "edit" || this.s.layout !== "narrow") return;
    const go = () => { const d = this.store.design; ssSet({ id: d.id || "", dirty: this.store.dirty, design: this.store.dirty || !d.id ? d : null }); };
    clearTimeout(this._ssT);
    if (now) go(); else this._ssT = setTimeout(go, 400);
  }

  /** Bottom sheet helpers */
  _afterSheet() { requestAnimationFrame(() => { this._refit(); this._revealSelected(); }); }

  // ---- modal layer: add palette, menus, print sheet, confirm (no window.confirm: blocked/ugly in WebViews) ----
  _openLayer(mode) { this.$.layer.dataset.mode = mode; this.$.layer.hidden = false; }
  _closeLayerFromBack() { if (this.$.layer.dataset.mode === "wizard") this._closeWizard(); else this._closeLayer(); }
  _closeLayer() {
    if (this._dlgResolve) { const r = this._dlgResolve; this._dlgResolve = null; r(false); }
    const wasGallery = this.$.layer.dataset.mode === "gallery";
    const wasPrinter = ["printers", "wizard"].includes(this.$.layer.dataset.mode);
    if (this.$.layer.dataset.mode === "wizard") this.wizard.abort();
    this.printerDrawer?.close();
    this.$.layer.hidden = true; this.$.layer.dataset.mode = "";
    if (wasGallery) this._restoreFocus();
    if (wasPrinter) { const o = this._printerOpener; this._printerOpener = null; if (o?.isConnected) { try { o.focus({ preventScroll: true }); } catch { /* ignore */ } } else this.$.chip.focus?.({ preventScroll: true }); }
  }
  _restoreFocus() { const o = this._galleryOpener; this._galleryOpener = null; if (o?.isConnected) { try { o.focus({ preventScroll: true }); } catch { /* ignore */ } } }
  /** In-app dialog with several buttons; resolves the chosen key ("" when dismissed). */
  _choose(message, buttons) {
    const $ = this.$;
    this._confirmFromGallery = this.$.layer.dataset.mode === "gallery" && !this.$.layer.hidden;
    const backToDrawer = this.$.layer.dataset.mode === "printers" && !this.$.layer.hidden;
    if (this._dlgResolve) { const r = this._dlgResolve; this._dlgResolve = null; r(""); }
    return new Promise((resolve) => {
      $.dlgText.textContent = message;
      const [primary, ...others] = buttons;   // first = primary, last = cancel
      const cancel = others.pop();
      const fill = (btn, def) => { btn.hidden = !def; if (!def) return; btn.textContent = def.label; btn.className = "btn" + (def.primary ? " primary" : "") + (def.danger ? " danger" : ""); btn.onclick = () => done(def.key); };
      const done = (v) => {
        this._dlgResolve = null; $.layer.hidden = true; $.layer.dataset.mode = "";
        if (!v && this._confirmFromGallery) { this._confirmFromGallery = false; this._showGallery(false); }
        if (backToDrawer) { $.layer.dataset.mode = "printers"; $.layer.hidden = false; }
        resolve(v);
      };
      this._dlgResolve = (v) => resolve(v ? v : "");
      fill($.dlgOk, primary); fill($.dlgAlt, others[0]); fill($.dlgCancel, cancel);
      $.dlgCancel.hidden = false;
      this._openLayer("confirm"); $.dlgCancel.focus();
    });
  }
  async _confirm(message, { ok = t("OK"), danger = false } = {}) {
    return (await this._choose(message, [{ key: "ok", label: ok, primary: true, danger }, { key: "", label: t("Cancel") }])) === "ok";
  }
  /** Bottom action sheet: items = [{icon, label, run, danger, disabled}]. */
  _actionSheet(title, items) {
    const $ = this.$;
    $.menuSheet.replaceChildren(h("h3", {}, h("span", { class: "grow" }, title), iconButton("mdi:close", t("Close"), () => this._closeLayer())),
      ...items.map((it) => h("button", { class: "asheet-item" + (it.danger ? " danger" : ""), type: "button", disabled: !!it.disabled,
        onClick: () => { this._closeLayer(); it.run(); } }, icon(it.icon), it.label)));
    $.menuSheet.setAttribute("aria-label", title);
    this._openLayer("menu");
  }
  _openEditorMenu() {
    const d = this.store.design;
    this._actionSheet(t("Label options"), [
      { icon: "mdi:content-save-outline", label: t("Save"), run: () => this._save(), disabled: !!this.s.busy },
      { icon: "mdi:ruler", label: t("Tape and length"), run: () => { this.store.select(null); this.m.openSheet("label", "half"); } },
      { icon: "mdi:content-cut", label: t("Cutting and feed"), run: () => { this._openLayer("cut"); this.m.renderCut(); } },
      { icon: "mdi:fit-to-screen-outline", label: t("Fit label to screen"), run: () => this._setZoom("fit") },
      { icon: "mdi:shape-plus-outline", label: t("Start from a template"), run: () => this._openGallery(this.$.more) },
      { icon: "mdi:delete-outline", label: t("Delete this label"), danger: true, disabled: !d.id, run: () => this._deleteDesign({ id: d.id, name: d.name }) },
    ]);
  }

  _applyLayout() {
    if (!this.$) return;
    const w = this.clientWidth || this.getBoundingClientRect().width;
    const narrow = w > 0 && w < NARROW_PX;
    const $ = this.$;
    $.root.classList.toggle("narrow", narrow);
    $.root.classList.toggle("has-menu", narrow && !!this._haNarrow);
    $.root.classList.toggle("coarse", !!(this._coarse || this._touchSeen));
    if (w > 0 && !narrow) this.s.view = "edit";
    $.root.dataset.view = this.s.view;
    this._ensureHeight();
    this._placeNodes(narrow);
    if (!narrow) this._closeLayerIfPhoneOnly();
    if (this.s.layout !== (narrow ? "narrow" : "wide")) { this.s.layout = narrow ? "narrow" : "wide"; if (this.s.fit) this.s.zoomKey = ""; }
    if (narrow) this.m.render();
    if (this.s.fit) this._refit();
  }
  /** Defensive: if the host chain gives us no height (height:100% of an auto parent), fill the viewport below our top edge. */
  _ensureHeight() {
    const r = this.getBoundingClientRect();
    if (this._fixedH) { this.style.height = ""; this._fixedH = false; }
    if (r.width > 0 && this.clientHeight < 160) {
      const hh = Math.max(240, window.innerHeight - Math.max(0, r.top));
      this.style.height = `${hh}px`; this._fixedH = true;
    }
  }
  _closeLayerIfPhoneOnly() { const m = this.$.layer.dataset.mode; if (m === "add" || m === "menu" || m === "print") this._closeLayer(); }

  // ---- derived state ---------------------------------------------------
  get printer() { return this.s.printers.find((p) => p.entry_id === this.s.entryId) || null; }
  get tape() {
    if (this.s.tapeSel !== "auto") return this.s.tapeSel;
    return this.s.preview?.tape_mm ?? this.printer?.tape_mm ?? 12;
  }
  get pins() { return G.tapePins(this.tape, this.printer?.tape_pins); }
  /** The cut toggle: auto cut on printers with a cutter, cut marks on those without. */
  get cutOption() {
    return this.printer?.has_cutter === false
      ? { key: "cutMark", label: t("Cut marks"), hint: t("Print a cut mark after every label.") }
      : { key: "autoCut", label: t("Auto cut"), hint: t("Cut the tape after printing.") };
  }
  get labelW() { const d = this.store.design; return d.elements.length || d.length_mm != null ? G.labelLengthDots(d) : 140; }
  get offX() { return G.contentOffsetX(this.store.design); }
  get zoom() { return this.s.zoom; }
  _testVars() {
    const out = {};
    for (const [k, v] of Object.entries(this.s.testValues)) if (v !== "" && k in this.store.design.variables) out[k] = v;
    return out;
  }

  // ---- store events ----------------------------------------------------
  _onStore(what) {
    if (what === "load") {
      this.s.testValues = {}; this._inspSig = "\u0000";   // force a re-render (stale sync callbacks must not run)
      this._refit();
    }
    if (this._drag?.moved) {
      // hot path while a finger/mouse drags: only touch the overlay and readout; the rest is rendered at the end
      this._patchOverlay(); this._renderReadout(); this._renderRuler();
      if (!this._drag.touch) this.previewer.request();
      return;
    }
    const n = this.store.design.elements.length;
    if (what === "design" && this.s.fit && (this.s.layout !== "narrow" || n !== this._lastCount)) this._refit();
    this._lastCount = n;
    if (what === "design" || what === "load" || what === "meta") this.previewer.request();
    this._renderTop(); this._renderLayers(); this._patchOverlay(); this._renderInspector(); this._renderVars(); this._renderReadout();
    if (what === "load" || what === "design") this._renderRuler();
    if (this.s.layout === "narrow") {
      if (what === "selection") this._onPhoneSelection();
      if (what === "design" || what === "meta") this._persistSession();
      if (what === "load" && this.s.view === "edit") this._persistSession(true);
    }
  }
  /** Selection changed on a phone: a sheet opened for an element closes when the selection is cleared; its title follows. */
  _onPhoneSelection() {
    const m = this.m;
    if (m.snap !== "closed") {
      if (!this.store.selected && m.sheetFor === "element") m.setSnap("closed");
      else { m.sheetFor = this.store.selected ? "element" : "label"; this._renderInspector(true); this.$.sheetBody.scrollTop = 0; m.renderSheetHead(); }
    }
    m.renderToolbar();
    if (this.store.selected) requestAnimationFrame(() => this._revealSelected());
  }

  _renderAll() {
    this._renderTop(); this._renderDesigns(); this._renderLayers(); this._renderInspector(true); this._renderVars(true); this._renderCanvas(); this._applyLayout();
  }

  _renderTop() {
    const $ = this.$, d = this.store.design;
    if (this.shadowRoot.activeElement !== $.name) $.name.value = d.name || "";
    $.root.classList.toggle("dirty", this.store.dirty);
    $.undo.disabled = !this.store.canUndo; $.redo.disabled = !this.store.canRedo;
    const p = this.printer;
    $.tape.replaceChildren(h("option", { value: "auto" }, `${t("From printer")}${p?.tape_mm ? ` (${G.tapeLabel(p.tape_mm)})` : ""}`),
      ...G.TAPES.map((x) => h("option", { value: x.value }, x.label)));
    $.tape.value = String(this.s.tapeSel);
    const fixed = d.length_mm != null && d.length_mm !== "";
    $.lenMode.value = fixed ? "fixed" : "auto";
    $.lenMm.hidden = !fixed; if (fixed && this.shadowRoot.activeElement !== $.lenMm) $.lenMm.value = d.length_mm;
    const cs = PL.chipState(this.s.printers, this.s.entryId, this.s.printersLoaded);
    $.chipDot.className = "dot " + cs.dot; $.chipName.textContent = t(cs.name); $.chipStatus.textContent = t(cs.status);
    $.chip.title = t(cs.title); $.chip.setAttribute("aria-label", `${t("Printer")}: ${cs.name}, ${cs.status}. ${t("Open printer list")}`);
    const first = this.s.printersLoaded && !this.s.printers.length;   // first run: no printer yet
    $.root.classList.toggle("first-run", first);
    $.print.disabled = !!this.s.busy || !d.elements.length || this.printFlow.phase === "waiting";
    const cut = this.cutOption;
    $.chain.checked = this.s.chain; $.cut.checked = !!this.s[cut.key];
    $.cutText.textContent = cut.label; $.cutLabel.title = cut.hint;
    $.feed.disabled = !!this._feeding || this.printFlow.phase === "waiting";
    $.print.classList.toggle("waiting", this.printFlow.phase === "waiting");
    $.save.disabled = !!this.s.busy;
    const sel = this.store.selected;
    for (const b of [$.tRotate, $.tDup, $.tDel]) b.disabled = !sel;
    const els = this.store.design.elements;
    $.tFront.disabled = !sel || els[els.length - 1] === sel;
    $.tBack.disabled = !sel || this.store.design.elements[0] === sel;
    $.empty.hidden = d.elements.length > 0;
    $.setup.hidden = !first || this.s.layout === "narrow"; $.print.hidden = first && this.s.layout !== "narrow";
    if (this.s.layout === "narrow" && this.m.enabled) { if (this.s.view === "edit") this.m.renderEditor(); else this.m.renderHome(); }
  }

  _renderDesigns() {
    const cur = this.store.design.id;
    if (this.s.layout === "narrow" && this.s.view === "home") this.m.renderHome();
    this.$.designs.replaceChildren(...(this.s.designs.length ? this.s.designs.map((d) =>
      h("div", { class: "item" + (d.id === cur ? " sel" : "") },
        h("button", { class: "label", type: "button", onClick: () => this._open(d.id) }, icon("mdi:label-outline"), h("span", {}, d.name || d.id)),
        iconButton("mdi:content-copy", t("Duplicate design"), () => this._duplicateDesign(d.id)),
        iconButton("mdi:delete-outline", t("Delete design"), () => this._deleteDesign(d))))
      : [h("div", { class: "hint" }, t("No saved designs yet"))]));
  }

  _renderLayers() {
    const els = this.store.design.elements, sel = this.store.selection;
    this.$.layers.replaceChildren(...(els.length ? [...els].reverse().map((e) =>
      h("div", { class: "item" + (e.id === sel ? " sel" : "") },
        h("button", { class: "label", type: "button", onClick: () => this.store.select(e.id) }, icon(TYPE_ICONS[e.type] || "mdi:shape"), h("span", {}, this._elLabel(e)))))
      : [h("div", { class: "hint" }, t("Nothing yet"))]));
  }
  _elLabel(e) {
    const v = e.type === "text" ? e.text : e.type === "icon" ? e.icon : e.type === "qr" || e.type === "barcode" ? e.data : "";
    const name = e.type === "rect" && e.fill ? t("Line / bar") : t(TYPE_NAMES[e.type] || e.type);
    return v ? `${name}: ${String(v).replace(/\s+/g, " ").slice(0, 24)}` : name;
  }

  _renderReadout() {
    const d = this.store.design, sel = this.store.selected;
    const mm = (v) => G.dotsToMm(v).toFixed(1);
    this.$.readout.textContent = sel
      ? `${sel.x},${sel.y}  ${sel.w}×${sel.h} dots  (${mm(sel.w)}×${mm(sel.h)} mm)`
      : `${this.labelW}×${this.pins} dots  (${mm(this.labelW)}×${mm(this.pins)} mm)`;
  }

  // ---- canvas ----------------------------------------------------------
  _setZoom(v, { keep = false } = {}) {
    if (v === "fit") { this.s.fit = true; this._refit(); } else { this.s.fit = false; this.s.zoom = Number(v); }
    storage.set("zoomMode", this.s.fit ? "fit" : "n"); storage.set("zoom", this.s.zoom);
    this._renderCanvas();
  }
  _stepZoom(dir) {
    const i = ZOOMS.findIndex((z) => z >= this.s.zoom - 1e-6);
    let n;
    if (i >= 0 && Math.abs(ZOOMS[i] - this.s.zoom) > 1e-6 && dir < 0) n = ZOOMS[Math.max(0, i - 1)];
    else n = ZOOMS[Math.min(ZOOMS.length - 1, Math.max(0, (i < 0 ? ZOOMS.length - 1 : i) + dir))];
    this._zoomAbout(n, null);
    storage.set("zoomMode", "n"); storage.set("zoom", this.s.zoom);
  }
  /** Zoom to `z`, keeping the content point under viewport point `c` (default: the centre) fixed. */
  _zoomAbout(z, c) {
    const sc = this.$.scroller, pad = this._pad();
    const c0 = c || { x: sc.clientWidth / 2, y: sc.clientHeight / 2 };
    const v = G.pinchView({ z0: this.s.zoom, d0: 1, d1: z / this.s.zoom, c0, c1: c0, scroll0: { x: sc.scrollLeft, y: sc.scrollTop }, pad });
    this.s.fit = false; this.s.zoom = v.zoom;
    this._renderCanvas();
    sc.scrollLeft = v.scrollX; sc.scrollTop = v.scrollY;
  }
  /** Offset of the stage inside the scroller's scrollable content (padding + ruler). */
  _pad() {
    const sc = this.$.scroller, st = this.$.stage;
    const a = sc.getBoundingClientRect(), b = st.getBoundingClientRect();
    return { x: b.left - a.left + sc.scrollLeft, y: b.top - a.top + sc.scrollTop };
  }
  _refit() {
    if (!this.s.fit) return;
    const narrow = this.s.layout === "narrow";
    const cw = this.$.scroller.clientWidth;
    if (narrow && !cw) return;   // hidden (home view): fitted when the editor opens
    const avail = (cw || 600) - (narrow ? 56 : 36);   // phones: room for the selection handles (22 px outside the label) on both sides
    this.s.zoom = narrow ? M.fitWidthZoom(this.labelW, avail) : G.fitZoom(this.labelW, avail);
    this._renderCanvas();
  }

  _renderCanvas() {
    const $ = this.$, z = this.zoom, W = this.labelW, H = this.pins;
    if (this.s.fit) $.zoomSel.value = "fit";
    else if (ZOOMS.includes(z)) $.zoomSel.value = String(z);
    else { const c = $.zoomSel.querySelector("option[value=custom]"); c.textContent = `${Math.round(z * 100)}%`; c.hidden = false; $.zoomSel.value = "custom"; }
    $.zoomChip.textContent = this.s.fit ? t("Fit") : `${Math.round(z * 100)}%`;
    $.stage.style.width = `${W * z}px`; $.stage.style.height = `${H * z}px`;
    const pv = this.s.preview;
    if (pv) { $.img.style.width = `${pv.width * z}px`; $.img.style.height = `${pv.height * z}px`; }
    this._renderRuler(); this._patchOverlay(); this._renderReadout();
  }

  _renderRuler() {
    const z = this.zoom, W = this.labelW;
    const key = `${W}@${z}`;
    if (key === this._rulerKey) return;
    this._rulerKey = key;
    const ppm = z * G.DOTS_PER_MM, step = G.rulerStep(z);
    const wpx = Math.ceil(W * z), mm = W / G.DOTS_PER_MM;
    let s = `<svg width="${wpx + 30}" height="22" xmlns="http://www.w3.org/2000/svg" aria-hidden="true"><g stroke="currentColor" stroke-width="1" fill="currentColor" font-size="10" font-family="sans-serif">`;
    for (let m = 0; m <= mm + 1e-6; m += step) {
      const x = Math.round(m * ppm) + 0.5, major = (m % (step * 5) === 0) || step >= 10;
      s += `<line x1="${x}" x2="${x}" y1="${major ? 8 : 14}" y2="22"/>`;
      if (major) s += `<text x="${x + 3}" y="10" stroke="none">${m}</text>`;
    }
    s += `</g></svg>`;
    this.$.ruler.innerHTML = s;
  }

  _patchOverlay() {
    const $ = this.$, z = this.zoom, offX = this.offX, d = this.store.design, sel = this.store.selection;
    $.stage.style.width = `${this.labelW * z}px`; $.stage.style.height = `${this.pins * z}px`;
    if (this.s.preview) { $.img.style.width = `${this.s.preview.width * z}px`; $.img.style.height = `${this.s.preview.height * z}px`; }
    const seen = new Set(), n = d.elements.length;
    d.elements.forEach((e, i) => {
      seen.add(e.id);
      let node = this._els.get(e.id);
      if (!node) {
        node = h("div", { class: "el", "data-id": e.id, onPointerdown: (ev) => this._onElDown(ev, e.id) });
        this._els.set(e.id, node); $.overlay.append(node);
      }
      const wPx = e.w * z, hPx = e.h * z;
      node.style.left = `${(e.x + offX) * z}px`; node.style.top = `${e.y * z}px`;
      node.style.width = `${wPx}px`; node.style.height = `${hPx}px`;
      node.style.zIndex = e.id === sel ? n + 10 : i + 1;   // selected element (and its handles) always on top
      node.style.setProperty("--px", `${G.hitPad(wPx)}px`); node.style.setProperty("--py", `${G.hitPad(hPx)}px`);
      node.title = this._elLabel(e);
      const isSel = e.id === sel;
      node.classList.toggle("sel", isSel);
      const hs = G.handlesFor(wPx, hPx);
      node.classList.toggle("outside", hs.outside);
      const sig = isSel ? hs.list.join() : "";
      if (node.dataset.hs !== sig) {
        node.querySelectorAll(".handle").forEach((x) => x.remove());
        node.dataset.hs = sig;
        if (isSel) for (const hd of hs.list) {
          const [fx, fy] = G.handleFraction(hd);
          node.append(h("div", { class: "handle", "data-h": hd, style: { left: `${fx * 100}%`, top: `${fy * 100}%`, cursor: G.HANDLE_CURSORS[hd], "--hx": (fx - 0.5) * 2, "--hy": (fy - 0.5) * 2 }, onPointerdown: (ev) => this._onHandleDown(ev, e.id, hd) }));
        }
      }
    });
    for (const [id, node] of this._els) if (!seen.has(id)) { node.remove(); this._els.delete(id); }
  }

  _bounds(excludeId) {
    const d = this.store.design, fixed = d.length_mm != null && d.length_mm !== "";
    let w = this.labelW;
    if (!fixed) { w = 0; for (const e of d.elements) if (e.id !== excludeId) w = Math.max(w, e.x + e.w); }
    return { w, h: this.pins };
  }

  // ---- pointer interaction: drag / resize with a finger or a mouse -----------
  _isBg(t) { const $ = this.$; return t === $.stage || t === $.img || t === $.scroller || t === $.empty || t === $.overlay || t?.classList?.contains("canvas-wrap") || t === $.ruler || !!t?.closest?.(".ruler"); }
  _onElDown(ev, id) {
    if (ev.button !== 0 && ev.pointerType === "mouse") return;
    ev.stopPropagation(); ev.preventDefault();
    if (this._pinch || this._ptrs.size > 1) return;
    this.$.stage.focus({ preventScroll: true });
    this.store.select(id);
    const e = this.store.element(id);
    this._startDrag(ev, { mode: "move", id, box: { x: e.x, y: e.y, w: e.w, h: e.h } });
  }
  _onHandleDown(ev, id, handle) {
    ev.stopPropagation(); ev.preventDefault();
    if (this._pinch || this._ptrs.size > 1) return;
    const e = this.store.element(id);
    this._startDrag(ev, { mode: "resize", handle, id, box: { x: e.x, y: e.y, w: e.w, h: e.h }, immediate: true });
  }

  _startDrag(ev, drag) {
    this._abortDrag();
    const sc = this.$.scroller, node = ev.currentTarget;
    const d = this._drag = { ...drag, sx: ev.clientX, sy: ev.clientY, sl: sc.scrollLeft, st: sc.scrollTop, moved: !!drag.immediate, pid: ev.pointerId,
      touch: ev.pointerType === "touch" || ev.pointerType === "pen", t0: Date.now(), last: { x: ev.clientX, y: ev.clientY, alt: false, shift: false }, raf: 0, node };
    try { node.setPointerCapture(ev.pointerId); } catch { /* not capturable (e.g. synthetic): window listeners still work */ }
    d.move = (e) => this._onDragMove(e);
    d.up = (e) => { if (e.pointerId === d.pid) this._finishDrag(e, e.type === "pointercancel"); };
    window.addEventListener("pointermove", d.move); window.addEventListener("pointerup", d.up); window.addEventListener("pointercancel", d.up);
    if (d.mode === "move") d.lp = setTimeout(() => this._longPress(), 520);
  }
  _detachDrag(d) {
    clearTimeout(d.lp); cancelAnimationFrame(d.raf); cancelAnimationFrame(d.edgeRaf);
    window.removeEventListener("pointermove", d.move); window.removeEventListener("pointerup", d.up); window.removeEventListener("pointercancel", d.up);
    try { d.node.releasePointerCapture(d.pid); } catch { /* already released */ }
  }
  _onDragMove(ev) {
    const d = this._drag; if (!d || ev.pointerId !== d.pid) return;
    d.last = { x: ev.clientX, y: ev.clientY, alt: ev.altKey, shift: ev.shiftKey };
    if (!d.moved) { if (Math.hypot(ev.clientX - d.sx, ev.clientY - d.sy) < (d.touch ? 8 : 3)) return; d.moved = true; clearTimeout(d.lp); }
    if (!d.raf) d.raf = requestAnimationFrame(() => { d.raf = 0; this._applyDrag(); });
    this._edgeScroll();
  }
  /** Apply the latest pointer position (at most once per frame). */
  _applyDrag() {
    const d = this._drag; if (!d || !d.moved) return;
    const sc = this.$.scroller, L = d.last;
    this.store.beginGesture();
    const dx = (L.x - d.sx + (sc.scrollLeft - d.sl)) / this.zoom, dy = (L.y - d.sy + (sc.scrollTop - d.st)) / this.zoom;
    const el = this.store.element(d.id); if (!el) return;
    if (d.mode === "move") {
      let box = { ...d.box, x: Math.round(d.box.x + dx), y: Math.round(d.box.y + dy) };
      let guides = [];
      if (!L.alt) {
        const others = this.store.design.elements.filter((e) => e.id !== d.id);
        const sn = G.snapMove(box, this._bounds(d.id), others, Math.max(1.5, (d.touch ? 10 : 6) / this.zoom));
        box = { ...box, x: sn.x, y: sn.y }; guides = sn.guides;
      }
      this._showGuides(guides);
      this.store.updateElement(d.id, { x: box.x, y: box.y });
    } else {
      const keep = L.shift || ["icon", "qr", "image"].includes(el.type);
      this.store.updateElement(d.id, G.resizeBox(d.box, d.handle, dx, dy, { min: 2, keepAspect: keep }));
    }
  }
  /** While dragging near the edge of the canvas viewport, scroll it (long labels). */
  _edgeScroll() {
    const d = this._drag; if (!d || d.edgeRaf || !d.touch) return;
    const tick = () => {
      d.edgeRaf = 0;
      if (this._drag !== d || !d.moved) return;
      const sc = this.$.scroller, r = sc.getBoundingClientRect(), x = d.last.x, y = d.last.y, m = 36, sp = 10;
      const vx = x < r.left + m ? -sp : x > r.right - m ? sp : 0, vy = y < r.top + m ? -sp : y > r.bottom - m ? sp : 0;
      if (!vx && !vy) return;
      const l0 = sc.scrollLeft, t0 = sc.scrollTop;
      sc.scrollLeft += vx; sc.scrollTop += vy;
      if (sc.scrollLeft !== l0 || sc.scrollTop !== t0) this._applyDrag();
      d.edgeRaf = requestAnimationFrame(tick);
    };
    d.edgeRaf = requestAnimationFrame(tick);
  }
  _finishDrag(ev, cancelled) {
    const d = this._drag; if (!d) return;
    this._detachDrag(d); this._drag = null;
    if (cancelled && d.moved) this.store.updateElement(d.id, { ...d.box });
    else if (d.moved) { d.last = { ...d.last, x: ev.clientX, y: ev.clientY }; this._drag = d; this._applyDrag(); this._drag = null; }
    this._showGuides([]); this.store.endGesture();
    if (d.moved) { this._onStore("design"); if (d.touch) this.previewer.request(); return; }
    if (cancelled || d.mode !== "move" || d.lpFired) return;
    // a tap: double tap / double click edits the element
    const now = Date.now(), lt = this._lastTap;
    if (lt && lt.id === d.id && now - lt.t < 380 && Math.hypot(lt.x - ev.clientX, lt.y - ev.clientY) < 30) { this._lastTap = null; this._editSel(); }
    else this._lastTap = { id: d.id, t: now, x: ev.clientX, y: ev.clientY };
  }
  _abortDrag() {
    const d = this._drag; if (!d) return;
    this._detachDrag(d); this._drag = null;
    if (d.moved) this.store.updateElement(d.id, { ...d.box });
    this._showGuides([]); this.store.endGesture();
    if (d.moved) this._onStore("design");
  }
  _longPress() {
    const d = this._drag; if (!d || d.moved) return;
    d.lpFired = true; try { navigator.vibrate?.(12); } catch { /* ignore */ }
    this._editSel();
  }
  /** Open the inspector (sheet on phones) and focus the main text field, if any. Runs inside the user gesture so the keyboard may open. */
  _editSel() {
    const el = this.store.selected; if (!el) return;
    if (this.s.layout === "narrow") this.m.openSheet("element", this.m.snap === "closed" ? "half" : this.m.snap);
    const f = this.$.insp.querySelector("textarea") || (["barcode", "icon"].includes(el.type) ? this.$.insp.querySelector("input[type=text]") : null);
    if (f) { f.focus({ preventScroll: true }); try { f.setSelectionRange(f.value.length, f.value.length); } catch { /* ignore */ } }
  }
  /** Scroll the canvas so the selected element is visible above the sheet / keyboard. */
  _revealSelected() {
    const e = this.store.selected; if (!e) return;
    const sc = this.$.scroller, z = this.zoom, pad = this._pad();
    sc.scrollLeft = G.revealRange(pad.x + e.x * z, pad.x + (e.x + e.w) * z, sc.scrollLeft, sc.clientWidth);
    sc.scrollTop = G.revealRange(pad.y + e.y * z, pad.y + (e.y + e.h) * z, sc.scrollTop, sc.clientHeight);
  }

  // ---- canvas gestures: one finger pans the background, two fingers pinch-zoom + pan ----
  _initGestures() {
    const sc = this.$.scroller;
    sc.addEventListener("pointerdown", (e) => this._gDown(e), true);
    sc.addEventListener("pointermove", (e) => this._gMove(e));
    sc.addEventListener("pointerup", (e) => this._gUp(e));
    sc.addEventListener("pointercancel", (e) => this._gUp(e, true));
    sc.addEventListener("lostpointercapture", (e) => { if (this._pan?.id === e.pointerId && !this._pan.done) this._gUp(e, true); });
    sc.addEventListener("wheel", (e) => {   // trackpad pinch / Ctrl+wheel
      if (!e.ctrlKey) return;
      e.preventDefault();
      const r = sc.getBoundingClientRect();
      this._zoomAbout(G.clamp(this.zoom * Math.exp(-e.deltaY * 0.01), 0.25, 8), { x: e.clientX - r.left, y: e.clientY - r.top });
    }, { passive: false });
    // belt and braces for engines that ignore touch-action: never scroll/refresh the page from the canvas
    sc.addEventListener("touchmove", (e) => { if (e.cancelable) e.preventDefault(); }, { passive: false });
    sc.addEventListener("contextmenu", (e) => e.preventDefault());
    this.$.stage.addEventListener("pointerdown", (e) => { if (e.pointerType === "mouse" && e.button === 0 && this._isBg(e.target)) { this.store.select(null); this.$.stage.focus(); } });
  }
  _rel(e) { const r = this.$.scroller.getBoundingClientRect(); return { x: e.clientX - r.left, y: e.clientY - r.top }; }
  _gDown(e) {
    if (e.pointerType !== "touch") return;
    if (!this._touchSeen) { this._touchSeen = true; this.$.root.classList.add("coarse"); this._patchOverlay(); }
    cancelAnimationFrame(this._inertiaRaf);
    this._ptrs.set(e.pointerId, { x: e.clientX, y: e.clientY });
    if (this._ptrs.size === 2) { this._abortDrag(); this._endPan(); this._startPinch(); }
    else if (this._ptrs.size === 1 && this._isBg(e.target)) this._startPan(e);
  }
  _gMove(e) {
    const p = this._ptrs.get(e.pointerId); if (!p) return;
    p.x = e.clientX; p.y = e.clientY;
    if (this._pinch) { this._pinch.dirty = true; if (!this._pinch.raf) this._pinch.raf = requestAnimationFrame(() => { if (this._pinch) { this._pinch.raf = 0; this._applyPinch(); } }); }
    else if (this._pan && this._pan.id === e.pointerId) this._movePan(e);
  }
  _gUp(e, cancelled) {
    if (!this._ptrs.has(e.pointerId)) return;
    this._ptrs.delete(e.pointerId);
    if (this._pinch) {
      if (this._ptrs.size < 2) { this._applyPinch(); this._endPinch(); }
      return;
    }
    const pan = this._pan;
    if (pan && pan.id === e.pointerId) {
      pan.done = true; this._pan = null;
      if (!pan.moved && !cancelled && pan.bg) this.store.select(null);
      else if (pan.moved && !cancelled) this._inertia(pan);
    }
  }
  _startPan(e) {
    const sc = this.$.scroller;
    this._pan = { id: e.pointerId, sx: e.clientX, sy: e.clientY, sl: sc.scrollLeft, st: sc.scrollTop, moved: false, bg: true, samples: [{ t: performance.now(), x: e.clientX, y: e.clientY }] };
    try { sc.setPointerCapture(e.pointerId); } catch { /* ignore */ }
  }
  _movePan(e) {
    const p = this._pan, sc = this.$.scroller;
    if (!p.moved && Math.hypot(e.clientX - p.sx, e.clientY - p.sy) < 6) return;
    p.moved = true;
    sc.scrollLeft = p.sl - (e.clientX - p.sx); sc.scrollTop = p.st - (e.clientY - p.sy);
    p.samples.push({ t: performance.now(), x: e.clientX, y: e.clientY }); if (p.samples.length > 5) p.samples.shift();
  }
  _endPan() { if (this._pan) { this._pan.done = true; try { this.$.scroller.releasePointerCapture(this._pan.id); } catch { /* ignore */ } this._pan = null; } }
  _inertia(pan) {
    const s = pan.samples, a = s[0], b = s[s.length - 1], dt = b.t - a.t;
    if (s.length < 2 || dt <= 0 || performance.now() - b.t > 80) return;
    let vx = -(b.x - a.x) / dt, vy = -(b.y - a.y) / dt;   // px per ms
    const sc = this.$.scroller;
    let last = performance.now();
    const step = (now) => {
      const f = Math.min(40, now - last); last = now;
      sc.scrollLeft += vx * f; sc.scrollTop += vy * f;
      const k = Math.pow(0.0025, f / 1000); vx *= k; vy *= k;    // decays to ~0 in about a second
      if (Math.hypot(vx, vy) > 0.02) this._inertiaRaf = requestAnimationFrame(step);
    };
    if (Math.hypot(vx, vy) > 0.15) this._inertiaRaf = requestAnimationFrame(step);
  }
  _pinchPts() { const [a, b] = [...this._ptrs.values()]; return [this._relPt(a), this._relPt(b)]; }
  _relPt(p) { const r = this.$.scroller.getBoundingClientRect(); return { x: p.x - r.left, y: p.y - r.top }; }
  _startPinch() {
    const sc = this.$.scroller, [a, b] = this._pinchPts();
    this._pinch = { z0: this.s.zoom, d0: Math.max(1, G.pointDist(a, b)), c0: G.pointMid(a, b), scroll0: { x: sc.scrollLeft, y: sc.scrollTop }, pad: this._pad(), raf: 0, dirty: false };
  }
  _applyPinch() {
    const pz = this._pinch; if (!pz || this._ptrs.size < 2) return;
    const [a, b] = this._pinchPts();
    const v = G.pinchView({ z0: pz.z0, d0: pz.d0, d1: Math.max(1, G.pointDist(a, b)), c0: pz.c0, c1: G.pointMid(a, b), scroll0: pz.scroll0, pad: pz.pad });
    this.s.fit = false; this.s.zoom = v.zoom;
    this._renderCanvas();
    const sc = this.$.scroller; sc.scrollLeft = v.scrollX; sc.scrollTop = v.scrollY;
  }
  _endPinch() {
    cancelAnimationFrame(this._pinch.raf); this._pinch = null;
    storage.set("zoomMode", "n"); storage.set("zoom", this.s.zoom);
    // a finger that stays down after the pinch continues as a pan
    const rest = [...this._ptrs.entries()][0];
    if (rest) this._startPan({ pointerId: rest[0], clientX: rest[1].x, clientY: rest[1].y, target: null });
    if (this._pan) this._pan.bg = false;
  }

  _showGuides(guides) {
    this.$.stage.querySelectorAll(".guide").forEach((n) => n.remove());
    for (const g of guides) {
      const off = g.axis === "x" ? this.offX : 0;
      this.$.stage.append(h("div", { class: `guide ${g.axis}`, style: g.axis === "x" ? { left: `${(g.pos + off) * this.zoom}px` } : { top: `${g.pos * this.zoom}px` } }));
    }
  }

  // ---- preview ---------------------------------------------------------
  async _runPreview() {
    const d = this.store.design;
    const jobs = new Map();
    for (const e of d.elements) if (e.type === "text" && e.font) jobs.set(`${e.font}|${e.weight || 400}|${!!e.italic}`, e);
    await Promise.all([...jobs.values()].map((e) => this.api.ensureFont(e.font, e.weight || 400, !!e.italic).catch(() => {})));
    return this.api.preview(d, {
      tape_mm: this.s.tapeSel === "auto" ? undefined : this.s.tapeSel,
      entry_id: this.s.entryId || undefined, variables: this._testVars(),
    });
  }
  _onPreview(m) {
    const $ = this.$;
    if ("loading" in m) $.stage.classList.toggle("loading", m.loading);
    if (m.error) {
      this.s.error = m.error.message || String(m.error);
      $.errStrip.hidden = false; $.errStrip.textContent = this.s.error;
    }
    if (m.result) {
      const r = m.result, hadTape = this.tape;
      this.s.preview = r; this.s.error = ""; $.errStrip.hidden = true;
      $.img.src = `data:image/png;base64,${r.png}`;
      this.s.warnings = r.warnings || [];
      $.warnStrip.hidden = !this.s.warnings.length;
      $.warnStrip.replaceChildren(icon("mdi:alert-outline"), h("div", {}, this.s.warnings.join(" · ")));
      if (hadTape !== this.tape && this.s.fit) this._refit(); else this._renderCanvas();
      this._renderTop();
    }
  }

  // ---- on-screen keyboard / visual viewport -------------------------------------
  _isEditable(n) { return !!n && (n.tagName === "TEXTAREA" || (n.tagName === "INPUT" && !["checkbox", "radio", "file", "button"].includes(n.type))); }
  _onFocusIn(e) {
    if (this.s.layout !== "narrow" || !this._isEditable(e.composedPath()[0])) return;
    const el = e.composedPath()[0];
    setTimeout(() => { this._onViewport(); try { el.scrollIntoView({ block: "nearest", inline: "nearest", behavior: "smooth" }); } catch { /* ignore */ } this._revealSelected(); }, 320);
  }
  /** Soft keyboard: shrink the panel to the visible area (visualViewport) so the sheet sits above the keyboard. */
  _onViewport() {
    const root = this.$?.root; if (!root) return;
    const narrow = this.s.layout === "narrow";
    const kb = narrow ? M.kbInset(this.getBoundingClientRect().bottom, window.visualViewport) : 0;
    this._setKbInset(kb);
  }
  _setKbInset(kb) {
    const root = this.$.root;
    if (kb === this.m.kb) return;
    this.m.kb = kb;
    root.classList.toggle("kb-open", kb > 0);
    root.style.setProperty("--bp-kb", `${kb}px`);
    this.m.renderToolbar();
    this._refit();
    requestAnimationFrame(() => { if (this.m.snap !== "closed") this.m.applyHeight(); this._revealSelected(); });
  }

  // ---- actions ---------------------------------------------------------
  _notify(text, kind = "info", ms = 3500) {
    if (kind === "err") {
      this.$.errStrip.hidden = false; this.$.errStrip.textContent = text;
      this.m.homeErr.hidden = false; this.m.homeErr.textContent = text;
      clearTimeout(this._errT); this._errT = setTimeout(() => { this.m.homeErr.hidden = true; }, 8000);
      return;
    }
    if (this.s.layout === "narrow") { this.m.toast(text, ms); return; }
    const s = this.$.msgStrip;
    s.hidden = false; s.textContent = text;
    clearTimeout(this._msgT); this._msgT = setTimeout(() => { s.hidden = true; }, ms);
  }
  async _guard(label, fn) {
    this.s.busy = label; this._renderTop();
    try { return await fn(); }
    catch (e) { this._notify(`${label}: ${e.message || e}`, "err"); }
    finally { this.s.busy = ""; this._renderTop(); }
  }
  async _refreshDesigns() {
    try { this.s.designs = await this.api.listDesigns(); } catch (e) { this._notify(e.message || String(e), "err"); }
    this.s.designsLoaded = true;
    this._renderDesigns();
  }
  async _confirmDiscard() { return !this.store.dirty || this._confirm(t("Discard unsaved changes?"), { ok: t("Discard"), danger: true }); }
  async _open(id, silent) {
    if (!silent && !(await this._confirmDiscard())) return;
    await this._guard(t("Open failed"), async () => {
      const d = await this.api.getDesign(id);
      this.store.load(d); storage.set("lastDesign", id); this._renderDesigns();
      if (this.s.layout === "narrow") this._showEditor();
    });
  }
  async _new() {
    if (!(await this._confirmDiscard())) return;
    this.store.load(emptyDesign()); storage.set("lastDesign", ""); this._renderDesigns();
    if (this.s.layout === "narrow") this._showEditor();
  }
  // ---- template gallery ---------------------------------------------------------
  _openGallery(opener) {
    this._galleryOpener = opener || null;
    this._showGallery(true, true);
  }
  _showGallery(focusSearch, reset = false) {
    this.$.layer.dataset.mode = "gallery"; this.$.layer.hidden = false;
    this.gallery.open({ focusSearch: focusSearch && !(this._coarse || this._touchSeen), reset });
  }
  async _newFromTemplate(tpl) {
    if (!(await this._confirmDiscard())) return;
    const tape = this.tape;
    let design;
    try { ({ design } = await this.api.buildTemplate(tpl.id, tape, this.s.entryId || undefined)); }
    catch (e) { this.gallery.showError(`${tpl.name}: ${e.message || e}`); return; }
    this._galleryOpener = null;
    this._closeLayer();
    design.id = ""; design.name = tpl.name || design.name;
    this.store.load(design, { saved: false });   // unsaved: dirty until the user saves
    storage.set("lastDesign", ""); this._renderDesigns();
    if (this.s.layout === "narrow") {
      this._showEditor();
      if (Object.keys(design.variables || {}).length) {   // the sheet shows the variables to fill in
        this.m.openSheet("label", "half");
        requestAnimationFrame(() => requestAnimationFrame(() => { this.$.sheetBody.scrollTop = Math.max(0, this.$.vars.offsetTop - 8); }));
      }
    }
    const first = this.$.vars.querySelector(".vars-row input:nth-child(2)");
    if (first && !(this._coarse || this._touchSeen)) { first.focus({ preventScroll: true }); first.select?.(); }
    this._notify(`${t("Created from template")}: ${tpl.name}`, "info", 2500);
  }

  async _save() {
    let ok = false;
    await this._guard(t("Save failed"), async () => {
      const saved = await this.api.saveDesign(this.store.design);
      this.store.markSaved(saved);
      if (saved.name !== this.store.design.name) { this.store.design.name = saved.name; this.store.markSaved(saved); }
      storage.set("lastDesign", saved.id);
      await this._refreshDesigns();
      this._notify(t("Saved"), "info", 2000);
      this._persistSession(true);
      ok = true;
    });
    return ok;
  }
  async _duplicateDesign(id) {
    await this._guard(t("Duplicate failed"), async () => {
      const d = await this.api.getDesign(id);
      delete d.id; delete d.updated; d.name = `${d.name} copy`;
      await this.api.saveDesign(d); await this._refreshDesigns();
    });
  }
  async _deleteDesign(d) {
    if (!(await this._confirm(`${t("Delete")} "${d.name || d.id}"?`, { ok: t("Delete"), danger: true }))) return;
    await this._guard(t("Delete failed"), async () => {
      await this.api.deleteDesign(d.id);
      if (this.store.design.id === d.id) { this.store.load(emptyDesign()); storage.set("lastDesign", ""); if (this.s.layout === "narrow" && this.s.view === "edit") this._goHome(); }
      await this._refreshDesigns();
    });
  }
  async _print() {
    const p = this.printer;
    if (!p) { this._openWizard(false); return; }
    if (this.s.layout === "narrow") { this.s.printDone = 0; if (this.printFlow.phase !== "waiting") this.printFlow = PL.dismissPrint(this.printFlow); this._openLayer("print"); this.m.renderPrint(); return; }
    if (this.printFlow.phase === "waiting") return;
    if (this.s.tapeSel !== "auto" && p?.tape_mm && p.tape_mm !== this.s.tapeSel &&
        !(await this._confirm(`${t("The printer has")} ${G.tapeLabel(p.tape_mm)} ${t("tape loaded, but this design is set to")} ${G.tapeLabel(this.s.tapeSel)}. ${t("Print anyway?")}`, { ok: t("Print") }))) return;
    this._startPrint();
  }
  /** Runs one print attempt. The call may block ~20 s while the backend wakes a sleeping printer. */
  async _startPrint() {
    const req = { design: this.store.design, entry_id: this.s.entryId || undefined, variables: this._testVars(), copies: this.s.copies,
      chain: this.s.chain, [this.cutOption.key]: this.s[this.cutOption.key] };
    this._lastPrint = req;
    this.printFlow = PL.startPrint(this.printFlow);
    const id = this.printFlow.id;
    this._renderPrintStrip(); this._renderTop();
    clearInterval(this._pTick); this._pTick = setInterval(() => this._renderPrintStrip(), 1000);
    let outcome;
    try { await this.api.print(req); outcome = { ok: true }; }
    catch (e) { const f = failureSentence(e, t("Printing failed.")); outcome = { ok: false, reason: f.reason, text: f.text }; }
    const { flow, late } = PL.finishPrint(this.printFlow, id, outcome);
    this.printFlow = flow;
    if (flow.phase !== "waiting") clearInterval(this._pTick);
    if (late?.ok) this._notify(t("The label you stopped waiting for was sent to the printer after all."), "info", 5000);
    if (flow.phase === "done") {
      this.printFlow = PL.dismissPrint(flow);
      if (this.s.layout === "narrow" && this.$.layer.dataset.mode === "print") this.s.printDone = req.copies;
      else this._notify(`${t("Sent to printer")}${req.copies > 1 ? ` (${req.copies}×)` : ""}${req.chain ? `. ${t("The label stays inside until the next print or Feed.")}` : ""}`, "info", req.chain ? 5000 : 3500);
    }
    this._renderPrintStrip(); this._renderTop(); this.m.renderPrint();
    this._refreshPrinters().catch(() => {});
  }
  _setCutting(key, on) {
    this.s[key] = on; storage.set(key, on);
    this._renderTop(); this.m.renderPrint(); this.m.renderCut();
  }
  /** Feed the tape out, e.g. to release a chained label. */
  async _feed() {
    if (this._feeding) return;
    this._feeding = true; this._renderTop(); this.m.renderPrint(); this.m.renderCut();
    try { await this.api.feed(this.s.entryId || undefined); this._notify(t("Tape fed out"), "info", 2500); }
    catch (e) { this._notify(failureSentence(e, t("Feeding failed.")).text, "err"); }
    finally { this._feeding = false; this._renderTop(); this.m.renderPrint(); this.m.renderCut(); this._refreshPrinters().catch(() => {}); }
  }
  _cancelPrintWait() {
    this.printFlow = PL.cancelPrint(this.printFlow); clearInterval(this._pTick);
    this._renderPrintStrip(); this._renderTop(); this.m.renderPrint();
  }
  _renderPrintStrip() {
    this.m?.renderPrint();
    const f = this.printFlow, el = this.$.printStrip;
    el.hidden = f.phase === "idle" || (this.s.layout === "narrow" && this.$.layer.dataset.mode === "print");
    if (f.phase === "idle") { el.replaceChildren(); return; }
    el.className = "pstrip " + (f.phase === "failed" ? "err" : "wait");
    el.setAttribute("role", f.phase === "failed" ? "alert" : "status");
    if (f.phase === "waiting") {
      el.replaceChildren(h("span", { class: "spin", "aria-hidden": "true" }), h("span", { class: "grow" }, PL.waitingText(f)),
        h("button", { class: "btn small", type: "button", onClick: () => this._cancelPrintWait() }, t("Cancel")));
    } else {
      el.replaceChildren(icon("mdi:alert-circle-outline"), h("span", { class: "grow" }, f.text || t("Printing failed.")),
        h("button", { class: "btn small primary", type: "button", onClick: () => { this.printFlow = PL.dismissPrint(this.printFlow); this._startPrint(); } }, icon("mdi:refresh"), t("Retry")),
        h("button", { class: "btn small", type: "button", onClick: () => { this.printFlow = PL.dismissPrint(this.printFlow); this._renderPrintStrip(); this._renderTop(); } }, t("Dismiss")),
        h("button", { class: "btn small", type: "button", onClick: () => this._openPrinters() }, icon("mdi:printer-settings"), t("Printers")));
    }
  }

  // ---- printer drawer and Add-printer wizard ----
  _openPrinters() {
    this._printerOpener = this.shadowRoot.activeElement;
    this.$.layer.dataset.mode = "printers"; this.$.layer.hidden = false;
    this.printerDrawer.open();
  }
  _openWizard(fromDrawer) {
    this._wizardFromDrawer = !!fromDrawer;
    this.printerDrawer.close();
    this.$.layer.dataset.mode = "wizard"; this.$.layer.hidden = false;
    this.wizard.open();
  }
  _closeWizard() {
    this.wizard.abort();
    if (this._wizardFromDrawer) { this._openPrinters(); return; }
    this._closeLayer();
  }
  async _wizardDone(id) {
    this.wizard.abort();
    await this._refreshPrinters().catch(() => {});
    if (id) this._selectPrinter(id);
    this._closeLayer();
    const p = this.printer;
    if (p) this._notify(`${p.name} ${t("is ready")}${p.tape ? ` (${PL.tapeWidthText(p.tape.width_mm)})` : ""}.`, "info", 4000);
    if (this.s.tapeSel === "auto") this.previewer.request();
  }

  _add(type, info) {
    const el = newElement(type, this.store.design, this.tape, info, this.printer?.tape_pins);
    this._closeLayer();
    this.store.addElement(el);
    if (this.s.layout === "narrow") this.m.openSheet("element", "peek");   // new elements need content: show their fields
  }
  _addImage() {
    const f = this.$.file.files?.[0]; this.$.file.value = "";
    if (!f) return;
    const url = URL.createObjectURL(f);
    const img = new Image();
    img.onload = () => {
      const maxH = this.pins, sc = Math.min(1, maxH / img.naturalHeight);
      const w = Math.max(1, Math.round(img.naturalWidth * sc)), hh = Math.max(1, Math.round(img.naturalHeight * sc));
      const c = document.createElement("canvas"); c.width = w; c.height = hh;
      const cx = c.getContext("2d"); cx.fillStyle = "#fff"; cx.fillRect(0, 0, w, hh); cx.drawImage(img, 0, 0, w, hh);
      URL.revokeObjectURL(url);
      this._add("image", { w, h: hh, src: c.toDataURL("image/png") });
    };
    img.onerror = () => { URL.revokeObjectURL(url); this._notify(t("Could not read that image"), "err"); };
    img.src = url;
  }
  _rotateSel() { const e = this.store.selected; if (e) this.store.updateElement(e.id, { rotation: G.rotateStep(e.rotation) }); }
  _dupSel() { if (this.store.selection) this.store.duplicateElement(this.store.selection); }
  _delSel() { if (this.store.selection) this.store.removeElement(this.store.selection); }
  _reorderSel(d) { if (this.store.selection) this.store.reorder(this.store.selection, d); }

  _onKey(ev) {
    const path = ev.composedPath();
    const tag = path[0]?.tagName;
    const inField = ["INPUT", "TEXTAREA", "SELECT"].includes(tag) && path[0].type !== "checkbox" && path[0].type !== "file";
    const mod = ev.ctrlKey || ev.metaKey, k = ev.key;
    if (k === "Escape" && !this.$.layer.hidden) { ev.preventDefault(); this._closeLayerFromBack(); return; }
    if (k === "Escape" && this.s.layout === "narrow" && this.m.snap !== "closed" && !inField) { this.m.setSnap("closed"); return; }
    if (mod && !ev.altKey && k.toLowerCase() === "s") { ev.preventDefault(); this._save(); return; }
    if (inField) return;
    if (mod && k.toLowerCase() === "z") { ev.preventDefault(); ev.shiftKey ? this.store.redo() : this.store.undo(); return; }
    if (mod && k.toLowerCase() === "y") { ev.preventDefault(); this.store.redo(); return; }
    if (mod && k.toLowerCase() === "d") { ev.preventDefault(); this._dupSel(); return; }
    const sel = this.store.selected;
    if (!sel) return;
    if ((k === "Delete" || k === "Backspace") && tag !== "BUTTON") { ev.preventDefault(); this._delSel(); return; }
    if (k === "r" && !mod) { this._rotateSel(); return; }
    if (k === "Escape") { this.store.select(null); return; }
    const n = G.nudge(sel, k, ev.shiftKey);
    if (n && tag !== "SELECT") { ev.preventDefault(); this.store.updateElement(sel.id, n, "nudge:" + sel.id); }
  }

  // ---- inspector -------------------------------------------------------
  _renderInspector(force) {
    const el = this.store.selected, sig = el ? `${el.id}:${el.type}` : "";
    if (!force && sig === this._inspSig) { this._sync.forEach((f) => f()); return; }
    this._inspSig = sig; this._sync = [];
    const box = this.$.insp;
    if (!el) {
      if (this.s.layout === "narrow") { box.replaceChildren(this._labelFields(true)); return; }
      box.replaceChildren(h("h3", {}, t("Properties")), h("div", { class: "hint" }, t("Select an element on the canvas or in the layer list.")),
        this._labelFields());
      return;
    }
    const id = el.id;
    const get = () => this.store.element(id);
    const upd = (patch, key) => this.store.updateElement(id, patch, key);
    const active = () => this.shadowRoot.activeElement;
    const sync = (f) => { this._sync.push(f); f(); };

    const field = (label, ctl, full) => h("div", { class: "field" + (full ? " full" : "") }, h("label", {}, label), ctl);
    const num = (prop, label, o = {}) => {
      const i = h("input", { type: "number", step: o.step ?? 1, min: o.min, max: o.max, "aria-label": label, onInput: () => { const v = parseFloat(i.value); if (!Number.isNaN(v)) upd({ [prop]: o.int === false ? v : Math.round(v) }, "f:" + prop); } });
      sync(() => { if (active() !== i) i.value = get()?.[prop] ?? ""; });
      return i;
    };
    const text = (prop, label) => {
      const i = h("input", { type: "text", "aria-label": label, onInput: () => upd({ [prop]: i.value }, "f:" + prop) });
      sync(() => { if (active() !== i) i.value = get()?.[prop] ?? ""; });
      return i;
    };
    const area = (prop, label) => {
      const i = h("textarea", { rows: 3, "aria-label": label, onInput: () => upd({ [prop]: i.value }, "f:" + prop) });
      sync(() => { if (active() !== i) i.value = get()?.[prop] ?? ""; });
      return i;
    };
    const check = (prop, label) => {
      const i = h("input", { type: "checkbox", "aria-label": label, onChange: () => upd({ [prop]: i.checked }) });
      sync(() => { i.checked = !!get()?.[prop]; });
      return i;
    };
    const select = (prop, label, opts, conv = (v) => v) => {
      const i = h("select", { "aria-label": label, onChange: () => upd({ [prop]: conv(i.value) }) }, opts.map(([v, l]) => h("option", { value: v }, l)));
      sync(() => { i.value = String(get()?.[prop]); });
      return i;
    };
    const segs = (prop, label, opts) => {
      const btns = opts.map(([v, ic, l]) => iconButton(ic, l, () => upd({ [prop]: v }), { role: "radio" }));
      const w = h("div", { class: "seg", role: "radiogroup", "aria-label": label }, btns);
      btns.forEach((b) => { b.className = ""; });
      sync(() => opts.forEach(([v], j) => { btns[j].classList.toggle("on", get()?.[prop] === v); btns[j].setAttribute("aria-checked", String(get()?.[prop] === v)); }));
      return w;
    };
    const kids = [h("h3", {}, h("span", { class: "grow" }, t(TYPE_NAMES[el.type] || el.type)))];

    if (el.type === "text") {
      kids.push(field(t("Text"), area("text", t("Text")), true));
      const picker = createFontPicker({
        api: this.api, t, getFont: () => ({ family: get()?.font || "" }),
        onPick: async ({ family, entry }) => {
          const cur = get(); if (!cur) return;
          const e = entry || fontInfo.get(family);
          const weights = e?.weights?.length ? e.weights : ALL_WEIGHTS;
          const patch = { font: family, weight: nearestWeight(weights, cur.weight || 400) };
          if (e && !(e.styles || []).includes("italic")) patch.italic = false;
          upd(patch);
          try { await this.api.ensureFont(family, patch.weight, !!(patch.italic ?? cur.italic)); } catch (err) { this._notify(err.message || String(err), "err"); }
          this.previewer.request();
        },
      });
      this._sync.push(() => picker.sync());
      kids.push(field(t("Font"), picker.el, true));
      const wSel = h("select", { "aria-label": t("Weight"), onChange: async () => { upd({ weight: Number(wSel.value) }); const c = get(); try { await this.api.ensureFont(c.font, c.weight, !!c.italic); } catch (e) { this._notify(e.message || String(e), "err"); } this.previewer.request(); } });
      const italic = h("input", { type: "checkbox", "aria-label": t("Italic"), onChange: async () => { upd({ italic: italic.checked }); const c = get(); try { await this.api.ensureFont(c.font, c.weight, !!c.italic); } catch (e) { this._notify(e.message || String(e), "err"); } this.previewer.request(); } });
      sync(() => {
        const c = get(); if (!c) return;
        const info = fontInfo.get(c.font); const ws = c.font && info?.weights?.length ? info.weights : ALL_WEIGHTS;
        const opts = [...new Set([...ws, c.weight || 400])].sort((a, b) => a - b);
        if (wSel.dataset.sig !== opts.join()) { wSel.replaceChildren(...opts.map((w) => h("option", { value: w }, w))); wSel.dataset.sig = opts.join(); }
        wSel.value = String(c.weight || 400);
        italic.checked = !!c.italic; italic.disabled = !!(c.font && info && !(info.styles || []).includes("italic"));
      });
      kids.push(h("div", { class: "field" }, h("label", {}, t("Weight")), h("div", { class: "row" }, wSel, h("label", { class: "row" }, italic, t("Italic")))));
      const auto = h("input", { type: "checkbox", "aria-label": t("Auto size"), onChange: () => upd({ size: auto.checked ? "auto" : Math.max(6, Math.round(get().h * 0.7)) }) });
      const size = h("input", { type: "number", min: 4, max: 400, "aria-label": t("Font size in dots"), onInput: () => { const v = parseFloat(size.value); if (v > 0) upd({ size: Math.round(v) }, "f:size"); } });
      sync(() => { const c = get(); auto.checked = c.size === "auto"; size.disabled = auto.checked; if (active() !== size) size.value = auto.checked ? "" : c.size; });
      kids.push(h("div", { class: "field" }, h("label", {}, t("Size (dots)")), h("div", { class: "row" }, size, h("label", { class: "row" }, auto, t("Auto fit")))));
      kids.push(field(t("Align"), h("div", { class: "row" },
        segs("align", t("Horizontal alignment"), [["left", "mdi:format-align-left", t("Left")], ["center", "mdi:format-align-center", t("Centre")], ["right", "mdi:format-align-right", t("Right")]]),
        segs("valign", t("Vertical alignment"), [["top", "mdi:format-vertical-align-top", t("Top")], ["middle", "mdi:format-vertical-align-center", t("Middle")], ["bottom", "mdi:format-vertical-align-bottom", t("Bottom")]]))));
      kids.push(field(t("Line spacing"), num("line_spacing", t("Line spacing"), { step: 0.1, min: 0.5, max: 3, int: false })));
    } else if (el.type === "icon") {
      const ip = createIconPicker({ api: this.api, t, getIcon: () => get()?.icon, onPick: (n) => upd({ icon: n }) });
      this._sync.push(() => ip.sync());
      kids.push(field(t("Icon"), ip.el, true), field(t("Name"), text("icon", t("Icon name"))));
    } else if (el.type === "qr") {
      kids.push(field(t("Data"), area("data", t("QR data")), true),
        field(t("Error correction"), select("ecc", t("Error correction"), ECC.map((c) => [c, c.toUpperCase()]))),
        field(t("Quiet zone"), num("quiet", t("Quiet zone modules"), { min: 0, max: 8 })));
    } else if (el.type === "barcode") {
      kids.push(field(t("Format"), select("format", t("Barcode format"), BARCODES.map((b) => [b, b]))),
        field(t("Data"), text("data", t("Barcode data"))),
        field(t("Show text"), check("show_text", t("Show text"))));
    } else if (el.type === "rect") {
      kids.push(field(t("Stroke (dots)"), num("stroke", t("Stroke"), { min: 1, max: 40 })), field(t("Filled"), check("fill", t("Filled"))));
    } else if (el.type === "image") {
      const thumb = h("img", { alt: "", style: "max-width:100%;max-height:60px;background:#fff;border:1px solid var(--bp-line);image-rendering:pixelated" });
      sync(() => { const s = get()?.src; if (thumb.dataset.s !== String(s?.length)) { thumb.src = s || ""; thumb.dataset.s = String(s?.length); } });
      kids.push(field(t("Preview"), thumb), field(t("Dither"), check("dither", t("Dither"))));
    }
    kids.push(h("h3", { style: "margin-top:14px" }, t("Position & size")));
    kids.push(h("div", { class: "grid4" },
      h("label", { class: "g" }, "X", num("x", "X")), h("label", { class: "g" }, "Y", num("y", "Y")),
      h("label", { class: "g" }, "W", num("w", t("Width"), { min: 1 })), h("label", { class: "g" }, "H", num("h", t("Height"), { min: 1 }))));
    const rot = select("rotation", t("Rotation"), [[0, "0°"], [90, "90°"], [180, "180°"], [270, "270°"]], Number);
    kids.push(field(t("Rotation"), h("div", { class: "row" }, rot, iconButton("mdi:rotate-right", t("Rotate 90°"), () => this._rotateSel()))));
    kids.push(field(t("Invert"), check("invert", t("Invert"))));
    box.replaceChildren(...kids);
  }

  _labelFields(phone = false) {
    // label-level options shown when nothing is selected
    const d = () => this.store.design;
    const pad = h("input", { type: "number", min: 0, max: 100, "aria-label": t("Padding"), onInput: () => { const v = parseInt(pad.value); if (v >= 0) this.store.setMeta({ padding_dots: v }, "pad"); } });
    this._sync.push(() => { if (this.shadowRoot.activeElement !== pad) pad.value = d().padding_dots ?? 6; });
    pad.value = d().padding_dots ?? 6;
    const $ = this.$;
    return h("div", {}, phone ? null : h("h3", { style: "margin-top:14px" }, t("Label")),
      phone && h("div", { class: "field" }, h("label", {}, t("Tape")), $.gTape),
      phone && h("div", { class: "field" }, h("label", {}, t("Length")), $.gLen),
      h("div", { class: "field" }, h("label", {}, t("Padding (dots)")), pad),
      h("div", { class: "hint" }, t("Padding applies to auto-length labels only.")));
  }

  // ---- variables -------------------------------------------------------
  _renderVars(force) {
    const box = this.$.vars, vars = this.store.design.variables || {};
    const sig = Object.keys(vars).join("\u0001");
    const focusedIn = box.contains(this.shadowRoot.activeElement) || this.shadowRoot.activeElement?.closest?.(".vars-box");
    if (!force && sig === this._varsSig && focusedIn) return;
    if (!force && sig === this._varsSig && this._varsInputs) {
      for (const [k, inp] of this._varsInputs) if (this.shadowRoot.activeElement !== inp) inp.value = vars[k] ?? "";
      return;
    }
    this._varsSig = sig; this._varsInputs = new Map();
    const rows = Object.keys(vars).map((k) => {
      const nameI = h("input", { type: "text", value: k, "aria-label": `${t("Variable name")} ${k}`, onChange: () => this._renameVar(k, nameI.value.trim()) });
      const defI = h("input", { type: "text", value: vars[k] ?? "", "aria-label": `${t("Default value of")} ${k}`, onInput: () => this.store.setVariables({ ...this.store.design.variables, [k]: defI.value }, "var:" + k) });
      const testI = h("input", { type: "text", value: this.s.testValues[k] ?? "", placeholder: t("(default)"), "aria-label": `${t("Test value of")} ${k}`, onInput: () => { this.s.testValues[k] = testI.value; this.previewer.request(); } });
      this._varsInputs.set(k, defI);
      return h("div", { class: "vars-row" }, nameI, defI, testI, iconButton("mdi:close", `${t("Remove variable")} ${k}`, () => this._removeVar(k)));
    });
    box.replaceChildren(h("h3", {}, h("span", { class: "grow" }, t("Variables")), iconButton("mdi:plus", t("Add variable"), () => this._addVar())),
      rows.length ? h("div", { class: "vars-head" }, h("span", {}, t("Name")), h("span", {}, t("Default")), h("span", {}, t("Test value")), h("span")) : h("div", { class: "hint" }, t("Use {{ name }} in text, QR and barcode data. Test values only affect preview and print from here; they are not saved.")),
      ...rows);
    box.classList.add("vars-box");
  }
  _addVar() {
    const vars = { ...this.store.design.variables }; let n = 1; while (`var${n}` in vars) n++;
    vars[`var${n}`] = ""; this.store.setVariables(vars, "var-add");
    this._renderVars(true);
  }
  _removeVar(k) { const v = { ...this.store.design.variables }; delete v[k]; delete this.s.testValues[k]; this.store.setVariables(v, "var-del"); this._renderVars(true); }
  _renameVar(k, nk) {
    const vars = this.store.design.variables;
    if (!nk || nk === k || nk in vars || !/^[A-Za-z_][A-Za-z0-9_]*$/.test(nk)) { this._renderVars(true); return; }
    const out = {}; for (const [a, b] of Object.entries(vars)) out[a === k ? nk : a] = b;
    if (k in this.s.testValues) { this.s.testValues[nk] = this.s.testValues[k]; delete this.s.testValues[k]; }
    this.store.setVariables(out, "var-ren"); this._renderVars(true);
  }
}

if (!customElements.get("brother-ptouch-panel")) customElements.define("brother-ptouch-panel", BrotherPtouchPanel);
export { BrotherPtouchPanel };
