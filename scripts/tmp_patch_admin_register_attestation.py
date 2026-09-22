from pathlib import Path

path = Path("admin_server.py")
source = path.read_text(encoding="utf-8")
marker = """  if path=='/api/admin/compliance/request':
"""
route = """  if path=='/api/admin/compliance/register-attestation':
   try:
    payload=self._read_json()
    result=compliance_admin.attest_operational_registers(payload)
    return self.send_json({'ok':True,'attestation':result},201)
   except PermissionError: return self.send_json({'ok':False,'error':'compliance_register_attestation_confirmation_required'},403)
   except RuntimeError: return self.send_json({'ok':False,'error':'compliance_register_attestation_conflict'},409)
   except Exception: return self.send_json({'ok':False,'error':'compliance_register_attestation_invalid'},400)
"""
if source.count(marker) != 1:
    raise SystemExit("unexpected compliance request route shape")
source = source.replace(marker, route + marker, 1)
path.write_text(source, encoding="utf-8")
