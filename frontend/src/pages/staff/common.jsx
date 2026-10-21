import { useEffect, useState } from "react";
import { staffColleges, staffMessHalls } from "../../lib/api";
import { useStaff } from "../../lib/session";
import { useAsync } from "../../components/ui";

// College + mess hall filters that respect the account's scope: a
// college-limited account never sees a college picker, a hall-limited one
// never sees a hall picker.
export function useScope({ withMess = true } = {}) {
  const { staff } = useStaff();
  const colleges = useAsync(staffColleges, []);
  const [collegeId, setCollegeId] = useState(staff.college_id ? String(staff.college_id) : "");
  const [messId, setMessId] = useState(staff.mess_id ? String(staff.mess_id) : "");
  const halls = useAsync(() => (withMess ? staffMessHalls(collegeId || undefined) : []), [collegeId, withMess]);

  useEffect(() => {
    if (!staff.mess_id) setMessId("");
  }, [collegeId, staff.mess_id]);

  return { staff, colleges, collegeId, setCollegeId, halls, messId, setMessId };
}

export function ScopeFilters({ scope, allowAllColleges = true, children }) {
  const { staff, colleges, collegeId, setCollegeId, halls, messId, setMessId } = scope;
  return (
    <div className="filters-row">
      {!staff.college_id && (
        <label className="field inline-field">
          <span className="field-label">College</span>
          <select value={collegeId} onChange={(e) => setCollegeId(e.target.value)}>
            {allowAllColleges && <option value="">All colleges</option>}
            {(colleges.data || []).map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}
          </select>
        </label>
      )}
      {!staff.mess_id && halls.data && (
        <label className="field inline-field">
          <span className="field-label">Mess hall</span>
          <select value={messId} onChange={(e) => setMessId(e.target.value)}>
            <option value="">All halls</option>
            {halls.data.map((h) => <option key={h.id} value={h.id}>{h.name}</option>)}
          </select>
        </label>
      )}
      {children}
    </div>
  );
}

export const COMPLAINT_STATUS_LABEL = {
  received: "New", acknowledged: "Acknowledged", action_taken: "Action taken", closed: "Closed", dismissed: "Dismissed",
};
