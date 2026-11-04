// Probe the shipped capture-overlay layout: the geometry of the extent dimensions.
//
// Loads convexHull, minAreaBox and extentGeometry from webapp/static/app.js and, for each
// outline in the input JSON ([{name, points}]), prints the dimension line and its two extension
// lines for both axes ("u" = length, "v" = width) on both sides, as JSON. The Python test checks
// them against cv2.minAreaRect, the box the measurement table uses.
import { readFileSync } from "node:fs";
import vm from "node:vm";

const src = readFileSync(process.argv[2], "utf8");
const cases = JSON.parse(readFileSync(process.argv[3], "utf8"));

function extract(name) {
  const start = src.indexOf(`function ${name}(`);
  if (start < 0) throw new Error(`${name} not found in the shipped app.js`);
  let depth = 0, i = src.indexOf("{", start);
  for (; i < src.length; i++) {
    if (src[i] === "{") depth++;
    if (src[i] === "}") { depth--; if (!depth) break; }
  }
  return src.slice(start, i + 1);
}

const sandbox = { scale: () => 1, cases, out: [] };
vm.createContext(sandbox);
vm.runInContext(`${["convexHull", "minAreaBox", "extentGeometry"].map(extract).join("\n")}
for (const { name, points } of cases) {
  const box = minAreaBox(points);
  const dims = [];
  for (const along of ["u", "v"]) for (const side of [-1, 1]) {
    dims.push({ along, side, ...extentGeometry(points, box, along, side, 30) });
  }
  out.push({ name, dims });
}`, sandbox);
console.log(JSON.stringify(sandbox.out));
