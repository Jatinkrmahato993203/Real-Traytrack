// The Content-Security-Policy for the built app. Used by `vite preview`
// (and the browser tests) via vite.config.js; nginx.conf carries the same
// policy for production — keep the two in sync.
//
// Allows exactly what the app uses: its own files, the API, Google
// Sign-In, Google Fonts, data:/blob: images (QR codes, camera). Inline
// scripts and inline <style> blocks are refused.
// `nonce`: the per-request value also placed in <meta name="csp-nonce">; it
// lets Google Sign-In's single injected <style> block through and nothing else.
export function contentSecurityPolicy(apiOrigin = "", nonce = "") {
  const api = apiOrigin ? ` ${apiOrigin}` : "";
  const n = nonce ? ` 'nonce-${nonce}'` : "";
  return [
    "default-src 'self'",
    "script-src 'self' https://accounts.google.com/gsi/client",
    // Stylesheets and <style> blocks: only our own and Google's. Inline
    // style *attributes* (React style={{…}}, chart sizing) are allowed —
    // they can't run script — but injected <style> blocks are not.
    `style-src 'self' https://fonts.googleapis.com https://accounts.google.com/gsi/style${n}`,
    `style-src-elem 'self' https://fonts.googleapis.com https://accounts.google.com/gsi/style${n}`,
    "style-src-attr 'unsafe-inline'",
    "font-src 'self' https://fonts.gstatic.com",
    `img-src 'self' data: blob: https://*.googleusercontent.com${api}`,
    `connect-src 'self' https://accounts.google.com/gsi/${api}`,
    "frame-src https://accounts.google.com/gsi/",
    "object-src 'none'",
    "base-uri 'self'",
    "form-action 'self'",
    "frame-ancestors 'none'",
  ].join("; ");
}
