import Link from "next/link";

import type { EvaluationRun, EvaluationRunCompareResult } from "@/features/evaluations/types";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";

/**
 * Renders the REAL response of `POST .../evaluations/compare/`
 * (evaluations/services.py `compare_evaluation_runs`) — every number here is
 * a value the backend actually computed and returned in this response, not
 * derived or estimated client-side. No invented "quality score",
 * "confidence", or "% improvement" language: `deltas` are shown exactly as
 * the backend rounds them (candidate metric minus baseline metric), and
 * `regressions`/`passed` are the backend's own threshold verdicts against
 * the candidate run's own `threshold_config` — this panel never computes or
 * relabels either.
 */
const METRIC_LABELS: Record<string, string> = {
  pass_rate: "Pass rate",
  forbidden_tool_violations: "Forbidden tool violations",
  approval_violations: "Approval violations",
  handoff_rate: "Handoff rate",
};

function metricLabel(key: string): string {
  return METRIC_LABELS[key] ?? key;
}

function formatMetric(key: string, value: number): string {
  if (key.endsWith("_rate")) {
    return `${(value * 100).toFixed(1)}%`;
  }
  return String(value);
}

function formatDelta(key: string, value: number): string {
  const sign = value > 0 ? "+" : "";
  if (key.endsWith("_rate")) {
    return `${sign}${(value * 100).toFixed(1)}pp`;
  }
  return `${sign}${value}`;
}

function RunLabel({ run, fallbackId }: { run: EvaluationRun | undefined; fallbackId: string }) {
  if (!run) {
    // The run is on the current page's results, but a race (e.g. it fell off
    // a page during refetch) could leave it briefly unresolved — still show
    // the real id rather than nothing.
    return <span className="font-mono text-xs">{fallbackId.slice(0, 8)}</span>;
  }
  return (
    // Underlined unconditionally, not just on hover: this link sits inline
    // inside a `text-text-secondary` prose sentence (below), so a
    // hover-only underline plus color alone doesn't meet the real axe
    // `link-in-text-block` contrast/distinguishability rule (Phase 23
    // Chunk 4 fix — see "Known defects" below).
    <Link href={`/app/evaluations/${run.id}`} className="text-primary-700 underline">
      Run #{run.id.slice(0, 8)}
    </Link>
  );
}

export function EvaluationRunCompareResultPanel({
  result,
  baselineRun,
  candidateRun,
}: {
  result: EvaluationRunCompareResult;
  baselineRun: EvaluationRun | undefined;
  candidateRun: EvaluationRun | undefined;
}) {
  const metricKeys = Object.keys(result.baseline_metrics);
  const thresholdKeys = Object.keys(result.thresholds);

  return (
    <Card>
      <CardHeader>
        <CardTitle>Comparison result</CardTitle>
      </CardHeader>
      <CardContent className="flex flex-col gap-4">
        <p className="text-text-secondary text-sm">
          Baseline <RunLabel run={baselineRun} fallbackId={result.baseline_run_id} /> vs. candidate{" "}
          <RunLabel run={candidateRun} fallbackId={result.candidate_run_id} /> · {result.case_count}{" "}
          case{result.case_count === 1 ? "" : "s"} in common ·{" "}
          <span className={result.passed ? "text-success-700" : "text-danger-700"}>
            {result.passed ? "Passed" : "Failed"} threshold checks
          </span>
        </p>

        <div className="border-border-subtle overflow-x-auto rounded-lg border">
          <table className="w-full min-w-[560px] text-left text-sm">
            <caption className="sr-only">Per-metric comparison</caption>
            <thead className="bg-surface-2 text-text-secondary text-xs font-medium uppercase">
              <tr>
                <th scope="col" className="px-4 py-2.5">
                  Metric
                </th>
                <th scope="col" className="px-4 py-2.5">
                  Baseline
                </th>
                <th scope="col" className="px-4 py-2.5">
                  Candidate
                </th>
                <th scope="col" className="px-4 py-2.5">
                  Delta
                </th>
              </tr>
            </thead>
            <tbody className="divide-border-subtle divide-y">
              {metricKeys.map((key) => (
                <tr key={key}>
                  <td className="px-4 py-2.5 font-medium">{metricLabel(key)}</td>
                  <td className="text-text-secondary px-4 py-2.5">
                    {formatMetric(key, result.baseline_metrics[key])}
                  </td>
                  <td className="text-text-secondary px-4 py-2.5">
                    {formatMetric(key, result.candidate_metrics[key])}
                  </td>
                  <td className="text-text-secondary px-4 py-2.5">
                    {formatDelta(key, result.deltas[key])}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>

        {thresholdKeys.length > 0 && (
          <div>
            <h3 className="text-text-primary text-sm font-medium">Threshold checks</h3>
            <ul className="mt-1 flex flex-col gap-1">
              {thresholdKeys.map((key) => {
                const threshold = result.thresholds[key];
                return (
                  <li key={key} className="text-text-secondary text-sm">
                    {key}: threshold {String(threshold.threshold)} —{" "}
                    <span className={threshold.passed ? "text-success-700" : "text-danger-700"}>
                      {threshold.passed ? "passed" : "failed"}
                    </span>
                  </li>
                );
              })}
            </ul>
          </div>
        )}

        {result.regressions.length > 0 && (
          <p className="text-danger-700 text-sm">Regressions: {result.regressions.join(", ")}</p>
        )}
        {thresholdKeys.length === 0 && (
          <p className="text-text-secondary text-xs">
            Neither run&apos;s threshold configuration defines any threshold checks — this
            comparison shows raw metrics only.
          </p>
        )}
      </CardContent>
    </Card>
  );
}
