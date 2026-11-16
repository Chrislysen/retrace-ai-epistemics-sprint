"""Verify public terminal-response docs and retained evidence, without API calls."""
from datetime import datetime, timezone
import hashlib
from html.parser import HTMLParser
import json
from pathlib import Path
import urllib.request

ROOT=Path(__file__).resolve().parents[1]


class Text(HTMLParser):
    def __init__(self):super().__init__();self.parts=[];self.skip=0
    def handle_starttag(self,tag,attrs):
        if tag in ("script","style"):self.skip+=1
    def handle_endtag(self,tag):
        if tag in ("script","style"):self.skip=max(0,self.skip-1)
    def handle_data(self,text):
        if not self.skip:self.parts.append(text)


def main():
    output=ROOT/"research/adaption-v6e-verification.json"
    if output.exists():raise FileExistsError("Evidence already exists; do not overwrite")
    urls={
      "https://docs.adaptionlabs.ai/api/resources/responses/methods/create":
         ["incomplete_details","max_output_tokens","input_tokens","output_tokens","total_tokens","incomplete"],
      "https://docs.adaptionlabs.ai/inference-stacks/generate-a-model-response/":
         ["response.completed","response.output_text.delta","stream"]}
    sources=[]
    for url,terms in urls.items():
        request=urllib.request.Request(url,headers={"User-Agent":"RETRACE-public-docs-verification/1"})
        with urllib.request.urlopen(request,timeout=30) as response:raw,status=response.read(),response.status
        p=Text();p.feed(raw.decode("utf-8"));text=" ".join(" ".join(p.parts).split())
        matches={term:term in text for term in terms}
        if status!=200 or not all(matches.values()):raise ValueError("Documentation check failed")
        sources.append({"url":url,"http_status":status,"body_sha256":hashlib.sha256(raw).hexdigest(),"required_terms_present":matches})
    models_path=ROOT/"data/frontier-v6c-model-availability.json"
    models=json.loads(models_path.read_text(encoding="utf-8"))
    selected=["deepseek-v4-flash","gemma-4-31b-it","glm-5.3-flash","qwen3.8-27b","glm-5.2"]
    limits={r["id"]:r["max_output_tokens"] for r in models["models"] if r["id"] in selected}
    if len(limits)!=5 or min(limits.values())<65536:raise ValueError("Output allowance unverified")
    artifact={"schema":"retrace.adaption-v6e-docs.v1","verified_at":datetime.now(timezone.utc).isoformat(),
      "authenticated_api_calls":0,"paid_calls":0,"sources":sources,
      "authenticated_metadata_snapshot":{"path":str(models_path.relative_to(ROOT)),"sha256":hashlib.sha256(models_path.read_bytes()).hexdigest(),"verified_at":models["verified_at"],"max_output_tokens":limits},
      "prospective_policy":"Only exact max_output_tokens terminal truncations with valid usage settle and continue; other incomplete or uncertain transport outcomes halt",
      "old_outcomes_unchanged":True,"new_max_output_tokens":65536,"new_max_timeout_seconds":1200,
      "reasoning_tokens":"Reported reasoning is within output_tokens; not added twice",
      "availability_caveat":"Maximum allowance is not a guarantee of completion or actual provider billing"}
    with output.open("x",encoding="utf-8",newline="\n") as stream:json.dump(artifact,stream,indent=2);stream.write("\n")
    print(json.dumps({"output":str(output),"sources":len(sources),"paid_calls":0}))


if __name__=="__main__":main()
