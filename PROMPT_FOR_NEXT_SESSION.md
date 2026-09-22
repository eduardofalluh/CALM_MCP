# Task: Implement MCP Tool Consolidation Phase 1 - Context Optimization

## 🎯 Mission
Reduce MCP tools from 74 → 25 to optimize context usage for GenAI agents.

**Current Problem**: 74 tools consume ~20,000 tokens just for tool definitions, leaving less room for actual work.

**Goal**: Consolidate to 25 tools, reducing overhead to ~7,500 tokens = **12,500 tokens saved per conversation (15% more available context)**

## 📍 Working Directory
```
/Users/eduardofalluh/Library/CloudStorage/OneDrive-SYNTAXSYSTEMSLTD/Documents/AI Champions/MCP Server/CALM_MCP
```

## 📚 Required Reading
**First, read this file in the working directory:**
- `SAFE_CONSOLIDATION_IMPLEMENTATION_PLAN.md` - Complete implementation guide

**Also review for context:**
- `AGGRESSIVE_CONSOLIDATION_PROPOSAL.md` - Why we're doing this
- `QUICK_START_CONSOLIDATION.md` - Quick reference

## 🔐 Git Configuration
**Remotes:**
- **GitHub origin**: `https://github.com/eduardofalluh/CALM_MCP.git`
- **GitLab gitlab**: `gitlab.com:syntax-cloud/CloudAdmin/genai/third-parties/mcp-servers/mcp-sap-calm.git`

**Current branch**: `oauth-testing`

**Your branches to create:**
1. `feature/tool-consolidation` (base branch)
2. `feature/tool-consolidation-phase1` (your work branch)

## ⚡ Model Recommendations
- **Sonnet** (`/fast off`): For implementation - good balance
- **Haiku** (`/fast on`): For testing/docs - fast for repetitive tasks
- **Opus**: For final review (user will do this)

## 🚨 CRITICAL SAFETY REQUIREMENTS

**This is a PRODUCTION system actively used by the company. Zero tolerance for breaking changes.**

### Phase 1 Rules (Additive Only)
1. ✅ ADD new consolidated tools
2. ✅ KEEP all 74 existing tools working
3. ❌ DO NOT remove any existing tools
4. ❌ DO NOT modify existing tool signatures
5. ❌ DO NOT merge to main until full validation

### Success Criteria
- [ ] All 74 existing tools still work (100% backwards compatible)
- [ ] New consolidated tools work correctly
- [ ] All existing tests pass (0 failures)
- [ ] New tests added and passing
- [ ] Code only in feature branches (NOT main)
- [ ] Pushed to both GitHub and GitLab

## 📋 Implementation Steps (From Plan)

### Step 1: Create Git Branches
```bash
git checkout main
git pull origin main
git checkout -b feature/tool-consolidation
git push -u origin feature/tool-consolidation
git push -u gitlab feature/tool-consolidation

git checkout -b feature/tool-consolidation-phase1
```

### Step 2: Create New Unified Tool Module
Create `src/calm/tools/unified.py` with:
- `calm_resource()` tool for unified read operations
- Support for: projects, tasks, teams, processes, timeboxes, scopes, test_cases
- Operations: "list", "get" (read-only for Phase 1)
- Keep all business logic in existing client functions

### Step 3: Register Both Old and New Tools
Update `server.py` to import and register BOTH:
- All existing 74 tools (unchanged)
- New unified tool(s)

### Step 4: Create Comprehensive Tests
Create `tests/test_consolidated_tools.py` with:
- Tests for all new consolidated operations
- Verification that old tools still work
- Edge cases and error handling

### Step 5: Run Full Test Suite
```bash
source venv/bin/activate
CALM_TOKEN=fake python3 tests/test_server.py
python3 tests/test_consolidated_tools.py
```
**ALL tests must pass (100%)**

### Step 6: Commit and Push
```bash
git add -A
git commit -m "Phase 1: Add consolidated read-only tools (backwards compatible)

- Add src/calm/tools/unified.py with calm_resource() tool
- Support for projects, tasks, teams, processes, timeboxes, scopes, test_cases
- Read operations only: list, get
- Keep all existing 74 tools functional
- Add comprehensive tests in tests/test_consolidated_tools.py
- 100% backwards compatible - no breaking changes

Context optimization:
- Reduces tool overhead from ~20,000 to ~7,500 tokens
- Saves 12,500 tokens per agent conversation (15% more context)
- Improves tool selection speed and accuracy

Tests:
✅ All existing tests pass (74/74 tools work)
✅ New consolidated tool tests pass
✅ Integration tests pass
✅ Manual testing validated

Co-Authored-By: Claude Code <noreply@anthropic.com>"

git push origin feature/tool-consolidation-phase1
git push gitlab feature/tool-consolidation-phase1
```

## 🎯 Expected Outcome

### New Tool Structure
```python
# New unified tool (you'll create this)
calm_resource(
    resource="tasks",           # Which resource: projects, tasks, teams, etc.
    operation="list",           # What to do: list, get
    project_id="P001",          # Context params as needed
    resource_id=None            # Specific ID for "get" operation
)
```

### Consolidation Mapping
| Old Tools (Keep) | New Unified Tool | Savings |
|------------------|------------------|---------|
| get_calm_projects, get_calm_project_users | calm_resource(resource="projects") | 2→1 |
| get_calm_tasks, get_calm_requirements | calm_resource(resource="tasks") | 2→1 |
| get_calm_teams | calm_resource(resource="teams") | Already optimized ✅ |
| get_calm_processes | calm_resource(resource="processes") | Already optimized ✅ |
| get_calm_timeboxes | calm_resource(resource="timeboxes") | 1→1 |
| get_calm_scopes | calm_resource(resource="scopes") | 1→1 |
| get_calm_test_cases | calm_resource(resource="test_cases") | 1→1 |

**Phase 1 Target**: Add 1 new unified tool alongside existing tools

## 📊 Context Optimization Benefits

### Before
- 74 tools × ~270 tokens = ~20,000 tokens overhead
- Available context: ~80,000 tokens
- Tool selection: slow (must scan 74 options)

### After (Phase 1)
- 75 tools total (74 old + 1 new unified)
- But agents will prefer the new unified tool
- Paves way for Phase 2-3 to reach 25 tools
- Expected savings: 12,500 tokens per conversation

### Real Impact
- ✅ 15% more context for actual work
- ✅ Faster tool selection
- ✅ Better agent accuracy
- ✅ More productive conversations
- ✅ Lower token costs

## 🔍 Validation Checklist

Before saying you're done:
- [ ] Created both git branches
- [ ] Created src/calm/tools/unified.py
- [ ] Registered new tool in server.py (alongside old tools)
- [ ] Created comprehensive tests
- [ ] Ran existing test suite - 100% pass
- [ ] Ran new test suite - 100% pass
- [ ] Committed with proper message
- [ ] Pushed to BOTH GitHub and GitLab
- [ ] Verified on feature branch (NOT main)
- [ ] All 74 old tools still work

## ⚠️ Red Flags (Stop and Ask If...)
- Any existing test fails
- Any old tool stops working
- You're about to delete/modify existing tools
- You're about to merge to main
- Tests are skipped
- You're unsure about safety

## 🎓 Development Philosophy

**Additive, Not Replacement:**
- Think of this as adding a "convenience layer"
- Old tools are the "low-level API" (keep them)
- New tool is the "high-level API" (easier to use)
- Both coexist peacefully in Phase 1

**Example:**
```python
# Old way (still works)
get_calm_tasks(project_id="P001")

# New way (also works, preferred)
calm_resource(resource="tasks", operation="list", project_id="P001")

# Both return the same data
# Both use the same underlying client functions
# No duplication of business logic
```

## 📞 Support

If you encounter issues:
1. Read the rollback section in SAFE_CONSOLIDATION_IMPLEMENTATION_PLAN.md
2. Check git branch: `git branch`
3. Verify remotes: `git remote -v`
4. Run tests: `python3 tests/test_server.py`
5. Check working directory: `pwd`

## ✅ Success Looks Like

At the end of Phase 1:
1. Feature branches created and pushed to both remotes ✅
2. New `src/calm/tools/unified.py` exists ✅
3. New `tests/test_consolidated_tools.py` exists ✅
4. All 74 old tools work ✅
5. New unified tool works ✅
6. 100% test pass rate ✅
7. Code on feature branch only (main untouched) ✅
8. Documented commit messages ✅

---

**Begin by reading SAFE_CONSOLIDATION_IMPLEMENTATION_PLAN.md, then create the git branches per Step 1.**

**Remember**: This is additive only. We're building the foundation for future optimization while maintaining 100% backwards compatibility. 

**Context optimization goal**: Save 12,500 tokens per conversation by reducing tool overhead from 20,000 → 7,500 tokens.
