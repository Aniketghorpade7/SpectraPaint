import { defineConfig } from 'vitest/config';

/**
 * A deliberately small suite. The two seams in docs/conventions.md §6 stay the project's testing
 * story; this covers only the shell logic that neither seam can reach and that is expensive to get
 * wrong — see docs/design-decisions.md §9d.
 */
export default defineConfig({
  test: {
    environment: 'node',
    include: ['apps/**/*.test.ts'],
  },
});
