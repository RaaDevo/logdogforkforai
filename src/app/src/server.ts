import { Container, getContainer } from "@cloudflare/containers";
import handler from "@tanstack/react-start/server-entry";

export class Server extends Container<Env> {
  defaultPort = 3001;
  sleepAfter = "10m";
  envVars = Object.fromEntries(
    Object.entries(this.env).filter(([, value]) => typeof value === "string" && !!value),
  ) as Record<string, string>;
}

export default {
  fetch: async (request: Request, env: Env) => {
    const requestUrl = new URL(request.url);

    if (requestUrl.pathname === "/api" || requestUrl.pathname.startsWith("/api/")) {
      const apiUrl = new URL(request.url);
      apiUrl.pathname = apiUrl.pathname.replace(/^\/api/, "") || "/";

      const instance = getContainer(env.SERVER, "singleton");
      const response = await instance.fetch(new Request(apiUrl.toString(), request));
      return response;
    }

    return handler.fetch(request);
  },
};
