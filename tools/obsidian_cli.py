"""Offline editable Markdown/ZIP export, preview and explicit apply."""
import argparse
import json
from pathlib import Path
from personalkb.workflow import load_config
from personalkb.workflow_store import WorkflowError
from personalkb.obsidian import ObsidianService


def main(argv=None):
    p=argparse.ArgumentParser();p.add_argument('--config',default='config/workflow.json')
    sub=p.add_subparsers(dest='action',required=True)
    for cmd in ('export-note','export-zip'):
        a=sub.add_parser(cmd);a.add_argument('source_id');a.add_argument('--output',required=True)
    a=sub.add_parser('preview');a.add_argument('file')
    a=sub.add_parser('apply');a.add_argument('preview_id');a.add_argument('--choice',choices=('keep_server','use_uploaded'),required=True)
    a=p.parse_args(argv)
    try:
        service=ObsidianService(load_config(a.config))
        if a.action.startswith('export-'):
            data,name=(service.export_note if a.action=='export-note' else service.export_zip)(a.source_id)
            target=Path(a.output)
            if any(x.is_symlink() or (hasattr(x,'is_junction') and x.is_junction()) for x in (target,*target.parents)):raise WorkflowError('invalid_output_path')
            with target.open('xb') as f:f.write(data)
            result={'source_id':a.source_id,'bytes':len(data),'saved':True}
        elif a.action=='preview':
            path=Path(a.file)
            if path.stat().st_size>service.config['max_input_bytes']:raise WorkflowError('invalid_size')
            result=service.preview(path.read_bytes(),path.name)
        else:result=service.apply(a.preview_id,a.choice)
        print(json.dumps(result,ensure_ascii=True));return 0
    except WorkflowError as e:print(json.dumps({'error':e.code}));return 1
    except (OSError,ValueError):print(json.dumps({'error':'file_operation_failed'}));return 1

if __name__=='__main__':raise SystemExit(main())
