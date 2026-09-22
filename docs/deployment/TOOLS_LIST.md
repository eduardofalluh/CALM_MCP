# Tools List - Read-Only vs Read-Write

## READ-ONLY SERVER (12 tools)

### Import modules:
```python
from src.calm.tools import (
    unified,
    health,
    oauth_info,
    user_uuid_helper,
    test_repo,
)
```

### Register:
```python
unified.register(mcp)
health.register(mcp)
oauth_info.register(mcp)
user_uuid_helper.register(mcp)
test_repo.register(mcp)
```

### Tools provided (12):
1. calm_resource (read operations only)
2. calm_health
3. get_calm_oauth_endpoints
4. get_calm_oauth_metadata
5. get_calm_authorization_server_metadata
6. get_my_calm_user_uuid_instructions
7. tm_health
8. get_tm_statistics
9. get_tm_test_cases
10. get_tm_test_case_full
11. get_tm_requirements
12. tm_odata_read

---

## READ-WRITE SERVER (21 tools - ALL)

### Import modules:
```python
from src.calm.tools import (
    unified,
    health,
    oauth_info,
    advanced_write,
    user_uuid_helper,
    test_repo,
    test_repo_write,
)
```

### Register:
```python
unified.register(mcp)
health.register(mcp)
oauth_info.register(mcp)
advanced_write.register(mcp)
user_uuid_helper.register(mcp)
test_repo.register(mcp)
test_repo_write.register(mcp)
```

### Tools provided (21):
All 12 from read-only server PLUS:

13. calm_resource (write operations: create/update/delete)
14. calm_api_write
15. calm_api_delete
16. create_tm_test_case
17. update_tm_test_case
18. delete_tm_test_case
19. create_tm_requirement
20. delete_tm_requirement
21. tm_odata_write
22. tm_odata_delete

Wait that's 22... let me recount from the actual test:

Actually from live test we have exactly 21:
1. calm_api_delete
2. calm_api_write
3. calm_health
4. calm_resource
5. create_tm_requirement
6. create_tm_test_case
7. delete_tm_requirement
8. delete_tm_test_case
9. get_calm_authorization_server_metadata
10. get_calm_oauth_endpoints
11. get_calm_oauth_metadata
12. get_my_calm_user_uuid_instructions
13. get_tm_requirements
14. get_tm_statistics
15. get_tm_test_case_full
16. get_tm_test_cases
17. tm_health
18. tm_odata_delete
19. tm_odata_read
20. tm_odata_write
21. update_tm_test_case

---

## DIFFERENCE

**Read-Only excludes these 2 modules:**
- advanced_write (provides: calm_api_write, calm_api_delete)
- test_repo_write (provides: 7 TM write tools)

**Total difference: 9 tools**
