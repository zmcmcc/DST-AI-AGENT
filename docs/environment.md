# 本机环境（2026-09-25）

- macOS 26.3.1，Apple Silicon `arm64`；系统 `python3` 为 3.14.3。
- Steam 位于 `/Applications/Steam.app`，库位于 `/Users/zhangmeng/Library/Application Support/Steam`。
- DST 的 Steam app ID 为 `322330`，已安装 manifest build ID `24700692`；2026-09-25 实际启动日志显示游戏版本 `747465`。游戏目录为 Steam 库下的 `steamapps/common/Don't Starve Together/dontstarve_steam.app`。
- 游戏客户端与随包专服可执行文件均为 `x86_64` Mach-O；当前机器是 `arm64`。本次构建已实际启动，并进入独立测试世界。
- 当前游戏脚本位于应用包的 `Contents/data/databundles/scripts.zip`。其中 `scripts/modutil.lua` 提供 `AddPlayerPostInit`，现有游戏代码包含 `TheSim:QueryServer(url, callback, method, body)` 的 POST 用法。
- 本地 Mod 目录为应用包的 `Contents/mods`；随包 `MAKING_MODS.txt` 说明可在此放置本地 Mod，并从游戏的 Mod 菜单启用。
- 用户数据位于 `/Users/zhangmeng/Documents/Klei/DoNotStarveTogether`。其中已有客户端数据；本项目尚未改动该目录或任何世界。
- Steam Workshop 目录中已有若干订阅 Mod。当前启用状态未核实；P0 测试世界应只启用探针，便于判断结果。
- 当前 `/Users/zhangmeng/.codex/projects` 中没有发现本项目已有仓库或 `AGENTS.md`。

`build ID` 来自 Steam manifest；游戏版本来自本次 `client_log.txt` 的启动记录。
