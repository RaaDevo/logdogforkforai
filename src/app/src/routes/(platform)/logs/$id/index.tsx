import { createFileRoute, Link } from "@tanstack/react-router";
import { DownloadIcon, FileTextIcon, MoreHorizontalIcon, PencilIcon, Trash2Icon } from "lucide-react";
import { type FormEvent, useCallback, useEffect, useMemo, useState } from "react";
import { toast } from "sonner";
import { z } from "zod";
import { Alert, AlertDescription, AlertTitle } from "#/components/ui/alert";
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from "#/components/ui/alert-dialog";
import { Button } from "#/components/ui/button";
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from "#/components/ui/dialog";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "#/components/ui/dropdown-menu";
import { Field, FieldContent, FieldError, FieldGroup, FieldLabel } from "#/components/ui/field";
import { Input } from "#/components/ui/input";
import { Skeleton } from "#/components/ui/skeleton";
import { Spinner } from "#/components/ui/spinner";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "#/components/ui/tabs";
import {
  createLogProcess,
  deleteLogGroup,
  downloadWorkbookReport,
  getLogGroup,
  type LogFile,
  type LogGroup,
  type LogProcess,
  listLogFiles,
  listLogProcesses,
  updateLogGroup,
} from "#/lib/server";
import { PageHeader } from "#/routes/(platform)/-components/page-header";
import { ChatbotTab } from "#/routes/(platform)/logs/-components/chatbot-tab";
import { ProcessesTab } from "#/routes/(platform)/logs/-components/processes-tab";
import { TablesTab } from "#/routes/(platform)/logs/-components/tables-tab";
import { UploadSection } from "#/routes/(platform)/logs/-components/upload-section";

const logGroupTabs = ["data", "processes", "chat"] as const;
type LogGroupTab = (typeof logGroupTabs)[number];

type TableHighlightRequest = {
  key: number;
  fileId: string | null;
  tableIds: string[];
};

export const Route = createFileRoute("/(platform)/logs/$id/")({
  validateSearch: z
    .object({
      tab: z.enum(logGroupTabs).optional(),
    })
    .catch({}),
  component: LogGroupPage,
});

function LogGroupPage() {
  const { id } = Route.useParams();
  const search = Route.useSearch();
  const navigate = Route.useNavigate();

  const [group, setGroup] = useState<LogGroup | null>(null);
  const [fetchError, setFetchError] = useState<string | null>(null);

  const [processes, setProcesses] = useState<LogProcess[]>([]);
  const [processesLoading, setProcessesLoading] = useState(false);
  const [processesError, setProcessesError] = useState<string | null>(null);

  const [files, setFiles] = useState<LogFile[]>([]);
  const [filesError, setFilesError] = useState<string | null>(null);

  const [activeTab, setActiveTab] = useState<LogGroupTab>(search.tab ?? "data");
  const [tableHighlightRequest, setTableHighlightRequest] = useState<TableHighlightRequest | null>(null);

  const [isRenameDialogOpen, setIsRenameDialogOpen] = useState(false);
  const [isDeleteAlertOpen, setIsDeleteAlertOpen] = useState(false);
  const [isDeleting, setIsDeleting] = useState(false);
  const [renameName, setRenameName] = useState("");
  const [renameError, setRenameError] = useState<string | null>(null);
  const [isRenaming, setIsRenaming] = useState(false);
  const [retryingProcessIds, setRetryingProcessIds] = useState<Set<string>>(new Set());

  const fetchGroup = useCallback(async () => {
    setFetchError(null);
    try {
      const data = await getLogGroup(id);
      setGroup(data);
    } catch (error) {
      const message = error instanceof Error ? error.message : "Failed to load log group.";
      const notFound = message.includes("404") || message.toLowerCase().includes("not found");
      if (notFound) {
        await navigate({ to: "/logs" });
        return;
      }
      setFetchError(message);
    }
  }, [id, navigate]);

  const fetchProcesses = useCallback(async () => {
    setProcessesLoading(true);
    setProcessesError(null);
    try {
      const data = await listLogProcesses(id);
      setProcesses(data);
    } catch (error) {
      setProcessesError(error instanceof Error ? error.message : "Failed to load processes.");
    } finally {
      setProcessesLoading(false);
    }
  }, [id]);

  const fetchFiles = useCallback(async () => {
    setFilesError(null);
    try {
      const data = await listLogFiles(id);
      setFiles(data);
    } catch (error) {
      setFilesError(error instanceof Error ? error.message : "Failed to load files.");
    }
  }, [id]);

  const onUploadSuccess = useCallback(async () => {
    await Promise.all([fetchGroup(), fetchProcesses(), fetchFiles()]);
  }, [fetchGroup, fetchFiles, fetchProcesses]);

  const onRetryProcess = useCallback(
    async (process: LogProcess) => {
      if (process.file_id === null) {
        toast.error("This process cannot be retried because it is not linked to a file.");
        return;
      }

      setRetryingProcessIds((previous) => {
        const next = new Set(previous);
        next.add(process.id);
        return next;
      });

      try {
        const response = await createLogProcess(id, {
          file_ids: [process.file_id],
        });
        if (response.process_ids.length === 0) {
          throw new Error(response.errors[0] ?? "Retry failed.");
        }

        toast.success("Reprocessing queued.");
        await Promise.all([fetchProcesses(), fetchFiles()]);
      } catch (error) {
        const message = error instanceof Error ? error.message : "Failed to retry process.";
        toast.error(message);
      } finally {
        setRetryingProcessIds((previous) => {
          const next = new Set(previous);
          next.delete(process.id);
          return next;
        });
      }
    },
    [fetchFiles, fetchProcesses, id],
  );

  useEffect(() => {
    void fetchGroup();
    void fetchProcesses();
    void fetchFiles();
  }, [fetchGroup, fetchFiles, fetchProcesses]);

  useEffect(() => {
    const nextTab = search.tab ?? "data";
    setActiveTab((previous) => (previous === nextTab ? previous : nextTab));
  }, [search.tab]);

  useEffect(() => {
    if (activeTab !== "processes") {
      return;
    }

    const hasActiveProcesses = processes.some(
      (process) => process.status === "queued" || process.status === "processing",
    );
    if (!hasActiveProcesses) {
      return;
    }

    const interval = setInterval(() => {
      void fetchProcesses();
    }, 3000);

    return () => clearInterval(interval);
  }, [activeTab, processes, fetchProcesses]);

  const openRenameDialog = () => {
    setRenameName(group?.name ?? "");
    setRenameError(null);
    setIsRenameDialogOpen(true);
  };

  const localRenameValidation = useMemo(() => {
    if (!renameName.trim()) {
      return "Name is required.";
    }
    if (renameName.trim().length > 255) {
      return "Name must be 255 characters or less.";
    }
    return null;
  }, [renameName]);

  const onRename = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    setRenameError(null);

    if (localRenameValidation !== null) {
      setRenameError(localRenameValidation);
      return;
    }

    setIsRenaming(true);
    try {
      const updated = await updateLogGroup(id, { name: renameName.trim() });
      setGroup(updated);
      setIsRenameDialogOpen(false);
      toast.success("Log group renamed.");
    } catch (error) {
      const message = error instanceof Error ? error.message : "Failed to rename log group.";
      setRenameError(message);
      toast.error(message);
    } finally {
      setIsRenaming(false);
    }
  };

  const onDelete = async () => {
    setIsDeleting(true);
    setIsDeleteAlertOpen(false);
    const deletingToastId = toast.loading("Deleting log group...");
    try {
      await deleteLogGroup(id);
      toast.success("Log group deleted.", { id: deletingToastId });
      await navigate({ to: "/logs" });
    } catch (error) {
      const message = error instanceof Error ? error.message : "Failed to delete log group.";
      toast.error(message, { id: deletingToastId });
      setFetchError(message);
    } finally {
      setIsDeleting(false);
    }
  };

  const tableNames = useMemo(() => {
    const names = new Set<string>();
    for (const process of processes) {
      const result = process.result;
      if (
        result !== null &&
        typeof result === "object" &&
        Array.isArray((result as Record<string, unknown>).table_definitions)
      ) {
        for (const table of (result as Record<string, unknown>).table_definitions as Array<Record<string, unknown>>) {
          const tableName = table.table_name;
          if (typeof tableName === "string") {
            names.add(tableName);
          }
        }
      }
    }
    return [...names];
  }, [processes]);

  const onTabChange = useCallback(
    (nextTab: string) => {
      if (!logGroupTabs.includes(nextTab as LogGroupTab)) {
        return;
      }

      const normalizedTab = nextTab as LogGroupTab;
      setActiveTab(normalizedTab);
      void navigate({
        replace: true,
        search: (previous) => ({
          ...previous,
          tab: normalizedTab,
        }),
      });
    },
    [navigate],
  );

  const onShowProcessTables = useCallback(
    (payload: { fileId: string | null; tableIds: string[] }) => {
      if (payload.tableIds.length > 0 || payload.fileId !== null) {
        setTableHighlightRequest({
          key: Date.now(),
          fileId: payload.fileId,
          tableIds: payload.tableIds,
        });
      }

      onTabChange("data");
    },
    [onTabChange],
  );

  const onTableHighlightHandled = useCallback(() => {
    setTableHighlightRequest(null);
  }, []);

  return (
    <div className={"flex h-full flex-col"}>
      <PageHeader
        breadcrumbs={
          group
            ? [{ label: "Logs", href: "/logs" }, { label: group.name }]
            : fetchError
              ? [{ label: "Logs", href: "/logs" }]
              : undefined
        }
        loading={group === null && fetchError === null}
      >
        {group !== null && (
          <>
            <Button asChild size={"sm"} variant={"ghost"}>
              <Link params={{ id }} to={"/logs/$id/report"}>
                <FileTextIcon />
                Generate Report
              </Link>
            </Button>
            <Button
              onClick={async () => {
                try {
                  const blob = await downloadWorkbookReport(id);
                  const url = window.URL.createObjectURL(blob);
                  const a = document.createElement("a");
                  a.href = url;
                  a.download = `logdog_workbook.xlsx`;
                  document.body.appendChild(a);
                  a.click();
                  document.body.removeChild(a);
                  window.URL.revokeObjectURL(url);
                } catch (err) {
                  toast.error(err instanceof Error ? err.message : "Download failed.");
                }
              }}
              size={"sm"}
              variant={"ghost"}
            >
              <DownloadIcon />
              Download Workbook
            </Button>
            <DropdownMenu>
              <DropdownMenuTrigger asChild>
                <Button aria-label={"Options"} size={"icon-sm"} variant={"ghost"}>
                  <MoreHorizontalIcon />
                </Button>
              </DropdownMenuTrigger>
              <DropdownMenuContent align={"end"}>
                <DropdownMenuItem onClick={openRenameDialog}>
                  <PencilIcon />
                  Rename
                </DropdownMenuItem>
                <DropdownMenuSeparator />
                <DropdownMenuItem onClick={() => setIsDeleteAlertOpen(true)} variant={"destructive"}>
                  <Trash2Icon />
                  Delete
                </DropdownMenuItem>
              </DropdownMenuContent>
            </DropdownMenu>
          </>
        )}
      </PageHeader>

      <main className={"flex flex-1 flex-col gap-6 overflow-auto"}>
        {group === null && fetchError === null && (
          <div className={"flex flex-col gap-6"}>
            <Skeleton className={"h-28 w-full rounded-lg"} />
            <Skeleton className={"h-48 w-full rounded-lg"} />
          </div>
        )}

        {fetchError !== null && (
          <div className={"flex flex-col items-center gap-4 py-12 text-center"}>
            <p className={"text-destructive text-sm"}>{fetchError}</p>
            <Button onClick={() => void fetchEntry()} size={"sm"} variant={"outline"}>
              Try again
            </Button>
          </div>
        )}

        {group !== null && (
          <Tabs className={"gap-0"} onValueChange={onTabChange} value={activeTab}>
            <TabsList className={"w-full rounded-none border-b bg-sidebar"}>
              <TabsTrigger value={"data"}>Data</TabsTrigger>
              <TabsTrigger value={"processes"}>Processes</TabsTrigger>
              <TabsTrigger value={"chat"}>Chat</TabsTrigger>
            </TabsList>

            <TabsContent className={"flex flex-col gap-6 p-4"} value={"data"}>
              <UploadSection
                logGroupId={id}
                onNavigateToProcesses={() => onTabChange("processes")}
                onUploadSuccess={onUploadSuccess}
              />

              <section className={"flex flex-col gap-3"}>
                <div className={"flex items-center gap-2"}>
                  <h2 className={"font-semibold text-sm"}>Tables</h2>
                </div>
                {filesError !== null && (
                  <Alert variant={"destructive"}>
                    <AlertTitle>Failed to load file metadata</AlertTitle>
                    <AlertDescription>{filesError}</AlertDescription>
                  </Alert>
                )}
                <TablesTab
                  entryId={id}
                  files={files}
                  highlightRequest={tableHighlightRequest}
                  onHighlightHandled={onTableHighlightHandled}
                  processes={processes}
                />
              </section>
            </TabsContent>

            <TabsContent className={"flex flex-col gap-3 p-4"} value={"processes"}>
              <div className={"flex items-center gap-2"}>
                <h2 className={"font-semibold text-sm"}>Processes</h2>
              </div>
              <ProcessesTab
                error={processesError}
                isLoading={processesLoading}
                onRetryProcess={onRetryProcess}
                onShowTables={onShowProcessTables}
                processes={processes}
                retryingProcessIds={retryingProcessIds}
              />
            </TabsContent>

            <TabsContent className={"flex min-h-[calc(100svh-10rem)] flex-col gap-3 p-4"} value={"chat"}>
              <ChatbotTab entryId={id} groupName={group?.name ?? "this log group"} tableNames={tableNames} />
            </TabsContent>
          </Tabs>
        )}
      </main>

      <Dialog onOpenChange={setIsRenameDialogOpen} open={isRenameDialogOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Rename Log Group</DialogTitle>
            <DialogDescription>Enter a new name for this log group.</DialogDescription>
          </DialogHeader>

          <form className={"flex flex-col gap-4"} onSubmit={onRename}>
            <FieldGroup>
              <Field>
                <FieldLabel htmlFor={"rename-log-group"}>Name</FieldLabel>
                <FieldContent>
                  <Input
                    autoComplete={"off"}
                    id={"rename-log-group"}
                    onChange={(event) => setRenameName(event.target.value)}
                    placeholder={"e.g. Production API Logs"}
                    value={renameName}
                  />
                </FieldContent>
              </Field>

              {renameError !== null && <FieldError>{renameError}</FieldError>}

              <div className={"flex justify-end gap-2"}>
                <Button onClick={() => setIsRenameDialogOpen(false)} type={"button"} variant={"outline"}>
                  Cancel
                </Button>
                <Button disabled={isRenaming} type={"submit"}>
                  {isRenaming ? <Spinner /> : "Rename"}
                </Button>
              </div>
            </FieldGroup>
          </form>
        </DialogContent>
      </Dialog>

      <AlertDialog onOpenChange={setIsDeleteAlertOpen} open={isDeleteAlertOpen}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>Delete log group?</AlertDialogTitle>
            <AlertDialogDescription>
              This will permanently delete <strong className={"text-foreground"}>{group?.name}</strong> and all
              associated data. This action cannot be undone.
            </AlertDialogDescription>
          </AlertDialogHeader>

          <AlertDialogFooter>
            <AlertDialogCancel disabled={isDeleting}>Cancel</AlertDialogCancel>
            <AlertDialogAction disabled={isDeleting} onClick={() => void onDelete()} variant={"destructive"}>
              {isDeleting ? <Spinner /> : "Delete"}
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </div>
  );
}
