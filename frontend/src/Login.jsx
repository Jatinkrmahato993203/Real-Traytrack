import { GoogleLogin } from "@react-oauth/google";
import { loginWithGoogle } from "./api";

export default function Login({ onLoggedIn }) {
  async function handleSuccess(credentialResponse) {
    try {
      const info = await loginWithGoogle(credentialResponse.credential);
      localStorage.setItem("user_email", info.email);
      localStorage.setItem("user_name", info.name || "");
      localStorage.setItem("user_token", info.token);
      onLoggedIn(info.email);
    } catch (err) {
      alert("Sign-in failed. Please try again.");
    }
  }

  return (
    <div className="content">
      <div className="login-card" style={{ margin: "40px auto" }}>
        <div className="brand-mark">🍽️</div>
        <h1>Sign in required</h1>
        <p className="subtitle">Sign in with your college Google account to continue.</p>
        <div className="google-btn-wrap">
          <GoogleLogin
            onSuccess={handleSuccess}
            onError={() => alert("Google sign-in failed.")}
          />
        </div>
        <p className="fine-print">
          We only ever see your verified college email — nothing else.
        </p>
      </div>
    </div>
  );
}
