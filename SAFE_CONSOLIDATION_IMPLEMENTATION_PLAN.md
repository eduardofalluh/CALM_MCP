# Safe MCP Tool Consolidation - Implementation Plan

## ⚠️ CRITICAL: Production Safety Requirements

**This MCP server is in active production use. Every change must be:**
1. ✅ Backwards compatible (old tools still work)
2. ✅ Thoroughly tested (100% test coverage)
3. ✅ Incrementally deployed (one resource at a time)
4. ✅ Easily rollback-able (git branch strategy)
5. ✅ Validated in staging before production

---

## Executive Summary

**Goal**: Reduce 74 tools → ~25 tools (66% reduction) without breaking any existing functionality

**Strategy**: Add NEW consolidated tools while keeping OLD tools, then deprecate old ones after validation

**Timeline**: 3 phases over 2-3 sessions

**Risk Level**: LOW (additive changes, nothing removed initially)

---

## Phase 1: Foundation (Session 1 - Use This Plan)

### Scope
Add NEW consolidated read-only tools without touching existing tools.

**Tools to Add:**
1. `calm_resources(resource, operation, ...)`  - Unified read operations
2. Keep all existing tools untouched

### Implementation Steps

#### Step 1: Create New Unified Tool Module
Create `src/calm/tools/unified.py` with consolidated resource operations.

#### Step 2: Register Both Old and New Tools
Update `server.py` to register BOTH old and new tools side-by-side.

#### Step 3: Test Exhaustively
Run all existing tests + new tests for consolidated tools.

#### Step 4: Deploy to Feature Branch
Push to `feature/tool-consolidation` branch first, NOT main.

---

## Detailed Implementation Guide

### Part A: Safe Consolidation Pattern

**Key Principle**: ADDITIVE ONLY in Phase 1

```python
# NEW unified tool (add this)
@mcp.tool()
def calm_resource(
    ctx: Context,
    resource: Literal["projects", "tasks", "teams", "timeboxes", ...],
    operation: Literal["list", "get", "create", "update", "delete"] = "list",
    resource_id: Optional[str] = None,
    project_id: Optional[str] = None,
    data: Optional[dict] = None,
) -> Union[list[dict], dict]:
    """Unified resource management for CALM.
    
    Examples:
        # List all projects
        calm_resource(resource="projects", operation="list")
        
        # Get specific task
        calm_resource(resource="tasks", operation="get", resource_id="T123")
        
        # Create new timebox
        calm_resource(resource="timeboxes", operation="create", 
                     project_id="P001", data={...})
    """
    h = get_calm_headers(ctx)
    
    # Route to existing client functions (no changes to business logic)
    if resource == "projects":
        if operation == "list":
            return client.get_projects(h.token, h.base_url)
        elif operation == "create":
            return client.create_project(h.token, data, h.base_url, h.user_email)
        # ... etc
    elif resource == "tasks":
        if operation == "list":
            return client.get_tasks(project_id, h.token, h.base_url)
        # ... etc

# OLD tools (keep these - DO NOT REMOVE yet)
@mcp.tool()
def get_calm_projects(ctx: Context):
    """DEPRECATED: Use calm_resource(resource='projects', operation='list')"""
    return client.get_projects(...)
```

### Part B: Testing Strategy

#### Test Matrix - ALL Must Pass

| Test Type | What to Test | Pass Criteria |
|-----------|--------------|---------------|
| **Existing Tests** | Run full test suite | 100% pass, 0 failures |
| **New Tool Tests** | Test consolidated tools | All operations work |
| **Backwards Compat** | Old tools still work | No regressions |
| **Integration** | End-to-end workflows | Complete scenarios work |
| **Load Test** | 100 concurrent requests | No errors, <2s response |

#### Test Commands

```bash
# 1. Run existing test suite
source venv/bin/activate
CALM_TOKEN=fake python3 tests/test_server.py

# 2. Run new consolidated tool tests
python3 tests/test_consolidated_tools.py

# 3. Run integration tests
python3 tests/test_integration_e2e.py

# 4. Manual smoke test
# Start server and test with MCP Inspector or Claude Desktop

# ALL TESTS MUST PASS before proceeding to deployment
```

### Part C: Git Strategy

#### Branch Structure
```
main (production)
  ├── oauth-testing (current work)
  ├── feature/write-tools
  └── feature/tool-consolidation (NEW - start here)
       ├── phase1-read-ops
       ├── phase2-write-ops
       └── phase3-cleanup
```

#### Git Commands for Implementation

```bash
# 1. Create feature branch from main
git checkout main
git pull origin main
git checkout -b feature/tool-consolidation
git push -u origin feature/tool-consolidation

# 2. Create phase 1 sub-branch
git checkout -b feature/tool-consolidation-phase1
# ... make changes ...

# 3. After testing passes, commit
git add -A
git commit -m "Phase 1: Add consolidated read-only tools (backwards compatible)

- Add src/calm/tools/unified.py with calm_resource() tool
- Keep all existing tools functional
- Add comprehensive tests in tests/test_consolidated_tools.py
- 100% backwards compatible - no breaking changes

Tests:
✅ All existing tests pass (74/74 tools work)
✅ New consolidated tool tests pass
✅ Integration tests pass
✅ Manual testing validated

Co-Authored-By: Claude Code <noreply@anthropic.com>"

# 4. Push to GitHub
git push origin feature/tool-consolidation-phase1

# 5. After manual validation, merge to feature/tool-consolidation
git checkout feature/tool-consolidation
git merge feature/tool-consolidation-phase1 --no-edit
git push origin feature/tool-consolidation

# 6. Push to GitLab
git push gitlab feature/tool-consolidation

# 7. DO NOT merge to main until full validation in staging
```

### Part D: Validation Checklist

Before merging to main, validate ALL these scenarios:

#### Read Operations
- [ ] `calm_resource(resource="projects", operation="list")` returns all projects
- [ ] `calm_resource(resource="tasks", operation="list", project_id="P001")` returns tasks
- [ ] `calm_resource(resource="teams", operation="list")` returns teams
- [ ] `calm_resource(resource="teams", operation="list", project_id="P001")` filters by project
- [ ] Old tools still work: `get_calm_projects()`, `get_calm_tasks()`, etc.

#### Write Operations (Phase 2)
- [ ] `calm_resource(resource="tasks", operation="create", ...)` creates task
- [ ] `calm_resource(resource="tasks", operation="update", ...)` updates task
- [ ] `calm_resource(resource="tasks", operation="delete", ...)` deletes task
- [ ] Old tools still work: `create_calm_task()`, `update_calm_task()`, etc.

#### Error Handling
- [ ] Invalid resource name returns clear error
- [ ] Invalid operation returns clear error
- [ ] Missing required params returns clear error
- [ ] Same error messages as old tools

#### Performance
- [ ] No performance regression vs old tools
- [ ] Memory usage unchanged
- [ ] Response times < 2 seconds

---

## Model Delegation Strategy

### When to Use Which Model

**Claude Opus (You)**: 
- Review this plan
- Final approval
- Critical decisions
- Production deployment

**Claude Sonnet (Recommended for Implementation)**:
```bash
# In new Claude Code session:
/fast off  # Use Sonnet, not Opus

# Paste this:
"I need to implement Phase 1 of tool consolidation per the plan in 
SAFE_CONSOLIDATION_IMPLEMENTATION_PLAN.md. Start by creating 
src/calm/tools/unified.py with read-only operations. Follow the 
testing strategy exactly. Do not skip any tests."
```
- Implement new unified tool module
- Write comprehensive tests
- Update documentation
- Code reviews

**Claude Haiku (For Repetitive Tasks)**:
```bash
# Use for tedious but low-risk work:
/fast on  # Use Haiku

# Example tasks:
"Update all docstrings to mention the new consolidated tool pattern.
Add deprecation notices to old tools per the template in line 50 of unified.py"

"Run the full test suite 3 times and report any intermittent failures"

"Generate markdown documentation for all 25 new consolidated tools with examples"
```
- Documentation updates
- Test suite runs
- Repetitive refactoring
- Markdown generation

### Sample Delegation Messages

**For Sonnet (Implementation)**:
```
Read SAFE_CONSOLIDATION_IMPLEMENTATION_PLAN.md in the current directory.

Implement Phase 1 exactly as specified:
1. Create src/calm/tools/unified.py
2. Implement calm_resource() for read operations only
3. Keep all existing tools untouched
4. Create tests/test_consolidated_tools.py
5. Run ALL tests and report results

Do NOT proceed to Phase 2. Do NOT remove any existing tools.
CRITICAL: All 74 existing tools must still work after your changes.
```

**For Haiku (Testing)**:
```
Run the complete test suite 5 times:

source venv/bin/activate
CALM_TOKEN=fake python3 tests/test_server.py

Report:
- How many tests passed/failed each run
- Any intermittent failures
- Total execution time
- Any memory leaks or warnings
```

---

## Phase 2: Write Operations (Future Session)

**After Phase 1 fully validated**, in new session:

### Scope
Add create/update/delete operations to `calm_resource()`.

### Prerequisites
- [ ] Phase 1 deployed to production
- [ ] No issues reported for 1 week
- [ ] All monitoring shows healthy metrics

### Implementation
Same additive pattern - add new, keep old.

---

## Phase 3: Deprecation (Future Session)

**After Phase 2 fully validated**, in new session:

### Scope
Remove old tools, keep only consolidated ones.

### Prerequisites
- [ ] All teams migrated to new tools
- [ ] Documentation updated
- [ ] Migration guide published
- [ ] 2+ weeks of validation

---

## Rollback Procedures

### If Tests Fail
```bash
# Immediately revert
git checkout feature/tool-consolidation-phase1
git reset --hard HEAD~1
git push origin feature/tool-consolidation-phase1 --force

# Fix issues, re-test, re-commit
```

### If Production Issues Detected
```bash
# Hotfix: switch back to main
git checkout main
git push origin main --force-with-lease

# Investigate in feature branch
git checkout feature/tool-consolidation-phase1
# Debug and fix
```

### Emergency Rollback
```bash
# Nuclear option - revert to last known good
git checkout main
git reset --hard <commit-hash-before-consolidation>
git push origin main --force  # ONLY in emergency

# Push to GitLab
git push gitlab main --force
```

---

## Risk Assessment

### Low Risk ✅ (Phase 1)
- Adding new tools alongside old ones
- No existing functionality removed
- Easy rollback
- Can validate extensively before promotion

### Medium Risk ⚠️ (Phase 2)
- Write operations more critical
- Data modification involved
- Requires staging environment testing
- Should run in parallel with old tools for 1+ week

### High Risk ❌ (Phase 3)
- Removing existing tools
- Breaking change for any hardcoded tool names
- Must ensure 100% migration complete
- Requires deprecation period (4+ weeks)

---

## Success Metrics

### Quantitative
- [ ] Tool count: 74 → 25 (66% reduction)
- [ ] Context tokens saved: Measure before/after
- [ ] Response time: No increase (< 2s maintained)
- [ ] Error rate: No increase (< 0.1% maintained)
- [ ] Test coverage: Maintain 100%

### Qualitative
- [ ] Developer feedback: Easier to use
- [ ] Agent feedback: Less context required
- [ ] Documentation: Clearer, more concise
- [ ] Maintenance: Easier to update/extend

---

## Final Checklist Before Starting

### Prerequisites
- [ ] Read this entire document
- [ ] Understand git branch strategy
- [ ] Have staging/test environment ready
- [ ] Know how to rollback
- [ ] Monitoring/alerting configured
- [ ] Backup of current main branch taken

### Start Signal
```bash
# When ready to begin:
git checkout main
git pull origin main
git pull gitlab main
git checkout -b feature/tool-consolidation
git push -u origin feature/tool-consolidation
git push -u gitlab feature/tool-consolidation

# Create Phase 1 branch
git checkout -b feature/tool-consolidation-phase1

# NOW you're ready to implement
```

---

## Next Steps for NEW SESSION

### Message to Paste in New Chat

```markdown
# Task: Implement MCP Tool Consolidation Phase 1

**Context**: I'm consolidating 74 MCP tools down to ~25 for context optimization.
This is a PRODUCTION system - safety is critical.

**Your Role**: Implement Phase 1 (read-only operations) following the plan exactly.

**Instructions**:
1. Read `/path/to/SAFE_CONSOLIDATION_IMPLEMENTATION_PLAN.md`
2. Implement Phase 1 as specified
3. Run ALL tests - 100% must pass
4. Do NOT skip testing
5. Do NOT remove any existing tools
6. Do NOT proceed to Phase 2

**Working Directory**: 
`/Users/eduardofalluh/Library/CloudStorage/OneDrive-SYNTAXSYSTEMSLTD/Documents/AI Champions/MCP Server/CALM_MCP`

**Git Remotes**:
- GitHub: origin (https://github.com/eduardofalluh/CALM_MCP.git)
- GitLab: gitlab (gitlab.com:syntax-cloud/CloudAdmin/genai/third-parties/mcp-servers/mcp-sap-calm.git)

**Current Branch**: Start from `main`, create `feature/tool-consolidation-phase1`

**Critical**: All 74 existing tools MUST still work after your changes.
This is additive only - we're adding new tools, not replacing old ones yet.

Begin by creating the branch and reading the plan.
```

---

## FAQ

**Q: Can we skip testing?**  
A: NO. This is production. Every test must pass.

**Q: Can we merge directly to main?**  
A: NO. Feature branch → validation → staging → main.

**Q: What if Phase 1 works perfectly, can we skip Phase 2 validation?**  
A: NO. Write operations need separate validation period.

**Q: Can we remove old tools immediately?**  
A: NO. Deprecation period required (4+ weeks minimum).

**Q: What if users already have tools cached?**  
A: Keeping old tools ensures backwards compatibility during transition.

---

## Conclusion

**This plan is designed to be SAFE and INCREMENTAL.**

**Key Principles**:
1. Add, don't replace (initially)
2. Test exhaustively
3. Deploy gradually
4. Monitor continuously
5. Rollback ready

**When done correctly**:
- ✅ Zero downtime
- ✅ Zero data loss
- ✅ Zero broken workflows
- ✅ 66% fewer tools
- ✅ Happier users

**Timeline**: 3 separate sessions, weeks apart, with validation between each.

---

## Support

If anything goes wrong:
1. Check rollback procedures above
2. Review git history: `git log --oneline`
3. Check test output: `tests/test_server.py`
4. Verify branch: `git branch -a`
5. Escalate if needed

---

**Ready to start? Use the "Message to Paste in New Chat" section above in your next Claude Code session.**
