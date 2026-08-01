import { ref, onMounted, type Ref } from 'vue'
import { api, ApiError } from '../utils/api'

/**
 * Composable to wrap real API calls with loading/error state.
 * Use this when the backend is reachable.
 */
export function useAsyncData<T>(fetcher: () => Promise<T>) {
  const data = ref<T | null>(null) as Ref<T | null>
  const loading = ref(false)
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

  return { data, loading, error, execute }
}

/**
 * Mock async composable for development/demo mode.
 * Simulates async fetch on mount so pages can show loading skeletons
 * and integrate with the shared <LoadingState> component.
 *
 * @param mockData The mock payload to deliver after the simulated delay.
 * @param delay Simulated network latency in ms (default 400ms).
 */
export function useAsyncMock<T>(mockData: T, delay = 400) {
  const data = ref<T | null>(null) as Ref<T | null>
  const loading = ref(true)
  const error = ref<string | null>(null)

  async function execute() {
    loading.value = true
    error.value = null
    // Simulate async fetch with possible (rare) failure
    await new Promise(resolve => setTimeout(resolve, delay))
    data.value = mockData
    loading.value = false
  }

  onMounted(execute)

  /** Manual refresh — resets loading state and re-fetches. */
  function refresh() {
    return execute()
  }

  return { data, loading, error, execute, refresh }
}

export { api, ApiError }
