#!/usr/bin/env bash
# Run the test suite against one or both backends.
#
#   ./run-tests.sh            SQLite only (fast, offline) — the default
#   ./run-tests.sh --both     SQLite, then the same suite against MySQL
#   ./run-tests.sh --mysql    MySQL only
#
# SQLite cannot catch type-mapping faults: it has one numeric type and
# ignores column widths, so it happily passed a FLOAT that truncated file
# mtimes by half an hour and TEXT columns that MySQL cannot index. Run
# --both before merging anything that touches models or queries.
#
# The MySQL target comes from CM_TEST_MYSQL_URL, or from the database
# section of config.json when that is set to a mysql backend. It uses its
# own schema (default cm_test) and TRUNCATEs between tests, so it never
# touches a real library.
set -euo pipefail
cd "$(dirname "$0")"

PY=venv/bin/python
mode="${1:---sqlite}"

resolve_url() {
    if [ -n "${CM_TEST_MYSQL_URL:-}" ]; then
        echo "$CM_TEST_MYSQL_URL"; return
    fi
    $PY - <<'EOF'
import json, pathlib, sys
cfg = pathlib.Path("config.json")
if not cfg.exists():
    sys.exit(0)
db = json.loads(cfg.read_text()).get("database") or {}
if db.get("backend") != "mysql":
    sys.exit(0)
pw = db.get("password", "")
# A separate schema: the suite truncates, and that must never hit a library.
print(f"mysql://{db.get('user','')}:{pw}@{db.get('host','localhost')}"
      f":{db.get('port',3306)}/cm_test")
EOF
}

run_sqlite() { echo "== SQLite =="; $PY -m pytest -q "${@:2}"; }

run_mysql() {
    local url; url="$(resolve_url)"
    if [ -z "$url" ]; then
        echo "== MySQL == skipped: set CM_TEST_MYSQL_URL, or point config.json" \
             "at a mysql backend" >&2
        return 0
    fi
    echo "== MySQL =="
    # No timeout wrapper here on purpose: severing pytest mid-DDL once left
    # two DDL sessions deadlocked on InnoDB's dict_sys.latch and took the
    # whole server down.
    CM_TEST_MYSQL_URL="$url" $PY -m pytest -q --backend=mysql "${@:2}"
}

case "$mode" in
    --sqlite) run_sqlite "$@" ;;
    --mysql)  run_mysql "$@" ;;
    --both)   run_sqlite "$@"; run_mysql "$@" ;;
    *)        echo "usage: $0 [--sqlite|--mysql|--both]" >&2; exit 2 ;;
esac
