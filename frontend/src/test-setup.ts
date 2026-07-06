import '@testing-library/jest-dom'

/**
 * localStorage polyfill for the jsdom test environment.
 *
 * Under Node, a native `localStorage` global can shadow jsdom's implementation,
 * causing components/tests that rely on `window.localStorage` (e.g. auth token
 * persistence in AdminLogin / ProtectedRoute) to fail. We install a simple
 * in-memory Storage implementation on both `window` and `globalThis` so tests
 * get consistent, isolated storage regardless of the host environment.
 */
class MemoryStorage implements Storage {
  private store = new Map<string, string>()

  get length(): number {
    return this.store.size
  }

  clear(): void {
    this.store.clear()
  }

  getItem(key: string): string | null {
    return this.store.has(key) ? (this.store.get(key) as string) : null
  }

  key(index: number): string | null {
    return Array.from(this.store.keys())[index] ?? null
  }

  removeItem(key: string): void {
    this.store.delete(key)
  }

  setItem(key: string, value: string): void {
    this.store.set(key, String(value))
  }
}

const memoryStorage = new MemoryStorage()

Object.defineProperty(globalThis, 'localStorage', {
  configurable: true,
  value: memoryStorage,
})

if (typeof window !== 'undefined') {
  Object.defineProperty(window, 'localStorage', {
    configurable: true,
    value: memoryStorage,
  })
}
