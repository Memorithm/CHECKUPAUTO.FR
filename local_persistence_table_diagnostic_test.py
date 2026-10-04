import pathlib,re,unittest

ROOT=pathlib.Path(__file__).resolve().parent
CREATE_RE=re.compile(r"CREATE\s+TABLE(?:\s+IF\s+NOT\s+EXISTS)?\s+([A-Za-z_][A-Za-z0-9_]*)",re.I)

class LocalPersistenceTableDiagnosticTest(unittest.TestCase):
    def test_emit_declared_sqlite_tables(self):
        rows={}
        for path in ROOT.rglob("*.py"):
            if ".ci-venv" in path.parts or "__pycache__" in path.parts:
                continue
            try:
                text=path.read_text(encoding="utf-8")
            except UnicodeDecodeError:
                continue
            for table in CREATE_RE.findall(text):
                rows.setdefault(table,set()).add(str(path.relative_to(ROOT)))
        print("PRIVACY_TABLE_INVENTORY="+repr({k:sorted(v) for k,v in sorted(rows.items())}))
        self.assertGreater(len(rows),10)

if __name__=="__main__":
    unittest.main()
