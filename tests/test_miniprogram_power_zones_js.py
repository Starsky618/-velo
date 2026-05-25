"""小程序功率区间展示工具测试：锁住 0W 展示口径。"""

import json
import subprocess
import textwrap
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _run_node(script: str):
    result = subprocess.run(
        ["node", "-e", textwrap.dedent(script)],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=True,
    )
    return json.loads(result.stdout)


def test_build_pedaling_power_zones_excludes_z1_zero_seconds_and_recomputes_percent():
    """活动详情默认展示真实蹬踏时间：Z1 扣 0W，百分比按新总时长重算。"""
    rows = _run_node(
        """
        const { buildPedalingPowerZones } = require('./miniprogram/utils/power-zones.js')
        const rows = buildPedalingPowerZones([
          { zone: 'Z1', name: '恢复', seconds: 1000, percent: 63, zero_seconds: 600 },
          { zone: 'Z2', name: '耐力', seconds: 600, percent: 37 }
        ])
        process.stdout.write(JSON.stringify(rows))
        """
    )

    assert rows[0]["seconds"] == 400
    assert rows[0]["percent"] == 40
    assert rows[0]["timeText"] == "7分"
    assert rows[1]["seconds"] == 600
    assert rows[1]["percent"] == 60


def test_build_pedaling_power_zones_treats_missing_zero_seconds_as_zero():
    """老活动如果还没有 zero_seconds 字段，展示层不报错、不乱扣。"""
    rows = _run_node(
        """
        const { buildPedalingPowerZones } = require('./miniprogram/utils/power-zones.js')
        const rows = buildPedalingPowerZones([
          { zone: 'Z1', name: '恢复', seconds: 300, percent: 50 },
          { zone: 'Z2', name: '耐力', seconds: 300, percent: 50 }
        ])
        process.stdout.write(JSON.stringify(rows))
        """
    )

    assert rows[0]["seconds"] == 300
    assert rows[0]["percent"] == 50
    assert rows[1]["percent"] == 50


def test_format_power_zone_rows_adds_readable_time_without_changing_backend_percent():
    """训练结构页右侧区间栏只格式化展示，不二次改后端已经算好的百分比。"""
    rows = _run_node(
        """
        const { formatPowerZoneRows } = require('./miniprogram/utils/power-zones.js')
        const rows = formatPowerZoneRows([
          { zone: 'Z1', name: '恢复', seconds: 7200, percent: 20 },
          { zone: 'Z2', name: '耐力', seconds: 1800, percent: 5 }
        ])
        process.stdout.write(JSON.stringify(rows))
        """
    )

    assert rows[0]["percent"] == 20
    assert rows[0]["timeText"] == "2.0h"
    assert rows[1]["timeText"] == "30分"


def test_training_distribution_switch_refetches_with_exclude_zero_and_updates_raw_zones():
    """训练结构页开关必须重新请求，并把后端双态 raw_zones 刷到页面上。"""
    result = _run_node(
        """
        ;(async function () {
          const apiPath = require.resolve('./miniprogram/utils/api.js')
          const calls = []
          const storageWrites = []
          const responses = [
            {
              data_complete: true,
              insufficient_power_data: false,
              groups: [{ key: 'endurance', label: '耐力', percent: 100 }],
              raw_zones: [{ zone: 'Z1', name: '恢复', seconds: 1000, percent: 75 }],
              actions: [],
              week_plan: []
            },
            {
              data_complete: true,
              insufficient_power_data: false,
              groups: [{ key: 'endurance', label: '耐力', percent: 100 }],
              raw_zones: [{ zone: 'Z1', name: '恢复', seconds: 400, percent: 44 }],
              actions: [],
              week_plan: []
            }
          ]
          require.cache[apiPath] = {
            id: apiPath,
            filename: apiPath,
            loaded: true,
            exports: {
              get: function (url, params) {
                calls.push({ url: url, params: params })
                return Promise.resolve(responses.shift())
              }
            }
          }
          global.wx = {
            getStorageSync: function () { return false },
            setStorageSync: function (key, value) { storageWrites.push({ key: key, value: value }) },
            stopPullDownRefresh: function () {},
            showToast: function () {}
          }
          let pageConfig = null
          global.Page = function (config) { pageConfig = config }

          require('./miniprogram/pages/training-distribution/training-distribution.js')
          const page = Object.assign({}, pageConfig, {
            data: JSON.parse(JSON.stringify(pageConfig.data)),
            setData: function (patch) { Object.assign(this.data, patch) }
          })

          await page.fetchDistribution(false)
          page.onExcludeZeroChange({ detail: { value: true } })
          await new Promise(function (resolve) { setImmediate(resolve) })

          process.stdout.write(JSON.stringify({
            calls: calls,
            storageWrites: storageWrites,
            excludeZero: page.data.excludeZero,
            rawZones: page.data.rawZones
          }))
        })().catch(function (err) {
          console.error(err)
          process.exit(1)
        })
        """
    )

    assert result["calls"][0]["params"]["exclude_zero"] is False
    assert result["calls"][1]["params"]["exclude_zero"] is True
    assert result["storageWrites"][0]["value"] is True
    assert result["excludeZero"] is True
    assert result["rawZones"][0]["seconds"] == 400
    assert result["rawZones"][0]["percent"] == 44
    assert result["rawZones"][0]["timeText"] == "7分"
