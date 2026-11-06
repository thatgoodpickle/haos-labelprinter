// Records every WebSocket message the panel's Api wrapper can send (with realistic arguments) and prints
// them as JSON. tests/test_frontend_contract.py replays them against the real Home Assistant backend, so a
// schema mismatch between the UI and the backend fails a test instead of a user.
//   node dev/tests/capture_calls.mjs
import { Api } from "../../lib/api.js";
import { addPayload } from "../../lib/printer_logic.js";

const sent = [];
let current = "";
const hass = { callWS: (msg) => { sent.push({ name: current, msg: JSON.parse(JSON.stringify(msg)) }); return Promise.resolve({}); } };
const api = new Api(hass);
const run = async (name, fn) => { current = name; try { await fn(); } catch { /* wrappers post-process an empty reply */ } };

const design = {
  name: "Contract", length_mm: null, padding_dots: 6, variables: { name: "Flour" },
  elements: [
    { id: "t", type: "text", x: 0, y: 0, w: 200, h: 60, text: "{{ name }}", font: "", weight: 400, italic: false, size: "auto", align: "center", valign: "middle" },
    { id: "q", type: "qr", x: 210, y: 0, w: 60, h: 60, data: "https://example.com", ecc: "m" },
  ],
};

await run("printers", () => api.printers());
await run("listDesigns", () => api.listDesigns());
await run("getDesign", () => api.getDesign("DESIGN"));
await run("saveDesign", () => api.saveDesign(design));
await run("deleteDesign", () => api.deleteDesign("DESIGN"));
await run("preview", () => api.preview(design, { tape_mm: 12, entry_id: "ENTRY", variables: { name: "Rice" } }));
await run("preview-3.5", () => api.preview(design, { tape_mm: 3.5 }));
await run("print-design", () => api.print({ design, entry_id: "ENTRY", variables: { name: "Rice" }, copies: 2 }));
await run("print-id", () => api.print({ id: "DESIGN", entry_id: "ENTRY" }));
await run("print-chain-cutmark", () => api.print({ design, entry_id: "ENTRY", chain: true, cutMark: true }));
await run("print-no-autocut", () => api.print({ design, entry_id: "ENTRY", autoCut: false }));
await run("feed", () => api.feed("ENTRY"));
await run("searchFonts", () => api.searchFonts("rob", "sans-serif", 40));
await run("ensureFont", () => api.ensureFont("Roboto", 700, true));
await run("templatesList", () => api.templatesList());
await run("buildTemplate", () => api.buildTemplate("TEMPLATE", 12, "ENTRY"));
await run("btStatus", () => api.btStatus());
await run("btScan", () => api.btScan(8));
await run("btPair", () => api.btPair("AA:BB:CC:DD:EE:01"));
await run("btPair-pin", () => api.btPair("AA:BB:CC:DD:EE:01", "0000"));
await run("btForget", () => api.btForget("AA:BB:CC:DD:EE:01"));
await run("btConnect", () => api.btConnect("ENTRY"));
const dev = { address: "AA:BB:CC:DD:EE:01", name: "PT-P710BT1234" };
await run("addPrinter-bt", () => api.addPrinter(addPayload({ method: "bluetooth", device: dev })));
await run("addPrinter-usb", () => api.addPrinter(addPayload({ method: "usb", serial: "" })));
await run("addPrinter-usb-serial", () => api.addPrinter(addPayload({ method: "usb", serial: " E123 " })));
await run("addPrinter-bridge", () => api.addPrinter(addPayload({ method: "bridge", url: "http://10.0.0.5:8765", token: "" })));
await run("addPrinter-bridge-token", () => api.addPrinter(addPayload({ method: "bridge", url: "http://10.0.0.5:8765", token: "s3cret" })));
await run("removePrinter", () => api.removePrinter("ENTRY"));
await run("renamePrinter", () => api.renamePrinter("ENTRY", "Office"));
await run("testPrint", () => api.testPrint("ENTRY"));
await run("searchIcons", () => api.searchIcons("tag", 120));

process.stdout.write(JSON.stringify(sent));
