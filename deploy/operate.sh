#!/bin/sh
set -eu
cd "$(dirname "$0")"
project=${PERSONALKB_COMPOSE_PROJECT:-personalkb}
case "$project" in
  ''|[!a-z0-9]*|*[!a-z0-9_-]*) echo "Invalid PERSONALKB_COMPOSE_PROJECT" >&2; exit 2 ;;
esac
export PERSONALKB_COMPOSE_PROJECT="$project"
command=${1:-}; [ "$#" -eq 0 ] || shift
# Keep service changes and cold snapshots in the same host-wide critical section
# as one-click deployment. The descriptor stays open through EXIT cleanup.
case "$command" in
  build|start|stop|restart|backup|daily|retention|export|verify|push|pull|import|restore)
    : "${STATE_DIR:?set STATE_DIR}"
    lock="$STATE_DIR/tmp/personalkb-deploy.lock"
    if [ ! -f "$lock" ]; then ( : >>"$lock" ) || [ -f "$lock" ]; fi
    exec 9<"$lock"
    if ! flock -n 9; then echo "Deployment or maintenance already running" >&2; exit 1; fi ;;
esac
case "$command" in
  build) docker compose --project-name "$project" build web ;;
  start)
    : "${CONFIG_DIR:?set CONFIG_DIR}" "${STATE_DIR:?set STATE_DIR}" "${SECRET_FILE:?set SECRET_FILE}"
    port=$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1], encoding="utf-8"))["port"])' "$CONFIG_DIR/web.json")
    python3 preflight.py --config "$CONFIG_DIR/web.json" --state "$STATE_DIR" --secret "$SECRET_FILE" --port "$port"
    docker compose --project-name "$project" up -d web worker ;;
  stop) docker compose --project-name "$project" stop web worker ;;
  restart) docker compose --project-name "$project" restart web worker ;;
  check) docker compose --project-name "$project" config --quiet ;;
  report) python3 preflight.py "$@" ;;
  backup|daily|retention|export|verify|push|pull|import|restore)
    running=$(docker compose --project-name "$project" ps --services --filter status=running)
    restore_services() {
      code=$?
      trap - EXIT HUP INT TERM
      services=''
      for service in web worker; do
        if printf '%s\n' "$running" | grep -qx "$service"; then services="$services $service"; fi
      done
      restored=true
      if [ -n "$services" ]; then docker compose --project-name "$project" up -d --no-deps $services || { restored=false; code=1; }; fi
      if [ "$command" = daily ] && [ "$restored" = true ] && [ -n "$services" ]; then
        (CONFIG_DIR=$(cd "$CONFIG_DIR" && pwd) && export CONFIG_DIR &&
          cd .. && python3 -m deploy.restore_health $services) || { restored=false; code=1; }
      fi
      if [ "$command" = daily ] && [ -f "$STATE_DIR/backup-status.json" ]; then
        python3 -c 'import json,sys; from pathlib import Path; p=Path(sys.argv[1]); d=json.loads(p.read_text()); d["services_restored"]=(sys.argv[2]=="true"); d["state"]="failed" if not d["services_restored"] else d["state"]; t=p.with_suffix(".tmp"); t.write_text(json.dumps(d)+"\n"); t.replace(p)' "$STATE_DIR/backup-status.json" "$restored" || code=1
      fi
      exit "$code"
    }
    trap restore_services EXIT
    trap 'exit 1' HUP INT TERM
    if [ "$command" = daily ]; then
      python3 -c 'import datetime,json,sys; from pathlib import Path; p=Path(sys.argv[1]); p.write_text(json.dumps({"time_utc":datetime.datetime.now(datetime.timezone.utc).isoformat(),"state":"failed","snapshot":None,"services_restored":None})+"\n")' "$STATE_DIR/backup-status.json"
    fi
    docker compose --project-name "$project" stop web worker
    case "$command" in backup) command=create ;; esac
    if [ "$command" = daily ]; then
      python3 daily.py --config "$CONFIG_DIR/maintenance.json" --report "$STATE_DIR/backup-status.json"
    elif [ "$command" = push ] || [ "$command" = pull ]; then
      keys=$(python3 -c 'import json,re,sys; d=json.load(open(sys.argv[1],encoding="utf-8"))["oss"]; k=[d["access_key_id_env"],d["access_key_secret_env"]]; assert all(re.fullmatch(r"[A-Z_][A-Z0-9_]*",x) for x in k); print(" ".join(k))' "$CONFIG_DIR/maintenance.json")
      set -- $keys "$@"
      key_id=$1; key_secret=$2; shift 2
      docker compose --project-name "$project" --profile push run --rm -e "$key_id" -e "$key_secret" push python -m tools.maintenance --config /app/config/maintenance.json "$command" "$@"
    else
      docker compose --project-name "$project" --profile maintenance run --rm maintenance python -m tools.maintenance --config /app/config/maintenance.json "$command" "$@"
    fi
    ;;
  *) echo "Usage: $0 {check|build|start|stop|report|backup|retention|export|verify|push}" >&2; exit 2 ;;
esac
