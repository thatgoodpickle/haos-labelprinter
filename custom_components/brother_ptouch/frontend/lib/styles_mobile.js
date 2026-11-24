// Phone (< 900 px) stylesheet, appended after styles.js. Everything is scoped to .narrow so desktop is untouched.
// Host-aware: no 100vh, no position:fixed; sizes come from the host (height:100%); safe-area insets are applied
// to the bars ourselves (the panel is registered with handle_safe_area false).
export const MOBILE_CSS = `
.mobile { display:none; }
.narrow > .topbar, .narrow > .pbar, .narrow > .body, .narrow > .tabs, .narrow > .pstrip-old { display:none !important; }
.narrow .mobile { display:flex; flex:1 1 0; min-height:0; min-width:0; flex-direction:column; position:relative; }
.narrow .mhome, .narrow .medit { display:none; flex:1 1 0; min-height:0; flex-direction:column; }
.narrow[data-view=home] .mhome, .narrow[data-view=edit] .medit { display:flex; }
.root.kb-open { height:calc(100% - var(--bp-kb, 0px)); }

/* top bars */
.mtop { display:flex; align-items:center; gap:4px; flex:none; min-height:56px; padding:0 8px; background:var(--bp-card); border-bottom:1px solid var(--bp-line); }
.mtop .grow, .msub .grow { flex:1 1 0; min-width:0; }
.mtitle { margin:0 0 0 4px; font-size:22px; font-weight:600; line-height:1.2; flex:none; }
.narrow .mtop .ibtn { width:44px; height:44px; }
.narrow .mtop .printer-chip { min-height:44px; max-width:62%; padding:0 10px 0 12px; border-radius:22px; }
.narrow .mtop .printer-chip .chip-status { margin-left:2px; }
.narrow .hamburger { display:none; }
.narrow.has-menu .hamburger { display:inline-flex; }
.narrow .mtop .hamburger { margin-left:-2px; }

/* home */
.mscroll { flex:1 1 0; min-height:0; overflow-y:auto; overflow-x:hidden; overscroll-behavior:contain; -webkit-overflow-scrolling:touch; }
.mpad { padding:14px 14px 24px; display:flex; flex-direction:column; gap:14px; max-width:960px; margin:0 auto; }
.cta { display:grid; grid-template-columns:1fr 1fr; gap:10px; }
.btn.big { min-height:56px; border-radius:16px; font-size:16px; font-weight:600; justify-content:center; padding:0 10px; gap:8px; }
.btn.big .ico { --mdc-icon-size:24px; width:24px; height:24px; }
.btn.big:not(.primary) { background:var(--bp-sel); border-color:transparent; color:var(--bp-accent); }
.hhead { display:flex; align-items:baseline; gap:8px; margin-top:6px; }
.hhead:empty { display:none; }
.hhead h2 { margin:0; font-size:15px; font-weight:600; color:var(--bp-text2); letter-spacing:.02em; }
.lgrid { display:grid; grid-template-columns:1fr; gap:12px; }
.lcard { background:var(--bp-card); border:1px solid var(--bp-line); border-radius:16px; overflow:hidden; display:flex; flex-direction:column; min-width:0; }
.lopen { display:block; width:100%; padding:10px 10px 0; border:none; background:none; cursor:pointer; }
.lthumb { height:96px; border-radius:10px; background:#fff; border:1px solid var(--bp-line); display:flex; align-items:center; justify-content:center; overflow:hidden; position:relative; color:#bbb; }
.lthumb img { max-width:100%; max-height:100%; object-fit:contain; display:block; }
.lthumb.loading::after { content:""; position:absolute; inset:0; background:linear-gradient(90deg, transparent, rgba(127,127,127,.22), transparent); background-size:200% 100%; animation:gal-shimmer 1.2s linear infinite; }
.lthumb.failed { background:repeating-linear-gradient(135deg, rgba(127,127,127,.12) 0 8px, rgba(127,127,127,.04) 8px 16px); color:#666; font-size:13px; }
.lthumb-ph .ico { --mdc-icon-size:32px; width:32px; height:32px; }
.lmeta { display:flex; align-items:center; padding:2px 2px 4px 14px; min-height:52px; }
.lname { flex:1; min-width:0; text-align:left; background:none; border:none; cursor:pointer; display:flex; flex-direction:column; gap:1px; padding:6px 0; min-height:44px; justify-content:center; }
.lname strong { font-size:16px; font-weight:600; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }
.lname span { font-size:13px; color:var(--bp-text2); }
.narrow .lmore { width:44px; height:44px; color:var(--bp-text2); }
.lcard.sk .lthumb { margin:10px 10px 0; }
.sk-line { height:12px; width:40%; border-radius:6px; background:var(--bp-surface2); }
.lempty { grid-column:1 / -1; display:flex; flex-direction:column; align-items:center; text-align:center; gap:6px; padding:36px 20px; color:var(--bp-text2); border:1.5px dashed var(--bp-line); border-radius:16px; }
.lempty .ico { --mdc-icon-size:44px; width:44px; height:44px; opacity:.6; }
.lempty strong { color:var(--bp-text); font-size:16px; }
.hstatus:empty { display:none; }
.scard { display:flex; gap:12px; padding:14px; border-radius:16px; background:var(--bp-info-bg); }
.scard.warn { background:var(--bp-warn-bg); } .scard.err { background:var(--bp-err-bg); }
.scard-ic .ico { --mdc-icon-size:28px; width:28px; height:28px; }
.scard-t { display:flex; flex-direction:column; gap:4px; min-width:0; flex:1; font-size:14px; line-height:1.4; }
.scard-t strong { font-size:16px; }
.scard-msg { font-weight:500; } .scard-msg.err { color:var(--bp-danger); }
.scard-acts { display:flex; gap:8px; flex-wrap:wrap; margin-top:8px; }
.scard-acts .btn { min-height:44px; }

/* editor */
.narrow .etop { gap:2px; padding-left:4px; padding-right:4px; }
.narrow .etop .name { flex:1 1 0; min-width:0; max-width:none; width:auto; border:1px solid transparent; background:transparent; border-radius:10px; font-size:17px; font-weight:600; padding:0 8px; min-height:44px; text-overflow:ellipsis; }
.narrow .etop .name:focus { border-color:var(--bp-accent); background:var(--bp-bg); outline:none; }
.narrow .etop .btn.primary { min-height:44px; padding:0 14px; border-radius:22px; margin-left:2px; font-size:15px; font-weight:600; }
.narrow .etop .setup-btn, .narrow .etop .save, .narrow .etop .dirty-dot { display:none !important; }
.narrow .u-sub { display:none; }
.msub { display:flex; align-items:center; gap:8px; flex:none; padding:2px 10px; min-height:48px; background:var(--bp-card); border-bottom:1px solid var(--bp-line); }
.mchip { display:inline-flex; align-items:center; gap:6px; min-height:44px; max-width:56%; flex:0 1 auto; padding:0 12px; border-radius:18px; border:1px solid var(--bp-line); background:var(--bp-bg); cursor:pointer; font-size:14px; white-space:nowrap; overflow:hidden; }
.mchip .ico { --mdc-icon-size:18px; width:18px; height:18px; color:var(--bp-text2); }
.mchip .tc-b { color:var(--bp-text2); overflow:hidden; text-overflow:ellipsis; }
.mchip.save { background:var(--bp-accent); color:var(--bp-on-accent); border-color:transparent; font-weight:600; }
.mchip.save .ico { color:inherit; }
.mchip.save:disabled { opacity:.5; }
.narrow .zoomchip { display:inline-flex; align-items:center; justify-content:center; min-width:56px; height:44px; padding:0 10px; font-size:14px; flex:none; }
.mstrips:empty { display:none; }
.narrow .mstrips .strip { font-size:13px; padding:6px 12px; }
.narrow .mstrips .strip.warn div, .narrow .mstrips .strip.err { overflow:hidden; display:-webkit-box; -webkit-line-clamp:2; -webkit-box-orient:vertical; }
.narrow .msgstrip-off { display:none; }
.narrow .mstrips .strip.info { display:none; }
.mbody { flex:1 1 0; min-height:0; display:flex; flex-direction:column; position:relative; }
.mmain { flex:1 1 0; min-height:0; display:flex; flex-direction:column; min-width:0; }
.narrow .scroller { flex:1 1 0; min-height:0; padding:26px 28px; display:flex; background:var(--bp-surface2);
  background-image:radial-gradient(rgba(127,127,127,.28) 1px, transparent 1.2px); background-size:16px 16px; }
.narrow .canvas-wrap { margin:auto; flex:none; display:block; }
.narrow .ruler { display:none; }
.narrow .empty-hint { color:#777; font-size:14px; padding:0 8px; text-align:center; }
.narrow .empty-hint .btn { display:none; }

/* bottom toolbar */
.mtool { flex:none; display:flex; align-items:stretch; gap:2px; padding:6px 6px 6px; background:var(--bp-card); border-top:1px solid var(--bp-line); }
.mtool[hidden] { display:none !important; }
.tbtn { flex:1 1 0; min-width:0; min-height:56px; display:flex; flex-direction:column; align-items:center; justify-content:center; gap:3px; border:none; background:none; border-radius:12px; cursor:pointer; font-size:14px; color:var(--bp-text); padding:2px 0; touch-action:manipulation; }
.tbtn .ico { --mdc-icon-size:26px; width:26px; height:26px; }
.tbtn span { max-width:100%; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }
.tbtn:active:not(:disabled) { background:var(--bp-sel2); }
.tbtn:disabled { opacity:.35; }
.tbtn.main { color:var(--bp-accent); font-weight:600; }
.tbtn.danger { color:var(--bp-danger); }
.mtool.tadd .tbtn:not(.more) .ico { color:var(--bp-accent); }

/* bottom sheet (properties) */
.bsheet { display:none; flex:none; flex-direction:column; min-height:0; background:var(--bp-card); border-top:1px solid var(--bp-line); border-radius:18px 18px 0 0; box-shadow:0 -4px 18px rgba(0,0,0,.2); overflow:hidden; transition:height .2s ease; z-index:3; }
.bsheet.dragging { transition:none; }
.bsheet:not([data-snap=closed]) { display:flex; }
.bsheet { position:relative; }
.grab { position:absolute; top:0; left:50%; margin-left:-60px; width:120px; height:44px; display:flex; align-items:flex-start; justify-content:center; padding-top:8px; cursor:grab; z-index:2; }
.grab .bar { width:44px; height:5px; border-radius:3px; background:var(--bp-line); filter:brightness(.8); }
.shead { flex:none; display:flex; align-items:center; gap:8px; padding:14px 8px 4px 14px; min-height:62px; font-weight:600; font-size:17px; }
.shead .sicon .ico { --mdc-icon-size:22px; width:22px; height:22px; color:var(--bp-text2); }
.shead .grow { flex:1; min-width:0; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }
.narrow .shead .btn { min-height:44px; padding:0 18px; }
.narrow .shead .sdel { width:44px; height:44px; color:var(--bp-danger); }
.narrow .sheet-body { flex:1 1 auto; min-height:0; overflow-y:auto; overflow-x:hidden; overscroll-behavior:contain; -webkit-overflow-scrolling:touch; touch-action:pan-y; padding:0 0 16px; }
.narrow .sheet-body .section { border-bottom:none; padding:4px 14px 8px; }
.narrow .sheet-body .section > h3 { display:none; }
.narrow .sheet-body .vars-box > h3 { display:flex; }
.narrow .sheet-body .section + .section { border-top:1px solid var(--bp-line); padding-top:12px; }
.narrow .sheet-body textarea { min-height:64px; }
.narrow .field > label, .narrow .hint, .narrow .small, .narrow .grid4 .g, .narrow .tag, .narrow .vars-head, .narrow .gal-need, .narrow .gal-fail, .narrow .lname span, .narrow .prow-t { font-size:14px; }
.narrow .badge { font-size:13px; }
.narrow input[type=checkbox] { -webkit-appearance:none; appearance:none; width:44px; height:44px; margin:0; padding:0; background:transparent; border:none; position:relative; cursor:pointer; flex:none; }
.narrow input[type=checkbox]::before { content:""; position:absolute; left:10px; top:10px; width:24px; height:24px; border:2px solid var(--bp-text2); border-radius:6px; box-sizing:border-box; }
.narrow input[type=checkbox]:checked::before { background:var(--bp-accent); border-color:var(--bp-accent); }
.narrow input[type=checkbox]:checked::after { content:""; position:absolute; left:19px; top:14px; width:6px; height:12px; border:solid var(--bp-on-accent); border-width:0 3px 3px 0; transform:rotate(45deg); }
.narrow input[type=checkbox]:disabled { opacity:.4; }
.gal-chips.more-r { -webkit-mask-image:linear-gradient(to right, #000 calc(100% - 36px), transparent); mask-image:linear-gradient(to right, #000 calc(100% - 36px), transparent); }
.gal-chips.more-l:not(.more-r) { -webkit-mask-image:linear-gradient(to left, #000 calc(100% - 36px), transparent); mask-image:linear-gradient(to left, #000 calc(100% - 36px), transparent); }
.gal-chips.more-l.more-r { -webkit-mask-image:linear-gradient(to right, transparent, #000 36px, #000 calc(100% - 36px), transparent); mask-image:linear-gradient(to right, transparent, #000 36px, #000 calc(100% - 36px), transparent); }
.narrow .field .tb-group { display:flex; gap:8px; width:100%; }
.narrow .field .tb-group select { flex:1; min-width:0; }
.narrow .field .tb-group input[type=number] { width:96px; flex:none; }
.narrow .grid4 { grid-template-columns:repeat(2, 1fr); }
.narrow .grid4 .g { font-size:12px; }
.narrow .tools { display:none; }

/* print sheet and action sheet (inside .layer) */
.print-sheet .pv { background:#fff; border:1px solid var(--bp-line); border-radius:10px; height:84px; display:flex; align-items:center; justify-content:center; overflow:hidden; margin:2px 0 10px; }
.print-sheet .pv img { max-width:100%; max-height:100%; object-fit:contain; }
.pbody { display:flex; flex-direction:column; gap:10px; }
.layer[data-mode=print] .print-sheet, .layer[data-mode=cut] .cut-sheet { display:block; }
.prow { display:flex; align-items:center; gap:12px; width:100%; min-height:56px; padding:8px 12px; border:1px solid var(--bp-line); border-radius:14px; background:var(--bp-card); text-align:left; cursor:pointer; }
.prow.static { cursor:default; }
.prow.warn { background:var(--bp-warn-bg); border-color:transparent; }
.prow-t { display:flex; flex-direction:column; flex:1; min-width:0; font-size:13px; color:var(--bp-text2); }
.prow-t strong { font-size:16px; color:var(--bp-text); }
.stepper { display:flex; align-items:center; gap:4px; }
.stepper output { min-width:36px; text-align:center; font-size:20px; font-weight:600; font-variant-numeric:tabular-nums; }
.ibtn.step { width:48px; height:48px; border:1px solid var(--bp-line); background:var(--bp-bg); }
.btn.big.go { margin-top:2px; }
.pstate { display:flex; flex-direction:column; align-items:center; text-align:center; gap:6px; padding:18px 8px; font-size:14px; }
.pstate strong { font-size:18px; }
.pstate.err .ico { --mdc-icon-size:44px; width:44px; height:44px; color:var(--bp-danger); }
.pstate.ok .ico { --mdc-icon-size:44px; width:44px; height:44px; color:#43a047; }
.layer[data-mode=menu] .menu-sheet { display:block; }
.asheet-item { display:flex; align-items:center; gap:14px; width:100%; min-height:56px; padding:0 8px; border:none; background:none; font-size:16px; text-align:left; cursor:pointer; border-radius:12px; }
.asheet-item:active { background:var(--bp-sel); }
.asheet-item .ico { --mdc-icon-size:24px; width:24px; height:24px; color:var(--bp-text2); }
.asheet-item.danger, .asheet-item.danger .ico { color:var(--bp-danger); }
.asheet-item:disabled { opacity:.4; }
.msheet { padding-bottom:14px; }
.narrow .dialog { width:min(380px, 100%); }
.narrow .dialog .acts { flex-direction:column-reverse; align-items:stretch; }
.narrow .dialog .acts .btn { min-height:48px; justify-content:center; }
.narrow .dialog .acts .btn[hidden] { display:none; }
.narrow .add-sheet .palette { grid-template-columns:repeat(3, 1fr); }

/* toast: floats above the bottom bar, inside the panel (never fixed to the viewport) */
.toast { position:absolute; left:50%; bottom:84px; transform:translateX(-50%); max-width:calc(100% - 32px); padding:10px 16px; border-radius:22px; background:#323232; color:#fff; font-size:14px; z-index:40; pointer-events:none; box-shadow:0 3px 12px rgba(0,0,0,.35); }
.toast.show { animation:toast-in .2s ease; }
@keyframes toast-in { from { opacity:0; transform:translate(-50%, 8px); } to { opacity:1; transform:translate(-50%, 0); } }
.sheet-open .toast { bottom:auto; top:64px; }

/* on-screen keyboard: more room for the field being edited */
.kb-open .msub, .kb-open .mtool { display:none; }
.kb-open .mtop { min-height:48px; }

@media (max-width:419px) { .mchip .tc-b { display:none; } }
@media (max-width:359px) {
  .narrow .zoomchip { display:none; }
  .mchip.save { font-size:0; padding:0 12px; gap:0; } .mchip.save .ico { margin:0; }
  .narrow .u-top { display:none; }
  .narrow .u-sub { display:inline-flex; }
  .narrow .etop .btn.primary { padding:0 12px; }
  .mchip .tc-b { display:none; }
  .narrow .printer-chip .chip-status { display:none; }
  .cta { grid-template-columns:1fr; }
}
@media (max-width:479px) { .narrow .etop .btn.primary .ico { display:none; } }
@media (min-width:640px) { .lgrid { grid-template-columns:repeat(2, 1fr); } }

/* landscape phones: sheet becomes a side panel, compact bars */
@media (orientation:landscape) and (max-height:520px) {
  .mtop { min-height:48px; }
  .kb-open .mtop { display:none; }
  .narrow .mtop .ibtn { width:40px; height:40px; }
  .msub { min-height:48px; padding:2px 10px; }
  .sheet-open .msub { display:none; }
  .mbody { flex-direction:row; }
  .bsheet { width:min(380px, 46%); height:auto !important; border-radius:0; border-top:none; border-left:1px solid var(--bp-line); box-shadow:-3px 0 12px rgba(0,0,0,.18); }
  .grab { display:none; }
  .tbtn { min-height:48px; flex-direction:row; gap:6px; font-size:13px; }
  .tbtn .ico { --mdc-icon-size:22px; width:22px; height:22px; }
  .mtool { padding-top:3px; padding-bottom:3px; }
  .cta { max-width:520px; }
  .lthumb { height:84px; }
}
`;
