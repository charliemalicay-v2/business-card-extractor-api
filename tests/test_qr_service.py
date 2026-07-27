import cv2
import numpy as np

from app.services.qr_service import QrService


def _qr_image(payload: str) -> np.ndarray:
    encoder = cv2.QRCodeEncoder.create()
    matrix = encoder.encode(payload)
    return cv2.resize(matrix, (400, 400), interpolation=cv2.INTER_NEAREST)


def _plain_image() -> np.ndarray:
    return np.full((200, 200), 255, dtype=np.uint8)


def test_detect_and_decode_finds_and_decodes_real_qr_code():
    payload = "BEGIN:VCARD\nVERSION:3.0\nFN:Jane Doe\nEND:VCARD"
    service = QrService()

    result = service.detect_and_decode(_qr_image(payload))

    assert result.detected is True
    assert result.decoded is True
    assert result.raw_payload == payload
    assert result.parsed_fields is not None
    assert result.parsed_fields.name == "Jane Doe"


def test_detect_and_decode_returns_not_detected_for_image_without_qr():
    service = QrService()

    result = service.detect_and_decode(_plain_image())

    assert result.detected is False
    assert result.decoded is False
    assert result.raw_payload is None


def test_detect_and_decode_marks_unreadable_when_qr_data_is_corrupted():
    payload = "BEGIN:VCARD\nVERSION:3.0\nFN:Jane Doe\nEND:VCARD"
    image = _qr_image(payload)
    # Invert only the central data region, leaving the corner finder patterns
    # intact, so the detector still locates a QR code but cannot decode it.
    corrupted = image.copy()
    h, w = corrupted.shape
    cy, cx = h // 2, w // 2
    region = corrupted[cy - 40 : cy + 40, cx - 40 : cx + 40]
    corrupted[cy - 40 : cy + 40, cx - 40 : cx + 40] = 255 - region

    service = QrService()
    result = service.detect_and_decode(corrupted)

    assert result.detected is True
    assert result.decoded is False
    assert result.raw_payload is None


class TestParsePayload:
    def setup_method(self) -> None:
        self.service = QrService()

    def test_parses_vcard_format(self):
        payload = (
            "BEGIN:VCARD\n"
            "VERSION:3.0\n"
            "FN:Jane Doe\n"
            "TITLE:Sales Manager\n"
            "ORG:Acme Corp\n"
            "EMAIL:jane@acme.com\n"
            "TEL:+1-555-0100\n"
            "END:VCARD"
        )

        fields = self.service.parse_payload(payload)

        assert fields is not None
        assert fields.name == "Jane Doe"
        assert fields.position == "Sales Manager"
        assert fields.company == "Acme Corp"
        assert fields.email == "jane@acme.com"
        assert fields.phone == "+1-555-0100"

    def test_parses_mecard_format(self):
        payload = "MECARD:N:Jane Doe;ORG:Acme Corp;TEL:+15550100;EMAIL:jane@acme.com;;"

        fields = self.service.parse_payload(payload)

        assert fields is not None
        assert fields.name == "Jane Doe"
        assert fields.company == "Acme Corp"
        assert fields.phone == "+15550100"
        assert fields.email == "jane@acme.com"

    def test_parses_delimited_text_fallback(self):
        payload = "Jane Doe\nAcme Corp\njane@acme.com\n+1-555-0100"

        fields = self.service.parse_payload(payload)

        assert fields is not None
        assert fields.name == "Jane Doe"
        assert fields.company == "Acme Corp"
        assert fields.email == "jane@acme.com"
        assert fields.phone == "+1-555-0100"

    def test_returns_none_for_empty_payload(self):
        assert self.service.parse_payload("   ") is None
