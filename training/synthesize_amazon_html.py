#!/usr/bin/env python3
"""Generate synthetic Amazon-like HTML training examples from local captures.

The script never writes modified data unless --write is passed. It keeps source
files read-only, replaces detected visible sensitive/private values with
synthetic values, and writes a manifest containing labels and hashes only.
"""

from __future__ import annotations

import argparse
import hashlib
import html
import json
import random
import re
from dataclasses import dataclass
from html.parser import HTMLParser
from pathlib import Path
from typing import Iterable


DEFAULT_SOURCE_GLOB = str(Path(__file__).resolve().parent / "source-html" / "*.html")
DEFAULT_OUTPUT_DIR = Path(__file__).resolve().parent / "generated-html"
SKIP_TAGS = {"script", "style", "noscript", "svg", "canvas"}

STREET_SUFFIXES = (
    "Street",
    "St",
    "ST",
    "Avenue",
    "Ave",
    "AVE",
    "Road",
    "Rd",
    "RD",
    "Drive",
    "Dr",
    "DR",
    "Lane",
    "Ln",
    "LN",
    "Court",
    "Ct",
    "CT",
    "Boulevard",
    "Blvd",
    "BLVD",
    "Way",
    "WAY",
    "Place",
    "Pl",
    "PL",
    "Circle",
    "Cir",
    "CIR",
    "Parkway",
    "Pkwy",
    "PKWY",
    "Terrace",
    "Ter",
    "TER",
)

FIRST_NAMES = [
    "Maya",
    "Jordan",
    "Priya",
    "Noah",
    "Elena",
    "Marcus",
    "Sofia",
    "Theo",
    "Avery",
    "Nina",
    "Leo",
    "Camila",
]
LAST_NAMES = [
    "Patel",
    "Rivera",
    "Kim",
    "Johnson",
    "Morgan",
    "Nguyen",
    "Carter",
    "Singh",
    "Brooks",
    "Garcia",
]
STREETS = [
    "Maple",
    "Cedar",
    "Willow",
    "Hillcrest",
    "Pine",
    "Sunset",
    "Lakeview",
    "Market",
    "Riverside",
    "Oak",
]
CITIES = [
    ("Seattle", "WA", "98103"),
    ("Austin", "TX", "78704"),
    ("Denver", "CO", "80205"),
    ("Chicago", "IL", "60614"),
    ("Brooklyn", "NY", "11211"),
    ("Portland", "OR", "97214"),
    ("Atlanta", "GA", "30308"),
    ("San Diego", "CA", "92103"),
]
PRODUCTS = [
    "USB-C Travel Charger",
    "Organic Cotton Towels",
    "Noise Cancelling Earbuds",
    "Stainless Steel Water Bottle",
    "Desk Lamp with Wireless Charging",
    "Running Socks 6-Pack",
    "Mechanical Keyboard",
    "Ceramic Dinner Bowls",
]


@dataclass(frozen=True)
class Candidate:
    label: str
    value: str


@dataclass
class SyntheticProfile:
    full_name: str
    first_name: str
    last_name: str
    email: str
    phone: str
    street: str
    city: str
    state: str
    zip_code: str
    order_id: str
    tracking_id: str
    card_tail: str
    gift_card_code: str
    serial_number: str
    product: str


def make_profile(rng: random.Random) -> SyntheticProfile:
    first = rng.choice(FIRST_NAMES)
    last = rng.choice(LAST_NAMES)
    city, state, zip_code = rng.choice(CITIES)
    street_no = rng.randint(100, 9899)
    street = f"{street_no} {rng.choice(STREETS)} {rng.choice(STREET_SUFFIXES)}"
    if rng.random() < 0.35:
        street = f"{street} Apt {rng.randint(2, 48)}{rng.choice('ABCDEFGH')}"
    return SyntheticProfile(
        full_name=f"{first} {last}",
        first_name=first,
        last_name=last,
        email=f"{first.lower()}.{last.lower()}{rng.randint(10, 999)}@example.test",
        phone=f"({rng.randint(201, 989)}) {rng.randint(200, 999)}-{rng.randint(1000, 9999)}",
        street=street,
        city=city,
        state=state,
        zip_code=zip_code,
        order_id=f"{rng.randint(100, 999)}-{rng.randint(1000000, 9999999)}-{rng.randint(1000000, 9999999)}",
        tracking_id=f"TBA{rng.randint(100000000000, 999999999999)}",
        card_tail=f"{rng.randint(1000, 9999)}",
        gift_card_code=make_gift_card_code(rng),
        serial_number="".join(str(rng.randint(0, 9)) for _ in range(16)),
        product=rng.choice(PRODUCTS),
    )


def make_gift_card_code(rng: random.Random) -> str:
    alphabet = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
    groups = (4, 6, 4)
    return "-".join("".join(rng.choice(alphabet) for _ in range(size)) for size in groups)


def synthetic_for(label: str, profile: SyntheticProfile, rng: random.Random) -> str:
    if label == "PERSON_NAME":
        return profile.full_name
    if label == "FIRST_NAME":
        return profile.first_name
    if label == "EMAIL":
        return profile.email
    if label == "PHONE":
        return profile.phone
    if label == "STREET_ADDRESS":
        return profile.street
    if label == "FULL_ADDRESS":
        return f"{profile.street}, {profile.city}, {profile.state}, {profile.zip_code}, United States"
    if label == "CITY_STATE_ZIP":
        return f"{profile.city}, {profile.state} {profile.zip_code}"
    if label == "ZIP_CODE":
        return profile.zip_code
    if label == "ORDER_ID":
        return profile.order_id
    if label == "TRACKING_ID":
        return profile.tracking_id
    if label == "CARD_TAIL":
        return profile.card_tail
    if label == "GIFT_CARD_CODE":
        return profile.gift_card_code
    if label == "SERIAL_NUMBER":
        return profile.serial_number
    if label == "MONEY":
        return f"${rng.randint(4, 249)}.{rng.randint(0, 99):02d}"
    if label == "PRODUCT":
        return profile.product
    raise ValueError(f"unknown label: {label}")


PATTERNS: list[tuple[str, re.Pattern[str], int | None]] = [
    ("PERSON_NAME", re.compile(r"(?i)\bDelivering to\s+([A-Z][A-Za-z'-]{1,30}(?:\s+[A-Z][A-Za-z'-]{1,30}){1,3})\b"), 1),
    ("PERSON_NAME", re.compile(r"(?i)\b(?:Ship to|Shipping to|Recipient|Sold to):?\s+([A-Z][A-Za-z'-]{1,30}(?:\s+[A-Z][A-Za-z'-]{1,30}){1,3})\b"), 1),
    ("FIRST_NAME", re.compile(r"(?i)\bHello,\s*([A-Z][A-Za-z'-]{2,})\b"), 1),
    ("FIRST_NAME", re.compile(r"(?i)\bDeliver to\s+([A-Z][A-Za-z'-]{2,})\b"), 1),
    ("EMAIL", re.compile(r"\b[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}\b"), None),
    (
        "PHONE",
        re.compile(r"(?<!\d)(?:\+?1[\s.-]?)?(?:\(?\d{3}\)?[\s.-]?\d{3}[\s.-]?\d{4})(?!\d)"),
        None,
    ),
    ("ORDER_ID", re.compile(r"\b(?:\d{3}-\d{7}-\d{7}|D\d{2}-\d{7}-\d{7})\b"), None),
    ("TRACKING_ID", re.compile(r"\bTBA\d{10,15}\b"), None),
    (
        "FULL_ADDRESS",
        re.compile(
            r"\b\d{1,6}\s+[A-Z0-9][A-Z0-9'.-]*(?:\s+[A-Z0-9#'.-]+){0,9},\s*"
            r"[A-Z][A-Z .'-]+,\s*[A-Z]{2},?\s*\d{5}(?:-\d{4})?,\s*(?:United States|USA)\b",
            re.IGNORECASE,
        ),
        None,
    ),
    (
        "STREET_ADDRESS",
        re.compile(
            r"\b\d{1,6}\s+(?:[A-Z0-9][A-Za-z0-9'.-]*\s+){0,7}"
            rf"(?:{'|'.join(STREET_SUFFIXES)})\.?"
            r"(?:\s+(?:Apt|Apartment|Unit|Ste|Suite|#)\s*[A-Za-z0-9-]+)?\b",
            re.IGNORECASE,
        ),
        None,
    ),
    ("CITY_STATE_ZIP", re.compile(r"\b[A-Z][A-Za-z .'-]+,\s*[A-Z]{2},?\s+\d{5}(?:-\d{4})?\b"), None),
    (
        "CARD_TAIL",
        re.compile(r"(?i)(?:(?:ending|ending in|ending with|last four|visa|mastercard|amex|discover)[^\d]{0,24})(\d{4})\b"),
        1,
    ),
    (
        "GIFT_CARD_CODE",
        re.compile(r"(?i)\b(?:gift\s*card|claim\s*code|redemption\s*code|card\s*code)[:\s#-]*([A-Z0-9]{3,6}-[A-Z0-9]{4,8}-[A-Z0-9]{2,6})\b"),
        1,
    ),
    (
        "SERIAL_NUMBER",
        re.compile(r"(?i)\b(?:serial\s*(?:number|no\.?)?|card\s*number)[:\s#-]*(\d{10,20}|[A-Z0-9]{8,24})\b"),
        1,
    ),
    ("MONEY", re.compile(r"\$\s?\d{1,3}(?:,\d{3})*(?:\.\d{2})?"), None),
]


def amazon_sources(paths: Iterable[Path]) -> list[Path]:
    hints = ("amazon", "order", "orders", "addresses", "checkout", "package", "no title")
    return sorted(
        p
        for p in paths
        if p.is_file() and p.suffix.lower() in {".html", ".htm"} and any(h in p.name.lower() for h in hints)
    )


class VisibleTextParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._skip_depth = 0
        self.parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.lower() in SKIP_TAGS:
            self._skip_depth += 1

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() in SKIP_TAGS and self._skip_depth:
            self._skip_depth -= 1

    def handle_data(self, data: str) -> None:
        if self._skip_depth:
            return
        if data.strip():
            self.parts.append(data)


def visible_text_parts(raw_html: str) -> list[str]:
    parser = VisibleTextParser()
    parser.feed(raw_html)
    return parser.parts


def collect_candidates(raw_html: str) -> list[Candidate]:
    candidates: list[Candidate] = []
    visible_parts = [" ".join(text.split()) for text in visible_text_parts(raw_html)]
    candidates.extend(collect_raw_field_candidates(raw_html))
    for text in visible_text_parts(raw_html):
        normalized = " ".join(text.split())
        if not normalized:
            continue
        for label, pattern, group_index in PATTERNS:
            for match in pattern.finditer(normalized):
                if group_index is not None:
                    value = match.group(group_index)
                else:
                    value = match.group(0)
                add_candidate(candidates, label, value)
    add_known_full_name_variants(candidates, visible_parts)
    return dedupe_candidates(candidates)


def collect_raw_field_candidates(raw_html: str) -> list[Candidate]:
    candidates: list[Candidate] = []
    field_patterns = [
        ("PERSON_NAME", re.compile(r'id=["\']?address-ui-widgets-FullName\b[^>]*>(.*?)<', re.IGNORECASE | re.DOTALL)),
        ("STREET_ADDRESS", re.compile(r'id=["\']?address-ui-widgets-AddressLineOne\b[^>]*>(.*?)<', re.IGNORECASE | re.DOTALL)),
        ("CITY_STATE_ZIP", re.compile(r'id=["\']?address-ui-widgets-CityStatePostalCode\b[^>]*>(.*?)<', re.IGNORECASE | re.DOTALL)),
        ("PERSON_NAME", re.compile(r'\bdata-name=["\']([^"\']+)["\']', re.IGNORECASE)),
        ("STREET_ADDRESS", re.compile(r'\bdata-line1=["\']([^"\']+)["\']', re.IGNORECASE)),
        ("CITY_STATE_ZIP", re.compile(r'\bdata-city-state-zip=["\']([^"\']+)["\']', re.IGNORECASE)),
        ("PERSON_NAME", re.compile(r'>\s*Shipping to\s*</span>\s*<span\b[^>]*>(.*?)<', re.IGNORECASE | re.DOTALL)),
        ("PERSON_NAME", re.compile(r'popoverLabel["\']?\s*:\s*["\']Recipient address["\'][\s\S]{0,1200}?<a\b[^>]*>\s*([^<]+?)\s*<i\b', re.IGNORECASE)),
        ("PERSON_NAME", re.compile(r'>\s*Ship to\s*</span>[\s\S]{0,1200}?<a\b[^>]*>\s*([^<]+?)\s*<i\b', re.IGNORECASE)),
    ]
    for label, pattern in field_patterns:
        for match in pattern.finditer(raw_html):
            value = clean_html_field(match.group(1))
            if value:
                add_candidate(candidates, label, value)
    return candidates


def clean_html_field(value: str) -> str:
    without_tags = re.sub(r"<[^>]+>", " ", value)
    decoded = html.unescape(without_tags)
    return " ".join(decoded.split()).strip(" ,.;:")


def add_known_full_name_variants(candidates: list[Candidate], visible_parts: list[str]) -> None:
    known_names = {
        candidate.value
        for candidate in candidates
        if candidate.label == "PERSON_NAME" and " " in candidate.value
    }
    for name in known_names:
        for text in visible_parts:
            if text.strip(" ,.;:") == name:
                add_candidate(candidates, "PERSON_NAME", name)


def add_candidate(candidates: list[Candidate], label: str, value: str) -> None:
    cleaned = " ".join(value.split()).strip(" ,.;:")
    if len(cleaned) < 4:
        return
    candidates.append(Candidate(label, cleaned))


def dedupe_candidates(candidates: list[Candidate]) -> list[Candidate]:
    seen: set[tuple[str, str]] = set()
    output: list[Candidate] = []
    for candidate in sorted(candidates, key=lambda c: len(c.value), reverse=True):
        key = (candidate.label, candidate.value.lower())
        if key not in seen:
            seen.add(key)
            output.append(candidate)
    return output


def build_replacement_map(
    candidates: list[Candidate], profile: SyntheticProfile, rng: random.Random
) -> dict[str, tuple[str, str]]:
    replacements: dict[str, tuple[str, str]] = {}
    value_to_label: dict[str, str] = {}
    original_values = {candidate.value for candidate in candidates}
    used_synthetic: set[str] = set()
    for candidate in candidates:
        existing = value_to_label.get(candidate.value)
        if existing and existing != candidate.label:
            continue
        synthetic = unique_synthetic(candidate.label, profile, rng, original_values, used_synthetic)
        used_synthetic.add(synthetic)
        replacements[candidate.value] = (candidate.label, synthetic)
        value_to_label[candidate.value] = candidate.label
    return replacements


def unique_synthetic(
    label: str,
    profile: SyntheticProfile,
    rng: random.Random,
    originals: set[str],
    used_synthetic: set[str],
) -> str:
    synthetic = synthetic_for(label, profile, rng)
    for _ in range(25):
        if synthetic not in originals and (label in {"FIRST_NAME", "LAST_NAME", "PERSON_NAME"} or synthetic not in used_synthetic):
            return synthetic
        synthetic = synthetic_for(label, make_profile(rng), rng)
    if synthetic not in originals:
        return synthetic
    raise RuntimeError(f"Could not create non-colliding synthetic value for {label}")


def apply_replacements(raw_html: str, replacements: dict[str, tuple[str, str]]) -> str:
    output = raw_html
    for original in sorted(replacements, key=len, reverse=True):
        _label, synthetic = replacements[original]
        output = replace_all_forms(output, original, synthetic)
    return output


def replace_all_forms(raw_html: str, original: str, synthetic: str) -> str:
    forms = {
        original: synthetic,
        html.escape(original, quote=False): html.escape(synthetic, quote=False),
        html.escape(original, quote=True): html.escape(synthetic, quote=True),
        original.replace(" ", "&nbsp;"): synthetic.replace(" ", "&nbsp;"),
    }
    output = raw_html
    for old, new in forms.items():
        if old:
            output = output.replace(old, new)
    return output


def leakage_audit(generated: str, originals: Iterable[str]) -> list[str]:
    leaked = []
    for value in originals:
        if len(value) >= 4 and value in generated:
            leaked.append(short_hash(value))
    return sorted(set(leaked))


def short_hash(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:16]


def display_path(path: Path) -> str:
    try:
        return str(path.resolve().relative_to(Path.cwd().resolve()))
    except ValueError:
        return path.name


def write_example(
    index: int,
    source: Path,
    output_dir: Path,
    seed: int,
    write: bool,
) -> dict[str, object]:
    rng = random.Random(seed + index * 7919)
    raw_html = source.read_text(encoding="utf-8", errors="ignore")
    candidates = collect_candidates(raw_html)
    profile = make_profile(rng)
    replacements = build_replacement_map(candidates, profile, rng)
    generated = apply_replacements(raw_html, replacements)
    leaked_hashes = leakage_audit(generated, replacements.keys())
    out_name = f"amazon_synth_{index:05d}_{source.stem[:40].replace(' ', '_')}.html"
    out_path = output_dir / out_name
    if write and not leaked_hashes:
        output_dir.mkdir(parents=True, exist_ok=True)
        out_path.write_text(generated, encoding="utf-8")
    label_counts: dict[str, int] = {}
    for label, _synthetic in replacements.values():
        label_counts[label] = label_counts.get(label, 0) + 1
    preview = [
        {"label": label, "synthetic": synthetic}
        for _original, (label, synthetic) in list(replacements.items())[:12]
    ]
    return {
        "index": index,
        "source": source.name,
        "output": display_path(out_path) if write and not leaked_hashes else None,
        "would_write": display_path(out_path),
        "replacement_count": len(replacements),
        "label_counts": label_counts,
        "original_value_hashes": [
            {"label": label, "sha256_16": short_hash(original)}
            for original, (label, _synthetic) in replacements.items()
        ],
        "synthetic_preview": preview,
        "leakage_audit": {
            "passed": not leaked_hashes,
            "leaked_original_hashes": leaked_hashes,
        },
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-glob", default=DEFAULT_SOURCE_GLOB)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--count", type=int, default=6)
    parser.add_argument("--start-index", type=int, default=0)
    parser.add_argument("--seed", type=int, default=1729)
    parser.add_argument("--manifest", type=Path)
    parser.add_argument("--write", action="store_true", help="Actually write generated HTML and manifest.")
    parser.add_argument(
        "--include-all-html",
        action="store_true",
        help="Use every HTML file matched by --source-glob instead of Amazon-looking filenames only.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    matched = sorted(Path().glob(args.source_glob) if not args.source_glob.startswith("/") else Path("/").glob(args.source_glob[1:]))
    sources = matched if args.include_all_html else amazon_sources(matched)
    if not sources:
        raise SystemExit(f"No source HTML files matched: {args.source_glob}")
    manifest_path = args.manifest or args.output_dir / "manifest.json"
    end_index = args.start_index + args.count
    results = [
        write_example(i, sources[i % len(sources)], args.output_dir, args.seed, args.write)
        for i in range(args.start_index, end_index)
    ]
    manifest = {
        "mode": "write" if args.write else "dry-run",
        "source_count": len(sources),
        "sources": [p.name for p in sources],
        "count": args.count,
        "start_index": args.start_index,
        "end_index": end_index,
        "seed": args.seed,
        "safety": {
            "source_files_modified": False,
            "manifest_contains_raw_original_values": False,
            "leakage_audit_passed": all(r["leakage_audit"]["passed"] for r in results),
        },
        "examples": results,
    }
    print(json.dumps(manifest, indent=2))
    if args.write:
        args.output_dir.mkdir(parents=True, exist_ok=True)
        manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    return 0 if manifest["safety"]["leakage_audit_passed"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
