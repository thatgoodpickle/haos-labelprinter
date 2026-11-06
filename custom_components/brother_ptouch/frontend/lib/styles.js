// Shadow-DOM stylesheet. Written for iOS 15 / Android WebView 100: no :has(), no container queries,
// color-mix() only inside @supports, dvh only after a plain fallback.
export const CSS = `
:host { display:block; height:100%; min-height:0; box-sizing:border-box;
  --bp-bg: var(--primary-background-color, #fafafa);
  --bp-card: var(--card-background-color, #fff);
  --bp-text: var(--primary-text-color, #212121);
  --bp-text2: var(--secondary-text-color, #727272);
  --bp-line: var(--divider-color, rgba(0,0,0,.12));
  --bp-accent: var(--primary-color, #03a9f4);
  --bp-on-accent: var(--text-primary-color, #fff);
  --bp-danger: var(--error-color, #db4437);
  --bp-warn: var(--warning-color, #ffa726);
  --bp-surface2: var(--secondary-background-color, #e5e5e5);
  --bp-radius: var(--ha-card-border-radius, 10px);
  --bp-sel: rgba(127,127,127,.22); --bp-sel2: rgba(127,127,127,.3); --bp-hover: rgba(127,127,127,.45);
  --bp-warn-bg: rgba(255,167,38,.22); --bp-err-bg: rgba(219,68,55,.2); --bp-info-bg: rgba(127,127,127,.18); --bp-el-bg: rgba(127,127,127,.08);
  color: var(--bp-text); background: var(--bp-bg); font-family: var(--paper-font-body1_-_font-family, Roboto, system-ui, sans-serif); font-size: 14px;
  -webkit-text-size-adjust: 100%; -webkit-tap-highlight-color: transparent; }
@supports (background: color-mix(in srgb, red 50%, blue)) {
  :host { --bp-sel: color-mix(in srgb, var(--bp-accent) 18%, transparent); --bp-sel2: color-mix(in srgb, var(--bp-accent) 25%, transparent);
    --bp-hover: color-mix(in srgb, var(--bp-accent) 60%, transparent); --bp-warn-bg: color-mix(in srgb, var(--bp-warn) 22%, transparent);
    --bp-err-bg: color-mix(in srgb, var(--bp-danger) 20%, transparent); --bp-info-bg: color-mix(in srgb, var(--bp-accent) 16%, transparent);
    --bp-el-bg: color-mix(in srgb, var(--bp-accent) 7%, transparent); }
}
* { box-sizing: border-box; }
[hidden] { display:none !important; }
.root { position:relative; display:flex; flex-direction:column; height:100%; min-height:0; overflow:hidden; }
button, input, select, textarea { font: inherit; color: inherit; }
button, select, summary, label, .ibtn, .btn { touch-action: manipulation; }
.ico { --mdc-icon-size: 20px; width:20px; height:20px; flex:none; display:inline-flex; align-items:center; justify-content:center; font-size:11px; }
.topbar, .tabs, .ctoolbar, .actionbar, .stage, .el, .handle, .layer, .strip, .hamburger, .btn, .ibtn { -webkit-user-select:none; user-select:none; -webkit-touch-callout:none; }
input, textarea { -webkit-user-select:text; user-select:text; -webkit-touch-callout:default; }

/* top bar */
.topbar { display:flex; flex-wrap:wrap; gap:8px 10px; align-items:center; padding:8px 12px; background:var(--bp-card); border-bottom:1px solid var(--bp-line); }
.topbar .name { flex:1 1 180px; min-width:120px; max-width:340px; font-size:16px; font-weight:500; }
.topbar .spacer { flex:1 1 0; }
.tb-group { display:flex; align-items:center; gap:6px; }
.tb-group label.small { color:var(--bp-text2); font-size:12px; }
.tb-check { display:inline-flex; align-items:center; gap:4px; }
.tb-check input { margin:0; }
.dirty-dot { width:8px; height:8px; border-radius:50%; background:var(--bp-warn); display:none; flex:none; }
.dirty .dirty-dot { display:inline-block; }

input[type=text], input[type=number], input[type=search], select, textarea { background:var(--bp-bg); border:1px solid var(--bp-line); border-radius:6px; padding:6px 8px; min-height:34px; max-width:100%; }
input[type=number] { width:76px; }
textarea { width:100%; resize:vertical; min-height:64px; }
input:focus-visible, select:focus-visible, textarea:focus-visible, button:focus-visible, [tabindex]:focus-visible { outline:2px solid var(--bp-accent); outline-offset:1px; }
input[type=checkbox] { width:18px; height:18px; accent-color: var(--bp-accent); }

.btn { display:inline-flex; align-items:center; gap:6px; min-height:36px; padding:0 14px; border-radius:18px; border:1px solid var(--bp-line); background:var(--bp-card); cursor:pointer; white-space:nowrap; }
.btn.primary { background:var(--bp-accent); color:var(--bp-on-accent); border-color:transparent; }
.btn.danger { color:var(--bp-danger); }
.btn.primary.danger { background:var(--bp-danger); color:#fff; }
.btn:disabled, .ibtn:disabled { opacity:.4; cursor:default; }
.ibtn { width:36px; height:36px; display:inline-flex; align-items:center; justify-content:center; border:none; border-radius:50%; background:transparent; cursor:pointer; color:inherit; padding:0; flex:none; }
.ibtn.on { background:var(--bp-accent); color:var(--bp-on-accent); }
.ibtn.accent { background:var(--bp-accent); color:var(--bp-on-accent); }
@media (hover:hover) {
  .btn:hover:not(:disabled), .ibtn:hover:not(:disabled) { background:var(--bp-surface2); }
  .btn.primary:hover:not(:disabled) { filter:brightness(1.08); background:var(--bp-accent); }
  .ibtn.on:hover:not(:disabled), .ibtn.accent:hover:not(:disabled) { background:var(--bp-accent); filter:brightness(1.08); }
  .item:hover, .fp-row:hover, .ip-cell:hover { background:var(--bp-surface2); }
  .el:hover { border-color:var(--bp-hover); }
}
.seg { display:inline-flex; border:1px solid var(--bp-line); border-radius:8px; overflow:hidden; }
.seg button { border:none; background:transparent; width:38px; height:34px; cursor:pointer; display:inline-flex; align-items:center; justify-content:center; }
.seg button + button { border-left:1px solid var(--bp-line); }
.seg button.on { background:var(--bp-accent); color:var(--bp-on-accent); }

/* body layout */
.body { flex:1; min-height:0; display:grid; grid-template-columns: 250px minmax(0,1fr) 330px; }
.pane { overflow:auto; min-height:0; overscroll-behavior:contain; -webkit-overflow-scrolling:touch; }
.left { border-right:1px solid var(--bp-line); background:var(--bp-card); }
.right { border-left:1px solid var(--bp-line); background:var(--bp-card); }
.center { display:flex; flex-direction:column; min-width:0; min-height:0; position:relative; overflow:hidden; }
.section { padding:10px 12px 12px; border-bottom:1px solid var(--bp-line); }
.section > h3 { margin:0 0 8px; font-size:12px; font-weight:600; letter-spacing:.06em; text-transform:uppercase; color:var(--bp-text2); display:flex; align-items:center; gap:6px; }
.section > h3 .grow { flex:1; }
.sheet-head, .sheet-grab { display:none; }

.palette { display:grid; grid-template-columns: repeat(2, 1fr); gap:6px; }
.palette .btn { border-radius:8px; justify-content:flex-start; padding:0 10px; }

.list { display:flex; flex-direction:column; gap:2px; }
.item { display:flex; align-items:center; gap:4px; border-radius:8px; padding:0 2px 0 8px; min-height:38px; cursor:pointer; }
.item.sel { background:var(--bp-sel); }
.item .label { flex:1; min-width:0; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; background:none; border:none; text-align:left; cursor:pointer; padding:8px 0; display:flex; align-items:center; gap:8px; }
.item .ibtn { width:30px; height:30px; }
.item .ibtn .ico { --mdc-icon-size:18px; }
.muted { color:var(--bp-text2); }
.hint { color:var(--bp-text2); font-size:12px; padding:2px 0; }

/* canvas */
.ctoolbar { display:flex; flex-wrap:wrap; align-items:center; gap:4px 8px; padding:6px 10px; background:var(--bp-card); border-bottom:1px solid var(--bp-line); }
.ctoolbar .sep { width:1px; align-self:stretch; background:var(--bp-line); margin:2px 2px; }
.ctoolbar .readout { margin-left:auto; color:var(--bp-text2); font-size:12px; font-variant-numeric:tabular-nums; }
.tools { display:contents; }
.zoomchip { min-width:52px; height:36px; padding:0 8px; border:1px solid var(--bp-line); border-radius:18px; background:var(--bp-card); font-variant-numeric:tabular-nums; cursor:pointer; display:none; }
.strip { padding:6px 12px; font-size:13px; display:flex; gap:8px; align-items:flex-start; }
.strip.warn { background:var(--bp-warn-bg); }
.strip.err { background:var(--bp-err-bg); color:var(--bp-text); }
.strip.info { background:var(--bp-info-bg); }
.scroller { flex:1; min-height:0; overflow:auto; padding:16px 18px 28px; background:var(--bp-surface2); position:relative;
  overscroll-behavior:contain; touch-action:none; -webkit-overflow-scrolling:touch; }
.canvas-wrap { display:inline-block; position:relative; min-width:0; }
.ruler { display:block; height:22px; color:var(--bp-text2); }
.stage { position:relative; background:#fff; outline:1px solid var(--bp-line); box-shadow:0 1px 6px rgba(0,0,0,.25); touch-action:none; }
.stage:focus-visible { outline:2px solid var(--bp-accent); }
.stage img { position:absolute; left:0; top:0; image-rendering:pixelated; image-rendering:crisp-edges; image-rendering:pixelated; pointer-events:none; max-width:none; -webkit-user-drag:none; }
.stage.loading::after { content:""; position:absolute; right:6px; top:6px; width:14px; height:14px; border-radius:50%; border:2px solid var(--bp-accent); border-top-color:transparent; animation:spin .7s linear infinite; }
@keyframes spin { to { transform:rotate(360deg); } }
.el { position:absolute; border:1px dashed transparent; cursor:move; touch-action:none; }
.el.sel { border:1.5px solid var(--bp-accent); background:var(--bp-el-bg); }
.coarse .el::before { content:""; position:absolute; left:calc(-1 * var(--px, 0px)); right:calc(-1 * var(--px, 0px)); top:calc(-1 * var(--py, 0px)); bottom:calc(-1 * var(--py, 0px)); }
.handle { position:absolute; width:26px; height:26px; margin:-13px 0 0 -13px; touch-action:none; z-index:6; display:flex; align-items:center; justify-content:center; }
.handle::after { content:""; width:10px; height:10px; background:#fff; border:2px solid var(--bp-accent); border-radius:2px; }
.coarse .handle { width:44px; height:44px; margin:-22px 0 0 -22px; }
.coarse .handle::after { width:16px; height:16px; border-radius:4px; box-shadow:0 0 0 1px rgba(0,0,0,.25); }
.coarse .outside .handle { transform:translate(calc(var(--hx) * 22px), calc(var(--hy) * 22px)); }
.guide { position:absolute; background:#e91e63; pointer-events:none; z-index:7; }
.guide.x { width:1px; top:0; bottom:0; } .guide.y { height:1px; left:0; right:0; }
.empty-hint { position:absolute; inset:0; display:flex; align-items:center; justify-content:center; color:#888; pointer-events:none; font-size:13px; }

/* inspector */
.field { display:grid; grid-template-columns: 92px 1fr; align-items:center; gap:6px 8px; margin:6px 0; }
.field > label, .field > .lbl { color:var(--bp-text2); font-size:12px; }
.field > * { min-width:0; }
.field input[type=text], .field textarea { width:100%; }
.field.full { grid-template-columns: 1fr; }
.row { display:flex; gap:6px; align-items:center; flex-wrap:wrap; }
.row > input[type=search] { flex:1; min-width:100px; }
.grid4 { display:grid; grid-template-columns: repeat(4, 1fr); gap:6px; }
.grid4 .g { display:flex; flex-direction:column; gap:2px; font-size:11px; color:var(--bp-text2); }
.grid4 input { width:100%; color:var(--bp-text); font-size:14px; }
.select-like { display:flex; align-items:center; gap:6px; width:100%; min-height:36px; padding:4px 8px; background:var(--bp-bg); border:1px solid var(--bp-line); border-radius:6px; cursor:pointer; text-align:left; }
.select-like > :first-child { flex:1; min-width:0; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; display:flex; gap:8px; align-items:center; }
.picker { position:relative; }
.fp-panel { margin-top:4px; border:1px solid var(--bp-line); border-radius:8px; padding:6px; background:var(--bp-card); }
.fp-list { max-height:260px; overflow:auto; margin-top:6px; overscroll-behavior:contain; }
.fp-row { display:flex; justify-content:space-between; align-items:baseline; gap:8px; width:100%; border:none; background:none; padding:7px 8px; border-radius:6px; cursor:pointer; text-align:left; font-size:16px; }
.fp-row.sel { background:var(--bp-sel); }
.fp-name { overflow:hidden; text-overflow:ellipsis; white-space:nowrap; } .fp-cat { font-size:11px; color:var(--bp-text2); flex:none; }
.ip-grid { display:grid; grid-template-columns: repeat(auto-fill, minmax(40px,1fr)); gap:2px; max-height:240px; overflow:auto; margin-top:6px; overscroll-behavior:contain; }
.ip-cell { height:40px; border:none; background:none; border-radius:6px; cursor:pointer; display:flex; align-items:center; justify-content:center; }
.ip-cell.sel { background:var(--bp-sel2); }
.ip-cell .ico { --mdc-icon-size:24px; width:24px; height:24px; }
.vars-row { display:grid; grid-template-columns: 1fr 1fr 1fr 30px; gap:4px; margin:4px 0; align-items:center; }
.vars-row input { width:100%; min-width:0; }
.vars-head { display:grid; grid-template-columns: 1fr 1fr 1fr 30px; gap:4px; font-size:11px; color:var(--bp-text2); }
.tabs, .hamburger, .actionbar, .more, .editbtn, .addbtn { display:none; }
.sr { position:absolute; width:1px; height:1px; overflow:hidden; clip:rect(0 0 0 0); opacity:0; pointer-events:none; }

/* modal layer: add palette, overflow menu, confirm dialog (absolute inside the panel, never position:fixed) */
.layer { position:absolute; inset:0; z-index:50; background:rgba(0,0,0,.45); display:flex; flex-direction:column; justify-content:flex-end; overscroll-behavior:contain; touch-action:manipulation; }
.layer[data-mode=confirm] { justify-content:center; align-items:center; padding:16px; }
.msheet, .dialog { background:var(--bp-card); color:var(--bp-text); box-shadow:0 -4px 24px rgba(0,0,0,.35); display:none; }
.msheet { border-radius:16px 16px 0 0; padding:8px 14px 14px; max-height:80%; overflow:auto; }
.msheet h3 { margin:6px 0 10px; font-size:13px; font-weight:600; letter-spacing:.05em; text-transform:uppercase; color:var(--bp-text2); display:flex; align-items:center; gap:8px; }
.msheet h3 .grow { flex:1; }
.layer[data-mode=add] .add-sheet, .layer[data-mode=menu] .menu-sheet { display:block; }
.dialog { border-radius:14px; padding:18px 18px 12px; width:min(380px, 100%); box-shadow:0 8px 32px rgba(0,0,0,.4); }
.layer[data-mode=confirm] .dialog { display:block; }
.dialog p { margin:0 0 16px; font-size:15px; line-height:1.4; white-space:pre-wrap; }
.dialog .acts { display:flex; justify-content:flex-end; gap:8px; }
.add-sheet .palette { grid-template-columns: repeat(4, 1fr); gap:8px; }
.add-sheet .palette .btn { flex-direction:column; justify-content:center; gap:4px; min-height:72px; border-radius:12px; padding:6px 2px; font-size:12px; }
.add-sheet .palette .ico { --mdc-icon-size:26px; width:26px; height:26px; }
.mrow { display:grid; grid-template-columns: 96px 1fr; align-items:center; gap:8px; margin:8px 0; }
.mrow > label { color:var(--bp-text2); font-size:13px; }
.mrow select, .mrow input { width:100%; }
.mrow .tb-group { display:flex; gap:8px; }
.mrow .tb-group select { flex:1; }
.mrow .tb-group input { width:96px; flex:none; }
.menu-sheet .acts { display:flex; gap:8px; margin-top:12px; flex-wrap:wrap; }

/* touch ergonomics: 44px targets, 16px inputs (no iOS focus zoom) */
.narrow input[type=text], .narrow input[type=number], .narrow input[type=search], .narrow select, .narrow textarea,
.coarse input[type=text], .coarse input[type=number], .coarse input[type=search], .coarse select, .coarse textarea { font-size:16px; min-height:44px; }
.narrow input[type=number], .coarse input[type=number] { width:88px; }
.narrow .field { grid-template-columns: 1fr; gap:2px; margin:10px 0; }
.narrow .field > label { font-size:12px; }
.narrow .field.inline { grid-template-columns: 92px 1fr; }
.coarse .btn { min-height:44px; border-radius:22px; }
.coarse .ibtn, .coarse .zoomchip { height:44px; }
.coarse .ibtn { width:44px; }
.coarse .item { min-height:48px; }
.coarse .item .ibtn { width:44px; height:44px; }
.coarse .seg button { width:44px; height:44px; }
.coarse .select-like { min-height:44px; }
.coarse .fp-row { min-height:44px; align-items:center; }
.coarse .ip-grid { grid-template-columns: repeat(auto-fill, minmax(44px,1fr)); }
.coarse .ip-cell { height:44px; }
.coarse input[type=checkbox] { width:26px; height:26px; margin:9px; }
.coarse .row label.row { min-height:44px; }
.coarse .vars-row, .coarse .vars-head { grid-template-columns: 1fr 1fr 1fr 44px; }
.coarse .tb-group select { min-width:0; }
.coarse .msheet .btn { min-height:48px; }

/* template gallery (inside the modal layer; centred dialog on desktop, full-screen sheet on phones) */
.newrow { display:flex; gap:6px; flex-wrap:wrap; margin-bottom:8px; }
.newrow .btn { flex:1 1 auto; justify-content:center; padding:0 10px; }
.newrow .tpl-btn { flex-basis:100%; }
.newrow .tpl-btn { background:var(--bp-sel); border-color:transparent; color:var(--bp-accent); font-weight:500; }
.empty-hint { flex-direction:column; gap:10px; }
.empty-hint .btn { pointer-events:auto; }
.layer[data-mode=gallery] { justify-content:center; align-items:center; padding:24px; }
.gallery { display:none; flex-direction:column; width:min(1040px, 100%); height:min(760px, 100%); background:var(--bp-card); color:var(--bp-text); border-radius:16px; box-shadow:0 8px 32px rgba(0,0,0,.4); overflow:hidden; }
.layer[data-mode=gallery] .gallery { display:flex; }
.gal-head { display:flex; align-items:center; gap:10px; padding:10px 8px 6px 18px; flex:none; }
.gal-head h2 { margin:0; font-size:18px; font-weight:600; flex:1; min-width:0; }
.gal-tape { font-size:12px; color:var(--bp-text2); border:1px solid var(--bp-line); border-radius:12px; padding:3px 10px; white-space:nowrap; }
.gal-tools { padding:4px 18px 10px; display:flex; flex-direction:column; gap:8px; flex:none; border-bottom:1px solid var(--bp-line); }
.gal-search { width:100%; box-sizing:border-box; }
.gal-chips { display:flex; gap:6px; overflow-x:auto; padding:2px 0; -webkit-overflow-scrolling:touch; scrollbar-width:thin; }
.chip { flex:none; min-height:32px; padding:0 14px; border-radius:16px; border:1px solid var(--bp-line); background:var(--bp-card); color:var(--bp-text); cursor:pointer; font-size:13px; white-space:nowrap; text-transform:capitalize; }
.chip.on { background:var(--bp-accent); color:var(--bp-on-accent); border-color:transparent; }
.gal-scroll { flex:1 1 0; min-height:0; overflow:auto; padding:14px 18px 18px; overscroll-behavior:contain; -webkit-overflow-scrolling:touch; }
.gal-grid { display:grid; grid-template-columns:repeat(auto-fill, minmax(250px, 1fr)); gap:12px; }
.gal-card { display:flex; flex-direction:column; align-items:stretch; gap:3px; text-align:left; padding:8px; border-radius:12px; border:1px solid var(--bp-line); background:var(--bp-card); color:var(--bp-text); cursor:pointer; font:inherit; min-width:0; }
.gal-card:disabled { cursor:default; opacity:.7; }
.gal-card:focus-visible { outline:2px solid var(--bp-accent); outline-offset:2px; }
@media (hover:hover) { .gal-card:hover:not(:disabled) { border-color:var(--bp-accent); background:var(--bp-sel); } }
.gal-thumb { height:92px; border-radius:8px; background:#fff; border:1px solid var(--bp-line); display:flex; align-items:center; justify-content:center; overflow:hidden; margin-bottom:4px; position:relative; }
.gal-thumb img { max-width:100%; max-height:100%; object-fit:contain; display:block; }
.gal-thumb.loading::after { content:""; position:absolute; inset:0; background:linear-gradient(90deg, transparent, rgba(127,127,127,.22), transparent); background-size:200% 100%; animation:gal-shimmer 1.2s linear infinite; }
@keyframes gal-shimmer { from { background-position:200% 0; } to { background-position:-200% 0; } }
@media (prefers-reduced-motion:reduce) { .gal-thumb.loading::after { animation:none; } }
.gal-thumb.off { background:repeating-linear-gradient(135deg, rgba(127,127,127,.12) 0 8px, rgba(127,127,127,.04) 8px 16px); }
.gal-need, .gal-fail { color:#555; font-size:12px; display:flex; align-items:center; gap:4px; }
.gal-need .ico { --mdc-icon-size:16px; }
.gal-name { font-weight:600; font-size:14px; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }
.gal-desc { font-size:12px; color:var(--bp-text2); overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }
.gal-note { font-size:12px; color:var(--bp-warn); font-weight:500; }
.gal-status { padding:24px 0; text-align:center; }
.gal-status:empty { display:none; }
.gal-err, .gal-banner { color:var(--bp-danger); background:var(--bp-err-bg); border-radius:8px; padding:8px 12px; margin-bottom:10px; font-size:13px; }
.gal-status .gal-err { display:inline-block; margin-right:8px; }
.coarse .chip { min-height:44px; padding:0 16px; }
.coarse .gal-card { padding:10px; }
.narrow .layer[data-mode=gallery] { padding:0; align-items:stretch; }
.narrow .gallery { width:100%; height:100%; border-radius:0; box-shadow:none;
 }
.narrow .gal-head { padding-left:14px; }
.narrow .gal-head .gal-close { width:44px; height:44px; }
.narrow .gal-tools { padding:4px 14px 10px; }
.narrow .gal-scroll { padding:12px 14px 18px; }
.narrow .gal-grid { grid-template-columns:1fr; }
@media (orientation:landscape) and (max-height:520px) { .narrow .gal-grid { grid-template-columns:repeat(auto-fill, minmax(240px, 1fr)); } }

/* ---- printer chip, drawer, wizard, print status ---- */
.dot { width:10px; height:10px; border-radius:50%; flex:none; background:#9e9e9e; display:inline-block; }
.dot.green { background:#43a047; } .dot.amber { background:#ffa000; } .dot.red { background:#e53935; } .dot.grey { background:#9e9e9e; }
.printer-chip { display:inline-flex; align-items:center; gap:8px; min-height:36px; max-width:300px; padding:0 8px 0 12px; border:1px solid var(--bp-line); border-radius:18px; background:var(--bp-card); cursor:pointer; white-space:nowrap; }
.printer-chip .chip-name { overflow:hidden; text-overflow:ellipsis; font-weight:500; min-width:0; }
.printer-chip .chip-status { color:var(--bp-text2); font-size:13px; flex:none; }
.printer-chip .ico { --mdc-icon-size:18px; width:18px; height:18px; color:var(--bp-text2); }
.setup-btn .lbl-s { display:none; }
.pbar { display:none; }
.pstrip { display:flex; align-items:center; gap:10px; padding:8px 12px; font-size:14px; flex-wrap:wrap; }
.pstrip.wait { background:var(--bp-info-bg); } .pstrip.err { background:var(--bp-err-bg); }
.pstrip .grow, .pd-note .grow { flex:1 1 200px; min-width:0; }
.btn.small { min-height:32px; padding:0 12px; font-size:13px; border-radius:16px; }
.btn.waiting { opacity:.6; }
.spin { width:16px; height:16px; border-radius:50%; border:2px solid var(--bp-accent); border-top-color:transparent; animation:spin .8s linear infinite; flex:none; display:inline-block; }
.spin.big { width:36px; height:36px; border-width:3px; }
.btn .spin { border-color:currentColor; border-top-color:transparent; }
.root.first-run .setup-btn { font-weight:600; }

.layer[data-mode=printers] { flex-direction:row; justify-content:flex-end; align-items:stretch; }
.layer[data-mode=wizard] { justify-content:center; align-items:center; padding:24px; }
.pdrawer, .wizard { display:none; flex-direction:column; background:var(--bp-card); color:var(--bp-text); box-shadow:0 8px 32px rgba(0,0,0,.4); min-height:0; }
.layer[data-mode=printers] .pdrawer, .layer[data-mode=wizard] .wizard { display:flex; }
.pdrawer { width:min(460px, 100%); box-shadow:-4px 0 24px rgba(0,0,0,.35); }
.pd-head, .wz-head { display:flex; align-items:center; gap:4px; padding:10px 8px 8px 18px; flex:none; border-bottom:1px solid var(--bp-line); }
.pd-head h2, .wz-head h2 { margin:0; font-size:18px; font-weight:600; flex:1; min-width:0; outline:none; }
.pd-body { flex:1; min-height:0; overflow:auto; padding:12px 14px; overscroll-behavior:contain; -webkit-overflow-scrolling:touch; }
.pd-foot { flex:none; padding:10px 14px 10px; border-top:1px solid var(--bp-line); display:flex; }
.pd-foot .btn { flex:1; justify-content:center; }
.pd-list { display:flex; flex-direction:column; gap:10px; }
.pd-card { border:1px solid var(--bp-line); border-radius:12px; padding:12px; display:flex; flex-direction:column; gap:6px; background:var(--bp-card); }
.pd-card.active { border-color:var(--bp-accent); box-shadow:0 0 0 1px var(--bp-accent) inset; }
.pd-name { display:flex; align-items:center; gap:8px; font-size:16px; min-width:0; }
.pd-name strong { overflow:hidden; text-overflow:ellipsis; white-space:nowrap; min-width:0; }
.badge { font-size:11px; padding:1px 8px; border-radius:10px; background:var(--bp-accent); color:var(--bp-on-accent); flex:none; }
.pd-line { display:flex; align-items:center; gap:8px; font-size:13px; min-width:0; word-break:break-all; }
.pd-line .ico { --mdc-icon-size:18px; width:18px; height:18px; color:var(--bp-text2); }
.pd-state { font-size:14px; line-height:1.35; }
.pd-state.amber { color:var(--bp-text); } .pd-state.red { color:var(--bp-danger); font-weight:500; }
.pd-acts { display:flex; flex-wrap:wrap; gap:6px; align-items:center; margin-top:4px; }
.pd-acts .grow, .wz-foot .grow { flex:1; }
.ibtn.danger { color:var(--bp-danger); }
.pd-rename { display:flex; gap:6px; flex-wrap:wrap; align-items:center; }
.pd-rename input { flex:1 1 140px; min-width:0; }
.pd-note { display:flex; align-items:center; gap:8px; padding:8px 10px; border-radius:8px; font-size:13px; line-height:1.4; flex-wrap:wrap; margin:2px 0; }
.pd-note.info { background:var(--bp-info-bg); } .pd-note.err { background:var(--bp-err-bg); } .pd-note.ok { background:rgba(67,160,71,.18); }
.pd-note .ico { --mdc-icon-size:20px; width:20px; height:20px; flex:none; }
.pd-note.err .ico { color:var(--bp-danger); } .pd-note.ok .ico { color:#43a047; }
.pd-note.big { padding:12px; font-size:14px; }
.pd-empty { text-align:center; padding:40px 20px; color:var(--bp-text2); }
.pd-empty .ico { --mdc-icon-size:48px; width:48px; height:48px; opacity:.6; }
.pd-empty p { margin:6px 0; }

.wizard { width:min(560px, 100%); max-height:100%; border-radius:16px; overflow:hidden; }
.wizard.tall { height:min(660px, 100%); }
.wz-dots { list-style:none; margin:0; padding:12px 18px 4px; display:flex; gap:6px; flex:none; }
.wz-dots li { flex:1; display:flex; flex-direction:column; gap:4px; font-size:11px; color:var(--bp-text2); }
.wz-dots li i { height:4px; border-radius:2px; background:var(--bp-line); display:block; }
.wz-dots li.done i { background:var(--bp-accent); opacity:.55; } .wz-dots li.cur i { background:var(--bp-accent); } .wz-dots li.cur { color:var(--bp-text); font-weight:600; }
.wz-body { flex:1; min-height:0; overflow:auto; padding:12px 18px 16px; display:flex; flex-direction:column; gap:10px; overscroll-behavior:contain; -webkit-overflow-scrolling:touch; }
.wz-foot { flex:none; display:flex; gap:8px; padding:10px 14px 10px; border-top:1px solid var(--bp-line); align-items:center; }
.wz-lead { margin:0; font-size:15px; }
.wz-cards { display:flex; flex-direction:column; gap:8px; }
.wz-card { display:flex; align-items:center; gap:12px; text-align:left; padding:12px 14px; border:1px solid var(--bp-line); border-radius:12px; background:var(--bp-card); cursor:pointer; min-height:64px; width:100%; }
.wz-card > .ico { --mdc-icon-size:28px; width:28px; height:28px; color:var(--bp-accent); }
.wz-card-t { display:flex; flex-direction:column; gap:2px; flex:1; min-width:0; font-size:13px; }
.wz-card-t strong { font-size:15px; display:flex; gap:8px; align-items:center; }
.tag { font-size:10px; font-weight:600; text-transform:uppercase; letter-spacing:.05em; padding:1px 6px; border-radius:8px; background:var(--bp-surface2); color:var(--bp-text2); }
.wz-radio { width:20px; height:20px; border-radius:50%; border:2px solid var(--bp-line); flex:none; }
.wz-card.sel { border-color:var(--bp-accent); background:var(--bp-sel); }
.wz-card.sel .wz-radio { border-color:var(--bp-accent); background:radial-gradient(var(--bp-accent) 45%, transparent 50%); }
.wz-check { list-style:none; margin:0; padding:0; display:flex; flex-direction:column; gap:6px; }
.wz-check li { display:flex; gap:8px; align-items:center; font-size:14px; }
.wz-check .ico { color:var(--bp-accent); }
.wz-scanrow { gap:10px; }
.wz-devs { list-style:none; margin:0; padding:0; display:flex; flex-direction:column; gap:6px; }
.wz-dev { border:1px solid var(--bp-line); border-radius:10px; padding:8px 10px; display:flex; flex-direction:column; gap:6px; }
.wz-dev.printer { border-color:var(--bp-accent); background:var(--bp-sel); }
.wz-dev.sel { box-shadow:0 0 0 2px var(--bp-accent) inset; }
.wz-dev-main { display:flex; align-items:center; gap:10px; min-height:44px; }
.wz-dev-t { display:flex; flex-direction:column; flex:1; min-width:0; }
.wz-dev-t strong { overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }
.small { font-size:12px; }
.sigbars { display:inline-flex; align-items:flex-end; gap:2px; height:16px; flex:none; }
.sigbars i { width:4px; background:var(--bp-line); border-radius:1px; display:block; }
.sigbars i:nth-child(1) { height:5px; } .sigbars i:nth-child(2) { height:8px; } .sigbars i:nth-child(3) { height:12px; } .sigbars i:nth-child(4) { height:16px; }
.sigbars i.on { background:var(--bp-text); }
.wz-others > summary { cursor:pointer; padding:8px 2px; color:var(--bp-text2); font-size:13px; min-height:36px; display:flex; align-items:center; }
.wz-others[open] > summary { margin-bottom:6px; }
.progress { height:4px; border-radius:2px; background:var(--bp-line); overflow:hidden; }
.progress i { display:block; height:100%; width:40%; background:var(--bp-accent); animation:wz-slide 1.2s ease-in-out infinite; }
@keyframes wz-slide { 0% { margin-left:-40%; } 100% { margin-left:100%; } }
.wz-busy { text-align:center; padding:30px 10px; display:flex; flex-direction:column; align-items:center; gap:4px; }
.wz-busy p { margin:4px 0; }
.err-t { color:var(--bp-danger); }
.wizard .field.full { display:flex; flex-direction:column; align-items:stretch; gap:4px; margin:4px 0; }
.wizard .field label { font-size:13px; color:var(--bp-text2); }
.wizard input[type=text], .wizard input[type=password] { width:100%; background:var(--bp-bg); border:1px solid var(--bp-line); border-radius:6px; padding:6px 8px; min-height:40px; font-size:16px; }
.wizard input[aria-invalid=true] { border-color:var(--bp-danger); }
.wz-foot .btn, .pd-acts .btn, .wz-dev .btn { min-height:40px; }
.wz-dev .btn.small, .pd-acts .btn.small, .pd-note .btn.small { min-height:36px; }
@media (prefers-reduced-motion:reduce) { .spin, .progress i { animation-duration:3s; } }
.coarse .printer-chip { min-height:44px; border-radius:22px; }
.coarse .wz-foot .btn, .coarse .pd-acts .btn, .coarse .wz-dev .btn, .coarse .pd-note .btn.small { min-height:44px; }
.coarse .pd-acts .ibtn { width:44px; height:44px; }

/* phone: drawer and wizard become full-screen sheets */
.narrow .printer-chip .chip-status { margin-left:auto; }
.narrow .setup-btn .lbl { display:none; } .narrow .setup-btn .lbl-s { display:inline; }
.narrow .layer[data-mode=printers], .narrow .layer[data-mode=wizard] { padding:0; align-items:stretch; }
.narrow .pdrawer, .narrow .wizard { width:100%; max-height:none; height:100%; border-radius:0; box-shadow:none;  }
.narrow .pd-head, .narrow .wz-head { min-height:56px; }
.narrow .pd-acts .grow { flex-basis:0; }

`;
