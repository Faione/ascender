# 安装材料获取与保存

工具只消费本地文件；浏览器下载、上传到构建服务器以及基础镜像的 pull/load 均由用户执行。

## 基础镜像

在构建服务器手动准备 Ubuntu 22.04 amd64 镜像：

```bash
docker pull --platform linux/amd64 ubuntu:22.04
docker image inspect ubuntu:22.04
```

也可在其他机器准备镜像归档后，用 `docker load -i /path/to/ubuntu.tar` 导入。文件导入后的引用应与 `--base-image` 一致。工具不会自动拉取基础镜像；本地缺失直接失败。

## 首个参考组合

从参考仓库 README 整理以下文件名和直链。文件放到相应目录，不需要收集其他型号的 ops。直链未在本仓库执行下载验证，失效时从官方入口重新选择精确版本。

| 材料 | 下载入口或参考直链 | 保存目录（相对材料根） |
| --- | --- | --- |
| `Ascend-cann-toolkit_9.1.0_linux-x86_64.run` | [Toolkit](https://ascend-repo.obs.cn-east-2.myhuaweicloud.com/CANN/CANN%209.1.0/Ascend-cann-toolkit_9.1.0_linux-x86_64.run) | `cann/` |
| `Ascend-cann-950-ops_9.1.0_linux-x86_64.run` | [950 ops](https://ascend-repo.obs.cn-east-2.myhuaweicloud.com/CANN/CANN%209.1.0/Ascend-cann-950-ops_9.1.0_linux-x86_64.run) | 同上 |
| `torch-2.10.0+cpu-cp310-cp310-manylinux_2_28_x86_64.whl` | [CPU wheel](https://download.pytorch.org/whl/cpu/torch-2.10.0%2Bcpu-cp310-cp310-manylinux_2_28_x86_64.whl) | `torch/` |
| `torch_npu-2.10.0.post4-cp310-cp310-manylinux_2_28_x86_64.whl` | [torch-npu wheel](https://gitcode.com/Ascend/pytorch/releases/download/v26.1.0-pytorch2.10.0/torch_npu-2.10.0.post4-cp310-cp310-manylinux_2_28_x86_64.whl) | 同上 |
| CAModel 主包与 `_config.zip` 配置包、`init.sh`、可选 `env.sh` / 自检脚本 | 从实际模型/仿真供应方获取，不推断公开地址 | `camodel/` |

官方入口：[CANN](https://www.hiascend.com/developer/download/community/result?module=cann)、[PyTorch CPU wheels](https://download.pytorch.org/whl/cpu/torch/)、[torch-npu releases](https://gitcode.com/Ascend/pytorch/releases)。有官方校验和时应在准备材料时核对；本工具记录的是本地 SHA-256 指纹，不将其标为上游来源验证。

## 配套记录

核对日期：2026-10-28。软件组合来源：[Ascend/pytorch 官方版本配套](https://github.com/Ascend/pytorch/blob/master/COMPATIBILITY.md)。TorchNPU 产品发行版 26.1.0 对应此处安装包 `2.10.0.post4`，二者不能混用。

| CANN | Torch | torch-npu 安装包 | 容器 | 配套状态 | 真实镜像 / 设备 / 仿真验收 |
| --- | --- | --- | --- | --- | --- |
| 9.1.0 | 2.10.0+cpu | 2.10.0.post4 | Ubuntu 22.04、amd64、Python 3.10 | 软件版本 documented；CPU wheel 与系统为本工具首个候选输入 | 均未完成 |
| 9.1.0 | 不安装 | 不安装 | 同上 | CANN-only 首版候选 | 均未完成 |

SoC 型号由 ops 包和实际设备确定。`950` 是参考示例；接受其他 SoC 字符串不等于其驱动、编译和仿真已验证。未收录的软件组合需显式 `--allow-unverified`，CANN 命名/安装路径仍须落在工具支持范围内，不保证自动适配。

上表是实际安装的完整版本。命令行可写 `--torch-version 2.10.0 --torch-npu-version 2.10.0`，默认先精确匹配，无精确候选时尝试同一基础版本的 post/local 后缀；目录中分别只有上表对应的兼容 wheel 时，会自动解析成 `2.10.0+cpu`、`2.10.0.post4`。多候选会告警并停止，需要指定完整版本或精确 wheel 路径。配套检查使用解析结果，不会因输入简写跳过；`--strict-versions` 可禁用基础版本回退。

也支持 `.postN.devN` 开发包，例如 `torch_npu-2.7.1.post5.dev20261111-cp310-cp310-manylinux_2_28_x86_64.whl` 可由 `--torch-npu-version 2.7.1` 匹配。Torch 基础版本应同为 `2.7.1`；该组合未收录，需 `--allow-unverified`。多日期候选须选择完整版本，工具不自动选最新日期。

ops 安装包可使用实际型号文件名，例如 `Ascend-cann-950dt-ops_9.1.0_linux-x86_64.run`、`Ascend-cann-950pr-ops_9.1.0_linux-x86_64.run`。`--soc 950` 优先选择精确的 950 包，否则只在同一 CANN 版本和架构中匹配唯一的字母后缀型号；多个候选告警停止，可用 `--soc 950dt` 或 `--ops FILE` 明确选择。`--strict-soc` 禁用型号回退。

## 仿真脚本契约

- 将 `x86_64_ESLMODEL_Ascend950DT_123A1.zip` 与 `x86_64_ESLMODEL_Ascend950DT_123A1_config.zip` 保持原名放到 `ROOT/camodel/`。默认按文件名顺序查找 `*ESLMODEL*.zip`，要求一对同名主包/配置包；不递归、不选其他 ZIP。多套材料时使用两次 `--camodel-archive FILE` 明确选定一对，按参数顺序处理。型号和版本以实际供应方文件名为准，不从 CANN 版本推导。
- 所有 ZIP 内容直接解压到 `/opt/CAModel/`，保留包内目录，不另建包名目录。例如包内 `lib/model.so` 对应 `/opt/CAModel/lib/model.so`。跨包同名目录可合并，同名文件报错；可执行文件的执行位会保留；不接受目录穿越、绝对路径或 ZIP 内符号链接。
- `init.sh` 的工作目录为 `/opt/CAModel`，已加载 CANN，`CAMODEL_HOME=/opt/CAModel`。负责本地目录整理、链接或其他安装步骤，不应在其中补做下载。
- `env.sh` 设置运行期变量和搜索路径；可能被加载到用户 Bash 中，应适合重复进入，不执行安装、不依赖 root、不固定写 `/root`。
- 可选自检脚本检查该 CAModel 的最小运行任务，不以 `torch.npu.is_available()` 作为仿真判据。
- 需要非 root 运行时，将日志/缓存/输出指向用户可写目录。特殊安装树写入需求需针对实际 CAModel 配置，不能通过将整个安装目录改为任意用户可写解决。

## 目录约定

每个 `--materials-root` 对应一套配套材料，固定使用 `cann/`、`torch/`、`camodel/` 三个直接子目录。旧的版本/架构嵌套布局及目录参数已移除，完整目录树见 [README](../README.md#材料目录)。

通用精确文件参数可指向其他本地路径；文件名仍须包含正确的版本、SoC 和平台信息。仿真文件参数的相对路径均以 `ROOT/camodel/` 为基准。
