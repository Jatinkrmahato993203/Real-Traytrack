// Small shared building blocks used across pages.
import { useEffect, useState } from "react";
import { staffBlobUrl } from "../lib/api";
import { formatDateTime, timeAgo } from "../lib/time";
import { useI18n } from "../lib/i18n";

// Severity is never shown by colour alone: each level has its own shape
// and its name, and screen readers hear "Severity: High".
const LEVEL_SHAPE = { Low: "●", Medium: "◆", High: "▲" };

export function Severity({ level }) {
  const { t } = useI18n();
  if (!level) return null;
  return (
    <span className={`sev sev-${level.toLowerCase()}`} aria-label={`Severity: ${level}`}>
      <span aria-hidden="true">{LEVEL_SHAPE[level]}</span> {t(`level.${level}`)}
    </span>
  );
}

export function StatusPill({ status, prefix = "alertStatus" }) {
  const { t } = useI18n();
  if (!status) return null;
  return <span className={`pill pill-${status}`}>{t(`${prefix}.${status}`)}</span>;
}

export function When({ value }) {
  if (!value) return <span>—</span>;
  return <time dateTime={String(value)} title={formatDateTime(value)}>{timeAgo(value)}</time>;
}

export function Loading({ label }) {
  const { t } = useI18n();
  return <p className="hint" role="status">{label || t("common.loading")}</p>;
}

export function ErrorBanner({ error, onRetry }) {
  const { t } = useI18n();
  if (!error) return null;
  const message = typeof error === "string" ? error : error.message || t("error.generic");
  return (
    <div className="banner error" role="alert">
      <span>{message}</span>
      {error.requestId && error.status >= 500 && (
        <span className="hint"> ({t("common.reference")}: {error.requestId})</span>
      )}
      {onRetry && (
        <button type="button" className="link-btn" onClick={onRetry} style={{ marginLeft: 10 }}>
          {t("common.retry")}
        </button>
      )}
    </div>
  );
}

// Loads data, exposes {data, error, loading, reload}. Cancels stale requests.
export function useAsync(fn, deps) {
  const [state, setState] = useState({ data: null, error: null, loading: true });
  const [tick, setTick] = useState(0);
  useEffect(() => {
    let cancelled = false;
    setState((s) => ({ ...s, loading: true, error: null }));
    Promise.resolve()
      .then(fn)
      .then((data) => !cancelled && setState({ data, error: null, loading: false }))
      .catch((error) => !cancelled && setState((s) => ({ ...s, error, loading: false })));
    return () => { cancelled = true; };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [...deps, tick]);
  return { ...state, reload: () => setTick((n) => n + 1) };
}

// Staff-only photo: fetched with the staff token, shown via a blob URL.
export function StaffPhoto({ url, alt = "Attached photo", className = "photo-thumb" }) {
  const [src, setSrc] = useState(null);
  const [failed, setFailed] = useState(false);
  useEffect(() => {
    let objectUrl;
    let cancelled = false;
    staffBlobUrl(url)
      .then((u) => { objectUrl = u; if (!cancelled) setSrc(u); else URL.revokeObjectURL(u); })
      .catch(() => !cancelled && setFailed(true));
    return () => { cancelled = true; if (objectUrl) URL.revokeObjectURL(objectUrl); };
  }, [url]);
  if (failed) return <p className="hint">Photo unavailable.</p>;
  if (!src) return <p className="hint">Loading photo…</p>;
  return (
    <a href={src} target="_blank" rel="noreferrer">
      <img src={src} alt={alt} className={className} />
    </a>
  );
}

export function Pager({ offset, limit, total, onChange }) {
  if (!total || total <= limit) return null;
  const pageNo = Math.floor(offset / limit) + 1;
  const pages = Math.ceil(total / limit);
  return (
    <nav className="pager" aria-label="Pages">
      <button type="button" className="secondary-btn" disabled={offset === 0} onClick={() => onChange(Math.max(0, offset - limit))}>
        ← Previous
      </button>
      <span className="hint">Page {pageNo} of {pages} · {total} total</span>
      <button type="button" className="secondary-btn" disabled={offset + limit >= total} onClick={() => onChange(offset + limit)}>
        Next →
      </button>
    </nav>
  );
}

export function Field({ label, hint, children, optional }) {
  const { t } = useI18n();
  return (
    <label className="field">
      <span className="field-label">
        {label}
        {optional && <span className="hint"> ({t("common.optional")})</span>}
      </span>
      {children}
      {hint && <span className="hint">{hint}</span>}
    </label>
  );
}

export function EmptyState({ children }) {
  return <div className="banner info">{children}</div>;
}
