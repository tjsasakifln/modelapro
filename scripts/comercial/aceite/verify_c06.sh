#!/bin/bash
# Entrada compatível com o nome antigo. A conferência real está em verify_c06.py,
# que extrai as passagens citadas DO documento e as confronta com as fontes
# persistidas em docs/comercial/c06/sources/.
exec python3 "$(dirname "$0")/verify_c06.py" "$@"
