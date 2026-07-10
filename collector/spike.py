"""盘口尖峰判据 —— 纯函数 + 常量，只用标准库。

collector.py（生产采集器）与 scripts/replay_spike.py（历史回放调参）共用本模块，
所以"回放里验证过的阈值"必然就是"线上真正跑的阈值"。改判据只改这里。

设计依据（对 5 场 R16/QF 的 ticks.db 回放，13 个 ESPN 真事件为 ground truth）：

  线上旧逻辑 (pp≥4, 参考点取队头)   67 次推送 / 39 次误报 / 精确率 42%
  本模块     (双门槛 + 分级确认)     22 次推送 /  7 次误报 / 精确率 68%
  两者都抓到 12/13 个真事件，中位领先 ESPN 官方记录约 4 秒。

三条经验，都是回放推翻假设换来的：

1. 参考点必须取"最接近 WINDOW_S 秒前"的采样点。旧代码用 next() 取队头，而
   trail 保留 60 秒，于是判据实际变成"和一分钟前比"——盘口慢漂被当成尖峰。

2. pp 和 logit 必须双门槛。pp 单独用，会漏掉低概率腿的真实重估；logit 单独用，
   会把末段极端区的 2pp 抖动（94%→96%）放大成"重大变化"。各挡一端。

3. 不要用"三腿概率之和守恒"做一致性过滤。事件越剧烈，做市商撤单越狠，三腿
   mid 之和偏离 1 越远——梅西 83' 扳平那一刻三腿和从 100.4% 掉到 94.5%，
   守恒判据会把最该推的球直接毙掉。
"""

from __future__ import annotations

import math

WINDOW_S = 12  # 尖峰比较窗口
PP = 0.05  # 单腿 mid 变化门槛
LOGIT = 0.45  # 单腿 logit 变化门槛（与 PP 同时满足才算尖峰）
FAST_PP = 0.12  # 单腿 ≥ 此幅度 = 进球级，免确认立即推
CONFIRM_S = 5  # 中等跳变的确认等待
CONFIRM_KEEP = 0.6  # 确认时需保持的原始幅度比例
CONFIRM_MIN_PP = 0.03  # 确认时只看这么大以上的腿，避免拿噪声腿去判定
COOLDOWN_S = 60  # 两次推送最小间隔
TRAIL_S = 60  # mid 轨迹保留时长


def logit(p: float) -> float:
    p = min(max(p, 1e-4), 1 - 1e-4)
    return math.log(p / (1 - p))


def pick_ref(trail: list[tuple[float, float]], ts: float, window: float = WINDOW_S):
    """取最接近 window 秒前的采样点。trail 时序升序，队头可达 TRAIL_S 秒前。"""
    ref = None
    for x in trail:
        if ts - x[0] < window:
            break
        ref = x
    return ref


def spiked(ds: dict[str, tuple[float, float]], cur: dict[str, float]) -> dict[str, tuple[float, float]]:
    """ds: outcome → (delta, ref_mid)。返回同时跨过 pp 与 logit 双门槛的腿。"""
    return {
        oc: v
        for oc, v in ds.items()
        if oc in cur and abs(v[0]) >= PP and abs(logit(cur[oc]) - logit(v[1])) >= LOGIT
    }


def is_fast(hits: dict[str, tuple[float, float]]) -> bool:
    """进球级跳变：立即推，不为确认多等 CONFIRM_S 秒。"""
    return bool(hits) and max(abs(v[0]) for v in hits.values()) >= FAST_PP


def confirmed(ds: dict[str, tuple[float, float]], cur: dict[str, float]) -> bool:
    """跳变是否站住：任一显著腿在 CONFIRM_S 后仍保持 ≥ CONFIRM_KEEP 的原始幅度。

    专杀"闪跳又跳回"——那会让用户先收到「利好葡萄牙 +12pp」，
    一分钟后再收到「利空葡萄牙 −12pp」，而场上什么都没发生。
    """
    for oc, (delta, ref) in ds.items():
        if abs(delta) < CONFIRM_MIN_PP or oc not in cur:
            continue
        if (cur[oc] - ref) / delta >= CONFIRM_KEEP:
            return True
    return False
