#!/usr/bin/env python3
"""
Scan weekly diaries in an Obsidian vault, discover mentioned cases
(under 10 🎯 Project/ or 20 🥅 Area/), and generate a structured report
for later AI digest generation.
"""

import argparse
import re
from collections import defaultdict
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Optional

DEFAULT_VAULT = Path("/Users/jim/Library/Mobile Documents/iCloud~md~obsidian/Documents/JimBox")
DIARY_SUBDIR = "♻️复盘/01 日记"
CASE_PREFIXES = ("10 🎯 Project/", "20 🥅 Area/")
REPORT_DIR = Path(__file__).parent / ".claude" / "case-weekly"

WIKILINK_RE = re.compile(r"\[\[([^\]|#]+)(?:#[^\]|]*)?(?:\|[^\]]*)?\]\]")


def parse_date_from_diary(diary_path: Path) -> Optional[date]:
    """Extract date from filename like 🎨2026_WK14_D5_2026-04-03.md,
    fallback to frontmatter 🌻日期🌻."""
    m = re.search(r"_(\d{4}-\d{2}-\d{2})\.md$", diary_path.name)
    if m:
        return datetime.strptime(m.group(1), "%Y-%m-%d").date()

    try:
        text = diary_path.read_text(encoding="utf-8")
    except Exception:
        return None

    m = re.search(r"^🌻日期🌻:\s*(\d{4}-\d{2}-\d{2})", text, re.MULTILINE)
    if m:
        return datetime.strptime(m.group(1), "%Y-%m-%d").date()
    return None


def _build_case_index(vault: Path) -> dict[str, list[Path]]:
    """Index all markdown files by basename and relative path string."""
    index: dict[str, list[Path]] = defaultdict(list)
    for md_file in vault.rglob("*.md"):
        rel = md_file.relative_to(vault)
        index[md_file.stem].append(rel)
        index[str(rel.with_suffix(""))].append(rel)
    return index


def resolve_wikilink(link_text: str, index: dict[str, list[Path]]) -> Optional[Path]:
    clean = link_text.strip()
    candidates: list[Path] = []

    if clean in index:
        candidates.extend(index[clean])

    if not candidates:
        for name, paths in index.items():
            if name.lower() == clean.lower():
                candidates.extend(paths)

    case_hits = [p for p in candidates if str(p).startswith(CASE_PREFIXES)]
    return case_hits[0] if case_hits else None


def extract_snippets(content: str, case_name: str) -> list[dict]:
    """Extract paragraphs where the case is mentioned, ignoring bare links."""
    pattern = re.compile(
        r"\[\[" + re.escape(case_name) + r"(?:#[^\]|]*)?(?:\|[^\]]*)?\]\]"
    )
    lines = content.split("\n")
    snippets = []
    current_heading: str | None = None

    for i, line in enumerate(lines):
        if re.match(r"^#{1,6}\s+", line):
            current_heading = re.sub(r"^#+\s+", "", line).strip()
            continue

        if not pattern.search(line):
            continue

        bare = pattern.sub("", line).strip()
        indent_match = re.match(r"^(\s*)", line)
        indent = indent_match.group(1) if indent_match else ""
        snippet_lines = [line]
        has_sub = False

        for j in range(i + 1, len(lines)):
            nxt = lines[j]
            if nxt.strip() == "":
                snippet_lines.append(nxt)
                continue
            nxt_indent = (re.match(r"^(\s*)", nxt) or [""])[0]
            if len(nxt_indent) > len(indent):
                snippet_lines.append(nxt)
                has_sub = True
            else:
                break

        if bare == "" and not has_sub:
            continue

        snippets.append({"heading": current_heading, "text": "\n".join(snippet_lines)})

    return snippets


def main() -> None:
    parser = argparse.ArgumentParser(description="Discover weekly case mentions from diaries.")
    parser.add_argument("--since", type=str, help="Start date YYYY-MM-DD")
    parser.add_argument("--until", type=str, help="End date YYYY-MM-DD")
    parser.add_argument("--vault", type=Path, default=DEFAULT_VAULT, help="Obsidian vault path")
    parser.add_argument("--output-dir", type=Path, default=REPORT_DIR, help="Directory to write the report")
    args = parser.parse_args()

    today = datetime.now().date()
    since = datetime.strptime(args.since, "%Y-%m-%d").date() if args.since else today - timedelta(days=today.weekday())
    until = datetime.strptime(args.until, "%Y-%m-%d").date() if args.until else today + timedelta(days=6 - today.weekday())

    diary_folder = args.vault / DIARY_SUBDIR
    diaries: list[tuple[date, Path]] = []
    for f in sorted(diary_folder.iterdir()):
        if not f.is_file() or f.suffix.lower() != ".md":
            continue
        d = parse_date_from_diary(f)
        if d and since <= d <= until:
            diaries.append((d, f))

    case_index = _build_case_index(args.vault)
    case_data: dict[str, dict[date, list[dict]]] = defaultdict(lambda: defaultdict(list))

    for diary_date, diary_path in diaries:
        content = diary_path.read_text(encoding="utf-8")
        links = WIKILINK_RE.findall(content)
        seen_cases: set[str] = set()

        for link in links:
            resolved = resolve_wikilink(link.strip(), case_index)
            if resolved:
                seen_cases.add(resolved.stem)

        for case_name in seen_cases:
            snippets = extract_snippets(content, case_name)
            if snippets:
                case_data[case_name][diary_date].extend(snippets)

    year, week, _ = since.isocalendar()
    output_dir = args.output_dir
    output_dir.mkdir(parents=True, exist_ok=True)
    report_path = output_dir / f"{year}-W{week:02d}_report.md"

    with open(report_path, "w", encoding="utf-8") as f:
        f.write(f"# Weekly Case Snapshot {year}-W{week:02d}\n")
        f.write(f"\n- **日期范围:** {since} ~ {until}\n")
        f.write(f"- **扫描日记数:** {len(diaries)}\n")
        f.write(f"- **发现 Case 数:** {len(case_data)}\n\n")

        for case_name in sorted(case_data.keys()):
            f.write(f"## Case: {case_name}\n")
            for d in sorted(case_data[case_name].keys()):
                for snip in case_data[case_name][d]:
                    heading = snip["heading"] or "（无标题）"
                    f.write(f"\n### {d} @ {heading}\n")
                    f.write(snip["text"])
                    f.write("\n")
            f.write("\n---\n\n")

    print(f"Report generated: {report_path}")


if __name__ == "__main__":
    main()
