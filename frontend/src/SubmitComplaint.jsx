import { useEffect, useState } from "react";
import { getColleges, getMessHalls, getCategories, submitComplaint } from "./api";

export default function SubmitComplaint({ userEmail }) {
  const [colleges, setColleges] = useState([]);
  const [messHalls, setMessHalls] = useState([]);
  const [categories, setCategories] = useState([]);

  const [collegeId, setCollegeId] = useState("");
  const [messId, setMessId] = useState("");
  const [studentName, setStudentName] = useState("");
  const [category, setCategory] = useState("");
  const [description, setDescription] = useState("");
  const [photoFile, setPhotoFile] = useState(null);

  const [submitting, setSubmitting] = useState(false);
  const [result, setResult] = useState(null);
  const [error, setError] = useState("");

  useEffect(() => {
    getColleges().then(setColleges);
    getCategories().then((c) => {
      setCategories(c);
      if (c.length) setCategory(c[0]);
    });
  }, []);

  useEffect(() => {
    if (collegeId) {
      getMessHalls(collegeId).then(setMessHalls);
      setMessId("");
    }
  }, [collegeId]);

  const selectedCollege = colleges.find((c) => c.id === Number(collegeId));

  async function handleSubmit(e) {
    e.preventDefault();
    setError("");
    setResult(null);

    if (!collegeId || !messId || !studentName.trim() || !category) {
      setError("Please fill in all required fields.");
      return;
    }

    setSubmitting(true);
    try {
      const res = await submitComplaint({
        college_id: Number(collegeId),
        mess_id: Number(messId),
        student_name: studentName,
        category,
        description,
      }, photoFile);
      setResult(res);
      setStudentName("");
      setDescription("");
      setPhotoFile(null);
    } catch (err) {
      setError(err.message);
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <div className="content">
      <h1>Report a problem</h1>
        <p className="subtitle">
          Your college email is already verified — your identity stays private and is never shown publicly.
        </p>

        <form onSubmit={handleSubmit} className="form-card">
          <label>
            Your college
            <select value={collegeId} onChange={(e) => setCollegeId(e.target.value)} required>
              <option value="" disabled>Select your college</option>
              {colleges.map((c) => (
                <option key={c.id} value={c.id}>{c.name}</option>
              ))}
            </select>
          </label>

          {selectedCollege && (
            <p className="hint">Authorized domain: <code>@{selectedCollege.email_domain}</code></p>
          )}

          <label>
            Mess hall
            <select value={messId} onChange={(e) => setMessId(e.target.value)} required disabled={!messHalls.length}>
              <option value="" disabled>Select a mess hall</option>
              {messHalls.map((m) => (
                <option key={m.id} value={m.id}>{m.name}</option>
              ))}
            </select>
          </label>

          <label>
            Full name (kept private)
            <input value={studentName} onChange={(e) => setStudentName(e.target.value)} required />
          </label>

          <label>
            What went wrong?
            <select value={category} onChange={(e) => setCategory(e.target.value)} required>
              {categories.map((c) => (
                <option key={c} value={c}>{c}</option>
              ))}
            </select>
          </label>

          <label>
            Describe the issue (optional)
            <textarea rows={4} value={description} onChange={(e) => setDescription(e.target.value)} />
          </label>

          <label>
            Photo of the problem (optional, max 4MB)
            <input
              type="file"
              accept="image/png, image/jpeg, image/webp"
              onChange={(e) => {
                const file = e.target.files?.[0] || null;
                if (file && file.size > 4 * 1024 * 1024) {
                  setError("Photo must be 4MB or smaller.");
                  e.target.value = "";
                  setPhotoFile(null);
                  return;
                }
                setError("");
                setPhotoFile(file);
              }}
            />
          </label>

          {error && <div className="banner error">{error}</div>}

          <button type="submit" className="primary-btn" disabled={submitting}>
            {submitting ? "Submitting…" : "Submit report"}
          </button>
        </form>

        {result && (
          <div className={`banner ${result.alert_created ? "success" : "info"}`}>
            {result.alert_created ? (
              <>
                <strong>Pattern confirmed — severity {result.level}.</strong>
                <p>{result.reason}</p>
              </>
            ) : (
              <>
                <strong>Report recorded and kept as evidence.</strong>
                <p>
                  {result.category_count}/{result.category_threshold} students reported this issue,{" "}
                  {result.mess_count}/{result.mess_threshold} reported any issue at this mess hall
                  (last {result.window_days} days).
                </p>
              </>
            )}
          </div>
        )}
    </div>
  );
}
