# obsidian-vault-sync

Automatically convert every Claude (and Copilot) conversation into a searchable, linked knowledge base in your Obsidian vault.

Two things make this different from the other sync tools out there:

1. **Your Claude memory lives inside the vault.** The memory index is symlinked directly — so the notes Claude keeps about your work are real Obsidian notes you can browse, backlink, and put in your graph. They stay current without any extra steps.
2. **Classification uses zero API calls.** Projects are assigned by keyword scoring (title weighted 3×, body 1×) — fast, deterministic, free to run. No model calls.

---

## What it does

- Converts each Claude Code session to a markdown note, organized by project and date
- Symlinks your Claude memory folder into the vault so it becomes part of your graph
- Classifies conversations by project automatically (no API calls)
- Only processes new or changed transcripts on each run (manifest-based tracking)
- Notes update when a conversation continues — it's not a static one-time export
- Optional: sync exported GitHub Copilot Chat sessions into the same vault
- Optional: selective sync — only save conversations you tag with `#vault`

---

## Why this vs other sync tools

| Feature | obsidian-vault-sync | Most others |
|---|---|---|
| Memory symlink (Claude's memory = vault notes) | ✅ | ❌ |
| Zero API calls for classification | ✅ | ❌ (call a model) |
| Notes update as conversations continue | ✅ | Static snapshot |
| Copilot Chat support | ✅ | ❌ |
| Selective sync (`#vault` tag) | ✅ | ❌ |
| MCP tool (sync from inside Claude) | ✅ | ❌ |
| Pure Python, no external dependencies | ✅ | Varies |

---

## How incremental sync works

Every run, the script checks a manifest file (`vault/.sync/manifest.json`) that stores the last-seen modification timestamp for each transcript. If the transcript hasn't changed, the note is skipped. If a conversation continues and Claude adds new messages, the transcript's mtime changes, the manifest sees the delta, and the note is updated on the next sync.

This means:
- **Active conversations stay current** as long as you sync on a schedule (see [Auto-sync](#auto-sync))
- First run processes everything. After that, only new or changed sessions are touched.
- To force a full rebuild, bump `FORMAT` in `sync.py` by 1.

---

## Quick start

### 1. Clone

```bash
git clone https://github.com/arya51-ai/obsidian-vault-sync.git
cd obsidian-vault-sync
```

### 2. Configure

Edit the paths at the top of `sync.py`:

```python
SRC_DIR = Path.home() / ".claude" / "projects" / "-Users-yourname"
MEM_SRC = SRC_DIR / "memory"
VAULT   = Path.home() / "MyVault"
```

### 3. Set up your projects

Edit the `PROJECTS` list:

```python
PROJECTS = [
    {"label": "My App", "hub": "project_myapp", "tag": "myapp",
     "kw": ["my app", "backend", "auth"]},
    {"label": "Work Notes", "hub": "project_work", "tag": "work",
     "kw": ["standup", "sprint", "jira"]},
]
```

- `label` — display name in the vault
- `hub` — your memory note filename (without `.md`)
- `tag` — Obsidian tag for filtering
- `kw` — keywords that identify this project (title match = 3×, body = 1×)

### 4. Run

```bash
python3 sync.py
```

```
Vault: /Users/you/MyVault
Claude: 127 scanned | 12 new/updated
Total notes: 89
```

Open your vault in Obsidian — `Home.md` is the entry point, `Conversations/_Index.md` is the full searchable index, `Memory/` is your live Claude memory.

---

## Auto-sync

### macOS (launchd — recommended)

```bash
cat > ~/Library/LaunchAgents/com.obsidian.vault-sync.plist << 'EOF'
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
  "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>com.obsidian.vault-sync</string>
    <key>ProgramArguments</key>
    <array>
        <string>python3</string>
        <string>/path/to/obsidian-vault-sync/sync.py</string>
    </array>
    <key>StartInterval</key>
    <integer>1800</integer>
    <key>StandardErrorPath</key>
    <string>/tmp/vault-sync.err</string>
</dict>
</plist>
EOF
launchctl load ~/Library/LaunchAgents/com.obsidian.vault-sync.plist
```

### Linux / cron

```bash
# Every 30 minutes
*/30 * * * * python3 /path/to/obsidian-vault-sync/sync.py >> ~/.vault-sync.log 2>&1
```

---

## Sync from inside Claude (MCP)

Instead of waiting for cron, trigger a sync from within Claude chat using the MCP server.

### Setup

Add to `~/.claude/claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "obsidian-vault-sync": {
      "command": "python3",
      "args": ["/path/to/obsidian-vault-sync/mcp_server.py"]
    }
  }
}
```

Then in Claude, just ask: **"sync my vault"** — Claude calls the `sync_vault` tool and reports back what was updated.

---

## Selective sync

By default, every conversation is synced. If you only want to keep conversations that are actually worth storing:

```python
# sync.py
SELECTIVE_MODE = True
VAULT_TAG      = "#vault"   # customize if you want a different tag
```

When `SELECTIVE_MODE` is on, a session is only synced if `#vault` appears anywhere in it — in a user message, a Claude response, anywhere. Just drop `#vault` in any message during a session you want to save.

Sessions without the tag are tracked in the manifest (so they aren't re-checked unless they change) but no note is written.

---

## Copilot Chat support

Export a session from VS Code: open the Copilot Chat panel → click `...` → **Export Chat...** → save as `.json`.

Point `COPILOT_DIR` at the folder where you save exports:

```python
# sync.py
COPILOT_DIR = "/Users/you/copilot-exports"
```

Copilot notes land in the same vault, classified by the same project taxonomy, tagged `copilot/conversation` instead of `claude/conversation`.

---

## Vault structure

```
MyVault/
├── Home.md                           # entry point
├── Memory/  ──symlink──▶  ~/.claude/projects/-Users-you/memory/
│   ├── MEMORY.md                     # live memory index
│   ├── project_myapp.md              # project memory note (hub)
│   └── ...
├── Conversations/
│   ├── _Index.md                     # searchable index, grouped by project
│   ├── 2025-06/
│   │   ├── 2025-06-15 - Auth flow redesign.md   → [[project_myapp]]
│   │   └── 2025-06-22 - Database migration.md   → [[project_myapp]]
│   └── 2025-07/
│       └── 2025-07-01 - Sprint planning.md      → [[project_work]]
└── .sync/
    └── manifest.json                 # tracks mtime per session
```

Obsidian Graph view shows project memory notes as hubs with conversations radiating as spokes.

---

## Customization

### Add a project

```python
PROJECTS = [
    {"label": "New Project", "hub": "project_new", "tag": "new",
     "kw": ["keyword1", "keyword2"]},
    ...
]
```

Run sync — new sessions matching those keywords are classified automatically.

### Force a full rebuild

```python
FORMAT = 4  # was 3 — bump by 1 to rebuild everything
```

### Tune keyword weights

```python
# In classify():
score = sum((5 if k in tl else 0) + (2 if k in bl else 0) for k in proj["kw"])
#            ^ title weight          ^ body weight
```

---

## Troubleshooting

**"0 new/updated" after first run**
The manifest is up to date. If you want to force a rebuild, bump `FORMAT` in `sync.py`.

**"memory symlink failed: File exists"**
The symlink is already there from a previous run — not an error.

**"No .json files found" (Copilot)**
Make sure you exported sessions as `.json` from VS Code, not markdown. Check `COPILOT_DIR` points to the right folder.

**Copilot export format not recognized**
The reader handles two export formats. If yours looks different, open an issue with a redacted sample.

---

## FAQ

**Does it sync to Claude, or only from Claude?**
One-way only: Claude → Obsidian. Edits in Obsidian don't sync back.

**Does it work with Claude Web (claude.ai)?**
No — it reads Claude Code's local `.jsonl` transcript files. Web sessions aren't stored locally.

**Will notes update if I keep adding to a conversation?**
Yes. The manifest tracks modification timestamps. When a transcript changes, the note is updated on the next sync run.

**Can I use multiple Claude accounts / project directories?**
Not in a single vault today. Run the script once per account by changing `SRC_DIR` for each run.

**Can I rename a project after syncing?**
Yes — update the `label` in `PROJECTS`. Old notes keep their old tag; new ones use the new label. To retag everything, bump `FORMAT` to trigger a full rebuild.

---

## License

MIT
