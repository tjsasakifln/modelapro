#!/usr/bin/env bash
set -eu
umask 077
if curl --silent --fail http://127.0.0.1:8501/_stcore/health >/dev/null; then exit 0; fi
if [[ -n "${CODESPACE_NAME:-}" && -n "${GITHUB_CODESPACES_PORT_FORWARDING_DOMAIN:-}" ]]; then
  export STREAMLIT_BROWSER_SERVER_ADDRESS="$CODESPACE_NAME-8501.$GITHUB_CODESPACES_PORT_FORWARDING_DOMAIN"
  export STREAMLIT_BROWSER_SERVER_PORT=443
fi
mkdir -p "$HOME/.local/state/modelapro"
nohup .venv/bin/modelapro --public >"$HOME/.local/state/modelapro/inicio.log" 2>&1 </dev/null &
