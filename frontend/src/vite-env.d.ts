/// <reference types="vite/client" />

interface ImportMetaEnv {
  // JSON string of left-nav tab visibility, injected from conf/config.yml
  // by vite.config.ts. See src/App.tsx.
  readonly VITE_TAB_VISIBILITY?: string;
}

interface ImportMeta {
  readonly env: ImportMetaEnv;
}
