import { defineConfig } from 'vite';
import type { Plugin } from 'vite';
import react from '@vitejs/plugin-react';

// Keep in sync with DEFAULT_PUBLIC_API_BASE_URL in src/api.ts (that module reads
// import.meta.env at load time, so the config cannot import it).
const DEFAULT_API_BASE_URL = 'https://aurafi-api.onrender.com';

/** Origin of an absolute http(s) URL, or null (relative, empty or other scheme). */
function httpOrigin(value: string | undefined): string | null {
  if (!value?.trim()) return null;
  try {
    const url = new URL(value.trim());
    return url.protocol === 'https:' || url.protocol === 'http:' ? url.origin : null;
  } catch {
    return null;
  }
}

function escapeAttribute(value: string): string {
  return value.replace(/&/g, '&amp;').replace(/"/g, '&quot;').replace(/</g, '&lt;');
}

/**
 * Adds the Content-Security-Policy meta tag to the built index.html. Build only:
 * the dev server relies on inline scripts (React Fast Refresh) and websockets
 * that this policy would block. The app loads no external fonts, images or
 * scripts, so the only origin beyond 'self' is the API it calls. frame-ancestors
 * is ignored in a meta tag; render.yaml sends it as a response header instead.
 */
function contentSecurityPolicy(): Plugin {
  let policy = '';
  return {
    name: 'aurafi-content-security-policy',
    apply: 'build',
    configResolved(config) {
      // config.env holds the same VITE_* values the bundle is built with.
      const configured = typeof config.env.VITE_API_BASE_URL === 'string' ? config.env.VITE_API_BASE_URL : undefined;
      const apiOrigin = configured?.trim() ? httpOrigin(configured) : httpOrigin(DEFAULT_API_BASE_URL);
      policy = [
        "default-src 'self'",
        "script-src 'self'",
        "style-src 'self'",
        "img-src 'self' data: blob:",
        "font-src 'self'",
        `connect-src 'self'${apiOrigin ? ` ${apiOrigin}` : ''}`,
        "object-src 'none'",
        "base-uri 'self'",
        "form-action 'self'",
      ].join('; ');
    },
    transformIndexHtml: {
      order: 'post',
      handler(html) {
        const tag = `<meta http-equiv="Content-Security-Policy" content="${escapeAttribute(policy)}" />`;
        // Right after the charset declaration, ahead of every script and stylesheet.
        const charset = /<meta\s+charset=["'][^"']*["']\s*\/?>/i;
        return charset.test(html)
          ? html.replace(charset, (match) => `${match}\n    ${tag}`)
          : html.replace(/<head>/i, (match) => `${match}\n    ${tag}`);
      },
    },
  };
}

export default defineConfig({
  plugins: [react(), contentSecurityPolicy()],
  server: {
    host: 'localhost',
    port: 5173,
  },
  build: {
    outDir: 'dist',
    emptyOutDir: true,
  },
});
