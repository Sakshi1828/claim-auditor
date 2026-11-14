"""LLM provider layer: Gemini (primary) and Groq (alternative) behind one interface, structured JSON only.

    from auditor.llm import LLMClient
    res = LLMClient.from_env().complete_json(system, user, schema, schema_name="claims")
    if res.ok: res.data            # validated against `schema`
    else:      res.error           # never raises; the caller falls back to the rule-based engine

Configuration (environment variables, or a .env file next to the project; see .env.example):
    LLM_PROVIDER=gemini|groq          primary provider (default gemini)
    LLM_FALLBACK=groq|gemini|none     used when the primary fails (default: the other one, if it has a key)
    GEMINI_API_KEY, GROQ_API_KEY      user-supplied keys: never logged, cached or exported
    GEMINI_MODEL=gemini-2.5-flash     GROQ_MODEL=openai/gpt-oss-120b
    LLM_TIMEOUT=90  LLM_MAX_RETRIES=3  LLM_MIN_INTERVAL=0.5  LLM_CACHE=1  LLM_CACHE_DIR=outputs/.llm_cache

Standard library HTTP and jsonschema only (no SDKs), so nothing new to install. Not used by the verification engine yet.
"""
from __future__ import annotations

import hashlib
import json
import os
import pathlib
import random
import re
import threading
import time
import urllib.error
import urllib.request
from dataclasses import asdict, dataclass, field

import jsonschema

ROOT = pathlib.Path(__file__).resolve().parents[1]
PROMPT_VERSION = "1"
_KEY_VARS = ("GEMINI_API_KEY", "GROQ_API_KEY")


# ------------------------------------------------------------------ configuration
def load_env(path: str | os.PathLike | None = None) -> None:
    """Read KEY=VALUE lines from .env into os.environ without overriding variables that are already set."""
    p = pathlib.Path(path) if path else ROOT / ".env"
    if not p.exists():
        return
    for line in p.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        v = re.split(r"\s+#", v, maxsplit=1)[0]                      # inline comment: KEY=value   # note
        k, v = k.strip().removeprefix("export ").strip(), v.strip().strip('"').strip("'")
        if k and k not in os.environ:
            os.environ[k] = v


def redact(text: str) -> str:
    """Remove every configured API key (and anything key-shaped) from a string before it is logged or stored."""
    s = str(text)
    for var in _KEY_VARS:
        v = os.environ.get(var)
        if v and len(v) >= 8:
            s = s.replace(v, "***")
    s = re.sub(r"AIza[0-9A-Za-z_\-]{20,}", "***", s)           # Google-style keys
    s = re.sub(r"gsk_[0-9A-Za-z]{20,}", "***", s)              # Groq-style keys
    s = re.sub(r"(?i)(bearer\s+|x-goog-api-key[\"':\s]+|key=)[^\s\"'&,}]+", r"\1***", s)
    return s


class LLMError(Exception):
    """Base error; messages are always redacted."""
    retryable = False

    def __init__(self, msg: str, status: int | None = None, retry_after: float | None = None):
        super().__init__(redact(msg))
        self.status, self.retry_after = status, retry_after


class LLMConfigError(LLMError):
    pass


class LLMRateLimited(LLMError):
    retryable = True


class LLMServerError(LLMError):
    retryable = True


class LLMTimeout(LLMError):
    retryable = True


class LLMBadResponse(LLMError):
    """Unparseable or schema-invalid output. Retried once (models occasionally slip), then reported."""
    retryable = True


# ------------------------------------------------------------------ HTTP with retries
def _post_json(url: str, headers: dict, body: dict, timeout: float) -> dict:
    req = urllib.request.Request(url, data=json.dumps(body).encode(), method="POST",
                                 headers={"Content-Type": "application/json", **headers})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        detail = e.read().decode("utf-8", "replace")[:500]
        ra = e.headers.get("Retry-After") if e.headers else None
        try:
            ra = float(ra) if ra else None
        except ValueError:
            ra = None
        if e.code == 429:
            raise LLMRateLimited(f"rate limited (HTTP 429): {detail}", 429, ra) from None
        if e.code >= 500:
            raise LLMServerError(f"provider error (HTTP {e.code}): {detail}", e.code, ra) from None
        if e.code in (401, 403):
            raise LLMConfigError(f"the API key was rejected (HTTP {e.code}). Check the key in .env.", e.code) from None
        raise LLMError(f"request rejected (HTTP {e.code}): {detail}", e.code) from None
    except (TimeoutError, urllib.error.URLError) as e:
        reason = getattr(e, "reason", e)
        if isinstance(reason, TimeoutError) or "timed out" in str(reason).lower():
            raise LLMTimeout(f"no answer within {timeout:.0f} s") from None
        raise LLMTimeout(f"network error: {reason}") from None
    except json.JSONDecodeError as e:
        raise LLMBadResponse(f"provider returned non-JSON: {e}") from None


class _RateGate:
    """At most one request per `min_interval` seconds per provider (simple client-side throttle)."""

    def __init__(self, min_interval: float):
        self.min_interval, self.last, self.lock = min_interval, 0.0, threading.Lock()

    def wait(self):
        with self.lock:
            delay = self.last + self.min_interval - time.monotonic()
            if delay > 0:
                time.sleep(delay)
            self.last = time.monotonic()


# ------------------------------------------------------------------ providers
class Provider:
    name = "base"
    key_var = ""
    default_model = ""
    model_var = ""

    def __init__(self, timeout: float, min_interval: float):
        self.timeout = timeout
        self.model = os.environ.get(self.model_var) or self.default_model
        self.gate = _RateGate(min_interval)

    @property
    def key(self) -> str | None:
        k = os.environ.get(self.key_var, "").strip()
        return None if not k or k.lower().startswith("your_") or "placeholder" in k.lower() else k

    def available(self) -> bool:
        return self.key is not None

    def call(self, system: str, user: str, schema: dict, schema_name: str) -> str:
        """Return the model's raw JSON text."""
        raise NotImplementedError


def to_gemini_schema(s: dict) -> dict:
    """JSON Schema -> Gemini responseSchema (OpenAPI subset: upper-case types, nullable instead of type lists)."""
    out = {}
    t = s.get("type")
    if isinstance(t, list):
        non_null = [x for x in t if x != "null"]
        t = non_null[0] if non_null else "string"
        out["nullable"] = True
    if t:
        out["type"] = t.upper()
    for k in ("enum", "description", "required"):
        if k in s:
            out[k] = [x for x in s[k] if x is not None] if k == "enum" else s[k]
    if "properties" in s:
        out["properties"] = {k: to_gemini_schema(v) for k, v in s["properties"].items()}
        out["propertyOrdering"] = list(s["properties"])
    if "items" in s:
        out["items"] = to_gemini_schema(s["items"])
    return out


class GeminiProvider(Provider):
    name, key_var, model_var, default_model = "gemini", "GEMINI_API_KEY", "GEMINI_MODEL", "gemini-2.5-flash"
    URL = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"

    def call(self, system, user, schema, schema_name):
        gen = {"temperature": 0, "responseMimeType": "application/json", "responseSchema": to_gemini_schema(schema)}
        budget = os.environ.get("GEMINI_THINKING_BUDGET")
        if budget not in (None, ""):
            gen["thinkingConfig"] = {"thinkingBudget": int(budget)}
        body = {"systemInstruction": {"parts": [{"text": system}]},
                "contents": [{"role": "user", "parts": [{"text": user}]}], "generationConfig": gen}
        # the key goes in a header, never in the URL, so it can't end up in proxy or error logs
        resp = _post_json(self.URL.format(model=self.model), {"x-goog-api-key": self.key}, body, self.timeout)
        try:
            cand = resp["candidates"][0]
            if cand.get("finishReason") not in (None, "STOP", "MAX_TOKENS"):
                raise LLMBadResponse(f"Gemini stopped early: {cand.get('finishReason')}")
            return "".join(p.get("text", "") for p in cand["content"]["parts"])
        except (KeyError, IndexError, TypeError):
            fb = resp.get("promptFeedback", {}).get("blockReason")
            raise LLMBadResponse(f"Gemini returned no content{f' (blocked: {fb})' if fb else ''}") from None


class GroqProvider(Provider):
    name, key_var, model_var, default_model = "groq", "GROQ_API_KEY", "GROQ_MODEL", "openai/gpt-oss-120b"
    URL = "https://api.groq.com/openai/v1/chat/completions"

    def call(self, system, user, schema, schema_name):
        msgs = [{"role": "system", "content": system}, {"role": "user", "content": user}]
        body = {"model": self.model, "messages": msgs, "temperature": 0,
                "response_format": {"type": "json_schema",
                                    "json_schema": {"name": schema_name, "schema": schema, "strict": True}}}
        effort = os.environ.get("GROQ_REASONING_EFFORT")
        if effort:
            body["reasoning_effort"] = effort
        headers = {"Authorization": f"Bearer {self.key}"}
        try:
            resp = _post_json(self.URL, headers, body, self.timeout)
        except LLMError as e:
            if e.status != 400 or "response_format" not in str(e) and "json_schema" not in str(e):
                raise
            # model without strict structured outputs: ask for a JSON object and put the schema in the prompt
            body["response_format"] = {"type": "json_object"}
            msgs[0] = {"role": "system", "content": system + "\n\nReturn only JSON matching this JSON Schema:\n"
                                                             + json.dumps(schema)}
            resp = _post_json(self.URL, headers, body, self.timeout)
        try:
            return resp["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError):
            raise LLMBadResponse("Groq returned no content") from None


PROVIDERS = {"gemini": GeminiProvider, "groq": GroqProvider}


# ------------------------------------------------------------------ client
@dataclass
class LLMResult:
    ok: bool
    data: dict | None = None
    provider: str | None = None
    model: str | None = None
    cached: bool = False
    seconds: float = 0.0
    attempts: list[dict] = field(default_factory=list)   # one per try: provider, error class, message (redacted)
    error: str | None = None

    def to_dict(self) -> dict:          # safe to log or export: no keys, no prompts
        return asdict(self)


class LLMClient:
    def __init__(self, primary: str = "gemini", fallback: str | None = None, timeout: float = 30, max_retries: int = 3,
                 min_interval: float = 0.5, cache_dir: str | os.PathLike | None = None, use_cache: bool = True):
        if primary not in PROVIDERS:
            raise LLMConfigError(f"LLM_PROVIDER must be one of {sorted(PROVIDERS)}, not {primary!r}")
        self.providers = [PROVIDERS[primary](timeout, min_interval)]
        if fallback and fallback != primary and fallback in PROVIDERS:
            self.providers.append(PROVIDERS[fallback](timeout, min_interval))
        self.max_retries = max(1, max_retries)
        self.use_cache = use_cache
        self.cache_dir = pathlib.Path(cache_dir) if cache_dir else ROOT / "outputs" / ".llm_cache"

    @classmethod
    def from_env(cls, env_file: str | os.PathLike | None = None) -> "LLMClient":
        load_env(env_file)
        e = os.environ.get
        primary = (e("LLM_PROVIDER") or "gemini").strip().lower()
        fb = (e("LLM_FALLBACK") or ("groq" if primary == "gemini" else "gemini")).strip().lower()
        return cls(primary=primary, fallback=None if fb in ("", "none", "off") else fb,
                   timeout=float(e("LLM_TIMEOUT") or 90), max_retries=int(e("LLM_MAX_RETRIES") or 3),
                   min_interval=float(e("LLM_MIN_INTERVAL") or 0.5),
                   cache_dir=e("LLM_CACHE_DIR") or None, use_cache=(e("LLM_CACHE") or "1") not in ("0", "false", "no"))

    def status(self) -> list[dict]:
        """Which providers are configured (never the keys themselves)."""
        return [{"provider": p.name, "model": p.model, "key_configured": p.available()} for p in self.providers]

    # ---- cache: validated answers only, keyed by everything that affects the output (not the key)
    def _cache_path(self, p: Provider, system: str, user: str, schema: dict) -> pathlib.Path:
        h = hashlib.sha256(json.dumps([PROMPT_VERSION, p.name, p.model, system, user, schema], sort_keys=True).encode())
        return self.cache_dir / f"{h.hexdigest()[:32]}.json"

    def complete_json(self, system: str, user: str, schema: dict, schema_name: str = "result") -> LLMResult:
        """Structured JSON from the first provider that answers validly. Never raises."""
        t0, attempts = time.monotonic(), []
        usable = [p for p in self.providers if p.available()]
        if not usable:
            names = ", ".join(p.key_var for p in self.providers)
            return LLMResult(ok=False, error=f"No LLM key configured ({names}); the rule-based engine is used alone.",
                             attempts=[{"provider": p.name, "error": "no key"} for p in self.providers])
        for p in usable:
            cpath = self._cache_path(p, system, user, schema)
            if self.use_cache and cpath.exists():
                try:
                    data = json.loads(cpath.read_text(encoding="utf-8"))["data"]
                    jsonschema.validate(data, schema)
                    return LLMResult(ok=True, data=data, provider=p.name, model=p.model, cached=True,
                                     seconds=round(time.monotonic() - t0, 3), attempts=attempts)
                except (ValueError, KeyError, jsonschema.ValidationError):
                    cpath.unlink(missing_ok=True)          # stale or corrupted entry
            bad_output_retries = 1
            for i in range(self.max_retries):
                try:
                    p.gate.wait()
                    raw = p.call(system, user, schema, schema_name)
                    try:
                        data = json.loads(raw)
                    except json.JSONDecodeError as e:
                        raise LLMBadResponse(f"model output is not valid JSON ({e.msg})") from None
                    try:
                        jsonschema.validate(data, schema)
                    except jsonschema.ValidationError as e:
                        where = "/".join(map(str, e.absolute_path)) or "(root)"
                        raise LLMBadResponse(f"model output failed validation at {where}: {e.message[:200]}") from None
                    if self.use_cache:
                        self.cache_dir.mkdir(parents=True, exist_ok=True)
                        cpath.write_text(json.dumps({"provider": p.name, "model": p.model, "prompt_version": PROMPT_VERSION,
                                                     "created": time.strftime("%Y-%m-%dT%H:%M:%S"), "data": data}),
                                         encoding="utf-8")
                    return LLMResult(ok=True, data=data, provider=p.name, model=p.model,
                                     seconds=round(time.monotonic() - t0, 3), attempts=attempts)
                except LLMError as e:
                    attempts.append({"provider": p.name, "try": i + 1, "error": type(e).__name__, "message": str(e)[:300]})
                    if isinstance(e, LLMBadResponse):
                        if bad_output_retries <= 0:
                            break
                        bad_output_retries -= 1
                    if not e.retryable or i == self.max_retries - 1:
                        break
                    # exponential backoff with jitter; honour Retry-After from rate limits (capped)
                    wait = min(30.0, e.retry_after if e.retry_after else (2 ** i) + random.uniform(0, 0.5))
                    time.sleep(wait)
                except Exception as e:  # noqa: BLE001  a provider bug must never crash the audit
                    attempts.append({"provider": p.name, "try": i + 1, "error": type(e).__name__,
                                     "message": redact(str(e))[:300]})
                    break
        last = attempts[-1] if attempts else {}
        return LLMResult(ok=False, seconds=round(time.monotonic() - t0, 3), attempts=attempts,
                         error=f"All providers failed; last error from {last.get('provider')}: {last.get('message')}. "
                               f"The rule-based engine is used alone.")
