# Obsidian Vault Sync

Automatically sync Claude conversations and memory into an Obsidian vault. Bridges your Claude workflow with Obsidian's knowledge graph, turning conversations into a queryable, linked knowledge base.

## What It Does

- **Conversations as notes** — Each Claude session converts to a markdown note, classified by project
- **Live memory links** — Your memory index symlinks into the vault, always current
- **Project hubs** — Conversations automatically link to their project's memory, creating a graph where each project is a hub with its conversations radiating out
- **Incremental sync** — Only processes new/changed transcripts (manifest-based tracking)
- **Deterministic classification** — Keyword scoring by title + body, no model calls needed

**Before:**
```
Claude work
    ├── 50+ conversations (scattered, hard to search)
    └── Memory (where did I write that?)

Obsidian
    └── Unlinked notes
```

**After:**
```
Obsidian Vault
    ├── Memory/ (live symlink, always current)
    │   ├── project_helm.md (hub)
    │   ├── project_diamond_savant.md (hub)
    │   └── ...
    │
    ├── Conversations/ (grouped by date)
    │   ├── 2024-06/ (Helm work)
    │   │   ├── 2024-06-15 - Auth flow redesign.md [→ project_helm]
    │   │   ├── 2024-06-22 - Database migration.md [→ project_helm]
    │   │   └── ...
    │   └── 2024-07/ (Diamond Savant)
    │       ├── 2024-07-01 - Model evaluation.md [→ project_diamond_savant]
    │       └── ...
    │
    └── Home.md + _Index.md
```

Graph view shows projects as hubs with conversations linked as spokes.

## Quick Start

### 1. Set Up Your Vault

```bash
# If you don't have a vault yet
mkdir ~/MyVault
cd ~/MyVault
git init
```

### 2. Install & Configure

```bash
# Clone this repo
git clone https://github.com/yourusername/obsidian-vault-sync.git
cd obsidian-vault-sync

# Edit config.yaml to point to your vault and Claude project directory
# See Configuration section below
```

### 3. Customize Your Projects

Edit `sync.py` and update the `PROJECTS` list to match your work:

```python
PROJECTS = [
    {"label": "Helm", "hub": "project_helm", "tag": "helm",
     "kw": ["helm", "subway", "multi-business", "ai coo"]},
    {"label": "DAT Prep", "hub": "project_dat", "tag": "dat",
     "kw": ["dat bootcamp", "dat exam", "dental admission"]},
    # ... add your projects
]
```

- `label` — display name in the vault
- `hub` — your memory note (filename without .md)
- `tag` — Obsidian tag (for filtering)
- `kw` — keywords to auto-classify conversations (title weighted 3x, body 1x)

### 4. Run the Sync

```bash
python3 sync.py
```

Output:
```
Vault: /Users/you/MyVault
Scanned 127 transcripts | 12 new/updated | 89 conversation notes
```

Then open your vault in Obsidian:
- **Home.md** — Overview
- **Memory/** — Your live memory index (symlinked)
- **Conversations/_Index.md** — Searchable conversation index, grouped by project
- **Graph view** — See projects as hubs with conversations as spokes

### 5. Keep It Fresh

Set up a cron job or launchd agent to run periodically:

```bash
# macOS: install as a launch agent
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
    <integer>3600</integer> <!-- run every hour -->
    <key>StandardErrorPath</key>
    <string>/tmp/vault-sync.err</string>
</dict>
</plist>
EOF
launchctl load ~/Library/LaunchAgents/com.obsidian.vault-sync.plist
```

## How It Works

### Classification

Conversations are classified by matching keywords against title (weighted 3x) and opening prompt (weighted 1x). No model calls — deterministic, fast, works offline.

Example:
```
Title: "Helm auth flow redesign"
Keywords matched: "helm" (in title, 3x)
Score: 3 → Classified as "Helm" project
```

### File Structure

```
YourVault/
├── Home.md                          # Entry point
├── Memory/ → symlink to ~/.claude/.../memory
├── Conversations/
│   ├── _Index.md                    # Searchable index
│   ├── 2024-06/
│   │   ├── 2024-06-15 - Auth flow.md
│   │   └── 2024-06-22 - Database.md
│   └── 2024-07/
│       └── 2024-07-01 - Model eval.md
└── .sync/
    └── manifest.json                # Track what's been converted
```

### Manifest Tracking

The manifest (`vault/.sync/manifest.json`) stores:
- Session ID → output file mapping
- Last modified time
- Project classification
- Format version (bump to force full rebuild)

Only changed transcripts are reconverted. To force a rebuild, edit `sync.py`:

```python
FORMAT = 2  # bump to 3 to force full rebuild
```

## Configuration

### Environment Variables

```bash
# Path to your Claude project directory (contains *.jsonl session files)
CLAUDE_PROJECT_DIR=~/.claude/projects/-Users-yourname

# Path to your memory directory (will be symlinked into the vault)
CLAUDE_MEMORY_DIR=~/.claude/projects/-Users-yourname/memory

# Path to your Obsidian vault
OBSIDIAN_VAULT=~/MyVault
```

Or edit `sync.py` directly:

```python
HOME     = Path.home()
SRC_DIR  = HOME / ".claude" / "projects" / "-Users-yourname"
MEM_SRC  = SRC_DIR / "memory"
VAULT    = HOME / "MyVault"
```

## Customization

### Add a New Project

1. Edit `PROJECTS` in `sync.py`:
   ```python
   {"label": "My New Project", "hub": "project_mynewproject", "tag": "mynewproject",
    "kw": ["keyword1", "keyword2", "related term"]},
   ```

2. Run the sync — new conversations matching those keywords will be auto-classified

3. (Optional) Create a memory note at `~/.claude/projects/-Users-yourname/memory/project_mynewproject.md`

### Ignore Sensitive Conversations

Add to `.gitignore` in the vault:

```bash
Conversations/2024-06-*.md  # Ignore a date range
Conversations/**/sensitive-topic.md
```

### Adjust Keyword Weights

In `classify()` function:

```python
score = sum((3 if k in tl else 0) + (1 if k in bl else 0) for k in proj["kw"])
```

Change the weights (3x title, 1x body) to adjust sensitivity:

```python
score = sum((5 if k in tl else 0) + (2 if k in bl else 0) for k in proj["kw"])
```

## Troubleshooting

### "Memory symlink failed"

If you see `! memory symlink: [Errno 17] File exists`, the symlink already exists. That's fine — just means it ran before.

### "No transcripts found"

Check:
1. `SRC_DIR` points to your Claude project directory (contains `*.jsonl` files)
2. Files exist: `ls ~/.claude/projects/-Users-yourname/*.jsonl`

### "0 new/updated" (nothing happening)

1. First run after a format bump always processes everything
2. Check manifest (`vault/.sync/manifest.json`) — are sessions being tracked?
3. Run with verbose output (optional — see Extend section below)

## Extend

### Add a Different Channel

Currently reads Claude sessions (`.jsonl` transcripts). To add Discord, Slack, email, etc.:

1. Write a reader function:
   ```python
   def read_slack_channel(channel_path):
       """Yield (title, body, timestamp) tuples"""
       ...
   ```

2. In `main()`, call your reader alongside the jsonl loop:
   ```python
   for item in read_slack_channel("~/path/to/slack/export"):
       # convert to note
   ```

### Add Metadata Extraction

Enhance the frontmatter with custom fields:

```python
fm = ['---',
      f'title: "{title}"',
      f'date: {date}',
      f'project: {proj["label"]}',
      f'length: {len(turns)} turns',  # add this
      f'has_code: {any("```" in turn[1] for turn in turns)}',  # add this
      '---']
```

## License

MIT

## FAQ

**Q: Does this sync *to* Claude, or only *from* Claude?**
A: One-way: Claude → Obsidian only. Your Obsidian edits don't sync back to Claude.

**Q: Does it include my actual memory content, or just link to it?**
A: Both. Memory notes are symlinked (live), so they're always current. Conversations are converted to markdown.

**Q: Can I rename projects after I start syncing?**
A: Yes. Update `PROJECTS` in `sync.py`. Old conversations keep their old project tag; new ones use the new tag.

**Q: Does it work with Claude Web?**
A: No — it reads Claude Code's local transcript files (`.jsonl`). Web conversations aren't synced locally.

**Q: How much disk space does this use?**
A: Minimal. A 50-turn conversation is ~20-50 KB markdown. 100 conversations ≈ 2-5 MB.

**Q: Can I use this with multiple Claude projects / accounts?**
A: Not yet in a single vault. You can run it once per account by pointing `SRC_DIR` to each. Future: a mapping to multi-project vaults.
