import http.client
import importlib.util
from pathlib import Path
import threading
import unittest
from http.server import ThreadingHTTPServer

spec=importlib.util.spec_from_file_location("public_redirect",Path(__file__).parent/"deploy/hostinger/public-redirect.py")
redirect=importlib.util.module_from_spec(spec)
spec.loader.exec_module(redirect)


class PublicRedirectTest(unittest.TestCase):
    def setUp(self):
        self.server=ThreadingHTTPServer(("127.0.0.1",0),redirect.RedirectHandler)
        self.thread=threading.Thread(target=self.server.serve_forever,daemon=True)
        self.thread.start()
        self.addCleanup(self.server.server_close)
        self.addCleanup(self.server.shutdown)

    def request(self,method,path):
        conn=http.client.HTTPConnection("127.0.0.1",self.server.server_port,timeout=3)
        self.addCleanup(conn.close)
        conn.request(method,path)
        response=conn.getresponse()
        return response.status,dict(response.getheaders()),response.read()

    def test_public_pages_redirect_temporarily_without_leaking_query_or_path(self):
        for method in ("GET","HEAD"):
            status,headers,body=self.request(method,"/compte?code=private&next=https://evil.example")
            self.assertEqual(status,302)
            self.assertEqual(headers["Location"],"https://rdv.checkupauto.fr/")
            self.assertEqual(headers["Cache-Control"],"no-store")
            self.assertEqual(headers["Referrer-Policy"],"no-referrer")
            self.assertEqual(body,b"")

    def test_sensitive_paths_and_mutations_are_never_forwarded(self):
        for method,path in (("GET","/auth/customer/google/callback?code=private"),
                            ("GET","/api/customer/me"),("GET","/payment/callback"),
                            ("POST","/")):
            with self.subTest(method=method,path=path):
                status,headers,_=self.request(method,path)
                self.assertEqual(status,404)
                self.assertNotIn("Location",headers)


if __name__=="__main__":
    unittest.main()
