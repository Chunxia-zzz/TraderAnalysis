@echo off
chcp 65001 > nul
cd /d F:\TraderAnalysis

echo [%date% %time%] 开始增量更新 K 线...
python -m trader_analysis update >> F:\TraderAnalysis\logs\local_cron.log 2>&1

echo [%date% %time%] 计算市场温度...
python -m trader_analysis temperature >> F:\TraderAnalysis\logs\local_cron.log 2>&1

echo [%date% %time%] 计算个股评分...
python -m trader_analysis score >> F:\TraderAnalysis\logs\local_cron.log 2>&1

echo [%date% %time%] 扫描交易信号（空转多/多转空 EMA 交叉）...
python -m trader_analysis scan-signals >> F:\TraderAnalysis\logs\local_cron.log 2>&1

echo [%date% %time%] 同步数据库到服务器...
scp F:\TraderAnalysis\data\indicators.db root@47.106.175.84:/opt/trader-analysis/data/indicators.db >> F:\TraderAnalysis\logs\local_cron.log 2>&1

echo [%date% %time%] 完成
