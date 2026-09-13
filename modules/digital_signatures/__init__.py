"""External-signing binding and optional pyHanko verification."""

from .pdf import (
    prepare_signature_request,
    record_external_signature,
    verify_pdf_signature,
    verify_signature_binding,
)

__all__ = [
    "prepare_signature_request",
    "record_external_signature",
    "verify_pdf_signature",
    "verify_signature_binding",
]
