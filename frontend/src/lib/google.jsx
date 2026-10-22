// Google Sign-In, loaded only where a student sign-in button is shown — so
// Google's script never runs on the dashboard, staff pages, etc.
import { GoogleOAuthProvider } from "@react-oauth/google";

export const GOOGLE_CLIENT_ID =
  import.meta.env.VITE_GOOGLE_CLIENT_ID || "964017053673-hg64g75ro6kbgl1345dats7ca0pgeq3s.apps.googleusercontent.com";

// The per-request CSP nonce the server put in <meta name="csp-nonce">.
// Google's script uses it for the one <style> block it injects; without it
// the strict policy (rightly) refuses that block.
export function cspNonce() {
  const value = document.querySelector('meta[name="csp-nonce"]')?.content;
  return value && value !== "__CSP_NONCE__" ? value : undefined;
}

export function GoogleSignInProvider({ children }) {
  return (
    <GoogleOAuthProvider clientId={GOOGLE_CLIENT_ID} nonce={cspNonce()}>
      {children}
    </GoogleOAuthProvider>
  );
}
