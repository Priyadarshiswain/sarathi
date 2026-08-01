#!/usr/bin/env python3
"""render_report.py — deterministic injection of a Sarathi report payload
into skills/report/report-template.html (story SAR-04, §7).

Pure Python 3, stdlib only. No network calls, ever. Two pure functions:

    render_fragment(template_text, payload) -> str
    render_standalone(template_text, payload, title) -> str

plus a CLI wrapping both, invoked by skills/report/SKILL.md's publish step
exactly the way it already shells out to sarathi.py (design rule 1: same
template + same payload -> byte-identical output, every time).

This script performs exactly one deterministic string-replace of the
pinned marker `__SARATHI_REPORT_PAYLOAD__`, with the escaping the
reviewer's ruling requires (2026-08-01): every `<` in the serialized JSON
is replaced with the six-character JSON string escape `\\u003c`, so a
claim's free text (which can legitimately contain `</script>` or `<!--`,
e.g. inside a memory description) can never prematurely close the
injected <script> tag or shift the HTML parser into a script-data-escaped
state. `<` is a valid JSON string escape that round-trips through both
`json.loads` and `JSON.parse` back to `<` unchanged, and since `<` can
only ever occur inside string values in a `json.dumps` render, the
blanket replace is safe. This is deliberately never something an LLM does
by hand (design rule 3) -- hand-substituting a JSON blob into an HTML
string is exactly the kind of mechanical, escaping-sensitive step that
belongs in a two-line, unit-testable script instead. See SAR-04 §7.
"""
import argparse
import json
import sys

MARKER = "__SARATHI_REPORT_PAYLOAD__"


class TemplateError(Exception):
    """Raised when the template's injection marker is not present exactly
    once (design rule 2: fail loudly, never emptily) -- a template edited
    later that accidentally duplicates or removes the marker must be a
    loud script failure, never a silent injection into the wrong spot or
    a silent no-op leaving the marker un-replaced."""


def _serialize_payload(payload):
    """`json.dumps(payload, ensure_ascii=False)` with every literal `<`
    replaced by the six-character JSON string escape `\\u003c` (reviewer
    ruling, 2026-08-01 -- SAR-04 §7). Strictly stronger than escaping only
    `</`, because the HTML parser's script-data-escaped states are also
    triggered by a bare `<!--` inside a <script> block."""
    return json.dumps(payload, ensure_ascii=False).replace("<", "\\u003c")


def _inject(template_text, payload):
    count = template_text.count(MARKER)
    if count != 1:
        raise TemplateError(
            "template marker {0!r} must appear exactly once, found {1}"
            .format(MARKER, count)
        )
    return template_text.replace(MARKER, _serialize_payload(payload))


def render_fragment(template_text, payload):
    """The injected fragment, unmodified further -- the Artifact-tool
    publish path (SKILL.md §8) needs exactly this: no <!DOCTYPE>, <html>,
    <head>, or <body> tag of this script's own construction, matching the
    fragment contract the Artifact tool's own runtime expects."""
    return _inject(template_text, payload)


def render_standalone(template_text, payload, title):
    """The same injected fragment, wrapped in a minimal, generated
    standalone HTML document -- used only for the local-fallback path
    (SKILL.md §8), where the output must be directly openable in a
    browser with no external wrapper provided by anything else. Adds
    nothing but the shell: the injected payload content is byte-identical
    to what render_fragment() alone would produce for the same inputs.

    `title` is expected to be a fixed literal (`"Sarathi — Direction
    Report"`), never derived from run data -- per SAR-04 §7, this
    introduces no new escaping surface beyond what render_fragment()
    already handles, so no extra escaping is performed on it here."""
    fragment = render_fragment(template_text, payload)
    return (
        "<!DOCTYPE html>\n"
        "<html>\n"
        "<head>\n"
        '<meta charset="utf-8">\n'
        "<title>{0}</title>\n"
        "</head>\n"
        "<body>\n"
        "{1}\n"
        "</body>\n"
        "</html>\n"
    ).format(title, fragment)


def main(argv=None):
    parser = argparse.ArgumentParser(prog="render_report.py")
    parser.add_argument("--template", required=True,
                         help="path to skills/report/report-template.html")
    parser.add_argument("--payload", required=True,
                         help="path to a payload JSON file (SAR-04 §6 schema)")
    parser.add_argument("--standalone", metavar="TITLE", default=None,
                         help="wrap the injected fragment in a minimal standalone "
                              "HTML document with this title, instead of emitting "
                              "a bare fragment")
    parser.add_argument("--out", default=None,
                         help="write output to this path instead of stdout")
    args = parser.parse_args(argv)

    with open(args.template, "r", encoding="utf-8") as fh:
        template_text = fh.read()
    with open(args.payload, "r", encoding="utf-8") as fh:
        payload = json.load(fh)

    try:
        if args.standalone is not None:
            output = render_standalone(template_text, payload, args.standalone)
        else:
            output = render_fragment(template_text, payload)
    except TemplateError as e:
        print("error: {0}".format(e), file=sys.stderr)
        return 1

    if args.out:
        with open(args.out, "w", encoding="utf-8") as fh:
            fh.write(output)
    else:
        sys.stdout.write(output)
    return 0


if __name__ == "__main__":
    sys.exit(main())
