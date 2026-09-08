import type { components } from "@/types/api";

/** The backend's real current-user shape (accounts/serializers.py MeSerializer) — never hand-duplicated. */
export type CurrentUser = components["schemas"]["Me"];

export type LoginCredentials = components["schemas"]["LoginRequest"];
