"""Load optional .env without dependencies, launch server."""
import os
from pathlib import Path
for raw in (Path(__file__).parent/'.env').read_text(encoding='utf-8').splitlines() if (Path(__file__).parent/'.env').exists() else []:
    if not raw.strip() or raw.lstrip().startswith('#') or '=' not in raw:continue
    key,value=raw.split('=',1)
    key=key.strip()
    if key.isidentifier():os.environ.setdefault(key,value.strip().strip('"').strip("'"))
import server
server.connect().close()
try:server.create_backup()
except Exception as exc:print("[backup] 自动备份失败：",exc)
import threading
threading.Thread(target=server.scheduler,daemon=True).start()
print(f'AI Daily 已启动：http://{server.HOST}:{server.PORT}',flush=True)
from http.server import ThreadingHTTPServer
ThreadingHTTPServer((server.HOST,server.PORT),server.Handler).serve_forever()
