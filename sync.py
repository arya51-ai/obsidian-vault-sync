#!/usr/bin/env python3
"""
Obsidian Vault Sync - Convert Claude (and Copilot) sessions to Obsidian notes

Reads Claude Code transcripts (.jsonl) from ~/.claude/projects/{USER}/
and converts them to markdown notes in your Obsidian vault, classified
by project and linked to memory hubs. Memory index symlinks as a live link.

Optionally syncs exported GitHub Copilot Chat sessions (see COPILOT_DIR).

Usage:
    python3 sync.py

Configuration:
    Edit HOME, SRC_DIR, MEM_SRC, VAULT paths below to match your setup.
    Edit PROJECTS list to customize project classification.

Output structure:
    Vault/
    ├── Home.md
    ├── Memory/ (symlink to ~/.claude/.../memory)
    ├── Conversations/
    │   ├── _Index.md (searchable index)
    │   ├── YYYY-MM/
    │   │   └── YYYY-MM-DD - Title.md
    │   └── ...
    └── .sync/
        └── manifest.json (incremental tracking)
"""
import json, os, re, sys, glob
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

HOME     = Path.home()
SRC_DIR  = HOME / ".claude" / "projects" / "-Users-arya"
MEM_SRC  = SRC_DIR / "memory"
VAULT    = HOME / "ClaudeVault"
CONV_DIR = VAULT / "Conversations"
MANIFEST = VAULT / ".sync" / "manifest.json"
FORMAT   = 3   # bump to force re-conversion of every transcript

# ---- selective sync -------------------------------------------------------
# When True, only conversations containing VAULT_TAG anywhere in the text
# are synced. Add the tag in any message to mark a session as worth keeping.
SELECTIVE_MODE = False
VAULT_TAG      = "#vault"

# ---- copilot support (optional) -------------------------------------------
# Point to a directory of exported Copilot Chat JSON files to also sync them.
# Export from VS Code: Copilot Chat panel → "..." → "Export Chat..." → save as .json
# Set to None to disable.
COPILOT_DIR = None

# ---- project taxonomy: label, Memory hub note, tag, keywords -------------
# Order = tie-break priority (earlier wins an exact score tie).
# Customize this to match your projects.
PROJECTS = [
    {"label": "Example Project", "hub": "project_example", "tag": "example",
     "kw": ["example", "test"]},
]
MISC = {"label": "Misc", "hub": None, "tag": "misc", "kw": []}

def classify(title, body):
    """Classify conversation by keyword match (title 3x weight, body 1x)."""
    tl, bl = (title or "").lower(), (body or "").lower()
    best, best_score = None, 0
    for proj in PROJECTS:
        score = sum((3 if k in tl else 0) + (1 if k in bl else 0) for k in proj["kw"])
        if score > best_score:
            best, best_score = proj, score
    return best or MISC

# ---------- helpers ---------------------------------------------------------

def load_manifest():
    try:    return json.loads(MANIFEST.read_text())
    except Exception: return {}

def save_manifest(m):
    MANIFEST.parent.mkdir(parents=True, exist_ok=True)
    MANIFEST.write_text(json.dumps(m))

def sanitize(name, maxlen=70):
    """Remove invalid filename characters."""
    name = re.sub(r'[\\/:\*\?"<>\|\n\r\t]', ' ', name or '')
    name = name.replace('[', '(').replace(']', ')')
    name = re.sub(r'\s+', ' ', name).strip()
    return name[:maxlen].strip() or "Untitled"

def strip_noise(text):
    """Remove system tags from Claude transcripts."""
    if not text: return ""
    for tag in ("system-reminder", "command-message", "command-name",
                "local-command-stdout", "command-args"):
        text = re.sub(rf'<{tag}>.*?</{tag}>', '', text, flags=re.S)
    return text.strip()

def short(s, n=200):
    """Truncate string to n chars."""
    if not isinstance(s, str):
        s = json.dumps(s, ensure_ascii=False)
    s = re.sub(r'\s+', ' ', s).strip()
    return s[:n] + ('...' if len(s) > n else '')

def tool_summary(name, inp):
    """Format tool call as summary line."""
    inp = inp or {}
    detail = ""
    for k in ('command', 'file_path', 'path', 'pattern', 'query',
              'url', 'prompt', 'description', 'skill'):
        if k in inp and inp[k]:
            detail = f" - `{short(inp[k], 110)}`"
            break
    return f"\U0001F527 **{name}**{detail}"

def render_user(content):
    """Extract and format user turn content."""
    parts, human = [], False
    if isinstance(content, str):
        t = strip_noise(content)
        if t: human, parts = True, [t]
    elif isinstance(content, list):
        for b in content:
            if not isinstance(b, dict): continue
            if b.get('type') == 'text':
                t = strip_noise(b.get('text', ''))
                if t: human = True; parts.append(t)
            elif b.get('type') == 'tool_result':
                c = b.get('content', '')
                if isinstance(c, list):
                    c = ' '.join(x.get('text', '') for x in c if isinstance(x, dict))
                if c: parts.append(f"> ↳ *result:* {short(c, 200)}")
    return human, "\n\n".join(parts).strip()

def render_asst(content):
    """Extract and format assistant turn content."""
    parts = []
    if isinstance(content, str):
        if content.strip(): parts.append(content.strip())
    elif isinstance(content, list):
        for b in content:
            if not isinstance(b, dict): continue
            bt = b.get('type')
            if bt == 'text' and b.get('text', '').strip():
                parts.append(b['text'].strip())
            elif bt == 'tool_use':
                parts.append(tool_summary(b.get('name', '?'), b.get('input')))
    return "\n\n".join(parts).strip()

def parse_ts(ts):
    """Parse ISO timestamp or unix ms timestamp."""
    if not ts: return None
    try:
        if isinstance(ts, (int, float)):
            ts = ts / 1000 if ts > 1e10 else ts
            return datetime.fromtimestamp(ts, tz=timezone.utc)
        return datetime.fromisoformat(str(ts).replace('Z', '+00:00'))
    except Exception:
        return None

def write_note(turns, title, date, ym, sid, proj, source="claude"):
    """Write a conversation to a markdown note and return the output path."""
    hub = proj["hub"]
    outdir = CONV_DIR / ym
    outdir.mkdir(parents=True, exist_ok=True)
    out = outdir / f"{date} - {sanitize(title)}.md"
    if out.exists():
        out = outdir / f"{date} - {sanitize(title, 60)} ({sid[:8]}).md"

    src_tag = f"claude/conversation" if source == "claude" else f"copilot/conversation"
    fm = ['---',
          f'title: "{title.replace(chr(34), chr(39))}"',
          f'date: {date}',
          f'project: {proj["label"]}',
          f'source: {source}']
    if hub: fm.append(f'hub: "[[{hub}]]"')
    fm += [f'session: {sid}', f'turns: {len(turns)}',
           f'tags: [{src_tag}, project/{proj["tag"]}]', '---', '']

    L = fm + [f'# {title}', '',
              f'**Project:** ' + (f'[[{hub}]]' if hub else proj["label"]) +
              f'  ·  *{date}*  ·  *{len(turns)} turns*', '']
    last = None
    for kind, md in turns:
        if kind == 'user':
            if last != 'user': L += ['', '## \U0001F464 User', '']
            L += [md, '']; last = 'user'
        elif kind == 'asst':
            label = '\U0001F916 Claude' if source == 'claude' else '\U0001F916 Copilot'
            if last != 'asst': L += ['', f'## {label}', '']
            L += [md, '']; last = 'asst'
        else:
            L += [md, '']
    out.write_text("\n".join(L), encoding='utf-8')
    return out

# ---------- claude core -----------------------------------------------------

def convert(path, manifest):
    """Convert a single Claude .jsonl transcript to a markdown note."""
    sid   = Path(path).stem
    mtime = os.path.getmtime(path)
    rec   = manifest.get(sid)
    if rec and abs(rec.get('mtime', 0) - mtime) < 1:
        out = rec.get('out', '')
        if out == '' or Path(out).exists():
            return None  # unchanged since last run

    title = None; turns = []; first_ts = None; cwd = None; first_human = ""
    with open(path, encoding='utf-8', errors='replace') as fh:
        for line in fh:
            line = line.strip()
            if not line: continue
            try:    d = json.loads(line)
            except Exception: continue
            t = d.get('type')
            if t == 'ai-title':
                title = d.get('aiTitle') or title; continue
            if t not in ('user', 'assistant'): continue
            if d.get('isSidechain'): continue
            first_ts = first_ts or d.get('timestamp')
            cwd = d.get('cwd') or cwd
            content = (d.get('message') or {}).get('content')
            if t == 'user':
                human, md = render_user(content)
                if md:
                    turns.append(('user' if human else 'result', md))
                    if human and not first_human:
                        first_human = md[:500]
            else:
                md = render_asst(content)
                if md: turns.append(('asst', md))

    if not turns:
        manifest[sid] = {'mtime': mtime, 'out': ''}
        return None

    # selective sync: skip unless #vault appears somewhere in the conversation
    if SELECTIVE_MODE:
        all_text = " ".join(md for _, md in turns)
        if VAULT_TAG not in all_text:
            manifest[sid] = {'mtime': mtime, 'out': '', 'skipped': True}
            return None

    dt   = parse_ts(first_ts) or datetime.fromtimestamp(mtime, tz=timezone.utc)
    date = dt.strftime('%Y-%m-%d'); ym = dt.strftime('%Y-%m')
    if not title:
        seed  = next((x[1] for x in turns if x[0] == 'user'), turns[0][1])
        title = short(seed, 55)

    proj = classify(title, first_human + " " + (Path(cwd).name if cwd else ""))
    hub  = proj["hub"]

    out = write_note(turns, title, date, ym, sid, proj, source="claude")

    old = (rec or {}).get('out')
    if old and old != str(out) and Path(old).exists():
        try: Path(old).unlink()
        except Exception: pass
    manifest[sid] = {'mtime': mtime, 'out': str(out), 'date': date,
                     'project': proj["label"], 'hub': hub}
    return out

# ---------- copilot core ----------------------------------------------------

def _parse_copilot_file(path):
    """
    Try to parse a Copilot Chat exported JSON file.
    Handles the VS Code Chat export format (VS Code 1.85+).

    To export: open Copilot Chat panel → "..." menu → "Export Chat..." → save as .json
    """
    with open(path, encoding='utf-8', errors='replace') as fh:
        data = json.load(fh)

    # VS Code chat export: {"sessionId": "...", "requests": [...]}
    if isinstance(data, dict) and 'requests' in data:
        sid   = data.get('sessionId') or Path(path).stem
        title = data.get('title') or None
        turns = []
        first_ts = None

        for req in data.get('requests', []):
            # user message
            user_text = ""
            msg = req.get('message', {})
            if isinstance(msg, str):
                user_text = msg
            elif isinstance(msg, dict):
                user_text = msg.get('text') or msg.get('parts', [{}])[0].get('text', '') if msg.get('parts') else msg.get('text', '')

            if user_text:
                turns.append(('user', user_text.strip()))

            # timestamp (unix ms or ISO)
            if not first_ts:
                ts = req.get('timestamp') or req.get('time')
                first_ts = parse_ts(ts)

            # assistant response — several possible shapes
            resp = req.get('response') or req.get('result') or ""
            resp_text = ""
            if isinstance(resp, str):
                resp_text = resp
            elif isinstance(resp, list):
                parts = []
                for r in resp:
                    if isinstance(r, str):
                        parts.append(r)
                    elif isinstance(r, dict):
                        parts.append(r.get('value') or r.get('text') or
                                     r.get('content') or "")
                resp_text = "\n\n".join(p for p in parts if p)
            elif isinstance(resp, dict):
                resp_text = resp.get('value') or resp.get('text') or ""

            if resp_text:
                turns.append(('asst', resp_text.strip()))

        return sid, title, turns, first_ts

    # Array of message objects: [{"role": "user"|"assistant", "content": "..."}, ...]
    if isinstance(data, list) and data and isinstance(data[0], dict) and 'role' in data[0]:
        sid   = Path(path).stem
        turns = []
        first_ts = None
        for msg in data:
            role    = msg.get('role', '')
            content = msg.get('content') or msg.get('text') or ""
            if isinstance(content, list):
                content = " ".join(c.get('text', '') for c in content if isinstance(c, dict))
            if not content: continue
            if role == 'user':
                turns.append(('user', content.strip()))
            elif role in ('assistant', 'copilot', 'model'):
                turns.append(('asst', content.strip()))
            if not first_ts:
                first_ts = parse_ts(msg.get('timestamp') or msg.get('time'))
        return sid, None, turns, first_ts

    return None, None, [], None


def convert_copilot(path, manifest):
    """Convert a single exported Copilot Chat JSON file to a markdown note."""
    sid   = f"copilot_{Path(path).stem}"
    mtime = os.path.getmtime(path)
    rec   = manifest.get(sid)
    if rec and abs(rec.get('mtime', 0) - mtime) < 1:
        out = rec.get('out', '')
        if out == '' or Path(out).exists():
            return None

    raw_sid, title, turns, first_ts = _parse_copilot_file(path)
    if not turns:
        manifest[sid] = {'mtime': mtime, 'out': ''}
        return None

    if SELECTIVE_MODE:
        all_text = " ".join(md for _, md in turns)
        if VAULT_TAG not in all_text:
            manifest[sid] = {'mtime': mtime, 'out': '', 'skipped': True}
            return None

    dt   = first_ts or datetime.fromtimestamp(mtime, tz=timezone.utc)
    date = dt.strftime('%Y-%m-%d'); ym = dt.strftime('%Y-%m')
    if not title:
        seed  = next((md for kind, md in turns if kind == 'user'), turns[0][1])
        title = short(seed, 55)

    first_human = next((md for kind, md in turns if kind == 'user'), "")
    proj = classify(title, first_human[:500])
    out  = write_note(turns, title, date, ym, sid, proj, source="copilot")

    old = (rec or {}).get('out')
    if old and old != str(out) and Path(old).exists():
        try: Path(old).unlink()
        except Exception: pass
    manifest[sid] = {'mtime': mtime, 'out': str(out), 'date': date,
                     'project': proj["label"], 'hub': proj["hub"]}
    return out

# ---------- vault setup -----------------------------------------------------

def ensure_memory_link():
    """Symlink memory into vault."""
    link = VAULT / "Memory"
    if link.is_symlink() or link.exists(): return
    try: link.symlink_to(MEM_SRC, target_is_directory=True)
    except Exception as e: print(f"  ! memory symlink: {e}", file=sys.stderr)

def ensure_home():
    """Create Home.md if missing."""
    home = VAULT / "Home.md"
    if home.exists(): return
    home.write_text(
        "---\ntitle: Obsidian Vault\ntags: [claude/home]\n---\n\n"
        "# \U0001F3E0 Obsidian Vault\n\n"
        "Your Claude work in Obsidian.\n\n"
        "- \U0001F9E0 [[Memory/MEMORY|Memory index]] - live, synced from Claude\n"
        "- \U0001F4AC [[Conversations/_Index|Conversations index]] - every session\n\n"
        "Each conversation links to its project's Memory note.\n\n"
        "## Refresh\n\n"
        "```sh\npython3 sync.py\n```\n",
        encoding='utf-8')

def build_index(manifest):
    """Generate Conversations/_Index.md."""
    groups = defaultdict(list)
    for sid, rec in manifest.items():
        if sid == '_format': continue
        out = rec.get('out')
        if not out or not Path(out).exists(): continue
        groups[rec.get('project', 'Misc')].append(
            (rec.get('date', ''), Path(out).stem, rec.get('hub')))
    order = [p["label"] for p in PROJECTS] + ["Misc"]
    total = sum(len(v) for v in groups.values())
    L = ['---', 'title: Conversations Index', 'tags: [claude/index]', '---', '',
         f'# \U0001F4AC Conversations ({total})', '',
         'Grouped by project. Each heading links to that project\'s Memory hub.', '']
    for label in order:
        items = groups.get(label)
        if not items: continue
        hub = next((h for _, _, h in items if h), None)
        head = f'\n## {label} ({len(items)})'
        if hub: head += f'  ·  [[{hub}]]'
        L.append(head); L.append('')
        for _, stem, _ in sorted(items, reverse=True):
            L.append(f'- [[{stem}]]')
    (CONV_DIR / "_Index.md").write_text("\n".join(L), encoding='utf-8')

# ---------- main ------------------------------------------------------------

def main():
    CONV_DIR.mkdir(parents=True, exist_ok=True)
    ensure_memory_link(); ensure_home()
    manifest = load_manifest()
    if manifest.get('_format') != FORMAT:
        for m in CONV_DIR.rglob('*.md'):
            if m.name != '_Index.md':
                try: m.unlink()
                except Exception: pass
        manifest = {'_format': FORMAT}

    # Claude sessions
    files = sorted(glob.glob(str(SRC_DIR / "*.jsonl")))
    new = 0
    for i, p in enumerate(files):
        try:
            if convert(p, manifest): new += 1
        except Exception as e:
            print(f"  ! {Path(p).name}: {e}", file=sys.stderr)
        if (i + 1) % 150 == 0:
            print(f"  ...{i + 1}/{len(files)}")

    # Copilot sessions (opt-in)
    cop_new = 0
    if COPILOT_DIR:
        cop_files = sorted(glob.glob(str(Path(COPILOT_DIR) / "*.json")))
        if not cop_files:
            print(f"  ! COPILOT_DIR set but no .json files found in {COPILOT_DIR}",
                  file=sys.stderr)
        for p in cop_files:
            try:
                if convert_copilot(p, manifest): cop_new += 1
            except Exception as e:
                print(f"  ! copilot {Path(p).name}: {e}", file=sys.stderr)

    save_manifest(manifest)
    build_index(manifest)

    total = len([m for m in CONV_DIR.rglob('*.md') if not m.name.startswith('_')])
    print(f"\nVault: {VAULT}")
    mode  = f" [selective: {VAULT_TAG}]" if SELECTIVE_MODE else ""
    print(f"Claude: {len(files)} scanned | {new} new/updated{mode}")
    if COPILOT_DIR:
        print(f"Copilot: {cop_new} new/updated")
    print(f"Total notes: {total}")

if __name__ == "__main__":
    main()
