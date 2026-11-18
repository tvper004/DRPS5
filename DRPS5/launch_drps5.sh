#!/usr/bin/env bash
# Doble clic para abrir DRPS5 en macOS
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
export PYTHONPATH="$DIR:$DIR/pyremoteplay:$PYTHONPATH"
cd "$DIR"
exec "$DIR/.venv/bin/python3" "$DIR/drps5.py"
