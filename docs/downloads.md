# 安装材料获取与保存

工具只消费本地文件；浏览器下载、上传到构建服务器以及基础镜像的 pull/load 均由用户执行。

## 基础镜像

在构建服务器手动准备 Ubuntu 22.04 amd64 镜像：

```bash
docker pull --platform linux/amd64 ubuntu:22.04
docker image inspect ubuntu:22.04
```

也可在其他机器准备镜像归档后，用 `docker load -i /path/to/ubuntu.tar` 导入。文件导入后的引用应与 `--base-image` 一致。工具不会自动拉取基础镜像；本地缺失直接失败。

## 下载入口与文件示例

从参考仓库 README 整理以下文件名和直链。文件放到相应目录，不需要收集其他型号的 ops。直链未在本仓库执行下载验证，失效时从官方入口重新选择精确版本。

| 材料 | 下载入口或参考直链 | 保存目录（相对材料根） |
| --- | --- | --- |
| `Ascend-cann-toolkit_9.1.0_linux-x86_64.run` | [Toolkit](https://ascend-repo.obs.cn-east-2.myhuaweicloud.com/CANN/CANN%209.1.0/Ascend-cann-toolkit_9.1.0_linux-x86_64.run) | `cann/` |
| `Ascend-cann-950-ops_9.1.0_linux-x86_64.run` | [950 ops](https://ascend-repo.obs.cn-east-2.myhuaweicloud.com/CANN/CANN%209.1.0/Ascend-cann-950-ops_9.1.0_linux-x86_64.run) | 同上 |
| `torch-2.10.0+cpu-cp310-cp310-manylinux_2_28_x86_64.whl` | [CPU wheel](https://download.pytorch.org/whl/cpu/torch-2.10.0%2Bcpu-cp310-cp310-manylinux_2_28_x86_64.whl) | `torch/` |
| `torch_npu-2.10.0.post4-cp310-cp310-manylinux_2_28_x86_64.whl` | [torch-npu wheel](https://gitcode.com/Ascend/pytorch/releases/download/v26.1.0-pytorch2.10.0/torch_npu-2.10.0.post4-cp310-cp310-manylinux_2_28_x86_64.whl) | 同上 |
| CAModel 主包与 `_config.zip` 配置包、可选 `init.sh` / `env.sh` / 自检脚本 | 从实际模型/仿真供应方获取，不推断公开地址 | `camodel/` |

官方入口：[CANN](https://www.hiascend.com/developer/download/community/result?module=cann)、[PyTorch CPU wheels](https://download.pytorch.org/whl/cpu/torch/)、[torch-npu releases](https://gitcode.com/Ascend/pytorch/releases)。有官方校验和时应在准备材料时核对；本工具仅在 `--strict` 下记录本地 SHA-256 指纹，不将其标为上游来源验证。

## 从目录识别版本

上表中的文件版本仅为命名及保存位置示例，不构成构建限制。每个材料根目录保存一套用户选择的材料。工具从 Toolkit 文件名读取 CANN 版本，再选择同版本的 ops；从 ops 读取 SoC，从 cp310/x86_64 wheels 读取完整 Torch/torch-npu 版本。多个候选会告警并要求明确选择。

型号和版本参数可全部省略；需要筛选时可指定 `--soc`、`--cann-version`、`--torch-version`、`--torch-npu-version`，或使用精确文件路径。Torch 与 torch-npu 基础版本应一致。文件选择规则不能代替实际安装与设备功能验证。

支持 post/local 及 `.postN.devN` 包。例如 `torch_npu-2.7.1.post5.dev20261111-cp310-cp310-manylinux_2_28_x86_64.whl` 可由目录自动识别，也可用 `--torch-npu-version 2.7.1` 筛选。多日期候选需要完整版本或文件路径；`--strict-versions` 禁用基础版本回退。

ops 安装包可使用实际型号文件名，例如 `Ascend-cann-950dt-ops_9.1.0_linux-x86_64.run`、`Ascend-cann-950pr-ops_9.1.0_linux-x86_64.run`。`--soc 950` 优先选择精确的 950 包，否则只在同一 CANN 版本和架构中匹配唯一的字母后缀型号；多个候选告警停止，可用 `--soc 950dt` 或 `--ops FILE` 明确选择。`--strict-soc` 禁用型号回退。

## 仿真脚本契约

- 将 `x86_64_ESLMODEL_Ascend950DT_123A1.zip` 与 `x86_64_ESLMODEL_Ascend950DT_123A1_config.zip` 保持原名放到 `ROOT/camodel/`。默认按文件名顺序查找 `*ESLMODEL*.zip`，要求一对同名主包/配置包；不递归、不选其他 ZIP。多套材料时使用两次 `--camodel-archive FILE` 明确选定一对，按参数顺序处理。型号和版本以实际供应方文件名为准，不从 CANN 版本推导。
- 所有 ZIP 内容直接解压到 `/opt/CAModel/`，保留包内目录，不另建包名目录。例如包内 `lib/model.so` 对应 `/opt/CAModel/lib/model.so`。跨包同名目录可合并，同名文件报错；可执行文件的执行位会保留；不接受目录穿越、绝对路径或 ZIP 内符号链接。
- 工具内置初始化：将 CANN `x86_64-linux/simulator/<soc_version>/lib/libruntime_camodel.so` 复制到 CAModel 库目录，创建 `libruntime.so` 和 `libascend_hal.so` 相对软链接，并在同一目录生成 `set_env.sh`。默认通过唯一的 `libnpu_drv_camodel.so` 定位库目录；可用 `--camodel-lib-dir` 指定。
- 生成脚本设置 `ASCEND_DEVICE_ID=0`、`ESL_HARDWARE_VERSION=0x1000`、`ESL_SOC_VERSION=Ascend950DT`，并将库目录置于 `LD_LIBRARY_PATH` 首位。`--esl-soc-version` / `ASCEND_DEV_ESL_SOC_VERSION` 设置型号字符串并选择 CANN simulator 子目录；`--esl-hardware-version` / `ASCEND_DEV_ESL_HARDWARE_VERSION` 设置硬件版本（默认 `0x1000`）；`--cann-install-dir` 设置镜像内 CANN 根目录。未指定型号字符串时，按 `--soc` 查找后使用匹配目录名。
- `init.sh` 改为可选额外初始化，在内置初始化后执行；工作目录为 `/opt/CAModel`，CANN 和生成的仿真环境均已加载。不存在时无需提供；显式指定的脚本仍必须可读、非空，不应在其中补做下载。
- 可选 `env.sh` 设置额外运行期变量和搜索路径；内置 `set_env.sh` 最后加载以保持指定变量及 CAModel 库目录的优先级；可能被加载到用户 Bash 中，应适合重复进入，不执行安装、不依赖 root、不固定写 `/root`。
- 可选自检脚本检查该 CAModel 的最小运行任务，不以 `torch.npu.is_available()` 作为仿真判据。
- 需要非 root 运行时，将日志/缓存/输出指向用户可写目录。特殊安装树写入需求需针对实际 CAModel 配置，不能通过将整个安装目录改为任意用户可写解决。

## 目录约定

每个 `--materials-root` 对应一套配套材料，固定使用 `cann/`、`torch/`、`camodel/` 三个直接子目录。旧的版本/架构嵌套布局及目录参数已移除，完整目录树见 [README](../README.md#材料目录)。

通用精确文件参数可指向其他本地路径；文件名仍须包含正确的版本、SoC 和平台信息。仿真文件参数的相对路径均以 `ROOT/camodel/` 为基准。
