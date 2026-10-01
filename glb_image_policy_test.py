"""Protect the GLB image policy without expanding executable source directives."""
import ast
from pathlib import Path
import unittest
class GLBImagePolicyTest(unittest.TestCase):
    def policy(self):
        tree=ast.parse(Path(__file__).with_name("admin_server.py").read_text(encoding="utf-8"))
        calls=[n for n in ast.walk(tree) if isinstance(n,ast.Call)
          and isinstance(n.func,ast.Attribute) and n.func.attr=="send_header"
          and len(n.args)>=2 and isinstance(n.args[0],ast.Constant)
          and n.args[0].value=="Content-Security-Policy"]
        self.assertEqual(len(calls),1)
        expression=ast.Expression(calls[0].args[1])
        value=eval(compile(expression,"response-image-policy","eval"),{"__builtins__":{}},{"nonce_src":" 'nonce-fixture'"})
        return {parts[0]:parts[1:] for segment in value.split(";") if (parts:=segment.split())}
    def test_embedded_glb_texture_is_allowed(self):
        self.assertIn("blob:",self.policy()["img-src"])
    def test_blob_is_not_an_executable_or_frame_source(self):
        policy=self.policy()
        for directive in ("script-src","default-src","frame-src","object-src"):
            self.assertNotIn("blob:",policy[directive])
        self.assertEqual(policy["object-src"],["'none'"])
        self.assertEqual(policy["frame-ancestors"],["'none'"])
    def test_script_nonce_and_existing_image_sources_survive(self):
        policy=self.policy()
        self.assertIn("'nonce-fixture'",policy["script-src"])
        self.assertTrue({"'self'","data:","https:"}.issubset(policy["img-src"]))
if __name__=="__main__":
    unittest.main()
