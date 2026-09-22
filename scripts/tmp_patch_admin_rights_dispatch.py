from pathlib import Path

# One-shot branch patcher; removed before the pull request is opened.
# The permanent CI will validate the resulting source once the pull request exists.
path = Path("admin_server.py")
source = path.read_text(encoding="utf-8")

import_marker = "import data_subject_rights as data_subject_rights\n"
if source.count(import_marker) != 1:
    raise SystemExit("unexpected data_subject_rights import count")
source = source.replace(
    import_marker,
    import_marker + "import rights_execution_dispatch as rights_execution_dispatch\n",
    1,
)

old = """  if path=='/api/admin/compliance/request-execute':
   try:
    payload=self._read_json()
    result=data_subject_rights.execute(
      payload.get('id'),payload.get('subjectRef'),
      adapter=str(payload.get('adapter') or ''),
      purpose=str(payload.get('purpose') or ''),
    )
    return self.send_json({'ok':True,'execution':result})
"""
new = """  if path=='/api/admin/compliance/request-execute':
   try:
    payload=self._read_json()
    result=rights_execution_dispatch.execute(payload)
    return self.send_json({'ok':True,'execution':result})
"""
if source.count(old) != 1:
    raise SystemExit("unexpected request-execute route shape")
source = source.replace(old, new, 1)
path.write_text(source, encoding="utf-8")
