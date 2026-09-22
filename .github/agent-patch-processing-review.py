from pathlib import Path

path = Path("admin_server.py")
text = path.read_text(encoding="utf-8")

import_anchor = "import compliance_admin as compliance_admin\nimport data_subject_rights as data_subject_rights\n"
import_replacement = (
    "import compliance_admin as compliance_admin\n"
    "import compliance_admin_http as compliance_admin_http\n"
    "import data_subject_rights as data_subject_rights\n"
)
if text.count(import_anchor) != 1:
    raise SystemExit("admin_server import anchor changed")
text = text.replace(import_anchor, import_replacement, 1)

route_anchor = """  if path=='/api/admin/compliance/request':
   try: return self.send_json({'ok':True,'request':compliance.create_rights_request(self._read_json())},201)
   except Exception: return self.send_json({'ok':False,'error':'compliance_request_invalid'},400)
"""
route_replacement = """  if path=='/api/admin/compliance/processing-review':
   try: payload=self._read_json()
   except Exception: return self.send_json({'ok':False,'error':'compliance_processing_review_invalid'},400)
   status, body=compliance_admin_http.review_high_risk_processing(payload)
   return self.send_json(body,status)
  if path=='/api/admin/compliance/request':
   try: return self.send_json({'ok':True,'request':compliance.create_rights_request(self._read_json())},201)
   except Exception: return self.send_json({'ok':False,'error':'compliance_request_invalid'},400)
"""
if text.count(route_anchor) != 1:
    raise SystemExit("admin_server compliance route anchor changed")
text = text.replace(route_anchor, route_replacement, 1)
path.write_text(text, encoding="utf-8")
