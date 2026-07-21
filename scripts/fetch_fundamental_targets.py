"""
批量拉取标的池的分析师目标价和晨星公允价值，写入 DB。
ETF/ETN 标的会跳过（无此类数据）。

用法: python scripts/fetch_fundamental_targets.py [--dry-run]
"""

import sys
import os
import json
import subprocess
import sqlite3
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

DB_PATH = os.path.join(os.path.dirname(__file__), '..', 'data', 'indicators.db')
SKILL_SCRIPTS = r"C:\Users\Administrator\.claude\skills\futuapi\scripts\quote"

# ETF/ETN 标的不拉基本面
ETF_CODES = {
    'US.QQQ', 'US.SPY', 'US.GLD', 'US.IBIT', 'US.GDXU', 'US.YINN',
    'US.KORU', 'US.MAGS', 'US.EUV', 'US.FOTO', 'US.EWY', 'US.EWJ',
    'US.EWT', 'US.SOXX', 'US.SOXL', 'US.DRAM', 'US.BMNR',
    'HK.07709',  # ETF
    # S&P 11 Sector ETFs
    'US.XLK', 'US.XLF', 'US.XLV', 'US.XLC', 'US.XLY', 'US.XLP',
    'US.XLE', 'US.XLI', 'US.XLU', 'US.XLB', 'US.XLRE',
    # Commodity ETFs
    'US.GDX', 'US.SLV', 'US.URA',
}


def get_all_codes():
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute('SELECT code, name FROM watchlist')
    rows = cur.fetchall()
    conn.close()
    return rows


def fetch_analyst_target(code):
    """调用 get_research_analyst_consensus.py 获取分析师平均目标价"""
    script = os.path.join(SKILL_SCRIPTS, 'get_research_analyst_consensus.py')
    try:
        result = subprocess.run(
            ['python', script, code, '--json'],
            capture_output=True, text=True, timeout=30, encoding='utf-8', errors='replace'
        )
        if result.returncode != 0:
            return None, result.stderr.strip()[:100]
        # JSON 可能混在 stderr 日志中，从 stdout 提取
        output = result.stdout.strip()
        # 找到 JSON 行（以 { 开头）
        json_line = None
        for line in output.split('\n'):
            line = line.strip()
            if line.startswith('{'):
                json_line = line
                break
        if not json_line:
            # 也检查 stderr 中的 JSON
            for line in result.stderr.split('\n'):
                line = line.strip()
                if line.startswith('{'):
                    json_line = line
                    break
        if not json_line:
            return None, "no JSON in output"
        data = json.loads(json_line)
        # 结构: {"code": "...", "data": {"average": 309.94, ...}}
        if 'data' in data and isinstance(data['data'], dict):
            avg = data['data'].get('average')
            if avg and float(avg) > 0:
                return float(avg), None
        return None, "no average field"
    except subprocess.TimeoutExpired:
        return None, "timeout"
    except (json.JSONDecodeError, Exception) as e:
        return None, str(e)[:100]


def fetch_morningstar_fair_value(code):
    """调用 get_research_morningstar_report.py 获取晨星公允价值"""
    script = os.path.join(SKILL_SCRIPTS, 'get_research_morningstar_report.py')
    try:
        result = subprocess.run(
            ['python', script, code, '--json'],
            capture_output=True, text=True, timeout=30, encoding='utf-8', errors='replace'
        )
        if result.returncode != 0:
            return None, result.stderr.strip()[:100]
        # 找到 JSON 行
        output = result.stdout.strip()
        json_line = None
        for line in output.split('\n'):
            line = line.strip()
            if line.startswith('{'):
                json_line = line
                break
        if not json_line:
            for line in result.stderr.split('\n'):
                line = line.strip()
                if line.startswith('{'):
                    json_line = line
                    break
        if not json_line:
            return None, "no JSON in output"
        data = json.loads(json_line)
        # 结构: {"code": "...", "data": {"fair_value": 280.0, ...}}
        if 'data' in data and isinstance(data['data'], dict):
            fv = data['data'].get('fair_value')
            if fv and float(fv) > 0:
                return float(fv), None
        return None, "no fair_value field"
    except subprocess.TimeoutExpired:
        return None, "timeout"
    except (json.JSONDecodeError, Exception) as e:
        return None, str(e)[:100]


def update_db(code, analyst_target, morningstar_fv):
    """更新 DB 中的字段"""
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    updates = []
    params = []
    if analyst_target is not None:
        updates.append("analyst_target_mean = ?")
        params.append(analyst_target)
    if morningstar_fv is not None:
        updates.append("morningstar_fair_value = ?")
        params.append(morningstar_fv)
    if updates:
        updates.append("updated_at = datetime('now')")
        sql = f"UPDATE watchlist SET {', '.join(updates)} WHERE code = ?"
        params.append(code)
        cur.execute(sql, params)
        conn.commit()
    conn.close()


def main():
    dry_run = '--dry-run' in sys.argv
    codes = get_all_codes()

    # 过滤掉 ETF
    stocks = [(code, name) for code, name in codes if code not in ETF_CODES]

    print(f"标的池共 {len(codes)} 只，排除 ETF 后 {len(stocks)} 只需要拉取")
    print("=" * 70)

    success_count = 0
    fail_count = 0

    for i, (code, name) in enumerate(stocks, 1):
        print(f"\n[{i}/{len(stocks)}] {code} ({name})")

        # 拉取分析师目标价
        analyst_target, err1 = fetch_analyst_target(code)
        if analyst_target:
            print(f"  分析师目标价: {analyst_target}")
        else:
            print(f"  分析师目标价: 无 ({err1})")

        # 拉取晨星公允价值
        morningstar_fv, err2 = fetch_morningstar_fair_value(code)
        if morningstar_fv:
            print(f"  晨星公允价值: {morningstar_fv}")
        else:
            print(f"  晨星公允价值: 无 ({err2})")

        # 写入 DB
        if not dry_run and (analyst_target or morningstar_fv):
            update_db(code, analyst_target, morningstar_fv)
            print(f"  -> 已写入 DB")
            success_count += 1
        elif analyst_target or morningstar_fv:
            print(f"  -> [DRY RUN] 不写入")
            success_count += 1
        else:
            fail_count += 1

        # 限频：避免触发 API 限制
        time.sleep(1)

    print("\n" + "=" * 70)
    print(f"完成！成功: {success_count}, 无数据: {fail_count}")


if __name__ == '__main__':
    main()
