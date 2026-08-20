import js from '@eslint/js';
import tseslint from 'typescript-eslint';
import reactHooks from 'eslint-plugin-react-hooks';
import globals from 'globals';

export default tseslint.config(
  // `.venv` is on this list because PyTorch ships JavaScript. Installing the service's `export`
  // dependency group puts torch/utils/model_dump/code.js inside the virtualenv, and without this
  // `npm run lint` reports eighty-odd errors in somebody else's minified code. CI happens not to
  // notice — it lints before it installs Python — which is exactly why it is worth pinning here
  // rather than leaving for the next person to rediscover.
  { ignores: ['**/dist/**', '**/out/**', '**/node_modules/**', '**/.venv/**'] },
  js.configs.recommended,
  ...tseslint.configs.recommended,
  {
    files: ['apps/ui/**/*.{ts,tsx}'],
    languageOptions: { globals: globals.browser },
    plugins: { 'react-hooks': reactHooks },
    rules: reactHooks.configs.recommended.rules,
  },
  {
    files: ['apps/desktop/**/*.ts'],
    languageOptions: { globals: globals.node },
  },
);
