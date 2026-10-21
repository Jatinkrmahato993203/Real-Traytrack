// The Content-Security-Policy for the built app. Used by `vite preview`
// (and the browser tests) via vite.config.js; nginx.conf carries the same
// policy for production — keep the two in sync.
//
// Allows exactly what the app uses: its own files, the API, Google
// Sign-In, Google Fonts, data:/blob: images (QR codes, camera). Inline
// styles are allowed (React style attributes); inline scripts are not.
export function contentSecurityPolicy(apiOrigin = "") {
  const api = apiOrigin ? ` ${apiOrigin}` : "";
  return [
    "default-src 'self'",
    "script-src 'self' https://accounts.google.com/gsi/client",
    "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com https://accounts.google.com/gsi/style",
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
