import re
import random
import unicodedata
from typing import List, Tuple, Optional

# ================== CONSTANTS ==================

ARABIC_INDIC_DIGITS = "٠١٢٣٤٥٦٧٨٩"

ARABIC_LETTER_MAP = {
    "أ": "a",
    "ا": "a",
    "ب": "b",
    "ج": "c",
    "د": "d",
    "ه": "e",
}

TRUE_FALSE_SETS = [
    ("true", "false"),
    ("صح", "خطأ"),
    ("yes", "no"),
]

QUESTION_START_RE = re.compile(r'(?m)^\s*(\d+)\s*[\.\)\-:]\s*')
OPTION_LINE_RE = re.compile(r'^\s*([A-Ha-h]|[أ-ه])[\.\)\-:]\s*(.+)')
INLINE_OPTION_SPLIT_RE = re.compile(
    r'(?:(?<=\s)|^)(?=[A-Ha-hأ-ه][\.\)\-:])'
)

ANSWER_LINE_RE = re.compile(
    r'(?i)\b(answer|ans|الإجابة|جواب|correct|الصحيح)\b\s*[:\-]?\s*(.+)'
)

MARK_RE = re.compile(r'(✓|✔|✅|\*|\bcorrect\b|\bصحيح\b)', re.I)


# ================== NORMALIZATION ==================

def normalize_text(text: str) -> str:
    text = unicodedata.normalize("NFKC", text)
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = text.replace("\u00A0", " ").replace("\u200B", "")

    def map_digit(m):
        return str(ARABIC_INDIC_DIGITS.index(m.group(0)))

    text = re.sub(r"[٠-٩]", map_digit, text)
    return text.strip()


# ================== HELPERS ==================

def letter_to_index(letter: str) -> Optional[int]:
    letter = letter.strip().lower()
    if letter in ARABIC_LETTER_MAP:
        letter = ARABIC_LETTER_MAP[letter]
    if "a" <= letter <= "z":
        return ord(letter) - ord("a")
    return None


def clean_option_text(text: str) -> str:
    text = re.sub(r'^[\(\[]?[A-Za-z\u0621-\u064A][\)\]\.\-:]\s*', '', text)
    text = MARK_RE.sub('', text)
    return text.strip()


# ================== BLOCK EXTRACTION ==================

def extract_blocks(text: str) -> List[str]:
    matches = list(QUESTION_START_RE.finditer(text))
    if not matches:
        return [b.strip() for b in re.split(r'\n{2,}', text) if b.strip()]

    blocks = []
    for i, m in enumerate(matches):
        start = m.start()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        blocks.append(text[start:end].strip())
    return blocks


# ================== QUESTION TEXT ==================

def extract_question_text(lines: List[str]) -> str:
    q_lines = []
    for ln in lines:
        if OPTION_LINE_RE.match(ln) or ANSWER_LINE_RE.search(ln):
            break
        q_lines.append(ln)

    q = " ".join(q_lines)
    return re.sub(r'^\s*\d+[\.\)\-:]\s*', '', q).strip()


# ================== OPTIONS ==================

def extract_options(lines: List[str]) -> Tuple[List[str], Optional[int]]:
    options: List[str] = []
    marked_correct: Optional[int] = None

    # ---- standard option lines ----
    for ln in lines:
        m = OPTION_LINE_RE.match(ln)
        if m:
            if MARK_RE.search(ln):
                marked_correct = len(options)
            options.append(clean_option_text(ln))

    if options:
        return options, marked_correct

    # ---- inline options ----
    joined = " ".join(lines)
    parts = INLINE_OPTION_SPLIT_RE.split(joined)

    for part in parts:
        m = OPTION_LINE_RE.match(part.strip())
        if m:
            if MARK_RE.search(part):
                marked_correct = len(options)
            options.append(clean_option_text(part))

    if options:
        return options, marked_correct

    # ---- bullets ----
    for ln in lines:
        if re.match(r'^\s*[\-\*\u2022]\s+', ln):
            if MARK_RE.search(ln):
                marked_correct = len(options)
            options.append(clean_option_text(ln))

    return options, marked_correct


# ================== TRUE / FALSE ==================

def detect_true_false(question_text: str, lines: List[str]):
    for t, f in TRUE_FALSE_SETS:
        if re.search(rf'\b({t}|{f})\b', question_text, re.I):
            options = [t.capitalize(), f.capitalize()]

            for ln in lines:
                if re.search(rf'\b{t}\b', ln, re.I):
                    return options, 0
                if re.search(rf'\b{f}\b', ln, re.I):
                    return options, 1

            return options, None
    return None


# ================== CORRECT ANSWER ==================

def detect_correct_answer(lines: List[str], options: List[str]) -> Optional[int]:
    for ln in lines:
        m = ANSWER_LINE_RE.search(ln)
        if not m:
            continue

        payload = m.group(2)

        letter = re.search(r'[A-Za-zأ-ه]', payload)
        if letter:
            idx = letter_to_index(letter.group(0))
            if idx is not None:
                return idx

        number = re.search(r'\d+', payload)
        if number:
            return int(number.group(0)) - 1

    return None


# ================== SHUFFLING ==================

def shuffle_with_correct(options: List[str], correct: int):
    shuffled = options[:]
    random.shuffle(shuffled)

    original = options[correct]
    try:
        new_index = shuffled.index(original)
    except ValueError:
        return None

    return shuffled, new_index


# ================== MAIN PARSER ==================

def parse_message(message: str) -> Tuple[List[tuple], List[str]]:
    text = normalize_text(message)
    blocks = extract_blocks(text)

    questions = []
    failed = []

    for block in blocks:
        lines = [ln.strip() for ln in block.splitlines() if ln.strip()]
        if len(lines) < 2:
            failed.append(block)
            continue

        qtext = extract_question_text(lines)

        # ---- True / False first ----
        tf = detect_true_false(qtext, lines)
        if tf:
            options, correct = tf
        else:
            options, marked = extract_options(lines)
            correct = detect_correct_answer(lines, options)

            if correct is None and marked is not None:
                correct = marked

        if not options or correct is None or not (0 <= correct < len(options)):
            failed.append(block)
            continue

        shuffled = shuffle_with_correct(options, correct)
        if not shuffled:
            failed.append(block)
            continue

        questions.append((qtext, shuffled[0], shuffled[1]))

    return questions, failed
