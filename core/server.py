import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


class TranslationServer:
    def __init__(self, pipeline, host="127.0.0.1", port=0):
        # 初始化翻譯伺服器，只綁 127.0.0.1；port=0 表示自動配埠
        self.pipeline = pipeline
        self.host = host
        self.port = port
        self._httpd = None
        self._thread = None

    def start(self) -> int:
        # 在背景執行緒啟動 HTTP 伺服器，回傳實際埠號
        pipeline = self.pipeline

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                # 靜音伺服器日誌
                pass

            def do_POST(self):
                # 處理 POST 要求
                if self.path != "/translate":
                    # 只允許 /translate 端點
                    self.send_response(404)
                    self.end_headers()
                    return

                # 讀取 request body
                length = int(self.headers.get("Content-Length", 0))
                body = json.loads(self.rfile.read(length) or b"{}")
                texts = body.get("texts", [])

                # 呼叫 Pipeline 進行翻譯
                result = pipeline.translate(texts)

                # 回傳 JSON，確保 UTF-8 編碼且不逃脫非 ASCII 字元
                payload = json.dumps(
                    {"translations": result}, ensure_ascii=False).encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.send_header("Content-Length", str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)

        # 使用 ThreadingHTTPServer 以支援多個並發請求
        self._httpd = ThreadingHTTPServer((self.host, self.port), Handler)
        self.port = self._httpd.server_address[1]

        # 在背景執行緒啟動伺服器
        self._thread = threading.Thread(target=self._httpd.serve_forever, daemon=True)
        self._thread.start()

        return self.port

    def stop(self) -> None:
        # 停止伺服器
        if self._httpd:
            self._httpd.shutdown()
            self._httpd.server_close()
