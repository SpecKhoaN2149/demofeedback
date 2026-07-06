import { defineConfig, mergeConfig } from 'vitest/config'
import viteConfig from './vite.config'

// Vitest configuration is kept separate from vite.config.ts because vitest@2.x
// depends on vite@5 while this project builds with vite@6. Sharing a single
// config file forces the two incompatible Vite type universes together and
// produces spurious `test`/`plugins` type errors under `tsc`. Merging the
// Vite config here keeps the app build (tsc + vite build) clean while giving
// the test runner the same plugins (react) plus the vitest `test` options.
export default mergeConfig(
  viteConfig,
  defineConfig({
    test: {
      environment: 'jsdom',
      globals: true,
      setupFiles: ['./src/test-setup.ts'],
    },
  })
)
