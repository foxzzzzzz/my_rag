"""Explicit entry point for the live video workflow."""
import argparse
import json
import os
import sys
import sqlite3
from tools.demo_setup import dotenv, ConfigError
from personalkb.asr_storage import StorageError
from pathlib import Path
from personalkb.workflow import load_config
from personalkb.workflow_store import WorkflowError


class Parser(argparse.ArgumentParser):
    def error(self, message):
        raise WorkflowError('invalid_arguments')


def _secrets(path):
    values = dotenv(Path(path))
    values.update(os.environ)
    return values


def main(argv=None):
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"): stream.reconfigure(encoding="utf-8")
    parser = Parser()
    parser.add_argument('--workflow-config', required=True)
    parser.add_argument('--pipeline-config')
    parser.add_argument('--env-file', default='.env')
    commands = parser.add_subparsers(dest='command', required=True)
    for name in ('run', 'resume', 'status', 'cleanup'):
        p = commands.add_parser(name, help='清理可联系 OSS，不调用模型' if name == 'cleanup' else None)
        p.add_argument('task_id')
        if name in ('run', 'resume'): p.add_argument('--live', action='store_true')
    try:
        args = parser.parse_args(argv)
    except WorkflowError as exc:
        print(json.dumps({'error': exc.code}), file=sys.stderr)
        return 2
    if args.command in ('run', 'resume') and not args.live:
        print(json.dumps({'error': 'live_required'}), file=sys.stderr)
        return 2
    try:
        from personalkb.video_pipeline import load_pipeline_config, run_video, video_status, cleanup_video
        wc = load_config(args.workflow_config)
        pc = load_pipeline_config(args.pipeline_config)
        if args.command == 'status': result = video_status(wc, pc, args.task_id)
        elif args.command == 'cleanup': result = cleanup_video(wc, pc, _secrets(args.env_file), args.task_id)
        else: result = run_video(wc, pc, _secrets(args.env_file), task_id=args.task_id, resume=args.command == 'resume')
        print(json.dumps(result, ensure_ascii=False, allow_nan=False))
        return 0
    except WorkflowError as exc:
        print(json.dumps({'error': exc.code}), file=sys.stderr)
    except sqlite3.Error:
        print(json.dumps({'error': 'database_error'}), file=sys.stderr)
    except StorageError:
        print(json.dumps({'error': 'storage_error'}), file=sys.stderr)
    except (RuntimeError, ConfigError):
        print(json.dumps({'error': 'operation_failed'}), file=sys.stderr)
    except (OSError, ValueError, TypeError, KeyError):
        print(json.dumps({'error': 'invalid_input'}), file=sys.stderr)
    return 2


if __name__ == '__main__':
    sys.exit(main())
