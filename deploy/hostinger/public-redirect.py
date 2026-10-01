"""Temporary public facade: keep visitors on the existing Mercure planner."""
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

TARGET = "https://rdv.checkupauto.fr/"


class RedirectHandler(BaseHTTPRequestHandler):
    # Never send account callbacks, payment callbacks, query strings or paths
    # to the old planner. A fixed destination also prevents open redirects.
    def respond(self, head=False):
        path = self.path.split("?", 1)[0]
        status = 404 if path.startswith(("/api/", "/auth/", "/admin/", "/payment/", "/app/claim")) else 302
        self.send_response(status)
        if status == 302:
            self.send_header("Location", TARGET)
        self.send_header("Cache-Control", "no-store")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Robots-Tag", "noindex, nofollow")
        self.send_header("Content-Length", "0")
        self.end_headers()

    def do_GET(self):
        self.respond()

    def do_HEAD(self):
        self.respond(head=True)

    def do_POST(self):
        self.send_response(404)
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", "0")
        self.end_headers()

    def log_message(self, format, *args):
        # Request URLs can contain OAuth/payment codes; do not log them.
        pass


if __name__ == "__main__":
    ThreadingHTTPServer(("0.0.0.0", 8080), RedirectHandler).serve_forever()
