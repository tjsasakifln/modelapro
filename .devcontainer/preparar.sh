#!/usr/bin/env bash
set -eu
sudo apt-get update -qq
sudo apt-get install -y libpango-1.0-0 libpangocairo-1.0-0 libgdk-pixbuf-2.0-0 shared-mime-info fonts-dejavu-core
python -m venv .venv
.venv/bin/python -m pip install -c constraints/linux-py3.txt -e .
