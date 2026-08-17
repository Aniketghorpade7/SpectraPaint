import { defineConfig, type Plugin } from 'vite';
import react from '@vitejs/plugin-react';

/**
 * Content-Security-Policy, injected into index.html.
 *
 * `connect-src 'none'` in the shipped build is the interesting line: the renderer has no business
 * making network requests of its own, because everything goes through the preload bridge and the
 * main process. It turns "the renderer cannot reach arbitrary hosts" from a design intention into
 * something the browser enforces.
 *
 * Development needs a looser policy — the dev server's HMR socket and its injected inline
 * scripts — so the two are kept separate rather than shipping the loose one.
 */
const PRODUCTION_CSP = [
  "default-src 'none'",
  "script-src 'self'",
  "style-src 'self' 'unsafe-inline'",
  "img-src 'self' data: blob:",
  "font-src 'self'",
  "connect-src 'none'",
  "base-uri 'none'",
  "form-action 'none'",
  "frame-ancestors 'none'",
].join('; ');

const DEVELOPMENT_CSP = [
  "default-src 'none'",
  "script-src 'self' 'unsafe-inline'",
  "style-src 'self' 'unsafe-inline'",
  "img-src 'self' data: blob:",
  "font-src 'self'",
  "connect-src 'self' ws://localhost:5273",
  "base-uri 'none'",
  "form-action 'none'",
  "frame-ancestors 'none'",
].join('; ');

function contentSecurityPolicy(isDevelopment: boolean): Plugin {
  return {
    name: 'spectrapaint-csp',
    transformIndexHtml(html) {
      const policy = isDevelopment ? DEVELOPMENT_CSP : PRODUCTION_CSP;
      return html.replace(
        '<!-- CSP -->',
        `<meta http-equiv="Content-Security-Policy" content="${policy}" />`,
      );
    },
  };
}

export default defineConfig(({ command }) => ({
  plugins: [react(), contentSecurityPolicy(command === 'serve')],
  // Electron loads the built UI from the filesystem, so asset URLs must be relative.
  base: './',
  server: { port: 5273, strictPort: true },
  build: { outDir: 'dist', emptyOutDir: true },
}));
