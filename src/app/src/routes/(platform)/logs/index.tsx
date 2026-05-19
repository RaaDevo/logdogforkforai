import { createFileRoute, Link, useNavigate } from "@tanstack/react-router";
import { ChevronRightIcon, PlusIcon, ScrollTextIcon } from "lucide-react";
import { type FormEvent, useCallback, useEffect, useMemo, useState } from "react";
import { toast } from "sonner";
import { Button } from "#/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "#/components/ui/dialog";
import { Empty, EmptyDescription, EmptyHeader, EmptyMedia, EmptyTitle } from "#/components/ui/empty";
import { Field, FieldContent, FieldError, FieldGroup, FieldLabel } from "#/components/ui/field";
import { Input } from "#/components/ui/input";
import { Skeleton } from "#/components/ui/skeleton";
import { Spinner } from "#/components/ui/spinner";
import { createLogGroup, type LogGroup, listLogGroups } from "#/lib/server";
import { PageHeader } from "#/routes/(platform)/-components/page-header";

export const Route = createFileRoute("/(platform)/logs/")({
  component: LogsPage,
});

function LogsPage() {
  const navigate = useNavigate();
  const [groups, setGroups] = useState<LogGroup[] | null>(null);
  const [fetchError, setFetchError] = useState<string | null>(null);
  const [isDialogOpen, setIsDialogOpen] = useState(false);
  const [name, setName] = useState("");
  const [createError, setCreateError] = useState<string | null>(null);
  const [isSubmitting, setIsSubmitting] = useState(false);

  const fetchGroups = useCallback(async () => {
    setFetchError(null);
    try {
      const data = await listLogGroups();
      setGroups(data);
    } catch (error) {
      setFetchError(error instanceof Error ? error.message : "Failed to load log groups.");
    }
  }, []);

  useEffect(() => {
    void fetchGroups();
  }, [fetchGroups]);

  const localValidationError = useMemo(() => {
    if (!name.trim()) {
      return "Name is required.";
    }
    if (name.trim().length > 255) {
      return "Name must be 255 characters or less.";
    }
    return null;
  }, [name]);

  const onSubmit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    setCreateError(null);

    if (localValidationError !== null) {
      setCreateError(localValidationError);
      return;
    }

    setIsSubmitting(true);
    try {
      const created = await createLogGroup({ name: name.trim() });
      setName("");
      setIsDialogOpen(false);
      toast.success("Log group created.");
      await navigate({ to: "/logs/$id", params: { id: created.id } });
    } catch (error) {
      const message = error instanceof Error ? error.message : "Failed to create log group.";
      setCreateError(message);
      toast.error(message);
    } finally {
      setIsSubmitting(false);
    }
  };

  const closeDialog = () => {
    setIsDialogOpen(false);
    setName("");
    setCreateError(null);
  };

  return (
    <div className={"flex h-full flex-col"}>
      <Dialog onOpenChange={setIsDialogOpen} open={isDialogOpen}>
        <PageHeader breadcrumbs={[{ label: "Logs" }]}>
          <DialogTrigger asChild>
            <Button size={"sm"}>
              <PlusIcon />
              New
            </Button>
          </DialogTrigger>
        </PageHeader>

        <DialogContent>
          <DialogHeader>
            <DialogTitle>New Log Group</DialogTitle>
            <DialogDescription>Create a new log group to organize and analyze your log files.</DialogDescription>
          </DialogHeader>

          <form className={"flex flex-col gap-4"} onSubmit={onSubmit}>
            <FieldGroup>
              <Field>
                <FieldLabel htmlFor={"log-group-name"}>Name</FieldLabel>
                <FieldContent>
                  <Input
                    autoComplete={"off"}
                    id={"log-group-name"}
                    onChange={(event) => setName(event.target.value)}
                    placeholder={"e.g. Production API Logs"}
                    value={name}
                  />
                </FieldContent>
              </Field>

              {createError !== null && <FieldError>{createError}</FieldError>}

              <div className={"flex justify-end gap-2"}>
                <Button onClick={closeDialog} type={"button"} variant={"outline"}>
                  Cancel
                </Button>
                <Button disabled={isSubmitting} type={"submit"}>
                  {isSubmitting ? <Spinner /> : "Create"}
                </Button>
              </div>
            </FieldGroup>
          </form>
        </DialogContent>
      </Dialog>

      <main className={"flex flex-1 flex-col overflow-auto p-6"}>
        {groups === null && fetchError === null && (
          <div className={"flex flex-col gap-2"}>
            {[1, 2, 3].map((index) => (
              <div className={"flex items-center gap-4 rounded-md border p-4"} key={index}>
                <div className={"flex flex-col gap-1.5"}>
                  <Skeleton className={"h-4 w-40"} />
                  <Skeleton className={"h-3 w-24"} />
                </div>
                <div className={"ml-auto flex items-center gap-3"}>
                  <Skeleton className={"h-3 w-16"} />
                  <Skeleton className={"h-3 w-16"} />
                  <Skeleton className={"size-4 rounded-full"} />
                </div>
              </div>
            ))}
          </div>
        )}

        {fetchError !== null && (
          <div className={"flex flex-col items-center gap-4 py-12 text-center"}>
            <p className={"text-destructive text-sm"}>{fetchError}</p>
            <Button onClick={() => void fetchEntries()} size={"sm"} variant={"outline"}>
              Try again
            </Button>
          </div>
        )}

        {groups !== null && groups.length === 0 && (
          <Empty className={"border"}>
            <EmptyHeader>
              <EmptyMedia variant={"icon"}>
                <ScrollTextIcon />
              </EmptyMedia>
              <EmptyTitle>No log groups yet</EmptyTitle>
              <EmptyDescription>Create a log group to start organizing and analyzing your log files.</EmptyDescription>
            </EmptyHeader>
            <Button onClick={() => setIsDialogOpen(true)}>
              <PlusIcon />
              New Log Group
            </Button>
          </Empty>
        )}

        {groups !== null && groups.length > 0 && (
          <div className={"flex flex-col gap-2"}>
            {groups.map((group) => (
              <Link
                className={"group flex items-center gap-4 rounded-md border p-4 transition-colors hover:bg-accent/50"}
                key={group.id}
                params={{ id: group.id }}
                to={"/logs/$id"}
              >
                <div className={"flex min-w-0 flex-col gap-0.5"}>
                  <span className={"font-medium text-sm"}>{group.name}</span>
                  <span className={"text-muted-foreground text-xs"}>
                    {new Date(group.created_at).toLocaleDateString("en-US", {
                      month: "short",
                      day: "numeric",
                      year: "numeric",
                    })}
                  </span>
                </div>
                <div className={"ml-auto flex items-center gap-3 text-muted-foreground text-xs tabular-nums"}>
                  <span>
                    {group.file_count} file{group.file_count !== 1 ? "s" : ""}
                  </span>
                  <span>
                    {group.table_count} table{group.table_count !== 1 ? "s" : ""}
                  </span>
                  <ChevronRightIcon className={"size-4 transition-transform group-hover:translate-x-0.5"} />
                </div>
              </Link>
            ))}
          </div>
        )}
      </main>
    </div>
  );
}
