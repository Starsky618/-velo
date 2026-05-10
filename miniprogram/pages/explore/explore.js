/**
 * 探索页 — 赛段瀑布流逻辑（task-4.4 改造）
 *
 * 这个文件干什么：
 *   - 拉后端 GET /api/segments 列表（默认按 created_at desc 排序）
 *   - 顶部 6 城横向筛选条（点 chip 切换 → 重新拉数据）
 *   - 主体瀑布流（segment-card / 距离 / 爬升 / 城市 / 难度 / NEW 标签）
 *   - 滑到底部 onReachBottom → 拉下一页追加（直到 hasMore=false）
 *
 * 类比：像翻一本"全国骑行赛段大全"杂志——
 *   顶部翻到"上海"分类 → 下面只显示上海赛段；翻到底部 → 自动续印下一页。
 *
 * 操作注意事项：
 *   - cities 是 7 城枚举（CLAUDE.md spec §3.1.3 / phase5 PRD D 决策）/ 不要漏 unknown
 *     但 unknown 不在筛选条上展示（用户视角"未分类"无意义）/ 不传 city 参数 = 全部
 *   - NEW 标签暂用占位（后端 SegmentListItem schema 不返 created_at / isNew 全 false）
 *     未来 hotfix 后端补字段后 / 这里把 enrich 函数里的 isNew 计算逻辑打开即可
 *   - difficulty 4 档：easy/medium/hard/extreme（spec §3.1.3）/ 中文标签在 enrich 时映射
 *
 * 数据流自治：
 *   data.segments 由本页面持有 / 切换城市完全重置 / 不与其他页面共享 state
 */

const api = require('../../utils/api')

// 6 城展示枚举（不含 unknown / 用户视角无意义）+ 中文标签映射
const CITIES = [
  { code: 'beijing', label: '北京' },
  { code: 'shanghai', label: '上海' },
  { code: 'hangzhou', label: '杭州' },
  { code: 'shenzhen', label: '深圳' },
  { code: 'chengdu', label: '成都' },
  { code: 'taiyuan', label: '太原' },
]

// 城市 code → 中文 label（含 unknown 兜底 / 卡片展示用）
const CITY_LABEL_MAP = {
  beijing: '北京',
  shanghai: '上海',
  hangzhou: '杭州',
  shenzhen: '深圳',
  chengdu: '成都',
  taiyuan: '太原',
  unknown: '',  // 未分类不展示城市标签（避免视觉噪音）
}

// 难度 code → 中文 label
const DIFFICULTY_LABEL_MAP = {
  easy: '入门',
  medium: '中等',
  hard: '困难',
  extreme: '魔鬼',
}

// 30 天毫秒数（NEW 标签判断用）
const NEW_THRESHOLD_MS = 30 * 24 * 60 * 60 * 1000

const PAGE_SIZE = 20

Page({
  data: {
    cities: CITIES,
    activeCity: '',       // '' = 全部 / 否则为 6 城 code 之一
    segments: [],         // 已加载的赛段列表（多页累积）
    page: 1,              // 当前已加载到第几页
    loading: false,       // 首屏 loading
    loadingMore: false,   // 分页 loading（底部小提示）
    hasMore: true,        // 是否还有下一页
    activeUsers: [],      // Sprint 5 task-3：骑友 section（最近活跃用户 / 横向 scroll）
  },

  onLoad() {
    // 并行拉赛段 + 骑友（Promise.all 不串行 / 减少首屏感知延迟）
    this.fetchSegments(1, '')
    this.fetchActiveUsers()
  },

  /**
   * 拉最近活跃骑友（Sprint 5 task-3 / 探索 tab 骑友 section）。
   *
   * 设计：
   * - 默认 limit=10 / 横向 scroll 一屏 6 个 + 滑动看后 4 个
   * - 失败静默 / 不阻断赛段瀑布流（社交 section 是辅助 / 不应让主功能不可用）
   * - 0 用户场景（你们三人都没活动时）→ activeUsers=[] / wxml wx:if 整 section 隐藏
   */
  fetchActiveUsers() {
    api.get('/api/user/active?limit=10')
      .then((data) => {
        this.setData({ activeUsers: data.items || [] })
      })
      .catch(() => {
        // 静默失败 / 不影响赛段瀑布流主功能
        this.setData({ activeUsers: [] })
      })
  },

  /**
   * 点骑友头像跳到 user 主页（看他人 profile）。
   * 复用现有 /pages/user/user?id=X 路径（task-4.3 已有 / 通知中心 kom_lost 也用此路径）。
   */
  onTapRiderAvatar(e) {
    const userId = e.currentTarget.dataset.id
    if (!userId) return
    wx.navigateTo({ url: '/pages/user/user?id=' + userId })
  },

  /**
   * 拉一页赛段数据。
   *
   * @param {number} page - 第几页（从 1 起）
   * @param {string} city - 城市筛选 code / 空串表示不筛
   */
  fetchSegments(page, city) {
    const isFirstPage = page === 1
    if (isFirstPage) {
      this.setData({ loading: true })
    } else {
      this.setData({ loadingMore: true })
    }

    api.getSegmentsList({ city: city, page: page, page_size: PAGE_SIZE })
      .then((res) => {
        const items = (res.items || []).map(this._enrichItem)
        const totalLoaded = isFirstPage ? items.length : this.data.segments.length + items.length
        const hasMore = totalLoaded < (res.total || 0)

        this.setData({
          segments: isFirstPage ? items : this.data.segments.concat(items),
          page: page,
          hasMore: hasMore,
          loading: false,
          loadingMore: false,
        })
      })
      .catch((err) => {
        this.setData({ loading: false, loadingMore: false })
        wx.showToast({
          title: (err && err.message) || '加载失败',
          icon: 'none',
        })
      })
  },

  /**
   * 给单个 segment 加前端展示需要的派生字段。
   *
   * 后端真返字段（SegmentListItem 实证）：
   *   id / name / distance / elevation_gain / avg_gradient / max_gradient
   *   difficulty / city / start_lat / start_lon / end_lat / end_lon / entries
   *
   * 前端补充字段：
   *   - cityLabel：city code → 中文（unknown → 空串）
   *   - difficultyLabel：difficulty code → 中文
   *   - isNew：NEW 标签判断（30 天内 created → true）
   */
  _enrichItem(item) {
    // distance 后端已是公里 / 但保留 1 位小数避免视觉杂乱
    const distance = typeof item.distance === 'number' ? item.distance.toFixed(1) : item.distance
    const elevation = item.elevation_gain != null ? Math.round(item.elevation_gain) : null

    // NEW 标签：30 天内 created 显示
    // 后端 SegmentListItem.created_at 是 ISO datetime 字符串（task-4.4 hotfix 补字段 / 2026-05-10）
    const created = item.created_at ? new Date(item.created_at).getTime() : 0
    const isNew = created > 0 && (Date.now() - created) < NEW_THRESHOLD_MS

    return {
      id: item.id,
      name: item.name,
      distance: distance,
      elevation_gain: elevation,
      difficulty: item.difficulty || 'medium',
      difficultyLabel: DIFFICULTY_LABEL_MAP[item.difficulty] || '中等',
      city: item.city,
      cityLabel: CITY_LABEL_MAP[item.city] || '',
      entries: item.entries || 0,
      isNew: isNew,
    }
  },

  /**
   * 切换城市筛选。
   * 完全重置（清空 segments + page=1 + hasMore=true）后重新拉数据。
   */
  switchCity(e) {
    const city = e.currentTarget.dataset.city || ''
    if (city === this.data.activeCity) return  // 同城重复点不做事

    this.setData({
      activeCity: city,
      segments: [],
      page: 1,
      hasMore: true,
    })
    this.fetchSegments(1, city)
  },

  /**
   * 点卡片跳赛段详情页（task-4.5 已 ship 空架子）。
   */
  goSegment(e) {
    const id = e.currentTarget.dataset.id
    if (!id) return
    wx.navigateTo({ url: '/pages/segment/segment?id=' + id })
  },

  /**
   * 滑到底部触发分页加载。
   * 守卫：已没下一页 / 正在加载 → 静默 return（防双触发）
   */
  onReachBottom() {
    if (!this.data.hasMore) return
    if (this.data.loading || this.data.loadingMore) return
    this.fetchSegments(this.data.page + 1, this.data.activeCity)
  },
})
