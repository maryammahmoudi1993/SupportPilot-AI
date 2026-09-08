import fs from "node:fs";

import type { Page } from "@playwright/test";

import { DATA_FILE } from "./global-setup";

export interface E2EData {
  primaryEmail: string;
  primaryPassword: string;
  zeroEmail: string;
  zeroPassword: string;
  workspaceAId: string;
  workspaceAName: string;
  workspaceBId: string;
  workspaceBName: string;
  /** The workspace `/auth/me/` lists first (most-recently-created membership — see global-setup.ts). */
  defaultWorkspaceName: string;
  defaultWorkspaceId: string;
  /** The other real, accessible workspace — for switch/stale-preference tests. */
  otherWorkspaceName: string;
  otherWorkspaceId: string;
}

let cached: E2EData | null = null;

/** Reads the synthetic backend data `global-setup.ts` created. */
export function e2eData(): E2EData {
  if (!cached) {
    cached = JSON.parse(fs.readFileSync(DATA_FILE, "utf-8")) as E2EData;
  }
  return cached;
}

/** Drives the real login form — every test that needs an authenticated session does a real UI login. */
export async function login(page: Page, email: string, password: string): Promise<void> {
  await page.goto("/login");
  await page.getByLabel("Email").fill(email);
  await page.getByLabel("Password").fill(password);
  await page.getByRole("button", { name: "Sign in" }).click();
  await page.waitForURL("**/app");
}

/** The login form's own error alert, not Next.js's route-announcer element (also `role="alert"`). */
export function formAlert(page: Page) {
  return page.locator("main").getByRole("alert");
}
