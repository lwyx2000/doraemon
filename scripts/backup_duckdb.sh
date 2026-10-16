#!/bin/bash
# ============================================================
# doraemon DuckDB 每日备份（2026-10-16 重写）
# 背景：原脚本被 Jenkins doraemon-deploy #38（rm -rf+clone）冲掉；
#       本版放 /home/sos/scripts/（Jenkins blast 半径外），
#       apps/doraemon/scripts/ 下留 symlink 兼容旧路径。
# 机制：
#   1) docker volume inspect 定位卷（返回的 Mountpoint 已含 /_data，勿再拼）
#   2) sudo cp -p 拷贝 quantterminal.duckdb(+wal) 与 biz sqlite(+wal/shm)
#   3) 冒烟：docker cp 进 doraemon_backend 容器 /tmp，duckdb 读写打开
#      （触发 WAL 重放）后 COUNT(base_sw_sector_daily/base_fund_nav)；
#      sqlite 副本 PRAGMA integrity_check。只动 /tmp 副本，不碰线上库
#      （线上库单写锁，新进程开不了也不该开）。
#   4) 7 天滚动清理。
# 恢复姿势：停 doraemon_backend -> 把备份目录内 quantterminal.duckdb*
#   覆盖回卷 -> 起容器（DuckDB/SQLite 自动重放 WAL）。
# 注意：卷目录 root 属主，sos 穿不透，目录检查与拷贝都要 sudo。
# ============================================================
set -u
export PATH=/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin
BASE=/home/sos/backups/duckdb_daily
LOG=$BASE/backup.log
VOL=doraemon_doraemon_data
CONTAINER=doraemon_backend
TS=$(date +%Y%m%d_%H%M%S)
DEST=$BASE/$TS

log(){ echo "[$(date '+%F %T')] $*" >> "$LOG"; }
mkdir -p "$BASE"

# 1) 定位卷（Mountpoint 即 _data 目录本身）
SRC=$(docker volume inspect "$VOL" --format '{{.Mountpoint}}' 2>/dev/null)
if [ -z "$SRC" ] || ! sudo test -d "$SRC"; then log "FAIL volume $VOL not found"; exit 1; fi

# 2) 拷贝（卷 root 属主，sudo 免密；cp -p 保留 mtime）
mkdir -p "$DEST" || { log "FAIL mkdir $DEST"; exit 1; }
sudo cp -p "$SRC/quantterminal.duckdb" "$DEST/" || { log "FAIL cp duckdb"; exit 1; }
WALSZ=0
if sudo test -f "$SRC/quantterminal.duckdb.wal"; then
  sudo cp -p "$SRC/quantterminal.duckdb.wal" "$DEST/"
  WALSZ=$(sudo stat -c%s "$SRC/quantterminal.duckdb.wal")
fi
# biz sqlite（小而珍贵的业务库，一并 daily）
SQLSZ=0
if sudo test -f "$SRC/quantterminal_biz.sqlite"; then
  sudo cp -p "$SRC/quantterminal_biz.sqlite" "$DEST/"
  for ext in -wal -shm; do
    sudo test -f "$SRC/quantterminal_biz.sqlite$ext" && sudo cp -p "$SRC/quantterminal_biz.sqlite$ext" "$DEST/"
  done
  SQLSZ=$(sudo stat -c%s "$SRC/quantterminal_biz.sqlite")
fi
DBSZ=$(du -sh "$DEST" | cut -f1)

# 3) 冒烟验证
VERIFY=SKIPPED; SW=-; NAV=-; SQ=SKIPPED
if docker ps --format '{{.Names}}' | grep -qx "$CONTAINER"; then
  docker cp "$DEST" "$CONTAINER:/tmp/bkv_$TS" >/dev/null 2>&1
  OUT=$(docker exec "$CONTAINER" python -c "
import duckdb
con = duckdb.connect('/tmp/bkv_$TS/quantterminal.duckdb')
sw = con.execute('SELECT COUNT(*) FROM base_sw_sector_daily').fetchone()[0]
nav = con.execute('SELECT COUNT(*) FROM base_fund_nav').fetchone()[0]
con.close()
print(sw, nav)
" 2>/dev/null)
  docker exec "$CONTAINER" rm -rf "/tmp/bkv_$TS" >/dev/null 2>&1
  if [ -n "$OUT" ]; then
    SW=${OUT%% *}; NAV=${OUT##* }
    if [ "${SW:-0}" -gt 0 ] 2>/dev/null; then VERIFY=OK; else VERIFY=FAIL; fi
  else VERIFY=FAIL; fi
fi
# sqlite 完整性（宿主机 python3 自带 sqlite3，不依赖容器）
if [ -f "$DEST/quantterminal_biz.sqlite" ]; then
  if python3 -c "
import sqlite3
con = sqlite3.connect('$DEST/quantterminal_biz.sqlite')
r = con.execute('PRAGMA integrity_check').fetchone()[0]
con.close()
exit(0 if r == 'ok' else 1)
" 2>/dev/null; then SQ=OK; else SQ=FAIL; fi
fi

if [ "$VERIFY" = FAIL ] || [ "$SQ" = FAIL ]; then
  log "FAIL $TS size=$DBSZ wal=${WALSZ}B verify=$VERIFY sw=$SW nav=$NAV sq=$SQ"
  exit 1
fi
log "OK $TS size=$DBSZ wal=${WALSZ}B verify=$VERIFY sw=$SW nav=$NAV sq=$SQ sqlite=${SQLSZ}B"

# 4) 7 天滚动
find "$BASE" -maxdepth 1 -type d -name '20*' -mtime +7 -exec rm -rf {} + 2>/dev/null
log "retention done, dirs=$(ls -d $BASE/20* 2>/dev/null | wc -l)"
exit 0
