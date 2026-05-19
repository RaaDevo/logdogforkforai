import { chat, type ModelMessage, toolDefinition, toServerSentEventsResponse } from "@tanstack/ai";
import { createOpenRouterText } from "@tanstack/ai-openrouter";
import { createServerFn } from "@tanstack/react-start";
import { z } from "zod";
import { getEnv } from "#/environment";

const ACCESS_TOKEN_COOKIE = "logdog-access-token";

const TABLE_RESULT_LIMIT = 200;
const DEFAULT_SQL_TYPE = "TEXT";

type TableDefinition = {
  table_name?: string;
  columns?: Array<{
    name?: string;
    sql_type?: string;
  }>;
};

type LogProcessResult = {
  table_definitions?: TableDefinition[];
  records?: Record<string, unknown[]>;
};

type LogProcessResponse = {
  status: string;
  result: LogProcessResult | null;
};

type TableAccumulator = {
  rowCount: number;
  columns: Map<string, string>;
};

const MAX_PERSISTED_MESSAGES = 500;
const MAX_MESSAGE_CONTENT_LENGTH = 100000;

const streamLogChatInputSchema = z.object({
  entryId: z.string().min(1),
  messages: z.array(z.unknown()).min(1).max(MAX_PERSISTED_MESSAGES),
});

const listAvailableTablesInputSchema = z.object({
  include_columns: z.boolean().optional().default(true),
});

const executeSqlQueryInputSchema = z.object({
  sql: z.string().min(1).describe("A SELECT SQL query to execute against the parsed log tables."),
});

const getSqlCommandTemplatesInputSchema = z.object({
  table_name: z
    .string()
    .optional()
    .describe("Optional table name to substitute into SQL templates. Double quotes are applied automatically."),
});

const widgetStatsItemSchema = z.object({
  label: z.string(),
  value: z.union([z.string(), z.number()]),
  description: z.string().optional(),
});

const renderWidgetInputSchema = z.discriminatedUnion("type", [
  z.object({
    type: z.literal("data_table"),
    columns: z.array(z.string()).min(1),
    rows: z.array(z.array(z.unknown())),
    title: z.string().optional(),
  }),
  z.object({
    type: z.literal("chart"),
    chart_type: z.enum(["bar", "line", "pie"]),
    data: z.array(z.record(z.string(), z.unknown())).min(1),
    x_key: z.string(),
    y_key: z.string(),
    title: z.string().optional(),
  }),
  z.object({
    type: z.literal("stats"),
    stats: z.array(widgetStatsItemSchema).min(1),
  }),
]);

const reportSectionTableSchema = z.object({
  title: z.string(),
  columns: z.array(z.string()),
  rows: z.array(z.array(z.unknown())),
});

const reportSectionSchema = z.object({
  heading: z.string(),
  content: z.string(),
  tables: z.array(reportSectionTableSchema).default([]),
});

const generateReportInputSchema = z.object({
  title: z.string().min(1).describe("Report title."),
  sections: z
    .array(reportSectionSchema)
    .min(1)
    .describe("Report sections with headings, content, and optional data tables."),
});

function getErrorMessage(error: unknown, fallbackMessage: string) {
  return error instanceof Error ? error.message : fallbackMessage;
}

async function fetchBackendPost<T>(
  origin: string,
  authorizationHeader: string,
  path: string,
  body: unknown,
): Promise<T> {
  const url = new URL(`/api${path}`, normalizeOrigin(origin));
  const response = await fetch(url, {
    method: "POST",
    headers: {
      Authorization: authorizationHeader,
      "Content-Type": "application/json",
    },
    body: JSON.stringify(body),
  });

  if (!response.ok) {
    const payload = await response.text();
    throw new Error(`Backend request failed (${response.status}): ${payload}`);
  }

  return (await response.json()) as T;
}

function normalizeOrigin(origin: string) {
  return origin.endsWith("/") ? origin.slice(0, -1) : origin;
}

type LogGroupMetadata = {
  id: string;
  name: string;
};

async function fetchLogGroupMetadata(entryId: string, origin: string, authorizationHeader: string) {
  const url = new URL(`/api/logs/${encodeURIComponent(entryId)}`, normalizeOrigin(origin));
  const response = await fetch(url, {
    headers: { Authorization: authorizationHeader },
  });

  if (!response.ok) {
    throw new Error(`Failed to fetch log group metadata (${response.status})`);
  }

  return (await response.json()) as LogGroupMetadata;
}

function normalizeGroupName(name: string): string {
  return name.trim().replace(/\s+/g, " ").slice(0, 120);
}

async function fetchLogProcesses(entryId: string, origin: string, authorizationHeader: string) {
  const processUrl = new URL(`/api/logs/${encodeURIComponent(entryId)}/processes`, normalizeOrigin(origin));
  const response = await fetch(processUrl, {
    headers: { Authorization: authorizationHeader },
  });

  if (!response.ok) {
    const payload = await response.text();
    throw new Error(`Failed to fetch log processes (${response.status}): ${payload}`);
  }

  return (await response.json()) as LogProcessResponse[];
}

function getOrCreateTableAccumulator(tableMetadata: Map<string, TableAccumulator>, tableName: string) {
  let accumulator = tableMetadata.get(tableName);
  if (accumulator === undefined) {
    accumulator = {
      rowCount: 0,
      columns: new Map<string, string>(),
    };
    tableMetadata.set(tableName, accumulator);
  }

  return accumulator;
}

function buildDiscoveredTables(processes: LogProcessResponse[]) {
  const completedProcesses = processes.filter((process) => process.status === "completed" && process.result !== null);
  if (completedProcesses.length === 0) {
    return [];
  }

  const tableMetadata = new Map<string, TableAccumulator>();

  for (const process of completedProcesses) {
    const result = process.result;
    if (result === null || typeof result !== "object") {
      continue;
    }

    const records =
      result.records !== null &&
      result.records !== undefined &&
      typeof result.records === "object" &&
      !Array.isArray(result.records)
        ? result.records
        : null;

    const tableDefinitions = Array.isArray(result.table_definitions) ? result.table_definitions : [];

    for (const definition of tableDefinitions) {
      const tableName = typeof definition.table_name === "string" ? definition.table_name.trim() : "";
      if (tableName.length === 0) {
        continue;
      }

      const accumulator = getOrCreateTableAccumulator(tableMetadata, tableName);

      const rows = records !== null && Array.isArray(records[tableName]) ? records[tableName] : [];
      accumulator.rowCount += rows.length;

      if (Array.isArray(definition.columns)) {
        for (const column of definition.columns) {
          const columnName = typeof column.name === "string" ? column.name.trim() : "";
          if (columnName.length === 0) {
            continue;
          }

          const sqlType =
            typeof column.sql_type === "string" && column.sql_type.trim().length > 0
              ? column.sql_type
              : DEFAULT_SQL_TYPE;
          if (!accumulator.columns.has(columnName)) {
            accumulator.columns.set(columnName, sqlType);
          }
        }
      }
    }

    if (records !== null) {
      for (const [tableName, rows] of Object.entries(records)) {
        const normalizedTableName = tableName.trim();
        if (normalizedTableName.length === 0 || !Array.isArray(rows)) {
          continue;
        }

        const accumulator = getOrCreateTableAccumulator(tableMetadata, normalizedTableName);
        accumulator.rowCount += rows.length;
      }
    }
  }

  return [...tableMetadata.entries()]
    .map(([tableName, details]) => ({
      table_name: tableName,
      row_count: details.rowCount,
      columns: [...details.columns.entries()]
        .map(([columnName, sqlType]) => ({
          name: columnName,
          sql_type: sqlType,
        }))
        .sort((leftColumn, rightColumn) => leftColumn.name.localeCompare(rightColumn.name)),
    }))
    .sort((leftTable, rightTable) => leftTable.table_name.localeCompare(rightTable.table_name))
    .slice(0, TABLE_RESULT_LIMIT);
}

function extractTextFromParts(parts: unknown[]) {
  return parts
    .map((part) => {
      if (typeof part !== "object" || part === null) {
        return "";
      }

      const typedPart = part as { type?: unknown; content?: unknown };
      if (typedPart.type !== "text" || typeof typedPart.content !== "string") {
        return "";
      }

      return typedPart.content;
    })
    .filter((value) => value.length > 0)
    .join("\n");
}

function toTextModelMessages(messages: unknown[]) {
  const modelMessages: Array<ModelMessage<string>> = [];

  for (const message of messages) {
    if (typeof message !== "object" || message === null) {
      continue;
    }

    const typedMessage = message as {
      role?: unknown;
      content?: unknown;
      parts?: unknown;
    };
    const role = typedMessage.role === "user" || typedMessage.role === "assistant" ? typedMessage.role : null;
    if (role === null) {
      continue;
    }

    const content =
      typeof typedMessage.content === "string"
        ? typedMessage.content
        : Array.isArray(typedMessage.parts)
          ? extractTextFromParts(typedMessage.parts)
          : "";

    if (content.trim().length === 0) {
      continue;
    }

    modelMessages.push({
      role,
      content: content.slice(0, MAX_MESSAGE_CONTENT_LENGTH),
    });
  }

  return modelMessages;
}

/**
 * Replaces occurrences of the raw entryId UUID in chat message text with the
 * display group name, so the model never sees internal IDs in prior history.
 */
function sanitizeModelMessages(
  messages: Array<ModelMessage<string>>,
  entryId: string,
  groupName: string,
): Array<ModelMessage<string>> {
  if (entryId.length === 0 || entryId === groupName) {
    return messages;
  }
  return messages.map((msg) => ({
    ...msg,
    content: msg.content.replaceAll(entryId, `"${groupName}"`),
  }));
}

function buildSystemPrompt(logGroupName: string) {
  return [
    "You are Logdog's data analyst assistant for a specific log group.",
    `Current log group display name: "${logGroupName}".`,
    "Refer to this log group by its display name. Do not mention internal IDs or UUIDs.",
    "Before any analysis or SQL assumptions, call list_available_tables(include_columns=true) to discover available data.",
    "If no tables are available, stop querying and tell the user to upload/process logs first.",
    "Use get_sql_command_templates to quickly choose valid exploration queries before writing custom SQL.",
    "Use execute_sql_query to run SELECT queries against the parsed log tables for data exploration and analysis.",
    "Always use double quotes around table and column identifiers in SQL.",
    "Avoid ROUND(); when you need integer/decimal averages, prefer CAST(AVG(...) AS INTEGER/REAL).",
    "If a query fails, immediately retry with a simpler inspection query (for example SELECT * ... LIMIT 5) before further analysis.",
    "SQL exploration playbook:",
    '1) Preview rows: SELECT * FROM "<table_name>" LIMIT 5;',
    '2) Count rows: SELECT COUNT(*) AS row_count FROM "<table_name>";',
    '3) Inspect schema: SELECT "column_name", "data_type" FROM information_schema.columns WHERE "table_name" = \'<table_name>\' ORDER BY "ordinal_position";',
    '4) Grouped averages: SELECT "group_col", CAST(AVG("volume") AS INTEGER) AS avg_volume, CAST(AVG("value_col") AS REAL) AS avg_value FROM "<table_name>" GROUP BY "group_col" LIMIT 20;',
    "Use render_widget to present results visually: type 'data_table' for tabular data, 'chart' for bar/line/pie charts, 'stats' for key metrics.",
    "Use generate_report to compile a full analysis report as a downloadable DOCX file when the user asks for a report or when you have gathered sufficient insights.",
    "Report workflow: list tables -> get_sql_command_templates -> query data -> render widgets -> compile findings into generate_report.",
    "Rely only on user-provided information and tool outputs.",
    "If the available data is insufficient, explicitly say what is missing and suggest the next query or upload.",
    "Keep answers concise, actionable, and focused on insights from the log data.",
    "Do not invent columns, tables, or values that are not present in tool outputs.",
  ].join("\n");
}

function createLogChatServerTools(options: { entryId: string; origin: string; authorizationHeader: string }) {
  const listAvailableTables = toolDefinition({
    name: "list_available_tables",
    description: "List parsed tables available for the current log group, including row counts and schemas.",
    inputSchema: listAvailableTablesInputSchema,
    outputSchema: z.object({
      status: z.enum(["ok", "no_data", "error"]),
      message: z.string(),
      tables: z.array(
        z.object({
          table_name: z.string(),
          row_count: z.number().int().nonnegative(),
          columns: z.array(
            z.object({
              name: z.string(),
              sql_type: z.string(),
            }),
          ),
        }),
      ),
    }),
  }).server(async ({ include_columns }) => {
    try {
      const processes = await fetchLogProcesses(options.entryId, options.origin, options.authorizationHeader);
      const tables = buildDiscoveredTables(processes);

      if (tables.length === 0) {
        return {
          status: "no_data" as const,
          message: "No parsed table data is currently available for this log group.",
          tables: [],
        };
      }

      const includeColumns = include_columns ?? true;
      const responseTables = includeColumns
        ? tables
        : tables.map((table) => ({
            ...table,
            columns: [],
          }));

      return {
        status: "ok" as const,
        message: `Found ${responseTables.length} parsed table${responseTables.length === 1 ? "" : "s"}.`,
        tables: responseTables,
      };
    } catch (error) {
      return {
        status: "error" as const,
        message: `Failed to list tables: ${getErrorMessage(error, "Unknown error.")}`,
        tables: [],
      };
    }
  });

  const getSqlCommandTemplates = toolDefinition({
    name: "get_sql_command_templates",
    description:
      "Return SQL exploration command templates that are safe for this environment. Use this before writing custom SQL.",
    inputSchema: getSqlCommandTemplatesInputSchema,
    outputSchema: z.object({
      status: z.literal("ok"),
      dialect: z.string(),
      notes: z.array(z.string()),
      commands: z.array(
        z.object({
          name: z.string(),
          purpose: z.string(),
          sql: z.string(),
        }),
      ),
    }),
  }).server(async ({ table_name }) => {
    const normalizedTableName = typeof table_name === "string" ? table_name.trim() : "";
    const escapedTableName = normalizedTableName.replaceAll('"', '""');
    const tableTarget = escapedTableName.length > 0 ? `"${escapedTableName}"` : '"<table_name>"';

    return {
      status: "ok" as const,
      dialect: "SQLAlchemy backend SQL dialect",
      notes: [
        "Use double quotes around table and column identifiers.",
        "Use SELECT-only queries.",
        "Prefer CAST(AVG(...)) over ROUND(...) for compatibility.",
      ],
      commands: [
        {
          name: "preview_rows",
          purpose: "Inspect sample rows before analysis.",
          sql: `SELECT * FROM ${tableTarget} LIMIT 5;`,
        },
        {
          name: "row_count",
          purpose: "Check table size.",
          sql: `SELECT COUNT(*) AS row_count FROM ${tableTarget};`,
        },
        {
          name: "column_types",
          purpose: "Inspect schema metadata from information_schema.",
          sql: 'SELECT "column_name", "data_type" FROM information_schema.columns WHERE "table_name" = \'<table_name>\' ORDER BY "ordinal_position";',
        },
        {
          name: "value_distribution",
          purpose: "Get top grouped values with frequencies.",
          sql: `SELECT "<group_col>", COUNT(*) AS count_rows FROM ${tableTarget} GROUP BY "<group_col>" ORDER BY count_rows DESC LIMIT 20;`,
        },
        {
          name: "time_range",
          purpose: "Get observed timestamp boundaries.",
          sql: `SELECT MIN("<timestamp_col>") AS min_timestamp, MAX("<timestamp_col>") AS max_timestamp FROM ${tableTarget};`,
        },
        {
          name: "casted_averages",
          purpose: "Compute averages without ROUND().",
          sql: `SELECT "<group_col>", CAST(AVG("<volume_col>") AS INTEGER) AS avg_volume, CAST(AVG("<metric_col>") AS REAL) AS avg_metric FROM ${tableTarget} GROUP BY "<group_col>" ORDER BY avg_volume DESC LIMIT 20;`,
        },
      ],
    };
  });

  const executeSqlQuery = toolDefinition({
    name: "execute_sql_query",
    description:
      "Run a read-only SELECT SQL query against the parsed log tables. Use this to explore data, compute aggregations, find anomalies, and answer analytical questions.",
    inputSchema: executeSqlQueryInputSchema,
    outputSchema: z.object({
      status: z.enum(["ok", "error"]),
      columns: z.array(z.string()),
      rows: z.array(z.array(z.unknown())),
      row_count: z.number(),
      execution_time_ms: z.number(),
      message: z.string(),
    }),
  }).server(async ({ sql }) => {
    try {
      const result = await fetchBackendPost<{
        status: string;
        columns: string[];
        rows: unknown[][];
        row_count: number;
        execution_time_ms: number;
        message: string;
      }>(options.origin, options.authorizationHeader, `/logs/${encodeURIComponent(options.entryId)}/query`, { sql });

      return {
        status: result.status === "ok" ? ("ok" as const) : ("error" as const),
        columns: result.columns ?? [],
        rows: (result.rows ?? []).map((row) => row.map((v) => (typeof v === "object" ? JSON.stringify(v) : v))),
        row_count: result.row_count ?? 0,
        execution_time_ms: result.execution_time_ms ?? 0,
        message: result.message ?? "",
      };
    } catch (error) {
      return {
        status: "error" as const,
        columns: [],
        rows: [],
        row_count: 0,
        execution_time_ms: 0,
        message: `Query failed: ${getErrorMessage(error, "Unknown error.")}`,
      };
    }
  });

  const renderWidget = toolDefinition({
    name: "render_widget",
    description:
      "Render a visual widget in the chat. Use type 'data_table' for tabular results, 'chart' for bar/line/pie charts, or 'stats' for key metric cards.",
    inputSchema: renderWidgetInputSchema,
    outputSchema: z.object({
      type: z.string(),
      message: z.string(),
    }),
  }).server(async (input) => {
    return {
      type: input.type,
      message: `Rendered ${input.type} widget.`,
    };
  });

  const generateReport = toolDefinition({
    name: "generate_report",
    description:
      "Generate a full analysis report as a downloadable DOCX file. Compile findings, data tables, and insights into a structured report document.",
    inputSchema: generateReportInputSchema,
    outputSchema: z.object({
      status: z.enum(["ok", "error"]),
      message: z.string(),
      download_url: z.string().optional(),
    }),
  }).server(async ({ title, sections }) => {
    try {
      const url = new URL(`/api/logs/${encodeURIComponent(options.entryId)}/report`, normalizeOrigin(options.origin));
      const response = await fetch(url, {
        method: "POST",
        headers: {
          Authorization: options.authorizationHeader,
          "Content-Type": "application/json",
        },
        body: JSON.stringify({ title, sections }),
      });

      if (!response.ok) {
        const payload = await response.text();
        throw new Error(`Report generation failed (${response.status}): ${payload}`);
      }

      const blob = await response.arrayBuffer();
      const bytes = new Uint8Array(blob);
      const binary = bytes.reduce((acc, byte) => acc + String.fromCharCode(byte), "");
      const base64 = btoa(binary);
      const downloadUrl = `data:application/vnd.openxmlformats-officedocument.wordprocessingml.document;base64,${base64}`;

      return {
        status: "ok" as const,
        message: `Report "${title}" generated successfully.`,
        download_url: downloadUrl,
      };
    } catch (error) {
      return {
        status: "error" as const,
        message: `Report generation failed: ${getErrorMessage(error, "Unknown error.")}`,
      };
    }
  });

  return [listAvailableTables, getSqlCommandTemplates, executeSqlQuery, renderWidget, generateReport];
}

export const streamLogChat = createServerFn({ method: "POST" })
  .inputValidator((data: unknown) => streamLogChatInputSchema.parse(data))
  .handler(async ({ data, request }) => {
    const modelMessages = toTextModelMessages(data.messages);
    if (modelMessages.length === 0) {
      throw new Error("No text messages were provided.");
    }

    // Derive backend origin and auth token server-side from the incoming
    // request instead of accepting them from the client. This prevents SSRF
    // and token-forwarding attacks.
    const requestUrl = new URL(request.url);
    const backendOrigin = `${requestUrl.protocol}//${requestUrl.host}`;

    const cookies = request.headers.get("cookie") ?? "";
    const accessToken = parseCookieValue(cookies, ACCESS_TOKEN_COOKIE);
    const authorizationHeader = accessToken ? `Bearer ${accessToken}` : "";

    const tools = createLogChatServerTools({
      entryId: data.entryId,
      origin: backendOrigin,
      authorizationHeader,
    });

    // Fetch the log group's friendly name so we never expose the raw UUID
    // to the model or in the system prompt.
    const groupMetadata = await fetchLogGroupMetadata(data.entryId, backendOrigin, authorizationHeader);
    const logGroupName = normalizeGroupName(groupMetadata.name);

    // Sanitize prior chat history: replace any occurrence of the internal
    // entryId UUID with the display name so the model doesn't see stale IDs.
    const sanitizedMessages = sanitizeModelMessages(modelMessages, data.entryId, logGroupName);

    const {
      openRouterApiKey: orApiKey,
      openRouterModel: orModel,
      openRouterTitle: orTitle,
      openRouterReferer: orReferer,
    } = getEnv();

    const chatStream = chat({
      adapter: createOpenRouterText(orModel, orApiKey, {
        xTitle: orTitle,
        httpReferer: orReferer,
      }),
      messages: sanitizedMessages,
      systemPrompts: [buildSystemPrompt(logGroupName)],
      tools,
    });

    return toServerSentEventsResponse(chatStream);
  });

function parseCookieValue(cookieHeader: string, name: string): string | null {
  for (const cookie of cookieHeader.split(";")) {
    const trimmed = cookie.trim();
    const eqIndex = trimmed.indexOf("=");
    if (eqIndex === -1) {
      continue;
    }
    const key = trimmed.slice(0, eqIndex).trim();
    if (key === name) {
      return decodeURIComponent(trimmed.slice(eqIndex + 1).trim());
    }
  }
  return null;
}
