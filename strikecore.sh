#!/bin/bash
cd "$(dirname "$0")"
exec ./strikecore/bin/python3 main.py "$@"
