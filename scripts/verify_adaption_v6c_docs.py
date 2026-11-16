"""Read-only public documentation capture; never calls authenticated APIs."""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import hashlib
from html.parser import HTMLParser
import json
from pathlib import Path
import re
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
URLS = [
    "https://docs.adaptionlabs.ai/inference-stacks/models/",
    "https://docs.adaptionlabs.ai/inference-stacks/generate-a-model-response/",
    "https://docs.adaptionlabs.ai/api/resources/responses/methods/create",
    "https://docs.adaptionlabs.ai/api/resources/models/methods/list",
    "https://docs.adaptionlabs.ai/resources/faq/",
    "https://huggingface.co/api/models/zai-org/GLM-5.2",
]


class Text(HTMLParser):
    def __init__(self):
        super().__init__(); self.parts=[]; self.skip=0
    def handle_starttag(self, tag, attrs):
        if tag in ("script","style"): self.skip += 1
    def handle_endtag(self, tag):
        if tag in ("script","style"): self.skip = max(0,self.skip-1)
    def handle_data(self, data):
        if not self.skip: self.parts.append(data)


def fetch(url):
    with urllib.request.urlopen(url, timeout=30) as response:
        raw = response.read()
        status = response.status
    source = raw.decode("utf-8")
    if url.endswith("GLM-5.2"):
        model = json.loads(source)
        detail = {"safetensors": model.get("safetensors"), "sha": model.get("sha"),
                  "note": "Upstream repository metadata, not attestation of hosted deployment weights."}
    else:
        parser=Text(); parser.feed(source)
        text = re.sub(r"\s+", " ", " ".join(parser.parts))
        patterns = [r"Models Compare pricing.{0,600}", r"Prices are in.{0,1600}",
                    r"Context length is.{0,1000}", r"Lists the models currently.{0,900}",
                    r"max_output_tokens.{0,300}", r"input_tokens_details.{0,400}"]
        detail = {"excerpts": [m.group(0) for p in patterns for m in re.finditer(p, text)],
                  "documented_rate_limit_match": bool(re.search(r"rate.limit|requests per minute|tokens per minute",text,re.I)),
                  "documented_token_count_endpoint_match": bool(re.search(r"count_tokens|/tokenize|/tokens/count",text,re.I))}
    return {"url":url,"http_status":status,"body_sha256":hashlib.sha256(raw).hexdigest(),**detail}


if __name__ == "__main__":
    output = ROOT / "research/adaption-v6c-verification.json"
    if output.exists(): raise FileExistsError("Refusing to overwrite documentation evidence")
    with ThreadPoolExecutor(max_workers=3) as pool:
        sources = list(pool.map(fetch,URLS))
    artifact = {"schema":"retrace.adaption-v6c-docs.v1","verified_at":datetime.now(timezone.utc).isoformat(),
                "authenticated_api_calls":0,"paid_calls":0,"sources":sources,
                "limitations":["No numeric service RPM/TPM or a token-count endpoint was found in the inspected pages; this is not proof none exists.",
                               "Authenticated availability and per-model limits are separately saved by the parent in data/frontier-v6c-model-availability.json.",
                               "Responses compatibility is documented for the model catalogue, including DeepSeek despite its mode:chat metadata."]}
    with output.open("x",encoding="utf-8",newline="\n") as stream:
        json.dump(artifact,stream,ensure_ascii=False,indent=2);stream.write("\n")
    print(json.dumps({"sources":len(sources),"paid_calls":0,"output":str(output),"upstream_glm52":sources[-1]["safetensors"]}))
