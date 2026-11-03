# Ascend 开发镜像构建工具

使用本地材料构建 NPU 或 CAModel 仿真开发镜像。宿主机工具使用 Python 标准库，无第三方 Python 依赖；镜像使用单个多 target Dockerfile。镜像 tag 自动生成，不接受自定义。

工具不下载或上传材料，不安装宿主机驱动，不管理容器日常启停。APT/PIP 可在镜像构建过程中联网安装依赖；运行配置工具只生成 Compose 文件和账号副本。

## Quick Start

以下以构建 Ascend950DT 的 `simulation` 目标为例。在装有 Python 3.9+、Docker 和 Buildx 的机器上，进入本项目目录执行，无需 `pip install`。

**1. 准备材料和基础镜像。** 下载并按原名保存到以下目录，具体文件名及下载入口见[材料目录](#材料目录)和[下载说明](docs/downloads.md)：

```text
/data/ascend-materials/
├── cann/       # CANN 9.1.0 Toolkit、950dt ops 的 .run 文件
├── torch/      # Torch 2.10.0+cpu、torch-npu 2.10.0.post4 的 cp310/x86_64 wheels
└── camodel/    # ESLMODEL 主包、同名 _config.zip；可选 init.sh/env.sh/check.sh
```

仿真包例如 `x86_64_ESLMODEL_Ascend950DT_123A1.zip` 及 `x86_64_ESLMODEL_Ascend950DT_123A1_config.zip`。无需提前解压或提供初始化脚本；工具内置运行库替换、软链接及 `set_env.sh` 生成。`ESL_SOC_VERSION` 使用 `Ascend950DT` 这样的型号字符串，`--esl-soc-version` 同时选择 CANN simulator 子目录；`ESL_HARDWARE_VERSION` 默认 `0x1000`，可通过 `--esl-hardware-version` 覆盖。

```bash
docker pull --platform linux/amd64 ubuntu:22.04
```

**2. 构建 simulation 镜像。** 工具自动读取目录中的唯一一套材料，识别 CANN 版本、SoC、Torch/torch-npu 完整版本及仿真包配对，随后解压到 `/opt/CAModel/` 并执行初始化：

```bash
python3 build.py \
  --target simulation \
  --materials-root /data/ascend-materials
```

首次使用可先在上述命令末尾追加 `--check --files-only` 快速检查材料，或追加 `--check` 同时检查 Docker；默认不扫描全文件 SHA-256 和 ZIP CRC。需要深度检查时再追加 `--strict`，例如 `--check --files-only --strict`。检查通过后移除检查选项进行构建。若已准备仿真自检脚本，可追加 `--camodel-check check.sh`。

APT/PIP 默认共用 `http://mirrors.tools.huawei.com`，分别使用 `/ubuntu` 和 `/pypi/simple`。切换到采用相同路径布局的源时，只需追加 `--mirror-url https://mirror.example.com`；URL 仅包含协议、主机及可选端口。

版本和型号参数均可省略，未指定时直接从目录内唯一候选的文件名识别完整值。需要筛选某个版本时可用 `--torch-version` / `--torch-npu-version`：先精确匹配，再按基础版本匹配后缀，例如 `2.10.0` 可解析为 `2.10.0+cpu` 或 `2.10.0.post4`。存在多个候选时输出 `WARNING`、列出候选并停止；可指定完整版本或 `--torch-wheel` / `--torch-npu-wheel` 精确路径。需要关闭基础版本匹配时追加 `--strict-versions`。

SoC 同样先精确匹配。若没有 `950` 的 ops 包且只有 `950dt` 或 `950pr` 中的一种，`--soc 950` 会采用该具体型号；两种都存在时告警并停止，需要指定 `--soc 950dt` / `--soc 950pr` 或 `--ops FILE`。解析结果显示在终端并用于镜像命名；`--strict-soc` 可关闭型号回退。

**指定不同的 CAModel：** 在构建命令中追加两次 `--camodel-archive`，分别指定需要的主包和配置包，例如另一套包名为 `x86_64_ESLMODEL_Ascend950DT_456B2.zip` 和 `x86_64_ESLMODEL_Ascend950DT_456B2_config.zip`（以实际供应方文件为准）。相对路径以 `/data/ascend-materials/camodel/` 为基准；包位于其他目录时，直接使用绝对路径：

```text
--camodel-archive /data/models/456B2/x86_64_ESLMODEL_Ascend950DT_456B2.zip
--camodel-archive /data/models/456B2/x86_64_ESLMODEL_Ascend950DT_456B2_config.zip
```

显式指定后只使用这两个包，忽略目录内其他 ZIP。省略全部 `--camodel-archive` 时自动查找 `camodel/*ESLMODEL*.zip`，该目录必须只有一套主包/配置包。普通构建每次生成新的构建 ID；`--strict` 构建使用内容指纹，包内容变化会改变 tag。

切换 CAModel 时同时核对 `--soc`、`--esl-soc-version` 和 `--esl-hardware-version` 是否适用于新包。仅有额外定制需求时再添加 `--camodel-init /data/models/456B2/init.sh`、`--camodel-env /data/models/456B2/env.sh` 或 `--camodel-check /data/models/456B2/check.sh`。这些都是可选文件，默认从材料根目录的 `camodel/` 读取，不会随 ZIP 的绝对路径自动切换。

构建和运行 simulation 环境均无需 NPU 设备。NPU 目标的独立构建命令见[构建](#构建)。

**3. 生成运行配置并进入容器。** 构建成功后打印 `Report: ...`，该目录中的 `image-ref.txt` 保存自动生成的镜像名。将下面的 `/path/to/report/image-ref.txt` 替换为实际文件，`/data/operator-project` 替换为已存在、可读写的待验证代码目录。在目标 Docker 服务器上以开发用户执行：

```bash
python3 prepare_runtime.py \
  --image-ref-file /path/to/report/image-ref.txt \
  --code-dir /data/operator-project \
  --output-dir /data/ascend-runtime

docker compose -f /data/ascend-runtime/compose.yaml config
docker compose -f /data/ascend-runtime/compose.yaml up -d
docker compose -f /data/ascend-runtime/compose.yaml exec ascend bash
```

镜像需要已存在于目标服务器的本地 Docker 中。生成器不会启动容器；后面的 Compose 命令由用户执行。默认映射当前 UID/GID，用户名为 `developer`，源码挂载到 `/workspace/code`，可写 HOME 为 `/workspace/home`，无需 export 环境变量。

更多参数通过 `python3 build.py --help`、`python3 prepare_runtime.py --help` 查看；权限及 NPU 设备配置见[运行配置说明](docs/runtime.md)。

## 使用前准备

- 宿主机：Python 3.9+，支持 Linux/macOS；无需 pip 安装、虚拟环境、unzip、sha256sum、awk 或 sed。
- 实际构建：Docker 和 Buildx；当前本地 context 使用 Unix socket，Engine builder 使用 `docker` driver，基础镜像已在同一 Engine 中。跨架构执行能力由用户准备。
- 当前镜像平台：Ubuntu 22.04 / linux/amd64 / 容器 Python 3.10。CANN、SoC、Torch 和 torch-npu 从实际材料识别，下面的文件名只是示例。
- 构建主机无需 NPU。运行 NPU 容器时才需要目标服务器的设备和驱动。

工具检查目录材料的文件格式、配对、ABI、架构和版本一致性。真实镜像、NPU 和 CAModel 功能仍需在目标服务器验收。

## 材料目录

每个材料根目录保存一套配套材料，直接放进三个固定子目录，不增加版本、SoC 或架构目录层级：

```text
/data/ascend-materials/
├── cann/
│   ├── Ascend-cann-toolkit_9.1.0_linux-x86_64.run
│   └── Ascend-cann-950dt-ops_9.1.0_linux-x86_64.run
├── torch/                          # --no-torch 时不需要
│   ├── torch-2.10.0+cpu-cp310-cp310-manylinux_2_28_x86_64.whl
│   └── torch_npu-2.10.0.post4-cp310-cp310-manylinux_2_28_x86_64.whl
└── camodel/                        # 仅仿真目标读取
    ├── x86_64_ESLMODEL_Ascend950DT_123A1.zip
    ├── x86_64_ESLMODEL_Ascend950DT_123A1_config.zip
    ├── init.sh                     # 可选：内置初始化后的额外操作
    ├── env.sh                      # 可选：运行期环境
    └── check.sh                    # 可选：显式启用的仿真自检
```

根目录名称和位置不限，文件保持供应方原名，无需提前解压。不同版本组合使用不同材料根目录。默认根目录为调用目录下的 `./materials`，推荐大文件放在仓库外并显式指定 `--materials-root`。

下载入口、基础镜像准备和仿真脚本要求见 [安装材料获取与保存](docs/downloads.md)。基础镜像通过 Docker pull/load 手动准备，不放进材料目录。

## 构建

在项目目录执行 NPU 构建，型号与版本自动识别：

```bash
python3 build.py \
  --target npu \
  --materials-root /data/ascend-materials
```

仿真只需将 `--target` 改为 `simulation`，无需先构建 NPU 镜像：

```bash
python3 build.py \
  --target simulation \
  --materials-root /data/ascend-materials \
  --esl-soc-version Ascend950DT \
  --esl-hardware-version 0x1000 \
  --camodel-check check.sh
```

不需要自检时省略 `--camodel-check`，此时报告明确保留“仿真功能未验证”。只安装 CANN 时使用 `--no-torch`，同时省略所有 Torch 专用参数。查看完整参数：

```bash
python3 build.py --help
python3 prepare_runtime.py --help
```

仿真自动选择 `camodel/` 当前目录下的 `*ESLMODEL*.zip`，要求一对同名主包和 `_config.zip` 配置包。多个版本共存时必须通过重复的 `--camodel-archive FILE` 选定一对；文件名中的 `123A1` 不从 CANN 版本推导，也不推断它与 SoC 的兼容关系。

所有 ZIP 内容直接解压到 `/opt/CAModel/`，保留内部层级，不添加包名目录。同名目录合并，重复文件报错，保留可执行位；拒绝符号链接、路径穿越和文件/目录冲突。随后执行内置初始化，再运行可选的额外 `init.sh` 和显式指定的 `check.sh`。供应方扩展脚本只消费本地材料，不下载内容；额外运行期变量可放入 `env.sh`。

## CAModel 内置初始化

工具在镜像内自动完成以下操作，无需用户编写 `init.sh`：

1. 从 CANN 安装目录的 `x86_64-linux/simulator/<soc_version>/lib/libruntime_camodel.so` 复制运行库，替换 CAModel 库目录中的同名文件。
2. 在该库目录创建相对软链接 `libruntime.so -> libruntime_camodel.so`、`libascend_hal.so -> libnpu_drv_camodel.so`，替换已有同名文件或链接。
3. 在同一目录生成 `set_env.sh`，设置 `ASCEND_DEVICE_ID=0`、`ESL_HARDWARE_VERSION`（默认 `0x1000`）、`ESL_SOC_VERSION`（如 `Ascend950DT`），并将 CAModel 库目录放到 `LD_LIBRARY_PATH` 首位；重复加载不会重复追加该目录。
4. 镜像入口和普通 Bash 自动加载生成的脚本。可选 `env.sh` 先加载，内置设置最后加载，保证 CAModel 库目录优先。

| 参数 | 默认行为 |
| --- | --- |
| `--esl-hardware-version VALUE` | `0x1000`；也可用 `ASCEND_DEV_ESL_HARDWARE_VERSION` 设置，CLI 优先 |
| `--esl-soc-version NAME` | 型号字符串，如 `Ascend950DT`；同时设置 `ESL_SOC_VERSION` 和选择 CANN simulator 子目录。默认按解析后的 `--soc` 查找，再使用匹配目录名；可通过 `ASCEND_DEV_ESL_SOC_VERSION` 配置 |
| `--cann-install-dir DIR` | **镜像内** CANN 安装根目录；默认使用已加载的 `ASCEND_HOME_PATH` / `ASCEND_TOOLKIT_HOME`，未设置时检查标准安装位置 |
| `--camodel-lib-dir DIR` | 默认在 `/opt/CAModel` 下查找唯一包含 `libnpu_drv_camodel.so` 的目录；相对路径以 `/opt/CAModel` 为基准，绝对路径也必须位于其中 |

例如需要显式指定镜像内 CANN 路径及 ZIP 内库目录时，可使用以下完整构建命令：

```bash
python3 build.py \
  --target simulation --soc 950dt --cann-version 9.1.0 \
  --torch-version 2.10.0 --torch-npu-version 2.10.0 \
  --materials-root /data/ascend-materials \
  --esl-soc-version Ascend950DT \
  --esl-hardware-version 0x1000 \
  --cann-install-dir /usr/local/Ascend/cann \
  --camodel-lib-dir x86_64_ESLMODEL_Ascend950DT_123A1/lib \
  --camodel-archive x86_64_ESLMODEL_Ascend950DT_123A1.zip \
  --camodel-archive x86_64_ESLMODEL_Ascend950DT_123A1_config.zip
```

以上目录按实际安装及包内布局调整。缺少运行库、缺少驱动库或存在多个候选目录时，构建会显示期望路径或候选列表并停止。`--check --files-only` 只校验宿主机材料，CANN 安装后的运行库和解压后的库目录在镜像构建时检查。

`init.sh` 现在是可选扩展脚本：默认使用材料目录中存在的 `camodel/init.sh`，也可通过 `--camodel-init FILE` 指定；在内置初始化后、`/opt/CAModel` 下执行，已加载生成的仿真环境。未选择外部脚本时不会自动执行 ZIP 自带的 `init.sh`。脚本 `export` 不会持久化到父进程；需要长期生效的额外变量写入 `env.sh`。

## 预览和检查

在完整构建命令后追加以下选项：

| 选项 | 行为 |
| --- | --- |
| `--materials` | 显示下载入口和材料位置；文件缺失时也可使用 |
| `--dry-run` | 展示参数和材料选择，不访问 Docker、不写文件；tag 暂不计算 |
| `--check` | 快速检查材料和 Docker，不扫描内容哈希/ZIP CRC，不计算最终 tag |
| `--check --files-only` | 快速检查材料，不访问 Docker，不扫描内容哈希/ZIP CRC |
| `--check --strict` | 计算材料 SHA-256、完整检查 ZIP CRC，检查 Docker 并计算最终镜像名，不构建 |
| `--check --files-only --strict` | 执行严格材料检查，不访问 Docker，不计算依赖基础镜像 ID 的最终 tag |

`--materials`、`--dry-run`、`--check` 三种模式互斥。默认只根据文件名和文件属性定位材料，检查存在/非空、版本/ABI/架构及仿真包配对，不打开文件读取内容，不执行 ZIP 预检。`--strict` 才读取材料计算 SHA-256，并检查 ZIP 目录结构、路径/类型安全、跨包冲突及完整 CRC。镜像内实际解压仍执行路径检查及 Python 解压器自带的 CRC 检查。

`--strict` 用于 `--check` 或实际构建，与控制模糊匹配的 `--strict-versions`、`--strict-soc` 相互独立，不改变版本/型号选择。只有此选项启用材料内容校验；计算的 SHA-256 是本地内容指纹，并非上游来源认证。

普通构建直接复制材料并安装，不计算 SHA-256、不执行 ZIP 预检、不比对复制后的内容，也不执行显式的安装器 `--check`、`pip check` 和镜像功能验证。添加 `--strict` 才启用这些检查，并在构建结束时复核基础镜像 ID。安装器/解压器自身的错误处理仍随实际安装执行；显式指定的 `--camodel-check` 会按要求运行。

Python 依赖只按实际声明安装：Torch/torch-npu wheel 由 pip 解析依赖；CANN 安装前后比较 Python 包元数据，将新增或变更包的 `Requires-Dist` 写入 `/etc/ascend/cann-requirements.txt`，保留版本范围、extras 和环境条件，再交给 pip 安装。没有声明元数据的依赖无法自动推断，可通过 `--pip-package PACKAGE` 或 `--post-install` 补充。默认不预装 `build`、`pyyaml`、`pytest`、`dtype`、`psutil`，也不统一限制 `numpy<2`；若实际软件声明需要这些包，会按声明安装。

`finish-image.sh` 安装上述 CANN 依赖和 `--pip-package` 指定的包，配置 shell 环境及容器入口，保存构建清单。依赖列表为空时跳过 pip 安装。仅 `--strict` 调用 `verify-image.sh` 检查编译器、Python 依赖和普通用户环境；系统/Python 包清单在两种模式下都会记录。`requires ... which is not installed` 表示已安装包缺少依赖，strict 下的 `pip check` 会因此失败。构建失败时查看报告目录的 `build.log`，脚本会输出阶段、失败命令、行号和退出码。

## 参数规则

- 优先级：默认值 → 列出的 `ASCEND_DEV_*` 环境变量 → CLI；重复标量以最后一次为准，列表按顺序追加。CANN/SoC/Torch 版本参数未指定时，从材料目录自动识别；指定时作为文件筛选条件。多个候选会告警并停止。
- 统一布局仅支持 `ROOT/cann/`、`ROOT/torch/`、`ROOT/camodel/`，不递归。旧的 `--cann-root`、`--torch-root`、`--camodel-dir` 已移除。
- `--toolkit`、`--ops`、`--torch-wheel`、`--torch-npu-wheel` 可精确指定文件，优先于固定目录查找；仍校验原始文件名。多个匹配文件时报错。
- SoC 从指定 CANN 版本、linux/x86_64 的 ops 包名解析，大小写不敏感，输出统一小写。默认先精确匹配；纯数字型号（例如 `950`）可回退到紧随字母后缀的型号（例如 `950dt`、`950pr`），不会匹配 `9500` 或其他数字型号。多候选告警并停止；明确输入 `950dt` 时仅精确匹配，`--strict-soc` 对默认查找和显式 `--ops` 都禁用回退。
- Torch/torch-npu 默认优先匹配完整版本；无精确候选且输入为 `X.Y.Z` 时，允许匹配同一基础版本的 `.postN`、`.postN.devN`、`+local` 及其组合。例如 `2.7.1` 可匹配 `2.7.1.post5.dev20261111`。只在 cp310/x86_64 wheel 中选择，不跨基础版本、不自动选择 rc 或独立 `.devN` 包；已写出后缀的输入仍按完整版本匹配（`2.7.1.post5` 不会隐式匹配 `2.7.1.post5.dev20261111`）。
- 唯一候选会显示 `Resolved ... version: 输入 -> 完整版本`。多个候选输出 `WARNING` 并停止，不自动选择最大版本。完整版本仍对应多个平台构建时，使用精确 wheel 文件路径消除歧义。`--strict-versions` 关闭基础版本回退；它也适用于显式 wheel 路径。
- 镜像 tag、manifest、Docker 构建参数、pip 约束及安装后校验均使用文件中解析出的完整版本；`--strict` 下，自动识别、基础版本筛选和完整版本筛选选择相同文件时得到相同镜像名。
- `2.7.1.post5.dev20261111` 等开发包可直接使用；Torch 与 torch-npu 的基础版本须一致。多个开发日期会列出候选，需要指定完整日期版本或文件路径。
- 通用相对路径以调用目录为基准；`--camodel-archive`、`--camodel-init`、`--camodel-env`、`--camodel-check` 的相对路径以 `ROOT/camodel/` 为基准，均支持绝对路径。
- `--mirror-url` 统一指定 APT/PIP 源，默认 `http://mirrors.tools.huawei.com`；APT 地址为 `URL/ubuntu`，PIP 地址为 `URL/pypi/simple`。仅接受 HTTP(S) 协议、主机和可选端口，允许末尾 `/`；不接受路径、凭据、查询串、片段或空白。原 `--apt-mirror`、`--pip-index` 已移除。
- PIP 源写入所有用户可读的 `/etc/pip.conf`，root、developer 和后续用户默认共享；HTTP 源同时写入对应的 `trusted-host`。不持久化 `PIP_INDEX_URL`，允许按 pip 的优先级覆盖。strict 构建检查 root 和非 root 均可读取源配置。
- `--apt-package vim --apt-package htop`、`--pip-package pytest --pip-package 'numpy<2'` 可重复。PIP 参数接受包名、extras 和版本约束，不接受直接 URL、VCS、markers 或选项；附加约束使用 `--pip-constraints`。
- `--post-install` 指定公共安装阶段执行的 Bash 脚本，先于 CAModel 初始化；strict 下在执行后校验核心版本。
- `--network none` 仅禁用 RUN 网络，当前不是完整离线安装方案。`--no-cache` 不删除全局缓存。

支持的环境变量为 `ASCEND_DEV_TARGET`、`ASCEND_DEV_SOC`、`ASCEND_DEV_CANN_VERSION`、`ASCEND_DEV_TORCH_VERSION`、`ASCEND_DEV_TORCH_NPU_VERSION`、`ASCEND_DEV_BASE_IMAGE`、`ASCEND_DEV_MATERIALS_ROOT`、`ASCEND_DEV_MIRROR_URL`、`ASCEND_DEV_ESL_SOC_VERSION`、`ASCEND_DEV_ESL_HARDWARE_VERSION`（仅仿真）。无 tag 配置变量。运行配置工具不依赖这些变量。

## 材料识别与缺失提示

工具从 `cann/` 的 Toolkit 和 ops 文件名、`torch/` 的 wheel 文件名获取实际版本、型号和 ABI。唯一候选直接使用；多个候选需通过版本/型号参数或精确文件路径选择。Torch 与 torch-npu 的基础版本需要一致，Toolkit 与 ops 的 CANN 版本需要一致。版本范围由材料决定，原 `--allow-unverified` 参数已删除。

材料缺失时单独显示缺少的组件、期望文件名或版本/ABI/架构、搜索目录、当前不匹配的候选和修复参数，例如：

```text
Missing compatible wheel for torch_npu 2.7.1 (cp310/x86_64).
  Missing component: torch-npu wheel
  Expected: torch_npu version 2.7.1; Python cp310, ABI cp310, linux/manylinux x86_64
  Search location: /data/ascend-materials/torch
  Available candidates: none
  Action: provide the expected material at this location or select it explicitly with --torch-npu-version / --torch-npu-wheel.
```

CAModel 配对缺失会明确列出缺的是主包还是配置包，以及期望的 ZIP 文件名。空文件会报告具体路径；不可读文件在 strict 扫描或实际复制时报告错误。材料缺失或无效时应修复文件后重新执行检查。

## 自动命名与报告

名称示意：

```text
ascend-dev:npu-cann9.1.0-950-torch2.10.0_cpu-npu2.10.0.post4-py310-amd64-<ID12>
ascend-sim:sim-cann9.1.0-950-torch2.10.0_cpu-npu2.10.0.post4-py310-amd64-<ID12>
```

没有 `--tag` 或 `latest` 别名。普通构建的 `ID12` 来自随机 UUID，每次构建生成不同 tag，无需读取材料内容。`--strict` 下改用 SHA-256 指纹前 12 位，参数（含仿真初始化设置）、材料、容器脚本、共享 ZIP/初始化模块和基础镜像 ID 参与指纹；材料绝对路径、报告目录、缓存和显示选项不参与，相同基础镜像 ID 的引用别名得到同一个 tag。在线依赖源会变化，内容指纹不保证镜像逐字节可复现。

实际构建输出到 `build/<build-id>/`，可用 `--output-dir` 修改父目录：

- `manifest.txt`：参数、自动镜像名、构建 ID 或内容指纹、命名模式及校验状态。
- `materials.sha256`：仅 `--strict` 构建生成，按上下文逻辑路径记录材料 SHA-256；普通构建不生成此文件。
- `build.log`：Docker 构建输出。
- `result.txt`：退出码、失败阶段、镜像引用和 ID；材料检查失败也保留。
- 成功后生成 `image-ref.txt` 和 `installed-packages.txt`。`image-id.txt` 由 Docker 构建成功后写入，后续报告阶段仍可能失败；`image-ref.txt` 才是完整流程成功的标志。

仅 `--strict` 在输入复制到临时上下文后再次核对哈希，变化则失败。原始安装包通过只读 RUN mount 使用，不 COPY 进最终镜像。临时目录在成功、失败或中断时清理。镜像内包清单通过未启动的临时容器读取，不访问设备。

## 外部代码验证

在目标 Docker 服务器上以开发用户生成运行配置：

```bash
python3 prepare_runtime.py \
  --image-ref-file /data/build/run-001/image-ref.txt \
  --code-dir /data/operator-project \
  --output-dir /data/ascend-runtime

docker compose -f /data/ascend-runtime/compose.yaml config
docker compose -f /data/ascend-runtime/compose.yaml up -d
docker compose -f /data/ascend-runtime/compose.yaml exec ascend bash
```

UID/GID 默认来自当前用户，用户名默认为 `developer`。脚本准备可写 HOME 和容器账号副本，避免 `I have no name!`。生成的 Compose 使用具体值，无需 export、`.env` 或 `--env-file`。NPU 自动读取设备 GID 并加入只读驱动挂载；仿真不依赖设备和驱动。详见 [运行配置说明](docs/runtime.md)。

## 模块与开发检查

模块职责、依赖方向和替换方式见 [设计说明](DESIGN.md)。宿主机不再保留旧 Bash 入口；容器内 Bash 继续用于安装器和供应方环境脚本。

```bash
python3 -m unittest discover -s tests -v
python3 -m compileall -q ascender build.py prepare_runtime.py
for script in scripts/*.sh; do bash -n "$script" || exit; done
```

测试使用标准库、ZIP 样本和 Docker 替身，不下载、不安装真实组件。ShellCheck 可选。测试不能替代实际 Docker/NPU/CAModel 验收。
