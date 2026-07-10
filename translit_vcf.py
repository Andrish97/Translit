#!/usr/bin/env python3
"""
Ukrainian VCF Transliterator
Transliteruje tekst ukraiński w plikach VCF (kontakty) na alfabet łaciński.
Zasady: Uchwała Gabinetu Ministrów Ukrainy nr 55 z dnia 27.01.2010.

Użycie:
    python3 translit_vcf.py plik.vcf [plik_wyjściowy.vcf]

Jeśli nie podasz pliku wyjściowego, zostanie utworzony plik <nazwa>_transliterated.vcf.
"""

import re
import sys
import quopri
from pathlib import Path


# ── Tabela transliteracji ─────────────────────────────────────────────────────

UKRAINIAN_CHARS = set(
    'АаБбВвГгҐґДдЕеЄєЖжЗзИиІіЇїЙйКкЛлМмНнОоПпРрСсТтУуФфХхЦцЧчШшЩщЬьЮюЯя'
)

# Litery o jednoznacznym mapowaniu (niezależne od kontekstu)
SIMPLE_MAP: dict[str, str] = {
    'А': 'A',    'а': 'a',
    'Б': 'B',    'б': 'b',
    'В': 'V',    'в': 'v',
    'Г': 'H',    'г': 'h',
    'Ґ': 'G',    'ґ': 'g',
    'Д': 'D',    'д': 'd',
    'Е': 'E',    'е': 'e',
    'Ж': 'Zh',   'ж': 'zh',
    'З': 'Z',    'з': 'z',
    'И': 'Y',    'и': 'y',
    'І': 'I',    'і': 'i',
    'К': 'K',    'к': 'k',
    'Л': 'L',    'л': 'l',
    'М': 'M',    'м': 'm',
    'Н': 'N',    'н': 'n',
    'О': 'O',    'о': 'o',
    'П': 'P',    'п': 'p',
    'Р': 'R',    'р': 'r',
    'С': 'S',    'с': 's',
    'Т': 'T',    'т': 't',
    'У': 'U',    'у': 'u',
    'Ф': 'F',    'ф': 'f',
    'Х': 'Kh',   'х': 'kh',
    'Ц': 'Ts',   'ц': 'ts',
    'Ч': 'Ch',   'ч': 'ch',
    'Ш': 'Sh',   'ш': 'sh',
    'Щ': 'Shch', 'щ': 'shch',
    # Znak miękki – pomijany (zgodnie z oficjalną tabelą)
    'Ь': '',     'ь': '',
    # Apostrofy ukraińskie – pomijane
    '\u2019': '', '\u02BC': '', '\u0027': '',
}

# Litery zależne od pozycji w wyrazie: (na_początku_wyrazu, w_innej_pozycji)
CONTEXT_MAP: dict[str, tuple[str, str]] = {
    'Є': ('Ye', 'ie'), 'є': ('ye', 'ie'),
    'Ї': ('Yi', 'i'),  'ї': ('yi', 'i'),
    'Й': ('Y',  'i'),  'й': ('y',  'i'),
    'Ю': ('Yu', 'iu'), 'ю': ('yu', 'iu'),
    'Я': ('Ya', 'ia'), 'я': ('ya', 'ia'),
}

_LETTER_RE = re.compile(r'[A-Za-zА-ЯҐЄІЇа-яґєіїь]')


def _is_word_start(text: str, pos: int) -> bool:
    """Zwraca True jeśli pozycja jest na początku wyrazu."""
    if pos == 0:
        return True
    return not _LETTER_RE.match(text[pos - 1])


def transliterate(text: str) -> str:
    """Transliteruje ukraiński tekst na alfabet łaciński."""
    if not any(c in UKRAINIAN_CHARS for c in text):
        return text

    result: list[str] = []
    i = 0
    n = len(text)

    while i < n:
        ch = text[i]

        # Specjalna kombinacja Зг/зг → Zgh/zgh/ZGH
        # (by odróżnić od Ж = Zh)
        if ch in 'Зз' and i + 1 < n and text[i + 1] in 'Гг':
            z_part = 'Z' if ch == 'З' else 'z'
            g_part = 'GH' if text[i + 1] == 'Г' else 'gh'
            result.append(z_part + g_part)
            i += 2
            continue

        if ch in SIMPLE_MAP:
            result.append(SIMPLE_MAP[ch])
        elif ch in CONTEXT_MAP:
            at_start, other = CONTEXT_MAP[ch]
            result.append(at_start if _is_word_start(text, i) else other)
        else:
            result.append(ch)

        i += 1

    return ''.join(result)


# ── Przetwarzanie VCF ─────────────────────────────────────────────────────────

# Pola VCF, których wartości należy transliterować
TRANSLITERATE_FIELDS = {
    'FN', 'N', 'ORG', 'TITLE', 'ROLE', 'NICKNAME',
    'NOTE', 'ADR', 'LABEL', 'CATEGORIES',
}

_FIELD_NAME_RE = re.compile(r'^([A-Z][A-Z0-9-]*)([;:])', re.IGNORECASE)


def _should_transliterate(field_name: str) -> bool:
    name = field_name.upper()
    return name in TRANSLITERATE_FIELDS or name.startswith('X-')


def _decode_quoted_printable(value: str) -> str:
    """Dekoduje wartość zakodowaną jako Quoted-Printable."""
    try:
        # Usuwa QP-owe miękkie łamanie linii (= na końcu)
        cleaned = value.replace('=\r\n', '').replace('=\n', '')
        return quopri.decodestring(cleaned.encode('ascii')).decode('utf-8')
    except Exception:
        return value


def _process_line(line: str) -> str:
    """Przetwarza pojedynczą linię VCF i zwraca transliterowaną wersję."""
    m = _FIELD_NAME_RE.match(line)
    if not m:
        return line

    field_name = m.group(1)
    if not _should_transliterate(field_name):
        return line

    # Znajdź pierwszy dwukropek (separator nazwa:wartość)
    try:
        colon_pos = line.index(':')
    except ValueError:
        return line

    params_part = line[:colon_pos]
    value = line[colon_pos + 1:]

    params_upper = params_part.upper()
    is_qp = 'QUOTED-PRINTABLE' in params_upper

    if is_qp:
        decoded = _decode_quoted_printable(value)
        transliterated = transliterate(decoded)
        # Usuń parametry kodowania – wynik to zwykły UTF-8
        clean_params = re.sub(
            r';?ENCODING=QUOTED-PRINTABLE', '', params_part, flags=re.IGNORECASE
        )
        clean_params = re.sub(
            r';?CHARSET=[A-Z0-9-]+', '', clean_params, flags=re.IGNORECASE
        )
        return f'{clean_params}:{transliterated}'
    else:
        return f'{params_part}:{transliterate(value)}'


def process_vcf(input_path: str, output_path: str) -> None:
    """Wczytuje plik VCF, transliteruje ukraiński tekst i zapisuje wynik."""
    raw = Path(input_path).read_bytes()

    # Wykryj kodowanie (UTF-8 z BOM lub bez, fallback na latin-1)
    if raw.startswith(b'\xef\xbb\xbf'):
        text = raw[3:].decode('utf-8', errors='replace')
    else:
        try:
            text = raw.decode('utf-8')
        except UnicodeDecodeError:
            text = raw.decode('latin-1')

    # Normalizuj końce linii, rozwiń VCF-owe złożenia (RFC 6350)
    lines = text.replace('\r\n', '\n').replace('\r', '\n').split('\n')

    unfolded: list[str] = []
    for line in lines:
        if line and line[0] in (' ', '\t') and unfolded:
            unfolded[-1] += line[1:]
        else:
            unfolded.append(line)

    # Transliteruj
    result = [_process_line(line) for line in unfolded]

    # Zapisz z końcami linii CRLF (standard VCF)
    output_text = '\r\n'.join(result)
    if not output_text.endswith('\r\n'):
        output_text += '\r\n'

    Path(output_path).write_text(output_text, encoding='utf-8')
    print(f'Gotowe: {output_path}')


# ── Punkt wejścia ─────────────────────────────────────────────────────────────

def main() -> None:
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)

    input_path = sys.argv[1]
    if not Path(input_path).exists():
        print(f'Błąd: plik "{input_path}" nie istnieje.', file=sys.stderr)
        sys.exit(1)

    if len(sys.argv) >= 3:
        output_path = sys.argv[2]
    else:
        p = Path(input_path)
        output_path = str(p.parent / f'{p.stem}_transliterated{p.suffix}')

    process_vcf(input_path, output_path)


if __name__ == '__main__':
    main()
