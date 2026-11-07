import contextlib
import io
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from tools.video_cli import main, _secrets
from personalkb.workflow_store import WorkflowError

TMP = Path(__file__).resolve().parents[2] / 'tmp'
TMP.mkdir(exist_ok=True)

class VideoCliTests(unittest.TestCase):
    def invoke(self, args):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err): code = main(args)
        return code, out.getvalue(), err.getvalue()

    def test_live_gate_precedes_config_and_secrets(self):
        code, _, err = self.invoke(['--workflow-config', 'missing', 'run', 'task'])
        self.assertEqual(code, 2)
        self.assertEqual(json.loads(err)['error'], 'live_required')

    def test_environment_overrides_dotenv(self):
        with tempfile.TemporaryDirectory(dir=TMP) as directory:
            path = Path(directory) / '.env'
            path.write_text('EXAMPLE_KEY="from file" # comment\n', encoding='utf-8')
            with patch.dict(os.environ, {'EXAMPLE_KEY':'from_environment'}):
                self.assertEqual(_secrets(path)['EXAMPLE_KEY'], 'from_environment')

    def test_unknown_argument_safe_json(self):
        code, _, err = self.invoke(['--unknown'])
        self.assertEqual(code, 2)
        self.assertEqual(json.loads(err)['error'], 'invalid_arguments')

    def test_invalid_config_safe_json(self):
        code, _, err = self.invoke(['--workflow-config', 'missing', 'status', 'task'])
        self.assertEqual(code, 2)
        self.assertEqual(json.loads(err)['error'], 'invalid_config')

    def test_missing_task_status_does_not_read_env(self):
        with patch('tools.video_cli.load_config', return_value={}), patch('personalkb.video_pipeline.load_pipeline_config', return_value={}), patch('personalkb.video_pipeline.video_status', side_effect=WorkflowError('not_found')), patch('tools.video_cli._secrets', side_effect=AssertionError):
            code, _, err = self.invoke(['--workflow-config','unused','status','missing'])
        self.assertEqual(code, 2)
        self.assertEqual(json.loads(err)['error'], 'not_found')

if __name__ == '__main__': unittest.main()
