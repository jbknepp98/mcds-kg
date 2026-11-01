#!/bin/zsh
# usage: tb.sh METHOD URL [json-body]
TOK=$(~/.claude/timebase-local-headers.sh | python3 -I -c "import json,sys;print(json.load(sys.stdin)['Authorization'])")
if [ -n "$3" ]; then curl -sk -X "$1" -H "Authorization: $TOK" -H 'Content-Type: application/json' -d "$3" -w '\nHTTP %{http_code}\n' "$2"
else curl -sk -X "$1" -H "Authorization: $TOK" -w '\nHTTP %{http_code}\n' "$2"; fi
