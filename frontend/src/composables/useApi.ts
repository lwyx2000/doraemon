import { ref, type Ref } from 'vue'
import { api, ApiError } from '../utils/api'

/**
 * Composable to wrap real API calls with loading/error state.
 * Use this when the backend is reachable.
 */
export function useAsyncData<T>(fetcher: () => Promise<T>) {
  const data = ref<T | null>(null) as Ref<T | null>
  const loading = ref(true)
  const error = ref<string | null>(null)

  async function execute() {
    loading.value = true
    error.value = null
    try {
      data.value = await fetcher()
    } catch (e) {
      if (e instanceof ApiError) {
        error.value = e.message
      } else {
        error.value = String(e)
      }
    } finally {
      loading.value = false
    }
  }

  function refresh() {
    return execute()
  }

  return { data, loading, error, execute, refresh }
}

export { api, ApiError }
