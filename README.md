# Free Nodes

[![Build subscriptions](https://github.com/XXS-pickle/node_engine/actions/workflows/build.yml/badge.svg)](https://github.com/XXS-pickle/node_engine/actions/workflows/build.yml)

[简体中文](#简体中文) | [English](#english)

## 简体中文

本项目自动整理、去重并测试节点订阅，通过 Mihomo 和 GitHub Pages 发布结果。Actions 每 3 小时运行一次，先用 2000ms TCP 预筛，再公平分配最多 3000 个候选，以 32 并发通过 Mihomo 访问 `https://www.gstatic.com/generate_204`，每节点超时 5000ms；只保留通过节点，名称统一添加 ` | tg@zzyyffxx`。

> 免费节点来自公开网络，可能随时失效、限速或被修改。请勿用于传输敏感信息，也不要将测速结果视为长期可用保证。

### 订阅地址

| 类型 | 订阅链接 | 说明 |
| --- | --- | --- |
| V2Ray | `https://XXS-pickle.github.io/node_engine/v2ray.txt` | Base64 编码订阅，适用于 v2rayN、v2rayNG 等客户端 |
| Clash / Mihomo | `https://XXS-pickle.github.io/node_engine/clash.yaml` | 完整 Clash/Mihomo 配置，包含自动延迟选择组 |
| 原始节点 | `https://XXS-pickle.github.io/node_engine/v2ray-raw.txt` | 未进行 Base64 编码的节点链接 |
| 测速报告 | `https://XXS-pickle.github.io/node_engine/report.json` | 运行统计和测试结果 |
| 状态页面 | `https://XXS-pickle.github.io/node_engine/` | 最近一次生成结果和节点列表 |

首次使用前，需要在仓库 `Settings → Pages` 中将发布来源设置为 **GitHub Actions**。Pages 尚未启用时，上述链接会返回 404。

### 主要功能

- 从多个公开订阅、文本文件或网页抓取节点
- 支持普通文本、Base64 订阅、HTML 中的节点链接和 Clash YAML
- 支持 `VLESS`、`VMess`、`Trojan`、`Shadowsocks`、`Hysteria2` 和 `TUIC`
- 按完整 Clash 连接配置去重，只忽略显示名称；密码、传输、TLS、Reality、插件和 `dialer-proxy` 不同的节点会保留
- 去重后先以 2000ms TCP 连接超时做预筛；仅 TCP 可达节点进入 Mihomo
- 按来源公平分配 Mihomo 名额，最多测试 3000 个候选，使用一个 Mihomo 实例、External Controller 和 32 并发
- 目标为 `https://www.gstatic.com/generate_204`，Mihomo 超时 5000ms，最终最多发布 300 个实测通过节点
- 报告记录每个来源的 fetched、parsed、deduped、tcp_alive、mihomo_tested、mihomo_alive；连续三次高量低转化来源会降权
- 单节点请求失败、TLS/握手失败或超时即删除；来源单独失败则跳过并继续抓取其他来源
- 保留来源节点名称；最终存活节点统一追加 ` | tg@zzyyffxx`，重名会在后缀前编号
- 每 3 小时自动运行一次，也支持在 Actions 页面手动运行
- Windows x64 随项目提供便携 Python 3.12、Python 依赖和 Mihomo，首次运行无需另外下载运行环境
- 生成 V2Ray、Clash/Mihomo、原始链接和 JSON 报告

### 客户端使用

节点必须满足“至少一个来源抓取成功、至少解析出一个节点、至少一个节点通过 Mihomo、最终 YAML 校验通过”才会发布。单个来源失败会记录为统计并继续；全部来源失败、没有解析结果、没有存活节点或 YAML 校验失败时，本次 Actions 失败并保留上一版 Pages 订阅。流程只上传 Pages artifact，不创建 Git commit，因此不会产生无变化的提交。

Actions 日志只保留来源/节点数量和运行时间统计，不输出来源 URL、UUID、密码、Token 或完整节点连接串。

V2Ray 客户端导入：

```text
https://XXS-pickle.github.io/node_engine/v2ray.txt
```

Clash/Mihomo 客户端导入：

```text
https://XXS-pickle.github.io/node_engine/clash.yaml
```

不同客户端对协议和传输方式的支持程度不同。如果某个节点在报告中可用，但客户端无法连接，请检查客户端内核版本以及对应协议支持情况。

### 测速设置

可在 [`.github/workflows/build.yml`](.github/workflows/build.yml) 中调整：

| 环境变量 | 默认值 | 用途 |
| --- | ---: | --- |
| `MAX_NODES` | `0` | `0` 表示对全部去重后的候选节点进行测试 |
| `MAX_OUTPUT_NODES` | `0` | `0` 表示发布全部通过测试的可用节点 |
| `TCP_PREFILTER_ENABLED` | `1` | 先做入口 TCP 预筛 |
| `TCP_CONNECT_TIMEOUT_SECONDS` | `2` | 单个入口端口连接超时 |
| `TCP_CONNECT_ATTEMPTS` | `1` | TCP 预筛尝试次数 |
| `MAX_MIHOMO_CANDIDATES` | `3000` | TCP 通过后按来源公平分配的 Mihomo 候选上限 |
| `MAX_OUTPUT_NODES` | `300` | 最终实测通过节点发布上限 |
| `TCP_PREFILTER_WORKERS` | `128` | 并发入口端口检测数量 |
| `ALIYUN_FC_URL` | Secret，可选 | 使用阿里云函数从杭州逐个复核入口端口；未配置时自动跳过 |
| `ALIYUN_FC_ENABLED` | `0` | 阿里云复核总开关；设置为 `1` 时启用 |
| `ALIYUN_FC_TIMEOUT_SECONDS` | `10` | 单次阿里云函数请求超时 |
| `ALIYUN_FC_WORKERS` | `10` | 阿里云复核最大并发请求数 |
| `ALIYUN_FC_INTERVAL_SECONDS` | `0.2` | 随机等待的中心值（配合抖动后为 0.1～0.3 秒） |
| `ALIYUN_FC_JITTER_SECONDS` | `0.1` | 随机等待抖动范围；请求仍保持串行 |
| `ALIYUN_FC_MAX_CONSECUTIVE_ERRORS` | `3` | 连续请求异常后停止远程检测并保留未检测节点 |
| `MAX_LATENCY_MS` | `5000` | 最大允许延迟，与 Mihomo 测试超时一致 |
| `LATENCY_TIMEOUT_MS` | `5000` | 单节点 Mihomo 代理请求超时 |
| `LATENCY_TEST_ATTEMPTS` | `1` | 每个节点只测一次；5 秒内失败即剔除 |
| `SOURCE_TIMEOUT_SECONDS` | `60` | 单个来源的连接/读取超时 |
| `SOURCE_RETRIES` | `3` | 来源临时连接失败时的额外重试次数 |
| `SOURCE_RETRY_BACKOFF_SECONDS` | `2` | 来源重试之间的递增等待秒数 |
| `FETCH_WORKERS` | `4` | 并发抓取来源数量，降低同一出口拥塞 |
| `MIN_SPEED_MBPS` | `0.1` | 仅在显式启用下载测速时使用；当前 Actions 默认关闭下载测速 |
| `GEOIP_TEST_URLS` | Cloudflare trace + country.is | 仅启用下载测速时用于记录出口 IP/国家信息 |
| `SPEED_TEST_ENABLED` | `0` | `0` 关闭下载测速；改成 `1` 可恢复测速和最低速度过滤 |
| `SPEED_TEST_LIMIT` | `0` | `0` 表示对全部延迟测试通过的节点执行下载测速 |
| `SPEED_TEST_BYTES` | `1000000` | 启用测速后每个节点下载约 1 MB，用于筛选而非精确带宽评测 |
| `SPEED_TIMEOUT_SECONDS` | `8` | 单个节点下载测速读取超时 |
| `BENCHMARK_WORKERS` | `48` | 并发延迟测试数量 |

构建调度器会先使用 `RUNNER_STATUS_TOKEN` 查询 Windows/X64 自托管 Runner：明确在线且空闲时立即使用本地 Runner；离线、忙碌、Token 缺失、权限不足、API 超时或返回异常时立即使用 GitHub 云端 Runner。本地任务执行失败时也会通过完成事件立即触发云端兜底，十分钟监控仅用于处理状态查询后电脑突然离线等极端情况。测速结果反映实际执行 Runner 所在网络到节点的质量。

`RUNNER_STATUS_TOKEN` 应保存为 Actions Secret，仅需为本仓库授予 `Administration: Read-only`，不要写入代码、日志或公开配置。

### 本地运行

Windows x64 已随项目提供便携 Python、依赖和 Mihomo。下载或克隆仓库后可以直接运行：

```powershell
powershell -ExecutionPolicy Bypass -File scripts/test_local.ps1
```

下载速度测试默认关闭。需要临时开启时运行：

```powershell
powershell -ExecutionPolicy Bypass -File scripts/test_local.ps1 -EnableSpeedTest
```

本地结果写入 `public-local/`，其延迟和速度更接近当前电脑运行 v2rayN 时的实际线路。便携运行时不需要联网安装 Python 包，但订阅抓取和节点检测仍然必须联网。

生成文件位于 `public/`。每次发布构建都必须运行 Mihomo；跳过实测会被拒绝。没有活节点或最终 Clash 配置校验失败时，不会替换上次成功的订阅。

### 项目说明

- 本项目不提供、出售或运营任何代理服务器
- 节点内容由上游公开来源提供，本项目只进行自动整理和测试
- 测速会产生真实代理流量，因此限制了并发量和下载大小
- 公开节点可能存在隐私、安全和可用性风险
- 请遵守所在地区法律、GitHub 服务条款以及节点提供方的使用规则

### 免责声明

本项目仅用于技术研究、网络测试和自动化学习。维护者不保证节点的真实性、安全性、速度或持续可用性，也不对使用这些节点造成的账号、数据、隐私、网络或法律风险承担责任。请只收集和发布你有权使用及再分发的来源。

---

## English

This repository automatically normalizes, deduplicates, and tests subscription nodes, then publishes the result through Mihomo and GitHub Pages. Every three hours, Actions runs a 2000 ms TCP prefilter, fairly allocates up to 3000 candidates, tests them through Mihomo with 32 workers against `https://www.gstatic.com/generate_204`, drops failures, and appends ` | tg@zzyyffxx` to surviving names.

> Public free nodes can disappear, slow down, or change without notice. Do not use them for sensitive traffic, and do not treat a successful CI test as a long-term availability guarantee.

### Subscription URLs

| Format | URL | Description |
| --- | --- | --- |
| V2Ray | `https://XXS-pickle.github.io/node_engine/v2ray.txt` | Base64 subscription for clients such as v2rayN and v2rayNG |
| Clash / Mihomo | `https://XXS-pickle.github.io/node_engine/clash.yaml` | Complete configuration with an automatic latency group |
| Raw links | `https://XXS-pickle.github.io/node_engine/v2ray-raw.txt` | Extracted node links without Base64 encoding |
| Benchmark report | `https://XXS-pickle.github.io/node_engine/report.json` | Runtime statistics and test results |
| Status page | `https://XXS-pickle.github.io/node_engine/` | Latest generated results and node table |

Before the first deployment, open `Settings → Pages` and select **GitHub Actions** as the publishing source. The URLs return 404 until Pages is enabled.

### Features

- Fetches multiple public subscriptions, text files, and webpages
- Accepts plain URI lists, Base64 subscriptions, HTML links, and Clash YAML
- Supports `VLESS`, `VMess`, `Trojan`, `Shadowsocks`, `Hysteria2`, and `TUIC`
- Deduplicates complete Clash connection maps, ignoring only the display name; credentials, transport, TLS, Reality, plugin, and `dialer-proxy` differences remain distinct
- Applies a 2000 ms TCP prefilter before Mihomo and allocates at most 3000 candidates fairly across sources
- Reuses one Mihomo instance and External Controller to test proxy requests against `https://www.gstatic.com/generate_204`, with 32 workers and a 5000 ms timeout
- Publishes at most 300 nodes that pass Mihomo; source quality counters are persisted between runs and low-yield sources are demoted after three runs
- Removes any node that fails the real Mihomo request; a single failed source is skipped while other sources continue
- Preserves source node names and appends ` | tg@zzyyffxx` to every surviving node name, numbering collisions before the suffix
- Runs every three hours and supports manual workflow dispatch
- Bundles portable Python 3.12, Python dependencies, and Mihomo for Windows x64 startup without initial runtime downloads
- Publishes V2Ray, Clash/Mihomo, raw-link, and JSON report outputs

### Usage

A publish requires at least one fetched source, at least one parsed node, at least one node that passes Mihomo, and a valid final YAML. Individual source failures are counted and skipped. If every source fails, parsing yields no nodes, Mihomo finds no live nodes, or final YAML validation fails, the run fails and the previous Pages subscription remains. Workflows deploy Pages artifacts without creating Git commits.

Action logs contain only source/node counts and runtime statistics; they do not print source URLs, UUIDs, passwords, tokens, or full connection strings.

Import one of these URLs into a compatible client:

```text
V2Ray: https://XXS-pickle.github.io/node_engine/v2ray.txt
Clash: https://XXS-pickle.github.io/node_engine/clash.yaml
```

Protocol and transport support varies between clients. A node that passes the CI benchmark can still fail on an older or incompatible client core.

### Benchmark Configuration

The main limits are configured in [`.github/workflows/build.yml`](.github/workflows/build.yml):

| Variable | Default | Purpose |
| --- | ---: | --- |
| `MAX_NODES` | `0` | No global prefix truncation before TCP screening |
| `MAX_OUTPUT_NODES` | `300` | Maximum published Mihomo-alive nodes |
| `MAX_MIHOMO_CANDIDATES` | `3000` | Fair per-source cap after TCP prefilter |
| `TCP_PREFILTER_ENABLED` | `1` | Run the TCP prefilter before Mihomo |
| `TCP_CONNECT_TIMEOUT_SECONDS` | `2` | Per-entry TCP connection timeout |
| `TCP_CONNECT_ATTEMPTS` | `1` | TCP prefilter attempts |
| `TCP_PREFILTER_WORKERS` | `128` | Concurrent entry-port checks |
| `ALIYUN_FC_URL` | Optional secret | Rechecks entry ports sequentially from Alibaba Cloud Hangzhou; skipped when unset |
| `ALIYUN_FC_ENABLED` | `0` | Master switch for Alibaba Cloud rechecks; set to `1` to enable |
| `ALIYUN_FC_TIMEOUT_SECONDS` | `10` | Timeout for each Alibaba Cloud function request |
| `ALIYUN_FC_WORKERS` | `10` | Maximum concurrent Alibaba Cloud recheck requests |
| `ALIYUN_FC_INTERVAL_SECONDS` | `0.2` | Center value for randomized delay (0.1–0.3 seconds with jitter) |
| `ALIYUN_FC_JITTER_SECONDS` | `0.1` | Randomized delay range; requests remain serial |
| `ALIYUN_FC_MAX_CONSECUTIVE_ERRORS` | `3` | Stops remote checks after consecutive request errors and preserves untested nodes |
| `MAX_LATENCY_MS` | `5000` | Maximum accepted latency, matching the Mihomo timeout |
| `LATENCY_TIMEOUT_MS` | `5000` | Per-node Mihomo proxy-request timeout |
| `LATENCY_TEST_ATTEMPTS` | `1` | One check per node; failures within the five-second window are removed |
| `SOURCE_TIMEOUT_SECONDS` | `60` | Per-source connection/read timeout |
| `SOURCE_RETRIES` | `3` | Extra retries for transient source failures |
| `SOURCE_RETRY_BACKOFF_SECONDS` | `2` | Increasing delay between source retries |
| `FETCH_WORKERS` | `4` | Concurrent source downloads to reduce congestion on one egress |
| `MIN_SPEED_MBPS` | `0.1` | Used only when download testing is explicitly enabled; Actions currently leave it disabled |
| `GEOIP_TEST_URLS` | Cloudflare trace + country.is | Used for exit-IP/country metadata only when download testing is enabled |
| `SPEED_TEST_ENABLED` | `0` | `0` disables download tests; set to `1` to restore speed filtering |
| `SPEED_TEST_LIMIT` | `0` | `0` tests every node that passes the latency check |
| `SPEED_TEST_BYTES` | `1000000` | Downloads about 1 MB per node when enabled, for screening rather than precise bandwidth benchmarking |
| `SPEED_TIMEOUT_SECONDS` | `8` | Per-node download read timeout |
| `BENCHMARK_WORKERS` | `32` | Concurrent Mihomo latency checks |

The dispatcher checks the Windows/X64 self-hosted runner with the `RUNNER_STATUS_TOKEN`. It immediately selects the local runner only when it is explicitly online and idle; an offline or busy runner, a missing or unauthorized token, an API timeout, or an invalid response immediately selects the GitHub-hosted runner. A failed local run triggers the cloud fallback through a completion event, while the ten-minute monitor remains only as a safety net for rare disconnects after routing. Results reflect the network of whichever runner performed the checks.

Store `RUNNER_STATUS_TOKEN` as an Actions secret with only `Administration: Read-only` access to this repository. Never commit or print the token.

### Local Development

Windows x64 includes portable Python, its dependencies, and Mihomo. After cloning or downloading the repository, run:

```powershell
powershell -ExecutionPolicy Bypass -File scripts/test_local.ps1
```

Local results are written to `public-local/`. The bundled runtime avoids initial Python-package and Mihomo downloads, while subscription fetching and node tests still require Internet access.

Generated subscriptions are staged before publication. `--skip-benchmark` is rejected; a run must parse nodes, pass at least one through Mihomo, and validate the final Clash file before replacing the previous output.

### Disclaimer

This repository is intended for technical research, network testing, and automation learning. It does not operate or sell proxy servers. No guarantee is made regarding node ownership, safety, privacy, speed, legality, or availability. Only fetch and redistribute sources you are authorized to use, and comply with local laws, GitHub's terms, and upstream providers' policies.

### References

- [Mihomo](https://github.com/MetaCubeX/mihomo)
