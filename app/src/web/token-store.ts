// This phone's device token (#303), kept in IndexedDB (never localStorage, which any script on the page
// reads synchronously and some browsers clear first). Without IndexedDB it lives for the page only.

export interface TokenStore {
  get(): Promise<string | null>
  set(token: string): Promise<void>
  clear(): Promise<void>
}

const DB = 'door'
const STORE = 'device'
const KEY = 'token'

function open(): Promise<IDBDatabase> {
  return new Promise((resolve, reject) => {
    const req = indexedDB.open(DB, 1)
    req.onupgradeneeded = () => req.result.createObjectStore(STORE)
    req.onsuccess = () => resolve(req.result)
    req.onerror = () => reject(req.error)
  })
}

function run<T>(mode: IDBTransactionMode, act: (s: IDBObjectStore) => IDBRequest<T>): Promise<T> {
  return open().then(
    (db) =>
      new Promise<T>((resolve, reject) => {
        const req = act(db.transaction(STORE, mode).objectStore(STORE))
        req.onsuccess = () => resolve(req.result)
        req.onerror = () => reject(req.error)
      }),
  )
}

export function indexedDbStore(): TokenStore {
  if (typeof indexedDB === 'undefined') {
    let memory: string | null = null
    return {
      get: async () => memory,
      set: async (t) => {
        memory = t
      },
      clear: async () => {
        memory = null
      },
    }
  }
  return {
    get: async () => {
      try {
        const v = await run<unknown>('readonly', (s) => s.get(KEY))
        return typeof v === 'string' ? v : null
      } catch {
        return null
      }
    },
    set: async (t) => {
      await run('readwrite', (s) => s.put(t, KEY))
    },
    clear: async () => {
      await run('readwrite', (s) => s.delete(KEY)).catch(() => undefined)
    },
  }
}
