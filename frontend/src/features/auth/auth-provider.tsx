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
import { ApiError, isUncertainSessionError, normalizeTransportError } from "@/lib/api/errors";
import { isLogoutPending } from "@/lib/api/logout-intent";
import { setSessionExpiredHandler } from "@/lib/api/token-store";

/**
 * Four explicit states — not three plus an incidental error field. See
 * README.md, "Session state model", for the full rationale; in short:
 *
 * - "loading": bootstrap/revalidate is in flight; render nothing privileged.
 * - "authenticated": the backend confirmed a valid session.
 * - "unauthenticated": the backend gave a *definitive* verdict of no valid
 *   session (`authentication_failed` from bootstrap/refresh) — safe to
 *   clear all privileged state and route to `/login`.
 * - "uncertain": the session could not be *verified* — network failure,
 *   timeout, or any backend response that isn't a definitive
 *   authentication verdict (see `isUncertainSessionError` in
 *   `lib/api/errors.ts`). This is NEVER treated as logged out: no redirect
 *   to `/login`, no clearing of workspace state as if the account had zero
 *   memberships. It is its own recoverable state with a `revalidate()`
 *   ("Retry") path back to `"authenticated"` or forward to
 *   `"unauthenticated"` once the backend can actually be asked.
 */
export type AuthStatus = "loading" | "authenticated" | "unauthenticated" | "uncertain";

export interface AuthState {
  status: AuthStatus;
  user: CurrentUser | null;
  /**
   * Set only when `status === "uncertain"`, carrying the classified failure
   * (network/timeout/unexpected-response/non-auth backend error) that made
   * verification impossible — a caller rendering the uncertain-state UI can
   * use it for a more specific message, but must never use its mere
   * presence to imply "logged out" (that's what `status` is for). Always
   * `null` for every other status.
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
      // `unwrap()`/`session.ts` always normalize into an ApiError before it
      // gets here — the `instanceof` fallback is defensive, not expected to
      // ever take the `else` branch — but on the off chance it doesn't,
      // "we don't know" (uncertain) is the safe default, never "logged out".
      if (!(err instanceof ApiError) || isUncertainSessionError(err)) {
        const apiError = err instanceof ApiError ? err : normalizeTransportError(err);
        setState({ status: "uncertain", user: null, error: apiError, logoutPending: false });
        return;
      }
      // A *definitive* backend verdict of no valid session (authentication_failed) —
      // safe to treat as confirmed "not logged in".
      setState({ status: "unauthenticated", user: null, error: null, logoutPending: false });
    }
  }, []);

  useEffect(() => {
    // A failed refresh discovered anywhere (e.g. mid-session, from a
    // protected call other than /me/) drives the same authenticated ->
    // uncertain/unauthenticated transition bootstrap's own catch block
    // uses — one owner for "something about the session just changed",
    // classifying the *same* way bootstrap does (see isUncertainSessionError):
    // a definitive authentication_failed clears everything and this is a
    // real logout; anything else (network/timeout/unexpected response) is
    // "uncertain" — privileged content still comes down (this is not
    // "authenticated" anymore, so ProtectedLayout unmounts the shell), but
    // the user is never told they're logged out on the strength of a
    // transport failure. See README.md, "Session state model".
    //
    // Only acts when we were actually authenticated: `ensureFreshAccessToken`
    // also fires this on the very first bootstrap's own refresh attempt (no
    // session ever existed yet), and clobbering that in-flight bootstrap's
    // request id here would erase the classification it's about to commit
    // itself.
    setSessionExpiredHandler((error) => {
      setState((prev) => {
        if (prev.status !== "authenticated") {
          return prev;
        }
        requestId.current += 1; // invalidate any in-flight bootstrap/revalidate
        if (isUncertainSessionError(error)) {
          return { status: "uncertain", user: null, error, logoutPending: false };
        }
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
