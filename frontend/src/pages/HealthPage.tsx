import { useQuery } from "@tanstack/react-query";
import { apiGet } from "@services/api.client";

interface HealthStatus {
  status: string;
  uptime_seconds: number;
  checks?: Record<string, { status: string; error?: string }>;
}

export default function HealthPage() {
  const { data, isLoading, isError, refetch } = useQuery({
    queryKey: ["health"],
    queryFn: () => apiGet<HealthStatus>("/health/ready"),
    refetchInterval: 30_000,
  });

  const status = data?.data;
  const isHealthy = status?.status === "ready";

  return (
    <div className="flex min-h-screen items-center justify-center bg-background p-6">
      <div className="w-full max-w-md space-y-6">
        {/* Header */}
        <div className="space-y-1">
          <h1 className="text-2xl font-bold tracking-tight">System Status</h1>
          <p className="text-sm text-muted-foreground">
            Enterprise AI Banking Platform — Phase 1
          </p>
        </div>

        {/* Status Card */}
        <div className="rounded-lg border bg-card p-6 shadow-sm space-y-4">
          {isLoading && (
            <div className="flex items-center gap-3">
              <div className="h-3 w-3 animate-pulse rounded-full bg-yellow-400" />
              <span className="text-sm text-muted-foreground">Checking systems…</span>
            </div>
          )}

          {isError && (
            <div className="flex items-center gap-3">
              <div className="h-3 w-3 rounded-full bg-red-500" />
              <span className="text-sm text-destructive">Backend unreachable</span>
            </div>
          )}

          {status && (
            <>
              <div className="flex items-center gap-3">
                <div
                  className={`h-3 w-3 rounded-full ${
                    isHealthy ? "bg-green-500" : "bg-red-500"
                  }`}
                />
                <span className="font-medium">
                  {isHealthy ? "All systems operational" : "Systems degraded"}
                </span>
              </div>

              <div className="text-xs text-muted-foreground">
                Uptime: {Math.round(status.uptime_seconds)}s
              </div>

              {status.checks && (
                <div className="space-y-2 pt-2 border-t">
                  {Object.entries(status.checks).map(([name, check]) => (
                    <div key={name} className="flex items-center justify-between text-sm">
                      <span className="capitalize">{name}</span>
                      <span
                        className={
                          check.status === "healthy"
                            ? "text-green-600 dark:text-green-400"
                            : "text-red-600 dark:text-red-400"
                        }
                      >
                        {check.status}
                      </span>
                    </div>
                  ))}
                </div>
              )}
            </>
          )}
        </div>

        <button
          onClick={() => refetch()}
          className="w-full rounded-md bg-primary px-4 py-2 text-sm font-medium text-primary-foreground hover:bg-primary/90 transition-colors"
        >
          Refresh
        </button>
      </div>
    </div>
  );
}
