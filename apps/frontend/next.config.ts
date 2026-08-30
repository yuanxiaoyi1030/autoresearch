// Purpose: Proxies the browser to the v0.2 backend while enforcing loopback-only origins.
import type {NextConfig} from "next";

const apiOrigin = process.env.AUTORESEARCH_V0_2_API_ORIGIN ?? "http://127.0.0.1:8100";
const parsedOrigin = new URL(apiOrigin);
const loopbackHosts = new Set(["127.0.0.1", "localhost", "::1"]);
if (!loopbackHosts.has(parsedOrigin.hostname) || !["http:", "https:"].includes(parsedOrigin.protocol)) {
  throw new Error("AUTORESEARCH_V0_2_API_ORIGIN must use an HTTP(S) loopback host");
}
if (parsedOrigin.username || parsedOrigin.password || parsedOrigin.pathname !== "/" || parsedOrigin.search || parsedOrigin.hash) {
  throw new Error("AUTORESEARCH_V0_2_API_ORIGIN must be a credential-free origin without a path");
}

const nextConfig: NextConfig = {
  agentRules: false,
  poweredByHeader: false,
  turbopack: {root: process.cwd()},
  async headers() {
    return [{
      source: "/:path*",
      headers: [
        {key: "X-Content-Type-Options", value: "nosniff"},
        {key: "Referrer-Policy", value: "no-referrer"},
        {key: "X-Frame-Options", value: "DENY"},
        {key: "Permissions-Policy", value: "camera=(), microphone=(), geolocation=()"}
      ]
    }];
  },
  async rewrites() {
    return [
      {source: "/api/:path*", destination: `${apiOrigin}/api/:path*`},
      {source: "/health", destination: `${apiOrigin}/health`}
    ];
  }
};

export default nextConfig;
