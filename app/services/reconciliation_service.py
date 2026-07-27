from app.schemas import (
    FieldStatus,
    LlmExtractionResult,
    QrResult,
    ReconciledCard,
    ReconciledField,
)

_FIELD_NAMES = ("name", "position", "company", "email", "phone")


def _normalize(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = " ".join(value.split()).lower()
    return normalized or None


class ReconciliationService:
    def reconcile(self, llm_result: LlmExtractionResult, qr_result: QrResult) -> ReconciledCard:
        qr_fields = qr_result.parsed_fields if qr_result.decoded else None

        reconciled_fields: dict[str, ReconciledField] = {}
        has_conflict = False

        for field_name in _FIELD_NAMES:
            ocr_llm_value = getattr(llm_result, field_name).value
            qr_value = getattr(qr_fields, field_name) if qr_fields is not None else None

            reconciled_fields[field_name] = self._reconcile_field(ocr_llm_value, qr_value)
            if reconciled_fields[field_name].status == FieldStatus.CONFLICT:
                has_conflict = True

        optional_fields = dict(qr_fields.optional_fields) if qr_fields is not None else {}
        optional_fields.update(llm_result.optional_fields)

        return ReconciledCard(
            **reconciled_fields,
            optional_fields=optional_fields,
            overall_status="needs_review" if has_conflict else "confirmed",
        )

    def _reconcile_field(self, ocr_llm_value: str | None, qr_value: str | None) -> ReconciledField:
        if ocr_llm_value is None or qr_value is None:
            return ReconciledField(
                value=ocr_llm_value if ocr_llm_value is not None else qr_value,
                status=FieldStatus.UNVERIFIED,
                ocr_llm_value=ocr_llm_value,
                qr_value=qr_value,
            )

        if _normalize(ocr_llm_value) == _normalize(qr_value):
            return ReconciledField(
                value=ocr_llm_value if ocr_llm_value is not None else qr_value,
                status=FieldStatus.CONFIRMED,
                ocr_llm_value=ocr_llm_value,
                qr_value=qr_value,
            )

        return ReconciledField(
            value=None,
            status=FieldStatus.CONFLICT,
            ocr_llm_value=ocr_llm_value,
            qr_value=qr_value,
        )
