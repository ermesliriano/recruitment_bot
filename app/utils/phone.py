# app/utils/phone.py
import phonenumbers


def normalize_phone(raw: str, region: str = "ES") -> str:
    parsed = phonenumbers.parse(raw, region)
    if not phonenumbers.is_valid_number(parsed):
        raise ValueError("Número de teléfono inválido")
    return phonenumbers.format_number(parsed, phonenumbers.PhoneNumberFormat.E164)
