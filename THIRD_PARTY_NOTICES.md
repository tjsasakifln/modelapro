# Third-party notices and distribution gate

This file is the human-readable index for a release. The authoritative release
inventory is the generated SBOM plus `third_party/reuse_manifest.json`. A
release operator must generate both from the exact isolated build environment,
review every `NOASSERTION` licence, preserve required notices, and stop the
affected distribution when a material right is unknown or incompatible.

## Product source

No repository licence file was present at the C04 baseline. Consequently, the
right to distribute the product source and all contributor contributions is
**BLOCKED_EXTERNAL_EVIDENCE** pending an authorised licence/ownership decision.
This record does not change copyright, authorship, or any repository licence.

## Dependencies

Python runtime and build dependencies are not copied into this repository by
C04. Their exact name, version, metadata licence, homepage and hashable SBOM
identity are collected using:

```text
python -m scripts.comercial.operacao.sbom --generated-at <RFC3339> --output <path>
python -m scripts.comercial.operacao.audit --output <path>
```

`pip-audit` returning a non-zero status is release-blocking. The initial
commercial-build tooling is [PyInstaller v6.22.2](https://github.com/pyinstaller/pyinstaller/releases/tag/v6.22.2)
and [pip-audit v2.10.1](https://github.com/pypa/pip-audit/releases/tag/v2.10.1).
Their exact source/archive hashes and licence text are **NOASSERTION** until
the approved release artifact is acquired and reviewed; do not infer them from
this notice. They are build tools, not buyer runtime components.

The runtime entitlement verifier uses `cryptography==50.0.1` through its
public Ed25519 API. Installed distribution metadata reports
`Apache-2.0 OR BSD-3-Clause`; the selected Windows wheel and its bundled
notices/native components still require release-artifact review.

The preserved Linux build-environment SBOM inventories 98 installed
distributions and leaves 16 licence metadata values as `NOASSERTION`. Those
unknowns are a review queue, not permission to redistribute them. The final
Windows artifact must carry a newly generated inventory of the files actually
shipped.

No third-party source, fonts, licensed standards, private data, or proprietary
PDF template is bundled by the C04 packaging definitions.
