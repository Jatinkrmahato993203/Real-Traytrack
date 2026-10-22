import { useState } from "react";
import { Link } from "react-router-dom";
import { GoogleLogin } from "@react-oauth/google";
import { GoogleSignInProvider } from "../../lib/google";
import { acceptPrivacy, getPrivacyInfo, loginWithGoogle } from "../../lib/api";
import { useI18n } from "../../lib/i18n";
import { useStudent } from "../../lib/session";
import { ErrorBanner, Loading, useAsync } from "../../components/ui";

// Wraps every student page: sign in → accept the privacy notice → content.
export default function StudentGate({ children, requireCollege = true }) {
  const { t } = useI18n();
  const { me, checking, signIn, refreshMe } = useStudent();
  const [error, setError] = useState(null);
  const [busy, setBusy] = useState(false);
  const privacy = useAsync(getPrivacyInfo, []);

  if (checking) return <div className="content"><Loading /></div>;

  if (!me) {
    return (
      <div className="content">
        <div className="login-card">
          <div className="brand-mark" aria-hidden="true">🍽️</div>
          <h1>{t("login.title")}</h1>
          <p className="subtitle">{t("login.subtitle")}</p>
          <div className="google-btn-wrap">
            <GoogleSignInProvider>
            <GoogleLogin
              onSuccess={async (cred) => {
                setError(null);
                try {
                  signIn(await loginWithGoogle(cred.credential));  // the server sets the session cookie
                } catch (e) {
                  setError(e);
                }
              }}
              onError={() => setError(t("login.failed"))}
            />
            </GoogleSignInProvider>
          </div>
          <ErrorBanner error={error} />
        </div>
      </div>
    );
  }

  if (me.consent_needed) {
    const days = privacy.data?.retention_days ?? 365;
    return (
      <div className="content">
        <div className="form-card">
          <h1 className="h2">{t("consent.title")}</h1>
          <ul className="consent-list">
            <li>{t("consent.p1")}</li>
            <li>{t("consent.p2")}</li>
            <li>{t("consent.p3", { days })}</li>
          </ul>
          <Link to="/privacy">{t("consent.read")}</Link>
          <ErrorBanner error={error} />
          <button
            type="button"
            className="primary-btn"
            disabled={busy}
            onClick={async () => {
              setBusy(true);
              setError(null);
              try {
                await acceptPrivacy(me.privacy_version);
                await refreshMe();
              } catch (e) {
                setError(e);
              } finally {
                setBusy(false);
              }
            }}
          >
            {t("consent.accept")}
          </button>
        </div>
      </div>
    );
  }

  if (requireCollege && !me.college) {
    return (
      <div className="content">
        <div className="banner info">{t("login.notCollege", { domain: me.email.split("@")[1] })}</div>
      </div>
    );
  }

  return children;
}
