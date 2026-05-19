import { TanStackDevtools } from "@tanstack/react-devtools";
import { createRootRoute, HeadContent, Scripts } from "@tanstack/react-router";
import { TanStackRouterDevtoolsPanel } from "@tanstack/react-router-devtools";
import AppProvider from "#/components/app-provider";
import ErrorOccurred from "#/components/error-occurred";
import Loading from "#/components/loading";
import NotFound from "#/components/not-found";
import { ScrollArea } from "#/components/ui/scroll-area";
import appCss from "../styles.css?url";

export const Route = createRootRoute({
  head: () => ({
    meta: [
      {
        charSet: "utf-8",
      },
      {
        name: "viewport",
        content: "width=device-width, initial-scale=1",
      },
      {
        title: "Logdog",
      },
    ],
    links: [
      {
        rel: "icon",
        href: "/icon.png",
        media: "(prefers-color-scheme: light)",
      },
      {
        rel: "icon",
        href: "/icon-dark.png",
        media: "(prefers-color-scheme: dark)",
      },
      {
        rel: "stylesheet",
        href: appCss,
      },
    ],
  }),
  shellComponent: ({ children }) => (
    <html lang={"en"} suppressHydrationWarning>
      <head>
        <HeadContent />
      </head>
      <body className={"antialiased"}>
        <AppProvider>
          <ScrollArea className={"h-dvh w-dvw"}>{children}</ScrollArea>
          <TanStackDevtools
            config={{
              position: "bottom-right",
            }}
            plugins={[
              {
                name: "Tanstack Router",
                render: <TanStackRouterDevtoolsPanel />,
              },
            ]}
          />
        </AppProvider>
        <Scripts />
      </body>
    </html>
  ),
  pendingComponent: () => (
    <main className={"h-dvh"}>
      <Loading />
    </main>
  ),
  errorComponent: ({ error }) => (
    <main className={"h-dvh"}>
      <ErrorOccurred error={error} />
    </main>
  ),
  notFoundComponent: () => (
    <main className={"h-dvh"}>
      <NotFound />
    </main>
  ),
});
