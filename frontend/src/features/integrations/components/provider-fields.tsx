"use client";

import type {
  DemoCommerceConfigurationInput,
  EmailConfigurationInput,
  GoogleCalendarConfigurationInput,
  IntegrationProviderValue,
  ProviderConfigurationInput,
  ProviderCredentialsInput,
  SmtpCredentialsInput,
  StripeCredentialsInput,
} from "@/features/integrations/types";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";

/**
 * Provider-specific credential/configuration fields, built directly from
 * the real backend schemas (backend/integrations/schemas.py — see
 * types.ts's doc comment). Master prompt Part C §8: never a free-form
 * secret-JSON editor invented merely because the storage column is a
 * `JSONField` — every scalar field here (`secret_key`, `host`, `port`,
 * `username`, `password`, `use_tls`, `calendar_id`, `from_email`) mirrors a
 * real, named `pydantic` field. The two JSON textareas
 * (`service_account_info`, the demo commerce catalog) are the exception
 * that proves the rule: both are genuinely unbounded/nested `dict`/
 * `dict[str, Any]` shapes in the real schema itself, not an escape hatch
 * around a stable field set.
 */

const JSON_TEXTAREA_CLASS =
  "bg-surface-0 text-text-primary placeholder:text-text-muted border-border-default focus-visible:outline-primary-500 mt-1 w-full rounded-md border px-3 py-2 font-mono text-xs outline-none";

function JsonTextarea({
  id,
  value,
  onChange,
  rows = 5,
  placeholder,
}: {
  id: string;
  value: string;
  onChange: (raw: string) => void;
  rows?: number;
  placeholder?: string;
}) {
  return (
    <textarea
      id={id}
      value={value}
      onChange={(event) => onChange(event.target.value)}
      rows={rows}
      spellCheck={false}
      placeholder={placeholder}
      className={JSON_TEXTAREA_CLASS}
    />
  );
}

// --- Credentials -------------------------------------------------------

export interface CredentialsFieldsProps {
  provider: IntegrationProviderValue;
  /** Raw, uncommitted field state — parsed/validated only at submit time by the caller (`parseCredentialsInput`). */
  value: Record<string, string>;
  onChange: (next: Record<string, string>) => void;
  disabled?: boolean;
  idPrefix: string;
}

/** Never prepopulated with a real value (master prompt Part C §9) — every field here always starts blank, including on the rotate form, which never round-trips the existing secret. */
export function ProviderCredentialsFields({
  provider,
  value,
  onChange,
  disabled,
  idPrefix,
}: CredentialsFieldsProps) {
  function set(field: string, fieldValue: string) {
    onChange({ ...value, [field]: fieldValue });
  }

  if (provider === "stripe") {
    return (
      <div>
        <Label htmlFor={`${idPrefix}-secret-key`}>Secret key</Label>
        <Input
          id={`${idPrefix}-secret-key`}
          type="password"
          autoComplete="off"
          value={value.secret_key ?? ""}
          onChange={(event) => set("secret_key", event.target.value)}
          disabled={disabled}
          minLength={8}
          maxLength={500}
          required
        />
      </div>
    );
  }

  if (provider === "google_calendar") {
    return (
      <div>
        <Label htmlFor={`${idPrefix}-service-account-info`}>Service account JSON key</Label>
        <p className="text-text-secondary text-xs">
          The full JSON key file content for a Google service account with calendar access.
        </p>
        <JsonTextarea
          id={`${idPrefix}-service-account-info`}
          value={value.service_account_info ?? ""}
          onChange={(raw) => set("service_account_info", raw)}
          placeholder='{ "type": "service_account", "project_id": "...", ... }'
        />
      </div>
    );
  }

  if (provider === "email") {
    return (
      <div className="flex flex-col gap-3">
        <div>
          <Label htmlFor={`${idPrefix}-host`}>SMTP host</Label>
          <Input
            id={`${idPrefix}-host`}
            value={value.host ?? ""}
            onChange={(event) => set("host", event.target.value)}
            disabled={disabled}
            required
          />
        </div>
        <div>
          <Label htmlFor={`${idPrefix}-port`}>Port</Label>
          <Input
            id={`${idPrefix}-port`}
            type="number"
            min={1}
            max={65535}
            value={value.port ?? ""}
            onChange={(event) => set("port", event.target.value)}
            disabled={disabled}
            placeholder="587"
          />
        </div>
        <div>
          <Label htmlFor={`${idPrefix}-username`}>Username</Label>
          <Input
            id={`${idPrefix}-username`}
            autoComplete="off"
            value={value.username ?? ""}
            onChange={(event) => set("username", event.target.value)}
            disabled={disabled}
            required
          />
        </div>
        <div>
          <Label htmlFor={`${idPrefix}-password`}>Password</Label>
          <Input
            id={`${idPrefix}-password`}
            type="password"
            autoComplete="off"
            value={value.password ?? ""}
            onChange={(event) => set("password", event.target.value)}
            disabled={disabled}
            required
          />
        </div>
        <div className="flex items-center gap-2">
          <input
            id={`${idPrefix}-use-tls`}
            type="checkbox"
            checked={value.use_tls !== "false"}
            onChange={(event) => set("use_tls", event.target.checked ? "true" : "false")}
            disabled={disabled}
            className="h-4 w-4"
          />
          <Label htmlFor={`${idPrefix}-use-tls`} className="mb-0">
            Use TLS
          </Label>
        </div>
      </div>
    );
  }

  // demo_commerce: no credential fields at all — the real schema
  // (`DemoCommerceCredentials`) accepts an empty object.
  return (
    <p className="text-text-secondary text-sm">
      The demo commerce provider has no credentials to configure.
    </p>
  );
}

export interface CredentialsParseResult {
  ok: boolean;
  credentials: ProviderCredentialsInput;
  error: string | null;
}

/** Parses this form's raw string state into the real typed shape `integrations/schemas.py` expects — never sent to the backend unparsed. A malformed JSON textarea is caught here, client-side, before submit. */
export function parseCredentialsInput(
  provider: IntegrationProviderValue,
  value: Record<string, string>,
): CredentialsParseResult {
  if (provider === "stripe") {
    const secretKey = (value.secret_key ?? "").trim();
    if (secretKey.length < 8) {
      return { ok: false, credentials: {} as StripeCredentialsInput, error: "Secret key must be at least 8 characters." };
    }
    return { ok: true, credentials: { secret_key: secretKey }, error: null };
  }

  if (provider === "google_calendar") {
    const raw = (value.service_account_info ?? "").trim();
    try {
      const parsed = JSON.parse(raw) as unknown;
      if (typeof parsed !== "object" || parsed === null || Array.isArray(parsed)) {
        throw new Error("not an object");
      }
      return {
        ok: true,
        credentials: { service_account_info: parsed as Record<string, unknown> },
        error: null,
      };
    } catch {
      return {
        ok: false,
        credentials: { service_account_info: {} },
        error: "Service account key must be valid JSON.",
      };
    }
  }

  if (provider === "email") {
    const host = (value.host ?? "").trim();
    const username = (value.username ?? "").trim();
    const password = value.password ?? "";
    if (!host || !username || !password) {
      return {
        ok: false,
        credentials: {} as SmtpCredentialsInput,
        error: "Host, username, and password are required.",
      };
    }
    const port = value.port ? Number(value.port) : undefined;
    if (port !== undefined && (!Number.isInteger(port) || port < 1 || port > 65535)) {
      return { ok: false, credentials: {} as SmtpCredentialsInput, error: "Port must be between 1 and 65535." };
    }
    return {
      ok: true,
      credentials: { host, username, password, port, use_tls: value.use_tls !== "false" },
      error: null,
    };
  }

  return { ok: true, credentials: {}, error: null };
}

// --- Configuration -------------------------------------------------------

export interface ConfigurationFieldsProps {
  provider: IntegrationProviderValue;
  value: Record<string, string>;
  onChange: (next: Record<string, string>) => void;
  disabled?: boolean;
  idPrefix: string;
}

export function ProviderConfigurationFields({
  provider,
  value,
  onChange,
  disabled,
  idPrefix,
}: ConfigurationFieldsProps) {
  function set(field: string, fieldValue: string) {
    onChange({ ...value, [field]: fieldValue });
  }

  if (provider === "google_calendar") {
    return (
      <div>
        <Label htmlFor={`${idPrefix}-calendar-id`}>Calendar ID</Label>
        <Input
          id={`${idPrefix}-calendar-id`}
          value={value.calendar_id ?? ""}
          onChange={(event) => set("calendar_id", event.target.value)}
          disabled={disabled}
          placeholder="primary"
        />
      </div>
    );
  }

  if (provider === "email") {
    return (
      <div>
        <Label htmlFor={`${idPrefix}-from-email`}>From address</Label>
        <Input
          id={`${idPrefix}-from-email`}
          type="email"
          value={value.from_email ?? ""}
          onChange={(event) => set("from_email", event.target.value)}
          disabled={disabled}
          required
        />
      </div>
    );
  }

  if (provider === "demo_commerce") {
    return (
      <div className="flex flex-col gap-3">
        <div>
          <Label htmlFor={`${idPrefix}-orders`}>Demo orders catalog (JSON)</Label>
          <JsonTextarea
            id={`${idPrefix}-orders`}
            value={value.orders ?? "{}"}
            onChange={(raw) => set("orders", raw)}
          />
        </div>
        <div>
          <Label htmlFor={`${idPrefix}-shipments`}>Demo shipments catalog (JSON)</Label>
          <JsonTextarea
            id={`${idPrefix}-shipments`}
            value={value.shipments ?? "{}"}
            onChange={(raw) => set("shipments", raw)}
          />
        </div>
      </div>
    );
  }

  return <p className="text-text-secondary text-sm">Stripe has no configuration fields.</p>;
}

export interface ConfigurationParseResult {
  ok: boolean;
  configuration: ProviderConfigurationInput;
  error: string | null;
}

export function parseConfigurationInput(
  provider: IntegrationProviderValue,
  value: Record<string, string>,
): ConfigurationParseResult {
  if (provider === "google_calendar") {
    const calendarId = (value.calendar_id ?? "").trim();
    const configuration: GoogleCalendarConfigurationInput = calendarId
      ? { calendar_id: calendarId }
      : {};
    return { ok: true, configuration, error: null };
  }

  if (provider === "email") {
    const fromEmail = (value.from_email ?? "").trim();
    if (!fromEmail) {
      return { ok: false, configuration: {} as EmailConfigurationInput, error: "A from address is required." };
    }
    return { ok: true, configuration: { from_email: fromEmail }, error: null };
  }

  if (provider === "demo_commerce") {
    try {
      const orders = JSON.parse(value.orders ?? "{}") as unknown;
      const shipments = JSON.parse(value.shipments ?? "{}") as unknown;
      if (typeof orders !== "object" || orders === null || Array.isArray(orders)) {
        throw new Error("orders must be an object");
      }
      if (typeof shipments !== "object" || shipments === null || Array.isArray(shipments)) {
        throw new Error("shipments must be an object");
      }
      const configuration: DemoCommerceConfigurationInput = {
        orders: orders as Record<string, unknown>,
        shipments: shipments as Record<string, unknown>,
      };
      return { ok: true, configuration, error: null };
    } catch {
      return {
        ok: false,
        configuration: { orders: {}, shipments: {} },
        error: "Orders/shipments catalogs must be valid JSON objects.",
      };
    }
  }

  return { ok: true, configuration: {}, error: null };
}
