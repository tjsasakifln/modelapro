"""WeasyPrint native-library probe. pip alone never proves PDF capability."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


NATIVE_INSTALL_HINT = (
    "WeasyPrint's Python package is not enough: it needs native libraries "
    "(Pango, cairo, GLib/GObject, GDK-Pixbuf). pip cannot install those."
)
LINUX_HINT = (
    "Debian/Ubuntu: sudo apt-get install libpango-1.0-0 libpangocairo-1.0-0 "
    "libgdk-pixbuf-2.0-0 libffi-dev shared-mime-info fonts-dejavu-core"
)
WINDOWS_HINT = (
    "Windows: install a GTK3 runtime that provides pango/cairo "
    "(e.g. https://github.com/tschoonj/GTK-for-Windows-Runtime-Environment-Installer) "
    "and reopen the terminal. Do not treat `pip install weasyprint` as a working PDF stack."
)
MACOS_HINT = (
    "macOS: brew install pango cairo gdk-pixbuf libffi. macOS is untested in C15 CI."
)


@dataclass(frozen=True)
class PdfProbeResult:
    ok: bool
    stage: str
    message: str
    pdf_bytes: Optional[bytes] = None

    def raise_for_status(self) -> None:
        if not self.ok:
            raise RuntimeError(self.message)


def _native_message(original: BaseException) -> str:
    import sys

    system = sys.platform
    if system.startswith("win"):
        os_hint = WINDOWS_HINT
    elif system == "darwin":
        os_hint = MACOS_HINT
    else:
        os_hint = LINUX_HINT
    return (
        f"{NATIVE_INSTALL_HINT}\n{os_hint}\n"
        f"Original error ({type(original).__name__}): {original}"
    )


def probe_weasyprint(*, html: str = "<html><body><p>c15-pdf-probe</p></body></html>") -> PdfProbeResult:
    """
    Try a real HTML-to-PDF conversion.

    Returns ok=True only when write_pdf produces PDF bytes. A missing Python
    package and a missing native library are distinct stages.
    """
    try:
        import weasyprint  # noqa: F401
        from weasyprint import HTML
    except ImportError as exc:
        return PdfProbeResult(
            ok=False,
            stage="python_package",
            message=(
                "Python package 'weasyprint' is not installed. "
                "Install modelapro (or pip install weasyprint) and re-run. "
                f"ImportError: {exc}"
            ),
        )
    except Exception as exc:  # native libs can fail during import
        return PdfProbeResult(
            ok=False,
            stage="native_libraries",
            message=_native_message(exc),
        )

    try:
        pdf_bytes = HTML(string=html).write_pdf()
    except Exception as exc:
        return PdfProbeResult(
            ok=False,
            stage="native_libraries",
            message=_native_message(exc),
        )

    if not pdf_bytes or not bytes(pdf_bytes).startswith(b"%PDF"):
        return PdfProbeResult(
            ok=False,
            stage="render",
            message="WeasyPrint returned empty or non-PDF output; native stack is not usable.",
        )
    return PdfProbeResult(
        ok=True,
        stage="ok",
        message="WeasyPrint rendered a PDF; native libraries are present.",
        pdf_bytes=bytes(pdf_bytes),
    )
