"""Reads HTML forms the way a browser would submit them (test helper)."""
from __future__ import annotations

from html.parser import HTMLParser


class FormReader(HTMLParser):
    """Collects what a browser would submit for each <form>: text/hidden
    input values and the selected option of each <select>."""

    def __init__(self) -> None:
        super().__init__()
        self.forms: list[dict] = []
        self._form: dict | None = None
        self._select: str | None = None
        self._first_option: str | None = None
        self._selected: str | None = None

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag == "form":
            self._form = {"action": a.get("action"), "fields": {}}
            self.forms.append(self._form)
        elif self._form is None:
            return
        elif tag == "input" and a.get("name") and a.get("type", "text") in ("text", "hidden"):
            self._form["fields"][a["name"]] = a.get("value", "")
        elif tag == "select":
            self._select, self._first_option, self._selected = a.get("name"), None, None
        elif tag == "option" and self._select is not None:
            value = a.get("value", "")
            if self._first_option is None:
                self._first_option = value
            if "selected" in a:
                self._selected = value

    def handle_endtag(self, tag):
        if tag == "select" and self._form is not None and self._select:
            chosen = self._selected if self._selected is not None else self._first_option
            self._form["fields"][self._select] = chosen or ""
            self._select = None
        elif tag == "form":
            self._form = None


def forms_posting_to(page: str, action: str) -> list[dict[str, str]]:
    reader = FormReader()
    reader.feed(page)
    return [dict(f["fields"]) for f in reader.forms if f["action"] == action]


def form_posting_to(page: str, action: str) -> dict[str, str]:
    matches = forms_posting_to(page, action)
    assert len(matches) == 1, f"expected one form posting to {action}, found {len(matches)}"
    return matches[0]
