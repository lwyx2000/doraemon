import { ref } from 'vue'

/**
 * Global sidebar state for responsive layout.
 * - On desktop (>= 1024px) sidebar is always expanded.
 * - On tablet/mobile (< 1024px) sidebar collapses into an overlay
 *   controlled by `mobileOpen`.
 */
const collapsed = ref(false)
const mobileOpen = ref(false)

export function useSidebar() {
  function toggleCollapsed() {
    collapsed.value = !collapsed.value
  }

  function openMobile() {
    mobileOpen.value = true
  }

  function closeMobile() {
    mobileOpen.value = false
  }

  function toggleMobile() {
    mobileOpen.value = !mobileOpen.value
  }

  return { collapsed, mobileOpen, toggleCollapsed, openMobile, closeMobile, toggleMobile }
}
