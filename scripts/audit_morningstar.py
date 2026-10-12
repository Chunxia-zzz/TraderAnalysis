"""
晨星公允价值核对：对比 DB 存值 vs 富途 API 实时值
用法: python scripts/audit_morningstar.py [code1 code2 ...]
      不带参数则核对默认抽样清单
"""
import sys, os, json, subprocess, sqlite3, time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB_PATH = os.path.join(ROOT, 'data', 'indicators.db')
SKILL_SCRIPTS = r"C:\Users\Administrator\.claude\skills\futuapi\scripts\quote"
MS_SCRIPT = os.path.join(SKILL_SCRIPTS, 'get_research_morningstar_report.py')

DEFAULT_CODES = [
    'US.TMUS', 'US.APH', 'US.BABA', 'US.AVGO', 'US.PEP', 'US.INTC',
    'US.YUMC', 'US.MSFT', 'US.NVDA', 'US.AAPL', 'US.GOOGL', 'US.AMZN',
    'US.META', 'US.TSLA', 'US.TSM', 'US.ASML', 'US.MSTR', 'US.CRCL',
]

# ETF/ETN 无基本面数据，跳过（与 scripts/fetch_fundamental_targets.py 保持一致）
ETF_CODES = {
    'US.QQQ', 'US.SPY', 'US.GLD', 'US.IBIT', 'US.GDXU', 'US.YINN',
    'US.KORU', 'US.MAGS', 'US.EUV', 'US.FOTO', 'US.EWY', 'US.EWJ',
    'US.EWT', 'US.SOXX', 'US.SOXL', 'US.DRAM', 'US.BMNR',
    'HK.07709',
    'US.XLK', 'US.XLF', 'US.XLV', 'US.XLC', 'US.XLY', 'US.XLP',
    'US.XLE', 'US.XLI', 'US.XLU', 'US.XLB', 'US.XLRE',
    'US.GDX', 'US.SLV', 'US.URA',
}


def api_fv(code):
    """返回 (fair_value, star, update_time_str, err)"""
    try:
        r = subprocess.run([sys.executable, MS_SCRIPT, code, '--json'],
                           capture_output=True, text=True, timeout=40,
                           encoding='utf-8', errors='replace')
        line = None
        for ln in (r.stdout or '').split('\n'):
            ln = ln.strip()
            if ln.startswith('{'):
                line = ln
                break
        if not line:
            return None, None, None, (r.stderr or 'no JSON')[:80]
        d = json.loads(line)
        data = d.get('data') or {}
        return (data.get('fair_value'), data.get('star_rating'),
                data.get('star_update_time_str'), None)
    except subprocess.TimeoutExpired:
        return None, None, None, 'timeout'
    except Exception as e:
        return None, None, None, str(e)[:80]


def db_rows(codes):
    c = sqlite3.connect(DB_PATH)
    out = {}
    for t in codes:
        r = c.execute('select morningstar_fair_value, updated_at from watchlist where code=?', (t,)).fetchone()
        out[t] = r
    # 最新 close
    closes = {}
    for t in codes:
        r = c.execute("select close, date from kline_indicators where code=? and ktype='1d' "
                      "order by date desc limit 1", (t,)).fetchone()
        closes[t] = r
    c.close()
    return out, closes


def write_back(pairs):
    """pairs: [(code, new_fv), ...] 写回 watchlist.morningstar_fair_value"""
    c = sqlite3.connect(DB_PATH)
    for code, fv in pairs:
        c.execute("UPDATE watchlist SET morningstar_fair_value=?, updated_at=datetime('now') "
                  "WHERE code=?", (fv, code))
    c.commit()
    c.close()
    return len(pairs)


def main():
    args = [a for a in sys.argv[1:] if not a.startswith('--')]
    if '--all' in sys.argv:
        c = sqlite3.connect(DB_PATH)
        all_codes = [r[0] for r in c.execute('select code from watchlist order by code')]
        c.close()
        codes = [t for t in all_codes if t not in ETF_CODES]
    else:
        codes = args or DEFAULT_CODES
    dbr, closes = db_rows(codes)
    print(f"核对 {len(codes)} 只标的（排除 ETF）")
    print(f"{'代码':<10} {'DB_FV':>9} {'API_FV':>9} {'差异':>9} {'DB更新':<12} {'晨星更新':<12} 现价")
    print('-' * 92)
    mismatch = []
    to_fix = []
    FIX = '--fix' in sys.argv
    for t in codes:
        fv, star, upd, err = api_fv(t)
        row = dbr.get(t)
        db_fv = row[0] if row else None
        db_upd = (row[1] or '')[:10] if row else '-'
        close_rec = closes.get(t)
        close = close_rec[0] if close_rec else None
        close_d = close_rec[1] if close_rec else '-'

        if err:
            print(f"{t:<10} {str(db_fv):>9} {'ERR':>9} {'':>9} {db_upd:<12} {err[:12]:<12} {close}")
            continue
        diff = None
        flag = ''
        if db_fv and fv:
            diff = (db_fv - fv) / fv * 100
            if abs(diff) > 1:
                flag = ' <<<'
                mismatch.append((t, db_fv, fv, diff, close))
                to_fix.append((t, fv))
        elif fv and not db_fv:
            flag = ' (DB空)'
            to_fix.append((t, fv))
        print(f"{t:<10} {str(db_fv):>9} {str(fv):>9} "
              f"{(f'{diff:+.1f}%' if diff is not None else '-'):>9} "
              f"{db_upd:<12} {str(upd or '-'):<12} {close} ({close_d}){flag}")
        time.sleep(1.2)

    print()
    print(f"=== 汇总：{len(codes)} 只中 {len(mismatch)} 只偏差 >1% ===")
    if mismatch:
        for t, d, a, p, c in mismatch:
            space_db = (d - c) / c * 100 if c else None
            space_api = (a - c) / c * 100 if c else None
            s = f"{t:<10} DB={d:<10} API={a:<10} 差异={p:+7.1f}%"
            if c:
                s += f"   上涨空间 DB口径={space_db:7.1f}%  API口径={space_api:7.1f}%  现价={c}"
            print(s)
        with open(os.path.join(ROOT, 'logs', 'morningstar_audit.json'), 'w', encoding='utf-8') as f:
            json.dump([{'code': t, 'db_fv': d, 'api_fv': a, 'diff_pct': round(p, 2), 'close': c}
                       for t, d, a, p, c in mismatch], f, ensure_ascii=False, indent=2)
        print(f"\n差异明细已写入 logs/morningstar_audit.json")
    else:
        print("全部一致（差异 ≤1%）")

    if FIX and to_fix:
        n = write_back(to_fix)
        print(f"\n✅ 已写回 watchlist.morningstar_fair_value：{n} 只")
    elif FIX:
        print("\n无需写回")
    elif to_fix:
        print(f"\n💡 加 --fix 参数可将以上 {len(to_fix)} 只刷新为 API 实时值")


if __name__ == '__main__':
    main()
