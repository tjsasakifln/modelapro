"""Deterministic, dependency-free DOCX export from the report view model.

The generated DOCX is intentionally conservative OOXML.  It contains the
same frozen numbers and qualification state as the PDF.  Equivalence is a
byte-for-byte property of the generated artifact; an externally edited DOCX
must be checked again and is otherwise a work document.
"""

from __future__ import annotations

import base64
import hashlib
import io
import zipfile
from collections.abc import Mapping
from typing import Any, Dict, Iterable, List, Optional
from xml.sax.saxutils import escape

from ..results_generator import build_report_view

_ZIP_TIME = (2020, 1, 1, 0, 0, 0)


def _paragraph(text: Any, *, style: Optional[str] = None) -> str:
    value = escape(str(text or ""))
    style_xml = f'<w:pPr><w:pStyle w:val="{escape(style)}"/></w:pPr>' if style else ""
    return f'<w:p>{style_xml}<w:r><w:t xml:space="preserve">{value}</w:t></w:r></w:p>'


def _table(rows: Iterable[Iterable[Any]]) -> str:
    table_rows: List[str] = []
    for row in rows:
        cells = "".join(
            '<w:tc><w:tcPr><w:tcW w:w="2400" w:type="dxa"/></w:tcPr>'
            + _paragraph(cell)
            + "</w:tc>"
            for cell in row
        )
        table_rows.append(f"<w:tr>{cells}</w:tr>")
    return (
        "<w:tbl><w:tblPr><w:tblBorders>"
        '<w:top w:val="single" w:sz="4"/><w:left w:val="single" w:sz="4"/>'
        '<w:bottom w:val="single" w:sz="4"/><w:right w:val="single" w:sz="4"/>'
        '<w:insideH w:val="single" w:sz="2"/><w:insideV w:val="single" w:sz="2"/>'
        "</w:tblBorders></w:tblPr>" + "".join(table_rows) + "</w:tbl>"
    )


def _image_paragraph(rel_id: str, name: str, index: int) -> str:
    safe_name = escape(name)
    return (
        '<w:p><w:r><w:drawing><wp:inline distT="0" distB="0" distL="0" distR="0">'
        f'<wp:extent cx="4572000" cy="3048000"/><wp:docPr id="{index}" name="{safe_name}"/>'
        '<a:graphic><a:graphicData uri="http://schemas.openxmlformats.org/drawingml/2006/picture">'
        f'<pic:pic><pic:nvPicPr><pic:cNvPr id="{index}" name="{safe_name}"/>'
        "<pic:cNvPicPr/></pic:nvPicPr><pic:blipFill>"
        f'<a:blip r:embed="{rel_id}"/><a:stretch><a:fillRect/></a:stretch>'
        '</pic:blipFill><pic:spPr><a:xfrm><a:off x="0" y="0"/>'
        '<a:ext cx="4572000" cy="3048000"/></a:xfrm><a:prstGeom prst="rect"><a:avLst/>'
        "</a:prstGeom></pic:spPr></pic:pic></a:graphicData></a:graphic>"
        "</wp:inline></w:drawing></w:r></w:p>"
    )


def _source_text(source: Any) -> str:
    if not isinstance(source, Mapping):
        return str(source or "")
    return " — ".join(
        str(source.get(field)).strip()
        for field in ("id", "label", "citation")
        if str(source.get(field) or "").strip()
    )


def _document_body(
    view: Mapping[str, Any], image_relations: Optional[Mapping[str, str]] = None
) -> str:
    parts: List[str] = [
        _paragraph(view.get("document_kind"), style="Title"),
        _paragraph(
            view.get("issuance_label") or view.get("document_state_label"),
            style="Subtitle",
        ),
        _paragraph("Identificação e finalidade", style="Heading1"),
        _paragraph(f"Solicitante: {view.get('applicant')}"),
        _paragraph(f"Finalidade: {view.get('purpose')}"),
        _paragraph(f"Bem/direitos: {view.get('asset_identification_display')}"),
        _paragraph(f"Data-base: {view.get('reference_date_display')}"),
        _paragraph(f"Vistoria: {view.get('inspection_date_display')}"),
        _paragraph(f"Região: {view.get('region_characterization') or 'PENDENTE'}"),
        _paragraph(f"Imóvel: {view.get('property_characterization') or 'PENDENTE'}"),
        _paragraph(f"Direitos: {view.get('rights_display') or 'PENDENTE'}"),
        _paragraph("Fontes", style="Heading2"),
        *[_paragraph(_source_text(source)) for source in (view.get("sources") or [])],
        _paragraph("Resultado", style="Heading1"),
        _paragraph(f"Estimativa pontual: {view.get('point_display')}"),
        _paragraph(f"Valor adotado: {view.get('adopted_value_display')}"),
        _paragraph(f"IC da média (80%): {view.get('mean_ci80_display')}"),
        _paragraph(f"Intervalo de predição: {view.get('prediction_interval_display')}"),
        _paragraph(f"Campo de arbítrio: {view.get('arbitration_interval_display')}"),
        _paragraph(f"Intervalo admissível: {view.get('admissible_interval_display')}"),
        _paragraph("Método, equação e diagnóstico", style="Heading1"),
        _paragraph(f"Método: {view.get('methodology_display')}"),
        _paragraph(
            f"Equação: {view.get('formula_display') or view.get('formula') or 'PENDENTE'}"
        ),
    ]
    coef_rows = [["Variável", "Coeficiente integral", "p-valor", "VIF"]]
    for coefficient in view.get("coef_rows") or []:
        coef_rows.append(
            [
                coefficient.get("variable"),
                coefficient.get("coefficient_full"),
                coefficient.get("pvalue"),
                coefficient.get("vif"),
            ]
        )
    if len(coef_rows) > 1:
        parts.append(_table(coef_rows))
    metric_rows = [["Métrica", "Valor"]]
    metrics = view.get("metrics") if isinstance(view.get("metrics"), Mapping) else {}
    for metric in metrics.get("rows") or []:
        metric_rows.append([metric.get("label"), metric.get("value")])
    if len(metric_rows) > 1:
        parts.append(_table(metric_rows))

    parts.extend(
        [
            _paragraph("Pressupostos, busca e validade", style="Heading1"),
            *[_paragraph(item) for item in (view.get("assumptions") or [])],
            _paragraph(
                f"Cobertura da busca: {view.get('search_summary') or 'PENDENTE'}"
            ),
            *[_paragraph(item) for item in (view.get("search_limitations") or [])],
            *[_paragraph(item) for item in (view.get("inference_limitations") or [])],
        ]
    )
    external = view.get("external_validation")
    if isinstance(external, Mapping):
        parts.append(
            _paragraph(
                "Validação externa: "
                + str(external.get("summary") or external.get("method") or "PENDENTE")
            )
        )
    if view.get("issues"):
        parts.append(_paragraph("Achados e ressalvas", style="Heading2"))
        for issue in view.get("issues") or []:
            parts.append(
                _paragraph(
                    " | ".join(
                        str(value or "")
                        for value in (
                            issue.get("severity"),
                            issue.get("code"),
                            issue.get("message"),
                        )
                    )
                )
            )

    parts.extend(
        [
            _paragraph("Qualificação", style="Heading1"),
            _paragraph(f"Perfil: {view.get('qualification_profile_display')}"),
            _paragraph(f"Base de valor: {view.get('value_basis_display')}"),
            _paragraph(
                f"Grau de fundamentação: {view.get('grau_fundamentacao_label')}"
            ),
            _paragraph(f"Grau de precisão: {view.get('grau_precisao_label')}"),
        ]
    )
    rule_rows = [
        ["Regra", "Fonte/versão", "Cláusula", "Estado", "Evidência", "Explicação"]
    ]
    for rule in view.get("qualification_rules") or []:
        rule_rows.append(
            [
                rule.get("rule_id"),
                f"{rule.get('source_id') or ''} {rule.get('edition_or_version') or ''}".strip(),
                rule.get("clause"),
                rule.get("status"),
                ", ".join(str(x) for x in (rule.get("evidence_refs") or [])),
                rule.get("explanation"),
            ]
        )
    if len(rule_rows) > 1:
        parts.append(_table(rule_rows))

    parts.append(_paragraph("Documentos e fotografias autorizados", style="Heading1"))
    attachment_rows = [["Arquivo", "Tipo", "Estado", "SHA-256"]]
    for attachment in view.get("documentary_attachments") or []:
        attachment_rows.append(
            [
                attachment.get("name"),
                attachment.get("media_type"),
                attachment.get("status"),
                attachment.get("sha256"),
            ]
        )
    if len(attachment_rows) > 1:
        parts.append(_table(attachment_rows))
    else:
        parts.append(_paragraph("Nenhum arquivo documental autorizado foi fornecido."))
    for name, rel_id in (image_relations or {}).items():
        parts.append(_paragraph(f"Conteúdo incorporado: {name}"))
        parts.append(_image_paragraph(rel_id, name, len(parts) + 1))

    parts.append(_paragraph("Amostra integral", style="Heading1"))
    used_headers = ["nº", "row_id", "Fonte", "Justificativa"] + list(
        view.get("used_value_columns") or []
    )
    used_rows = [used_headers]
    for row in view.get("used_rows") or []:
        used_rows.append(
            [
                row.get("seq"),
                row.get("row_id"),
                row.get("source"),
                row.get("justification"),
            ]
            + list(row.get("value_cells") or [])
        )
    parts.append(_table(used_rows))
    if view.get("excluded_rows"):
        parts.append(_paragraph("Registros excluídos", style="Heading2"))
        excluded_headers = ["nº", "row_id", "Fonte", "Justificativa"] + list(
            view.get("excluded_value_columns") or []
        )
        excluded_rows = [excluded_headers]
        for row in view.get("excluded_rows") or []:
            excluded_rows.append(
                [
                    row.get("seq"),
                    row.get("row_id"),
                    row.get("source"),
                    row.get("justification"),
                ]
                + list(row.get("value_cells") or [])
            )
        parts.append(_table(excluded_rows))

    parts.extend(
        [
            _paragraph("Revisão e rastreabilidade", style="Heading1"),
            _paragraph(
                f"Revisão profissional: {view.get('professional_review_display')}"
            ),
            _paragraph(
                f"Fingerprint do resultado: {view.get('result_fingerprint') or 'PENDENTE'}"
            ),
            _paragraph(
                f"Estado institucional: {view.get('institution_acceptance_display')}"
            ),
            _paragraph("Campos congelados", style="Heading2"),
        ]
    )
    for line in view.get("frozen_lines") or []:
        parts.append(_paragraph(line))
    return "".join(parts)


def _zip_write(archive: zipfile.ZipFile, name: str, data: str) -> None:
    info = zipfile.ZipInfo(name, _ZIP_TIME)
    info.compress_type = zipfile.ZIP_DEFLATED
    info.external_attr = 0o600 << 16
    archive.writestr(info, data.encode("utf-8"))


def _zip_write_bytes(archive: zipfile.ZipFile, name: str, data: bytes) -> None:
    info = zipfile.ZipInfo(name, _ZIP_TIME)
    info.compress_type = zipfile.ZIP_DEFLATED
    info.external_attr = 0o600 << 16
    archive.writestr(info, data)


def build_docx(
    snapshot: Mapping[str, Any],
    report_context: Optional[Mapping[str, Any]] = None,
) -> bytes:
    """Generate deterministic DOCX bytes from the same view as the PDF."""
    view = build_report_view(snapshot, report_context)
    if view.get("case_release_status") == "signed_integrity_verified" and view.get(
        "document_is_final"
    ):
        raise ValueError(
            "signed revision cannot be re-rendered as DOCX; create a new work revision"
        )
    media: List[tuple[str, str, str, bytes]] = []
    image_relations: Dict[str, str] = {}
    for attachment in view.get("documentary_attachments") or []:
        data_uri = attachment.get("image_data_uri")
        if not isinstance(data_uri, str) or ";base64," not in data_uri:
            continue
        media_type, encoded = data_uri[5:].split(";base64,", 1)
        extension = {"image/png": "png", "image/jpeg": "jpg", "image/webp": "webp"}.get(
            media_type
        )
        if not extension:
            continue
        index = len(media) + 1
        rel_id = f"rId{index + 1}"
        path = f"media/c03_attachment_{index}.{extension}"
        name = str(attachment.get("name") or path)
        media.append((rel_id, path, media_type, base64.b64decode(encoded)))
        image_relations[name] = rel_id
    document = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main" '
        'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships" '
        'xmlns:wp="http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing" '
        'xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main" '
        'xmlns:pic="http://schemas.openxmlformats.org/drawingml/2006/picture">'
        f"<w:body>{_document_body(view, image_relations)}"
        '<w:sectPr><w:pgSz w:w="11906" w:h="16838"/>'
        '<w:pgMar w:top="1134" w:right="1134" w:bottom="1134" w:left="1134"/></w:sectPr>'
        "</w:body></w:document>"
    )
    styles = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<w:styles xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
        '<w:style w:type="paragraph" w:default="1" w:styleId="Normal"><w:name w:val="Normal"/></w:style>'
        '<w:style w:type="paragraph" w:styleId="Title"><w:name w:val="Title"/><w:basedOn w:val="Normal"/>'
        '<w:rPr><w:b/><w:sz w:val="34"/></w:rPr></w:style>'
        '<w:style w:type="paragraph" w:styleId="Subtitle"><w:name w:val="Subtitle"/><w:basedOn w:val="Normal"/>'
        '<w:rPr><w:i/><w:sz w:val="22"/></w:rPr></w:style>'
        '<w:style w:type="paragraph" w:styleId="Heading1"><w:name w:val="heading 1"/><w:basedOn w:val="Normal"/>'
        '<w:rPr><w:b/><w:sz w:val="28"/></w:rPr></w:style>'
        '<w:style w:type="paragraph" w:styleId="Heading2"><w:name w:val="heading 2"/><w:basedOn w:val="Normal"/>'
        '<w:rPr><w:b/><w:sz w:val="24"/></w:rPr></w:style>'
        "</w:styles>"
    )
    media_types = "".join(
        f'<Default Extension="{path.rsplit(".", 1)[-1]}" ContentType="{media_type}"/>'
        for _, path, media_type, _ in media
    )
    content_types = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
        '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
        '<Default Extension="xml" ContentType="application/xml"/>'
        + media_types
        + '<Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>'
        '<Override PartName="/word/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.styles+xml"/>'
        "</Types>"
    )
    rels = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/>'
        "</Relationships>"
    )
    image_rels = "".join(
        f'<Relationship Id="{rel_id}" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/image" Target="{path}"/>'
        for rel_id, path, _, _ in media
    )
    doc_rels = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" Target="styles.xml"/>'
        + image_rels
        + "</Relationships>"
    )
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w") as archive:
        _zip_write(archive, "[Content_Types].xml", content_types)
        _zip_write(archive, "_rels/.rels", rels)
        _zip_write(archive, "word/document.xml", document)
        _zip_write(archive, "word/styles.xml", styles)
        _zip_write(archive, "word/_rels/document.xml.rels", doc_rels)
        for _, path, _, data in media:
            _zip_write_bytes(archive, f"word/{path}", data)
    return out.getvalue()


def verify_docx_equivalence(
    docx_bytes: bytes,
    snapshot: Mapping[str, Any],
    report_context: Optional[Mapping[str, Any]] = None,
) -> Dict[str, Any]:
    """Confirm that bytes are exactly the DOCX generated from this snapshot."""
    expected = build_docx(snapshot, report_context)
    observed_sha = hashlib.sha256(docx_bytes).hexdigest()
    expected_sha = hashlib.sha256(expected).hexdigest()
    try:
        with zipfile.ZipFile(io.BytesIO(docx_bytes), "r") as archive:
            bad_member = archive.testzip()
            names = set(archive.namelist())
    except (zipfile.BadZipFile, OSError) as exc:
        return {
            "status": "invalid",
            "equivalent": False,
            "expected_sha256": expected_sha,
            "observed_sha256": observed_sha,
            "findings": [{"code": "DOCX_INVALID_CONTAINER", "message": str(exc)}],
        }
    required = {
        "[Content_Types].xml",
        "_rels/.rels",
        "word/document.xml",
        "word/styles.xml",
    }
    findings = []
    if bad_member:
        findings.append({"code": "DOCX_CRC_ERROR", "member": bad_member})
    if not required.issubset(names):
        findings.append(
            {"code": "DOCX_REQUIRED_PART_MISSING", "members": sorted(required - names)}
        )
    if observed_sha != expected_sha:
        findings.append(
            {
                "code": "DOCX_EXTERNAL_EDIT_OR_DIFFERENT_SNAPSHOT",
                "message": "Os bytes não coincidem com a exportação determinística deste snapshot.",
            }
        )
    return {
        "status": "verified" if not findings else "work_document",
        "equivalent": not findings,
        "expected_sha256": expected_sha,
        "observed_sha256": observed_sha,
        "findings": findings,
    }
