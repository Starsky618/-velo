"""
bindchart 指针坐标测试——专门防“点右边却读左边”的错位。

微信 canvas 触摸事件里的 touch.x 已经是 canvas 内坐标；
如果再减一次 canvas.left，就会把读数整体推到左边。
"""

import subprocess
import textwrap
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _run_node(script: str) -> None:
    subprocess.run(
        ["node", "-e", script],
        cwd=ROOT,
        check=True,
        text=True,
    )


def test_canvas_touch_x_is_used_as_local_coordinate_without_subtracting_left():
    script = textwrap.dedent(
        """
        const bindchart = require('./miniprogram/utils/bindchart')
        const page = {
          __bindchartStates: {
            '#chart': {
              left: 60,
              width: 300,
              pad: { left: 0, right: 0 },
              chartW: 300,
              maxX: 100,
              xData: [0, 25, 50, 75, 100],
            },
          },
        }
        const idx = bindchart.getNearestIndexFromTouch(page, '#chart', { x: 150, clientX: 210 })
        if (idx !== 2) {
          throw new Error('expected local canvas x=150 to select index 2, got ' + idx)
        }
        """
    )

    _run_node(script)


def test_client_x_fallback_subtracts_canvas_left():
    script = textwrap.dedent(
        """
        const bindchart = require('./miniprogram/utils/bindchart')
        const page = {
          __bindchartStates: {
            '#chart': {
              left: 60,
              width: 300,
              pad: { left: 0, right: 0 },
              chartW: 300,
              maxX: 100,
              xData: [0, 25, 50, 75, 100],
            },
          },
        }
        const idx = bindchart.getNearestIndexFromTouch(page, '#chart', { clientX: 210 })
        if (idx !== 2) {
          throw new Error('expected page clientX=210 with left=60 to select index 2, got ' + idx)
        }
        """
    )

    _run_node(script)
