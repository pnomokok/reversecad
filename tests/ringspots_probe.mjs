// Probe the shipped capture-overlay layout: hole-label candidate spots.
//
// ringSpots must offer 16 angles per ring — the 8 compass points first, then the
// 8 half-offset angles — so a shared hole label lands between grid points when
// every compass spot is blocked (e.g. just inside a tilted part edge).
import { readFileSync } from "node:fs";
import vm from "node:vm";

const src = readFileSync(process.argv[2], "utf8");
const start = src.indexOf("function ringSpots(");
if (start < 0) throw new Error("ringSpots not found in the shipped app.js");
let depth = 0, i = src.indexOf("{", start);
for (; i < src.length; i++) {
  if (src[i] === "{") depth++;
  if (src[i] === "}") { depth--; if (!depth) break; }
}
const sandbox = { scale: () => 2 };
vm.createContext(sandbox);
vm.runInContext(`${src.slice(start, i + 1)}\nglobalThis.__spots = ringSpots([100, 200], 10, [30]);`, sandbox);

const spots = sandbox.__spots;
const fail = (msg) => { throw new Error(msg); };
if (spots.length !== 16) fail(`expected 16 spots per ring, got ${spots.length}`);
const radius = 10 + 30 * 2;
spots.forEach(([x, y], n) => {
  const k = n < 8 ? n : n - 8 + 0.5;
  const [ex, ey] = [100 + Math.cos((k / 8) * 2 * Math.PI) * radius,
                    200 + Math.sin((k / 8) * 2 * Math.PI) * radius];
  if (Math.hypot(x - ex, y - ey) > 1e-9) fail(`spot ${n} is [${x}, ${y}], expected [${ex}, ${ey}]`);
});
console.log(`ok: 16 spots, compass points first, then half-offsets (r=${radius})`);
