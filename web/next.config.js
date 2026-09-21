/** @type {import('next').NextConfig} */

const fs = require("fs");
const os = require("os");
const path = require("path");

function readJsonFile(filePath) {
  try {
    return JSON.parse(fs.readFileSync(filePath, "utf8"));
  } catch {
    return {};
  }
}

function firstNonEmpty(...values) {
  for (const value of values) {
    if (value !== undefined && value !== null && String(value).trim() !== "") {
      return String(value).trim();
    }
  }
  return "";
}

function normalizeBoolean(value) {
  if (value === "__NEXT_PUBLIC_AUTH_ENABLED_PLACEHOLDER__") {
    return value;
  }
  return ["1", "true", "yes", "on"].includes(String(value).trim().toLowerCase())
    ? "true"
    : "false";
}

/** This machine's non-loopback IPv4 addresses — the hosts `next dev` prints
 *  as "Network:", i.e. the ones a phone on the same WiFi actually types. */
function localNetworkHosts() {
  const hosts = [];
  for (const addresses of Object.values(os.networkInterfaces())) {
    for (const address of addresses ?? []) {
      if (address.family === "IPv4" && !address.internal) {
        hosts.push(address.address);
      }
    }
  }
  return hosts;
}

/** Extra dev hosts via ALLOWED_DEV_ORIGINS env or system.json
 *  `allowed_dev_origins` (comma/space-separated). Accepts bare hostnames,
 *  wildcards (`*.trycloudflare.com`), or full origins (`https://host`) —
 *  origins are reduced to hostnames to match what Next expects. */
function extraDevHosts(systemSettings) {
  const raw = firstNonEmpty(
    process.env.ALLOWED_DEV_ORIGINS,
    systemSettings && systemSettings.allowed_dev_origins,
    "",
  );
  return String(raw)
    .split(/[\s,]+/)
    .map((entry) => entry.trim())
    .filter(Boolean)
    .map((entry) => {
      try {
        if (/^https?:\/\//i.test(entry)) {
          return new URL(entry).hostname;
        }
      } catch {
        // Fall through and keep the raw entry.
      }
      return entry;
    })
    .filter(Boolean);
}

const SETTINGS_DIR = path.resolve(__dirname, "..", "data", "user", "settings");
const SYSTEM_SETTINGS = readJsonFile(path.join(SETTINGS_DIR, "system.json"));
const AUTH_SETTINGS = readJsonFile(path.join(SETTINGS_DIR, "auth.json"));
const BACKEND_PORT = firstNonEmpty(
  process.env.BACKEND_PORT,
  SYSTEM_SETTINGS.backend_port,
  "8001",
);

// Use data/user/settings as the frontend source of truth. Environment values
// remain explicit deployment overrides for Docker/CI.
const NEXT_PUBLIC_API_BASE = firstNonEmpty(
  process.env.NEXT_PUBLIC_API_BASE_EXTERNAL,
  SYSTEM_SETTINGS.next_public_api_base_external,
  process.env.NEXT_PUBLIC_API_BASE,
  SYSTEM_SETTINGS.next_public_api_base,
  `http://localhost:${BACKEND_PORT}`,
);

const NEXT_PUBLIC_AUTH_ENABLED = normalizeBoolean(
  firstNonEmpty(
    process.env.NEXT_PUBLIC_AUTH_ENABLED,
    process.env.AUTH_ENABLED,
    AUTH_SETTINGS.enabled,
    "false",
  ),
);

process.env.NEXT_PUBLIC_API_BASE = NEXT_PUBLIC_API_BASE;
process.env.NEXT_PUBLIC_AUTH_ENABLED = NEXT_PUBLIC_AUTH_ENABLED;

// Resolve the build-time application version from the single source of
// truth at ``deeptutor/__version__.py``. The Python file is parsed with a
// small regex so the JS build does not need to execute Python.
const APP_VERSION = (() => {
  try {
    const text = fs.readFileSync(
      path.resolve(__dirname, "..", "deeptutor", "__version__.py"),
      "utf8",
    );
    const match = text.match(/__version__\s*=\s*["']([^"']+)["']/);
    if (match) return match[1];
  } catch {}
  return "";
})();

const nextConfig = {
  // Keep the production build used by `deeptutor start` separate from the
  // `.next` development cache used by the explicit `deeptutor start --dev`.
  // Without separate directories either command can invalidate the other
  // process while it is running.
  distDir: process.env.DEEPTUTOR_NEXT_DIST_DIR || ".next",

  // Expose the build-time version to the browser so the sidebar badge
  // can compare it against GitHub's latest release.
  env: {
    NEXT_PUBLIC_APP_VERSION: APP_VERSION,
    NEXT_PUBLIC_API_BASE,
    NEXT_PUBLIC_AUTH_ENABLED,
  },

  // Standalone output: self-contained server.js + minimal node_modules
  // This eliminates the need to copy the full node_modules into Docker production images
  output: "standalone",

  // web/proxy.ts (the Next.js middleware) forwards /api/* and /ws/* to the
  // backend by buffering and re-issuing the request. Next caps the buffered
  // request body at 10MB by default, but the backend accepts uploads up to
  // 200MB (DocumentValidator.MAX_FILE_SIZE). Raise the proxy cap to match (plus
  // multipart overhead headroom) so knowledge-base document uploads aren't
  // silently truncated when they pass through the proxy.
  experimental: {
    proxyClientMaxBodySize: 210 * 1024 * 1024,
  },

  // Move dev indicator to bottom-right corner
  devIndicators: {
    position: "bottom-right",
  },

  // Transpile mermaid and related packages for proper ESM handling
  transpilePackages: ["mermaid"],

  // Next.js 16 blocks cross-origin access to /_next/* dev resources (HMR
  // WebSocket, fonts, dev-only scripts) unless the request host is on this
  // allow-list. Without it, browsing http://127.0.0.1:<port>/ against a dev
  // server bound to localhost silently breaks client hydration — the SSR HTML
  // renders, but no React event handlers or effects ever attach.
  // The same applies to a phone or tablet on the LAN: `next dev` advertises a
  // "Network: http://<lan-ip>:<port>" address, and that host has to be on the
  // list too or the device gets the identical hydrated-nothing shell — a
  // top bar with an empty page under it. Detected rather than hard-coded so it
  // follows whatever network this machine is on. Dev-only: `allowedDevOrigins`
  // has no effect on `next build`/`next start`, and anyone who can reach the
  // dev server on these addresses is already inside the LAN.
  // Tunnel hosts (Cloudflare Quick Tunnel rotates `*.trycloudflare.com` on
  // every restart, ngrok similar) must be covered by wildcards — listing a
  // single tunnel hostname goes stale on the next reconnect. Extra hosts can
  // also be injected without editing this file via ALLOWED_DEV_ORIGINS.
  allowedDevOrigins: [
    "localhost",
    "127.0.0.1",
    ...localNetworkHosts(),
    "*.trycloudflare.com",
    "*.cfargotunnel.com",
    "*.ngrok-free.app",
    "*.ngrok.io",
    "*.loca.lt",
    ...extraDevHosts(SYSTEM_SETTINGS),
  ],

  // Turbopack configuration (used when running `npm run dev:turbo`)
  turbopack: {
    resolveAlias: {
      // Fix for mermaid's cytoscape dependency - use CJS version
      cytoscape: "cytoscape/dist/cytoscape.cjs.js",
    },
  },

  // Webpack configuration (used for production builds - next build)
  webpack: (config) => {
    const path = require("path");
    config.resolve.alias = {
      ...config.resolve.alias,
      cytoscape: path.resolve(
        __dirname,
        "node_modules/cytoscape/dist/cytoscape.cjs.js",
      ),
    };
    // @mediapipe/tasks-vision's vision_bundle.mjs uses a dynamic
    // require(expression) for its WASM loader. Harmless at runtime but
    // webpack logs "Critical dependency: the request of a dependency is an
    // expression" on every page compile. Silence only that upstream warning.
    config.ignoreWarnings = [
      ...(config.ignoreWarnings ?? []),
      {
        module: /vision_bundle\.mjs/,
        message: /Critical dependency/,
      },
      {
        module: /@mediapipe\/tasks-vision/,
        message: /Critical dependency/,
      },
    ];
    return config;
  },
};

module.exports = nextConfig;
