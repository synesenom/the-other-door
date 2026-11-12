"""What a prepared .tex may not contain (#302 hardening): anything that reads or writes another file or
runs a program. The documents are model output, steered by a job ad (an untrusted page) or an
instruction typed on a phone, and their PDFs are shown back; `\\input{~/.ssh/...}` would put a private
file on the page. The templates need none of it (only `\\usepackage`), and neither does a CV or a letter.
`compile` refuses a file that `unsafe` names anything in.
"""

from __future__ import annotations

import re

# File reads and writes, shell and Lua escapes, and the ways to spell them indirectly.
_COMMANDS = (
    "input", "include", "InputIfFileExists", "IfFileExists", "openin", "openout", "read", "readline",
    "write", "immediate", "newread", "newwrite", "directlua", "luaexec", "lstinputlisting", "verbatiminput",
    "VerbatimInput", "includegraphics", "includepdf", "special", "catcode", "csname", "scantokens",
    "ShellEscape", "pdfobj", "pdffiledump", "pdffilesize",
)
_COMMAND = re.compile(r"\\(" + "|".join(_COMMANDS) + r")(?![A-Za-z])")
_ENVIRONMENTS = re.compile(r"\\begin\{(filecontents\*?|verbatimwrite)\}")
_HEX = re.compile(r"\^\^[0-9a-fA-F]{2}|\^\^[@-_]")  # ^^5c is a backslash TeX reads past any word list


def unsafe(tex: str) -> list[str]:
    """The refused commands found in `tex`, in order, each once (`[]` when it is clean)."""
    found: list[str] = []
    for m in _COMMAND.finditer(tex):
        found.append("\\" + m.group(1))
    for m in _ENVIRONMENTS.finditer(tex):
        found.append(m.group(0))
    if _HEX.search(tex):
        found.append("^^ (a character written in hex)")
    return list(dict.fromkeys(found))
