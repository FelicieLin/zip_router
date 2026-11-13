#!/bin/bash

BASEDIR=$(dirname "$0")

python3.6 "$BASEDIR/zip_router.py"
RUN_STATUS=$?

printf '程式結束碼：%s\n' "$RUN_STATUS"

exit "$RUN_STATUS"+
