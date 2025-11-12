from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

def count_missing(po: Path) -> int:
    miss = 0
    in_header = False
    current_id = None
    with po.open('r', encoding='utf-8') as f:
        for line in f:
            line = line.rstrip('\n')
            if line.startswith('msgid '):
                current_id = line[7:-1] if line.endswith('"') else None
                in_header = (current_id == '')
            elif line.startswith('msgstr ') and current_id is not None:
                if not in_header and line.strip() == 'msgstr ""':
                    miss += 1
                current_id = None
                in_header = False
    return miss

def main():
    total = 0
    for po in (ROOT/"translations").rglob('messages.po'):
        m = count_missing(po)
        total += m
        print(f"{po}: {m} empty msgstr")
    print(f"TOTAL: {total}")

if __name__ == '__main__':
    main()

