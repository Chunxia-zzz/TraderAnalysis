# 前端项目指南

> 最后更新：2026-03-28

本文记录 TraderAnalysis 前端项目的选型建议与架构规划，供新建前端仓库时参考。

---

## 一、项目定位

前端与后端（本仓库）**独立部署、独立 Git 仓库**。后端已提供标准 REST API，前端通过 HTTP 调用，两者通过 CORS 解耦。

**核心功能需求：**
- 静态概览页：持仓、信号汇总展示
- 动态查询页：输入标的代码 + 选择 K 线周期（日K/周K），展示 K 线图与技术指标

---

## 二、技术栈

| 层 | 选型 | 版本建议 | 理由 |
|----|------|----------|------|
| 框架 | **Vue 3** | 3.4+ | 上手快，Composition API 灵活，中文资料丰富 |
| 构建 | **Vite** | 5.x | 极快冷启动，零配置，官方推荐 |
| UI 组件 | **Ant Design Vue** | 4.x | 表单、下拉、表格开箱即用，风格专业 |
| 图表 | **LightweightCharts** | 4.x | TradingView 开源，专为金融 K 线设计，支持叠加指标线 |
| HTTP 请求 | **axios** | 1.x | 拦截器、错误处理完善 |
| 路由 | **Vue Router** | 4.x | 官方路由，支持懒加载 |

### 为什么选 LightweightCharts

- 原生支持蜡烛图（K 线）+ 折线叠加（均线/布林带）
- 后端 `/v1/indicators/latest` 和 `/v1/indicators/history` 返回的字段（open/high/low/close + sma/ema/bb）可以直接映射，几乎无需二次转换
- 体积小（~50KB gzip），渲染性能强，适合实时刷新场景
- MIT 开源，免费商用

---

## 三、推荐项目结构

```
trader-frontend/
├── public/
│   └── favicon.ico
├── src/
│   ├── api/
│   │   └── trader.js          # 封装所有对 TraderAnalysis API 的调用
│   ├── components/
│   │   └── KLineChart.vue     # LightweightCharts 封装组件（K线 + 指标叠加）
│   ├── views/
│   │   ├── Dashboard.vue      # 静态概览：信号汇总、最新指标
│   │   └── Chart.vue          # 动态查询：标的输入 + 周期选择 + 图表展示
│   ├── router/
│   │   └── index.js
│   ├── App.vue
│   └── main.js
├── index.html
├── vite.config.js
└── package.json
```

---

## 四、API 对接说明

后端 Base URL（本地）：`http://localhost:8000`

| 前端功能 | 调用的后端接口 |
|----------|---------------|
| K 线图数据（含指标） | `GET /v1/indicators/history?limit=N` |
| 最新指标数值展示 | `GET /v1/indicators/latest` |
| 最新信号（BUY/SELL/HOLD） | `GET /v1/signals/latest` |
| 服务状态 | `GET /health` |

后续接入富途实时行情后，接口路径不变，前端无需改动。

### api/trader.js 参考结构

```js
import axios from 'axios'

const client = axios.create({
  baseURL: import.meta.env.VITE_API_BASE_URL || 'http://localhost:8000',
  timeout: 10000,
})

export const getHealth       = ()              => client.get('/health')
export const getLatest       = ()              => client.get('/v1/indicators/latest')
export const getHistory      = (limit = 100)   => client.get('/v1/indicators/history', { params: { limit } })
export const getLatestSignal = ()              => client.get('/v1/signals/latest')
```

通过 `.env` 文件配置 API 地址，本地开发与生产环境无缝切换：

```bash
# .env.development
VITE_API_BASE_URL=http://localhost:8000

# .env.production
VITE_API_BASE_URL=https://your-api-server.com
```

---

## 五、后端需要的配套改动

### 1. 开启 CORS（本仓库 `app.py`）

```python
from fastapi.middleware.cors import CORSMiddleware

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173"],  # 生产环境改为实际前端域名
    allow_methods=["GET"],
    allow_headers=["*"],
)
```

### 2. 多标的支持（规划中）

前端动态查询需要按标的查询，后端需扩展 `?symbols=HK.00700` 参数支持，详见 `docs/architecture.md` 第三节。

---

## 六、初始化命令

```bash
# 新建项目
npm create vite@latest trader-frontend -- --template vue

cd trader-frontend
npm install

# 安装依赖
npm install axios ant-design-vue lightweight-charts vue-router

# 启动开发服务器（默认 localhost:5173）
npm run dev
```

---

## 七、部署建议

| 环境 | 方式 |
|------|------|
| 本地开发 | `npm run dev`，Vite 代理转发 API 请求 |
| 生产（推荐） | `npm run build` 产出 `dist/`，Nginx 托管静态文件，API 请求反向代理到后端 |
| 容器化 | 多阶段 Dockerfile：Node 构建 → Nginx 服务静态文件 |
