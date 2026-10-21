import { useEffect, useState } from "react";
import { fetchComplaintPhoto } from "./api";

// A complaint photo loaded with the staff session (photos aren't public).
// Clicking opens the full-size image in a new tab.
export default function StaffPhoto({ photoUrl, className, style }) {
  const [src, setSrc] = useState(null);
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    let objectUrl = null;
    let cancelled = false;
    setSrc(null);
    setFailed(false);
    fetchComplaintPhoto(photoUrl)
      .then((url) => {
        if (cancelled) URL.revokeObjectURL(url);
        else setSrc((objectUrl = url));
      })
      .catch(() => { if (!cancelled) setFailed(true); });
    return () => {
      cancelled = true;
      if (objectUrl) URL.revokeObjectURL(objectUrl);
    };
  }, [photoUrl]);

  if (failed) return <p className="hint">(Photo unavailable)</p>;
  if (!src) return <p className="hint">Loading photo…</p>;
  return (
    <a href={src} target="_blank" rel="noreferrer">
      <img src={src} alt="Attached evidence" className={className} style={style} />
    </a>
  );
}
