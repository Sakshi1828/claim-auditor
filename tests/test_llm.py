"""Offline tests for the LLM provider layer: no keys or network needed (HTTP is faked).

  python tests/test_llm.py
Covers: missing/placeholder keys, Gemini and Groq request shapes, schema validation, retries with Retry-After,
fallback between providers, timeouts, rejected keys, caching, key redaction, and .env parsing.
"""
import io
import json
import os
import pathlib
import sys
import tempfile
import urllib.error

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))

from auditor import llm  # noqa: E402
from auditor.claim_schema import EXTRACTION, SYSTEM_PROMPT, user_prompt  # noqa: E402

GEMINI_KEY = "AIzaFAKEfakeFAKEfakeFAKEfakeFAKE1234567"     # fake test values, never real keys
GROQ_KEY = "gsk_FAKEfakeFAKEfakeFAKEfakeFAKE123456"
GOOD = {"claims": [{
    "claim_text": "Luminal A accounts for about 62% of tumors.", "is_factual_claim": True, "metric": "share",
    "data_layer": "clinical", "target": {"concept": "PAM50 subtype", "value": "Luminal A"},
    "population": "primary tumors with a subtype call",
    "claimed_value": {"number": 62, "unit": "percent", "comparator": "eq", "low": None, "high": None,
                      "approximate": True, "as_written": "about 62%"},
    "comparison_group": None, "needs_human_judgement": False}]}

calls, script = [], []


class FakeResp(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def gemini_ok(data=GOOD):
    return {"candidates": [{"finishReason": "STOP", "content": {"parts": [{"text": json.dumps(data)}]}}]}


def groq_ok(data=GOOD):
    return {"choices": [{"message": {"content": json.dumps(data)}}]}


def http_error(code, body="", retry_after=None):
    hdrs = {"Retry-After": str(retry_after)} if retry_after is not None else {}
    import email.message
    m = email.message.Message()
    for k, v in hdrs.items():
        m[k] = v
    return urllib.error.HTTPError("https://x", code, "err", m, io.BytesIO(body.encode()))


def fake_urlopen(req, timeout=None):
    calls.append({"url": req.full_url, "headers": dict(req.header_items()), "body": json.loads(req.data)})
    step = script.pop(0)
    if isinstance(step, Exception):
        raise step
    return FakeResp(json.dumps(step).encode() if isinstance(step, dict) else step)


llm.urllib.request.urlopen = fake_urlopen
llm.time.sleep = lambda s: calls.append({"slept": s})
bad = 0


def check(name, ok, detail=""):
    global bad
    print(f"{'ok  ' if ok else 'FAIL'} {name}" + (f"  ({detail})" if not ok and detail else ""))
    bad += 0 if ok else 1


def client(primary="gemini", fallback="groq", cache=None, retries=3):
    return llm.LLMClient(primary=primary, fallback=fallback, timeout=5, max_retries=retries, min_interval=0,
                         cache_dir=cache or tempfile.mkdtemp(), use_cache=cache is not None)


def reset(keys=True):
    calls.clear()
    script.clear()
    for k in ("GEMINI_API_KEY", "GROQ_API_KEY"):
        os.environ.pop(k, None)
    if keys:
        os.environ["GEMINI_API_KEY"], os.environ["GROQ_API_KEY"] = GEMINI_KEY, GROQ_KEY


SYS, USER = SYSTEM_PROMPT, user_prompt(["Luminal A accounts for about 62% of tumors."])

# 1. no keys / placeholder keys: graceful, no exception, no network
reset(keys=False)
r = client().complete_json(SYS, USER, EXTRACTION, "claims")
check("no keys: fails gracefully without calling the network", not r.ok and not calls and "No LLM key" in r.error)
os.environ["GEMINI_API_KEY"], os.environ["GROQ_API_KEY"] = "your_gemini_api_key_here", "your_groq_api_key_here"
r = client().complete_json(SYS, USER, EXTRACTION, "claims")
check(".env.example placeholders count as no key", not r.ok and not calls)

# 2. Gemini request shape and success
reset()
script.append(gemini_ok())
r = client().complete_json(SYS, USER, EXTRACTION, "claims")
c = calls[0]
check("Gemini: valid structured JSON returned", r.ok and r.provider == "gemini" and r.data == GOOD, r.error)
check("Gemini: key sent in a header, not in the URL", GEMINI_KEY not in c["url"] and
      c["headers"].get("X-goog-api-key") == GEMINI_KEY)
gc = c["body"]["generationConfig"]
check("Gemini: JSON mode, temperature 0, schema converted",
      gc["responseMimeType"] == "application/json" and gc["temperature"] == 0 and gc["responseSchema"]["type"] == "OBJECT")
check("Gemini: model is gemini-2.5-flash by default", "models/gemini-2.5-flash:generateContent" in c["url"])

# 3. Groq request shape (as primary)
reset()
script.append(groq_ok())
r = client(primary="groq", fallback="gemini").complete_json(SYS, USER, EXTRACTION, "claims")
c = calls[0]
check("Groq: valid structured JSON returned", r.ok and r.provider == "groq", r.error)
check("Groq: openai/gpt-oss-120b with strict json_schema",
      c["body"]["model"] == "openai/gpt-oss-120b" and c["body"]["response_format"]["type"] == "json_schema"
      and c["body"]["response_format"]["json_schema"]["strict"] is True)
check("Groq: key only in the Authorization header", c["headers"].get("Authorization") == f"Bearer {GROQ_KEY}")

# 4. rate limit with Retry-After, then success
reset()
script += [http_error(429, "slow down", retry_after=2), gemini_ok()]
r = client().complete_json(SYS, USER, EXTRACTION, "claims")
check("429: waits Retry-After then succeeds", r.ok and {"slept": 2.0} in calls and r.attempts[0]["error"] == "LLMRateLimited")

# 5. server errors exhaust retries, then fall back to Groq
reset()
script += [http_error(503), http_error(503), http_error(503), groq_ok()]
r = client().complete_json(SYS, USER, EXTRACTION, "claims")
check("5xx x3: retried with backoff, then fallback provider answers", r.ok and r.provider == "groq"
      and len([a for a in r.attempts if a["provider"] == "gemini"]) == 3)

# 6. rejected key: not retried, falls back
reset()
script += [http_error(401, f"bad key {GEMINI_KEY}"), groq_ok()]
r = client().complete_json(SYS, USER, EXTRACTION, "claims")
check("401: not retried, fallback used", r.ok and r.provider == "groq" and len(r.attempts) == 1)
check("401: key redacted from the error message", GEMINI_KEY not in json.dumps(r.to_dict()))

# 7. invalid output: non-JSON, then schema-invalid -> one retry, then fallback
reset()
bad_shape = {"claims": [{**GOOD["claims"][0], "metric": "vibes"}]}
script += [{"candidates": [{"finishReason": "STOP", "content": {"parts": [{"text": "not json"}]}}]},
           gemini_ok(bad_shape), groq_ok()]
r = client().complete_json(SYS, USER, EXTRACTION, "claims")
check("bad output: retried once, then fallback", r.ok and r.provider == "groq"
      and [a["error"] for a in r.attempts] == ["LLMBadResponse", "LLMBadResponse"], r.attempts)
check("bad output: validation error says where", "claims/0/metric" in r.attempts[1]["message"], r.attempts[1]["message"])

# 8. timeouts on both providers: graceful failure
reset()
script += [TimeoutError()] * 6
r = client().complete_json(SYS, USER, EXTRACTION, "claims")
check("timeouts everywhere: ok=False, clear error, no exception", not r.ok and "All providers failed" in r.error
      and len(r.attempts) == 6)

# 9. cache: second identical call is served locally; files hold no key
reset()
cdir = tempfile.mkdtemp()
script.append(gemini_ok())
r1 = client(cache=cdir).complete_json(SYS, USER, EXTRACTION, "claims")
r2 = client(cache=cdir).complete_json(SYS, USER, EXTRACTION, "claims")
blob = "".join(p.read_text() for p in pathlib.Path(cdir).glob("*.json"))
check("cache: second call served from cache, one network request", r1.ok and r2.ok and r2.cached and
      len([c for c in calls if "url" in c]) == 1)
check("cache: no API key in cached files", GEMINI_KEY not in blob and GROQ_KEY not in blob and '"data"' in blob)

# 10. redaction and .env parsing
check("redact() removes configured and key-shaped secrets",
      "***" in llm.redact(f"x {GEMINI_KEY} y Bearer {GROQ_KEY}") and GEMINI_KEY not in llm.redact(GEMINI_KEY))
tmp = pathlib.Path(tempfile.mkdtemp()) / ".env"
tmp.write_text("LLM_TIMEOUT=12   # seconds\nexport LLM_TEST_X='hello'\n# comment\nGEMINI_API_KEY=should_not_override\n")
os.environ.pop("LLM_TIMEOUT", None)
llm.load_env(tmp)
check(".env: inline comments, quotes and export handled; existing vars not overridden",
      os.environ.get("LLM_TIMEOUT") == "12" and os.environ.get("LLM_TEST_X") == "hello"
      and os.environ["GEMINI_API_KEY"] == GEMINI_KEY)
os.environ.pop("LLM_TIMEOUT", None)
check("schema rejects unknown fields", not llm.jsonschema.Draft202012Validator(EXTRACTION).is_valid(
    {"claims": [{**GOOD["claims"][0], "extra": 1}]}))

print("ALL PASSED" if not bad else f"{bad} FAILURE(S)")
sys.exit(1 if bad else 0)
