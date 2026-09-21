# Quick Start: Tool Consolidation

## 🎯 Goal
**74 tools → 25 tools (66% reduction)** without breaking anything

## ✅ Safety Guarantee
- All existing tools keep working
- We ADD new tools, not replace (Phase 1)
- 100% backwards compatible
- Thoroughly tested before deployment

## 📋 What to Do

### 1. Read the Full Plan
Open and read: `SAFE_CONSOLIDATION_IMPLEMENTATION_PLAN.md`

### 2. Start New Claude Session
Copy this message into a NEW Claude Code chat:

```
Task: Implement MCP Tool Consolidation Phase 1

Context: Consolidating 74 MCP tools to ~25 for production system.

Working Directory: /Users/eduardofalluh/Library/CloudStorage/OneDrive-SYNTAXSYSTEMSLTD/Documents/AI Champions/MCP Server/CALM_MCP

Read SAFE_CONSOLIDATION_IMPLEMENTATION_PLAN.md and implement Phase 1:
1. Create feature branch: feature/tool-consolidation-phase1
2. Create src/calm/tools/unified.py with read-only operations
3. Keep ALL existing 74 tools working
4. Add comprehensive tests
5. Run full test suite - 100% must pass

Git Remotes:
- GitHub: origin (https://github.com/eduardofalluh/CALM_MCP.git)
- GitLab: gitlab (gitlab.com:syntax-cloud/CloudAdmin/genai/third-parties/mcp-servers/mcp-sap-calm.git)

CRITICAL: This is additive only. Do not remove any existing tools.
All 74 existing tools must still work after your changes.

Begin by creating the git branch per the plan.
```

### 3. Model Selection
- **Sonnet**: For implementation (`/fast off`)
- **Haiku**: For testing/docs (`/fast on`)
- **Opus**: For review (you)

## 📊 Expected Results

**Phase 1 (First Session)**:
- ✅ New `calm_resource()` tool added
- ✅ All 74 old tools still work
- ✅ All tests pass
- ✅ Deployed to feature branch

**Phase 2 (Future Session)**:
- ✅ Write operations added
- ✅ 2 weeks validation
- ✅ Deployed to staging

**Phase 3 (Future Session)**:  
- ✅ Old tools deprecated
- ✅ 74 → 25 tools complete

## ⚡ Quick Commands

```bash
# Check current branch
git branch

# See all remotes
git remote -v

# Run tests
source venv/bin/activate
CALM_TOKEN=fake python3 tests/test_server.py

# Check tool count
grep -r "@mcp.tool()" src/calm/tools/*.py | wc -l
```

## 🚨 Red Flags (Stop Immediately If...)
- Any existing test fails
- Old tools stop working
- Tool gets deleted (should only add)
- Merge to main happens before validation
- Tests skipped

## ✨ Success Looks Like
- All existing tests: ✅ PASS
- New consolidated tests: ✅ PASS
- Old tools: ✅ Still work
- New tools: ✅ Work
- Git: ✅ Feature branch only
- Production: ✅ Untouched

## 📞 If Issues
1. Read rollback section in main plan
2. Check git branch: `git branch`
3. Verify tests: `python3 tests/test_server.py`
4. Ask for help if needed

---

**Ready?** Open new Claude session and paste the message above! 🚀
