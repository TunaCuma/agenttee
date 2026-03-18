"""
Line tokenizer: classifies each segment of a log line into typed tokens.

This is the lexer at the heart of the system. It scans each line and
produces a template signature that captures the *structure* of the line
while abstracting away the variable parts (timestamps values, hashes, etc).
"""

import re
from dataclasses import dataclass, field
from enum import Enum, auto


class TokenType(Enum):
    TIMESTAMP = auto()
    LEVEL = auto()
    NAMESPACE = auto()    # dot.separated.identifiers or [bracketed]
    NUMBER = auto()
    HEX = auto()          # docker layer hashes, commit SHAs
    IP = auto()
    URL = auto()
    PATH = auto()         # file system paths
    HASH_LIKE = auto()    # long alphanumeric strings (build hashes)
    ANSI = auto()         # ANSI escape sequences
    QUOTED = auto()
    WORD = auto()
    SYMBOL = auto()
    PROGRESS = auto()     # percentage patterns like "92%"
    KV_PAIR = auto()      # key=value patterns


ANSI_RE = re.compile(r'\x1b\[[0-9;]*m')

LEVEL_KEYWORDS = frozenset({
    'TRACE', 'DEBUG', 'INFO', 'NOTICE', 'WARNING', 'WARN',
    'ERROR', 'ERR', 'CRITICAL', 'FATAL', 'VERBOSE',
    'trace', 'debug', 'info', 'notice', 'warning', 'warn',
    'error', 'err', 'critical', 'fatal', 'verbose',
})

TIMESTAMP_PATTERNS = [
    re.compile(r'\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:[+-]\d{2}:\d{2}|Z)?'),
    re.compile(r'\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?'),
    re.compile(r'time="[^"]*"'),
]

NAMESPACE_RE = re.compile(r'[a-zA-Z_][a-zA-Z0-9_]*(?:\.[a-zA-Z_][a-zA-Z0-9_]*){2,}')
BRACKETED_NS_RE = re.compile(r'\[([a-zA-Z][a-zA-Z0-9_.]*)\]')
HEX_RE = re.compile(r'[0-9a-f]{8,}')
HASH_LIKE_RE = re.compile(r'[0-9a-f]{12,}(?:\.[0-9a-f]+)?')
URL_RE = re.compile(r'https?://\S+')
PATH_RE = re.compile(r'(?:/[a-zA-Z0-9._-]+){2,}(?:\.[a-zA-Z]+)?')
IP_RE = re.compile(r'\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}(?::\d+)?')
KV_RE = re.compile(r'[a-zA-Z_][a-zA-Z0-9_]*=[^\s,]+')
PROGRESS_RE = re.compile(r'\d{1,3}%')
NUMBER_RE = re.compile(r'\d+(?:\.\d+)?(?:\s*(?:KiB|MiB|GiB|KB|MB|GB|ms|s|bytes))?')


@dataclass
class Token:
    type: TokenType
    value: str


@dataclass
class TokenizedLine:
    original: str
    clean: str          # ANSI-stripped
    tokens: list[Token] = field(default_factory=list)
    signature: str = ""

    @property
    def template_key(self) -> str:
        """Signature ignoring variable tokens (numbers, hashes, etc)."""
        return self.signature


def strip_ansi(text: str) -> str:
    return ANSI_RE.sub('', text)


def tokenize_line(line: str) -> TokenizedLine:
    clean = strip_ansi(line).strip()
    result = TokenizedLine(original=line, clean=clean)

    if not clean:
        result.signature = "EMPTY"
        return result

    sig_parts = []
    remaining = clean

    for pat in TIMESTAMP_PATTERNS:
        m = pat.search(remaining)
        if m:
            sig_parts.append("TS")
            remaining = remaining[:m.start()] + remaining[m.end():]
            result.tokens.append(Token(TokenType.TIMESTAMP, m.group()))
            break

    for word in remaining.split():
        if word.upper() in LEVEL_KEYWORDS or word.rstrip(',') in LEVEL_KEYWORDS:
            sig_parts.append("LVL")
            result.tokens.append(Token(TokenType.LEVEL, word))
        elif NAMESPACE_RE.fullmatch(word) or NAMESPACE_RE.fullmatch(word.rstrip(',')):
            sig_parts.append("NS")
            result.tokens.append(Token(TokenType.NAMESPACE, word))
        elif URL_RE.fullmatch(word):
            sig_parts.append("URL")
            result.tokens.append(Token(TokenType.URL, word))
        elif HASH_LIKE_RE.fullmatch(word):
            sig_parts.append("HASH")
            result.tokens.append(Token(TokenType.HASH_LIKE, word))
        elif IP_RE.fullmatch(word):
            sig_parts.append("IP")
            result.tokens.append(Token(TokenType.IP, word))
        elif PATH_RE.fullmatch(word):
            sig_parts.append("PATH")
            result.tokens.append(Token(TokenType.PATH, word))
        elif PROGRESS_RE.fullmatch(word):
            sig_parts.append("PCT")
            result.tokens.append(Token(TokenType.PROGRESS, word))
        elif KV_RE.fullmatch(word):
            sig_parts.append("KV")
            result.tokens.append(Token(TokenType.KV_PAIR, word))
        elif NUMBER_RE.fullmatch(word):
            sig_parts.append("N")
            result.tokens.append(Token(TokenType.NUMBER, word))
        elif word in (':', '-', '|', '>', '<', '=', '+', '*', '[', ']', '(', ')', '{', '}'):
            sig_parts.append("SYM")
            result.tokens.append(Token(TokenType.SYMBOL, word))
        elif BRACKETED_NS_RE.fullmatch(word):
            sig_parts.append("BNS")
            result.tokens.append(Token(TokenType.NAMESPACE, word))
        else:
            sig_parts.append("W")
            result.tokens.append(Token(TokenType.WORD, word))

    result.signature = "_".join(sig_parts) if sig_parts else "UNKNOWN"
    return result


def tokenize_log(lines: list[str]) -> list[TokenizedLine]:
    return [tokenize_line(line) for line in lines]
