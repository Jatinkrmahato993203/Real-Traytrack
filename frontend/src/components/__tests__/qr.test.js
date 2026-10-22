import { describe, expect, it } from "vitest";
import QRCode from "qrcode";
import jsQR from "jsqr";

// The iPhone path of the kitchen-code scanner: jsQR must read the exact QR
// that Setup prints ("TRAYTRACK-KITCHEN:<code>").
function render(text, scale = 6, quiet = 4) {
  const { modules } = QRCode.create(text, { errorCorrectionLevel: "M" });
  const n = modules.size;
  const size = (n + quiet * 2) * scale;
  const data = new Uint8ClampedArray(size * size * 4).fill(255);
  for (let y = 0; y < n; y++) {
    for (let x = 0; x < n; x++) {
      if (!modules.get(y, x)) continue;
      for (let dy = 0; dy < scale; dy++) {
        for (let dx = 0; dx < scale; dx++) {
          const i = (((y + quiet) * scale + dy) * size + (x + quiet) * scale + dx) * 4;
          data[i] = data[i + 1] = data[i + 2] = 0;
        }
      }
    }
  }
  return { data, width: size, height: size };
}

describe("kitchen QR fallback decoder", () => {
  it("reads the printed kitchen code", () => {
    const img = render("TRAYTRACK-KITCHEN:WQX5J7");
    expect(jsQR(img.data, img.width, img.height)?.data).toBe("TRAYTRACK-KITCHEN:WQX5J7");
  });

  it("reads the table QR (report link)", () => {
    const url = "https://mess.college.edu/report?mess=12";
    const img = render(url, 3);
    expect(jsQR(img.data, img.width, img.height)?.data).toBe(url);
  });
});
