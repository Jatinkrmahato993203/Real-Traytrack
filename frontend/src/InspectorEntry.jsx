import { useEffect, useState } from "react";
import { getColleges, getMessHalls, getChecklist, submitInspection } from "./api";
import ComplaintList from "./ComplaintList";
import StaffLogin, { StaffBar, useStaffSession } from "./StaffLogin";

export default function InspectorEntry() {
  const { staff, setStaff, checking, logout } = useStaffSession();

  const [colleges, setColleges] = useState([]);
  const [collegeId, setCollegeId] = useState("");
  const [messHalls, setMessHalls] = useState([]);
  const [messId, setMessId] = useState("");
  const [checklist, setChecklist] = useState([]);
  const [responses, setResponses] = useState({});
  const [result, setResult] = useState(null);
  const [error, setError] = useState("");

  useEffect(() => {
    if (!staff) return;
    // A college-scoped inspector only ever sees their own college.
    getColleges().then((all) => {
      const cs = staff.college_id ? all.filter((c) => c.id === staff.college_id) : all;
      setColleges(cs);
      if (cs.length) setCollegeId(cs[0].id);
    });
    getChecklist().then((items) => {
      setChecklist(items);
      const initial = {};
      items.forEach((i) => { initial[i.id] = true; });
      setResponses(initial);
    });
  }, [staff]);

  useEffect(() => {
    if (collegeId) getMessHalls(collegeId).then(setMessHalls);
    setMessId("");
  }, [collegeId]);

  async function handleSubmit(e) {
    e.preventDefault();
    setError(""); setResult(null);
    if (!messId) {
      setError("Choose a mess hall.");
      return;
    }
    try {
      const res = await submitInspection({ mess_id: Number(messId), responses });
      setResult(res);
    } catch (err) {
      setError(err.message);
    }
  }

  if (checking) return <div className="content">Loading…</div>;
  if (!staff) return <StaffLogin title="Inspector entry" onLoggedIn={setStaff} />;

  return (
    <div className="content">
      <h1>🔍 Inspector checklist entry</h1>
      <StaffBar staff={staff} onLogout={logout} />
      <form onSubmit={handleSubmit} className="form-card">
        <label>
          College
          <select value={collegeId} onChange={(e) => setCollegeId(Number(e.target.value))}>
            {colleges.map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}
          </select>
        </label>
        <label>
          Mess hall
          <select value={messId} onChange={(e) => setMessId(e.target.value)}>
            <option value="" disabled>Select a mess hall</option>
            {messHalls.map((m) => <option key={m.id} value={m.id}>{m.name}</option>)}
          </select>
        </label>
        <p className="hint">This inspection will be recorded under your account ({staff.name}).</p>

        <div>
          <p className="hint">Items marked ⚠️ Critical automatically trigger a High alert if failed.</p>
          {checklist.map((item) => (
            <label key={item.id} className="checkbox-row">
              <input
                type="checkbox"
                checked={!!responses[item.id]}
                onChange={(e) => setResponses({ ...responses, [item.id]: e.target.checked })}
              />
              {item.text}{item.critical && "  ⚠️ Critical"}
            </label>
          ))}
        </div>

        {error && <div className="banner error">{error}</div>}
        <button className="primary-btn" type="submit">Submit inspection</button>
      </form>

      {result && (
        <div className="banner success">
          <strong>
            Inspection recorded — score {result.score}%.{" "}
            {result.level ? `Severity: ${result.level}` : "No issues found, so no alert was raised."}
          </strong>
          <p>{result.reason}</p>
        </div>
      )}

      {messId && (
        <>
          <h2 style={{ marginTop: 28 }}>📋 Student complaints for this mess hall</h2>
          <p className="hint">What students have reported here — worth checking during the inspection.</p>
          <ComplaintList collegeId={collegeId} messId={messId} />
        </>
      )}
    </div>
  );
}
