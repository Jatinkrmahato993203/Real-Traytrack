import { useEffect, useRef, useState } from "react";

// Scans a QR code with the phone camera. Uses the browser's built-in
// BarcodeDetector where it exists (Chrome/Edge on Android); everywhere else —
// notably iPhone Safari — falls back to decoding camera frames with jsQR,
// loaded only when needed. The code is also printed under the QR, so typing
// it always works if the camera can't be used.
export const qrScanSupported =
  typeof navigator !== "undefined" && !!navigator.mediaDevices?.getUserMedia;

async function makeDetector() {
  if ("BarcodeDetector" in window) {
    try {
      const detector = new window.BarcodeDetector({ formats: ["qr_code"] });
      return async (video) => (await detector.detect(video))[0]?.rawValue || null;
    } catch { /* fall through to jsQR */ }
  }
  const { default: jsQR } = await import("jsqr");
  const canvas = document.createElement("canvas");
  const ctx = canvas.getContext("2d", { willReadFrequently: true });
  return async (video) => {
    const w = video.videoWidth;
    const h = video.videoHeight;
    if (!w || !h) return null;
    // Downscale big frames: faster, and QR codes survive it fine.
    const scale = Math.min(1, 640 / Math.max(w, h));
    canvas.width = Math.round(w * scale);
    canvas.height = Math.round(h * scale);
    ctx.drawImage(video, 0, 0, canvas.width, canvas.height);
    const image = ctx.getImageData(0, 0, canvas.width, canvas.height);
    return jsQR(image.data, image.width, image.height, { inversionAttempts: "dontInvert" })?.data || null;
  };
}

export default function QrScanner({ onResult, onClose }) {
  const videoRef = useRef(null);
  const [error, setError] = useState("");

  useEffect(() => {
    let stream;
    let stopped = false;
    let timer;
    (async () => {
      try {
        const detect = await makeDetector();
        stream = await navigator.mediaDevices.getUserMedia({ video: { facingMode: "environment" }, audio: false });
        if (stopped) return;
        const video = videoRef.current;
        video.srcObject = stream;
        video.setAttribute("playsinline", "true"); // iOS: don't go full-screen
        await video.play();
        const tick = async () => {
          if (stopped) return;
          try {
            const value = await detect(video);
            if (value) {
              onResult(value);
              return;
            }
          } catch { /* frame not ready yet */ }
          timer = setTimeout(tick, 250);
        };
        tick();
      } catch (e) {
        setError(
          e.name === "NotAllowedError"
            ? "Camera permission was denied — type the code instead."
            : window.isSecureContext === false
              ? "The camera only works over HTTPS — type the code instead."
              : "Couldn't start the camera — type the code instead.",
        );
      }
    })();
    return () => {
      stopped = true;
      clearTimeout(timer);
      stream?.getTracks().forEach((t) => t.stop());
    };
  }, [onResult]);

  return (
    <div className="scanner">
      {error ? <p className="banner warn">{error}</p> : <video ref={videoRef} muted playsInline aria-label="Camera preview for scanning the kitchen QR code" />}
      <button type="button" className="secondary-btn" onClick={onClose}>Close camera</button>
    </div>
  );
}
