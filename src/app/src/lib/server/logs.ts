import { $fetch } from "#/lib/server/utils";

export type LogGroup = {
  id: string;
  user_id: string;
  name: string;
  profile_name?: string | null;
  created_at: string;
  file_count: number;
  table_count: number;
};

export type LogFile = {
  id: string;
  group_id: string;
  asset_id: string;
  name: string;
  size: number;
  content_type: string;
  created_at: string;
};

export type LogProcess = {
  id: string;
  group_id: string;
  file_id: string | null;
  status: LogProcessStatus;
  classification: LogProcessClassification | Record<string, unknown> | null;
  result: LogProcessResult | Record<string, unknown> | null;
  error: string | null;
  created_at: string;
  updated_at: string;
};

export type LogProcessStatus = "queued" | "processing" | "completed" | "failed";

export type LogProcessClassification = {
  dominant_format?: string;
  structural_class?: string;
  selected_parser_key?: string;
  file_classifications?: Array<Record<string, unknown>>;
  warnings?: string[];
  confidence?: number;
};

export type LogProcessResult = {
  table_definitions?: Array<Record<string, unknown>>;
  records?: Record<string, unknown>;
  parser_key?: string;
  warnings?: string[];
  confidence?: number;
};

export type UploadFilesResponse = {
  process_ids: string[];
  status: string;
  files: LogFile[];
  outcomes: UploadFileOutcome[];
};

export type UploadFileOutcome = {
  file_id: string;
  filename: string;
  process_id: string | null;
  status: string;
  error: string | null;
};

export type ProcessEnqueuedResponse = {
  process_ids: string[];
  status: string;
  errors: string[];
};

export type FilteredExportPayload = {
  format: "csv" | "json";
  search?: string;
  levels?: string[];
  field_filters?: Record<string, string>;
  timestamp_from?: string;
  timestamp_to?: string;
};

export type FormatDistributionItem = {
  format: string;
  count: number;
};

export type DashboardStats = {
  log_group_count: number;
  total_files: number;
  total_rows: number;
  processes: {
    queued: number;
    processing: number;
    completed: number;
    failed: number;
  };
  format_distribution: FormatDistributionItem[];
};

export type LogInsightReport = {
  summary: string;
  severity: string;
  top_errors: string[];
  root_cause_hypothesis: string;
  log_sequence_narrative: string;
  recommendations: string[];
  anomalies: string[];
};

export type ChatMessage = {
  id: string;
  role: string;
  content?: string;
  parts?: Array<Record<string, unknown>>;
  [key: string]: unknown;
};

type ChatMessagesResponse = {
  messages: ChatMessage[];
};

type ReplaceChatMessagesPayload = {
  messages: ChatMessage[];
};

type ReplaceChatMessagesResponse = {
  saved_messages: number;
};

type MessageResponse = {
  message: string;
};

type CreateLogGroupPayload = {
  name: string;
  profile_name?: string;
};

type UpdateLogGroupPayload = {
  name: string;
  profile_name?: string;
};

type CreateProcessPayload = {
  file_ids?: string[];
};

async function parseJsonResponse<T>(response: Response) {
  if (!response.ok) {
    const payload = await response.text();
    throw new Error(`Request failed (${response.status}): ${payload}`);
  }

  return (await response.json()) as T;
}

export async function listLogGroups() {
  const response = await $fetch("/logs");
  return parseJsonResponse<LogGroup[]>(response);
}

export async function createLogGroup(payload: CreateLogGroupPayload) {
  const response = await $fetch("/logs", {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify(payload),
  });

  return parseJsonResponse<LogGroup>(response);
}

export async function getLogGroup(groupId: string) {
  const response = await $fetch(`/logs/${groupId}`);
  return parseJsonResponse<LogGroup>(response);
}

export async function updateLogGroup(groupId: string, payload: UpdateLogGroupPayload) {
  const response = await $fetch(`/logs/${groupId}`, {
    method: "PATCH",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify(payload),
  });

  return parseJsonResponse<LogGroup>(response);
}

export async function deleteLogGroup(groupId: string) {
  const response = await $fetch(`/logs/${groupId}`, {
    method: "DELETE",
  });

  return parseJsonResponse<MessageResponse>(response);
}

export async function uploadLogFiles(groupId: string, files: File[]) {
  if (!files.length) {
    throw new Error("At least one file is required.");
  }

  const formData = new FormData();
  for (const file of files) {
    formData.append("files", file);
  }

  const response = await $fetch(`/logs/${groupId}/files/upload`, {
    method: "POST",
    body: formData,
  });

  return parseJsonResponse<UploadFilesResponse>(response);
}

export async function listLogFiles(groupId: string) {
  const response = await $fetch(`/logs/${groupId}/files`);
  return parseJsonResponse<LogFile[]>(response);
}

export async function getLogFile(groupId: string, fileId: string) {
  const response = await $fetch(`/logs/${groupId}/files/${fileId}`);
  return parseJsonResponse<LogFile>(response);
}

export async function downloadLogFile(groupId: string, fileId: string) {
  const response = await $fetch(`/logs/${groupId}/files/${fileId}/download`);
  if (!response.ok) {
    const payload = await response.text();
    throw new Error(`Request failed (${response.status}): ${payload}`);
  }

  return response.blob();
}

export async function downloadTableCsv(groupId: string, tableName: string) {
  const response = await $fetch(`/logs/${groupId}/tables/${tableName}/download/csv`);
  if (!response.ok) {
    const payload = await response.text();
    throw new Error(`Request failed (${response.status}): ${payload}`);
  }

  return response.blob();
}

export async function downloadTableXlsx(groupId: string, tableName: string) {
  const response = await $fetch(`/logs/${groupId}/tables/${tableName}/download/xlsx`);
  if (!response.ok) {
    const payload = await response.text();
    throw new Error(`Request failed (${response.status}): ${payload}`);
  }

  return response.blob();
}

export async function downloadFilteredTable(groupId: string, tableName: string, payload: FilteredExportPayload) {
  const response = await $fetch(`/logs/${groupId}/tables/${tableName}/download/filtered`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify(payload),
  });
  if (!response.ok) {
    const rawPayload = await response.text();
    throw new Error(`Request failed (${response.status}): ${rawPayload}`);
  }

  return response.blob();
}

export async function deleteLogFile(groupId: string, fileId: string) {
  const response = await $fetch(`/logs/${groupId}/files/${fileId}`, {
    method: "DELETE",
  });

  return parseJsonResponse<MessageResponse>(response);
}

export async function listLogProcesses(groupId: string) {
  const response = await $fetch(`/logs/${groupId}/processes`);
  return parseJsonResponse<LogProcess[]>(response);
}

export async function getLogProcess(groupId: string, processId: string) {
  const response = await $fetch(`/logs/${groupId}/processes/${processId}`);
  return parseJsonResponse<LogProcess>(response);
}

export async function createLogProcess(groupId: string, payload?: CreateProcessPayload) {
  const response = await $fetch(`/logs/${groupId}/processes`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify(payload ?? {}),
  });

  return parseJsonResponse<ProcessEnqueuedResponse>(response);
}

export async function getDashboardStats() {
  const response = await $fetch("/stats");
  return parseJsonResponse<DashboardStats>(response);
}

export async function getLogReport(entryId: string) {
  const response = await $fetch(`/logs/${entryId}/insights`);
  if (response.status === 404) {
    return null;
  }
  return parseJsonResponse<LogInsightReport | null>(response);
}

export async function downloadWorkbookReport(entryId: string) {
  const response = await $fetch(`/logs/${entryId}/workbook-report`, {
    method: "POST",
  });
  if (!response.ok) {
    const payload = await response.text();
    throw new Error(`Request failed (${response.status}): ${payload}`);
  }
  return response.blob();
}

export async function generateLogReport(entryId: string) {
  const response = await $fetch(`/logs/${entryId}/insights`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify({}),
  });
  return parseJsonResponse<LogInsightReport>(response);
}

export async function getLogChatMessages(entryId: string) {
  const response = await $fetch(`/logs/${entryId}/chat/messages`);
  const payload = await parseJsonResponse<ChatMessagesResponse>(response);
  return payload.messages;
}

export async function replaceLogChatMessages(entryId: string, payload: ReplaceChatMessagesPayload) {
  const response = await $fetch(`/logs/${entryId}/chat/messages`, {
    method: "PUT",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify(payload),
  });

  return parseJsonResponse<ReplaceChatMessagesResponse>(response);
}

export type ChatHistoryMessage = {
  role: string;
  content: string;
};

export async function* streamChatWithLogs(
  entryId: string,
  message: string,
  history: ChatHistoryMessage[],
  signal?: AbortSignal,
): AsyncGenerator<string, void, unknown> {
  const response = await $fetch(`/logs/${entryId}/chat`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify({ message, history }),
    signal,
  });

  if (!response.ok) {
    const payload = await response.text();
    throw new Error(`Chat request failed (${response.status}): ${payload}`);
  }

  if (response.body === null) {
    throw new Error("Chat response body is empty.");
  }

  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";

  try {
    while (true) {
      const { done, value } = await reader.read();
      if (done) {
        break;
      }

      buffer += decoder.decode(value, { stream: true });
      const lines = buffer.split("\n");
      buffer = lines.pop() ?? "";

      for (const line of lines) {
        const trimmed = line.trim();
        if (!trimmed.startsWith("data: ")) {
          continue;
        }

        const data = trimmed.slice(6);
        if (data === "[DONE]") {
          return;
        }

        try {
          const parsed = JSON.parse(data) as { token?: string };
          if (typeof parsed.token === "string") {
            yield parsed.token;
          }
        } catch {
          // Ignore malformed SSE lines.
        }
      }
    }
  } finally {
    reader.releaseLock();
  }
}
