import { ref } from 'vue'

const isDark = ref(false)

export function useDarkMode() {
  function toggle() {
    isDark.value = !isDark.value
    document.documentElement.classList.toggle('dark', isDark.value)
  }

  function enable() {
    isDark.value = true
    document.documentElement.classList.add('dark')
  }

  function disable() {
    isDark.value = false
    document.documentElement.classList.remove('dark')
  }

  return { isDark, toggle, enable, disable }
}
