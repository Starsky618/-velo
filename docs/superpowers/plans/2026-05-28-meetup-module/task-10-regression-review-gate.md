# Task 10: Regression And Review Gate Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Prove the meetup module works end-to-end and pass the required multi-surface review gate before accepting v1.

**Architecture:** This is the final inspection before letting riders use the room. It does not add product scope; it creates regression checks, runs real commands, fixes discovered defects in the task that introduced them, and produces review evidence.

**Tech Stack:** pytest, Alembic, grep architecture audit, manual mini program smoke pass, Claude reviewer prompts, Codex third review.

---

## User Story

Tim does not care that ten commits exist if a real rider still cannot create, publish, join, and finish a meetup. This task makes the whole journey walkable and forces three independent review surfaces to agree that Critical and Important are zero.

## Files

- Create: `tests/test_meetup_regression_contracts.py`
- Modify: `app/route_book/models.py`, `app/route_book/schemas.py`, `app/route_book/service.py`, `app/route_book/router.py`, `app/meetup/models.py`, `app/meetup/schemas.py`, `app/meetup/service.py`, `app/meetup/router.py`, `app/meetup/media_service.py`, `app/meetup/cron.py`, `app/main.py`, `scheduler.py`, `app/user/service.py`, `app/segment/router.py`, `miniprogram/utils/api.js`, `miniprogram/pages/meetups-list/meetups-list.js`, `miniprogram/pages/meetup-detail/meetup-detail.js`, `miniprogram/pages/meetup-create/meetup-create.js` only if a regression test or reviewer finding proves the owning task is wrong.
- Test: `tests/test_meetup_regression_contracts.py`, `tests/test_meetup_models.py`, `tests/test_route_book_api.py`, `tests/test_meetup_service.py`, `tests/test_meetup_api.py`, `tests/test_meetup_participation.py`, `tests/test_meetup_media.py`, `tests/test_meetup_cron_delete_user.py`, `tests/test_segment_upcoming_meetups.py`, `tests/test_meetup_miniprogram_static.py`

## Evidence Anchors

- [✓ grep] spec requires true-use regression with 8 hot spots: `docs/superpowers/specs/2026-05-28-meetup-module-design.md:513-528`.
- [✓ grep] architecture forced grep output is mandatory: `docs/agent-rules/agent-collaboration.md:212-232`.
- [✓ grep] spec Task 10 estimate and scope: `docs/superpowers/specs/2026-05-28-meetup-module-design.md:546`.
- [✓ grep] every execution task carries commit instructions in the project docs workflow: `docs/README.md:115`.

## TDD Protocol

- [ ] 测试者先按 Step 2 写红测；实现者只能在红测确认失败后修 Task 1-9 所属文件；复审时确认测试者≠实现者，并保留 reviewer 证据。

## Steps

- [ ] **Step 1: Read verification scope**

```bash
nl -ba docs/superpowers/specs/2026-05-28-meetup-module-design.md | sed -n '513,528p;533,546p'
nl -ba docs/agent-rules/agent-collaboration.md | sed -n '212,232p'
```

Expected: you see unit/API/frontend/scheduler hot spots and architecture report requirements.

- [ ] **Step 2: Write red regression contract tests**

Create `tests/test_meetup_regression_contracts.py`:

```python
"""约骑模块 Task 10：整体验收静态合同测试。"""

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def test_all_meetup_and_route_book_modules_exist():
    for path in [
        "app/meetup/models.py",
        "app/meetup/service.py",
        "app/meetup/media_service.py",
        "app/meetup/cron.py",
        "app/meetup/router.py",
        "app/route_book/models.py",
        "app/route_book/service.py",
        "app/route_book/router.py",
    ]:
        assert (ROOT / path).exists(), path


def test_main_mounts_route_book_and_meetup_routers():
    main = _read("app/main.py")

    assert "from app.route_book.router import router as route_book_router" in main
    assert "from app.meetup.router import router as meetup_router" in main
    assert "app.include_router(route_book_router)" in main
    assert "app.include_router(meetup_router)" in main


def test_scheduler_keeps_import_tick_and_meetup_tick_separate():
    scheduler = _read("scheduler.py")

    assert "run_import_tick()" in scheduler
    assert "run_meetup_complete_tick()" in scheduler
    assert "_meetup_tick_counter >= 20" in scheduler
    assert scheduler.count("logger.exception") >= 2


def test_schema_names_match_frontend_contract():
    schemas = _read("app/meetup/schemas.py")
    mini_api = _read("miniprogram/utils/api.js")

    for name in ["snapshot_route_name", "participants_count", "first_media_file_id", "route_book_id"]:
        assert name in schemas
    for helper in ["getMeetupsList", "getMeetupDetail", "createMeetup", "joinMeetup", "leaveMeetup", "getRouteBooksList"]:
        assert helper in mini_api


def test_route_book_router_exposes_spec_endpoints():
    router = _read("app/route_book/router.py")

    for snippet in [
        '@router.get("", response_model=schemas.RouteBookListResponse)',
        '@router.post("", response_model=schemas.RouteBookResponse)',
        '@router.get("/activity-candidates", response_model=schemas.ActivityCandidateResponse)',
        '@router.get("/{route_book_id}", response_model=schemas.RouteBookResponse)',
        '@router.delete("/{route_book_id}", status_code=204)',
    ]:
        assert snippet in router


def test_delete_draft_meetup_uses_storage_cleanup_and_delete_user_is_atomic():
    meetup_service = _read("app/meetup/service.py")
    user_service = _read("app/user/service.py")

    assert "def delete_draft_meetup" in meetup_service
    assert "_cleanup_meetup_storage(file_ids)" in meetup_service
    delete_user_block = user_service[user_service.index("def delete_user"):]
    assert "with db.begin()" in delete_user_block
    assert "_cleanup_meetup_storage(file_ids)" in delete_user_block


def test_no_v1_out_of_scope_frontend_features():
    mini = ROOT / "miniprogram" / "pages"
    text = "\n".join(path.read_text(encoding="utf-8") for path in mini.glob("meetup*/*.*"))

    for forbidden in ["路线足迹", "算法推荐", "为你推荐", "私聊", "私信", "评论", "关注", "点赞", "打招呼", "群聊"]:
        assert forbidden not in text


def test_plans_dependency_graph_has_no_back_edge():
    readme = _read("docs/superpowers/plans/2026-05-28-meetup-module/README.md")

    ordered = [f"T{i}" for i in range(1, 11)]
    position = {name: readme.index(name + "[") if name + "[" in readme else readme.index(name + ":") for name in ordered}
    edges = [
        ("T1", "T2"), ("T1", "T3"), ("T2", "T3"), ("T3", "T4"), ("T4", "T5"),
        ("T4", "T6"), ("T3", "T7"), ("T4", "T8"), ("T4", "T9"), ("T5", "T10"),
        ("T6", "T10"), ("T7", "T10"), ("T8", "T10"), ("T9", "T10"),
    ]
    for before, after in edges:
        assert position[before] < position[after]


def test_app_json_home_stays_first():
    data = json.loads(_read("miniprogram/app.json"))

    assert data["pages"][0] == "pages/home/home"
```

- [ ] **Step 3: Run red tests**

```bash
python3 -m pytest tests/test_meetup_regression_contracts.py -q
```

Expected: FAIL until all Task 1-9 files exist.

- [ ] **Step 4: Run full meetup pytest set**

Run:

```bash
python3 -m pytest \
  tests/test_meetup_models.py \
  tests/test_route_book_api.py \
  tests/test_meetup_service.py \
  tests/test_meetup_api.py \
  tests/test_meetup_participation.py \
  tests/test_meetup_media.py \
  tests/test_meetup_cron_delete_user.py \
  tests/test_segment_upcoming_meetups.py \
  tests/test_meetup_miniprogram_static.py \
  tests/test_meetup_regression_contracts.py \
  -q
```

Expected: PASS. If a test fails, fix the implementation file that owns the failure and rerun this exact command.

- [ ] **Step 5: Run selected existing regression tests**

Run:

```bash
python3 -m pytest \
  tests/test_segment_service_v5.py \
  tests/test_user_router_v5.py \
  tests/test_training_distribution.py \
  tests/test_training_distribution_static.py \
  tests/test_parse_activity_type.py \
  -q
```

Expected: PASS. These tests protect Segment/User/Training/Parser surfaces that meetup reads or sits beside.

- [ ] **Step 6: Run Alembic real migration cycle**

Run against a disposable dev database:

```bash
python3 -m alembic heads
python3 -m alembic upgrade head
python3 -m alembic downgrade sprint10_daily_training_load
python3 -m alembic upgrade head
```

Expected: migration upgrade and downgrade complete. If downgrade fails on FK order, fix Task 1 migration drop order.

- [ ] **Step 7: Run architecture dependency audit**

Run:

```bash
grep -rn "from app.meetup\\|import app.meetup" app/user app/activity app/segment scheduler.py
grep -rn "from app.route_book\\|import app.route_book" app/user app/activity app/segment app/meetup
grep -rh "^from app\\.\\|^import app\\." app/meetup/*.py app/route_book/*.py | sort -u
grep -A 1 "单向依赖\\|依赖方向\\|防火墙" CLAUDE.md docs/agent-rules/*.md
```

Expected:

- `scheduler.py` imports `app.meetup.cron`.
- `app/user/service.py` imports `app.meetup` for delete-user cleanup.
- `app/segment/router.py` imports `app.meetup.models` for upcoming-meetups.
- No `app/activity/` import of `app.meetup` or `app.route_book`.

- [ ] **Step 8: Run route smoke commands**

With local API running, run:

```bash
curl -sS http://127.0.0.1:8000/health
curl -sS "http://127.0.0.1:8000/api/meetups?status=OPEN&page=1&page_size=20"
curl -sS "http://127.0.0.1:8000/api/segments/1/upcoming-meetups"
```

Expected: health returns ok, public list/detail smoke calls return JSON, and no server traceback appears.

- [ ] **Step 9: Mini program smoke pass**

Open WeChat Developer Tools and manually walk:

1. `pages/meetups-list/meetups-list`: loading, empty/error, and list card states render.
2. `pages/meetup-detail/meetup-detail?id=<open_meetup_id>`: detail renders, join button calls backend, leave button calls backend.
3. `pages/meetup-create/meetup-create`: route step loads activity candidates, details step saves draft, publish step redirects to detail.

Expected: text fits, buttons are tappable, no page console error.

- [ ] **Step 10: Claude reviewer prompts**

Ask reviewer-spec-faithful:

```text
Review VELO meetup module implementation against docs/superpowers/specs/2026-05-28-meetup-module-design.md v1.8.
Scope: app/meetup/, app/route_book/, migrations/versions/20260528_meetup_route_book.py, app/main.py, scheduler.py, app/user/service.py delete_user hook, app/segment/router.py upcoming-meetups, miniprogram/pages/meetup*, tests/test_meetup*.
Focus: spec fidelity, v1 scope guard, state machine, 30 min + 30s cutoff, FOR UPDATE join race, route_book orphan semantics, GPX+FIT, media DB/storage direction, no route footprint or user-user interaction.
Output Critical / Important / Minor with file:line evidence only.
```

Ask reviewer-integration:

```text
Review VELO meetup module integration.
Run architecture-layer grep per docs/agent-rules/agent-collaboration.md §4.0.1.
Focus: app/user and app/segment reverse hooks, app/activity isolation, router mounts, Alembic env imports, test SQLite table coverage, scheduler exception isolation, storage cleanup, frontend/backend field names.
Output an "架构层依赖审查" section with ASCII dependency graph, reverse import state, reverse hook list with file:line, drift statement, and cycle import state.
```

- [ ] **Step 11: Codex third review**

Use a fresh Codex reviewer with this prompt:

```text
You are an independent Codex reviewer for VELO meetup module v1.
Read the spec, current diff, and real caller/callee code.
Do not repeat Claude findings unless you add new evidence.
Find only Critical/Important issues that block or materially risk ship.
Mandatory checks: spec §4, §5, §6, §7, §10, §11, §15; architecture grep per agent-collab §4.0.1; tests do not mock away FOR UPDATE/storage/delete semantics.
Return Critical / Important / Minor and final commit recommendation.
```

Expected: reviewer Critical+Important are zero, or all findings are fixed and re-reviewed.

- [ ] **Step 12: Self-review**

- [ ] Spec coverage: every line item in spec §10 tests and §11 Task 1-10 has a test or manual evidence.
- [ ] Placeholder scan: run the repository-wide plan sanity check from README.
- [ ] Type consistency: compare `app/meetup/schemas.py`, `miniprogram/utils/api.js`, and page usage for field spelling.
- [ ] Architecture: confirm regression fixes only touch Task 1-9 owned files and do not add route matching or meetup state logic to mini program pages.

- [ ] **Step 13: Commit**

```bash
git add tests/test_meetup_regression_contracts.py
git add app/meetup app/route_book app/main.py scheduler.py app/user/service.py app/segment/router.py app/segment/schemas.py miniprogram/app.json miniprogram/utils/api.js miniprogram/pages/meetups-list miniprogram/pages/meetup-detail miniprogram/pages/meetup-create tests/test_meetup*.py tests/test_route_book_api.py tests/test_segment_upcoming_meetups.py
git commit -F - <<'MSG'
test(meetup): task 10 verify meetup v1

Add regression contracts and finish meetup v1 through pytest, Alembic, architecture grep, mini program smoke, and multi-surface review.
Accept only after reviewer Critical and Important findings are zero.
MSG
```
