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
The Windows host must first generate and review
`constraints/windows-py312-x64.txt`; the builder refuses a dirty checkout or
an installed environment that differs from that lock. The Linux-generated
`commercial-build.txt` is not evidence for Windows wheels/DLLs.
Release evidence must retain the resulting `release-manifest.json`, SBOM,
pip-audit result, artifact hashes and the actual installer-signing record.
