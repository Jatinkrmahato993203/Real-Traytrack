import { useEffect, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { getMeals, getMessHalls, getMyRatings, rateMeal } from "../../lib/api";
import { useI18n } from "../../lib/i18n";
import { useStudent } from "../../lib/session";
import { todayIso } from "../../lib/time";
import { ErrorBanner, Field, Loading, useAsync } from "../../components/ui";
import StudentGate from "./StudentGate";
import { currentMeal } from "../../lib/meal";

function Stars({ value, onChange }) {
  const { t } = useI18n();
  return (
    <div className="stars" role="radiogroup" aria-label={t("rate.how")}>
      {[1, 2, 3, 4, 5].map((n) => (
        <button
          key={n}
          type="button"
          role="radio"
          aria-checked={value === n}
          aria-label={`${n} — ${t(`rate.star${n}`)}`}
          className={`star ${n <= value ? "on" : ""}`}
          onClick={() => onChange(n)}
        >
          ★
        </button>
      ))}
      <span className="hint">{value ? t(`rate.star${value}`) : ""}</span>
    </div>
  );
}

function RateForm() {
  const { t } = useI18n();
  const { me } = useStudent();
  const [params] = useSearchParams();
  const halls = useAsync(() => getMessHalls(me.college.id), [me.college.id]);
  const meals = useAsync(getMeals, []);
  const mine = useAsync(getMyRatings, []);
  const [messId, setMessId] = useState(params.get("mess") || "");
  const [meal, setMeal] = useState(currentMeal());
  const [stars, setStars] = useState(0);
  const [comment, setComment] = useState("");
  const [error, setError] = useState(null);
  const [done, setDone] = useState(false);

  useEffect(() => {
    if (halls.data?.length === 1 && !messId) setMessId(String(halls.data[0].id));
  }, [halls.data, messId]);

  const today = (mine.data || []).filter((r) => String(r.rating_date).startsWith(todayIso()));
  const hallName = (id) => halls.data?.find((h) => h.id === id)?.name || "";

  async function submit(e) {
    e.preventDefault();
    setError(null);
    try {
      await rateMeal({ mess_id: Number(messId), meal, stars, comment: comment.trim() || null });
      setDone(true);
      setStars(0);
      setComment("");
      mine.reload();
    } catch (err) {
      setError(err);
    }
  }

  if (halls.loading) return <div className="content"><Loading /></div>;

  return (
    <div className="content">
      <h1>{t("rate.title")}</h1>
      <p className="subtitle">{t("rate.subtitle")}</p>
      {done && <div className="banner success" role="status">{t("rate.thanks")}</div>}
      <form className="form-card" onSubmit={submit}>
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
        <div className="field">
          <span className="field-label">{t("rate.how")}</span>
          <Stars value={stars} onChange={(n) => { setStars(n); setDone(false); }} />
        </div>
        <Field label={t("rate.comment")} optional>
          <input maxLength={280} value={comment} onChange={(e) => setComment(e.target.value)} />
        </Field>
        <ErrorBanner error={error} />
        <button type="submit" className="primary-btn" disabled={!stars || !messId}>{t("rate.submit")}</button>
      </form>

      {today.length > 0 && (
        <section>
          <h2 className="h3">{t("rate.today")}</h2>
          <ul className="plain-list">
            {today.map((r) => (
              <li key={`${r.mess_id}-${r.meal}`}>{hallName(r.mess_id)} · {t(`meal.${r.meal}`)} · {"★".repeat(r.stars)}</li>
            ))}
          </ul>
        </section>
      )}
    </div>
  );
}

export default function Rate() {
  return <StudentGate><RateForm /></StudentGate>;
}
