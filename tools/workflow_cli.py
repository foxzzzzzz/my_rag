import argparse
import json
import sqlite3
import sys

from personalkb import workflow
from personalkb.workflow_store import WorkflowError


class Parser(argparse.ArgumentParser):
    def error(self, message):
        raise WorkflowError('invalid_arguments')


def main(argv=None):
    sys.stdout.reconfigure(encoding='utf-8')
    sys.stderr.reconfigure(encoding='utf-8')
    parser = Parser()
    parser.add_argument('--config', required=True)
    commands = parser.add_subparsers(dest='command', required=True, parser_class=Parser)
    for name in ('init', 'tasks', 'sources', 'eligible'):
        commands.add_parser(name)
    p = commands.add_parser('import'); p.add_argument('path'); p.add_argument('--rights-confirmed', action='store_true')
    p = commands.add_parser('work-once'); p.add_argument('--bundle')
    p = commands.add_parser('show'); p.add_argument('source_id')
    p = commands.add_parser('review'); p.add_argument('source_id'); p.add_argument('--version', required=True); p.add_argument('--sha256', required=True); p.add_argument('--score', required=True, type=float); p.add_argument('--decision', required=True, choices=('approve', 'rework', 'reject')); p.add_argument('--reviewer', required=True); p.add_argument('--review-id'); p.add_argument('--note', default='')
    p = commands.add_parser('revise'); p.add_argument('source_id'); p.add_argument('--expected-version', required=True); p.add_argument('--result', required=True)
    for name in ('cancel', 'retry'):
        p = commands.add_parser(name); p.add_argument('task_id')
    p = commands.add_parser('delete'); p.add_argument('source_id')
    p = commands.add_parser('export'); p.add_argument('--version', required=True); p.add_argument('--output-dir', required=True)
    try:
        args = parser.parse_args(argv)
        config = workflow.load_config(args.config)
        store = workflow.make_store(config)
        cmd = args.command
        if cmd == 'init': result = {'initialized': True}
        elif cmd == 'tasks': result = store.list_tasks()
        elif cmd == 'sources': result = store.list_sources()
        elif cmd == 'eligible': result = store.eligible_sources()
        elif cmd == 'import': result = workflow.import_file(config, args.path, rights_confirmed=args.rights_confirmed)
        elif cmd == 'work-once': result = workflow.run_once(config, bundle_path=args.bundle)
        elif cmd == 'show':
            source = store.get_source(args.source_id)
            versions = store.list_versions(args.source_id)
            result = {'source': source, 'versions': versions, 'current': next((v for v in versions if v['id'] == source.get('current_version_id')), None)}
        elif cmd == 'review': result = store.review(args.source_id, args.version, args.sha256, args.score, args.decision, args.reviewer, review_id=args.review_id, note=args.note)
        elif cmd == 'revise':
            with open(args.result, encoding='utf-8-sig') as f: data = json.load(f)
            result = store.revise(args.source_id, args.expected_version, data)
        elif cmd == 'cancel': result = store.cancel(args.task_id)
        elif cmd == 'retry': result = store.retry(args.task_id)
        elif cmd == 'delete': result = store.delete_source(args.source_id)
        else: result = workflow.export_version(config, args.version, args.output_dir)
        if cmd == 'work-once' and isinstance(result, dict) and 'error' in result:
            print(json.dumps(result, ensure_ascii=False), file=sys.stderr)
            return 2
        print(json.dumps(result, ensure_ascii=False, allow_nan=False))
        return 0
    except WorkflowError as exc:
        code = exc.code
    except sqlite3.Error:
        code = 'database_error'
    except (OSError, UnicodeError, json.JSONDecodeError):
        code = 'io_or_json_error'
    except (ValueError, TypeError, KeyError):
        code = 'invalid_input'
    print(json.dumps({'error': code}), file=sys.stderr)
    return 2


if __name__ == '__main__':
    sys.exit(main())


