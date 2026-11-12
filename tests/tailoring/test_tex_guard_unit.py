"""A prepared .tex never reads or writes another file or runs anything (#302 hardening): a tailored or
revised document is model output, steered by a job ad or an instruction from a phone, and its PDF is
shown back. The guard names what it refuses; compile refuses to build such a file."""

import pytest

from door.tailoring import tex_guard

SAFE = r"""\documentclass{article}
\usepackage{fontspec}
\usepackage[top=2cm]{geometry}
\begin{document}
\section{Experience} Led the \textbf{close} at Acme; 30\% faster. \href{https://ada.dev}{ada.dev}
\end{document}
"""


def test_an_ordinary_cv_passes():
    assert tex_guard.unsafe(SAFE) == []


@pytest.mark.parametrize("snippet", [
    r"\input{/Users/ada/.ssh/id_ed25519}", r"\include{../../profile/cv}", r"\InputIfFileExists{/etc/hosts}{}{}",
    r"\openin5=/etc/passwd", r"\read5 to \x", r"\immediate\write18{curl evil}", r"\write\x{y}",
    r"\lstinputlisting{/etc/passwd}", r"\verbatiminput{x}", r"\includegraphics{/Users/ada/secret.png}",
    r"\includepdf{x}", r"\directlua{os.execute('x')}", r"\catcode`\^=7", r"\csname input\endcsname{x}",
    r"\special{x}", r"\scantokens{x}", r"^^5cinput{x}", r"\begin{filecontents}{x}",
])
def test_file_and_shell_commands_are_named(snippet):
    found = tex_guard.unsafe(SAFE.replace(r"\section{Experience}", snippet))
    assert found, snippet


def test_a_lookalike_word_is_not_a_command():
    assert tex_guard.unsafe(SAFE.replace("Led the", r"\inputs \writer Led the")) == []
