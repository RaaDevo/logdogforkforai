import { createFileRoute, Link } from "@tanstack/react-router";
import {
  ArrowRight,
  BarChart3,
  Braces,
  CheckCircle2,
  ChevronRight,
  Database,
  FileCode,
  FileText,
  RefreshCw,
  Search,
  Shield,
  Zap,
} from "lucide-react";
import { useTheme } from "next-themes";
import type { ReactNode } from "react";
import { Button } from "#/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "#/components/ui/card";
import { Separator } from "#/components/ui/separator";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "#/components/ui/tabs";
import { cn } from "#/lib/utils";

export const Route = createFileRoute("/(public)/")({
  component: LandingPage,
});

const FEATURES = [
  {
    Icon: Zap,
    title: "Instant Schema Detection",
    description:
      "AI automatically infers schema from any log format. No configuration files, no regex patterns to write.",
  },
  {
    Icon: Database,
    title: "Unified Data Store",
    description: "All parsed logs land in a queryable store. Use built-in search or the visual explorer.",
  },
  {
    Icon: Search,
    title: "Full-Text And Structured Search",
    description: "Search across every field and entry with regex, exact match, or natural language.",
  },
  {
    Icon: BarChart3,
    title: "Auto-Generated Analytics",
    description:
      "Error rates, latency distributions, and traffic trends appear automatically as your logs are ingested.",
  },
  {
    Icon: Shield,
    title: "Anomaly Detection",
    description: "Surface unusual patterns and outliers automatically before incidents escalate.",
  },
  {
    Icon: RefreshCw,
    title: "Live Processing",
    description: "Upload files and watch parsing processes update in near real time.",
  },
];

const STATS = [
  { value: "100+", label: "Log formats supported" },
  { value: "<50ms", label: "Parse latency" },
  { value: "Infinity", label: "Schema flexibility" },
];

const STEPS = [
  {
    number: "01",
    title: "Upload or stream your logs",
    description: "Drag and drop files or connect your source. Any format, any source.",
    detail: "Supports plaintext, JSON, CSV, syslog, and mixed-format bundles",
  },
  {
    number: "02",
    title: "AI detects structure",
    description: "The parser extracts fields, types, and relationships automatically.",
    detail: "Handles structured, semi-structured, and unstructured logs",
  },
  {
    number: "03",
    title: "Query and act",
    description: "Explore parsed data, inspect processes, and download normalized files.",
    detail: "Designed for debugging, operations, and rapid incident response",
  },
];

const STRUCTURED_FORMATS = ["JSON / NDJSON", "CSV / TSV", "Logfmt", "OpenTelemetry", "Custom structured"];
const SEMI_FORMATS = ["Apache / Nginx", "Syslog / journald", "W3C logs", "Cloud LB logs", "Kubernetes logs"];
const UNSTRUCTURED_FORMATS = [
  "Legacy application output",
  "Error message dumps",
  "Crash reports",
  "Debug output",
  "Custom text",
];

function LandingPage() {
  const { resolvedTheme } = useTheme();

  return (
    <div className={"min-h-screen overflow-x-hidden bg-[#141414] text-[#f4f4f4]"}>
      <style>{`
        @keyframes scroll-logs {
          0% { transform: translateY(0); }
          100% { transform: translateY(-50%); }
        }
        @keyframes fade-up {
          from { opacity: 0; transform: translateY(20px); }
          to { opacity: 1; transform: translateY(0); }
        }
        .animate-scroll-logs {
          animation: scroll-logs 16s linear infinite;
        }
        .animate-fade-up {
          animation: fade-up 0.65s cubic-bezier(0.22, 1, 0.36, 1) forwards;
        }
        .stagger-1 { animation-delay: 0.05s; opacity: 0; }
        .stagger-2 { animation-delay: 0.15s; opacity: 0; }
        .stagger-3 { animation-delay: 0.25s; opacity: 0; }
        .stagger-4 { animation-delay: 0.38s; opacity: 0; }
        .stagger-5 { animation-delay: 0.52s; opacity: 0; }
      `}</style>

      <div
        className={"pointer-events-none fixed inset-0 select-none"}
        style={{
          backgroundImage:
            "linear-gradient(to right, rgba(244,244,244,0.035) 1px, transparent 1px), linear-gradient(to bottom, rgba(244,244,244,0.035) 1px, transparent 1px)",
          backgroundSize: "72px 72px",
        }}
      />

      <div
        className={"pointer-events-none fixed inset-0 select-none"}
        style={{
          background: "radial-gradient(ellipse 90% 45% at 50% -5%, rgba(249, 246, 24, 0.09) 0%, transparent 65%)",
        }}
      />

      <nav className={"relative z-10 mx-auto flex max-w-7xl items-center justify-between px-6 py-4"}>
        <div className={"flex items-center gap-2.5"}>
          <img alt="Logdog" className="h-8 w-auto" src={resolvedTheme === "dark" ? "/icon-dark.png" : "/icon.png"} />
          <span className={"font-bold text-lg tracking-tight"}>Logdog</span>
        </div>

        <div className={"hidden items-center gap-7 text-sm text-zinc-400 md:flex"}>
          <a className={"transition-colors duration-150 hover:text-white"} href={"#formats"}>
            Formats
          </a>
          <a className={"transition-colors duration-150 hover:text-white"} href={"#how-it-works"}>
            How it works
          </a>
          <a className={"transition-colors duration-150 hover:text-white"} href={"#features"}>
            Features
          </a>
        </div>

        <div className={"flex items-center gap-3"}>
          <Button
            asChild
            className={"text-zinc-400 hover:bg-zinc-800/80 hover:text-white"}
            size={"sm"}
            variant={"ghost"}
          >
            <Link to={"/auth"}>Sign in</Link>
          </Button>
          <Button
            asChild
            className={"bg-[#F9F618] font-semibold text-[#141414] shadow-none hover:bg-[#F9F618]/90"}
            size={"sm"}
          >
            <Link to={"/auth/new"}>Get started</Link>
          </Button>
        </div>
      </nav>

      <section className={"relative z-10 mx-auto max-w-7xl px-6 pt-20 pb-28 text-center"}>
        <h1
          className={
            "stagger-2 mb-6 animate-fade-up font-extrabold text-5xl leading-[1.04] tracking-tight md:text-[4.5rem] lg:text-[5.5rem]"
          }
        >
          Parse any log.
          <br />
          <span className={"text-[#F9F618]"}>Understand everything.</span>
        </h1>

        <p
          className={
            "stagger-3 mx-auto mb-10 max-w-2xl animate-fade-up text-lg text-zinc-400 leading-relaxed md:text-xl"
          }
        >
          Drop in your raw logs. Logdog detects schema, extracts fields, and surfaces insight you can act on without
          brittle parser setup.
        </p>

        <div className={"stagger-4 mb-20 flex animate-fade-up flex-col justify-center gap-3 sm:flex-row"}>
          <Button
            asChild
            className={
              "h-12 gap-2 bg-[#F9F618] px-7 font-semibold text-[#141414] text-base shadow-none hover:bg-[#F9F618]/90"
            }
            size={"lg"}
          >
            <Link to={"/auth/new"}>
              Start parsing free
              <ArrowRight className={"size-4"} />
            </Link>
          </Button>
          <Button
            asChild
            className={
              "h-12 border-zinc-700 bg-transparent px-7 text-base text-zinc-300 hover:bg-zinc-800/80 hover:text-white"
            }
            size={"lg"}
            variant={"outline"}
          >
            <a href={"#how-it-works"}>See how it works</a>
          </Button>
        </div>

        <div className={"stagger-5 relative mx-auto max-w-5xl animate-fade-up"}>
          <div
            className={"pointer-events-none absolute -inset-12 rounded-3xl"}
            style={{
              background: "radial-gradient(ellipse at center, rgba(249,246,24,0.085) 0%, transparent 65%)",
            }}
          />

          <div
            className={
              "relative grid gap-0 overflow-hidden rounded-2xl border border-zinc-800 bg-zinc-950/90 shadow-2xl md:grid-cols-2"
            }
          >
            <div className={"border-zinc-800 border-r"}>
              <div className={"flex items-center gap-2 border-zinc-800 border-b bg-zinc-900/60 px-4 py-3"}>
                <div className={"flex gap-1.5"}>
                  <div className={"size-3 rounded-full bg-zinc-700"} />
                  <div className={"size-3 rounded-full bg-zinc-700"} />
                  <div className={"size-3 rounded-full bg-zinc-700"} />
                </div>
                <span className={"ml-2 font-mono text-xs text-zinc-500"}>raw.log</span>
                <span className={"ml-auto rounded bg-zinc-800 px-1.5 py-0.5 font-mono text-[10px] text-zinc-500"}>
                  INPUT
                </span>
              </div>

              <div className={"relative h-64 overflow-hidden px-5 py-4"}>
                <div
                  className={"animate-scroll-logs whitespace-nowrap font-mono text-[11px] text-zinc-500 leading-[1.7]"}
                >
                  {[...Array(2)].map((_, index) => (
                    <div key={index}>
                      <p>
                        <span className={"text-zinc-600"}>[14:22:31]</span> <span className={"text-red-400"}>CRIT</span>{" "}
                        auth-worker OOM killed after 47 open connections
                      </p>
                      <p>
                        <span className={"text-zinc-600"}>192.168.1.2</span> - alice [05/Mar/2026:14:22:31]{" "}
                        <span className={"text-zinc-400"}>"POST /api/login HTTP/1.1"</span>{" "}
                        <span className={"text-[#F9F618]"}>401</span> 1247
                      </p>
                      <p>
                        <span
                          className={"text-zinc-500"}
                        >{`{"ts":"2026-03-05","lvl":"WARN","svc":"payments","msg":"retry #3","dur":892}`}</span>
                      </p>
                      <p>
                        <span className={"text-zinc-600"}>Mar 5 14:22:33</span> prod-node-1 sshd: Failed password for
                        root from 203.0.113.1
                      </p>
                    </div>
                  ))}
                </div>
                <div
                  className={
                    "pointer-events-none absolute inset-x-0 bottom-0 h-20 bg-linear-to-t from-zinc-950 to-transparent"
                  }
                />
              </div>
            </div>

            <div>
              <div
                className={"flex items-center justify-between gap-2 border-zinc-800 border-b bg-zinc-900/60 px-4 py-3"}
              >
                <div className={"flex items-center gap-2"}>
                  <div className={"flex gap-1.5"}>
                    <div className={"size-3 rounded-full bg-zinc-700"} />
                    <div className={"size-3 rounded-full bg-zinc-700"} />
                    <div className={"size-3 rounded-full bg-zinc-700"} />
                  </div>
                  <span className={"ml-2 font-mono text-xs text-zinc-500"}>parsed output</span>
                </div>
                <span className={"flex items-center gap-1.5 font-mono text-[10px] text-green-400"}>
                  <span
                    className={
                      "inline-block size-1.5 animate-[pulse_2s_ease-in-out_infinite] rounded-full bg-green-400"
                    }
                  />
                  live
                </span>
              </div>

              <div className={"h-64 overflow-hidden p-5 font-mono text-[11px] leading-[1.8]"}>
                <p className={"mb-1 text-zinc-600"}>{`// 1,042 rows - 9 fields extracted`}</p>
                <p>
                  <span className={"text-violet-400"}>timestamp</span> <span className={"text-zinc-600"}>-&gt;</span>{" "}
                  <span className={"text-[#F9F618]"}>"2026-03-05T14:22:31Z"</span>
                </p>
                <p>
                  <span className={"text-violet-400"}>source_ip</span> <span className={"text-zinc-600"}>-&gt;</span>{" "}
                  <span className={"text-[#F9F618]"}>"192.168.1.2"</span>
                </p>
                <p>
                  <span className={"text-violet-400"}>user</span> <span className={"text-zinc-600"}>-&gt;</span>{" "}
                  <span className={"text-blue-300"}>"alice"</span>
                </p>
                <p>
                  <span className={"text-violet-400"}>method</span> <span className={"text-zinc-600"}>-&gt;</span>{" "}
                  <span className={"text-blue-300"}>"POST"</span>
                </p>
                <p>
                  <span className={"text-violet-400"}>path</span> <span className={"text-zinc-600"}>-&gt;</span>{" "}
                  <span className={"text-blue-300"}>"/api/login"</span>
                </p>
                <p>
                  <span className={"text-violet-400"}>status</span> <span className={"text-zinc-600"}>-&gt;</span>{" "}
                  <span className={"text-[#F9F618]"}>401</span>
                </p>
                <p>
                  <span className={"text-violet-400"}>format</span> <span className={"text-zinc-600"}>-&gt;</span>{" "}
                  <span className={"text-zinc-400"}>"combined+json+syslog"</span>
                </p>
              </div>
            </div>
          </div>
        </div>
      </section>

      <div className={"relative z-10 mx-auto max-w-7xl px-6"}>
        <Separator className={"bg-[#404040]/80"} />
      </div>

      <section className={"relative z-10 mx-auto max-w-7xl px-6 py-24"} id={"formats"}>
        <div className={"mb-14 text-center"}>
          <p className={"mb-3 font-mono text-[#F9F618] text-xs uppercase tracking-[0.2em]"}>Universal compatibility</p>
          <h2 className={"mb-4 font-bold text-4xl tracking-tight md:text-5xl"}>Every format. One parser.</h2>
          <p className={"mx-auto max-w-xl text-lg text-zinc-400"}>
            Whether your logs come from modern services or legacy systems, Logdog handles it.
          </p>
        </div>

        <Tabs className={"w-full"} defaultValue={"structured"}>
          <TabsList
            className={cn(
              "mx-auto mb-10 flex w-fit justify-center",
              "h-auto gap-1 rounded-lg border border-zinc-800 bg-zinc-900 p-1",
            )}
          >
            <TabsTrigger
              className={cn(
                "rounded-md px-5 py-2 font-medium text-sm text-zinc-400 transition-all",
                "data-[state=active]:bg-[#F9F618] data-[state=active]:font-semibold data-[state=active]:text-[#141414] data-[state=active]:shadow-none",
                "hover:text-zinc-200",
              )}
              value={"structured"}
            >
              <Braces className={"size-3.5"} />
              Structured
            </TabsTrigger>
            <TabsTrigger
              className={cn(
                "rounded-md px-5 py-2 font-medium text-sm text-zinc-400 transition-all",
                "data-[state=active]:bg-[#F9F618] data-[state=active]:font-semibold data-[state=active]:text-[#141414] data-[state=active]:shadow-none",
                "hover:text-zinc-200",
              )}
              value={"semi"}
            >
              <FileCode className={"size-3.5"} />
              Semi-Structured
            </TabsTrigger>
            <TabsTrigger
              className={cn(
                "rounded-md px-5 py-2 font-medium text-sm text-zinc-400 transition-all",
                "data-[state=active]:bg-[#F9F618] data-[state=active]:font-semibold data-[state=active]:text-[#141414] data-[state=active]:shadow-none",
                "hover:text-zinc-200",
              )}
              value={"unstructured"}
            >
              <FileText className={"size-3.5"} />
              Unstructured
            </TabsTrigger>
          </TabsList>

          <TabsContent value={"structured"}>
            <FormatPanel
              description={
                "Structured logs already carry schema. Logdog reads and reconciles mixed payloads into coherent queryable tables."
              }
              formats={STRUCTURED_FORMATS}
              preview={
                <pre
                  className={
                    "overflow-x-auto whitespace-pre-wrap px-5 py-5 font-mono text-[11px] text-zinc-300 leading-[1.8]"
                  }
                >
                  {`{"ts":"2026-03-05T14:22:31Z","lvl":"ERROR","svc":"auth","msg":"Token expired"}\n{"ts":"2026-03-05T14:22:32Z","lvl":"INFO","svc":"api","msg":"Request completed"}`}
                </pre>
              }
              subtitle={"JSON / NDJSON / CSV / Logfmt"}
              title={"Schema-aligned from the start"}
            />
          </TabsContent>

          <TabsContent value={"semi"}>
            <FormatPanel
              description={
                "Semi-structured logs follow known conventions. Logdog identifies the pattern, extracts fields, and normalizes output automatically."
              }
              formats={SEMI_FORMATS}
              preview={
                <pre
                  className={
                    "overflow-x-auto whitespace-pre-wrap px-5 py-5 font-mono text-[11px] text-zinc-300 leading-[1.8]"
                  }
                >
                  {`192.168.1.105 - alice [05/Mar/2026:14:22:31 +0000]\n"POST /api/v2/sessions HTTP/2.0" 201 512\n10.0.0.2 - - [05/Mar/2026:14:22:32 +0000]\n"GET /health HTTP/1.1" 200 34`}
                </pre>
              }
              subtitle={"Apache / Nginx / Syslog / W3C"}
              title={"Pattern-extracted and normalized"}
            />
          </TabsContent>

          <TabsContent value={"unstructured"}>
            <FormatPanel
              description={
                "No strict format? Logdog uses AI-assisted extraction to identify timestamps, severity, services, and key entities."
              }
              formats={UNSTRUCTURED_FORMATS}
              preview={
                <pre
                  className={
                    "overflow-x-auto whitespace-pre-wrap px-5 py-5 font-mono text-[11px] text-zinc-300 leading-[1.8]"
                  }
                >
                  {`CRITICAL auth-worker crashed while processing request from prod-node-3\nmemory limit exceeded, process restarted, connections dropped.`}
                </pre>
              }
              subtitle={"Plain text / Legacy output"}
              title={"Raw text made queryable"}
            />
          </TabsContent>
        </Tabs>
      </section>

      <section
        className={"relative z-10 px-6 py-24"}
        id={"how-it-works"}
        style={{
          background: "linear-gradient(to bottom, transparent 0%, rgba(255,255,255,0.012) 50%, transparent 100%)",
        }}
      >
        <div className={"mx-auto max-w-7xl"}>
          <div className={"mb-16 text-center"}>
            <p className={"mb-3 font-mono text-[#F9F618] text-xs uppercase tracking-[0.2em]"}>Simple by design</p>
            <h2 className={"font-bold text-4xl tracking-tight md:text-5xl"}>
              From raw chaos to clean data
              <br />
              in three steps.
            </h2>
          </div>

          <div className={"grid gap-6 md:grid-cols-3"}>
            {STEPS.map(({ number, title, description, detail }, index) => (
              <div className={"relative"} key={number}>
                {index < STEPS.length - 1 && (
                  <div
                    className={
                      "absolute top-10 left-[calc(100%+0.75rem)] z-10 hidden w-6 items-center justify-center md:flex"
                    }
                  >
                    <ChevronRight className={"size-4 text-zinc-700"} />
                  </div>
                )}
                <div
                  className={
                    "relative h-full rounded-2xl border border-zinc-800 bg-zinc-900/40 p-8 transition-all duration-200 hover:border-zinc-700 hover:bg-zinc-900/70"
                  }
                >
                  <div className={"mb-5 select-none font-black font-mono text-6xl text-[#F9F618]/20 leading-none"}>
                    {number}
                  </div>
                  <h3 className={"mb-3 font-semibold text-xl"}>{title}</h3>
                  <p className={"mb-5 text-sm text-zinc-400 leading-relaxed"}>{description}</p>
                  <div className={"border-zinc-800 border-t pt-4 font-mono text-xs text-zinc-600"}>{detail}</div>
                </div>
              </div>
            ))}
          </div>
        </div>
      </section>

      <section className={"relative z-10 mx-auto max-w-7xl px-6 py-24"} id={"features"}>
        <div className={"mb-16 text-center"}>
          <p className={"mb-3 font-mono text-[#F9F618] text-xs uppercase tracking-[0.2em]"}>What you get</p>
          <h2 className={"mb-4 font-bold text-4xl tracking-tight md:text-5xl"}>The whole pipeline, built in.</h2>
          <p className={"mx-auto max-w-xl text-lg text-zinc-400"}>
            Logdog is not only a parser. It is the ingestion-to-insight workflow designed for operations.
          </p>
        </div>

        <div className={"grid gap-5 sm:grid-cols-2 lg:grid-cols-3"}>
          {FEATURES.map(({ Icon, title, description }) => (
            <Card
              className={
                "group gap-4 border-zinc-800 bg-zinc-900/40 transition-all duration-200 hover:border-zinc-700 hover:bg-zinc-900/70"
              }
              key={title}
            >
              <CardHeader className={"pb-0"}>
                <div
                  className={
                    "mb-1 flex size-10 items-center justify-center rounded-lg border border-[#F9F618]/30 bg-[#F9F618]/10 transition-colors group-hover:bg-[#F9F618]/20"
                  }
                >
                  <Icon className={"size-5 text-[#F9F618]"} />
                </div>
                <CardTitle className={"font-semibold text-base text-white"}>{title}</CardTitle>
              </CardHeader>
              <CardContent>
                <CardDescription className={"text-sm text-zinc-400 leading-relaxed"}>{description}</CardDescription>
              </CardContent>
            </Card>
          ))}
        </div>
      </section>

      <section className={"relative z-10 mx-auto max-w-4xl px-6 py-6"}>
        <div
          className={"grid grid-cols-3 divide-x divide-zinc-800 overflow-hidden rounded-2xl border border-zinc-800"}
          style={{ background: "rgba(255,255,255,0.015)" }}
        >
          {STATS.map(({ value, label }) => (
            <div className={"p-10 text-center"} key={label}>
              <div className={"mb-2 font-black font-mono text-5xl text-[#F9F618]"}>{value}</div>
              <div className={"text-sm text-zinc-400"}>{label}</div>
            </div>
          ))}
        </div>
      </section>

      <section className={"relative z-10 overflow-hidden px-6 py-32 text-center"}>
        <div
          className={"pointer-events-none absolute inset-0"}
          style={{
            background: "radial-gradient(ellipse 70% 70% at 50% 50%, rgba(249,246,24,0.085) 0%, transparent 65%)",
          }}
        />
        <div className={"relative"}>
          <p className={"mb-5 font-mono text-[#F9F618] text-xs uppercase tracking-[0.2em]"}>Get started free</p>
          <h2
            className={
              "mx-auto mb-6 max-w-3xl font-extrabold text-4xl leading-[1.08] tracking-tight md:text-5xl lg:text-6xl"
            }
          >
            Your logs have been trying to tell you something.
          </h2>
          <p className={"mx-auto mb-10 max-w-md text-lg text-zinc-400"}>
            Start parsing in minutes. No card required. No configuration needed.
          </p>
          <Button
            asChild
            className={
              "h-12 gap-2 bg-[#F9F618] px-8 font-semibold text-[#141414] text-base shadow-none hover:bg-[#F9F618]/90"
            }
            size={"lg"}
          >
            <Link to={"/auth/new"}>
              Start parsing free
              <ArrowRight className={"size-4"} />
            </Link>
          </Button>
        </div>
      </section>

      <footer className={"relative z-10 border-zinc-800/80 border-t px-6 py-10"}>
        <div className={"mx-auto flex max-w-7xl flex-col items-center justify-between gap-5 md:flex-row"}>
          <div className={"flex items-center gap-2.5"}>
            <img alt="Logdog" className="h-7 w-auto" src="/icon.png" />
            <span className={"font-bold text-sm"}>Logdog</span>
          </div>

          <p className={"text-xs text-zinc-600"}>Copyright 2026 Dennise Catolos. All logs welcome.</p>

          <div className={"flex gap-7 text-xs text-zinc-500"}>
            <a className={"transition-colors hover:text-zinc-300"} href={"https://dennise.me/privacy"}>
              Privacy
            </a>
            <a className={"transition-colors hover:text-zinc-300"} href={"https://dennise.me/terms"}>
              Terms
            </a>
          </div>
        </div>
      </footer>
    </div>
  );
}

function FormatPanel({
  subtitle,
  title,
  description,
  formats,
  preview,
}: {
  subtitle: string;
  title: string;
  description: string;
  formats: string[];
  preview: ReactNode;
}) {
  return (
    <div className={"grid items-start gap-10 md:grid-cols-2"}>
      <div>
        <p className={"mb-4 font-mono text-[#F9F618] text-xs uppercase tracking-widest"}>{subtitle}</p>
        <h3 className={"mb-3 font-bold text-2xl"}>{title}</h3>
        <p className={"mb-7 text-zinc-400 leading-relaxed"}>{description}</p>
        <ul className={"space-y-2.5"}>
          {formats.map((format) => (
            <li className={"flex items-center gap-2.5 text-sm text-zinc-300"} key={format}>
              <CheckCircle2 className={"size-4 shrink-0 text-[#F9F618]"} />
              {format}
            </li>
          ))}
        </ul>
      </div>

      <div className={"overflow-hidden rounded-xl border border-zinc-800 bg-zinc-900/50 shadow-xl"}>
        <div className={"flex items-center gap-2 border-zinc-800 border-b bg-zinc-900/80 px-4 py-3"}>
          <div className={"flex gap-1.5"}>
            <div className={"size-2.5 rounded-full bg-zinc-700"} />
            <div className={"size-2.5 rounded-full bg-zinc-700"} />
            <div className={"size-2.5 rounded-full bg-zinc-700"} />
          </div>
          <span className={"ml-1 font-mono text-xs text-zinc-500"}>sample.log</span>
        </div>
        {preview}
      </div>
    </div>
  );
}
