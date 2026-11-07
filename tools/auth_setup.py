import argparse, getpass, json, os
from pathlib import Path
from personalkb.web_auth import hash_password

def main():
    parser=argparse.ArgumentParser(description='Create a private authentication environment file')
    parser.add_argument('--output', required=True)
    parser.add_argument('--config', default='config/auth.json')
    args=parser.parse_args()
    cfg=json.loads(Path(args.config).read_text(encoding='utf-8-sig'))
    first=getpass.getpass('Password: ')
    second=getpass.getpass('Confirm password: ')
    if not first or first != second: raise SystemExit('Passwords empty or do not match')
    value=hash_password(first,cfg['hash_iterations'])
    fd=os.open(args.output,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
    with os.fdopen(fd,'w',encoding='utf-8') as f: f.write(cfg['password_hash_env']+'='+value+'\n')
    print('Authentication environment file created.')

if __name__=='__main__': main()
