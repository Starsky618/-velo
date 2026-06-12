// ride-card 组件 —— 骑行卡片列表（可复用于首页 / 个人主页）
// 设计思路：把首页"今日骑行"列表的卡片抽出来做组件，
// 让 home 和 profile 共用同一份 wxml/wxss/逻辑，避免复制粘贴出现两个版本飘移。
// 类比：像快递柜里的"统一格式标签"，无论谁来打印（home 还是 profile），
// 都使用同一台机器，保证格式完全一致，
// 这样以后改字段（如多加"心率"显示）只在一处改。
//
// 输入（properties.rides 数组 / 每条字段对齐后端 ActivitySummary schema）：
//   - id: 活动 ID（必填 / 用作 wx:key + 点击事件 payload / 不叫 activity_id）
//   - title: 活动标题
//   - distance: 距离（公里 / service 层已从米转过 / wxml 用 wxs km() 保 2 位）
//   - duration: 时长（秒 / wxml 用 wxs secToHm() 转 "Xh Ymin"）
//   - avg_speed: 均速（km/h / worker 已转 / 直接显示）
//   - elevation_gain: 爬升（米 / float / wxml 用 wxs roundInt() 取整）
//   - startedAtDisplay: 父页面预格式化的"今天 09:30"等字符串（subtitle 槽位 / 可选）
// 输出：triggerEvent("tap-ride", { activity_id })——父页面决定跳详情或其他动作
// 边界：
// - 组件不直接调用 api（保持纯展示）
// - 组件不修改 properties.rides（单向数据流）
// - 数据为空显示空态 / 避免 "-" 占位
// - 与父页面契约：父页透传后端 ActivitySummary + 可选补 startedAtDisplay /
//   组件不脑补字段名 / 不再做 distance_km / duration_display 那种映射层

const routeThumb = require('../../utils/route-thumb')

Component({
  properties: {
    // 骑行列表数据；外部传入，组件不修改。
    // 每条可选带 trackPoints（[[lon, lat], ...]，父页面从 track-thumbs 端点拉好塞入），
    // 有则组件在左侧画路线轨迹缩略线（iGPSport 式），没有则缩略图槽整块隐藏。
    rides: {
      type: Array,
      value: [],
    },
    // 空态文案，允许父页面定制（home / profile 文案略不同）
    emptyText: {
      type: String,
      value: '还没有骑行记录',
    },
    // 空态副文案
    emptySubtext: {
      type: String,
      value: '上传 GPX 或绑定 Strava 同步活动',
    },
    // 是否显示空态（外层可强制隐藏）
    showEmpty: {
      type: Boolean,
      value: true,
    },
  },

  lifetimes: {
    // created（不是 attached）：observers 可能在 attached 之前触发，
    // 晚初始化会让首批 trackPoints 撞上 guard 被静默丢弃（集成审 Important #1）
    created() {
      // 已画过的活动 id 登记（组件内部状态，不进 data 不触发渲染）：
      // 父页面翻页/局部 setData 都会触发 observer，靠它防止同一张图反复重画
      this._drawnThumbs = {};
    },
  },

  observers: {
    // 父页面塞入 trackPoints 后自动画缩略线。
    // setTimeout 兜底 canvas 初始化（hidden 翻转与绘制不能同帧，陷阱 #17 pattern）。
    // ⚠ 绘制坐标 70×70px = wxss .ride-thumb-canvas 140×140rpx 的一半（旧 canvas API 2:1）
    rides: function (rides) {
      if (!Array.isArray(rides) || !this._drawnThumbs) return;
      const that = this;
      const toDraw = rides.filter(function (r) {
        return r && r.id && Array.isArray(r.trackPoints) && r.trackPoints.length >= 2
          && !that._drawnThumbs[r.id];
      });
      if (toDraw.length === 0) return;
      toDraw.forEach(function (r) { that._drawnThumbs[r.id] = true; });
      setTimeout(function () {
        toDraw.forEach(function (r) {
          routeThumb.drawRouteThumb('ride-thumb-' + r.id, r.trackPoints, {
            width: 70,
            height: 70,
            lineWidth: 2,
            component: that,
          });
        });
      }, 150);
    },
  },

  methods: {
    // 卡片点击事件 —— 把 activity_id 通过 emit 抛给父页面
    // 父页面决定后续动作（跳详情 / 弹出菜单等）
    onTapRide(e) {
      const { activityId } = e.currentTarget.dataset;
      // 三审 Important 修（A）：用 == null 防 truthiness 陷阱（id=0 数字 0 被 ! 误判 falsy）
      // 虽然 DB auto-increment 实际从 1 起 / id=0 极不可能 / 但写法语义更稳
      if (activityId == null) return;
      this.triggerEvent('tap-ride', { activity_id: activityId });
    },
  },
});
