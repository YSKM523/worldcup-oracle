"""共享统计工具: 置换检验相关 / 残差化 / Wilson CI。全脚本统一从这里 import。"""
import numpy as np
from scipy import stats

RS = np.random.RandomState(42)   # 固定种子, 全研究可复现


def perm_corr(x, y, method="spearman", n=20000):
    """相关系数 + 置换 p 值(双尾)。向量化: Spearman=秩上的Pearson, 一次性置换。"""
    x = np.asarray(x, float); y = np.asarray(y, float)
    m = ~(np.isnan(x) | np.isnan(y)); x, y = x[m], y[m]
    k = len(x)
    if k < 5: return np.nan, np.nan, k
    if method == "spearman":
        x = stats.rankdata(x); y = stats.rankdata(y)
    xc = x - x.mean(); yc = y - y.mean()
    den = np.sqrt((xc**2).sum() * (yc**2).sum())
    obs = float((xc * yc).sum() / den) if den > 0 else 0.0
    perms = np.array([RS.permutation(yc) for _ in range(n)])
    stat = perms @ xc / den
    p = (np.sum(np.abs(stat) >= abs(obs) - 1e-12) + 1) / (n + 1)
    return obs, float(p), k


def residualize(y, ctrl):
    """y 对 ctrl 线性回归取残差(扣掉 ctrl 的影响)。"""
    y = np.asarray(y, float); c = np.asarray(ctrl, float)
    m = ~(np.isnan(y) | np.isnan(c))
    b = np.polyfit(c[m], y[m], 1)
    r = np.full_like(y, np.nan); r[m] = y[m] - np.polyval(b, c[m])
    return r


def wilson(k, n, z=1.96):
    """比例的 Wilson 95% CI -> (p, lo, hi)。"""
    if n == 0: return (np.nan, np.nan, np.nan)
    p = k / n
    d = 1 + z*z/n
    c = (p + z*z/(2*n)) / d
    h = z*np.sqrt(p*(1-p)/n + z*z/(4*n*n)) / d
    return p, max(0, c-h), min(1, c+h)


def ci_mean(a):
    """均值 ± 1.96·SE -> (mean, lo, hi)。"""
    a = np.asarray(a, float); a = a[~np.isnan(a)]; n = len(a)
    if n < 2: return (np.nan, np.nan, np.nan)
    se = a.std(ddof=1) / np.sqrt(n)
    return a.mean(), a.mean() - 1.96*se, a.mean() + 1.96*se


def demean_by(df, col, grp):
    """按组去均值(固定效应)。"""
    return df[col] - df.groupby(grp)[col].transform("mean")


def np_json(o):
    """json.dump(default=...) 用的 numpy 转换器。"""
    if isinstance(o, np.integer): return int(o)
    if isinstance(o, np.floating): return float(o)
    if isinstance(o, np.ndarray): return o.tolist()
    raise TypeError(str(type(o)))
