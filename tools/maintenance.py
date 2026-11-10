import argparse
import json
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from personalkb import maintenance


def main():
    parser = argparse.ArgumentParser(description='Cold backup and offline restore')
    parser.add_argument('--config', default='config/maintenance.json')
    sub = parser.add_subparsers(dest='command', required=True)
    sub.add_parser('create')
    p = sub.add_parser('push'); p.add_argument('snapshot')
    p = sub.add_parser('pull'); p.add_argument('snapshot')
    p = sub.add_parser('retention'); p.add_argument('--apply', action='store_true')
    p = sub.add_parser('purge-trash'); p.add_argument('--apply', action='store_true')
    for command in ('verify', 'export', 'restore'):
        p = sub.add_parser(command); p.add_argument('snapshot')
        if command == 'export': p.add_argument('--output', required=True)
        if command == 'restore': p.add_argument('--target-empty-dir', required=True)
    p = sub.add_parser('import'); p.add_argument('--archive', required=True); p.add_argument('--target-empty-dir', required=True)
    args = parser.parse_args()
    try:
        if args.command == 'import':
            raw = json.loads(Path(args.config).read_text(encoding='utf-8-sig'))
            result = maintenance.import_archive(args.archive, args.target_empty_dir, raw['min_free_bytes'], raw['max_manifest_bytes'])
        else:
            config = maintenance.load_config(args.config)
            if args.command in ('push', 'pull'):
                from personalkb import backup_storage
                result = getattr(backup_storage, args.command)(config, args.snapshot)
            elif args.command == 'retention': result = maintenance.retention(config, apply=args.apply)
            elif args.command == 'purge-trash':
                from personalkb.trash_purge import purge
                result = purge(config, apply=args.apply)
            elif args.command == 'create': result = {'snapshot': maintenance.create(config)}
            elif args.command == 'verify': result = maintenance.verify(config, args.snapshot)
            elif args.command == 'export': result = {'archive': maintenance.export(config, args.snapshot, args.output)}
            else: result = maintenance.restore(config, args.snapshot, args.target_empty_dir)
        print(json.dumps(result, ensure_ascii=False))
    except Exception as e:
        print(json.dumps({'error': getattr(e, 'code', type(e).__name__)}, ensure_ascii=False), file=sys.stderr)
        return 1
    return 0

if __name__ == '__main__': sys.exit(main())
