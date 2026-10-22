import { useEffect, useState } from "react";
import QRCode from "qrcode";
import { newRecoveryCodes, twoFactorDisable, twoFactorEnable, twoFactorSetup } from "../../lib/api";
import { useStaff } from "../../lib/session";
import { ErrorBanner, Field } from "../../components/ui";

function RecoveryCodes({ codes, onDone }) {
  const text = `TrayTrack recovery codes\nEach works once, if you lose your phone.\n\n${codes.join("\n")}\n`;
  return (
    <div className="banner warn">
      <strong>Save these recovery codes now — they won't be shown again.</strong>
      <p>Each one signs you in once if you lose your phone. Keep them somewhere safe (not on the same phone).</p>
      <ul className="recovery-codes">{codes.map((c) => <li key={c}><code>{c}</code></li>)}</ul>
      <div className="button-row">
        <button type="button" className="secondary-btn" onClick={() => navigator.clipboard?.writeText(text)}>Copy</button>
        <a className="secondary-btn" download="traytrack-recovery-codes.txt" href={`data:text/plain;charset=utf-8,${encodeURIComponent(text)}`}>Download</a>
        {onDone && <button type="button" className="primary-btn" onClick={onDone}>I've saved them</button>}
      </div>
    </div>
  );
}

// Scan a QR code (or type the key) into an authenticator app, then confirm
// with a code from it. Used in My account and as the forced first step for
// roles that require two-factor sign-in.
export function TwoFactorSetup({ onEnabled }) {
  const [setup, setSetup] = useState(null);
  const [qr, setQr] = useState(null);
  const [code, setCode] = useState("");
  const [codes, setCodes] = useState(null);
  const [error, setError] = useState(null);

  useEffect(() => {
    if (setup) QRCode.toDataURL(setup.otpauth_uri, { width: 200, margin: 1 }).then(setQr);
  }, [setup]);

  if (codes) return <RecoveryCodes codes={codes} onDone={onEnabled} />;
  if (!setup) {
    return (
      <div>
        <p>Two-factor sign-in asks for a 6-digit code from an app on your phone (Google Authenticator, Microsoft Authenticator, Authy…) after your password — so a stolen password alone can't get in.</p>
        <ErrorBanner error={error} />
        <button type="button" className="primary-btn" onClick={() => twoFactorSetup().then(setSetup).catch(setError)}>Set up two-factor sign-in</button>
      </div>
    );
  }
  return (
    <form onSubmit={async (e) => {
      e.preventDefault();
      setError(null);
      try { setCodes((await twoFactorEnable(code)).recovery_codes); } catch (err) { setError(err); }
    }}>
      <ol className="steps">
        <li>Open your authenticator app and add an account by scanning this code:
          <div className="qr-box">{qr && <img src={qr} width={200} height={200} alt="QR code to add TrayTrack to your authenticator app" />}</div>
          <details><summary>Can't scan? Enter this key instead</summary><code className="secret-key">{setup.secret.match(/.{1,4}/g).join(" ")}</code></details>
        </li>
        <li>
          <Field label="Enter the 6-digit code the app shows">
            <input inputMode="numeric" autoComplete="one-time-code" pattern="[0-9 ]{6,7}" maxLength={7} required value={code} onChange={(e) => setCode(e.target.value)} />
          </Field>
        </li>
      </ol>
      <ErrorBanner error={error} />
      <button type="submit" className="primary-btn">Turn on</button>
    </form>
  );
}

export function TwoFactorPanel() {
  const { staff, refreshStaff } = useStaff();
  const [codes, setCodes] = useState(null);
  const [code, setCode] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState(null);

  if (!staff.two_factor_enabled) {
    return <TwoFactorSetup onEnabled={refreshStaff} />;
  }
  return (
    <div>
      <p className="ok-text">✓ Two-factor sign-in is on.</p>
      {codes && <RecoveryCodes codes={codes} onDone={() => setCodes(null)} />}
      <Field label="Code from your authenticator app (needed for the actions below)">
        <input inputMode="numeric" autoComplete="one-time-code" maxLength={9} value={code} onChange={(e) => setCode(e.target.value)} />
      </Field>
      <div className="button-row">
        <button type="button" className="secondary-btn" disabled={!code} onClick={async () => {
          setError(null);
          try { setCodes((await newRecoveryCodes(code)).recovery_codes); setCode(""); } catch (e) { setError(e); }
        }}>Get new recovery codes</button>
      </div>
      {!staff.two_factor_required && (
        <details>
          <summary>Turn off two-factor sign-in</summary>
          <Field label="Your password"><input type="password" autoComplete="current-password" value={password} onChange={(e) => setPassword(e.target.value)} /></Field>
          <button type="button" className="danger-btn" disabled={!code || !password} onClick={async () => {
            setError(null);
            try { await twoFactorDisable(password, code); refreshStaff(); } catch (e) { setError(e); }
          }}>Turn off</button>
        </details>
      )}
      {staff.two_factor_required && <p className="hint">Your role requires two-factor sign-in, so it can't be turned off. Lost your phone? Use a recovery code, or ask an admin to reset it.</p>}
      <ErrorBanner error={error} />
    </div>
  );
}
