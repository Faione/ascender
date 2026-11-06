# Ascend 开发镜像构建工具

使用本地材料构建 NPU 或 CAModel 仿真开发镜像。宿主机工具使用 Python 标准库，无第三方 Python 依赖；镜像使用单个多 target Dockerfile。镜像 tag 自动生成，不接受自定义。

工具不下载或上传材料，不安装宿主机驱动，不管理容器日常启停。APT/PIP 可在镜像构建过程中联网安装依赖；运行配置工具只生成 Compose 文件和账号副本。

## Quick Start

以下以构建 Ascend950DT 的 `simulation` 环境，并使用预构建的 mock / ops_transformer 安装包和 TTK 源码进行验证为例。在装有 Python 3.9+、Docker 和 Buildx 的机器上，进入本项目目录执行。安装包由对应项目在其他位置构建并交付，验证机器只需准备安装包和 TTK 源码。

**1. 准备环境材料、验证材料和基础镜像。** 环境材料按原名保存到以下目录，具体文件名及下载入口见[材料目录](#材料目录)和[下载说明](docs/downloads.md)：

```text
/data/ascend-materials/
├── cann/       # CANN 9.1.0 Toolkit、950dt ops 的 .run 文件
├── torch/      # Torch 2.10.0+cpu、torch-npu 2.10.0.post4 的 cp310/x86_64 wheels
└── camodel/    # ESLMODEL 主包、同名 _config.zip；可选 init.sh/env.sh/check.sh
```

将本次验证的三个材料放在另一个工作目录中：

```text
/data/ascend-verify/
├── packages/
│   ├── mock/              # 预构建 mock 安装包及随包说明/依赖声明
│   └── ops_transformer/   # 预构建 ops_transformer 安装包及随包说明
└── ttk/                   # TTK 源码及其依赖声明
    └── validation/        # 本例约定的验证材料目录
        ├── cases.csv
        ├── assets/        # TTK 插件及其 golden 等资源
        └── target.json    # mock 包要求的目标配置
```

`mock/` 和 `ops_transformer/` 保存各项目实际交付的安装包，例如 `.whl`、`.run`，保留原名；目录不要求包含这两个项目的源码。业务依赖由对应项目的 requirements、项目元数据或安装入口维护，本工具不预置 mock / TTK 专用 Python 包。

TTK 所需插件/assets、golden、CSV 和 mock 目标配置应随上述安装包或 TTK 一同交付，并按其安装后的实际路径引用。普通算子 `.run` 不保证携带测试插件；若交付物缺少这些内容，需要由对应项目补齐发布材料，不能隐式依赖验证机器上的 ops_transformer 源码。环境中的型号、安装包支持的目标和 TTK 配置须配套，示例 `Ascend950DT` 不代表业务包已完成目标适配。

仿真包例如 `x86_64_ESLMODEL_Ascend950DT_123A1.zip` 及 `x86_64_ESLMODEL_Ascend950DT_123A1_config.zip`。无需提前解压或提供初始化脚本；工具内置运行库替换、软链接及 `set_env.sh` 生成。`--soc` 选择 ops 包；`--simu-soc` 选择 CANN simulator 子目录，省略时使用材料中解析的 SoC。`--esl-soc-version` 仅设置导出的 `ESL_SOC_VERSION`，如 `Ascend950DT`，不影响运行库查找。`ESL_HARDWARE_VERSION` 默认 `0x1000`，可通过 `--esl-hardware-version` 覆盖。

```bash
docker pull --platform linux/amd64 ubuntu:22.04
```

**2. 构建 simulation 镜像。** 工具自动选择环境材料并初始化 CAModel，成功后在终端输出 `Report:` 报告目录，其中的 `image-ref.txt` 用于下一步生成运行配置：

```bash
python3 build.py \
  --target simulation \
  --materials-root /data/ascend-materials
```

`build.py` 只消费基础环境材料并制作镜像，不接收代码目录、账号、设备或运行网络参数。业务安装包和 TTK 在下一步通过运行期挂载提供，不会被自动安装或复制进基础镜像。业务安装包的依赖、格式和完整性检查由各自项目处理。

首次使用可先在上述命令末尾追加 `--check --files-only` 快速检查材料，或追加 `--check` 同时检查 Docker；默认不扫描全文件 SHA-256 和 ZIP CRC。需要深度检查时再追加 `--strict`，例如 `--check --files-only --strict`。检查通过后移除检查选项进行构建。若已准备仿真自检脚本，可追加 `--camodel-check check.sh`。

APT/PIP 默认共用 `http://mirrors.tools.huawei.com`，分别使用 `/ubuntu` 和 `/pypi/simple`。切换到采用相同路径布局的源时，只需追加 `--mirror-url https://mirror.example.com`；URL 仅包含协议、主机及可选端口。

版本和型号参数均可省略，未指定时直接从目录内唯一候选的文件名识别完整值。需要筛选某个版本时可用 `--torch-version` / `--torch-npu-version`：先精确匹配，再按基础版本匹配后缀，例如 `2.10.0` 可解析为 `2.10.0+cpu` 或 `2.10.0.post4`。存在多个候选时输出 `WARNING`、列出候选并停止；可指定完整版本或 `--torch-wheel` / `--torch-npu-wheel` 精确路径。需要关闭基础版本匹配时追加 `--strict-versions`。

SoC 同样先精确匹配。若没有 `950` 的 ops 包且只有 `950dt` 或 `950pr` 中的一种，`--soc 950` 会采用该具体型号；两种都存在时告警并停止，需要指定 `--soc 950dt` / `--soc 950pr` 或 `--ops FILE`。实际型号显示在终端并记录到报告，镜像 tag 仍保留输入的 `950`；`--strict-soc` 可关闭型号回退。

**指定不同的 CAModel：** 在构建命令中追加两次 `--camodel-archive`，分别指定需要的主包和配置包，例如另一套包名为 `x86_64_ESLMODEL_Ascend950DT_456B2.zip` 和 `x86_64_ESLMODEL_Ascend950DT_456B2_config.zip`（以实际供应方文件为准）。相对路径以 `/data/ascend-materials/camodel/` 为基准；包位于其他目录时，直接使用绝对路径：

```text
--camodel-archive /data/models/456B2/x86_64_ESLMODEL_Ascend950DT_456B2.zip
--camodel-archive /data/models/456B2/x86_64_ESLMODEL_Ascend950DT_456B2_config.zip
```

显式指定后只使用这两个包，忽略目录内其他 ZIP。省略全部 `--camodel-archive` 时自动查找 `camodel/*ESLMODEL*.zip`，该目录必须只有一套主包/配置包。镜像 tag 按软件版本生成；同版本下切换 CAModel 会更新同一个 tag，具体材料由报告和镜像 ID 区分，`--strict` 额外记录内容指纹。

切换 CAModel 时同时核对 `--soc`、`--simu-soc`、`--esl-soc-version` 和 `--esl-hardware-version` 是否适用于新包。仅有额外定制需求时再添加 `--camodel-init /data/models/456B2/init.sh`、`--camodel-env /data/models/456B2/env.sh` 或 `--camodel-check /data/models/456B2/check.sh`。这些都是可选文件，默认从材料根目录的 `camodel/` 读取，不会随 ZIP 的绝对路径自动切换。

构建和运行 simulation 环境均无需 NPU 设备。NPU 目标的独立构建命令见[构建](#构建)。

**3. 为已有镜像生成 Compose。** 在目标 Docker 服务器上，以拥有 `/data/ascend-verify` 读写权限、可访问 Docker 的普通开发用户执行。把下面的 `build/run-001` 替换为上一步 `Report:` 输出的实际目录；镜像须已存在于该服务器的本地 Docker 中：

```bash
python3 prepare_runtime.py \
  --image-ref-file build/run-001/image-ref.txt \
  --code-dir /data/ascend-verify \
  --output-dir /data/ascend-runtime \
  --runtime-subnet 192.168.240.0/24
```

此命令生成 `/data/ascend-runtime/compose.yaml`、`home/` 和 `identity/`，并打印启动和进入命令；不重新构建镜像，也不启动容器。`--code-dir` 是整体挂载的验证工作目录，`--output-dir` 是运行配置和 HOME 的保存位置，重新生成时保留 HOME。更换工作目录或运行参数，只需重新执行此命令。

生成的 Compose 已写入具体镜像、绝对挂载路径、root 身份、设备和子网，不需要设置 `ASCEND_IMAGE`、`LOCAL_*`、`CODE_DIR` 等环境变量，也不需要 `.env` 或 `--env-file`。其中 `environment` 仅为容器设置固定的 HOME 和缓存目录。

仿真和 NPU 的 Compose 都显式使用 bridge 子网，默认 `192.168.240.0/24`。先确认目标服务器路由及已有 Docker 网络未占用该范围；有冲突时通过 `--runtime-subnet` 改为其他空闲私有 IPv4 网段，同时运行多个环境时为每个环境指定不同网段。此参数只用于 `prepare_runtime.py`，与构建时的 `--network` 无关。已有网络需先用原 Compose 执行 `down`，再生成新配置并 `up -d`，见[网络配置](docs/runtime.md#网络配置)。

**4. 启动并进入容器。** 使用上一步生成的配置：

```bash
docker compose -f /data/ascend-runtime/compose.yaml config
docker compose -f /data/ascend-runtime/compose.yaml up -d
docker compose -f /data/ascend-runtime/compose.yaml exec ascend bash
```

镜像需要已存在于目标服务器的本地 Docker 中。生成器不会启动容器；上面的 Compose 命令由用户执行。仿真和 NPU 的 Compose 均显式设置 `user: '0:0'`，容器及普通 `exec` 会话以 root 运行。另保留与宿主机 UID/GID 对应的 `developer` 账号记录，供按需切换身份，不影响默认 root 身份。容器中的验证材料路径为：

| 宿主机 | 容器内 |
| --- | --- |
| `/data/ascend-verify/packages/mock/` | `/workspace/code/packages/mock/` |
| `/data/ascend-verify/packages/ops_transformer/` | `/workspace/code/packages/ops_transformer/` |
| `/data/ascend-verify/ttk/` | `/workspace/code/ttk/` |
| `/data/ascend-runtime/home/` | `/workspace/home`（`$HOME`，可持久保存安装结果和缓存） |

**5. 在容器内安装业务包并运行 TTK。** 先按 mock 和 ops_transformer 安装包的发布说明安装、加载各自的环境脚本，使用 `$HOME` 下可写的安装目录。安装参数、vendor 和激活脚本路径以实际交付包为准；组合包已包含的组件按其说明处理。

TTK 使用自己的项目元数据或 requirements 安装依赖。例如交付的 TTK 支持 editable 安装时，在容器 Bash 中执行：

```bash
cd /workspace/code/ttk
python3 -m pip install --user -c /etc/ascend/core-constraints.txt -e .
```

这里的约束文件用于保持镜像已选择的 Torch/torch-npu 版本；若项目依赖与其冲突，应准备配套的环境材料。依赖包名及版本由业务项目声明，无需在 Ascender 构建命令中逐项添加。

以 aicore_mock 的 QFA 验证入口为例，完成业务包安装和环境激活后，按上面的 `validation/` 布局执行。`SIM_SOC` 必须替换为交付包实际支持的仿真器标识，`target.json` 使用业务项目提供、与之配套的配置；这些业务设置不会由 Ascender 的构建参数自动生成：

```bash
export SIM_SOC='<实际仿真器 SoC 标识>'
export QFA_METADATA_BACKEND=mock_aicpu
export QFA_METADATA_CONFIG=/workspace/code/ttk/validation/target.json
source /etc/ascend/camodel-env.sh

cd /workspace/code/ttk
python3 -m ttk e2e \
  --backend npusim --sim-soc "$SIM_SOC" \
  -i /workspace/code/ttk/validation/cases.csv \
  --plugin /workspace/code/ttk/validation/assets \
  --golden-mode Enable
```

重新加载 CAModel 环境是为了在业务环境激活后保持其库目录位于 `LD_LIBRARY_PATH` 首位。上述路径均使用容器内路径；更换业务安装包后按其发布说明重新安装，基础环境仍配套时可复用同一镜像。

更多参数通过 `python3 build.py --help`、`python3 prepare_runtime.py --help` 查看；权限及 NPU 设备配置见[运行配置说明](docs/runtime.md)。

## 使用前准备

- 宿主机：Python 3.9+，支持 Linux/macOS；无需 pip 安装、虚拟环境、unzip、sha256sum、awk 或 sed。
- 实际构建：Docker 和 Buildx；当前本地 context 使用 Unix socket，Engine builder 使用 `docker` driver，基础镜像已在同一 Engine 中。跨架构执行能力由用户准备。
- 当前镜像平台：Ubuntu 22.04 / linux/amd64 / 容器 Python 3.10。CANN、SoC、Torch 和 torch-npu 从实际材料识别，下面的文件名只是示例。
- 构建镜像无需 NPU。生成 NPU 运行配置时，应在具备设备和驱动的目标服务器执行；仿真目标不需要这些资源。

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
| `--simu-soc NAME` | 匹配 CANN 的 `simulator/<NAME>` 子目录，如 `Ascend950DT`；支持大小写和 `Ascend` 前缀别名。默认使用材料解析后的 SoC，也可通过 `ASCEND_DEV_SIMU_SOC` 设置 |
| `--esl-hardware-version VALUE` | `0x1000`；也可用 `ASCEND_DEV_ESL_HARDWARE_VERSION` 设置，CLI 优先 |
| `--esl-soc-version NAME` | 仅设置导出的 `ESL_SOC_VERSION`，如 `Ascend950DT`，不参与运行库查找。默认使用按 `--simu-soc` 匹配到的目录名；可通过 `ASCEND_DEV_ESL_SOC_VERSION` 配置 |
| `--cann-install-dir DIR` | **镜像内** CANN 安装根目录；默认使用已加载的 `ASCEND_HOME_PATH` / `ASCEND_TOOLKIT_HOME`，未设置时检查标准安装位置 |
| `--camodel-lib-dir DIR` | 默认在 `/opt/CAModel` 下查找唯一包含 `libnpu_drv_camodel.so` 的目录；相对路径以 `/opt/CAModel` 为基准，绝对路径也必须位于其中 |

例如需要显式指定镜像内 CANN 路径及 ZIP 内库目录时，可使用以下完整构建命令：

```bash
python3 build.py \
  --target simulation --soc 950dt --cann-version 9.1.0 \
  --torch-version 2.10.0 --torch-npu-version 2.10.0 \
  --materials-root /data/ascend-materials \
  --simu-soc Ascend950DT \
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
| `--check` | 快速检查材料和 Docker，显示自动 tag，不扫描内容哈希/ZIP CRC |
| `--check --files-only` | 快速检查材料并显示 tag，不访问 Docker，不扫描内容哈希/ZIP CRC |
| `--check --strict` | 计算材料 SHA-256、完整检查 ZIP CRC，检查 Docker，显示 tag 和构建指纹，不构建 |
| `--check --files-only --strict` | 严格检查材料并显示 tag，不访问 Docker，不计算依赖基础镜像 ID 的完整构建指纹 |

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
- 镜像 tag 优先使用用户通过 CLI 或环境变量输入的型号和版本，只有未输入的字段才从材料补齐。例如输入 `2.7.1`，tag 不会被选中文件的 `2.7.1.post5.dev20261111` 覆盖。Docker 构建参数、pip 约束、安装后校验及内容指纹仍使用实际完整版本；manifest 同时记录输入值和实际值。
- `2.7.1.post5.dev20261111` 等开发包可直接使用；Torch 与 torch-npu 的基础版本须一致。多个开发日期会列出候选，需要指定完整日期版本或文件路径。
- 通用相对路径以调用目录为基准；`--camodel-archive`、`--camodel-init`、`--camodel-env`、`--camodel-check` 的相对路径以 `ROOT/camodel/` 为基准，均支持绝对路径。
- `--mirror-url` 统一指定 APT/PIP 源，默认 `http://mirrors.tools.huawei.com`；APT 地址为 `URL/ubuntu`，PIP 地址为 `URL/pypi/simple`。仅接受 HTTP(S) 协议、主机和可选端口，允许末尾 `/`；不接受路径、凭据、查询串、片段或空白。原 `--apt-mirror`、`--pip-index` 已移除。
- PIP 源写入所有用户可读的 `/etc/pip.conf`，root、developer 和后续用户默认共享；HTTP 源同时写入对应的 `trusted-host`。不持久化 `PIP_INDEX_URL`，允许按 pip 的优先级覆盖。strict 构建检查 root 和非 root 均可读取源配置。
- `--apt-package vim --apt-package htop`、`--pip-package pytest --pip-package 'numpy<2'` 可重复。PIP 参数接受包名、extras 和版本约束，不接受直接 URL、VCS、markers 或选项；附加约束使用 `--pip-constraints`。
- `--post-install` 指定公共安装阶段执行的 Bash 脚本，先于 CAModel 初始化；strict 下在执行后校验核心版本。
- `build.py` 只制作镜像；`prepare_runtime.py` 独立接收 `--image-ref-file`、`--code-dir`、`--output-dir` 及账号、设备、驱动和子网参数，生成 Compose。运行配置参数不参与镜像命名和内容指纹。
- `--network none` 仅禁用 RUN 网络，当前不是完整离线安装方案。`--no-cache` 不删除全局缓存。

支持的环境变量为 `ASCEND_DEV_TARGET`、`ASCEND_DEV_SOC`、`ASCEND_DEV_CANN_VERSION`、`ASCEND_DEV_TORCH_VERSION`、`ASCEND_DEV_TORCH_NPU_VERSION`、`ASCEND_DEV_BASE_IMAGE`、`ASCEND_DEV_MATERIALS_ROOT`、`ASCEND_DEV_MIRROR_URL`、`ASCEND_DEV_SIMU_SOC`、`ASCEND_DEV_ESL_SOC_VERSION`、`ASCEND_DEV_ESL_HARDWARE_VERSION`（后三项仅仿真）。无 tag 配置变量。运行配置工具不依赖这些变量。

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
ascend-dev:npu-cann9.1.0-950-torch2.10.0-npu2.10.0
ascend-sim:sim-cann9.1.0-950-torch2.7.1-npu2.7.1
```

没有 `--tag` 或 `latest` 别名。tag 包含目标、CANN、SoC、Torch/torch-npu 版本，各字段优先使用输入值，未输入的字段才使用材料中的实际值。上面分别对应输入 `--torch-version 2.10.0 --torch-npu-version 2.10.0` 和 `--torch-version 2.7.1 --torch-npu-version 2.7.1`。若输入完整开发版本，tag 会保留 `.postN.dev日期`；`+` 转为 Docker 支持的 `_`。末尾不附加 Python 版本、架构或构建 ID。同一组命名字段再次构建会更新同一个 tag，具体材料和实际完整版本由构建报告、镜像 ID 及镜像的 `dev.ascend.input-fingerprint` 标签区分。

普通构建用随机 UUID 记录构建身份，无需扫描材料内容。仅 `--strict` 使用 SHA-256 内容指纹，参数（含仿真初始化设置）、材料、容器脚本、共享 ZIP/初始化模块和基础镜像 ID 参与指纹，完整值保存在报告和镜像标签中；材料绝对路径、报告目录、缓存和显示选项不参与。在线依赖源会变化，内容指纹不保证镜像逐字节可复现。

实际构建输出到 `build/<build-id>/`，可用 `--output-dir` 修改父目录：

- `manifest.txt`：实际完整版本、用户输入的 `requested_*` 字段、自动镜像名、构建 ID 或内容指纹、命名模式及校验状态。
- `materials.sha256`：仅 `--strict` 构建生成，按上下文逻辑路径记录材料 SHA-256；普通构建不生成此文件。
- `build.log`：Docker 构建输出。
- `result.txt`：退出码、失败阶段、镜像引用和 ID；材料检查失败也保留。
- 成功后生成 `image-ref.txt` 和 `installed-packages.txt`。`image-id.txt` 由 Docker 构建成功后写入，后续报告阶段仍可能失败；`image-ref.txt` 才是完整流程成功的标志。

仅 `--strict` 在输入复制到临时上下文后再次核对哈希，变化则失败。原始安装包通过只读 RUN mount 使用，不 COPY 进最终镜像。临时目录在成功、失败或中断时清理。镜像内包清单通过未启动的临时容器读取，不访问设备。

## 外部代码验证

镜像制作和运行配置使用两个独立命令。先用 `build.py` 构建镜像，再在目标服务器上用 `prepare_runtime.py` 读取构建报告中的 `image-ref.txt`，生成 Compose、HOME 和账号文件。构建镜像不检查业务代码、NPU 设备或宿主机驱动；生成 NPU 运行配置时才检查这些运行资源。

运行配置命令示例：

```bash
python3 prepare_runtime.py \
  --image-ref-file /data/build/run-001/image-ref.txt \
  --code-dir /data/operator-project \
  --output-dir /data/ascend-runtime

docker compose -f /data/ascend-runtime/compose.yaml config
docker compose -f /data/ascend-runtime/compose.yaml up -d
docker compose -f /data/ascend-runtime/compose.yaml exec ascend bash
```

脚本仍按当前用户的 UID/GID 准备 `developer` 账号记录，支持显式切换身份时查询用户名；`--uid`、`--gid`、`--user` 只配置该账号，不改变 Compose 的 root 运行身份。生成的 Compose 使用具体值，无需 export、`.env` 或 `--env-file`。NPU 自动读取设备 GID 并加入只读驱动挂载；仿真不依赖设备和驱动。已有配置需重新生成并执行 `docker compose -f /data/ascend-runtime/compose.yaml up -d --force-recreate` 才生效。详见 [运行配置说明](docs/runtime.md)。

## 模块与开发检查

模块职责、依赖方向和替换方式见 [设计说明](DESIGN.md)。宿主机不再保留旧 Bash 入口；容器内 Bash 继续用于安装器和供应方环境脚本。

```bash
python3 -m unittest discover -s tests -v
python3 -m compileall -q ascender build.py prepare_runtime.py
for script in scripts/*.sh; do bash -n "$script" || exit; done
```

测试使用标准库、ZIP 样本和 Docker 替身，不下载、不安装真实组件。ShellCheck 可选。测试不能替代实际 Docker/NPU/CAModel 验收。
