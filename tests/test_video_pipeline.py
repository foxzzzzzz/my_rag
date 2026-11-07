import tempfile
import unittest
from pathlib import Path
from personalkb.video_pipeline import paid_stage, load_pipeline_config
from personalkb.workflow_store import WorkflowError

class Journal:
    def __init__(self, state=None): self.state = state
    def begin(self, *args):
        if self.state is None: self.state = {'status':'prepared'}
    def stage(self, *args): return self.state
    def mark_started(self, *args): self.state['status'] = 'in_flight'
    def complete(self, *args): self.state = {'status':'completed', 'result':args[-1]}

class PaidStageTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.cfg = {'budget': {'ledger':str(Path(self.tmp.name)/'budget.sqlite'), 'run_limit':'5', 'research_limit':'100'}}
        self.calls = []
    def run_stage(self, journal, amount='1'):
        return paid_stage(journal, 'task', 'token', 'vision', 'abc', amount, self.cfg, lambda: self.calls.append(1) or {'content':'ok'})
    def test_completed_reused(self):
        j = Journal({'status':'completed','result':{'content':'cached'}})
        self.assertEqual(self.run_stage(j)['content'], 'cached')
        self.assertEqual(self.calls, [])
    def test_budget_rejects_before_call(self):
        with self.assertRaises(WorkflowError): self.run_stage(Journal(), '6')
        self.assertEqual(self.calls, [])
    def test_unknown_inflight_rejects(self):
        with self.assertRaises(WorkflowError): self.run_stage(Journal({'status':'in_flight'}))
        self.assertEqual(self.calls, [])
    def test_default_config(self):
        self.assertEqual(load_pipeline_config()['default_profile'], 'screen_tutorial')

if __name__ == '__main__': unittest.main()
