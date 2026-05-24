# Допоміжні функції для очищення українського тексту у фінансових voice-командах.
from __future__ import annotations

import re
from typing import Optional


UKRAINIAN_DATE_WORDS = {
    "сьогодні",
    "вчора",
    "позавчора",
    "завтра",
    "ранком",
    "вранці",
    "ввечері",
    "увечері",
    "вечором",
    "зранку",
}

CATEGORY_ALIASES = {
    "їжа": "їжа",
    "їжу": "їжа",
    "їжі": "їжа",
    "їжею": "їжа",
    "йіжа": "їжа",
    "йіжу": "їжа",
    "йізя": "їжа",
    "йізю": "їжа",
    "їзя": "їжа",
    "їзю": "їжа",
    "іжа": "їжа",
    "іжу": "їжа",
    "іжі": "їжа",
    "ізя": "їжа",
    "ізю": "їжа",
    "ізью": "їжа",
    "изя": "їжа",
    "изю": "їжа",
    "изью": "їжа",
    "еда": "їжа",
    "еду": "їжа",
    "едой": "їжа",
    "продукт": "продукти",
    "продукти": "продукти",
    "продуктів": "продукти",
    "продукты": "продукти",
    "магазин": "продукти",
    "супермаркет": "продукти",
    "атб": "продукти",
    "сільпо": "продукти",
    "транспорт": "транспорт",
    "транспортом": "транспорт",
    "таксі": "транспорт",
    "такси": "транспорт",
    "метро": "транспорт",
    "бензин": "транспорт",
    "кафе": "кафе",
    "ресторан": "кафе",
    "ресторани": "кафе",
    "комуналка": "комунальні",
    "комунальні": "комунальні",
    "інтернет": "комунальні",
    "аптека": "здоров'я",
    "аптеку": "здоров'я",
    "ліки": "здоров'я",
    "одяг": "одяг",
    "одягом": "одяг",
    "зарплата": "зарплата",
    "зарплату": "зарплата",
    "дохід": "дохід",
}


def normalize_spoken_text(value: str) -> str:
    # Нормалізує типові помилки ASR/LLM в українських фінансових командах.
    text = (value or "").strip().lower()
    text = text.replace("ґ", "г").replace("ғ", "г")
    text = text.replace("’", "'").replace("`", "'").replace("ʼ", "'")
    text = text.replace("йі", "ї").replace("йи", "ї")
    text = re.sub(r"\s+", " ", text)
    return text


def normalize_category_name(value: str) -> str:
    # Повертає канонічну назву категорії без зміни невідомого тексту.
    text = normalize_spoken_text(value)
    text = re.sub(r"[^\w'їієґа-яА-ЯІЇЄҐ-]+", " ", text, flags=re.U)
    text = " ".join(text.replace("-", " ").split())
    if not text:
        return ""

    if text in CATEGORY_ALIASES:
        return CATEGORY_ALIASES[text]

    words = [CATEGORY_ALIASES.get(word, word) for word in text.split()]
    if len(words) == 1:
        return words[0]
    return " ".join(words)


def extract_category_from_spoken_text(text: str) -> Optional[str]:
    # Витягує озвучену категорію після прийменників на кшталт "на їжу вчора".
    normalized = normalize_spoken_text(text)
    tokens = re.findall(r"[a-zа-яіїєґ']+", normalized, flags=re.I)
    if not tokens:
        return None

    prepositions = {"на", "за", "для"}
    for index, token in enumerate(tokens):
        if token not in prepositions:
            continue
        collected: list[str] = []
        for next_token in tokens[index + 1 :]:
            if next_token in UKRAINIAN_DATE_WORDS or next_token in prepositions:
                break
            if next_token in {"грн", "гривень", "гривні", "гривню", "гривней", "гри"}:
                break
            collected.append(next_token)
            candidate = normalize_category_name(" ".join(collected))
            if candidate in CATEGORY_ALIASES.values():
                return candidate
            if len(collected) >= 3:
                break

    for token in tokens:
        candidate = normalize_category_name(token)
        if candidate in CATEGORY_ALIASES.values():
            return candidate
    return None


def resolve_spoken_category(category_name: str, raw_text: str | None = None) -> str:
    # Бере чисту категорію з вихідного ASR-тексту, а потім нормалізує значення від LLM.
    if raw_text:
        extracted = extract_category_from_spoken_text(raw_text)
        if extracted:
            return extracted
    return normalize_category_name(category_name)


def clean_transaction_description(
    intent_description: str | None,
    raw_text: str | None = None,
) -> str:
    # Використовує початкову українську команду як опис транзакції, якщо вона доступна.
    source = raw_text or intent_description or ""
    source = source.strip()
    source = re.sub(r"\s+", " ", source)
    source = source.replace("ғ", "г")
    return source
