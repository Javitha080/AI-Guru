import nextConfig from "eslint-config-next";
import i18nPlugin from "./eslint/i18n-plugin.mjs";

// React Compiler-era hooks rules (eslint-plugin-react-hooks v6+) flag the
// existing data-fetching-in-effect / imperative patterns across the app. The
// codebase has not adopted the React Compiler yet, so the compiler analysis
// family is kept as warnings during migration (same pattern as
// i18n/no-literal-ui-text below). The classic rules rules-of-hooks and
// exhaustive-deps stay enforced. CI treats ESLint errors as blocking, so this
// override lives on the same config entry that eslint-config-next uses to
// register the react-hooks plugin.
const REACT_COMPILER_RULES = [
  "react-hooks/set-state-in-effect",
  "react-hooks/set-state-in-render",
  "react-hooks/purity",
  "react-hooks/refs",
  "react-hooks/immutability",
  "react-hooks/static-components",
  "react-hooks/preserve-manual-memoization",
  "react-hooks/use-memo",
  "react-hooks/globals",
  "react-hooks/error-boundaries",
  "react-hooks/config",
  "react-hooks/gating",
];

const nextBase = {
  ...nextConfig[0],
  rules: {
    ...nextConfig[0].rules,
    ...Object.fromEntries(REACT_COMPILER_RULES.map((rule) => [rule, "warn"])),
  },
};

const config = [
  nextBase,
  ...nextConfig.slice(1),
  {
    files: ["app/**/*.{ts,tsx}", "components/**/*.{ts,tsx}"],
    plugins: {
      i18n: i18nPlugin,
    },
    rules: {
      // During migration keep as warning; change to "error" once phase2/3 complete.
      "i18n/no-literal-ui-text": "warn",
    },
  },
  {
    ignores: [
      "node_modules/**",
      ".next/**",
      ".next-deeptutor/**",
      "dist/**",
      "out/**",
      "public/**",
    ],
  },
];

export default config;
