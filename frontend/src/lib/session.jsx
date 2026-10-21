// Student and staff sessions, shared app-wide. The sessions themselves are
// HttpOnly cookies the app can't read; on load we ask the server who we
// are. Any 401 from an authenticated call drops the session via the
// "tt-session-expired" event.
import { createContext, useCallback, useContext, useEffect, useState } from "react";
import { getMe, getStaffMe, staffLogin, staffLogout, studentLogout } from "./api";

const StudentContext = createContext(null);
const StaffContext = createContext(null);

export function SessionProvider({ children }) {
  // ---- student ----
  const [me, setMe] = useState(null);
  const [studentChecking, setStudentChecking] = useState(true);

  const refreshMe = useCallback(async () => {
    try {
      const data = await getMe();
      setMe(data);
      return data;
    } catch {
      setMe(null);
      return null;
    } finally {
      setStudentChecking(false);
    }
  }, []);

  const studentSignIn = useCallback((data) => setMe(data), []);

  const studentSignOut = useCallback(async () => {
    setMe(null);
    try { await studentLogout(); } catch { /* already signed out */ }
  }, []);

  // ---- staff ----
  const [staff, setStaff] = useState(null);
  const [staffChecking, setStaffChecking] = useState(true);
  const [staffNotice, setStaffNotice] = useState("");

  useEffect(() => {
    refreshMe();
    getStaffMe()
      .then(setStaff)
      .catch(() => setStaff(null))
      .finally(() => setStaffChecking(false));
  }, [refreshMe]);

  const staffSignIn = useCallback(async (email, password) => {
    const data = await staffLogin(email, password);
    setStaffNotice("");
    setStaff(data.staff);
    return data.staff;
  }, []);

  const staffSignOut = useCallback(async (notice = "") => {
    setStaff(null);
    setStaffNotice(notice);
    if (!notice) {
      try { await staffLogout(); } catch { /* already signed out */ }
    }
  }, []);

  useEffect(() => {
    const onExpired = (e) => {
      if (e.detail === "staff") staffSignOut("Your session expired or your access changed — please sign in again.");
      if (e.detail === "student") setMe(null);
    };
    window.addEventListener("tt-session-expired", onExpired);
    return () => window.removeEventListener("tt-session-expired", onExpired);
  }, [staffSignOut]);

  const can = useCallback((cap) => !!staff?.capabilities?.includes(cap), [staff]);

  return (
    <StudentContext.Provider value={{ me, checking: studentChecking, refreshMe, signIn: studentSignIn, signOut: studentSignOut }}>
      <StaffContext.Provider value={{ staff, setStaff, checking: staffChecking, notice: staffNotice, signIn: staffSignIn, signOut: staffSignOut, can }}>
        {children}
      </StaffContext.Provider>
    </StudentContext.Provider>
  );
}

export const useStudent = () => useContext(StudentContext);
export const useStaff = () => useContext(StaffContext);
