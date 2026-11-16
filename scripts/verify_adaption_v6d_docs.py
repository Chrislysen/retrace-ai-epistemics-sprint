"""Read-only public documentation verification; no model or authenticated calls."""
from datetime import datetime, timezone
import hashlib
from html.parser import HTMLParser
import json
from pathlib import Path
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
SOURCES = {
    "https://docs.adaptionlabs.ai/inference-stacks/generate-a-model-response/":
        ["response.output_text.delta", "response.completed", "stream", "error"],
    "https://docs.adaptionlabs.ai/api/resources/responses/methods/create":
        ["server-sent events", "stream", "input_tokens", "output_tokens"],
    "https://docs.adaptionlabs.ai/api/resources/responses":
        ["ResponseStreamEvent", "sequence_number", "response", "usage"],
}


class Text(HTMLParser):
    def __init__(self):
        super().__init__(); self.parts = []; self.skip = 0
    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style"): self.skip += 1
    def handle_endtag(self, tag):
        if tag in ("script", "style"): self.skip = max(0, self.skip-1)
    def handle_data(self, text):
        if not self.skip: self.parts.append(text)


def main():
    output = ROOT / "research/adaption-v6d-verification.json"
    if output.exists():
        raise FileExistsError("Documentation evidence already exists; do not overwrite frozen evidence")
    rows = []
    for url, terms in SOURCES.items():
        request = urllib.request.Request(url, headers={"User-Agent": "RETRACE-public-docs-verification/1"})
        with urllib.request.urlopen(request, timeout=30) as response:
            raw, status = response.read(), response.status
        parser = Text(); parser.feed(raw.decode("utf-8"))
        text = " ".join(" ".join(parser.parts).split())
        matches = {term: term in text for term in terms}
        if status != 200 or not all(matches.values()):
            raise ValueError("Public documentation verification failed")
        rows.append({"url": url, "http_status": status,
                     "body_sha256": hashlib.sha256(raw).hexdigest(), "required_terms_present": matches})
    artifact = {"schema": "retrace.adaption-v6d-docs.v1",
                "verified_at": datetime.now(timezone.utc).isoformat(),
                "authenticated_api_calls": 0, "paid_calls": 0, "sources": rows,
                "interpretation": {
                    "streaming_request": "stream=true requests semantic server-sent events",
                    "delta": "response.output_text.delta carries incremental text",
                    "completion": "response.completed is the successful lifecycle terminal event",
                    "failure": "error events indicate request failure",
                    "nested_response": "ResponseStreamEvent permits a nested response and optional sequence_number",
                    "usage": "The completed response exposes input/output usage; no preflight token endpoint assumed",
                    "timeout_remediation": "Streaming is a tested transport hypothesis, not a guarantee against gateway deadlines"
                },
                "client_integrity_rules_not_provider_guarantees": [
                    "Exactly one successful completion terminal; reject subsequent semantic events",
                    "When sequence numbers are present they must strictly increase",
                    "Concatenated output-text deltas must equal the final complete output text",
                    "Strict duplicate-key-free finite JSON and strict UTF-8",
                    "Optional [DONE] is accepted only after a proven completed terminal",
                    "No retries, redirects, nonstream fallback, partial-output completion, or missing-usage settlement"
                ]}
    with output.open("x", encoding="utf-8", newline="\n") as stream:
        json.dump(artifact, stream, ensure_ascii=False, indent=2); stream.write("\n")
    print(json.dumps({"output": str(output), "sources": len(rows), "paid_calls": 0}))


if __name__ == "__main__":
    main()
