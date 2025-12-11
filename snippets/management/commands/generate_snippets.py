import random
import secrets
import uuid
import hashlib
from collections import defaultdict
from datetime import date, datetime, timedelta

from django.core.management.base import BaseCommand
from django.db import transaction, connection
from django.utils import timezone
from cryptography.fernet import Fernet

from snippets.models import SnippetMetrics


class Command(BaseCommand):
    help = "Generate synthetic snippets with realistic distribution across August–November."

    def add_arguments(self, parser):
        parser.add_argument(
            "--count",
            type=int,
            default=3500,
            help="How many snippets to generate (default: 3500)",
        )
        parser.add_argument(
            "--start",
            type=lambda s: datetime.strptime(s, "%Y-%m-%d").date(),
            default=None,
            help="Start date for snippet creation window (YYYY-MM-DD). Defaults to Aug 1 of current year.",
        )
        parser.add_argument(
            "--end",
            type=lambda s: datetime.strptime(s, "%Y-%m-%d").date(),
            default=None,
            help="End date for snippet creation window (YYYY-MM-DD). Defaults to Nov 30 of current year.",
        )
        parser.add_argument(
            "--seed",
            type=int,
            default=None,
            help="Random seed for reproducibility.",
        )

    def handle(self, *args, **options):
        count = options["count"]
        start_date = options["start"]
        end_date = options["end"]
        seed = options["seed"]

        if seed is not None:
            random.seed(seed)

        today = timezone.now().date()
        if not start_date:
            start_date = date(today.year, 8, 1)
        if not end_date:
            end_date = date(today.year, 11, 30)
        if start_date >= end_date:
            raise ValueError("Start date must be before end date.")

        tz = timezone.get_current_timezone()
        day_weights = self._build_day_weights(start_date, end_date)
        hour_weights = self._build_hour_weights()
        language_weights = self._build_language_weights()

        # Precompute helpers
        access_tokens = set()
        existing_ids = []
        metrics_counter = defaultdict(int)

        snippets_payload = []
        encryptor = self._build_encryptor()

        for _ in range(count):
            created_at = self._choose_timestamp(day_weights, hour_weights, tz)
            expires_at = created_at + timedelta(hours=random.randint(12, 120))

            language = random.choices(
                list(language_weights.keys()), weights=language_weights.values(), k=1
            )[0]
            content = self._build_content(language)

            # Optional encryption aligned to observed ~3–4% usage
            is_encrypted = random.random() < 0.035 and encryptor is not None
            if is_encrypted:
                content = encryptor.encrypt(content.encode("utf-8")).decode("utf-8")

            one_time_view = random.random() < 0.05
            max_views = 1 if one_time_view else (random.randint(3, 25) if random.random() < 0.08 else None)
            allow_comments = random.random() > 0.15
            is_public = random.random() < 0.12

            parent_snippet_id = None
            version = 1
            if existing_ids and random.random() < 0.08:
                parent_snippet_id = random.choice(existing_ids)
                version = random.randint(2, 4)

            snippet_id = uuid.uuid4()
            access_token = self._unique_token(access_tokens)
            creator_ip_hash = self._maybe_ip_hash()
            creator_location = self._maybe_location()
            public_name = self._build_public_name(is_public, language)

            snippets_payload.append(
                (
                    str(snippet_id),
                    content,
                    language,
                    created_at,
                    expires_at,
                    0,  # view_count
                    access_token,
                    is_encrypted,
                    one_time_view,
                    None,  # password_hash
                    None,  # password_salt
                    parent_snippet_id,
                    version,
                    False,  # is_consumed
                    None,  # consumed_at
                    creator_ip_hash,
                    creator_location,
                    is_public,
                    public_name,
                    max_views,
                    allow_comments,
                )
            )

            existing_ids.append(str(snippet_id))
            metrics_counter[created_at.date()] += 1

        self.stdout.write(
            self.style.NOTICE(
                f"Prepared {len(snippets_payload)} snippets from {start_date} to {end_date}"
            )
        )

        self._insert_snippets(snippets_payload)
        self._update_metrics(metrics_counter)

        self.stdout.write(self.style.SUCCESS("Snippet generation complete."))

    def _build_language_weights(self):
        # Javascript and Python nearly even; tail reflects dashboard mix
        return {
            "javascript": 0.34,
            "python": 0.33,
            "text": 0.11,
            "cpp": 0.05,
            "json": 0.05,
            "shell": 0.04,
            "typescript": 0.04,
            "markdown": 0.04,
        }

    def _build_hour_weights(self):
        # Reflects chart: peaks at 10–11, secondary at 14, lighter 6 and 15–18, minimal overnight
        weights = {
            0: 0.01,
            1: 0.01,
            2: 0.01,
            3: 0.01,
            4: 0.015,
            5: 0.02,
            6: 0.12,
            7: 0.04,
            8: 0.07,
            9: 0.09,
            10: 0.2,
            11: 0.22,
            12: 0.07,
            13: 0.06,
            14: 0.14,
            15: 0.09,
            16: 0.07,
            17: 0.07,
            18: 0.07,
            19: 0.04,
            20: 0.03,
            21: 0.02,
            22: 0.02,
            23: 0.02,
        }
        total = sum(weights.values())
        return {h: w / total for h, w in weights.items()}

    def _build_day_weights(self, start_date, end_date):
        weekday_bias = {0: 1.15, 1: 1.15, 2: 1.12, 3: 1.05, 4: 1.0, 5: 0.55, 6: 0.65}
        month_bias = {8: 0.20, 9: 0.25, 10: 0.30, 11: 0.25}

        weights = {}
        cur = start_date
        while cur <= end_date:
            month_factor = month_bias.get(cur.month, 0.1)
            weekday_factor = weekday_bias[cur.weekday()]
            jitter = random.uniform(0.65, 1.35)
            weights[cur] = month_factor * weekday_factor * jitter
            cur += timedelta(days=1)

        total = sum(weights.values())
        return {d: w / total for d, w in weights.items()}

    def _choose_timestamp(self, day_weights, hour_weights, tz):
        chosen_day = random.choices(
            population=list(day_weights.keys()),
            weights=day_weights.values(),
            k=1,
        )[0]
        chosen_hour = random.choices(
            population=list(hour_weights.keys()),
            weights=hour_weights.values(),
            k=1,
        )[0]
        minute = random.randint(0, 59)
        second = random.randint(0, 59)
        naive_dt = datetime.combine(chosen_day, datetime.min.time()).replace(
            hour=chosen_hour, minute=minute, second=second
        )
        return timezone.make_aware(naive_dt, tz)

    def _unique_token(self, existing):
        token = secrets.token_urlsafe(32)
        while token in existing:
            token = secrets.token_urlsafe(32)
        existing.add(token)
        return token

    def _maybe_ip_hash(self):
        if random.random() < 0.25:
            fake_ip = f"192.168.{random.randint(1, 254)}.{random.randint(1, 254)}"
            return hashlib.sha256(fake_ip.encode()).hexdigest()
        return None

    def _maybe_location(self):
        if random.random() < 0.1:
            regions = ["US-CA", "US-NY", "CA-ON", "GB-LND", "IN-KA", "DE-BE"]
            return random.choice(regions)
        return None

    def _build_public_name(self, is_public, language):
        if not is_public:
            return None
        suffix = secrets.token_hex(3)
        return f"{language}-snippet-{suffix}"

    def _build_encryptor(self):
        try:
            from django.conf import settings

            key = getattr(settings, "ENCRYPTION_KEY", None)
            if not key:
                return None
            return Fernet(key.encode())
        except Exception:
            return None

    def _build_content(self, language):
        # Lightweight templates per language with placeholders for variation
        var_a = random.choice(["alpha", "beta", "gamma", "delta"])
        var_fn = random.choice(["throttle", "debounce", "memoize", "schedule"])
        var_key = random.choice(["featureFlags", "launchDarkly", "rollout"])

        js_templates = [
            f"""function {var_fn}(fn, wait) {{
  let inFlight = false;
  return (...args) => {{
    if (inFlight) return;
    inFlight = true;
    setTimeout(() => (inFlight = false), wait);
    return fn.apply(null, args);
  }};
}}

const cache = new Map();
export async function fetchJson(url) {{
  if (cache.has(url)) return cache.get(url);
  const res = await fetch(url);
  const data = await res.json();
  cache.set(url, data);
  return data;
}}""",
            """const retry = async (task, attempts = 3) => {
  let error;
  for (let i = 0; i < attempts; i++) {
    try {
      return await task();
    } catch (err) {
      error = err;
      await new Promise(r => setTimeout(r, 40 * (i + 1)));
    }
  }
  throw error;
};""",
            """export const backoff = (fn, limit = 4) => {
  let delay = 40;
  return async (...args) => {
    for (let i = 0; i < limit; i++) {
      try { return await fn(...args); }
      catch (err) { await new Promise(r => setTimeout(r, delay)); delay *= 2; }
    }
    throw new Error("exceeded backoff");
  };
};""",
        ]

        py_templates = [
            f"""from functools import lru_cache
from pathlib import Path

@lru_cache(maxsize=128)
def read_config(path: str) -> dict:
    data = Path(path).read_text()
    lines = [line.split("=", 1) for line in data.splitlines() if "=" in line]
    return {{k.strip(): v.strip() for k, v in lines}}

def chunked(iterable, size):
    for i in range(0, len(iterable), size):
        yield iterable[i:i+size]

TEAM = "{var_a}"
""",
            """import asyncio
from typing import Iterable, Awaitable, TypeVar

T = TypeVar("T")

async def gather_with_concurrency(limit: int, coros: Iterable[Awaitable[T]]) -> list[T]:
    sem = asyncio.Semaphore(limit)
    async def _bound(coro):
        async with sem:
            return await coro
    return await asyncio.gather(*(_bound(c) for c in coros))""",
            """def merge_dicts(a, b):
    out = a.copy()
    out.update(b)
    return out

def clamp(value, lo=0, hi=1):
    return max(lo, min(value, hi))
""",
        ]

        text_templates = [
            "Checklist:\n- Reproduce with fresh cache\n- Capture HAR + headers\n- Compare 304 vs 200 paths\n- Note proxy hops",
            "Notes: deploy pipeline tweaks\n- add smoke tests for /health\n- bump timeout to 60s\n- rotate webhook secret weekly\n",
            "Retro: keep shipping fast but small\n- freeze Friday past 15:00\n- always have rollback plan\n- audit error budget monthly",
        ]

        cpp_templates = [
            """#include <bits/stdc++.h>
using namespace std;

vector<int> twoSum(vector<int>& nums, int target) {
    unordered_map<int,int> seen;
    for (int i = 0; i < nums.size(); ++i) {
        int diff = target - nums[i];
        if (seen.count(diff)) return {seen[diff], i};
        seen[nums[i]] = i;
    }
    return {};
}""",
            """#include <chrono>
template <typename F>
auto measure(F&& fn) {
    auto start = std::chrono::steady_clock::now();
    auto result = fn();
    auto end = std::chrono::steady_clock::now();
    return std::chrono::duration_cast<std::chrono::microseconds>(end - start).count();
}""",
        ]

        json_templates = [
            '{\n  "' + var_key + '": ["beta-toggles", "fast-cache"],\n  "retries": 3,\n  "timeoutMs": 1200\n}',
            '{\n  "service": "ctrlv-backend",\n  "alerts": {"threshold": 0.15, "windowMinutes": 5}\n}',
            '{\n  "pipeline": "deploy",\n  "steps": ["lint", "test", "build", "ship"],\n  "owner": "' + var_a + '"\n}',
        ]

        shell_templates = [
            "export PATH=$HOME/.local/bin:$PATH\npip install --upgrade pip\npip install -r requirements.txt",
            "for file in $(find . -name '*.py'); do\n  python -m pyflakes \"$file\" || exit 1\ndone",
            "set -euo pipefail\nBRANCH=$(git rev-parse --abbrev-ref HEAD)\necho \"deploying $BRANCH\"\n",
        ]

        ts_templates = [
            """type Result<T> = { ok: true; value: T } | { ok: false; error: Error };
export function safeParse<T>(fn: () => T): Result<T> {
  try {
    return { ok: true, value: fn() };
  } catch (err) {
    return { ok: false, error: err as Error };
  }
}""",
            """export function pick<T extends object, K extends keyof T>(obj: T, keys: K[]): Pick<T, K> {
  const out = {} as Pick<T, K>;
  for (const k of keys) if (k in obj) out[k] = obj[k];
  return out;
}""",
        ]

        md_templates = [
            "# Incident Review\n\n- Impact: minor latency spike\n- Root cause: cache node recycle\n- Fix: warmed cache + tuned TTLs\n",
            f"# ADR: cache policy\n- Strategy: stale-while-revalidate\n- Owner: {var_a}\n- Rollout: canary + monitor p99\n",
        ]

        pools = {
            "javascript": js_templates,
            "python": py_templates,
            "text": text_templates,
            "cpp": cpp_templates,
            "json": json_templates,
            "shell": shell_templates,
            "typescript": ts_templates,
            "markdown": md_templates,
        }

        choices = pools.get(language.lower(), text_templates)
        base = random.choice(choices)

        # Light variation to avoid uniform length
        if language.lower() in {"javascript", "python", "shell"} and random.random() < 0.3:
            base += "\n# quick note: revisit perf later" if language != "javascript" else "\n// quick note: revisit perf later"
        if language.lower() == "text" and random.random() < 0.4:
            base += f"\nOwner: team-{random.choice(['alpha','beta','delta','gamma'])}"
        if language.lower() == "markdown" and random.random() < 0.4:
            base += "\n- Next: add SLO burn alerts"
        return base

    def _insert_snippets(self, payload):
        insert_sql = """
            INSERT INTO snippets (
                id, content, language, created_at, expires_at, view_count,
                access_token, is_encrypted, one_time_view, password_hash, password_salt,
                parent_snippet_id, version, is_consumed, consumed_at,
                creator_ip_hash, creator_location, is_public, public_name,
                max_views, allow_comments
            )
            VALUES (
                %s, %s, %s, %s, %s, %s,
                %s, %s, %s, %s, %s,
                %s, %s, %s, %s,
                %s, %s, %s, %s,
                %s, %s
            )
        """
        with transaction.atomic():
            with connection.cursor() as cursor:
                cursor.executemany(insert_sql, payload)

    def _update_metrics(self, metrics_counter):
        with transaction.atomic():
            for dt, count in metrics_counter.items():
                metrics, _ = SnippetMetrics.objects.get_or_create(
                    date=dt, defaults={"total_views": 0, "total_snippets": 0}
                )
                metrics.total_snippets += count
                metrics.save(update_fields=["total_snippets"])
