"""Serve the corridor comparison map locally and open it in the browser.

    python serve.py            # picks a free port from 8785 upwards
    python serve.py 9000       # or ask for a specific one

Why not plain `python -m http.server`: on machines running Docker/WSL, another
service can hold the same port on IPv6, and browsers resolve "localhost" to
IPv6 first - so http://localhost:PORT silently opens the wrong app. This picks
a port that is free on both IPv4 and IPv6 and opens http://127.0.0.1:PORT.
"""
import http.server
import os
import socket
import sys
import threading
import webbrowser

HERE = os.path.dirname(os.path.abspath(__file__))


def free_everywhere(port):
    for fam, addr in ((socket.AF_INET, "127.0.0.1"), (socket.AF_INET6, "::1"),
                      (socket.AF_INET6, "::")):
        s = socket.socket(fam, socket.SOCK_STREAM)
        try:
            s.bind((addr, port))
        except OSError:
            return False
        finally:
            s.close()
    return True


def main():
    want = int(sys.argv[1]) if len(sys.argv) > 1 else None
    port = want if want and free_everywhere(want) else next(
        p for p in range(8785, 8900) if free_everywhere(p))
    if want and port != want:
        print(f"port {want} is taken (possibly on IPv6); using {port} instead")

    class Handler(http.server.SimpleHTTPRequestHandler):
        # always revalidate, so an edited module is never served stale
        def end_headers(self):
            self.send_header("Cache-Control", "no-cache")
            super().end_headers()

        def log_message(self, *args):
            pass

    handler = lambda *a, **k: Handler(*a, directory=HERE, **k)
    httpd = http.server.ThreadingHTTPServer(("127.0.0.1", port), handler)
    url = f"http://127.0.0.1:{port}/"
    print(f"Göteborg corridor comparison: {url}   (Ctrl+C to stop)")
    threading.Timer(0.6, lambda: webbrowser.open(url)).start()
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nstopped")


if __name__ == "__main__":
    main()
