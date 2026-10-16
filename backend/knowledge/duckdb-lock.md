# DuckDB 单写锁与任务触发铁律

## 单写锁

- DuckDB 全库单写锁：宿主机/`docker exec` 新进程均打不开（只读也 Conflicting lock）。
- **查数走 API 或 `docker cp`**，绝不开新进程直连文件。
- 任务触发只走 HTTP 端点（需登录）或重启 `_startup_backfill`，**绝不用 `docker exec` 起进程**。

##  schema 变更

- 给已有表加列必须显式 `ALTER TABLE ... ADD COLUMN`——`CREATE TABLE IF NOT EXISTS` 不补列，漏了会读写全 Binder Error。

## 双库分层

- jobs/registry.py = SQLite（任务注册表持久化）。
- `register_job` 的 `update_cols` 须排除 last_status/run_count/fail_count。

## 并发/超时

- `concurrent.futures`：`wait()` 返回 (done, not_done) 二元组。
- `with ThreadPoolExecutor` 的 `__exit__` = shutdown(wait=True)，白加超时——须显式 pool + try/finally `shutdown(wait=False, cancel_futures=True)`。
