# Commercial local packaging

Windows x64 is the planned buyer-facing package: PyInstaller produces the
application directory and Inno Setup turns that directory into an installer.
The installer must be built and clean-machine tested on Windows; this source
tree does not claim that execution occurred.

Linux is a separately declared reference distribution, installed from a
reviewed wheel/lock in an isolated environment. It is not a substitute for a
Windows installer.

Run `python -m scripts.comercial.operacao.build_windows --help` and
`python -m scripts.comercial.operacao.sbom --help` from a release checkout.
Release evidence must retain the resulting `release-manifest.json`, SBOM,
pip-audit result, artifact hashes and the actual installer-signing record.
