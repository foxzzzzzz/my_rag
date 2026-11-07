import argparse
from pathlib import Path
import uvicorn
from personalkb.web_app import create_app, load_web_config
from personalkb import workflow

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--config',default='config/web.json')
    args=parser.parse_args()
    c=load_web_config(args.config)
    wc=workflow.load_config(c['workflow_config'])
    uvicorn.run(create_app(wc,None,c),host=c['host'],port=c['port'],workers=1,reload=False,
                proxy_headers=True,forwarded_allow_ips='127.0.0.1',
                access_log=c.get('deployment_mode','development')!='production')

if __name__=='__main__': main()
