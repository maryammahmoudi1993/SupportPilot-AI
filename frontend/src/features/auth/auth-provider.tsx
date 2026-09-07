"use client";

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";
import type { ReactNode } from "react";

import {
  fetchCurrentUser,
  login as loginRequest,
  logout as logoutRequest,
} from "@/features/auth/api";
import type { CurrentUser, LoginCredentials } from "@/features/auth/types";
import { ApiError, isUncertainSessionError } from "@/lib/api/errors";
import { isLogoutPending } from "@/lib/api/logout-intent";
import { setSessionExpiredHandler } from "@/lib/api/token-store";

export type AuthStatus = "loading" | "authenticated" | "unauthenticated";

export interface AuthState {
  status: AuthStatus;
  user: CurrentUser | null;
  /**
   * Set when the most recent bootstrap/revalidate attempt failed because
   * the network was unreachable or timed out, rather than because the
   * session was proven invalid — `status` is still "unauthenticated" (the
   * safe default: never claim authenticated without proof), but a caller
   * that wants to offer "Retry" instead of "please log in" can check this.
   */
  error: ApiError | null;
  /**
   * True when a logout could not be confirmed server-side (the refresh
   * token's revocation request failed — network, CSRF, or server error).
   * The user IS locally signed out (privileged UI is already gone by the
   * time this is ever true), but the backend session may still be live
   * until it naturally expires or a later attempt succeeds — never
   * represent this state to the user as "you are fully signed out".
   */
  logoutPending: boolean;
}

export interface AuthContextValue extends AuthState {
  login: (credentials: LoginCredentials) => Promise<void>;
  logout: () => Promise<void>;
  /** Re-run session bootstrap (e.g. after a "Retry" action on a network error). */
  revalidate: () => Promise<void>;
}

const AuthContext = createContext<AuthContextValue | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [state, setState] = useState<AuthState>({
    status: "loading",
    user: null,
    error: null,
    logoutPending: false,
  });

  // Bootstrap/revalidate calls race if e.g. a mount-time bootstrap is still
  // in flight when something else calls revalidate(); only the latest call
  // is allowed to commit state.
  const requestId = useRef(0);

  const bootstrap = useCallback(async () => {
    const id = ++requestId.current;
    setState((prev) => ({ ...prev, status: "loading" }));

    if (isLogoutPending()) {
      // A prior logout's server-side revocation was never confirmed. Retry
      // it before doing anything else — the user must not be silently
      // re-authenticated by a refresh cookie that logout intended to kill,
      // just because it survived to the next page load.
      const result = await logoutRequest();
      if (id !== requestId.current) {
        return;
      }
      if (result === "server_unconfirmed") {
        setState({ status: "unauthenticated", user: null, error: null, logoutPending: true });
        return;
      }
      // Revocation now confirmed — fall through to the normal bootstrap
      // below, which will correctly find no valid session.
    }

    try {
      const user = await fetchCurrentUser();
      if (id === requestId.current) {
        setState({ status: "authenticated", user, error: null, logoutPending: false });
      }
    } catch (err) {
      if (id !== requestId.current) {
        return;
      }
      // Only an *uncertain* failure (network/timeout) is surfaced as
      // `error` — an ordinary confirmed-invalid session (e.g. no refresh
      // cookie at all, `authentication_failed`) is just "not logged in",
      // not something to offer a "Retry" action for.
      const apiError = err instanceof ApiError && isUncertainSessionError(err) ? err : null;
      setState({ status: "unauthenticated", user: null, error: apiError, logoutPending: false });
    }
  }, []);

  useEffect(() => {
    // A failed refresh discovered anywhere (e.g. mid-session, from a
    // protected call other than /me/) drives the same transition bootstrap
    // uses on an invalid session — one owner for "the session just ended".
    //
    // Only acts when we were actually authenticated: `ensureFreshAccessToken`
    // also fires this on the very first bootstrap's own refresh attempt (no
    // session ever existed yet), and clobbering that in-flight bootstrap's
    // request id here would erase the network-vs-invalid-session
    // classification it's about to commit itself.
    setSessionExpiredHandler(() => {
      setState((prev) => {
        if (prev.status !== "authenticated") {
          return prev;
        }
        requestId.current += 1; // invalidate any in-flight bootstrap/revalidate
        return { status: "unauthenticated", user: null, error: null, logoutPending: false };
      });
    });
    // bootstrap() only calls setState from inside its own `await`
    // continuation (an async network round trip), never synchronously
    // during this effect's body — the standard "subscribe to an external
    // system on mount" pattern the rule's own description calls out as
    // fine; the linter just can't see through the indirection to
    // fetchCurrentUser's await.
    void bootstrap(); // eslint-disable-line react-hooks/set-state-in-effect
    return () => setSessionExpiredHandler(null);
  }, [bootstrap]);

  const login = useCallback(async (credentials: LoginCredentials) => {
    const user = await loginRequest(credentials);
    requestId.current += 1;
    setState({ status: "authenticated", user, error: null, logoutPending: false });
  }, []);

  const logout = useCallback(async () => {
    const result = await logoutRequest();
    requestId.current += 1;
    setState({
      status: "unauthenticated",
      user: null,
      error: null,
      logoutPending: result === "server_unconfirmed",
    });
  }, []);

  const value = useMemo<AuthContextValue>(
    () => ({ ...state, login, logout, revalidate: bootstrap }),
    [state, login, logout, bootstrap],
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthContextValue {
  const ctx = useContext(AuthContext);
  if (!ctx) {
    throw new Error("useAuth() must be used within an <AuthProvider>.");
  }
  return ctx;
}
