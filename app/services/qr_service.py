import re

import cv2
import numpy as np

from app.schemas import CardFields, QrResult


class QrService:
    def __init__(self) -> None:
        self._detector = cv2.QRCodeDetector()

    def detect_and_decode(self, image: np.ndarray) -> QrResult:
        data, points, _ = self._detector.detectAndDecode(image)

        detected = points is not None and len(points) > 0
        decoded = detected and bool(data)

        if not detected:
            return QrResult(detected=False, decoded=False)

        if not decoded:
            return QrResult(detected=True, decoded=False)

        return QrResult(
            detected=True,
            decoded=True,
            raw_payload=data,
            parsed_fields=self.parse_payload(data),
        )

    def parse_payload(self, payload: str) -> CardFields | None:
        payload = payload.strip()

        if payload.upper().startswith("BEGIN:VCARD"):
            return self._parse_vcard(payload)

        if payload.upper().startswith("MECARD:"):
            return self._parse_mecard(payload)

        return self._parse_delimited(payload)

    def _parse_vcard(self, payload: str) -> CardFields | None:
        fields = CardFields()
        found_any = False

        for line in payload.splitlines():
            line = line.strip()
            if ":" not in line:
                continue

            key, _, value = line.partition(":")
            key = key.split(";")[0].upper()
            value = value.strip()
            if not value:
                continue

            if key == "FN":
                fields.name = value
                found_any = True
            elif key == "TITLE":
                fields.position = value
                found_any = True
            elif key == "ORG":
                fields.company = value.split(";")[0]
                found_any = True
            elif key == "EMAIL":
                fields.email = value
                found_any = True
            elif key == "TEL":
                fields.phone = value
                found_any = True

        return fields if found_any else None

    def _parse_mecard(self, payload: str) -> CardFields | None:
        body = payload[len("MECARD:"):].rstrip(";")
        fields = CardFields()
        found_any = False

        for part in body.split(";"):
            if ":" not in part:
                continue
            key, _, value = part.partition(":")
            key = key.strip().upper()
            value = value.strip()
            if not value:
                continue

            if key == "N":
                fields.name = value
                found_any = True
            elif key == "TITLE":
                fields.position = value
                found_any = True
            elif key == "ORG":
                fields.company = value
                found_any = True
            elif key == "EMAIL":
                fields.email = value
                found_any = True
            elif key == "TEL":
                fields.phone = value
                found_any = True

        return fields if found_any else None

    def _parse_delimited(self, payload: str) -> CardFields | None:
        lines = [line.strip() for line in re.split(r"[\n;|,]", payload) if line.strip()]
        if not lines:
            return None

        email_pattern = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
        phone_pattern = re.compile(r"^\+?[\d\-\.\s()]{7,}$")

        fields = CardFields()
        found_any = False
        remaining: list[str] = []

        for line in lines:
            if email_pattern.fullmatch(line):
                fields.email = line
                found_any = True
            elif phone_pattern.fullmatch(line):
                fields.phone = line
                found_any = True
            else:
                remaining.append(line)

        if remaining:
            fields.name = remaining[0]
            found_any = True
        if len(remaining) > 1:
            fields.company = remaining[1]

        return fields if found_any else None
