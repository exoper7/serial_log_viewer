"""Parser logow ESP-IDF (i podobnych) z portu szeregowego.

Niezalezny od Qt - mozna go testowac i uzywac samodzielnie.

Rozpoznawane formaty:
  * ESP-IDF:  ``I (12345) TAG: wiadomosc``  (poziomy E/W/I/D/V, takze z kolorami ANSI)
  * wlasne:   ``[ERR] ...``, ``[WRN] ...``, ``[INF] ...``, ``[DBG] ...``
  * prefiks:  ``DEBUG: ...``, ``ERROR: ...``, ``WARNING: ...``, ``INFO: ...``
  * ROM/bootloader ESP32 (``ESP-ROM:``, ``rst:0x..``, ``load:0x..`` ...)
  * panic (Guru Meditation, Backtrace, abort()) - oznaczane jako bledy
Pozostale linie trafiaja do poziomu ``-`` (inne) bez tagu.

Linie sklejone przez rownolegle logowanie z kilku watkow, np.
``...buffer num: 32I (2927) https_server: ...`` sa dzielone na osobne wpisy.
"""

from __future__ import annotations

import re
from datetime import datetime

LEVELS = ("E", "W", "I", "D", "V", "-")
LEVEL_NAMES = {
    "E": "Error",
    "W": "Warning",
    "I": "Info",
    "D": "Debug",
    "V": "Verbose",
    "-": "Inne",
}
NO_TAG = ""  # wpisy bez rozpoznanego watku/tagu

_ANSI_RE = re.compile(r"\x1b\[[0-9;?]*[A-Za-z]")
_ESP_RE = re.compile(r"^([EWIDV]) \((\d+)\) ([^:]{1,48}?):\s?(.*)$")
# Poczatek rekordu ESP-IDF doklejony do poprzedniego tekstu (brak '\n').
_SPLIT_RE = re.compile(r"(?<=\S)(?=[EWIDV] \(\d+\) [^:\s][^:]{0,47}:)")
_BRACKET_RE = re.compile(
    r"^\[(ERR|ERROR|WRN|WAR|WARN|INF|INFO|DBG|DEBUG|VRB|VERBOSE)\]\s?(.*)$", re.I
)
_PREFIX_RE = re.compile(r"^(ERROR|WARNING|WARN|INFO|DEBUG)\s*:\s?(.*)$")
_ROM_RE = re.compile(
    r"^(ESP-ROM:|Build:|rst:0x|configsip:|clk_drv:|mode:\w+, clock|load:0x|entry 0x|"
    r"SPIWP:|Saved PC:|ets |waiting for download)"
)
_PANIC_RE = re.compile(
    r"(Guru Meditation Error|abort\(\) was called|^Backtrace:|assert failed|"
    r"Stack canary watchpoint|Stack smashing|Rebooting\.\.\.|CORRUPT HEAP|"
    r"Task watchdog got triggered|LoadProhibited|StoreProhibited|IllegalInstruction)"
)
# Prefiks czasu hosta zapisywany przez program do pliku logu.
_HOST_TS_RE = re.compile(r"^(\d{4}-\d{2}-\d{2}[ T]\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?) (.*)$")

_BRACKET_LEVEL = {
    "ERR": "E", "ERROR": "E",
    "WRN": "W", "WAR": "W", "WARN": "W",
    "INF": "I", "INFO": "I",
    "DBG": "D", "DEBUG": "D",
    "VRB": "V", "VERBOSE": "V",
}
_PREFIX_LEVEL = {"ERROR": "E", "WARNING": "W", "WARN": "W", "INFO": "I", "DEBUG": "D"}


class LogEntry:
    __slots__ = ("seq", "host_ts", "dev_ts", "level", "tag", "msg", "raw")

    def __init__(self, seq, host_ts, dev_ts, level, tag, msg, raw):
        self.seq = seq
        self.host_ts = host_ts  # datetime
        self.dev_ts = dev_ts    # int (ms od startu urzadzenia) lub None
        self.level = level      # jeden z LEVELS
        self.tag = tag          # nazwa watku/tagu lub NO_TAG
        self.msg = msg
        self.raw = raw

    def __repr__(self):
        return f"LogEntry({self.level} {self.tag!r} {self.msg!r})"


class LineAssembler:
    """Sklada bajty z portu w kompletne linie tekstu (UTF-8, '\\r\\n' / '\\n')."""

    def __init__(self):
        self._buf = bytearray()

    def feed(self, data: bytes) -> list[str]:
        self._buf.extend(data)
        lines = []
        while True:
            i = self._buf.find(b"\n")
            if i < 0:
                break
            chunk = bytes(self._buf[:i])
            del self._buf[: i + 1]
            lines.append(_decode(chunk))
        return lines

    def has_partial(self) -> bool:
        return bool(self._buf)

    def flush(self) -> str:
        chunk = bytes(self._buf)
        self._buf.clear()
        return _decode(chunk)


def _decode(chunk: bytes) -> str:
    return chunk.decode("utf-8", errors="replace").rstrip("\r")


class LogParser:
    """Zamienia linie tekstu na obiekty LogEntry (numeruje je kolejno)."""

    def __init__(self):
        self._seq = 0

    def parse(self, line: str, host_ts: datetime | None = None) -> list[LogEntry]:
        line = _ANSI_RE.sub("", line).replace("\r", "")
        if host_ts is None:
            host_ts = datetime.now()
        if not line.strip():
            return []
        parts = _SPLIT_RE.split(line)
        out = []
        for part in parts:
            if part.strip():
                out.append(self._parse_one(part, host_ts))
        return out

    def parse_file_line(self, line: str) -> list[LogEntry]:
        """Jak parse(), ale rozpoznaje prefiks czasu hosta zapisany przez ten program."""
        m = _HOST_TS_RE.match(line)
        if m:
            try:
                ts = datetime.fromisoformat(m.group(1).replace(" ", "T"))
                return self.parse(m.group(2), ts)
            except ValueError:
                pass
        return self.parse(line)

    def _parse_one(self, text: str, host_ts: datetime) -> LogEntry:
        self._seq += 1
        seq = self._seq

        m = _ESP_RE.match(text)
        if m:
            lvl, ts, tag, msg = m.groups()
            return LogEntry(seq, host_ts, int(ts), lvl, tag.strip(), msg, text)

        m = _BRACKET_RE.match(text)
        if m:
            lvl = _BRACKET_LEVEL[m.group(1).upper()]
            return LogEntry(seq, host_ts, None, lvl, NO_TAG, m.group(2), text)

        m = _PREFIX_RE.match(text)
        if m:
            return LogEntry(seq, host_ts, None, _PREFIX_LEVEL[m.group(1)], NO_TAG, m.group(2), text)

        if _ROM_RE.match(text):
            lvl = "W" if text.startswith("rst:0x") else "I"
            return LogEntry(seq, host_ts, None, lvl, "ROM", text, text)

        if _PANIC_RE.search(text):
            return LogEntry(seq, host_ts, None, "E", "PANIC", text, text)

        return LogEntry(seq, host_ts, None, "-", NO_TAG, text, text)
