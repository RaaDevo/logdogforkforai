import type { UIMessage } from "@tanstack/ai-react";
import { fetchServerSentEvents, useChat } from "@tanstack/ai-react";
import {
  AlertCircleIcon,
  BotIcon,
  ChevronDownIcon,
  ChevronUpIcon,
  SendHorizontalIcon,
  SparklesIcon,
  Trash2Icon,
} from "lucide-react";
import { type FormEvent, useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Button } from "#/components/ui/button";
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from "#/components/ui/collapsible";
import { InputGroup, InputGroupAddon, InputGroupButton, InputGroupTextarea } from "#/components/ui/input-group";
import { Spinner } from "#/components/ui/spinner";
import { getLogChatMessages, replaceLogChatMessages } from "#/lib/server";
import { streamLogChat } from "#/lib/server/chat";
import { ChatMessageItem } from "#/routes/(platform)/logs/-components/chat-message";

type ChatbotTabProps = {
  entryId: string;
  groupName: string;
  tableNames: string[];
};

const STARTER_MESSAGES = [
  "What tables are available in this log group?",
  "Show me a summary of all uploaded data.",
  "Are there any anomalies or errors in the logs?",
];

function toPersistedMessages(messages: UIMessage[]) {
  return messages
    .filter((message) => message.role === "user" || message.role === "assistant")
    .map((message) => ({
      id: message.id,
      role: message.role,
      content: message.parts
        .filter((part) => part.type === "text" && typeof part.content === "string")
        .map((part) => (part as { content: string }).content)
        .join("\n"),
      parts: message.parts as Array<Record<string, unknown>>,
    }));
}

function restoreUIMessages(messages: Array<{ role: string; parts?: Array<Record<string, unknown>>; id?: string }>) {
  return messages
    .filter((msg) => msg.role === "user" || msg.role === "assistant")
    .map((msg) => ({
      id: msg.id ?? crypto.randomUUID(),
      role: msg.role as "user" | "assistant",
      parts: (msg.parts ?? []) as UIMessage["parts"],
    })) as UIMessage[];
}

function hasVisibleContent(message: UIMessage) {
  return message.parts.some(
    (part) => part.type === "text" && typeof part.content === "string" && part.content.length > 0,
  );
}

function ErrorBadge({ label, message }: { label: string; message: string }) {
  const [isOpen, setIsOpen] = useState(false);

  return (
    <Collapsible onOpenChange={setIsOpen} open={isOpen}>
      <CollapsibleTrigger asChild>
        <button
          className={
            "inline-flex cursor-pointer items-center gap-1 rounded-full bg-destructive/10 px-2 py-0.5" +
            "text-destructive text-xs transition-colors hover:bg-destructive/20"
          }
          type={"button"}
        >
          <AlertCircleIcon className={"size-2.5"} />
          {label}
          {isOpen ? <ChevronUpIcon className={"size-3"} /> : <ChevronDownIcon className={"size-3"} />}
        </button>
      </CollapsibleTrigger>
      <CollapsibleContent>
        <p className={"mt-2 max-w-md rounded-md bg-destructive/5 px-3 py-2 text-destructive text-xs"}>{message}</p>
      </CollapsibleContent>
    </Collapsible>
  );
}

type Suggestion = {
  text: string;
};

function getNextMessageSuggestions(lastMessageIsAssistant: boolean, hasTables: boolean): Suggestion[] {
  if (!lastMessageIsAssistant) {
    return [];
  }

  if (hasTables) {
    return [
      { text: "Show a high-level summary" },
      { text: "Find the most important anomalies" },
      { text: "Create a chart of key trends" },
      { text: "Generate a report" },
    ];
  }

  return [
    { text: "What data has been uploaded?" },
    { text: "How do I process logs first?" },
    { text: "What should I upload next?" },
  ];
}

function messagesEqual(a: UIMessage[], b: UIMessage[]) {
  if (a.length !== b.length) return false;
  for (let i = 0; i < a.length; i++) {
    if (a[i].id !== b[i].id) return false;
    if (a[i].role !== b[i].role) return false;
    if (a[i].parts.length !== b[i].parts.length) return false;
  }
  return true;
}

export function ChatbotTab({ entryId, groupName, tableNames }: ChatbotTabProps) {
  const [draftMessage, setDraftMessage] = useState("");
  const [hydrateError, setHydrateError] = useState<string | null>(null);
  const [persistError, setPersistError] = useState<string | null>(null);
  const [isHydrating, setIsHydrating] = useState(true);
  const [isAtBottom, setIsAtBottom] = useState(true);

  const scrollContainerRef = useRef<HTMLDivElement>(null);
  const messagesEndRef = useRef<HTMLDivElement>(null);
  const hydratedMessagesRef = useRef<UIMessage[]>([]);
  const hasHydratedRef = useRef(false);

  const { messages, sendMessage, setMessages, stop, isLoading, status, error } = useChat({
    id: `log-group-${entryId}`,
    connection: fetchServerSentEvents("/", {
      fetchClient: async (_url, init) => {
        const bodyText = typeof init?.body === "string" ? init.body : "";
        let parsedBody: { messages?: unknown[] } = {};
        if (bodyText.length > 0) {
          try {
            parsedBody = JSON.parse(bodyText) as { messages?: unknown[] };
          } catch {
            parsedBody = {};
          }
        }

        return streamLogChat({
          data: {
            entryId,
            messages: Array.isArray(parsedBody.messages) ? parsedBody.messages : [],
          },
          signal: init?.signal ?? undefined,
        });
      },
    }),
  });

  const scrollToBottom = useCallback(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, []);

  const handleScroll = useCallback(() => {
    const container = scrollContainerRef.current;
    if (!container) {
      return;
    }

    const { scrollTop, scrollHeight, clientHeight } = container;
    const atBottom = scrollHeight - scrollTop - clientHeight < 50;
    setIsAtBottom(atBottom);
  }, []);

  useEffect(() => {
    if (isAtBottom || isLoading) {
      scrollToBottom();
    }
  }, [messages, isLoading, isAtBottom, scrollToBottom]);

  useEffect(() => {
    let cancelled = false;

    const hydrate = async () => {
      setHydrateError(null);
      setPersistError(null);
      setIsHydrating(true);

      try {
        const savedMessages = await getLogChatMessages(entryId);
        if (cancelled) {
          return;
        }

        const restoredMessages = restoreUIMessages(savedMessages);
        hydratedMessagesRef.current = restoredMessages;
        hasHydratedRef.current = true;
        setMessages(restoredMessages);
      } catch (hydrateError) {
        if (!cancelled) {
          setHydrateError(hydrateError instanceof Error ? hydrateError.message : "Failed to load chat history.");
          setMessages([]);
        }
      } finally {
        if (!cancelled) {
          setIsHydrating(false);
        }
      }
    };

    void hydrate();

    return () => {
      cancelled = true;
    };
  }, [entryId, setMessages]);

  useEffect(() => {
    if (isHydrating || status !== "ready") {
      return;
    }

    if (hasHydratedRef.current && messagesEqual(messages, hydratedMessagesRef.current)) {
      return;
    }

    let cancelled = false;

    const persist = async () => {
      setPersistError(null);

      try {
        await replaceLogChatMessages(entryId, {
          messages: toPersistedMessages(messages),
        });
      } catch (persistError) {
        if (!cancelled) {
          setPersistError(persistError instanceof Error ? persistError.message : "Failed to save chat history.");
        }
      }
    };

    void persist();

    return () => {
      cancelled = true;
    };
  }, [entryId, isHydrating, messages, status]);

  const submitMessage = async () => {
    const trimmed = draftMessage.trim();
    if (trimmed.length === 0 || isLoading) {
      return;
    }

    setDraftMessage("");
    await sendMessage(trimmed);
  };

  const onSubmit = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    void submitMessage();
  };

  const handleClearChat = useCallback(async () => {
    stop();
    setDraftMessage("");
    setMessages([]);
    hydratedMessagesRef.current = [];
    try {
      await replaceLogChatMessages(entryId, { messages: [] });
    } catch {
      setPersistError("Failed to clear chat history.");
    }
  }, [entryId, setMessages, stop]);

  const visibleMessages = useMemo(() => messages.filter(hasVisibleContent), [messages]);
  const hasMessages = visibleMessages.length > 0;
  const lastMessageIsAssistant = useMemo(
    () => hasMessages && visibleMessages[visibleMessages.length - 1].role === "assistant",
    [hasMessages, visibleMessages],
  );
  const suggestions = useMemo(
    () => getNextMessageSuggestions(lastMessageIsAssistant, tableNames.length > 0),
    [lastMessageIsAssistant, tableNames.length],
  );

  return (
    <div className={"flex min-h-0 flex-1 flex-col"}>
      {(hydrateError !== null || persistError !== null || error !== undefined) && (
        <div className={"flex flex-wrap gap-2 px-4 pt-2 pb-1"}>
          {hydrateError !== null && <ErrorBadge label={"Load failed"} message={hydrateError} />}
          {persistError !== null && <ErrorBadge label={"Save failed"} message={persistError} />}
          {error !== undefined && (
            <ErrorBadge label={"Chat failed"} message={error.message || "Failed to generate a response."} />
          )}
        </div>
      )}

      <div
        className={
          "flex min-h-0 flex-1 overflow-y-auto" + (hasMessages ? "" : "bg-gradient-to-b from-muted/30 to-background")
        }
        onScroll={handleScroll}
        ref={scrollContainerRef}
      >
        {isHydrating ? (
          <div className={"flex flex-1 items-center justify-center"}>
            <Spinner />
          </div>
        ) : !hasMessages ? (
          <div className={"flex flex-1 flex-col items-center justify-center px-6"}>
            <div className={"flex max-w-lg flex-col items-center gap-8 text-center"}>
              <div
                className={"flex size-16 items-center justify-center rounded-3xl bg-primary/10 ring-1 ring-primary/20"}
              >
                <BotIcon className={"size-8 text-primary"} />
              </div>
              <div className={"flex flex-col gap-1.5"}>
                <h2 className={"font-semibold text-xl"}>Log Analysis Chatbot</h2>
                <p className={"mx-auto max-w-sm text-muted-foreground text-sm"}>
                  Ask questions about {groupName}. I can query tables, find anomalies, generate charts, and compile
                  reports.
                </p>
              </div>
              <div className={"flex w-full flex-col gap-2"}>
                {STARTER_MESSAGES.map((message) => (
                  <Button
                    className={"h-auto w-full justify-start gap-3 px-4 py-3 text-left text-sm"}
                    disabled={isLoading}
                    key={message}
                    onClick={() => void sendMessage(message)}
                    variant={"outline"}
                  >
                    <SparklesIcon className={"size-4 shrink-0 text-muted-foreground"} />
                    <span className={"line-clamp-2"}>{message}</span>
                  </Button>
                ))}
              </div>
            </div>
          </div>
        ) : (
          <div className={"mx-auto w-full max-w-3xl space-y-4 px-4 py-6"}>
            {visibleMessages.map((message) => (
              <ChatMessageItem entryId={entryId} groupName={groupName} key={message.id} message={message} />
            ))}
            <div ref={messagesEndRef} />
          </div>
        )}
      </div>

      {!isAtBottom && hasMessages && (
        <div className={"absolute right-4 bottom-24 z-10"}>
          <Button
            className={"rounded-full shadow-lg ring-1 ring-border"}
            onClick={scrollToBottom}
            size={"sm"}
            variant={"secondary"}
          >
            Scroll to bottom
          </Button>
        </div>
      )}

      <div
        className={
          "shrink-0 border-t bg-background/80 backdrop-blur-xl supports-[backdrop-filter]:bg-background/60" +
          (hasMessages ? "" : "border-t-transparent")
        }
      >
        <div className={"mx-auto max-w-3xl"}>
          {hasMessages && (
            <div className={"flex items-center justify-end gap-2 px-4 pt-3 pb-2"}>
              <Button
                className={"shrink-0 rounded-full"}
                disabled={isLoading}
                onClick={() => void handleClearChat()}
                size={"sm"}
                type={"button"}
                variant={"ghost"}
              >
                <Trash2Icon className={"size-3 shrink-0"} />
                <span className={"truncate"}>Clear Chat</span>
              </Button>
            </div>
          )}

          {hasMessages && suggestions.length > 0 && !isLoading && (
            <div className={"flex flex-wrap items-center gap-2 px-4 pb-2"}>
              {suggestions.map((suggestion) => (
                <Button
                  className={"h-auto gap-2 px-3 py-1.5 text-xs"}
                  key={suggestion.text}
                  onClick={() => void sendMessage(suggestion.text)}
                  size={"sm"}
                  variant={"outline"}
                >
                  <SparklesIcon className={"size-3 shrink-0 text-muted-foreground"} />
                  {suggestion.text}
                </Button>
              ))}
            </div>
          )}

          <form className={"flex items-center justify-center gap-2 px-4 pt-3 pb-4"} onSubmit={onSubmit}>
            <InputGroup className={"bg-background shadow-sm"}>
              <InputGroupTextarea
                className={"max-h-[200px] min-h-[44px] py-3"}
                disabled={isLoading}
                onChange={(event) => setDraftMessage(event.currentTarget.value)}
                onKeyDown={(event) => {
                  if (event.key === "Enter" && !event.shiftKey) {
                    event.preventDefault();
                    void submitMessage();
                  }
                }}
                placeholder={"Ask about anomalies, trends, or table insights..."}
                rows={1}
                value={draftMessage}
              />
              <InputGroupAddon align={"inline-end"}>
                <InputGroupButton
                  className={"mr-1 size-8 rounded-full"}
                  disabled={isLoading || !draftMessage.trim()}
                  size={"icon-sm"}
                  type={"submit"}
                  variant={"default"}
                >
                  <SendHorizontalIcon />
                  <span className={"sr-only"}>Send</span>
                </InputGroupButton>
              </InputGroupAddon>
            </InputGroup>
          </form>
        </div>
      </div>
    </div>
  );
}
