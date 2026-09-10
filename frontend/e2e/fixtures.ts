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
  workspaceACustomerId: string;
  workspaceACustomerName: string;
  workspaceBCustomerId: string;
  workspaceBCustomerName: string;
  workspaceBConversationId: string;
  workspaceBConversationSubject: string;
  workspaceBUnassignedConversationId: string;
  workspaceBUnassignedConversationSubject: string;
  workspaceAConversationId: string;
  workspaceAConversationSubject: string;
  workspaceBTicketId: string;
  workspaceBTicketSubject: string;
  workspaceBResolvedTicketId: string;
  workspaceBResolvedTicketSubject: string;
  workspaceATicketId: string;
  workspaceATicketSubject: string;
  workspaceBAgentRunSucceededId: string;
  workspaceBAgentRunRunningId: string;
  workspaceAAgentRunId: string;
  workspaceAAgentRunResponse: string;
  workspaceBToolExecutionSucceededId: string;
  workspaceBToolExecutionFailedId: string;
  workspaceBToolExecutionWaitingId: string;
  workspaceAApprovalApproveId: string;
  workspaceAApprovalRejectId: string;
  workspaceAApprovalConcurrentId: string;
  workspaceAApprovalExpiredId: string;
  workspaceAApprovalDecidedId: string;
  workspaceBApprovalPendingId: string;
  workspaceAApprovalKeyboardId: string;
  workspaceAApprovalMobileId: string;
  workspaceBHandoffPendingId: string;
  workspaceBHandoffResolvedId: string;
  workspaceAHandoffPendingId: string;
  workspaceBKnowledgeSourceId: string;
  workspaceBKnowledgeSourceName: string;
  workspaceBKnowledgeDocumentReadyId: string;
  workspaceBKnowledgeDocumentFailedId: string;
  workspaceAKnowledgeDocumentId: string;
  workspaceAKnowledgeSourceId: string;
  workspaceAKnowledgeDocumentFailedId: string;
  workspaceAKnowledgeDocumentProcessingId: string;
  workspaceARetrievalSourceId: string;
  workspaceARetrievalDocumentId: string;
  workspaceBIntegrationStripeId: string;
  workspaceBIntegrationEmailId: string;
  workspaceAIntegrationCalendarId: string;
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
