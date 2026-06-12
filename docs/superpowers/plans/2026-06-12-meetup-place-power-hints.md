# Meetup Place + Power Hints Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让发起约骑的人可以在强度默认带出功率/均速后手动修改，并能用地图/搜索选择集合点、保存常用集合点。

**Architecture:** 强度提示字段放在 `meetups` 表，跟随草稿创建、修改、详情返回。常用集合点新建 `meetup_favorite_places` 表，只归当前用户所有；腾讯地点搜索复用现有 `app.route_book.tencent_place.search_place`，由后端转发，避免小程序接触服务端密钥。

**Tech Stack:** FastAPI + SQLAlchemy + Alembic + pytest；微信小程序 JS/WXML/WXSS；腾讯地点检索已有服务端客户端。

---

### Task 1: Persist Meetup Power And Speed Hints

**Files:**
- Modify: `app/meetup/models.py`
- Modify: `app/meetup/schemas.py`
- Modify: `app/meetup/service.py`
- Modify: `app/meetup/router.py`
- Modify: `tests/conftest.py`
- Modify: `tests/test_meetup_api.py`
- Create: `migrations/versions/20260612_meetup_place_power_hints.py`

- [x] **Step 1: Write failing API test**

Add a test that creates a meetup with:

```python
payload["recommended_power_label"] = "FTP 180-220W"
payload["average_speed_range"] = "24-27 km/h"
```

Assert create, patch, detail, and list responses return those exact strings.

- [x] **Step 2: Run red test**

Run: `python3 -m pytest tests/test_meetup_api.py::test_create_patch_and_list_return_custom_power_speed_hints -q`

Expected: FAIL because the schema currently forbids those fields.

- [x] **Step 3: Implement minimal backend fields**

Add nullable `recommended_power_label` and `average_speed_range` fields to model, schemas, service create/update, response assembly, SQLite fixture table, and Alembic migration.

- [x] **Step 4: Run green test**

Run: `python3 -m pytest tests/test_meetup_api.py::test_create_patch_and_list_return_custom_power_speed_hints -q`

Expected: PASS.

### Task 2: Add Meetup Favorite Places And Place Search API

**Files:**
- Modify: `app/meetup/models.py`
- Modify: `app/meetup/schemas.py`
- Modify: `app/meetup/service.py`
- Modify: `app/meetup/router.py`
- Modify: `tests/conftest.py`
- Modify: `tests/test_meetup_api.py`
- Create: `migrations/versions/20260612_meetup_place_power_hints.py`

- [x] **Step 1: Write failing API tests**

Add tests for:

```python
POST /api/meetups/favorite-places
GET /api/meetups/favorite-places
DELETE /api/meetups/favorite-places/{place_id}
GET /api/meetups/place-search?keyword=晋祠&region=太原
```

Assert favorite places are scoped to the current user, sorted by most recently used, and place search returns the mocked Tencent result without exposing secrets.

- [x] **Step 2: Run red tests**

Run: `python3 -m pytest tests/test_meetup_api.py::test_meetup_favorite_places_are_user_scoped_and_sort_by_recent_use tests/test_meetup_api.py::test_meetup_place_search_wraps_tencent_place_without_secret -q`

Expected: FAIL because routes and model do not exist.

- [x] **Step 3: Implement minimal favorite-place backend**

Create `MeetupFavoritePlace` model with user id, name, address, latitude, longitude, usage count, last used time, timestamps. Add service helpers and three routes. Add place-search route that calls `tencent_place.search_place` and maps config errors to 503, search errors to 422.

- [x] **Step 4: Run green tests**

Run: `python3 -m pytest tests/test_meetup_api.py::test_meetup_favorite_places_are_user_scoped_and_sort_by_recent_use tests/test_meetup_api.py::test_meetup_place_search_wraps_tencent_place_without_secret -q`

Expected: PASS.

### Task 3: Wire Mini Program Create And Picker Pages

**Files:**
- Modify: `miniprogram/utils/api.js`
- Modify: `miniprogram/pages/meetup-create/meetup-create.js`
- Modify: `miniprogram/pages/meetup-create/meetup-create.wxml`
- Modify: `miniprogram/pages/meetup-create/meetup-create.wxss`
- Modify: `miniprogram/pages/map-picker/map-picker.js`
- Modify: `miniprogram/pages/map-picker/map-picker.wxml`
- Modify: `miniprogram/pages/map-picker/map-picker.wxss`
- Modify: `tests/test_meetup_miniprogram_static.py`

- [x] **Step 1: Write failing static tests**

Add tests proving:

```text
meetup-create has onTapChooseMeetingPoint, saveMeetingPointAsFavorite, favoritePlaces
map-picker supports kind=meeting and calls api.searchMeetupPlace
confirm page has editable recommended_power_label and average_speed_range inputs
create/save/publish payloads include recommended_power_label and average_speed_range
```

- [x] **Step 2: Run red tests**

Run: `python3 -m pytest tests/test_meetup_miniprogram_static.py::test_create_page_supports_meeting_point_map_and_favorites tests/test_meetup_miniprogram_static.py::test_create_page_persists_custom_power_speed_hints tests/test_meetup_miniprogram_static.py::test_map_picker_supports_meeting_search -q`

Expected: FAIL because the frontend hooks do not exist.

- [x] **Step 3: Implement minimal mini-program wiring**

Reuse `map-picker` for `kind=meeting`, add search box/result cards, write selected meeting point into `pendingMapPoint`, load favorite places on create page, allow saving current meeting point, and include custom power/speed fields in create/update/publish payloads. Pace picker should still auto-fill defaults, while manual edits override the current values.

- [x] **Step 4: Run green static tests**

Run: same static test command.

Expected: PASS.

### Task 4: Final Verification

**Files:**
- All modified files.

- [x] **Step 1: Run targeted backend + mini-program tests**

Run: `python3 -m pytest tests/test_meetup_api.py tests/test_meetup_miniprogram_static.py tests/test_tencent_place.py -q`

Expected: PASS.

- [x] **Step 2: Run syntax checks**

Run: `node --check miniprogram/pages/meetup-create/meetup-create.js`

Expected: PASS.

Run: `node --check miniprogram/pages/map-picker/map-picker.js`

Expected: PASS.

Run: `python3 -m alembic heads`

Expected: one head containing the new migration.

- [x] **Step 3: Self review and code review**

Check diff manually for schema/route ordering, model-migration-fixture consistency, secret exposure, and mini-program payload drift. Then request code review before calling the work complete.
