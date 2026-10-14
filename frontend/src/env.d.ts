/**
 * 构建期注入的全局常量（由 `vite.config.ts` 的 `define` 注入）。
 * ⚠️ **只在构建时存在**，本地 `vite dev` 也会走同一份 config，故都有值。
 */
declare const __BUILD_TIME__: string
declare const __COMMIT__: string
declare const __BRANCH__: string
