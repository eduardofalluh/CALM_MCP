# Phase 3: Legacy Tool Deprecation - Implementation Plan

## ⚠️ CRITICAL: This Phase Requires User Migration

**Status**: PLANNING ONLY  
**Implementation**: After 4+ weeks grace period  
**Prerequisites**: Phase 1 & 2 deployed, validated, and stable in production

---

## Executive Summary

**Goal**: Remove legacy tools to achieve final optimization goal of ~25 tools

**Strategy**: Graceful deprecation with clear migration path and long grace period

**Timeline**: Minimum 4 weeks after deprecation warnings added

**Risk Level**: MEDIUM - Users must migrate, but we provide clear guidance

---

## Prerequisites for Phase 3

### ✅ Must Be Complete Before Starting

1. **Phase 1 & 2 Deployed** ✅
   - [x] Unified tool with read operations deployed
   - [x] Unified tool with write operations deployed
   - [x] Both tested and stable in production

2. **Production Validation** (Required Before Phase 3)
   - [ ] Unified tool used successfully in production (2+ weeks)
   - [ ] No critical issues reported
   - [ ] Performance metrics acceptable
   - [ ] Agent usage data collected

3. **User Communication** (Required Before Phase 3)
   - [ ] Migration guide published
   - [ ] Deprecation announcement sent
   - [ ] Training materials available
   - [ ] Support team briefed

4. **Monitoring** (Required Before Phase 3)
   - [ ] Legacy tool usage tracked
   - [ ] Migration progress measured
   - [ ] Alerts configured for issues

---

## Phase 3 Sub-Phases

### Phase 3A: Deprecation Warnings (Week 1-2)

**Goal**: Warn users that legacy tools will be removed

**Actions**:
1. Add deprecation warnings to all legacy tool docstrings
2. Log warning message when legacy tool is called
3. Update documentation to recommend unified tool
4. Send announcement to all users

**Implementation**:
```python
# Example deprecation warning
@mcp.tool()
def get_calm_tasks(project_id: str, ctx: Context, task_type: str | None = None):
    """[DEPRECATED] Use calm_resource(resource='tasks', ...) instead.
    
    This tool will be removed in version X.Y.Z (after YYYY-MM-DD).
    Please migrate to the unified calm_resource() tool.
    
    Migration example:
        # Old way:
        get_calm_tasks(project_id="P001")
        
        # New way:
        calm_resource(resource="tasks", operation="list", project_id="P001")
    
    Original description:
    Return tasks for a Cloud ALM project...
    """
    # Log deprecation warning
    log.warning(
        f"get_calm_tasks is deprecated. Use calm_resource(resource='tasks') instead. "
        f"This tool will be removed after {DEPRECATION_DATE}."
    )
    
    # Original implementation continues to work
    h = get_calm_headers(ctx)
    return client.get_tasks(project_id, h.token, h.base_url, task_type=task_type)
```

### Phase 3B: Grace Period (Week 3-6+)

**Goal**: Give users time to migrate

**Duration**: Minimum 4 weeks, possibly longer

**Activities**:
- Monitor migration progress
- Answer user questions
- Update migration guide based on feedback
- Fix any issues with unified tool
- Extend grace period if needed

**Metrics to Track**:
- % of API calls using legacy vs unified tools
- Number of unique users on legacy tools
- Support tickets related to migration
- Errors/issues with unified tool

**Migration Complete Criteria**:
- < 5% of API calls use legacy tools
- No active users depend exclusively on legacy tools
- No critical issues blocking migration
- Team approval to proceed

### Phase 3C: Tool Removal (After Grace Period)

**Goal**: Remove legacy tools to achieve ~25 tool target

**Prerequisites**:
- All users migrated or explicitly acknowledged
- No critical dependencies on legacy tools
- Rollback plan in place
- Team approval

**Actions**:
1. Remove legacy tool registrations from server.py
2. Remove legacy tool modules
3. Update documentation
4. Bump major version number

**Tools to Remove** (37 legacy read tools):
```python
# Read tools to remove:
get_calm_projects
get_calm_tasks
get_calm_requirements
get_calm_teams
get_calm_business_processes
get_calm_solution_processes
get_calm_processes  # Keep or remove? (combines both)
get_calm_timeboxes
get_calm_scopes
get_calm_test_cases
get_calm_tags
get_calm_features
get_calm_test_plans
get_calm_project_users
get_calm_project_customization
# ... plus other read-only helpers
```

**Write Tools to Remove** (37 legacy write tools):
```python
# Write tools to remove:
create_calm_project
update_calm_project
create_calm_task
update_calm_task
delete_calm_task
create_calm_requirement
update_calm_requirement
delete_calm_requirement
create_calm_scope
update_calm_scope
delete_calm_scope
create_calm_test_case
update_calm_test_case
delete_calm_test_case
create_calm_timebox
update_calm_timebox
delete_calm_timebox
create_calm_business_process
update_calm_business_process
delete_calm_business_process
create_calm_solution_process
update_calm_solution_process
delete_calm_solution_process
create_calm_tag
create_calm_feature
create_calm_test_plan
# ... plus task relations, comments, etc.
```

**Tools to Keep** (~25 remaining):
```python
# Core unified tool
calm_resource  # The main unified interface

# Helper/utility tools (essential, not easily consolidated)
calm_health  # Server health check
get_calm_oauth_endpoints  # OAuth discovery
get_calm_oauth_metadata  # OAuth configuration
get_calm_authorization_server_metadata  # OAuth server info
get_my_calm_user_uuid_instructions  # User UUID helper

# Advanced/specialized operations
set_calm_task_tags  # Batch tag assignment
update_calm_scope_assignments  # Batch scope assignments
assign_calm_test_case_to_plan  # Test case assignment
link_calm_test_case_to_requirement  # Traceability link
assign_calm_scenario_versions  # Complex assignment

# Task sub-entities (could be consolidated further)
create_calm_task_relation  # Task relationships
delete_calm_task_relation
create_calm_task_comment  # Task comments
update_calm_task_comment
delete_calm_task_comment

# Test actions/activities
create_calm_test_action
update_calm_test_action
delete_calm_test_action
create_calm_test_activity  # Test execution
update_calm_test_activity
delete_calm_test_activity

# Generic escape hatches
calm_api_write  # Generic POST/PATCH
calm_api_delete  # Generic DELETE

# BTP Test Management (separate system)
tm_health  # TM health check
get_tm_statistics  # TM statistics
get_tm_test_cases  # TM test cases
get_tm_test_case_full  # TM single test case
get_tm_requirements  # TM requirements
create_tm_test_case  # TM create
update_tm_test_case  # TM update
delete_tm_test_case  # TM delete
create_tm_requirement  # TM requirement
delete_tm_requirement
tm_odata_read  # TM generic read
tm_odata_write  # TM generic write
tm_odata_delete  # TM generic delete
```

**Final Count**: ~25-30 tools (down from 74)

---

## Migration Guide for Users

### Quick Migration Reference

#### Read Operations

```python
# BEFORE (Legacy)
projects = get_calm_projects()
tasks = get_calm_tasks(project_id="P001")
requirements = get_calm_requirements(project_id="P001")
teams = get_calm_teams()
teams_proj = get_calm_teams(project_id="P001")

# AFTER (Unified)
projects = calm_resource(resource="projects", operation="list")
tasks = calm_resource(resource="tasks", operation="list", project_id="P001")
requirements = calm_resource(resource="requirements", operation="list", project_id="P001")
teams = calm_resource(resource="teams", operation="list")
teams_proj = calm_resource(resource="teams", operation="list", project_id="P001")
```

#### Write Operations

```python
# BEFORE (Legacy)
new_task = create_calm_task(
    project_id="P001",
    title="New task",
    type="User Story",
    acting_user_email="user@example.com"
)

updated = update_calm_task(
    project_id="P001",
    task_id="3-12345",
    status="Done",
    acting_user_email="user@example.com"
)

delete_calm_task(
    project_id="P001",
    task_id="3-12345",
    acting_user_email="user@example.com"
)

# AFTER (Unified)
new_task = calm_resource(
    resource="tasks",
    operation="create",
    project_id="P001",
    data={"title": "New task", "type": "User Story"},
    user_email="user@example.com"
)

updated = calm_resource(
    resource="tasks",
    operation="update",
    project_id="P001",
    resource_id="3-12345",
    data={"status": "Done"},
    user_email="user@example.com"
)

calm_resource(
    resource="tasks",
    operation="delete",
    project_id="P001",
    resource_id="3-12345",
    user_email="user@example.com"
)
```

### Migration Checklist

For each codebase using CALM MCP:

- [ ] Inventory all usages of legacy tools
- [ ] Update to use `calm_resource()` instead
- [ ] Test thoroughly
- [ ] Deploy to staging
- [ ] Validate in staging
- [ ] Deploy to production
- [ ] Monitor for issues

---

## Rollback Plan

### If Issues Are Discovered

**Option 1: Delay Phase 3C**
- Keep deprecation warnings
- Extend grace period
- Fix issues with unified tool
- Resume when stable

**Option 2: Revert Tool Removal**
- Re-add legacy tool registrations
- Keep unified tool available
- Fix issues
- Try again later

**Option 3: Keep Both Indefinitely**
- Accept higher tool count
- Both interfaces available
- Some context optimization achieved
- No forced migration

---

## Communication Template

### Deprecation Announcement Email

```
Subject: [ACTION REQUIRED] CALM MCP Tools - Migration to Unified Interface

Dear CALM MCP Users,

We're improving the CALM MCP server by consolidating tools for better performance 
and ease of use. This requires migrating from legacy tools to our new unified interface.

WHAT'S CHANGING:
- 74 individual tools being replaced with 1 unified tool
- Better performance (12,500 token savings per conversation)
- Simpler, more consistent interface
- All functionality preserved

TIMELINE:
- NOW: Deprecation warnings added to legacy tools
- [DATE + 4 weeks]: Legacy tools will be removed
- Grace period: Minimum 4 weeks, possibly longer

ACTION REQUIRED:
1. Review the migration guide: [link]
2. Update your code to use calm_resource()
3. Test in staging
4. Deploy before [DATE]

MIGRATION EXAMPLE:
Before: get_calm_tasks(project_id="P001")
After:  calm_resource(resource="tasks", operation="list", project_id="P001")

SUPPORT:
- Migration guide: [link]
- Training video: [link]
- Questions? Contact: [support]

Thank you for your cooperation!
The CALM MCP Team
```

---

## Success Metrics

### Phase 3 Complete When:

✅ **Migration**:
- < 5% of API calls use legacy tools
- All teams have migrated or explicitly acknowledged
- No active users blocked by migration

✅ **Stability**:
- Unified tool performs as well as legacy
- No increase in errors
- No performance degradation

✅ **Documentation**:
- Migration guide complete
- All examples updated
- Training materials available

✅ **Final Tool Count**:
- ~25-30 tools (down from 74)
- 66% reduction achieved
- Context savings: 13,000+ tokens

---

## Risk Assessment

### High Risk Items

1. **User Disruption**
   - Mitigation: Long grace period, clear communication
   - Rollback: Keep legacy tools if needed

2. **Undiscovered Dependencies**
   - Mitigation: Monitor usage carefully
   - Rollback: Delay removal, fix issues

3. **Unified Tool Issues**
   - Mitigation: Thorough testing in Phase 1 & 2
   - Rollback: Keep legacy tools available

### Medium Risk Items

1. **Training Burden**
   - Mitigation: Excellent documentation, examples
   - Impact: Support tickets may increase temporarily

2. **Adoption Resistance**
   - Mitigation: Show benefits, make migration easy
   - Impact: May need longer grace period

---

## Phase 3 Checklist

### Before Starting Phase 3A

- [ ] Phase 1 & 2 in production (2+ weeks)
- [ ] No critical issues with unified tool
- [ ] Usage metrics collected
- [ ] Migration guide written
- [ ] Team approval obtained

### During Phase 3A (Deprecation Warnings)

- [ ] Add warnings to all legacy tools
- [ ] Update documentation
- [ ] Send announcement email
- [ ] Monitor feedback
- [ ] Answer questions

### During Phase 3B (Grace Period)

- [ ] Track migration progress
- [ ] Update migration guide based on feedback
- [ ] Extend period if needed
- [ ] Get final approval

### Before Phase 3C (Removal)

- [ ] Migration >95% complete
- [ ] No blockers identified
- [ ] Rollback plan ready
- [ ] Final approval obtained

### During Phase 3C (Removal)

- [ ] Remove legacy registrations
- [ ] Delete legacy modules
- [ ] Update docs
- [ ] Bump version
- [ ] Monitor closely

### After Phase 3C

- [ ] Verify ~25 tools achieved
- [ ] Measure context savings
- [ ] Document lessons learned
- [ ] Celebrate success! 🎉

---

## Conclusion

**Phase 3 is the final step to achieve our consolidation goals.**

**Key Principles**:
1. User-first: No one left behind
2. Safety: Long grace period, clear rollback
3. Communication: Over-communicate the changes
4. Support: Help users migrate successfully

**Timeline**: Minimum 6 weeks (2 weeks warnings + 4 weeks grace)

**Success**: ~25 tools, 66% reduction, 13,000+ token savings

---

**DO NOT START PHASE 3 until Phase 1 & 2 are validated in production!**

---

**Generated**: 2026-09-22  
**Status**: PLANNING ONLY  
**Implementation**: After production validation + grace period
