// Student and staff sessions, shared app-wide. Tokens live in localStorage
// (so a new tab stays signed in); the server is the source of truth, and any
// 401 drops the session via the "tt-session-expired" event.
import { createContext, useCallback, useContext, useEffect, useState } from "react";
import { getMe, getStaffMe, staffLogin, tokens } from "./api";

const StudentContext = createContext(null);
const StaffContext = createContext(null);

export function SessionProvider({ children }) {
  // ---- student ----
  const [me, setMe] = useState(null);
  const [studentChecking, setStudentChecking] = useState(!!tokens.student());

  const refreshMe = useCallback(async () => {
    if (!tokens.student()) {
      setMe(null);
      setStudentChecking(false);
      return null;
    }
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

  const studentSignIn = useCallback((data) => {
    tokens.setStudent(data.token);
    const { token: _token, ...rest } = data;
    setMe(rest);
  }, []);

  const studentSignOut = useCallback(() => {
    tokens.setStudent(null);
    setMe(null);
  }, []);

  // ---- staff ----
  const [staff, setStaff] = useState(null);
  const [staffChecking, setStaffChecking] = useState(!!tokens.staff());
  const [staffNotice, setStaffNotice] = useState("");

  useEffect(() => {
    refreshMe();
    if (tokens.staff()) {
      getStaffMe()
        .then(setStaff)
        .catch(() => tokens.setStaff(null))
        .finally(() => setStaffChecking(false));
    }
  }, [refreshMe]);

  const staffSignIn = useCallback(async (email, password) => {
    const data = await staffLogin(email, password);
    tokens.setStaff(data.token);
    setStaffNotice("");
    setStaff(data.staff);
    return data.staff;
  }, []);

  const staffSignOut = useCallback((notice = "") => {
    tokens.setStaff(null);
    setStaff(null);
    setStaffNotice(notice);
  }, []);

  useEffect(() => {
    const onExpired = (e) => {
      if (e.detail === "staff") staffSignOut("Your session expired or your access changed — please log in again.");
      if (e.detail === "student") studentSignOut();
    };
    window.addEventListener("tt-session-expired", onExpired);
    return () => window.removeEventListener("tt-session-expired", onExpired);
  }, [staffSignOut, studentSignOut]);

  const can = useCallback((cap) => !!staff?.capabilities?.includes(cap), [staff]);

  return (
    <StudentContext.Provider value={{ me, checking: studentChecking, refreshMe, signIn: studentSignIn, signOut: studentSignOut }}>
      <StaffContext.Provider value={{ staff, checking: staffChecking, notice: staffNotice, signIn: staffSignIn, signOut: staffSignOut, can }}>
        {children}
      </StaffContext.Provider>
    </StudentContext.Provider>
  );
}

export const useStudent = () => useContext(StudentContext);
export const useStaff = () => useContext(StaffContext);
