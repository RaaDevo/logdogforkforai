import { format } from "date-fns";
import { AlertCircleIcon, CheckCircle2Icon, ClockIcon, InfoIcon, RotateCcwIcon, Table2Icon } from "lucide-react";
import { useMemo, useState } from "react";
import { Accordion, AccordionContent, AccordionItem, AccordionTrigger } from "#/components/ui/accordion";
import { Alert, AlertDescription, AlertTitle } from "#/components/ui/alert";
import { Badge } from "#/components/ui/badge";
import { Button } from "#/components/ui/button";
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from "#/components/ui/dialog";
import { Empty, EmptyDescription, EmptyHeader, EmptyMedia, EmptyTitle } from "#/components/ui/empty";
import { Progress } from "#/components/ui/progress";
import { ScrollArea } from "#/components/ui/scroll-area";
import { Spinner } from "#/components/ui/spinner";
import type { LogProcess } from "#/lib/server";

type ProcessesTabProps = {
  processes: LogProcess[];
  isLoading: boolean;
  error: string | null;
  onRetryProcess: (process: LogProcess) => Promise<void>;
  onShowTables: (payload: { fileId: string | null; tableIds: string[] }) => void;
  retryingProcessIds: Set<string>;
};

type ProcessInsights = {
  classification: Record<string, unknown> | null;
  result: Record<string, unknown> | null;
  tableDefinitions: Record<string, unknown>[];
  fileClassifications: Record<string, unknown>[];
  tableSummaries: Array<{
    name: string;
    rowCount: number;
    columnCount: number;
    columns: Record<string, unknown>[];
  }>;
  dominantFormat: string | null;
  structuralClass: string | null;
  selectedParserKey: string | null;
  parserKey: string | null;
  classificationConfidence: number | null;
  resultConfidence: number | null;
  overallConfidence: number | null;
  perFileConfidence: Record<string, number | null> | null;
  perTableConfidence: Record<string, number | null> | null;
  totalRowCount: number;
  tableCount: number;
  fileCount: number;
  classificationWarnings: string[];
  resultWarnings: string[];
};

export function ProcessesTab({
  processes,
  isLoading,
  error,
  onRetryProcess,
  onShowTables,
  retryingProcessIds,
}: ProcessesTabProps) {
  const [selectedProcessId, setSelectedProcessId] = useState<string | null>(null);

  const selectedProcess = useMemo(() => {
    if (selectedProcessId === null) {
      return null;
    }

    return processes.find((process) => process.id === selectedProcessId) ?? null;
  }, [processes, selectedProcessId]);

  const isRefreshing = isLoading && processes.length > 0;

  if (isLoading && processes.length === 0) {
    return (
      <div className={"flex items-center justify-center py-12"}>
        <Spinner />
      </div>
    );
  }

  if (error !== null && processes.length === 0) {
    return (
      <Alert variant={"destructive"}>
        <AlertCircleIcon className={"size-4"} />
        <AlertTitle>Failed to load processes</AlertTitle>
        <AlertDescription>{error}</AlertDescription>
      </Alert>
    );
  }

  if (processes.length === 0) {
    return (
      <Empty className={"border"}>
        <EmptyHeader>
          <EmptyMedia variant={"icon"}>
            <ClockIcon />
          </EmptyMedia>
          <EmptyTitle>No processes yet</EmptyTitle>
          <EmptyDescription>Upload log files to start a parsing run.</EmptyDescription>
        </EmptyHeader>
      </Empty>
    );
  }

  return (
    <>
      <div className={"flex flex-col gap-2"}>
        {isRefreshing && (
          <div
            className={
              "flex items-center gap-2 rounded-md border border-dashed px-3 py-2 text-muted-foreground text-xs"
            }
          >
            <Spinner className={"size-3.5"} />
            Refreshing process details...
          </div>
        )}

        {error !== null && processes.length > 0 && (
          <Alert variant={"destructive"}>
            <AlertCircleIcon className={"size-4"} />
            <AlertTitle>Failed to refresh processes</AlertTitle>
            <AlertDescription>{error}</AlertDescription>
          </Alert>
        )}

        {processes.map((process) => (
          <ProcessRow
            key={process.id}
            onRetryProcess={onRetryProcess}
            onShowTables={onShowTables}
            onViewDetails={hasProcessDetails(process) ? () => setSelectedProcessId(process.id) : undefined}
            process={process}
            retrying={retryingProcessIds.has(process.id)}
          />
        ))}
      </div>

      {selectedProcess !== null && (
        <ProcessDetailsDialog onClose={() => setSelectedProcessId(null)} process={selectedProcess} />
      )}
    </>
  );
}

function ProcessRow({
  process,
  onViewDetails,
  onRetryProcess,
  onShowTables,
  retrying,
}: {
  process: LogProcess;
  onViewDetails?: () => void;
  onRetryProcess: (process: LogProcess) => Promise<void>;
  onShowTables: (payload: { fileId: string | null; tableIds: string[] }) => void;
  retrying: boolean;
}) {
  const formattedDate = format(new Date(process.created_at), "MMM d, yyyy 'at' h:mm a");
  const insights = getProcessInsights(process);
  const isInProgress = process.status === "queued" || process.status === "processing";
  const processName = getProcessName(process, insights);
  const warningCount = insights.classificationWarnings.length + insights.resultWarnings.length;

  const getStatusLabel = () => {
    if (process.status === "completed") {
      return "Ingestion successful";
    }
    if (process.status === "failed") {
      return "Ingestion failed";
    }
    if (process.status === "processing") {
      return "Parsing and loading...";
    }
    return "Queued for processing...";
  };

  return (
    <div className={"flex flex-col gap-1.5 rounded-md border p-4"}>
      <div className={"flex items-center gap-3"}>
        <ProcessStatusIcon status={process.status} />
        <div className={"flex flex-1 flex-col gap-0.5"}>
          <span className={"font-medium text-sm"}>{processName}</span>
          <span className={"text-muted-foreground text-xs"}>
            {getStatusLabel()} · {formattedDate}
          </span>
        </div>
        {insights.tableCount > 0 && (
          <Button
            className={"shrink-0"}
            onClick={() => {
              onShowTables({
                fileId: process.file_id,
                tableIds: insights.tableSummaries.map((summary) => summary.name),
              });
            }}
            size={"sm"}
            variant={"ghost"}
          >
            <Table2Icon />
            Tables
            <Badge className={"px-1.5 font-mono text-[10px]"} variant={"secondary"}>
              {insights.tableCount}
            </Badge>
          </Button>
        )}
        {process.status === "failed" && (
          <Button
            className={"shrink-0"}
            disabled={retrying || process.file_id === null}
            onClick={() => {
              void onRetryProcess(process);
            }}
            size={"sm"}
            variant={"ghost"}
          >
            {retrying ? <Spinner className={"size-4"} /> : <RotateCcwIcon />}
            Retry
          </Button>
        )}
        {!isInProgress && onViewDetails !== undefined && (
          <Button className={"shrink-0"} onClick={onViewDetails} size={"sm"} variant={"ghost"}>
            <InfoIcon />
            Details
          </Button>
        )}
      </div>

      {process.status === "completed" && (
        <div className={"flex items-center gap-2 text-muted-foreground text-xs"}>
          <span>{insights.tableCount} table(s) generated</span>
          <span>·</span>
          <span>{insights.totalRowCount.toLocaleString()} row(s) persisted</span>
          <span>·</span>
          <span>{insights.fileCount} file(s) analyzed</span>
          {insights.overallConfidence !== null && (
            <>
              <span>·</span>
              <span>{Math.round(insights.overallConfidence * 100)}% overall confidence</span>
            </>
          )}
          {insights.resultConfidence !== null && (
            <>
              <span>·</span>
              <span>{Math.round(insights.resultConfidence * 100)}% parser confidence</span>
            </>
          )}
        </div>
      )}

      {warningCount > 0 && <div className={"text-muted-foreground text-xs"}>{warningCount} warning(s)</div>}

      {process.status === "failed" && process.error !== null && (
        <p className={"rounded bg-destructive/10 px-2 py-1 font-mono text-destructive text-xs"}>{process.error}</p>
      )}
    </div>
  );
}

function ProcessStatusIcon({ status }: { status: string }) {
  if (status === "completed") {
    return <CheckCircle2Icon className={"size-4 shrink-0 text-green-500"} />;
  }
  if (status === "failed") {
    return <AlertCircleIcon className={"size-4 shrink-0 text-destructive"} />;
  }
  return <Spinner className={"size-4 shrink-0"} />;
}

function ProcessDetailsDialog({ process, onClose }: { process: LogProcess; onClose: () => void }) {
  const insights = getProcessInsights(process);
  const createdAt = new Date(process.created_at);
  const updatedAt = new Date(process.updated_at);
  const formattedDate = format(new Date(process.created_at), "MMM d, yyyy 'at' h:mm a");
  const durationLabel = getDurationLabel(process.status, createdAt, updatedAt);
  const classificationWarningEntries = getWarningEntries("classification", insights.classificationWarnings);
  const resultWarningEntries = getWarningEntries("result", insights.resultWarnings);

  return (
    <Dialog
      onOpenChange={(open) => {
        if (!open) {
          onClose();
        }
      }}
      open
    >
      <DialogContent className={"flex max-h-[85vh] flex-col overflow-hidden sm:max-w-2xl"}>
        <DialogHeader>
          <DialogTitle>Process Details</DialogTitle>
          <DialogDescription>{formattedDate}</DialogDescription>
        </DialogHeader>
        <ScrollArea className={"flex-1"}>
          <div className={"flex flex-col gap-4 py-1 pr-4"}>
            <div className={"rounded-md border"}>
              <div className={"flex flex-col gap-2 p-3"}>
                <span className={"font-medium text-muted-foreground text-xs"}>Process Overview</span>
                <div className={"grid gap-2 text-xs sm:grid-cols-2"}>
                  <DetailPair label={"Process ID"} value={process.id} valueClassName={"font-mono"} />
                  <DetailPair label={"Status"} value={process.status} />
                  <DetailPair label={"Created"} value={format(createdAt, "MMM d, yyyy h:mm:ss a")} />
                  <DetailPair label={"Updated"} value={format(updatedAt, "MMM d, yyyy h:mm:ss a")} />
                  <DetailPair label={"Duration"} value={durationLabel} />
                  <DetailPair
                    label={"Output"}
                    value={`${insights.tableCount} table(s), ${insights.totalRowCount.toLocaleString()} row(s)`}
                  />
                </div>
              </div>
            </div>

            {insights.classification !== null && (
              <div className={"rounded-md border"}>
                <div className={"flex flex-col gap-3 p-3"}>
                  <span className={"font-medium text-muted-foreground text-xs"}>Classification</span>
                  <div className={"flex flex-wrap items-center gap-1.5"}>
                    {insights.dominantFormat !== null && <Badge variant={"secondary"}>{insights.dominantFormat}</Badge>}
                    {insights.structuralClass !== null && <Badge variant={"outline"}>{insights.structuralClass}</Badge>}
                    {insights.selectedParserKey !== null && (
                      <Badge variant={"outline"}>preferred parser: {insights.selectedParserKey}</Badge>
                    )}
                  </div>

                  {insights.classificationConfidence !== null && (
                    <div className={"flex flex-col gap-1.5"}>
                      <div className={"flex items-center justify-between"}>
                        <span className={"font-medium text-muted-foreground text-xs"}>Classification confidence</span>
                        <span className={"font-medium text-xs"}>
                          {Math.round(insights.classificationConfidence * 100)}%
                        </span>
                      </div>
                      <Progress className={"h-1.5"} value={Math.round(insights.classificationConfidence * 100)} />
                    </div>
                  )}

                  {insights.fileClassifications.length > 0 && (
                    <div className={"flex flex-col divide-y rounded-md border"}>
                      {insights.fileClassifications.map((fileClassification) => {
                        const filename = asString(fileClassification.filename, "unknown");
                        const formatName = asString(fileClassification.detected_format, "unknown");
                        const lineCount = asNumber(fileClassification.line_count, 0);
                        const formatConfidence = asFiniteNumber(fileClassification.format_confidence);
                        const key = getFileClassificationKey(fileClassification);
                        const parseConfidence = insights.perFileConfidence?.[asNullableString(fileClassification.file_id) ?? filename];

                        return (
                          <div className={"flex items-center gap-3 px-3 py-2"} key={key}>
                            <span className={"flex-1 truncate font-mono text-xs"}>{filename}</span>
                            <Badge className={"text-xs"} variant={"secondary"}>
                              {formatName}
                            </Badge>
                            <span className={"shrink-0 text-muted-foreground text-xs"}>{lineCount} lines</span>
                            {formatConfidence !== null && (
                              <span className={"shrink-0 text-muted-foreground text-xs"}>
                                {Math.round(formatConfidence * 100)}%
                              </span>
                            )}
                            {typeof parseConfidence === "number" && Number.isFinite(parseConfidence) && (
                              <Badge className={"text-xs"} variant={"outline"}>
                                parse {Math.round(parseConfidence * 100)}%
                              </Badge>
                            )}
                          </div>
                        );
                      })}
                    </div>
                  )}
                </div>
              </div>
            )}

            {insights.result !== null && (
              <div className={"rounded-md border"}>
                <div className={"flex flex-col gap-3 p-3"}>
                  <span className={"font-medium text-muted-foreground text-xs"}>Output Summary</span>

                  <div className={"flex flex-wrap items-center gap-1.5"}>
                    {insights.parserKey !== null && <Badge variant={"outline"}>parser: {insights.parserKey}</Badge>}
                    <Badge variant={"secondary"}>{insights.tableCount} table(s)</Badge>
                    <Badge variant={"secondary"}>{insights.totalRowCount.toLocaleString()} row(s)</Badge>
                    {insights.overallConfidence !== null && (
                      <Badge variant={"outline"}>overall: {Math.round(insights.overallConfidence * 100)}%</Badge>
                    )}
                  </div>

                  {insights.resultConfidence !== null && (
                    <div className={"flex flex-col gap-1.5"}>
                      <div className={"flex items-center justify-between"}>
                        <span className={"font-medium text-muted-foreground text-xs"}>Parser confidence</span>
                        <span className={"font-medium text-xs"}>{Math.round(insights.resultConfidence * 100)}%</span>
                      </div>
                      <Progress className={"h-1.5"} value={Math.round(insights.resultConfidence * 100)} />
                    </div>
                  )}

                  {insights.tableSummaries.length > 0 ? (
                    <div className={"flex flex-col divide-y rounded-md border"}>
                      {insights.tableSummaries.map((tableSummary) => (
                        <div className={"flex items-center gap-3 px-3 py-2"} key={tableSummary.name}>
                          <span className={"flex-1 truncate font-medium font-mono text-xs"}>{tableSummary.name}</span>
                          <Badge className={"text-xs"} variant={"outline"}>
                            {tableSummary.columnCount} column(s)
                          </Badge>
                          <Badge className={"text-xs"} variant={"secondary"}>
                            {tableSummary.rowCount.toLocaleString()} row(s)
                          </Badge>
                          {typeof insights.perTableConfidence?.[tableSummary.name] === "number" && (
                            <Badge className={"text-xs"} variant={"outline"}>
                              conf {Math.round((insights.perTableConfidence?.[tableSummary.name] ?? 0) * 100)}%
                            </Badge>
                          )}
                        </div>
                      ))}
                    </div>
                  ) : (
                    <p className={"text-muted-foreground text-xs"}>No tables were produced in this run.</p>
                  )}

                  {insights.tableSummaries.length > 0 && (
                    <Accordion collapsible type={"single"}>
                      <AccordionItem className={"rounded-md border"} value={"columns-by-table"}>
                        <AccordionTrigger className={"px-3 py-2 text-xs hover:no-underline"}>
                          View columns by table
                        </AccordionTrigger>
                        <AccordionContent>
                          <div className={"flex flex-col divide-y"}>
                            {insights.tableSummaries.map((tableSummary) => (
                              <div className={"flex flex-col gap-1.5 px-3 py-2"} key={`columns-${tableSummary.name}`}>
                                <span className={"font-medium font-mono text-xs"}>{tableSummary.name}</span>
                                <div className={"flex flex-wrap gap-1"}>
                                  {tableSummary.columns.map((column) => (
                                    <Badge
                                      className={"font-mono text-xs"}
                                      key={`${tableSummary.name}-${asString(column.name, "column")}-${asString(column.sql_type, "TEXT")}`}
                                      variant={"outline"}
                                    >
                                      {asString(column.name, "column")}: {asString(column.sql_type, "TEXT")}
                                    </Badge>
                                  ))}
                                </div>
                              </div>
                            ))}
                          </div>
                        </AccordionContent>
                      </AccordionItem>
                    </Accordion>
                  )}
                </div>
              </div>
            )}

            {process.error !== null && (
              <Alert variant={"destructive"}>
                <AlertCircleIcon className={"size-4"} />
                <AlertTitle>Process Error</AlertTitle>
                <AlertDescription className={"flex flex-col gap-1"}>
                  <span className={"font-mono text-xs"}>{process.error}</span>
                </AlertDescription>
              </Alert>
            )}

            {(insights.classificationWarnings.length > 0 || insights.resultWarnings.length > 0) && (
              <Alert variant={"destructive"}>
                <AlertCircleIcon className={"size-4"} />
                <AlertTitle>Diagnostics</AlertTitle>
                <AlertDescription className={"flex flex-col gap-1"}>
                  {classificationWarningEntries.map((entry) => (
                    <span key={entry.key}>classification: {entry.message}</span>
                  ))}
                  {resultWarningEntries.map((entry) => (
                    <span key={entry.key}>parser: {entry.message}</span>
                  ))}
                </AlertDescription>
              </Alert>
            )}

            {process.error === null &&
              insights.classificationWarnings.length === 0 &&
              insights.resultWarnings.length === 0 && (
                <Alert>
                  <InfoIcon className={"size-4"} />
                  <AlertTitle>No diagnostics reported</AlertTitle>
                  <AlertDescription>
                    No parser warnings or processing errors were recorded for this run.
                  </AlertDescription>
                </Alert>
              )}
          </div>
        </ScrollArea>
      </DialogContent>
    </Dialog>
  );
}

function DetailPair({ label, value, valueClassName }: { label: string; value: string; valueClassName?: string }) {
  return (
    <div className={"flex flex-col gap-0.5"}>
      <span className={"text-muted-foreground"}>{label}</span>
      <span className={valueClassName ?? ""}>{value}</span>
    </div>
  );
}

function getProcessInsights(process: LogProcess): ProcessInsights {
  const classification = asRecord(process.classification);
  const result = asRecord(process.result);
  const tableDefinitions = asArrayOfRecords(result?.table_definitions);
  const fileClassifications = asArrayOfRecords(classification?.file_classifications);
  const recordsByTable = asRecord(result?.records);

  const tableSummaries = tableDefinitions.map((tableDefinition) => {
    const tableName = asString(tableDefinition.table_name, "unknown_table");
    const columns = asArrayOfRecords(tableDefinition.columns);
    const rowCount = recordsByTable !== null ? asArray(recordsByTable[tableName]).length : 0;

    return {
      name: tableName,
      rowCount,
      columnCount: columns.length,
      columns,
    };
  });

  const totalRowCount = tableSummaries.reduce((runningTotal, tableSummary) => runningTotal + tableSummary.rowCount, 0);

  return {
    classification,
    result,
    tableDefinitions,
    fileClassifications,
    tableSummaries,
    dominantFormat: asNullableString(classification?.dominant_format),
    structuralClass: asNullableString(classification?.structural_class),
    selectedParserKey: asNullableString(classification?.selected_parser_key),
    parserKey: asNullableString(result?.parser_key),
    classificationConfidence: asFiniteNumber(classification?.confidence),
    resultConfidence: asFiniteNumber(result?.confidence),
    overallConfidence: asFiniteNumber(result?.overall_confidence),
    perFileConfidence: asRecord(result?.per_file_confidence) as Record<string, number | null> | null,
    perTableConfidence: asRecord(result?.per_table_confidence) as Record<string, number | null> | null,
    totalRowCount,
    tableCount: tableDefinitions.length,
    fileCount: fileClassifications.length,
    classificationWarnings: asStringArray(classification?.warnings),
    resultWarnings: asStringArray(result?.warnings),
  };
}

function getFileClassificationKey(fileClassification: Record<string, unknown>) {
  const fileId = asNullableString(fileClassification.file_id);
  if (fileId !== null && fileId !== "") {
    return fileId;
  }

  const filename = asString(fileClassification.filename, "unknown");
  const formatName = asString(fileClassification.detected_format, "unknown");
  const lineCount = asNumber(fileClassification.line_count, 0);
  return `${filename}:${formatName}:${lineCount}`;
}

function getWarningEntries(prefix: string, warnings: string[]) {
  const seen = new Map<string, number>();

  return warnings.map((warning) => {
    const currentCount = (seen.get(warning) ?? 0) + 1;
    seen.set(warning, currentCount);

    return {
      key: `${prefix}:${warning}:${currentCount}`,
      message: warning,
    };
  });
}

function getProcessName(process: LogProcess, insights: ProcessInsights) {
  const filenames = insights.fileClassifications
    .map((classification) => asNullableString(classification.filename))
    .filter((name): name is string => name !== null && name.length > 0);
  const uniqueFilenames = Array.from(new Set(filenames));

  if (uniqueFilenames.length === 1) {
    return uniqueFilenames[0];
  }

  if (uniqueFilenames.length > 1) {
    return `${uniqueFilenames[0]} +${uniqueFilenames.length - 1} more`;
  }

  if (process.file_id !== null) {
    return `file ${process.file_id}`;
  }

  return "batch process";
}

function hasProcessDetails(process: LogProcess) {
  return process.classification !== null || process.result !== null || process.error !== null;
}

function getDurationLabel(status: string, createdAt: Date, updatedAt: Date) {
  if (status === "queued" || status === "processing") {
    return "In progress";
  }

  const milliseconds = updatedAt.getTime() - createdAt.getTime();
  if (!Number.isFinite(milliseconds) || milliseconds <= 0) {
    return "Unavailable";
  }

  const totalSeconds = Math.round(milliseconds / 1000);
  return `${totalSeconds}s`;
}

function asRecord(value: unknown): Record<string, unknown> | null {
  if (value !== null && typeof value === "object" && !Array.isArray(value)) {
    return value as Record<string, unknown>;
  }
  return null;
}

function asArray(value: unknown): unknown[] {
  return Array.isArray(value) ? value : [];
}

function asArrayOfRecords(value: unknown) {
  return asArray(value)
    .map((item) => asRecord(item))
    .filter((item): item is Record<string, unknown> => item !== null);
}

function asString(value: unknown, fallback: string): string {
  return typeof value === "string" ? value : fallback;
}

function asNullableString(value: unknown): string | null {
  return typeof value === "string" ? value : null;
}

function asNumber(value: unknown, fallback: number): number {
  return typeof value === "number" && Number.isFinite(value) ? value : fallback;
}

function asFiniteNumber(value: unknown): number | null {
  return typeof value === "number" && Number.isFinite(value) ? value : null;
}

function asStringArray(value: unknown) {
  return asArray(value).map((item) => String(item));
}
