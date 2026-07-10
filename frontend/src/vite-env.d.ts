/// <reference types="vite/client" />

// Bundled data assets (e.g. the us-atlas topojson) are imported for their
// runtime value only; typed as `unknown` to avoid heavy inference over large
// JSON and cast at the use site.
declare module '*.json' {
  const value: unknown
  export default value
}
