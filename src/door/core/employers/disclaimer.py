"""The disclaimer for an `unsure` source (docs/job-sites.md, "How The other door fetches"): the one text
every surface shows when the user turns such a source on (`init`, `/onboard`, the app's wizard and Profile,
`init --set`, the `init_profile` tool). Pure; the terms come from the source's registry entry."""


def text(label: str, terms_summary: str, terms_url: str) -> str:
    """The disclaimer for *label*: what its terms say (*terms_summary*), where they are (*terms_url*), and
    that using it is the user's decision, for personal use, at their own risk."""
    summary = terms_summary.strip().rstrip(".")
    return (
        f"{label}: {summary}. Terms: {terms_url}. The other door reads it logged out and slowly, for your own "
        "job search only. Turning it on is your decision and at your own risk; see LEGAL_DISCLAIMER.md. "
        "You can turn it off at any time."
    )
