"use client";

import Link from "next/link";
import { useRef, useState } from "react";
import type { ChangeEvent, FormEvent } from "react";

import { useKnowledgeSearchQuery, useKnowledgeSourceFilterOptionsQuery } from "@/features/knowledge/queries";
import type { KnowledgeSearchHit, KnowledgeSearchRequestInput } from "@/features/knowledge/types";
import {
  KNOWLEDGE_SEARCH_DEFAULT_TOP_K,
  KNOWLEDGE_SEARCH_MAX_QUERY_LENGTH,
} from "@/features/knowledge/types";
import { StructuredPayload } from "@/components/support/structured-payload";
import { Alert } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Skeleton } from "@/components/ui/skeleton";

/** Real, backend-bounded choices only (`KNOWLEDGE_DEFAULT_TOP_K`/`KNOWLEDGE_MAX_TOP_K` = 5/20) — never an arbitrary huge request (master prompt Part F §29). */
const TOP_K_OPTIONS: readonly number[] = [3, 5, 10, 20];

/**
 * Retrieved chunk text is untrusted content (master prompt Part D §19-21):
 * it may contain HTML-looking, script-looking, or prompt-injection-looking
 * text, long strings, or customer data. Rendered as a plain text node inside
 * a bounded, internally-scrolling box — never `dangerouslySetInnerHTML`,
 * raw Markdown-to-HTML, `eval`, or `new Function`. Chunks are already capped
 * server-side (~1200 chars, `KNOWLEDGE_CHUNK_SIZE`) — the hard slice below
 * is a defensive last resort, not the primary size control (same posture as
 * `StructuredPayload`).
 */
const MAX_DISPLAYED_CHUNK_CHARS = 4000;

function ChunkText({ text }: { text: string }) {
  const truncated = text.length > MAX_DISPLAYED_CHUNK_CHARS;
  const displayed = truncated ? text.slice(0, MAX_DISPLAYED_CHUNK_CHARS) : text;
  return (
    <p className="bg-surface-2 border-border-subtle max-h-40 overflow-y-auto rounded-md border p-2 text-sm break-words whitespace-pre-wrap">
      {displayed}
      {truncated && "… (truncated)"}
    </p>
  );
}

function ResultRow({ hit }: { hit: KnowledgeSearchHit }) {
  return (
    <li className="border-border-subtle rounded-lg border p-4">
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <div>
          <span className="text-text-muted mr-2 text-xs font-medium uppercase">
            Rank {hit.rank}
          </span>
          <Link
            href={`/app/knowledge/${hit.document_id}`}
            className="text-primary-700 font-medium hover:underline focus-visible:underline"
          >
            {hit.document_title}
          </Link>
        </div>
        {/*
          `hit.score` is cosine similarity (`score = 1 - cosine_distance`,
          knowledge/retrieval/services.py `search_knowledge`) — higher is
          more similar. Never converted to a percentage, never labeled
          "confidence": neither is what the backend's math actually
          computes (master prompt Part B §7-9).
        */}
        <span className="text-text-secondary text-sm">Similarity {hit.score.toFixed(2)}</span>
      </div>
      {/*
        `hit.source_id` is real, but there is no Source detail page in this
        app (Chunk 1 decision, unchanged) — shown as plain text, never a
        dead link (master prompt Part D §22).
      */}
      <p className="text-text-secondary mt-1 text-xs">Source: {hit.source_name}</p>
      <div className="mt-2">
        <ChunkText text={hit.text} />
      </div>
      <div className="mt-2">
        <StructuredPayload value={hit.citation} label="View citation" defaultOpen={false} />
      </div>
    </li>
  );
}

function SearchResultsSkeleton() {
  return (
    <div className="flex flex-col gap-2" role="status" aria-label="Searching">
      {Array.from({ length: 3 }).map((_, index) => (
        <Skeleton key={index} className="h-24 w-full" />
      ))}
      <span className="sr-only">Searching</span>
    </div>
  );
}

/**
 * Real-time retrieval preview (Phase 21 Chunk 3): an operator's window into
 * "what chunks would the RAG system retrieve for this query?" — never a
 * chatbot, answer generator, or prompt playground (master prompt Part C
 * §13). Visible to every active workspace member, not gated behind
 * `canManageKnowledge`: the real endpoint (`KnowledgeSearchView`) requires
 * only workspace membership, same as the read-only Documents/Sources tabs
 * (master prompt Part I §52).
 */
export function KnowledgeSearchPanel({ workspaceId }: { workspaceId: string }) {
  const [queryDraft, setQueryDraft] = useState("");
  const [topKDraft, setTopKDraft] = useState(KNOWLEDGE_SEARCH_DEFAULT_TOP_K);
  const [sourceIdDraft, setSourceIdDraft] = useState("");
  // See queries.ts `useKnowledgeSearchQuery`'s doc comment: a ref, not
  // state, so `queryFn` always reads the just-submitted request rather than
  // a stale closure from an earlier render.
  const requestRef = useRef<KnowledgeSearchRequestInput | null>(null);
  const query = useKnowledgeSearchQuery(workspaceId, requestRef);
  const sourcesQuery = useKnowledgeSourceFilterOptionsQuery(workspaceId);
  // Only active sources are offered — searching by an inactive source would
  // always return zero results (the retrieval query excludes
  // `document__source__is_active=False` chunks unconditionally), so this
  // mirrors the upload form's same "never offer a doomed choice" pattern
  // rather than duplicating a second sources fetch (master prompt Part G §30).
  const activeSources = sourcesQuery.data?.results.filter((source) => source.is_active) ?? [];

  const trimmedQuery = queryDraft.trim();
  const canSubmit = trimmedQuery.length > 0 && !query.isFetching;

  function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!canSubmit) {
      return;
    }
    requestRef.current = {
      query: trimmedQuery,
      topK: topKDraft,
      sourceId: sourceIdDraft || undefined,
    };
    void query.refetch();
  }

  function handleTopKChange(event: ChangeEvent<HTMLSelectElement>) {
    setTopKDraft(Number(event.target.value));
  }

  const hasSearched = query.data !== undefined || query.isError;

  return (
    <div className="flex flex-col gap-6">
      <form
        onSubmit={handleSubmit}
        className="border-border-subtle flex flex-col gap-3 rounded-lg border p-4"
        aria-label="Search knowledge"
      >
        <div>
          <Label htmlFor="knowledge-search-query">Query</Label>
          <Input
            id="knowledge-search-query"
            type="search"
            value={queryDraft}
            onChange={(event) => setQueryDraft(event.target.value)}
            maxLength={KNOWLEDGE_SEARCH_MAX_QUERY_LENGTH}
            placeholder="What would a customer ask?"
            disabled={query.isFetching}
          />
          <p className="text-text-muted mt-1 text-xs">
            Previews the chunks this workspace&apos;s retrieval layer would surface for this
            query. This does not generate an answer.
          </p>
        </div>

        <div className="flex flex-col gap-3 sm:flex-row sm:flex-wrap sm:items-end">
          <div className="w-full sm:w-40">
            <Label htmlFor="knowledge-search-top-k">Results</Label>
            <select
              id="knowledge-search-top-k"
              value={topKDraft}
              onChange={handleTopKChange}
              disabled={query.isFetching}
              className="bg-surface-0 text-text-primary border-border-default focus-visible:outline-primary-500 h-9 w-full rounded-md border px-3 text-sm outline-none"
            >
              {TOP_K_OPTIONS.map((option) => (
                <option key={option} value={option}>
                  {option}
                </option>
              ))}
            </select>
          </div>
          <div className="w-full sm:w-64">
            <Label htmlFor="knowledge-search-source">Source</Label>
            <select
              id="knowledge-search-source"
              value={sourceIdDraft}
              onChange={(event) => setSourceIdDraft(event.target.value)}
              disabled={query.isFetching}
              className="bg-surface-0 text-text-primary border-border-default focus-visible:outline-primary-500 h-9 w-full rounded-md border px-3 text-sm outline-none"
            >
              <option value="">All sources</option>
              {activeSources.map((source) => (
                <option key={source.id} value={source.id}>
                  {source.name}
                </option>
              ))}
            </select>
          </div>
          <div>
            <Button type="submit" disabled={!canSubmit} isLoading={query.isFetching}>
              Search
            </Button>
          </div>
        </div>
      </form>

      <section aria-label="Search results" className="flex flex-col gap-3">
        {query.isFetching && <SearchResultsSkeleton />}

        {!query.isFetching && query.isError && (
          <Alert variant="danger" title="This search couldn't be completed">
            {query.error.message}
          </Alert>
        )}

        {!query.isFetching && query.isSuccess && query.data.results.length === 0 && (
          <div className="border-border-subtle rounded-lg border border-dashed py-16 text-center">
            <p className="text-text-primary text-sm font-medium">No results</p>
            <p className="text-text-secondary mt-1 text-sm">
              No ready, active chunks matched this query{sourceIdDraft ? " in that source" : ""}.
            </p>
          </div>
        )}

        {!query.isFetching && query.isSuccess && query.data.results.length > 0 && (
          <ol className="flex flex-col gap-3">
            {query.data.results.map((hit) => (
              <ResultRow key={hit.chunk_id} hit={hit} />
            ))}
          </ol>
        )}

        {!hasSearched && !query.isFetching && (
          <p className="text-text-secondary text-sm">Enter a query and press Search.</p>
        )}
      </section>
    </div>
  );
}
