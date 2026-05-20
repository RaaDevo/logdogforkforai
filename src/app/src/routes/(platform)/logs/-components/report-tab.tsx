import { AlertTriangleIcon, FileTextIcon, LightbulbIcon, RefreshCwIcon, ShieldAlertIcon } from "lucide-react";
import { useCallback, useEffect, useState } from "react";
import { toast } from "sonner";
import { Alert, AlertDescription, AlertTitle } from "#/components/ui/alert";
import { Badge } from "#/components/ui/badge";
import { Button } from "#/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "#/components/ui/card";
import { Empty, EmptyDescription, EmptyHeader, EmptyMedia, EmptyTitle } from "#/components/ui/empty";
import { Skeleton } from "#/components/ui/skeleton";
import { Spinner } from "#/components/ui/spinner";
import { generateLogReport, getLogReport, type LogInsightReport } from "#/lib/server";

type ReportTabProps = {
  logGroupId: string;
};

export function ReportTab({ logGroupId }: ReportTabProps) {
  const [report, setReport] = useState<LogInsightReport | null>(null);
  const [loadingReport, setLoadingReport] = useState(true);
  const [generating, setGenerating] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const fetchReport = useCallback(async () => {
    setLoadingReport(true);
    setError(null);
    try {
      const data = await getLogReport(logGroupId);
      setReport(data);
    } catch (err) {
      const message = err instanceof Error ? err.message : "Failed to load report.";
      setError(message);
    } finally {
      setLoadingReport(false);
    }
  }, [logGroupId]);

  useEffect(() => {
    void fetchReport();
  }, [fetchReport]);

  const handleGenerate = useCallback(async () => {
    setGenerating(true);
    try {
      const data = await generateLogReport(logGroupId);
      setReport(data);
      toast.success("Report generated.");
    } catch (err) {
      const message = err instanceof Error ? err.message : "Failed to generate report.";
      toast.error(message);
    } finally {
      setGenerating(false);
    }
  }, [logGroupId]);

  const hasReport = report !== null;
  const isLoading = loadingReport;

  const severityColor = getSeverityColor(report?.severity ?? "");
  const citationsById = new Map((report?.citations ?? []).map((citation) => [citation.id, citation]));

  if (isLoading) {
    return (
      <div className={"flex flex-col gap-4"}>
        <Skeleton className={"h-32 w-full rounded-lg"} />
        <Skeleton className={"h-48 w-full rounded-lg"} />
        <Skeleton className={"h-48 w-full rounded-lg"} />
      </div>
    );
  }

  if (error !== null) {
    return (
      <Alert variant={"destructive"}>
        <AlertTitle>Error</AlertTitle>
        <AlertDescription>{error}</AlertDescription>
      </Alert>
    );
  }

  if (!hasReport) {
    return (
      <Empty className={"border"}>
        <EmptyHeader>
          <EmptyMedia variant={"icon"}>
            <FileTextIcon />
          </EmptyMedia>
          <EmptyTitle>No report yet</EmptyTitle>
          <EmptyDescription>
            Generate an AI-powered insight report for this log group to see summary, severity, anomalies, and
            recommendations.
          </EmptyDescription>
        </EmptyHeader>
        <Button disabled={generating} onClick={() => void handleGenerate()} size={"sm"}>
          {generating ? <Spinner className={"size-3"} /> : <FileTextIcon />}
          Generate Report
        </Button>
      </Empty>
    );
  }

  return (
    <div className={"flex flex-col gap-4"}>
      <section className={"grid gap-4 md:grid-cols-2 lg:grid-cols-3"}>
        <Card>
          <CardHeader className={"pb-2"}>
            <CardDescription>Severity</CardDescription>
            <CardTitle>
              <Badge className={severityColor.className} variant={severityColor.variant}>
                {report.severity.toUpperCase()}
              </Badge>
            </CardTitle>
          </CardHeader>
          <CardContent>
            <p className={"text-muted-foreground text-sm"}>{report.summary}</p>
            <SectionSources citationIds={report.summary_citation_ids} citationsById={citationsById} />
          </CardContent>
        </Card>

        <Card>
          <CardHeader className={"pb-2"}>
            <CardDescription>Root Cause Hypothesis</CardDescription>
          </CardHeader>
          <CardContent>
            <p className={"text-sm"}>{report.root_cause_hypothesis}</p>
            <SectionSources citationIds={report.root_cause_hypothesis_citation_ids} citationsById={citationsById} />
          </CardContent>
        </Card>

        <Card>
          <CardHeader className={"pb-2"}>
            <CardDescription>Top Errors</CardDescription>
          </CardHeader>
          <CardContent>
            {report.top_errors.length === 0 ? (
              <p className={"text-muted-foreground text-sm"}>No top errors identified.</p>
            ) : (
              <ul className={"flex list-disc flex-col gap-1 pl-4 text-sm"}>
                {report.top_errors.map((error, index) => (
                  <li key={index}>{error}</li>
                ))}
              </ul>
            )}
            <SectionSources citationIds={report.top_errors_citation_ids} citationsById={citationsById} />
          </CardContent>
        </Card>
      </section>

      <Card>
        <CardHeader>
          <CardTitle className={"flex items-center gap-2 text-base"}>
            <FileTextIcon className={"size-4"} />
            Log Sequence Narrative
          </CardTitle>
        </CardHeader>
        <CardContent>
          <div className={"rounded-md bg-muted/40 p-4 text-sm leading-relaxed"}>{report.log_sequence_narrative}</div>
          <SectionSources citationIds={report.log_sequence_narrative_citation_ids} citationsById={citationsById} />
        </CardContent>
      </Card>

      <section className={"grid gap-4 md:grid-cols-2"}>
        <Card>
          <CardHeader>
            <CardTitle className={"flex items-center gap-2 text-base"}>
              <LightbulbIcon className={"size-4"} />
              Recommendations
            </CardTitle>
          </CardHeader>
          <CardContent>
            {report.recommendations.length === 0 ? (
              <p className={"text-muted-foreground text-sm"}>No recommendations.</p>
            ) : (
              <ul className={"flex list-disc flex-col gap-2 pl-4 text-sm"}>
                {report.recommendations.map((rec, index) => (
                  <li key={index}>{rec}</li>
                ))}
              </ul>
            )}
            <SectionSources citationIds={report.recommendations_citation_ids} citationsById={citationsById} />
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle className={"flex items-center gap-2 text-base"}>
              <AlertTriangleIcon className={"size-4"} />
              Anomalies
            </CardTitle>
          </CardHeader>
          <CardContent>
            {report.anomalies.length === 0 ? (
              <p className={"text-muted-foreground text-sm"}>No anomalies detected.</p>
            ) : (
              <div className={"flex flex-col gap-2"}>
                {report.anomalies.map((anomaly, index) => (
                  <Alert key={index} variant={"default"}>
                    <ShieldAlertIcon className={"size-4"} />
                    <AlertTitle>Anomaly {index + 1}</AlertTitle>
                    <AlertDescription>{anomaly}</AlertDescription>
                  </Alert>
                ))}
              </div>
            )}
            <SectionSources citationIds={report.anomalies_citation_ids} citationsById={citationsById} />
          </CardContent>
        </Card>
      </section>

      <div className={"flex"}>
        <Button disabled={generating} onClick={() => void handleGenerate()} size={"sm"} variant={"outline"}>
          {generating ? <Spinner className={"size-3"} /> : <RefreshCwIcon />}
          {generating ? "Generating..." : "Regenerate Report"}
        </Button>
      </div>
    </div>
  );
}

function SectionSources({
  citationIds,
  citationsById,
}: {
  citationIds: string[];
  citationsById: Map<string, LogInsightReport["citations"][number]>;
}) {
  const sectionCitations = citationIds.map((id) => citationsById.get(id)).filter((citation) => citation !== undefined);
  if (sectionCitations.length === 0) {
    return null;
  }

  return (
    <details className={"mt-3 rounded-md border p-2 text-xs"}>
      <summary className={"cursor-pointer font-medium"}>Sources ({sectionCitations.length})</summary>
      <div className={"mt-2 flex flex-col gap-2"}>
        {sectionCitations.map((citation) => (
          <div className={"rounded border bg-muted/40 p-2"} key={citation.id}>
            <div className={"font-medium"}>{citation.id}</div>
            <div>Table: {citation.source_table}</div>
            <div>File: {citation.source_file ?? "N/A"}</div>
            <div>Rows: {citation.row_range}</div>
            <div>Evidence: {citation.evidence}</div>
          </div>
        ))}
      </div>
    </details>
  );
}

function getSeverityColor(severity: string) {
  const normalized = severity.trim().toLowerCase();
  if (normalized === "critical") {
    return { className: "bg-red-600 text-white hover:bg-red-700", variant: "default" as const };
  }
  if (normalized === "high") {
    return { className: "bg-orange-500 text-white hover:bg-orange-600", variant: "default" as const };
  }
  if (normalized === "medium") {
    return { className: "bg-yellow-500 text-black hover:bg-yellow-600", variant: "default" as const };
  }
  return { className: "", variant: "secondary" as const };
}
