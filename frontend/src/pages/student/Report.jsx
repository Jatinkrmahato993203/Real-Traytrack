import { useEffect, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { getCategories, getMeals, getMessHalls, submitComplaint } from "../../lib/api";
import { useI18n } from "../../lib/i18n";
import { useStudent } from "../../lib/session";
import { ErrorBanner, Field, Loading, Severity, useAsync } from "../../components/ui";
import StudentGate from "./StudentGate";

const MAX_PHOTO = 4 * 1024 * 1024;
// Who an alert of each level goes to (mirrors the backend's authority chain).
const AUTHORITY = { Low: "Mess Head", Medium: "Principal", High: "FSSAI" };

// Pre-selects the meal by time of day (local time).
function currentMeal() {
  const h = new Date().getHours();
  if (h < 11) return "breakfast";
  if (h < 16) return "lunch";
  if (h < 19) return "snacks";
  return "dinner";
}

function ReportForm() {
  const { t, tCategory } = useI18n();
  const { me } = useStudent();
  const [params] = useSearchParams();
  const halls = useAsync(() => getMessHalls(me.college.id), [me.college.id]);
  const categories = useAsync(getCategories, []);
  const meals = useAsync(getMeals, []);

  // A QR code on a table opens /report?mess=ID with the hall already chosen.
  const [messId, setMessId] = useState(params.get("mess") || "");
  const [meal, setMeal] = useState(currentMeal());
  const [dish, setDish] = useState("");
  const [category, setCategory] = useState("");
  const [description, setDescription] = useState("");
  const [photo, setPhoto] = useState(null);
  const [anonymous, setAnonymous] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const [result, setResult] = useState(null);

  useEffect(() => {
    if (halls.data?.length === 1 && !messId) setMessId(String(halls.data[0].id));
  }, [halls.data, messId]);

  const chosen = categories.data?.find((c) => c.name === category);

  async function handleSubmit(e) {
    e.preventDefault();
    setError(null);
    if (!messId) return setError(t("report.chooseHall"));
    setBusy(true);
    try {
      setResult(await submitComplaint({ mess_id: messId, category, description, meal, dish, anonymous }, photo));
    } catch (err) {
      setError(err);
    } finally {
      setBusy(false);
    }
  }

  if (result) {
    return (
      <div className="content">
        <div className={`banner ${result.alert_created ? "warn" : "success"}`} role="status">
          <strong>{t("report.recorded")}</strong>
          {result.alert_created ? (
            <p>
              <Severity level={result.level} />{" "}
              {t("report.alert", { level: t(`level.${result.level}`), who: t(`authority.${AUTHORITY[result.level]}`) })}
            </p>
          ) : result.fast_lane ? (
            <p>{t("report.fastProgress", { c: result.fast_lane_count, ct: result.fast_lane_threshold, h: result.fast_lane_hours })}</p>
          ) : (
            <p>{t("report.progress", { c: result.category_count, ct: result.category_threshold, d: result.window_days })}</p>
          )}
        </div>
        <div className="button-row">
          <Link className="primary-btn" to="/my-reports">{t("report.track")}</Link>
          <button type="button" className="secondary-btn" onClick={() => {
            setResult(null); setDescription(""); setDish(""); setPhoto(null); setCategory("");
          }}>{t("report.another")}</button>
        </div>
      </div>
    );
  }

  if (halls.loading || categories.loading) return <div className="content"><Loading /></div>;

  return (
    <div className="content">
      <h1>{t("report.title")}</h1>
      <p className="subtitle">{t("report.subtitle")}</p>
      <p className="hint">{t("report.signedIn", { email: me.email })} · {me.college.name}</p>
      <ErrorBanner error={halls.error || categories.error} onRetry={() => { halls.reload(); categories.reload(); }} />

      <form onSubmit={handleSubmit} className="form-card" noValidate>
        <Field label={t("common.messHall")}>
          <select value={messId} onChange={(e) => setMessId(e.target.value)} required>
            <option value="" disabled>{t("common.selectHall")}</option>
            {(halls.data || []).map((m) => <option key={m.id} value={m.id}>{m.name}</option>)}
          </select>
        </Field>

        <fieldset className="choice-group">
          <legend className="field-label">{t("report.meal")}</legend>
          <div className="chips">
            {(meals.data || []).map((m) => (
              <label key={m} className={`chip ${meal === m ? "on" : ""}`}>
                <input type="radio" name="meal" value={m} checked={meal === m} onChange={() => setMeal(m)} />
                {t(`meal.${m}`)}
              </label>
            ))}
          </div>
        </fieldset>

        <Field label={t("report.dish")} optional>
          <input value={dish} maxLength={120} placeholder={t("report.dishPlaceholder")} onChange={(e) => setDish(e.target.value)} />
        </Field>

        <Field label={t("report.category")}>
          <select value={category} onChange={(e) => setCategory(e.target.value)} required>
            <option value="" disabled>—</option>
            {(categories.data || []).map((c) => (
              <option key={c.name} value={c.name}>{tCategory(c.name)}</option>
            ))}
          </select>
        </Field>
        {chosen?.fast_lane && <p className="banner warn small">{t("report.fastLane")}</p>}

        <Field label={t("report.describe")} hint={t("report.describeHint")} optional>
          <textarea rows={4} maxLength={2000} value={description} onChange={(e) => setDescription(e.target.value)} />
        </Field>

        <Field label={t("report.photo")} hint={t("report.photoHint")} optional>
          <input
            type="file"
            accept="image/jpeg,image/png,image/webp"
            capture="environment"
            onChange={(e) => {
              const file = e.target.files?.[0] || null;
              if (file && file.size > MAX_PHOTO) {
                setError(t("report.photoTooBig"));
                e.target.value = "";
                return setPhoto(null);
              }
              setError(null);
              setPhoto(file);
            }}
          />
        </Field>

        <label className="checkbox-row">
          <input type="checkbox" checked={anonymous} onChange={(e) => setAnonymous(e.target.checked)} />
          <span>
            {t("report.anonymous")}
            <span className="hint block">{t("report.anonymousHint")}</span>
          </span>
        </label>

        <ErrorBanner error={error} />
        <button type="submit" className="primary-btn" disabled={busy || !category}>
          {busy ? t("common.submitting") : t("report.submit")}
        </button>
      </form>
    </div>
  );
}

export default function Report() {
  return <StudentGate><ReportForm /></StudentGate>;
}
