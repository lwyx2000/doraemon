# 部署与构建坑位

## doraemon 部署流程

1. 只 `up --force-recreate` 不改代码 → 必须先 `build`。
2. frontend 改完须 `docker compose build frontend`（dist 进镜像）。
3. **53 宿主构建前端须 `nvm use 20`（v20.19.0）后 `npm run build`**（vite 8 要求）。
4. 交付验三层 md5：本地 == 53 宿主 == 容器。
5. scp 多文件可能静默漏传 → 逐个传 + 校验和。

## 构建坑

- `dist/assets` 若属 root（历史 root 构建残留）→ emptyDir EACCES：先 `sudo rm -rf dist` 再 build。
- 重启后 30–60s 内 curl API 会 502（lifespan 启动任务多），非故障。
- 路由同名副本：真正生效 `backend/routers/*.py`；`backend/dividend_router.py` 是死副本（勿改）。
- vite `define` 注入值是 JS 片段非字符串：正解 `JSON.stringify('...')` + 前端正则还原。

## 53 服务器通用

- Docker 走 docker.1ms.run（公共 mirror 被墙）。
- **禁重启 docker daemon**（18+ 容器长 Up）。
- **禁 `docker exec -i ... cat > file`**（SSH 断 → stdin 永不 EOF → 满核）；脚本先落宿主再 cp，或 `docker exec python -c`。
- 查负载高：`ps -eo pid,user,pcpu,etime,args --sort=-pcpu`；判存活看 `uptime` + `top -bn1`。
- 端口：doraemon backend :9080、frontend :9080(宿主 9080→容器 80)、akshare :8000(nginx:8085) 等。
