from __future__ import annotations

import re
from dataclasses import dataclass

IBAN_CANDIDATE_RE = re.compile(r"UA\d{27}")
EDRPOU_CANDIDATE_RE = re.compile(r"(?<!\d)\d{8}(?!\d)")
PHONE_CANDIDATE_RE = re.compile(r"(?:\+?38)?0[\d\s\-()]{7,16}\d")

PHONE_PREFIXES = {
    "039", "050", "063", "066", "067", "068", "073",
    "091", "092", "093", "094", "095", "096", "097", "098", "099",
}


@dataclass
class ValidationWarning:
    kind: str  # "iban" | "edrpou" | "phone"
    text: str  # offending substring
    position: int
    message: str


def _iban_mod97_valid(iban: str) -> bool:
    iban = iban.upper().replace(" ", "")
    if len(iban) != 29 or not iban.startswith("UA"):
        return False
    rearranged = iban[4:] + iban[:4]
    try:
        digits = "".join(str(int(ch, 36)) for ch in rearranged)
    except ValueError:
        return False
    return int(digits) % 97 == 1


def _edrpou_checksum_valid(code: str) -> bool:
    if not code.isdigit() or len(code) != 8:
        return False
    digits = [int(c) for c in code]
    n = int(code)
    weights = [7, 1, 2, 3, 4, 5, 6] if 30_000_000 <= n <= 60_000_000 else [1, 2, 3, 4, 5, 6, 7]

    def _control(ws: list[int]) -> int:
        return sum(d * w for d, w in zip(digits[:7], ws, strict=True)) % 11

    control = _control(weights)
    if control > 9:
        control = _control([w + 2 for w in weights])
    if control > 9:
        control = 0
    return control == digits[7]


def _normalize_phone(raw: str) -> str | None:
    digits = re.sub(r"\D", "", raw)
    if digits.startswith("380") and len(digits) == 12:
        return "0" + digits[3:]
    if digits.startswith("0") and len(digits) == 10:
        return digits
    return None


def validate_text(text: str) -> list[ValidationWarning]:
    """Scans free-form answer text for financial identifiers that look
    malformed. Never rejects anything (plan addendum A3) — the caller
    always lets the admin confirm regardless, this just highlights a
    likely mistyped digit before it reaches 200 neighbours."""
    warnings: list[ValidationWarning] = []

    for m in IBAN_CANDIDATE_RE.finditer(text):
        iban = m.group()
        if not _iban_mod97_valid(iban):
            warnings.append(
                ValidationWarning("iban", iban, m.start(), f"IBAN {iban}: не проходить перевірку mod-97")
            )

    for m in EDRPOU_CANDIDATE_RE.finditer(text):
        code = m.group()
        if not _edrpou_checksum_valid(code):
            warnings.append(
                ValidationWarning("edrpou", code, m.start(), f"ЄДРПОУ {code}: не проходить перевірку контрольної суми")
            )

    for m in PHONE_CANDIDATE_RE.finditer(text):
        raw = m.group()
        national = _normalize_phone(raw)
        if national is None:
            continue
        prefix = national[0:3]
        if prefix not in PHONE_PREFIXES:
            warnings.append(
                ValidationWarning("phone", raw.strip(), m.start(), f"Телефон {raw.strip()}: незвичний префікс оператора ({prefix})")
            )

    return warnings


async def check_url(url: str, timeout: float = 5.0) -> str | None:
    """Optional HEAD check (plan A3). Never raises, never blocks an
    import — returns a warning string only on a confirmed non-2xx
    response; network errors are swallowed and treated as "can't tell"."""
    try:
        import httpx

        async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:
            response = await client.head(url)
        if not (200 <= response.status_code < 300):
            return f"{url}: HTTP {response.status_code}"
    except Exception:
        return None
    return None
