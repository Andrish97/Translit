#!/usr/bin/env node
// Ukrainian VCF Transliterator
// Zasady: Uchwała Gabinetu Ministrów Ukrainy nr 55 z 27.01.2010
//
// Użycie:
//   node translit_vcf.js wejście.vcf [wyjście.vcf]

const fs = require('fs');
const path = require('path');

// ── Tabela transliteracji ──────────────────────────────────────────────────

const SIMPLE_MAP = {
  'А':'A',  'а':'a',
  'Б':'B',  'б':'b',
  'В':'V',  'в':'v',
  'Г':'H',  'г':'h',
  'Ґ':'G',  'ґ':'g',
  'Д':'D',  'д':'d',
  'Е':'E',  'е':'e',
  'Ж':'Zh', 'ж':'zh',
  'З':'Z',  'з':'z',
  'И':'Y',  'и':'y',
  'І':'I',  'і':'i',
  'К':'K',  'к':'k',
  'Л':'L',  'л':'l',
  'М':'M',  'м':'m',
  'Н':'N',  'н':'n',
  'О':'O',  'о':'o',
  'П':'P',  'п':'p',
  'Р':'R',  'р':'r',
  'С':'S',  'с':'s',
  'Т':'T',  'т':'t',
  'У':'U',  'у':'u',
  'Ф':'F',  'ф':'f',
  'Х':'Kh', 'х':'kh',
  'Ц':'Ts', 'ц':'ts',
  'Ч':'Ch', 'ч':'ch',
  'Ш':'Sh', 'ш':'sh',
  'Щ':'Shch','щ':'shch',
  'Ь':'',   'ь':'',      // znak miękki – pomijany
  '\u2019':'','\u02BC':'', // apostrofy ukraińskie – pomijane
};

// Litery zależne od pozycji: [na_początku_wyrazu, w_innej_pozycji]
const CONTEXT_MAP = {
  'Є':['Ye','ie'], 'є':['ye','ie'],
  'Ї':['Yi','i'],  'ї':['yi','i'],
  'Й':['Y', 'i'],  'й':['y', 'i'],
  'Ю':['Yu','iu'], 'ю':['yu','iu'],
  'Я':['Ya','ia'], 'я':['ya','ia'],
};

const UK_CHARS = new Set(Object.keys(SIMPLE_MAP).concat(Object.keys(CONTEXT_MAP)));

function isLetter(ch) {
  return ch && /[A-Za-zА-ЯҐЄІЇа-яґєіїь]/.test(ch);
}

function transliterate(text) {
  if (![...text].some(c => UK_CHARS.has(c))) return text;

  const result = [];
  let i = 0;
  while (i < text.length) {
    const ch = text[i];

    // Зг/зг → Zgh/zgh (by nie mylić z Ж→Zh)
    if ('Зз'.includes(ch) && 'Гг'.includes(text[i+1] || '')) {
      const z = ch === 'З' ? 'Z' : 'z';
      const g = text[i+1] === 'Г' ? 'GH' : 'gh';
      result.push(z + g);
      i += 2;
      continue;
    }

    if (ch in SIMPLE_MAP) {
      result.push(SIMPLE_MAP[ch]);
    } else if (ch in CONTEXT_MAP) {
      const atStart = !isLetter(text[i-1]);
      result.push(CONTEXT_MAP[ch][atStart ? 0 : 1]);
    } else {
      result.push(ch);
    }
    i++;
  }
  return result.join('');
}

// ── Przetwarzanie VCF ──────────────────────────────────────────────────────

const TRANSLITERATE_FIELDS = new Set([
  'FN','N','ORG','TITLE','ROLE','NICKNAME','NOTE','ADR','LABEL','CATEGORIES',
]);

function shouldTransliterate(fieldName) {
  return TRANSLITERATE_FIELDS.has(fieldName.toUpperCase()) ||
         fieldName.toUpperCase().startsWith('X-');
}

function decodeQP(value) {
  // Usuń QP-owe miękkie łamanie linii, zdekoduj sekwencje =XX
  const cleaned = value.replace(/=\r?\n/g, '');
  const bytes = [];
  let j = 0;
  while (j < cleaned.length) {
    if (cleaned[j] === '=' && j + 2 < cleaned.length) {
      const hex = cleaned.slice(j+1, j+3);
      if (/^[0-9A-Fa-f]{2}$/.test(hex)) {
        bytes.push(parseInt(hex, 16));
        j += 3;
        continue;
      }
    }
    bytes.push(cleaned.charCodeAt(j));
    j++;
  }
  return Buffer.from(bytes).toString('utf8');
}

function processLine(line) {
  const m = line.match(/^([A-Z][A-Z0-9-]*)([;:])/i);
  if (!m) return line;

  const fieldName = m[1];
  if (!shouldTransliterate(fieldName)) return line;

  const colonPos = line.indexOf(':');
  if (colonPos === -1) return line;

  const paramsPart = line.slice(0, colonPos);
  const value = line.slice(colonPos + 1);
  const paramsUpper = paramsPart.toUpperCase();

  if (paramsUpper.includes('QUOTED-PRINTABLE')) {
    const decoded = decodeQP(value);
    const transliterated = transliterate(decoded);
    // Usuń parametry kodowania – wynik to zwykły UTF-8
    const cleanParams = paramsPart
      .replace(/;?ENCODING=QUOTED-PRINTABLE/gi, '')
      .replace(/;?CHARSET=[A-Z0-9-]+/gi, '');
    return `${cleanParams}:${transliterated}`;
  }

  return `${paramsPart}:${transliterate(value)}`;
}

function processVCF(inputPath, outputPath) {
  const raw = fs.readFileSync(inputPath);

  // Obsługa BOM UTF-8
  let text;
  if (raw[0] === 0xEF && raw[1] === 0xBB && raw[2] === 0xBF) {
    text = raw.slice(3).toString('utf8');
  } else {
    try {
      text = raw.toString('utf8');
    } catch {
      text = raw.toString('latin1');
    }
  }

  // Normalizuj końce linii
  const lines = text.replace(/\r\n/g, '\n').replace(/\r/g, '\n').split('\n');

  // Rozwiń VCF-owe złożenia (RFC 6350: kontynuacja zaczyna się od spacji/taba)
  const unfolded = [];
  for (const line of lines) {
    if (line.length > 0 && (line[0] === ' ' || line[0] === '\t') && unfolded.length > 0) {
      unfolded[unfolded.length - 1] += line.slice(1);
    } else {
      unfolded.push(line);
    }
  }

  const result = unfolded.map(processLine);

  // VCF używa CRLF
  let output = result.join('\r\n');
  if (!output.endsWith('\r\n')) output += '\r\n';

  fs.writeFileSync(outputPath, output, 'utf8');
  console.log(`Gotowe: ${outputPath}`);
}

// ── Punkt wejścia ──────────────────────────────────────────────────────────

const [,, inputArg, outputArg] = process.argv;

if (!inputArg) {
  console.log('Użycie: node translit_vcf.js wejście.vcf [wyjście.vcf]');
  process.exit(1);
}

if (!fs.existsSync(inputArg)) {
  console.error(`Błąd: plik "${inputArg}" nie istnieje.`);
  process.exit(1);
}

const outputPath = outputArg || (() => {
  const ext = path.extname(inputArg);
  return path.join(path.dirname(inputArg), path.basename(inputArg, ext) + '_transliterated' + ext);
})();

processVCF(inputArg, outputPath);
