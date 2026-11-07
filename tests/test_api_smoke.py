import sqlite3, tempfile, unittest
from contextlib import closing
from pathlib import Path
from tools.api_smoke import reserve
ROOT=Path(__file__).resolve().parents[1]
class BudgetTests(unittest.TestCase):
    def test_reserve_and_reject_duplicate_and_overflow(self):
        with tempfile.TemporaryDirectory(dir=ROOT/'tmp') as directory:
            db=Path(directory)/'budget.sqlite'; reserve(db,'run','one','0.1','2','100')
            with self.assertRaises(sqlite3.IntegrityError): reserve(db,'run','one','0.1','2','100')
            with self.assertRaises(ValueError): reserve(db,'run','two','2','2','100')
            with closing(sqlite3.connect(db)) as conn: self.assertEqual(conn.execute('SELECT COUNT(*) FROM reservations').fetchone()[0],1)
