# -*- coding: utf-8 -*-
"""
server.py - 대시보드 및 수동 실행 API 서버
============================================
파이썬 내장 라이브러리만을 사용하여 구현한 가벼운 웹서버입니다.
1) 정적 파일(index.html, logs/daily_log.json 등)을 서비스합니다.
2) /api/run 경로로 POST 요청이 오면 백그라운드에서 main.py를 실행하고 결과를 반환합니다.
"""

import http.server
import socketserver
import subprocess
import json
import os
import sys

PORT = 80

class DashboardHandler(http.server.SimpleHTTPRequestHandler):
    def do_POST(self):
        # 봇 실행 API 호출 처리
        if self.path == '/api/run':
            try:
                # subprocess를 사용해 main.py 실행
                result = subprocess.run(
                    [sys.executable, 'main.py'],
                    capture_output=True,
                    text=True,
                    timeout=300,
                    encoding='utf-8'
                )
                
                success = result.returncode == 0
                response_data = {
                    "success": success,
                    "stdout": result.stdout,
                    "stderr": result.stderr
                }
                
                self.send_response(200)
                self.send_header('Content-type', 'application/json; charset=utf-8')
                self.end_headers()
                self.wfile.write(json.dumps(response_data, ensure_ascii=False).encode('utf-8'))
            except Exception as e:
                self.send_response(500)
                self.send_header('Content-type', 'application/json; charset=utf-8')
                self.end_headers()
                self.wfile.write(json.dumps({"success": False, "error": str(e)}, ensure_ascii=False).encode('utf-8'))
        else:
            self.send_response(404)
            self.end_headers()

if __name__ == '__main__':
    # 스크립트가 존재하는 폴더로 경로 변경 (경로 에러 방지)
    script_dir = os.path.dirname(os.path.abspath(__file__))
    if script_dir:
        os.chdir(script_dir)
    
    # 포트 바인딩 중복 에러(Address already in use) 방지 설정
    socketserver.TCPServer.allow_reuse_address = True
    
    with socketserver.TCPServer(("", PORT), DashboardHandler) as httpd:
        print(f"Serving TQQQ Bot Dashboard on port {PORT}...")
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            print("\nServer stopped.")
            sys.exit(0)
