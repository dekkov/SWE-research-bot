# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## AI Guidance

* Ignore GEMINI.md and GEMINI-*.md files
* To save main context space, for code searches, inspections, troubleshooting or analysis, use code-searcher subagent where appropriate - giving the subagent full context background for the task(s) you assign it.
* After receiving tool results, carefully reflect on their quality and determine optimal next steps before proceeding. Use your thinking to plan and iterate based on this new information, and then take the best next action.
* For maximum efficiency, whenever you need to perform multiple independent operations, invoke all relevant tools simultaneously rather than sequentially.
* Before you finish, please verify your solution
* Do what has been asked; nothing more, nothing less.
* NEVER create files unless they're absolutely necessary for achieving your goal.
* ALWAYS prefer editing an existing file to creating a new one.
* NEVER proactively create documentation files (*.md) or README files. Only create documentation files if explicitly requested by the User.
* When you update or modify core context files, also update markdown documentation and memory bank
* When asked to commit changes, exclude CLAUDE.md and CLAUDE-*.md referenced memory bank system files from any commits. Never delete these files.

## Memory Bank System

This project uses a structured memory bank system with specialized context files. Always check these files for relevant information before starting work:

### Core Context Files

* **CLAUDE-activeContext.md** - Current session state, goals, and progress (if exists)
* **CLAUDE-patterns.md** - Established code patterns and conventions (if exists)
* **CLAUDE-decisions.md** - Architecture decisions and rationale (if exists)
* **CLAUDE-troubleshooting.md** - Common issues and proven solutions (if exists)
* **CLAUDE-config-variables.md** - Configuration variables reference (if exists)
* **CLAUDE-temp.md** - Temporary scratch pad (only read when referenced)

**Important:** Always reference the active context file first to understand what's currently being worked on and maintain session continuity.

### Memory Bank System Backups

When asked to backup Memory Bank System files, you will copy the core context files above and @.claude settings directory to directory @/path/to/backup-directory. If files already exist in the backup directory, you will overwrite them.

## Claude Code Official Documentation

When working on Claude Code features (hooks, skills, subagents, MCP servers, etc.), use the `claude-docs-consultant` skill to selectively fetch official documentation from docs.claude.com.

## Project Overview

**SWE Job Research Bot** - An AI-powered job scraping and analysis tool that:
1. Scrapes job postings from company career pages using Playwright (browser automation)
2. Stores data in SQLite database with deduplication
3. Parses job descriptions with GPT-4o-mini LLM to extract tech stacks and requirements
4. Displays results in FastAPI web dashboard with search/filter capabilities

**Primary Use Case**: Help job seekers understand tech stack requirements across multiple companies and identify skill gaps.

**Tech Stack**: Python 3.10+, Playwright, SQLite, OpenAI API (GPT-4o-mini), FastAPI, Pydantic

---

## Setup and Development Commands

### Initial Setup

```bash
# Create virtual environment and install dependencies
python -m venv .venv
source .venv/bin/activate  # On Windows: .venv\Scripts\activate
pip install -r requirements.txt

# Install Playwright browser
playwright install chromium

# Configure environment
cp .env.example .env
# Edit .env and add your OPENAI_API_KEY

# Initialize database (creates data/jobs.db)
python main.py init
```

### Common Development Commands

```bash
# Run full pipeline (scrape → analyze → summarize)
python main.py run-all

# Individual steps
python main.py scrape              # Discover and scrape job listings
python main.py analyze             # Parse requirements with LLM
python main.py summarize           # Generate category summaries
python main.py status              # Show database statistics

# Web dashboard
python main.py web                 # Launch at http://127.0.0.1:8000
python main.py web --host 0.0.0.0 --port 8080  # Custom host/port

# Maintenance
python main.py rescrape-failed     # Re-extract jobs with missing descriptions
```

### Command Options

```bash
# Scrape specific company
python main.py scrape --company "OpenAI"

# Limit jobs for testing
python main.py scrape --limit 5
python main.py run-all --limit 10

# Analyze specific company
python main.py analyze --company "OpenAI" --limit 20
```

### Running Tests

```bash
# Run all tests
pytest

# Run specific test file
pytest tests/test_scraper.py

# Run with coverage
pytest --cov=src --cov-report=html
```

---

## Architecture and Key Workflows

### Data Flow

```
1. DISCOVERY (src/scraper/discovery.py)
   → Navigate to careers page
   → Scroll to load all jobs (infinite scroll)
   → Extract job links + metadata
   → Generate URL hash for deduplication
   ↓
2. EXTRACTION (src/scraper/extractor.py)
   → Navigate to individual job pages
   → Wait for JavaScript to render (CRITICAL - see timing notes below)
   → Extract job description from .prose element
   → Store in jobs table with raw_description
   ↓
3. ANALYSIS (src/analyzer/parser.py)
   → Send job description to GPT-4o-mini
   → Parse into structured requirements (skills, experience, etc.)
   → Store in requirements table as JSON arrays
   ↓
4. CATEGORIZATION (src/analyzer/categorizer.py)
   → Classify job into categories (Backend, Frontend, ML, etc.)
   → Store in job_categories table with confidence scores
   ↓
5. SUMMARIZATION (src/analyzer/summarizer.py)
   → Aggregate requirements by category
   → Generate LLM summary of common patterns
   → Store in category_summaries table
   ↓
6. WEB DASHBOARD (src/web/app.py)
   → FastAPI serves jobs with tech stack badges
   → Search/filter by category, tech stack, location
   → Export selected jobs as JSON/CSV/Markdown
```

### Database Schema (Critical Relationships)

```sql
jobs (1) ←→ (1) requirements     -- One job has one requirement record
jobs (1) ←→ (N) job_categories   -- One job can have multiple categories
```

**IMPORTANT**: The `requirements` table should have a **1:1 relationship** with jobs. If duplicates exist, `get_requirements(job_id)` uses `fetchone()` which returns the FIRST row by ID. This can cause the web UI to show empty tech stacks if old empty rows exist before newer rows with data.

**Prevention**: When updating requirements, use `UPDATE` or `DELETE + INSERT`, not just `INSERT`.

### CSS Selector Configuration

Company-specific selectors are defined in `config/companies.json`:

```json
{
  "companies": [{
    "name": "OpenAI",
    "careers_url": "https://openai.com/careers/search/?q=",
    "selectors": {
      "job_link": "a[href^=\"/careers/\"][href$=\"/\"]",
      "detail_description": ".prose, div.prose, [class*='prose']"
    }
  }]
}
```

**Critical**: The `detail_description` selector targets the main job description container. For SPAs (single-page applications) like OpenAI's career site, the content is client-side rendered.

---

## Critical Implementation Details

### Playwright Timing Strategy (CRITICAL)

Modern career pages use client-side rendering (JavaScript populates content after page load). The extraction code MUST wait for content to be fully rendered:

**CORRECT approach** (src/scraper/extractor.py:40-52):
```python
# Wait for network to be idle (JavaScript has executed)
await page.goto(url, wait_until="networkidle", timeout=60000)
await page.wait_for_timeout(3000)

# Scroll to trigger lazy-loaded content
await page.evaluate('window.scrollTo(0, document.body.scrollHeight)')
await page.wait_for_timeout(2000)

# Wait for description element to be VISIBLE (not just in DOM)
await page.wait_for_selector(desc_selector, state='visible', timeout=15000)
```

**WRONG approach** (causes 95%+ failure rate):
```python
# ❌ domcontentloaded fires before JavaScript executes
await page.goto(url, wait_until="domcontentloaded")
await page.wait_for_timeout(5000)

# ❌ Silent exception handling masks race conditions
try:
    await page.wait_for_selector(desc_selector, timeout=5000)
except Exception:
    logger.debug("Selector not found, proceeding anyway")  # DANGEROUS!
```

**Why this matters**:
- `domcontentloaded` = HTML parsed (but JS hasn't run yet)
- `networkidle` = No network activity for 500ms (JS has loaded data)
- `state='visible'` ensures element is rendered, not just present in DOM
- Silent exception handling prevents retry mechanisms from working

See `Behavioural.md` for full incident report on this issue.

### LLM-Based Parsing Strategy

Instead of complex regex/NLP, we use a single GPT-4o-mini call per job:

```python
# src/analyzer/parser.py
prompt = f"""
Extract job requirements from this description:

{job_description}

Return JSON:
{{
  "responsibilities": [...],
  "required_skills": [...],
  "preferred_skills": [...],
  "experience": [...],
  "education": [...]
}}
"""
```

**Advantages**:
- No regex maintenance
- Handles varied formats automatically
- Understands context and implicit requirements
- ~$0.015 per job at GPT-4o-mini rates

**Settings** (config/settings.py):
- `openai_model`: "gpt-4o-mini" (cheap, fast, sufficient for parsing)
- `openai_temperature`: 0.3 (low for consistent extraction)
- `openai_max_tokens`: 2000 (enough for structured output)

### Database Deduplication

Jobs are deduplicated using SHA-256 hash of canonical URL:

```python
# src/storage/database.py
def job_exists(self, url_hash: str) -> bool:
    # Check if job_url_hash exists in jobs table
    # Prevents re-scraping same job across multiple runs
```

**Resume capability**: If scraping is interrupted, re-running `scrape` or `run-all` will:
1. Skip jobs that already exist (by URL hash)
2. Only scrape new jobs
3. Mark unprocessed jobs for analysis

---

## Project Structure (Key Modules)

```
src/
├── scraper/
│   ├── browser.py          # Playwright browser context manager
│   ├── discovery.py        # Job listing discovery + infinite scroll
│   └── extractor.py        # Individual job detail extraction (TIMING CRITICAL)
├── analyzer/
│   ├── llm_client.py       # OpenAI API wrapper with token counting
│   ├── parser.py           # LLM-based requirement parsing
│   ├── categorizer.py      # Job categorization (Backend, Frontend, etc.)
│   └── summarizer.py       # Category-level summaries
├── storage/
│   ├── database.py         # SQLite CRUD operations
│   └── models.py           # Pydantic models for type safety
├── cli/
│   └── commands.py         # Click CLI commands (scrape, analyze, web, etc.)
└── web/
    ├── app.py              # FastAPI application
    ├── api/                # REST endpoints
    │   ├── jobs.py         # Job listing/detail endpoints
    │   ├── search.py       # Tech stack search
    │   └── export.py       # Export jobs as JSON/CSV/Markdown
    └── templates/          # Jinja2 HTML templates

config/
├── settings.py             # Pydantic settings from .env
└── companies.json          # Company-specific CSS selectors

data/
└── jobs.db                 # SQLite database (auto-created by init)
```

### Key Files to Understand

1. **src/scraper/extractor.py:40-52** - Timing logic for content extraction (CRITICAL)
2. **src/storage/database.py:389-405** - `get_requirements()` uses `fetchone()` (can return wrong row if duplicates exist)
3. **config/companies.json** - CSS selectors must target correct elements for each company
4. **src/analyzer/parser.py** - LLM prompt engineering for requirement extraction
5. **src/web/api/jobs.py:69-76** - Tech stack extraction from requirements for display

---

## Common Troubleshooting

### Issue: Only 3-5 jobs have descriptions, rest are empty

**Symptom**: Database shows jobs but `raw_description` is NULL/empty for most jobs

**Root cause**: Race condition - extraction happens before JavaScript renders content

**Solution**: Verify `src/scraper/extractor.py` uses `networkidle` + `state='visible'` (see timing section above)

**Debug command**:
```bash
python main.py rescrape-failed  # Re-extracts jobs with missing descriptions
```

### Issue: Tech stacks show in database but not in web UI

**Symptom**: `requirements` table has data but web dashboard shows empty badges

**Root cause**: Duplicate requirement rows exist, `fetchone()` returns old empty row

**Solution**: Clean up duplicates
```python
# Keep only the row with most data for each job_id
# Delete duplicates where required_skills and preferred_skills are both empty
```

**Verify**:
```sql
-- Check for duplicates
SELECT job_id, COUNT(*) FROM requirements GROUP BY job_id HAVING COUNT(*) > 1;

-- Check if requirements have data
SELECT job_id, required_skills, preferred_skills FROM requirements WHERE job_id = 1;
```

### Issue: OpenAI API rate limits

**Symptom**: `analyze` command fails with 429 errors

**Solution**: GPT-4o-mini has high rate limits, but if hit:
1. Add retry logic with exponential backoff
2. Use `--limit` to process in smaller batches
3. Check your API usage dashboard for quotas

---

## Testing Strategy

### Manual Testing Workflow

```bash
# 1. Test scraping with limited jobs
python main.py scrape --limit 5

# 2. Verify database
sqlite3 data/jobs.db "SELECT id, title, length(raw_description) FROM jobs;"

# 3. Test analysis
python main.py analyze --limit 5

# 4. Check requirements
sqlite3 data/jobs.db "SELECT job_id, required_skills FROM requirements LIMIT 3;"

# 5. Launch web UI and verify
python main.py web
# Visit http://127.0.0.1:8000 and check if tech stacks display
```

### Key Assertions

When modifying extraction logic, verify:
- [ ] `raw_description` is populated (4000-6000 chars for OpenAI jobs)
- [ ] Description contains actual job content, not navigation HTML
- [ ] No duplicate requirement rows exist per job
- [ ] `required_skills` and `preferred_skills` arrays are populated
- [ ] Web UI displays tech stack badges correctly

---



## ALWAYS START WITH THESE COMMANDS FOR COMMON TASKS

**Task: "List/summarize all files and directories"**

```bash
fd . -t f           # Lists ALL files recursively (FASTEST)
# OR
rg --files          # Lists files (respects .gitignore)
```

**Task: "Search for content in files"**

```bash
rg "search_term"    # Search everywhere (FASTEST)
```

**Task: "Find files by name"**

```bash
fd "filename"       # Find by name pattern (FASTEST)
```

### Directory/File Exploration

```bash
# FIRST CHOICE - List all files/dirs recursively:
fd . -t f           # All files (fastest)
fd . -t d           # All directories
rg --files          # All files (respects .gitignore)

# For current directory only:
ls -la              # OK for single directory view
```

### BANNED - Never Use These Slow Tools

* ❌ `tree` - NOT INSTALLED, use `fd` instead
* ❌ `find` - use `fd` or `rg --files`
* ❌ `grep` or `grep -r` - use `rg` instead
* ❌ `ls -R` - use `rg --files` or `fd`
* ❌ `cat file | grep` - use `rg pattern file`

### Use These Faster Tools Instead

```bash
# ripgrep (rg) - content search 
rg "search_term"                # Search in all files
rg -i "case_insensitive"        # Case-insensitive
rg "pattern" -t py              # Only Python files
rg "pattern" -g "*.md"          # Only Markdown
rg -1 "pattern"                 # Filenames with matches
rg -c "pattern"                 # Count matches per file
rg -n "pattern"                 # Show line numbers 
rg -A 3 -B 3 "error"            # Context lines
rg " (TODO| FIXME | HACK)"      # Multiple patterns

# ripgrep (rg) - file listing 
rg --files                      # List files (respects •gitignore)
rg --files | rg "pattern"       # Find files by name 
rg --files -t md                # Only Markdown files 

# fd - file finding 
fd -e js                        # All •js files (fast find) 
fd -x command {}                # Exec per-file 
fd -e md -x ls -la {}           # Example with ls 

# jq - JSON processing 
jq. data.json                   # Pretty-print 
jq -r .name file.json           # Extract field 
jq '.id = 0' x.json             # Modify field
```

### Search Strategy

1. Start broad, then narrow: `rg "partial" | rg "specific"`
2. Filter by type early: `rg -t python "def function_name"`
3. Batch patterns: `rg "(pattern1|pattern2|pattern3)"`
4. Limit scope: `rg "pattern" src/`

### INSTANT DECISION TREE

```
User asks to "list/show/summarize/explore files"?
  → USE: fd . -t f  (fastest, shows all files)
  → OR: rg --files  (respects .gitignore)

User asks to "search/grep/find text content"?
  → USE: rg "pattern"  (NOT grep!)

User asks to "find file/directory by name"?
  → USE: fd "name"  (NOT find!)

User asks for "directory structure/tree"?
  → USE: fd . -t d  (directories) + fd . -t f  (files)
  → NEVER: tree (not installed!)

Need just current directory?
  → USE: ls -la  (OK for single dir)
```
