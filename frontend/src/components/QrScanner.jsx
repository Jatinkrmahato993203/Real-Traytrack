import { useEffect, useRef, useState } from "react";

// Scans a QR code with the camera where the browser supports BarcodeDetector
// (Chrome/Edge on Android, most Chromium desktops). Elsewhere it explains
// that the code can be typed in — the code is printed under the QR anyway.
export const qrScanSupported = typeof window !== "undefined" && "BarcodeDetector" in window;

export default function QrScanner({ onResult, onClose }) {
  const videoRef = useRef(null);
  const [error, setError] = useState("");

  useEffect(() => {
    let stream;
    let stopped = false;
    let timer;
    (async () => {
      try {
        const detector = new window.BarcodeDetector({ formats: ["qr_code"] });
        stream = await navigator.mediaDevices.getUserMedia({ video: { facingMode: "environment" } });
        if (stopped) return;
        videoRef.current.srcObject = stream;
        await videoRef.current.play();
        const tick = async () => {
          if (stopped) return;
          try {
            const codes = await detector.detect(videoRef.current);
            if (codes.length) {
              onResult(codes[0].rawValue);
              return;
            }
          } catch { /* frame not ready yet */ }
          timer = setTimeout(tick, 250);
        };
        tick();
      } catch (e) {
        setError(e.name === "NotAllowedError" ? "Camera permission was denied — type the code instead." : "Couldn't start the camera — type the code instead.");
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
