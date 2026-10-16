# Git 分叉与 GitHub 中继推送

## 分叉现状（2026-10-14 核实）

- 本地与 53 均不能直连 github.com（HTTPS 超时/连接重置）。
- 53 → `ssh.github.com:443`（GitHub 443 SSH 备用通道）可达；53 的 `~/.ssh/github_deploy` key 已注册在 lwyx2000 账号。
- doraemon 本地与 53 历史上有过分叉：53 HEAD(50c5fcf) 曾领先 origin 7 个 commit（dividend 系列直接提交在 53）。两侧工作树内容一致时，部署走「scp 逐个传 + md5 双验 → 宿主 build → force-recreate → 三层 md5」。
- **Jenkins 流水线（rm -rf + git clone）会丢 53 本地 commit，慎用**。提交前先与用户确认 git 策略。

## 推送路线（GitHub 被封时）

1. 本地：`git bundle create <bundle> origin/master..HEAD`（bundle 与锁文件用 **Windows 原生路径**，MSYS /tmp 会失败）。
2. scp bundle 到 53。
3. 53 中继：
   ```bash
   export GIT_SSH_COMMAND="ssh -i ~/.ssh/github_deploy -o StrictHostKeyChecking=no"
   GH="ssh://git@ssh.github.com:443/lwyx2000/doraemon.git"
   git fetch "$GH" master:refs/remotes/ghproxy/master   # 拿前置 commit
   git fetch /tmp/<bundle> HEAD:refs/heads/_push_<sha>
   git push "$GH" refs/heads/_push_<sha>:refs/heads/master
   ```
4. 验证 `git ls-remote`，删临时 refs，本地 `git update-ref refs/remotes/origin/master <sha>` 对齐跟踪引用。
5. 非 FF（远端被他人推进）时先与用户确认，禁强推。
