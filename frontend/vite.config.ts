import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'
import { execSync } from 'node:child_process'

/**
 * 构建时注入版本信息（2026-10-09）。
 *
 * ⚠️ 为什么注入**构建时间**而不是 git hash / 手动维护的版本号：
 *   用户的诉求是「靠版本号判断 53 上是不是最新部署的」——
 *   那版本号必须**每次构建都变**，否则改了半天看到还是 1.0.0，等于没信息。
 *   构建时间由CI/本地构建那一刻决定，容器里显示的就是「这批代码何时构建的」，
 *   与「部署是否最新」一一对应。
 */
function buildInfo() {
  let commit = ''
  let branch = ''
  try {
    commit = execSync('git rev-parse --short HEAD', { stdio: ['ignore', 'pipe', 'ignore'] })
      .toString().trim()
    branch = execSync('git rev-parse --abbrev-ref HEAD', { stdio: ['ignore', 'pipe', 'ignore'] })
      .toString().trim()
  } catch {
    // 无 git 环境（如拷贝部署）→ 留空即可，不影响构建
  }
  const now = new Date()
  const pad = (n: number) => String(n).padStart(2, '0')
  // ⚠️⚠️ vite `define` 的值会被当**JS 表达式**解析，所以：
  //   ① 值里不能有空格（`"2026-10-09 00:02"` → Invalid characters after number）
  //   ② 不能用 `-` 分隔日期（`2026-10-09` 会被解析成**减法表达式**！）
  //   ③ 故必须 **JSON.stringify 成带引号的字符串字面量**，让 rolldown 当纯字符串替换。
  //   格式用 `T` 分隔以避免减号：20261009T0012，显示时再转成 "2026-10-09 00:12"。
  const stamp = `${now.getFullYear()}${pad(now.getMonth() + 1)}${pad(now.getDate())}`
    + `T${pad(now.getHours())}${pad(now.getMinutes())}`
  return {
    __BUILD_TIME__: JSON.stringify(stamp),
    __COMMIT__: JSON.stringify(commit || 'n/a'),
    __BRANCH__: JSON.stringify(branch || 'n/a'),
  }
}

// https://vite.dev/config/
export default defineConfig({
  plugins: [vue()],
  define: buildInfo(),
})
