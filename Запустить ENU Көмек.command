#!/bin/bash
set -e
cd -- "$(dirname -- "$0")"
if [ ! -x .venv/bin/python ]; then
  echo 'Сначала установите зависимости по инструкции README.md.'
  read -r -p 'Нажмите Enter для выхода.'
  exit 1
fi
echo 'ENU Көмек — http://127.0.0.1:8777'
exec .venv/bin/python server.py
