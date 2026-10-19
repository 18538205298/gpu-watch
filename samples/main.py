from __future__ import annotations

import json
import os
import shlex
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

ROOT = Path(__file__).resolve().parents[2]
load_dotenv(ROOT / ".env")
HOST = os.getenv("GPU_SSH_HOST", "")
PORT = os.getenv("GPU_SSH_PORT", "22")
USER = os.getenv("GPU_SSH_USER", "root")
KEY = os.getenv("GPU_SSH_KEY", "")
LOG_ROOTS = tuple(x.strip() for x in os.getenv("GPU_REMOTE_LOG_ROOTS", "").split(",") if x.strip())
STATIC = ROOT / "frontend" / "dist"
app = FastAPI(title="GPU Watch")


def ssh(script: str, timeout: int = 15) -> str:
    if not HOST:
        raise RuntimeError("GPU_SSH_HOST 未配置")
    cmd = ["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=8", "-o", "StrictHostKeyChecking=no"]
    if KEY:
        cmd += ["-i", KEY]
    # 作为一个完整的远程命令传给 ssh；否则 bash -lc 会把 script 的第一个词当作命令。
    cmd += ["-p", PORT, f"{USER}@{HOST}", "bash -lc " + shlex.quote(script)]
    result = subprocess.run(cmd, text=True, capture_output=True, timeout=timeout)
    if result.returncode:
        raise RuntimeError((result.stderr or result.stdout or f"ssh exit {result.returncode}").strip())
    return result.stdout


def run_json(script: str) -> dict:
    return json.loads(ssh(script))


@app.get("/api/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/api/overview")
def overview() -> dict:
    try:
        return {"ok": True, **run_json(r'''python3 - <<'PY'
import json, subprocess
ps=subprocess.run(["ps","-eo","pid,ppid,pgid,etime,%cpu,%mem,args","--sort=-%cpu"],capture_output=True,text=True).stdout
processes=[]
for line in ps.splitlines()[1:]:
 p=line.split(None,6)
 if len(p)==7: processes.append(dict(zip(["pid","ppid","pgid","etime","cpu","mem","command"],p)))
g=subprocess.run(["nvidia-smi","--query-gpu=index,name,utilization.gpu,memory.used,memory.total,temperature.gpu","--format=csv,noheader,nounits"],capture_output=True,text=True)
gpus=[]
for line in g.stdout.splitlines():
 p=[x.strip() for x in line.split(',')]
 if len(p)==6: gpus.append(dict(zip(["index","name","utilization","memory_used","memory_total","temperature"],p)))
a=subprocess.run(["nvidia-smi","--query-compute-apps=pid,process_name,used_memory","--format=csv,noheader,nounits"],capture_output=True,text=True)
apps=[]
for line in a.stdout.splitlines():
 p=[x.strip() for x in line.split(',')]
 if len(p)==3: apps.append(dict(zip(["pid","name","memory"],p)))
print(json.dumps({"gpus":gpus,"apps":apps,"processes":processes[:200]}))
PY''')}
    except Exception as exc:
        return {"ok": False, "error": str(exc), "gpus": [], "apps": [], "processes": []}


@app.get("/api/logs")
def logs() -> dict:
    try:
        roots=json.dumps(list(LOG_ROOTS))
        data=run_json(f'''python3 - <<'PY'
import json,os,time
roots=json.loads({roots!r}); out=[]
for root in roots:
 for base,dirs,files in os.walk(root):
  dirs[:]=[d for d in dirs if d not in {{".git","__pycache__"}}]
  for name in files:
   if name.endswith((".log",".jsonl")) or name in {{"END","summary.json"}}:
    path=os.path.join(base,name)
    try:
     st=os.stat(path)
     out.append({{"path":path,"size":st.st_size,"mtime":st.st_mtime,"mtime_iso":time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(st.st_mtime)),"age_seconds":round(time.time()-st.st_mtime,1)}})
    except OSError: pass
out.sort(key=lambda x:x["mtime"],reverse=True)
print(json.dumps(out[:200]))
PY''')
        return {"ok": True, "files": data}
    except Exception as exc:
        return {"ok": False, "error": str(exc), "files": []}


@app.get("/api/log")
def log(path: str = Query(...), lines: int = Query(300, ge=1, le=2000)) -> dict:
    if not LOG_ROOTS or not any(path == root or path.startswith(root.rstrip('/') + '/') for root in LOG_ROOTS):
        raise HTTPException(400, "日志路径不在配置目录内")
    try:
        content=ssh(f"tail -n {int(lines)} -- {shlex.quote(path)}")
        stamp = run_json(f'''python3 - <<'PY'
import json, os, time
p={path!r}
try:
 s=os.stat(p)
 print(json.dumps({{"mtime":s.st_mtime,"size":s.st_size,"age_seconds":round(time.time()-s.st_mtime,1)}}))
except OSError as e: print(json.dumps({{"error":str(e)}}))
PY''')
        return {"ok": True, "path": path, "content": content, "read_at": time.time(), **stamp}
    except Exception as exc:
        return {"ok": False, "path": path, "content": "", "error": str(exc)}


if STATIC.exists():
    app.mount("/", StaticFiles(directory=STATIC, html=True), name="static")
else:
    @app.get("/")
    def missing_frontend() -> FileResponse:
        raise HTTPException(503, "前端尚未构建，请运行 pnpm build")
