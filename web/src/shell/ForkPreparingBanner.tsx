import { useEffect } from "react";
import { AlertTriangleIcon, Loader2Icon } from "lucide-react";
import { useQueryClient } from "@tanstack/react-query";
import { Button } from "@/components/ui/button";

export const FORK_PREPARING_LABEL = "omnigent.fork.preparing";
export const FORK_PREPARING_REASON_LABEL = "omnigent.fork.preparing_reason";

export type ForkPreparationState =
  | { status: "ready"; reason: null }
  | { status: "preparing"; reason: null }
  | { status: "failed"; reason: string | null };

type LabelSource = { labels?: Record<string, string> } | null | undefined;

/**
 * Read the server-owned fork preparation state without inferring it from
 * runner liveness. A preparing fork is intentionally still an ordinary route.
 */
export function forkPreparationState(source: LabelSource): ForkPreparationState {
  const labels = source?.labels;
  const state = labels?.[FORK_PREPARING_LABEL];
  if (state === "1") return { status: "preparing", reason: null };
  if (state !== "failed") return { status: "ready", reason: null };

  const reason = labels?.[FORK_PREPARING_REASON_LABEL] ?? labels?.["preparing_reason"] ?? null;
  return { status: "failed", reason: reason?.trim() || null };
}

interface ForkPreparingBannerProps {
  sessionId: string | null;
  state: ForkPreparationState;
}

/**
 * Non-modal status surface for a fork whose copied history is being prepared.
 * The short polling fallback covers deployments that do not emit the
 * compaction event to this browser; the SSE path invalidates the same query.
 */
export function ForkPreparingBanner({ sessionId, state }: ForkPreparingBannerProps) {
  const queryClient = useQueryClient();

  useEffect(() => {
    if (sessionId === null || state.status !== "preparing") return;
    const refresh = () => {
      void queryClient.invalidateQueries({
        queryKey: ["session", sessionId],
        exact: true,
      });
    };
    const timer = window.setInterval(refresh, 1_000);
    return () => window.clearInterval(timer);
  }, [queryClient, sessionId, state.status]);

  if (state.status === "ready") return null;

  if (state.status === "preparing") {
    return (
      <div
        data-testid="fork-preparing-banner"
        role="status"
        aria-live="polite"
        className="mx-auto flex w-full max-w-3xl shrink-0 items-center gap-2 px-4 py-2 text-sm text-muted-foreground"
      >
        <Loader2Icon className="size-4 shrink-0 animate-spin" aria-hidden="true" />
        <span>Preparing fork — summarizing history…</span>
      </div>
    );
  }

  const refresh = () => {
    if (sessionId === null) return;
    void queryClient.invalidateQueries({
      queryKey: ["session", sessionId],
      exact: true,
    });
  };
  return (
    <div
      data-testid="fork-preparing-banner"
      role="alert"
      className="mx-auto flex w-full max-w-3xl shrink-0 items-start gap-3 px-4 py-2 text-sm text-destructive"
    >
      <AlertTriangleIcon className="mt-0.5 size-4 shrink-0" aria-hidden="true" />
      <div className="min-w-0 flex-1">
        <p className="font-medium">Fork preparation failed.</p>
        <p data-testid="fork-preparing-reason">
          {state.reason ?? "The copied history could not be prepared."}
        </p>
        <p className="mt-1 text-muted-foreground">
          Refresh the status or retry cloning from the source session.
        </p>
      </div>
      <Button type="button" variant="outline" size="sm" onClick={refresh}>
        Retry fork preparation
      </Button>
    </div>
  );
}
