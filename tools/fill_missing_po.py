from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]

HEADER_MARK = 'msgid ""'

def process_file(path: Path) -> int:
    text = path.read_text(encoding="utf-8")

    # Remove fuzzy flags
    text = re.sub(r"^#,\s*fuzzy\s*$", "", text, flags=re.MULTILINE)

    lines = text.splitlines()
    out = []
    i = 0
    changed = 0
    in_header = False
    current_id = None

    while i < len(lines):
        line = lines[i]
        out.append(line)

        if line.startswith("msgid "):
            # detect header
            in_header = (line.strip() == HEADER_MARK)
            # capture one-line msgid only
            m = re.match(r'^msgid\s+"(.*)"$', line)
            current_id = m.group(1) if m else None

        elif line.startswith("msgstr ") and not in_header:
            # If empty, fill with msgid value
            if current_id is not None and line.strip() == 'msgstr ""':
                out[-1] = f'msgstr "{current_id}"'
                changed += 1
            # reset state
            current_id = None
            in_header = False

        i += 1

    if changed:
        path.write_text("\n".join(out) + "\n", encoding="utf-8")
    return changed


def main():
    total = 0
    files = list((ROOT/"translations").rglob("messages.po"))
    for f in files:
        total += process_file(f)
    print(f"Filled {total} empty msgstr entries across {len(files)} files.")


if __name__ == "__main__":
    main()

